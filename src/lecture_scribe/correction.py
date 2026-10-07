"""전사 후 교정 제안 (F-09).

Whisper 전사가 끝난 뒤 로컬 LLM(Ollama의 gemma4)에게 **음성인식 오류로 보이는
구간**을 물어 교정 후보를 받는다. 원칙 두 가지:

1. **원문은 절대 고치지 않는다.** 교정은 `원문[→교정]` 형태의 주석으로만 붙는다.
   CLAUDE.md의 "축자 전사" 원칙을 지키면서도 읽는 사람이 오류를 알아볼 수 있다.
2. **LLM은 오디오를 듣지 못한다.** 그래서 제안은 전부 추정이고, 기계적으로
   검증 가능한 것만 통과시킨다(`validate_proposals`).

실측(2026-09-04, 전자회로 강의, 918자 소구간):

| 모델 | 제안 | 정답 | 정확도 | 소요 |
|---|---|---|---|---|
| gemma4:e4b | 9 | 8 | 89% | 33.5s / 918자 |
| gemma4:e2b | 7 | 5 | 71% | 19.7s / 918자 |

같은 모델도 프롬프트에 **주제·용어집**이 없으면 1/7까지 떨어진다(실측). 그래서
`build_prompt()`가 두 가지를 반드시 넣는다.

실측(2026-09-27, FIX_GUIDE_13 E-01/P-01, gemma4:e4b, 13.8분 강의 전체 정답 49건
기준, 3회 평균): 기준선 precision 0.56 / recall 0.22 / 108초. 채택한 두 가지:

- **한글 오인식도 대상에 포함**(기존 프롬프트는 영어 전문용어 오인식만 겨냥) →
  precision 0.57 / recall 0.36 / 125초.
- **청크 앞뒤 문맥**(교정 대상 아님, 참고만) 제공 → precision 0.68 / recall 0.29 /
  105초(문맥이 있으면 잘린 문장을 덜 잘못 읽어 오히려 시간 변화 없음).
- 둘 결합: precision 0.56 / recall 0.37 / 127초(기준선과 정밀도는 같고 재현율만
  오름 — 채택).

기각한 가설(precision 하락 또는 개선 없음): temperature 0, 스키마 필드 순서
변경(reason 먼저), few-shot 예시, "교정 안 함" 예시, 수식 표기 금지 규칙. 실험
스크립트는 `scripts/c_eval/`(정답 목록은 초안, 단일 강의라 과적합 가능성 있음).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Final

from .backends.base import Segment
from .errors import LectureScribeError
from .logsetup import get_logger

logger = get_logger(__name__)

#: Ollama 기본 주소. 환경변수 OLLAMA_HOST가 있으면 그쪽을 쓴다.
DEFAULT_HOST: Final[str] = "http://localhost:11434"

#: 구간을 도는 동안 모델을 붙잡아 두는 시간. 끝나면 명시적으로 내린다.
KEEP_ALIVE_DURING_RUN: Final[str] = "5m"

#: 선택 가능한 교정 모델. 실측 정확도는 모듈 docstring 참조.
CORRECTION_MODELS: Final[tuple[str, ...]] = ("gemma4:e4b", "gemma4:e2b")

#: 청크 경계에서 잘린 문장의 문맥으로 앞/뒤 청크에서 몇 세그먼트를 보여줄지.
CONTEXT_SEGMENTS: Final[int] = 3

#: 응답 형식(Ollama `format` 필드). 모델이 이 스키마를 따르도록 강제한다.
RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "original": {"type": "string"},
                    "correction": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                },
                "required": ["original", "correction", "reason", "confidence"],
            },
        }
    },
    "required": ["corrections"],
}

_CONFIDENCE_ORDER: Final[dict[str, int]] = {"low": 0, "medium": 1, "high": 2}

#: (현재 구간, 전체 구간)
ProgressHook = Callable[[int, int], None]
CancelHook = Callable[[], bool]

#: `ollama_available()`/`ensure_running()`가 PATH 앞에 먼저 뒤진다. GUI 번들
#: 프로세스는 PATH가 `/usr/bin:/bin:/usr/sbin:/sbin`뿐이라(실측) Homebrew로
#: 설치된 `ollama`(보통 `/opt/homebrew/bin`)를 `shutil.which`만으론 못 찾는다
#: — `audio.py find_binary()`가 ffmpeg에 쓰던 것과 같은 문제, 같은 해법.
_OLLAMA_SEARCH_DIRS: Final[tuple[Path, ...]] = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/opt/local/bin"),
    Path("/usr/bin"),
)


def find_ollama() -> Path | None:
    """Ollama 실행 파일 절대 경로. 없으면 None(에러를 던지지 않는다)."""
    for directory in _OLLAMA_SEARCH_DIRS:
        candidate = directory / "ollama"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("ollama")
    return Path(found) if found else None


def ollama_available() -> bool:
    """Ollama 실행 파일이 있는지. GUI 위젯 비활성화 판단용(데몬 기동은 하지 않는다)."""
    return find_ollama() is not None


def list_installed_gemma_models(client: "OllamaClient | None" = None) -> list[str]:
    """실제로 `ollama pull`돼 있는 gemma 계열 모델 이름을 전부 돌려준다.

    GUI 교정 모델 드롭다운이 `CORRECTION_MODELS`(gemma4:e4b/e2b) 고정 두 개만
    보여주던 걸 대신한다 — 사용자가 다른 버전(gemma2, gemma3, 다른 크기 등)을
    받아 뒀으면 그것도 보여야 한다.

    실패(Ollama 미설치, 데몬 꺼짐, 응답 오류)해도 예외를 던지지 않고 빈 목록을
    돌려준다 — 호출부가 `CORRECTION_MODELS` 고정 목록으로 대체한다.
    """
    if not ollama_available():
        return []
    active = client or OllamaClient()
    try:
        if not active.alive(1.0):
            return []
        names = active.models()
    except Exception:  # noqa: BLE001 - 점검 실패로 GUI 구성을 막으면 안 된다
        return []
    gemma = sorted({name for name in names if "gemma" in name.lower()})
    return gemma


def _model_stem(name: str) -> str:
    """`gemma4:e4b:latest`처럼 붙는 기본 태그(`:latest`)만 떼어낸다.

    첫 콜론까지만 자르면 `gemma4:e4b`와 `gemma4:e2b`가 둘 다 "gemma4"가 되어
    서로 다른 모델을 같다고 오판한다(실측 버그) — 그래서 `:latest` 접미사만
    벗긴다.
    """
    if name.endswith(":latest"):
        return name[: -len(":latest")]
    return name


class CorrectionUnavailableError(LectureScribeError):
    """Ollama가 없거나 모델이 준비되지 않았다. 교정만 건너뛰고 전사는 살린다."""


@dataclass(slots=True, frozen=True)
class Proposal:
    """교정 후보 1건."""

    original: str
    correction: str
    reason: str
    confidence: str
    segment_id: int | None = None
    start: float | None = None
    end: float | None = None
    context: str = ""
    segment_avg_logprob: float | None = None

    @property
    def rank(self) -> int:
        return _CONFIDENCE_ORDER.get(self.confidence, 0)


@dataclass(slots=True)
class CorrectionResult:
    """교정 단계 산출물."""

    proposals: list[Proposal] = field(default_factory=list)
    rejected: list[tuple[str, str, str]] = field(default_factory=list)  # (원문, 교정, 사유)
    model: str = ""
    elapsed_sec: float = 0.0
    chunks: int = 0
    skipped_reason: str | None = None
    #: 프롬프트에 실제로 넣은 슬라이드 OCR 용어(사이드카 기록용)
    slide_terms: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.skipped_reason is None


# --- 한글 음차 판별 --------------------------------------------------------
#
# 모델이 `화이트 → White`, `가우시안 → Gaussian`처럼 **이미 올바른 한국어 음차를
# 영어 철자로 바꾸는** 제안을 자주 낸다. 교정이 아니라 표기 변환일 뿐이라 걸러야
# 한다(실측: 한 구간에서 11건 중 3건이 이 유형).

_CHO: Final[str] = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JONG: Final[str] = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

#: 받침 ㅇ은 /ŋ/이라 영어 -ng에 대응한다. 빈 문자열로 버리면 `네트워킹 ~ networking`을
#: 놓친다(실측). 초성 ㅇ은 무음이므로 아래에서 따로 처리한다.
_JONG_NG: Final[str] = "g"

#: 자음 -> 로마자 뼈대. 모음은 버린다(음차 변형이 심한 쪽이 모음이라서).
_CONSONANT_MAP: Final[dict[str, str]] = {
    "ㄱ": "g", "ㄲ": "g", "ㄴ": "n", "ㄷ": "d", "ㄸ": "d", "ㄹ": "r",
    "ㅁ": "m", "ㅂ": "b", "ㅃ": "b", "ㅅ": "s", "ㅆ": "s", "ㅇ": "",
    # ㅊ는 영어 ch에 대응한다. 영문 c는 아래에서 k로 접히므로 같은 뼈대(kh)로 맞춘다.
    "ㅈ": "j", "ㅉ": "j", "ㅊ": "kh", "ㅋ": "k", "ㅌ": "t", "ㅍ": "p",
    "ㅎ": "h",
}

#: 영어 철자를 같은 뼈대로 줄이기 위한 정규화.
_LATIN_FOLD: Final[dict[str, str]] = {
    "k": "g", "q": "g", "x": "gs", "c": "k", "v": "b", "f": "p",
    "z": "j", "w": "", "y": "", "l": "r",
}


def consonant_skeleton(text: str) -> str:
    """한글/영문을 자음 뼈대로 줄인다. 음차 여부 비교용."""
    out: list[str] = []
    normalized = unicodedata.normalize("NFC", text)
    for position, ch in enumerate(normalized):
        next_char = normalized[position + 1].lower() if position + 1 < len(normalized) else ""
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:  # 완성형 한글
            index = code - 0xAC00
            out.append(_CONSONANT_MAP.get(_CHO[index // 588], ""))
            jong = _JONG[index % 28]
            if jong == "ㅇ":
                out.append(_JONG_NG)  # 받침 ㅇ = /ŋ/ = 영어 ng
            elif jong != " ":
                out.append(_CONSONANT_MAP.get(jong, ""))
        elif ch.isascii() and ch.isalpha():
            lower = ch.lower()
            if lower in "aeiou":
                continue
            # 연음 c(device의 ce = /s/)를 반영하면 `디바이스 ~ device`는 잡히지만
            # 진짜 교정인 `라이샤인트 -> Ricean`까지 폐기된다(실측). 진짜 교정을
            # 잃는 쪽이 훨씬 나쁘므로 c는 항상 k로 접는다.
            out.append(_LATIN_FOLD.get(lower, lower))
    # 같은 자음 반복은 하나로 (Gaussian의 ss 등)
    skeleton = "".join(out)
    return re.sub(r"(.)\1+", r"\1", skeleton)


def is_mere_transliteration(original: str, correction: str, threshold: float = 0.8) -> bool:
    """교정이 원문의 철자 변환일 뿐인지.

    `가우시안 -> Gaussian`처럼 자음 뼈대가 같으면 정보가 늘지 않는다.
    한글 -> 로마자 방향에만 적용한다(한글 -> 한글 교정은 진짜 교정일 수 있다).
    """
    has_hangul = any(0xAC00 <= ord(c) <= 0xD7A3 for c in original)
    correction_ascii = correction.strip() and all(
        c.isascii() for c in correction if not c.isspace()
    )
    if not (has_hangul and correction_ascii):
        return False
    left, right = consonant_skeleton(original), consonant_skeleton(correction)
    if not left or not right:
        return False
    return SequenceMatcher(None, left, right).ratio() >= threshold


# --- 검증 -----------------------------------------------------------------


def validate_proposals(
    raw: Sequence[dict[str, Any]],
    source_text: str,
    min_confidence: str = "medium",
) -> tuple[list[Proposal], list[tuple[str, str, str]]]:
    """모델 제안을 기계적으로 거른다. (통과, 폐기[(원문, 교정, 사유)])

    LLM은 오디오를 못 듣기 때문에 제안은 전부 추정이다. 최소한 다음은 보장한다.

    - `original`이 전사문에 **글자 그대로** 있을 것 (환각 방지)
    - 원문과 교정이 다를 것
    - 단순 철자 변환이 아닐 것
    - 같은 원문에 대한 중복 제안이 아닐 것
    - 신뢰도 하한을 넘을 것
    """
    passed: list[Proposal] = []
    rejected: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    floor = _CONFIDENCE_ORDER.get(min_confidence, 1)

    for item in raw:
        original = str(item.get("original", "")).strip()
        correction = str(item.get("correction", "")).strip()
        confidence = str(item.get("confidence", "low")).strip().lower()
        reason = str(item.get("reason", "")).strip()

        if not original or not correction:
            rejected.append((original, correction, "빈 값"))
            continue
        if original not in source_text:
            rejected.append((original, correction, "전사문에 없는 문자열(환각)"))
            continue
        if original == correction:
            rejected.append((original, correction, "원문과 동일"))
            continue
        if _CONFIDENCE_ORDER.get(confidence, 0) < floor:
            rejected.append((original, correction, f"신뢰도 미달({confidence})"))
            continue
        if is_mere_transliteration(original, correction):
            rejected.append((original, correction, "철자 변환일 뿐(교정 아님)"))
            continue
        if original in seen:
            rejected.append((original, correction, "중복 제안"))
            continue
        # 이미 통과한 제안의 부분 문자열이면 중복이다(`어댑티브` vs `어댑티브가 뭐다?`)
        if any(original in kept.original or kept.original in original for kept in passed):
            rejected.append((original, correction, "다른 제안과 겹침"))
            continue

        seen.add(original)
        passed.append(
            Proposal(
                original=original,
                correction=correction,
                reason=reason,
                confidence=confidence,
            )
        )
    return passed, rejected


def locate(proposals: Sequence[Proposal], segments: Sequence[Segment]) -> list[Proposal]:
    """제안을 세그먼트에 연결해 타임스탬프·신뢰도를 채운다."""
    located: list[Proposal] = []
    for proposal in proposals:
        match = next((s for s in segments if proposal.original in s.text), None)
        if match is None:
            located.append(proposal)
            continue
        located.append(
            Proposal(
                original=proposal.original,
                correction=proposal.correction,
                reason=proposal.reason,
                confidence=proposal.confidence,
                segment_id=match.id,
                start=round(match.start, 2),
                end=round(match.end, 2),
                context=match.text.strip(),
                segment_avg_logprob=round(match.avg_logprob, 3),
            )
        )
    return located


# --- 주석 적용 -------------------------------------------------------------


def annotate(text: str, proposals: Sequence[Proposal], marker: str = "[→{correction}]") -> str:
    """원문은 그대로 두고 교정을 주석으로 덧붙인다.

    긴 원문부터 치환해야 짧은 쪽이 긴 쪽 안을 먼저 건드리지 않는다.
    이미 주석이 붙은 자리는 다시 건드리지 않는다.
    """
    annotated = text
    for proposal in sorted(proposals, key=lambda p: -len(p.original)):
        suffix = marker.format(correction=proposal.correction)
        if f"{proposal.original}{suffix}" in annotated:
            continue
        pattern = re.escape(proposal.original) + r"(?!\[→)"
        annotated = re.sub(
            pattern, lambda m: m.group(0) + suffix, annotated, count=1
        )
    return annotated


# --- 프롬프트 -------------------------------------------------------------


def build_prompt(
    text: str,
    topic: str,
    glossary: Sequence[str],
    slide_terms: Sequence[str] = (),
    context_before: Sequence[str] = (),
    context_after: Sequence[str] = (),
) -> str:
    """교정 요청 프롬프트.

    **주제와 용어집이 반드시 들어간다.** 이 둘이 없으면 같은 모델이 1/7까지
    떨어진다(실측). 있으면 8/9까지 올라간다.

    `slide_terms`(영상 슬라이드 OCR에서 뽑은 용어)는 "확인된 용어"에 섞지 않고
    **별도 섹션**으로 넣는다. OCR은 오타가 섞여 있어(실측: "Fitters" 등) 정답으로
    취급하면 모델이 오타 쪽으로 교정할 수 있다. 비어 있으면 섹션 자체를 넣지 않아
    프롬프트가 기존과 완전히 같다.

    `context_before`/`context_after`는 이 구간 앞뒤의 원문 몇 줄(참고용, 교정 대상
    아님)이다. 청크 경계에서 잘린 문장의 문맥을 보여줘 판단을 돕는다(FIX_GUIDE_13
    P-01 e 실측: precision 0.56->0.68, recall 0.22->0.29, 속도 변화 없음). 검증은
    이 텍스트가 아니라 본문(`text`)만 대상으로 한다 — 문맥 쪽 문자열은 애초에
    `original`로 쓰지 말라고 프롬프트에서 명시한다.
    """
    known = ", ".join(glossary) if glossary else "(없음)"
    slide_section = ""
    if slide_terms:
        slide_section = (
            "슬라이드에서 읽은 표기(OCR이라 오타가 있을 수 있다. 참고만 하고, "
            "녹취록과 발음이 비슷할 때만 근거로 삼아라): "
            + ", ".join(slide_terms)
            + "\n"
        )
    context_section = ""
    if context_before or context_after:
        before = "\n".join(context_before) or "(없음)"
        after = "\n".join(context_after) or "(없음)"
        context_section = (
            f"\n앞뒤 문맥(참고용. 여기 있는 문자열은 original로 쓰지 마라):\n"
            f"[앞]\n{before}\n[뒤]\n{after}\n"
        )
    return f"""너는 한국어 강의 녹취록의 **음성인식 오류**를 찾아내는 교정 보조다.

강의 주제: {topic or "(미지정)"}
이미 확인된 용어: {known}
{slide_section}
녹취록에는 강의자가 말한 **영어 전문용어를 음성인식기가 한국어로 잘못 받아쓴**
부분이 많다. 발음이 비슷하지만 이 강의 맥락에서 뜻이 통하지 않는 표현을 찾아,
실제로 무슨 용어였을지 추정하라. 영어 약어(AWGN, ML, MAP, PSD 등)는 각 글자가
무엇의 약자인지 먼저 따져 보고 판단하라. 영어 전문용어뿐 아니라 **일반 한국어
단어**도 발음이 비슷한 다른 말로 잘못 받아쓴 경우(예: "수신신호"를 "수신신보"로,
"복조"를 "복주"로)를 찾아라. 문맥상 뜻이 통하지 않을 때만 제안하라.

규칙:
- "original"은 녹취록에 **글자 그대로 있는** 문자열이어야 한다. 지어내면 버려진다.
- 이미 올바른 한국어 음차(화이트, 가우시안, 노이즈, 채널 등)를 영어 철자로
  바꾸는 것은 교정이 아니다. **제안하지 마라.**
- 멀쩡한 구어체·말버릇("어", "그러니까", "뭐야")은 건드리지 마라.
- 뜻이 통하지 않아 **실제로 알아보기 어려운 곳만** 골라라.
- "reason"은 그렇게 판단한 근거 한 문장.
{context_section}
녹취록:
---
{text}
---"""


# --- Ollama 클라이언트 -----------------------------------------------------


class OllamaClient:
    """Ollama HTTP API 최소 클라이언트.

    표준 라이브러리만 쓴다(신규 파이썬 의존성 없음). 데몬이 꺼져 있으면 직접
    띄운다(실측 0.3초). 매 요청에 `keep_alive=0`을 넣어 응답 직후 모델을
    내리게 한다(실측: 4,580MB -> 51MB, 1초). 전사 모델과 메모리가 겹치지 않는다.
    """

    def __init__(self, host: str = DEFAULT_HOST, timeout: float = 600.0) -> None:
        self._host = host.rstrip("/")
        self._timeout = timeout

    def alive(self, timeout: float = 1.0) -> bool:
        try:
            with urllib.request.urlopen(f"{self._host}/api/version", timeout=timeout):
                return True
        except (urllib.error.URLError, OSError):
            return False

    def ensure_running(self, wait_sec: float = 15.0) -> None:
        """데몬이 꺼져 있으면 띄운다. 실패하면 CorrectionUnavailableError."""
        if self.alive():
            return
        binary = find_ollama()
        if binary is None:
            raise CorrectionUnavailableError(
                "교정 기능을 쓰려면 Ollama가 필요합니다. "
                "`brew install ollama` 후 `ollama pull gemma4:e4b` 를 실행하세요.",
                "ollama 실행 파일을 찾지 못함(고정 경로·PATH 전부 탐색)",
            )
        logger.info("Ollama 데몬이 꺼져 있어 직접 실행합니다: %s", binary)
        try:
            subprocess.Popen(  # noqa: S603 - find_ollama()로 찾은 실행 파일
                [str(binary), "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise CorrectionUnavailableError(
                "Ollama를 실행하지 못했습니다. 터미널에서 `ollama serve`를 직접 실행해 보세요.",
                f"ollama serve 기동 실패: {exc!r}",
            ) from exc
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            if self.alive(0.5):
                return
            time.sleep(0.25)
        raise CorrectionUnavailableError(
            "Ollama가 응답하지 않습니다. 터미널에서 `ollama serve`를 직접 실행해 보세요.",
            f"ollama serve 기동 후 {wait_sec}초 동안 응답 없음",
        )

    def release(self, model: str) -> None:
        """모델을 즉시 메모리에서 내린다. 빈 프롬프트 + keep_alive=0."""
        body = json.dumps(
            {"model": model, "prompt": "", "stream": False, "keep_alive": 0}
        ).encode()
        request = urllib.request.Request(
            f"{self._host}/api/generate", body, {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
        except (urllib.error.URLError, OSError) as exc:
            raise CorrectionUnavailableError(
                "교정 모델을 내리지 못했습니다.", f"keep_alive=0 요청 실패: {exc!r}"
            ) from exc
        logger.info("교정 모델 해제 요청: %s", model)

    def models(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self._host}/api/tags", timeout=10) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise CorrectionUnavailableError(
                "Ollama 모델 목록을 읽지 못했습니다.", f"/api/tags 실패: {exc!r}"
            ) from exc
        return [str(m.get("name", "")) for m in payload.get("models", [])]

    def require_model(self, model: str) -> None:
        available = self.models()
        if model in available:
            return
        # `gemma4:e4b`와 `gemma4:e4b:latest` 같은 표기 차이(끝의 기본 태그)만
        # 흡수한다. **첫 콜론까지만 자르면 안 된다** — `gemma4:e4b`와
        # `gemma4:e2b`가 같은 "gemma4" 스템을 공유해서, e2b만 설치돼 있어도
        # e4b 요구가 통과해버리는 실측 버그가 있었다.
        if _model_stem(model) in {_model_stem(name) for name in available}:
            return
        raise CorrectionUnavailableError(
            f"교정 모델 '{model}' 이(가) 없습니다. `ollama pull {model}` 로 내려받으세요.",
            f"모델 미설치: {model} (설치된 것: {', '.join(available) or '없음'})",
        )

    def propose(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.2,
        keep_alive: str | int = KEEP_ALIVE_DURING_RUN,
    ) -> list[dict[str, Any]]:
        """교정 후보를 받는다.

        `think=False`가 중요하다. 켜두면 은닉 사고 토큰이 출력 예산을 다 먹어
        **빈 응답**이 오고 17배 느려진다(실측 20.7초 -> 1.2초).

        `keep_alive`는 구간을 도는 동안 모델을 붙잡아 둔다. 매 요청에 0을 주면
        구간마다 모델을 다시 올려 로드 비용(e4b 약 7.7초)이 구간 수만큼 붙는다.
        전부 끝난 뒤 `release()`로 한 번에 내린다.
        """
        body = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "format": RESPONSE_SCHEMA,
                "keep_alive": keep_alive,
                "options": {"temperature": temperature, "num_predict": 2000},
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._host}/api/generate", body, {"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, OSError) as exc:
            raise CorrectionUnavailableError(
                "교정 모델 호출에 실패했습니다. 전사 결과는 그대로 저장됩니다.",
                f"/api/generate 실패 model={model}: {exc!r}",
            ) from exc
        except ValueError as exc:
            raise CorrectionUnavailableError(
                "교정 모델 응답을 해석하지 못했습니다.", f"응답 JSON 파싱 실패: {exc!r}"
            ) from exc
        raw = str(payload.get("response", "")).strip()
        if not raw:
            logger.warning("교정 모델이 빈 응답을 돌려줬습니다 (model=%s)", model)
            return []
        try:
            parsed = json.loads(raw)
        except ValueError:
            logger.warning("교정 응답이 JSON이 아닙니다: %s", raw[:200])
            return []
        items = parsed.get("corrections", [])
        return [i for i in items if isinstance(i, dict)]


def _release_client(client: OllamaClient, model: str) -> None:
    """교정이 끝났으니 모델을 메모리에서 내린다(실측 4,580MB -> 51MB, 1초)."""
    try:
        client.release(model)
    except CorrectionUnavailableError as exc:
        logger.warning("교정 모델 해제 실패(무시): %s", exc.log_message)


def chunk_segments(
    segments: Sequence[Segment], max_chars: int
) -> list[tuple[list[Segment], str]]:
    """세그먼트를 문자 수 기준으로 묶는다. 세그먼트 경계는 깨지 않는다."""
    chunks: list[tuple[list[Segment], str]] = []
    current: list[Segment] = []
    size = 0
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if current and size + len(text) > max_chars:
            chunks.append((current, "\n".join(s.text.strip() for s in current)))
            current, size = [], 0
        current.append(segment)
        size += len(text) + 1
    if current:
        chunks.append((current, "\n".join(s.text.strip() for s in current)))
    return chunks


# --- 오케스트레이션 ---------------------------------------------------------


def propose_corrections(
    segments: Sequence[Segment],
    topic: str,
    glossary: Sequence[str],
    *,
    model: str = CORRECTION_MODELS[0],
    min_confidence: str = "medium",
    max_chars: int = 1200,
    slide_terms: Sequence[str] = (),
    client: OllamaClient | None = None,
    on_progress: "ProgressHook | None" = None,
    should_cancel: "CancelHook | None" = None,
) -> CorrectionResult:
    """전사 세그먼트를 훑어 교정 후보를 모은다.

    실패하면 예외를 올리지 않고 `skipped_reason`을 채워 돌려준다. 교정은 부가
    기능이라 여기서 실패해도 전사 결과는 그대로 저장돼야 한다.
    """
    started = time.monotonic()
    result = CorrectionResult(model=model, slide_terms=list(slide_terms))
    if not segments:
        result.skipped_reason = "전사 결과가 비어 있습니다."
        return result

    ollama = client or OllamaClient()
    try:
        ollama.ensure_running()
        ollama.require_model(model)
    except CorrectionUnavailableError as exc:
        logger.warning("교정 건너뜀: %s", exc.log_message)
        result.skipped_reason = exc.user_message
        return result

    chunks = chunk_segments(segments, max_chars)
    result.chunks = len(chunks)
    collected: list[Proposal] = []
    for chunk_index, (chunk_segments_, chunk_text) in enumerate(chunks):
        if should_cancel is not None and should_cancel():
            # 루프를 빠져나가도 아래에서 반드시 해제한다.
            result.skipped_reason = "사용자가 취소했습니다."
            break
        if on_progress is not None:
            on_progress(chunk_index + 1, len(chunks))
        context_before = (
            [s.text.strip() for s in chunks[chunk_index - 1][0][-CONTEXT_SEGMENTS:]]
            if chunk_index > 0
            else []
        )
        context_after = (
            [s.text.strip() for s in chunks[chunk_index + 1][0][:CONTEXT_SEGMENTS]]
            if chunk_index + 1 < len(chunks)
            else []
        )
        prompt = build_prompt(
            chunk_text, topic, glossary, slide_terms, context_before, context_after
        )
        try:
            raw = ollama.propose(prompt, model)
        except CorrectionUnavailableError as exc:
            logger.warning(
                "교정 구간 %d/%d 실패: %s", chunk_index + 1, len(chunks), exc.log_message
            )
            continue
        passed, rejected = validate_proposals(raw, chunk_text, min_confidence)
        result.rejected.extend(rejected)
        collected.extend(locate(passed, chunk_segments_))

    # 구간을 넘나드는 중복을 한 번 더 정리한다.
    final: list[Proposal] = []
    seen: set[str] = set()
    for proposal in sorted(collected, key=lambda p: (-p.rank, -len(p.original))):
        if proposal.original in seen:
            continue
        seen.add(proposal.original)
        final.append(proposal)
    result.proposals = sorted(final, key=lambda p: (p.start is None, p.start or 0.0))
    # 교정이 끝났다. 전사 모델이 다시 올라오기 전에 메모리를 비운다.
    _release_client(ollama, model)
    result.elapsed_sec = time.monotonic() - started
    logger.info(
        "교정 %d건 채택 / %d건 폐기 (%d구간, %.1f초, model=%s)",
        len(result.proposals),
        len(result.rejected),
        result.chunks,
        result.elapsed_sec,
        model,
    )
    return result


def build_sidecar(
    result: CorrectionResult,
    *,
    source_audio: Path,
    transcript_path: Path | None,
    topic: str,
    glossary: Sequence[str],
    generated_at: str,
) -> dict[str, Any]:
    """Claude 등 에이전트가 바로 읽을 수 있는 교정 설명 JSON."""
    return {
        "schema": "lecture-scribe/corrections/v1",
        "source_audio": str(source_audio),
        "source_transcript": str(transcript_path) if transcript_path else None,
        "generated_at": generated_at,
        "topic": topic,
        "glossary": list(glossary),
        "slide_terms_used": list(result.slide_terms),
        "corrector": {
            "backend": "ollama",
            "model": result.model,
            "elapsed_sec": round(result.elapsed_sec, 2),
            "chunks": result.chunks,
        },
        "notice": (
            "원문 전사는 수정되지 않았습니다. 아래는 음성인식 오류로 추정되는 부분과 "
            "교정 후보입니다. 각 original 문자열은 전사문에 그대로 존재함이 기계적으로 "
            "확인되었습니다. 다만 교정을 제안한 모델은 오디오를 듣지 못하고 문맥만 보고 "
            "추정했으므로, 교정 내용은 확정 사실이 아닙니다. 인용할 때는 원문을 쓰고 "
            "교정은 가능성으로만 다루십시오."
        ),
        "inline_marker": "전사문에는 `원문[→교정]` 형태로 표시되어 있습니다.",
        "stats": {
            "accepted": len(result.proposals),
            "rejected": len(result.rejected),
            "by_confidence": {
                level: sum(1 for p in result.proposals if p.confidence == level)
                for level in ("high", "medium", "low")
            },
        },
        "corrections": [
            {
                "id": index,
                "segment_id": proposal.segment_id,
                "start": proposal.start,
                "end": proposal.end,
                "original": proposal.original,
                "correction": proposal.correction,
                "reason": proposal.reason,
                "confidence": proposal.confidence,
                "segment_avg_logprob": proposal.segment_avg_logprob,
                "context": proposal.context,
            }
            for index, proposal in enumerate(result.proposals, 1)
        ],
        "rejected_samples": [
            {"original": o, "correction": c, "reason": r}
            for o, c, r in result.rejected[:20]
        ],
    }


__all__ = [
    "CORRECTION_MODELS",
    "CorrectionResult",
    "CorrectionUnavailableError",
    "DEFAULT_HOST",
    "KEEP_ALIVE_DURING_RUN",
    "Proposal",
    "OllamaClient",
    "annotate",
    "build_prompt",
    "build_sidecar",
    "chunk_segments",
    "consonant_skeleton",
    "find_ollama",
    "is_mere_transliteration",
    "list_installed_gemma_models",
    "locate",
    "ollama_available",
    "propose_corrections",
    "validate_proposals",
]
