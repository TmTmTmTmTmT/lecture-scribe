"""설정 스키마, 로드/저장, 프리셋 관리.

- 저장 위치: ~/Library/Application Support/LectureScribe/settings.json
- `version` 필드 기준 마이그레이션 경로를 처음부터 유지한다.
- GUI/백엔드에 의존하지 않는 순수 데이터 계층.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import urlparse

from .errors import ConfigError

# `logsetup.py`가 로그 폴더 기본값(`default_log_dir()`)을 이 모듈에서 가져오므로
# 여기서 `logsetup.get_logger`를 쓰면 순환 임포트가 된다. 표준 로거를 직접 쓴다
# (`get_logger`도 결국 `logging.getLogger(name)`일 뿐이라 동작은 같다).
logger = logging.getLogger(__name__)

SCHEMA_VERSION: Final[int] = 3

BackendName = Literal["faster", "mlx"]
LanguageCode = Literal["ko", "en", "auto"]
ConflictPolicy = Literal["overwrite", "suffix", "skip"]
OutputFormat = Literal["txt", "md", "srt", "vtt", "json"]
MirrorMode = Literal["hardlink", "copy", "symlink"]
SettingsSource = Literal["active_preset", "last_used"]

#: GUI에서 고를 수 있는 모델. 실사용에 의미 있는 2종만 남겼다.
#: - large-v3       : 정확도 기준. 45분 강의 약 30분, 상주 2.4GB
#: - large-v3-turbo : 3.4배 빠름. 45분 강의 약 8분, 상주 1.4GB
#: 더 작은 모델(medium 이하)은 한국어 강의에서 품질이 크게 떨어져 뺐다.
#: CLI에서는 `--model <이름 또는 HF 리포 id>`로 아무 모델이나 지정할 수 있다.
MODEL_NAMES: Final[tuple[str, ...]] = (
    "large-v3",
    "large-v3-turbo",
)

def default_app_support_dir() -> Path:
    """기본 저장 폴더. **호출 시점에** `Path.home()`을 읽는다.

    `Final` 상수로 모듈 임포트 시점에 굳혀 두면, 테스트가 나중에 `Path.home`을
    패치해도 이미 계산된 값은 바뀌지 않아 **실제 사용자 파일을 건드리게 된다**
    (실측 확인: `tests/conftest.py`의 `isolated_home`이 패치하기 전에 이 모듈이
    한 번이라도 임포트되면 `APP_SUPPORT_DIR`/`SETTINGS_PATH`가 진짜 홈 디렉터리로
    고정되고, 그 뒤로 어떤 테스트가 `load_settings()`/`save_settings()`를 경로 없이
    불러도 실제 `~/Library/Application Support/LectureScribe/settings.json`을
    읽고 쓴다). `settings_path()`가 이 함수를 매번 호출해 우회한다.
    """
    return Path.home() / "Library" / "Application Support" / "LectureScribe"


def default_log_dir() -> Path:
    """로그 폴더 기본값. 같은 이유로 호출 시점에 계산한다(`default_app_support_dir` 참고)."""
    return Path.home() / "Library" / "Logs" / "LectureScribe"


#: 참고/문서화·하위 호환용 기본값. 모듈 임포트 시점에 고정되므로 **런타임 기본값으로
#: 쓰지 않는다** — `settings_path()`/`logsetup.py`는 각각 `default_app_support_dir()`/
#: `default_log_dir()`를 호출 시점에 다시 계산해서 쓴다.
APP_SUPPORT_DIR: Final[Path] = default_app_support_dir()
SETTINGS_PATH: Final[Path] = APP_SUPPORT_DIR / "settings.json"
LOG_DIR: Final[Path] = default_log_dir()
LOG_PATH: Final[Path] = LOG_DIR / "lecture-scribe.log"


def _expand(path_str: str) -> Path:
    """`~` 확장 포함 경로 변환. 문자열 결합 대신 항상 Path를 쓴다."""
    return Path(os.path.expanduser(path_str))


@dataclass(slots=True)
class Preset:
    """주제/용어/치환사전 묶음."""

    topic: str = ""
    glossary: list[str] = field(default_factory=list)
    corrections: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Preset:
        glossary_raw = raw.get("glossary", [])
        corrections_raw = raw.get("corrections", {})
        return cls(
            topic=str(raw.get("topic", "")),
            glossary=[str(g) for g in glossary_raw],
            corrections={str(k): str(v) for k, v in corrections_raw.items()},
        )


@dataclass(slots=True)
class PromptSettings:
    """F-03 프롬프트 파이프라인 설정.

    `use_initial_prompt` 기본값이 False인 이유(실측):
    initial_prompt를 넣으면 Whisper가 프롬프트를 "이미 말한 내용"으로 해석해
    오디오 **앞부분을 통째로 건너뛴다**(90초 클립에서 25초 누락, 프롬프트 길이
    96/149토큰 모두 동일하게 재현). hotwords만 써도 전문 용어 인식 효과는
    그대로였고 앞 구간 누락은 발생하지 않았다. 필요하면 설정이나
    `--initial-prompt`로 다시 켤 수 있다.
    """

    use_initial_prompt: bool = False
    use_hotwords: bool = True
    #: faster-whisper가 쓰는 값. mlx는 아래 `condition_on_previous_text_mlx`를
    #: 따로 쓴다(§ 바로 아래 주석) — 이 필드는 건드리지 않는다.
    condition_on_previous_text: bool = True
    #: FIX_GUIDE_4.md A-02: mlx는 원래 위 `condition_on_previous_text` 하나로
    #: **서로 다른 두 메커니즘**을 같이 켰다/껐다 했다 — ① Whisper 내부 30초
    #: 서브청크끼리의 조건화와 ② 우리가 만든 120초 창 경계 캐리 프롬프트
    #: (마지막 문장을 다음 창에 넘기는 것, 아래 `carry_window_prompt`).
    #:
    #: §5-2 게이트 실측(실사용 3462초 파일 풀 런, A=켬 vs B=끔+캐리유지):
    #:   속도      A 1420.5초 → B 639.9초 (2.2배 빠름)
    #:   반복 루프 A 4건 → B 4건 (동률 — 어느 쪽도 나빠지지 않음)
    #:   외국어 혼입 A 102세그먼트 → B 11세그먼트 (89% 감소)
    #:   저신뢰 비율 A 9.61% → B 8.04% (개선)
    #:   용어 빈도  거의 동일(표기 흔들림 없음)
    #: 5개 중 나빠진 항목 없음 → 게이트 통과. **mlx 전용 기본값을 끔(False)으로
    #: 내렸다.** faster-whisper 쪽 `condition_on_previous_text`(위 필드)는
    #: 이 게이트와 무관하므로 손대지 않았다 — 그래서 별도 필드로 분리했다.
    condition_on_previous_text_mlx: bool = False
    #: 창 경계 캐리는 게이트에서 계속 켜 둔 상태(B 조건)로 측정했다 — 그대로 유지.
    carry_window_prompt: bool = True
    prompt_reset_on_temperature: float = 0.5
    max_prompt_tokens: int = 224
    fallback_on_collapse: bool = True  # 프롬프트로 출력이 붕괴하면 프롬프트 없이 재전사
    repeat_glossary_in_sentence: bool = True  # 용어를 initial_prompt 문장에도 넣을지

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PromptSettings:
        base = cls()
        return cls(
            use_initial_prompt=bool(
                raw.get("use_initial_prompt", base.use_initial_prompt)
            ),
            use_hotwords=bool(raw.get("use_hotwords", base.use_hotwords)),
            condition_on_previous_text=bool(
                raw.get("condition_on_previous_text", base.condition_on_previous_text)
            ),
            condition_on_previous_text_mlx=bool(
                raw.get(
                    "condition_on_previous_text_mlx",
                    base.condition_on_previous_text_mlx,
                )
            ),
            carry_window_prompt=bool(
                raw.get("carry_window_prompt", base.carry_window_prompt)
            ),
            prompt_reset_on_temperature=float(
                raw.get(
                    "prompt_reset_on_temperature", base.prompt_reset_on_temperature
                )
            ),
            max_prompt_tokens=int(
                raw.get("max_prompt_tokens", base.max_prompt_tokens)
            ),
            fallback_on_collapse=bool(
                raw.get("fallback_on_collapse", base.fallback_on_collapse)
            ),
            repeat_glossary_in_sentence=bool(
                raw.get(
                    "repeat_glossary_in_sentence", base.repeat_glossary_in_sentence
                )
            ),
        )


@dataclass(slots=True)
class DecodingSettings:
    """F-04 환각 억제 및 디코딩 파라미터."""

    #: 실측(7개 클립): beam 3이 beam 5보다 27% 빠르고 품질은 무승부.
    #: 정확도를 더 원하면 5로 올린다(`--beam-size 5`).
    beam_size: int = 3
    vad_filter: bool = True
    min_silence_duration_ms: int = 500
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    #: FIX_GUIDE_5.md B-01: 0.6 -> 0.5 시도, §5-1 게이트 **실패로 0.6 유지**.
    #: 실측(57분 실제 강의, faster/CPU/int8, large-v3): 0.6 기준 세그먼트983·글자19251·
    #: 반복0·저신뢰7.53% → 0.5로 내리자 글자19251->18900(-1.82%, 통과선 -1% 초과)·
    #: 반복0->2("만나러" 13회, "몰래" 4회 연속 반복 발생)·세그먼트983->1046.
    #: 환각(외국어 세그먼트)은 두 값 모두 0으로 차이 없었다 — 이 파라미터로는 얻는 게
    #: 없이 실제 발화 손실+반복 루프만 늘었다. 재개 조건: 다른 파일에서 재측정해
    #: 이 결과가 재현되지 않는다는 근거가 나올 때.
    no_speech_threshold: float = 0.6
    temperatures: list[float] = field(
        default_factory=lambda: [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    )
    hallucination_silence_threshold: float | None = 2.0
    repeat_warning_count: int = 3

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DecodingSettings:
        base = cls()
        hst = raw.get("hallucination_silence_threshold", base.hallucination_silence_threshold)
        return cls(
            beam_size=int(raw.get("beam_size", base.beam_size)),
            vad_filter=bool(raw.get("vad_filter", base.vad_filter)),
            min_silence_duration_ms=int(
                raw.get("min_silence_duration_ms", base.min_silence_duration_ms)
            ),
            compression_ratio_threshold=float(
                raw.get(
                    "compression_ratio_threshold", base.compression_ratio_threshold
                )
            ),
            log_prob_threshold=float(
                raw.get("log_prob_threshold", base.log_prob_threshold)
            ),
            no_speech_threshold=float(
                raw.get("no_speech_threshold", base.no_speech_threshold)
            ),
            temperatures=[float(t) for t in raw.get("temperatures", base.temperatures)],
            hallucination_silence_threshold=(
                None if hst is None else float(hst)
            ),
            repeat_warning_count=int(
                raw.get("repeat_warning_count", base.repeat_warning_count)
            ),
        )


@dataclass(slots=True)
class OutputSettings:
    """F-05 출력 설정."""

    formats: list[OutputFormat] = field(default_factory=lambda: ["txt"])
    timestamps: bool = False
    paragraph_break_sec: float = 2.0
    line_width: int = 0  # 0 = 줄바꿈 없음
    on_conflict: ConflictPolicy = "suffix"
    fallback_dir: str = "~/Documents/LectureScribe"
    mark_repeats: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OutputSettings:
        base = cls()
        formats_raw = raw.get("formats", base.formats)
        formats: list[OutputFormat] = []
        for f in formats_raw:
            if f in ("txt", "md", "srt", "vtt", "json"):
                formats.append(f)
        conflict = raw.get("on_conflict", base.on_conflict)
        if conflict not in ("overwrite", "suffix", "skip"):
            conflict = base.on_conflict
        return cls(
            formats=formats or ["txt"],
            timestamps=bool(raw.get("timestamps", base.timestamps)),
            paragraph_break_sec=float(
                raw.get("paragraph_break_sec", base.paragraph_break_sec)
            ),
            line_width=int(raw.get("line_width", base.line_width)),
            on_conflict=conflict,
            fallback_dir=str(raw.get("fallback_dir", base.fallback_dir)),
            mark_repeats=bool(raw.get("mark_repeats", base.mark_repeats)),
        )

    @property
    def fallback_path(self) -> Path:
        return _expand(self.fallback_dir)


@dataclass(slots=True)
class QuickActionSettings:
    """F-08 Quick Action이 어떤 설정을 쓸지."""

    settings_source: SettingsSource = "active_preset"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> QuickActionSettings:
        src = raw.get("settings_source", "active_preset")
        if src not in ("active_preset", "last_used"):
            src = "active_preset"
        return cls(settings_source=src)


#: FIX_GUIDE_4.md A-01: 교정 호스트로 허용하는 로컬 주소만 명시한다.
#: `urlparse(...).hostname`은 IPv6 대괄호를 벗겨 `::1`로 돌려준다(실측 확인).
_ALLOWED_CORRECTION_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "127.0.0.1", "::1"}
)

#: 이 환경변수가 켜져 있으면 원격 교정 호스트를 허용한다(탈출구). 앱이 사용자
#: 몰래 이 값을 켜는 일은 없다 — 사람이 직접 셸에서 설정해야만 동작한다.
_ALLOW_REMOTE_CORRECTION_ENV: Final[str] = "LECTURE_SCRIBE_ALLOW_REMOTE_CORRECTION"


def _validate_correction_host(raw_host: str, default: str) -> str:
    """교정(Ollama) 호스트를 검증한다.

    FIX_GUIDE_4.md A-01: 이 앱의 1순위 원칙은 "전 과정 로컬"이다(CLAUDE.md §목적,
    §절대 하지 말 것 2). `settings.json`을 직접 편집(또는 다른 도구가 건드림)해
    원격 주소가 들어오면, 전사문 전체가 그 주소로 나간다(`correction.py propose`).
    검증 없이 통과시키면 이 원칙이 조용히 깨진다.

    로컬호스트가 아니면 기본값으로 되돌리고 WARNING을 남긴다(§15-6 — 조용히
    삼키지 않는다). `_ALLOW_REMOTE_CORRECTION_ENV`가 켜져 있을 때만 예외로
    허용하되, 그때도 매번 WARNING을 남긴다 — 설정 파일 한 줄로 조용히 열리는
    길을 막는 것이 목적이다.
    """
    try:
        parsed = urlparse(raw_host)
    except ValueError:
        logger.warning(
            "교정 host를 해석할 수 없어 기본값으로 되돌립니다: %r", raw_host
        )
        return default
    hostname = (parsed.hostname or "").lower()
    if hostname in _ALLOWED_CORRECTION_HOSTS:
        return raw_host
    if os.environ.get(_ALLOW_REMOTE_CORRECTION_ENV):
        logger.warning(
            "교정 host가 로컬이 아닙니다(%s) — %s가 켜져 있어 허용합니다. "
            "전사문이 이 주소로 전송됩니다.",
            raw_host,
            _ALLOW_REMOTE_CORRECTION_ENV,
        )
        return raw_host
    logger.warning(
        "교정 host가 로컬이 아니라 기본값으로 되돌립니다: %r "
        "(원격을 쓰려면 %s=1을 설정하세요 — 전사문이 그 주소로 전송됩니다)",
        raw_host,
        _ALLOW_REMOTE_CORRECTION_ENV,
    )
    return default


@dataclass(slots=True)
class CorrectionSettings:
    """F-09 전사 후 LLM 교정 제안.

    전사문은 **고치지 않고** `원문[→교정]` 주석만 붙이고, 근거를 담은
    `<basename>.corrections.json`을 함께 낸다.

    실측(전자회로 강의 918자): gemma4:e4b 8/9 정답 33.5초 /
    gemma4:e2b 5/7 정답 19.7초. 주제·용어집을 프롬프트에 넣지 않으면 1/7까지 떨어진다.
    """

    #: 기본은 꺼둔다. Ollama가 없는 환경이 정상이고, 전사만으로도 완결되어야 한다.
    enabled: bool = False
    model: str = "gemma4:e4b"
    #: low는 잡음이 많아 기본 제외.
    min_confidence: str = "medium"
    #: 한 번에 모델에 넘길 전사문 길이. 길수록 문맥이 좋아지지만 느려진다.
    chunk_chars: int = 1200
    #: 전사문에 주석을 넣을지. 끄면 JSON만 낸다.
    annotate_transcript: bool = True
    #: 근거 JSON을 낼지.
    emit_sidecar: bool = True
    #: 영상 슬라이드 OCR 용어를 이 파일의 교정 프롬프트에 별도 섹션으로 넣는다(파일별, 저장 안 함).
    #: 전사 프롬프트용 `video.ocr_terms_to_prompt`와 별개다.
    use_ocr_terms: bool = False
    host: str = "http://localhost:11434"
    timeout_sec: float = 600.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CorrectionSettings:
        base = cls()
        confidence = str(raw.get("min_confidence", base.min_confidence)).lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = base.min_confidence
        return cls(
            enabled=bool(raw.get("enabled", base.enabled)),
            model=str(raw.get("model", base.model)),
            min_confidence=confidence,
            chunk_chars=max(200, int(raw.get("chunk_chars", base.chunk_chars))),
            annotate_transcript=bool(
                raw.get("annotate_transcript", base.annotate_transcript)
            ),
            emit_sidecar=bool(raw.get("emit_sidecar", base.emit_sidecar)),
            use_ocr_terms=bool(raw.get("use_ocr_terms", base.use_ocr_terms)),
            host=_validate_correction_host(
                str(raw.get("host", base.host)), base.host
            ),
            timeout_sec=float(raw.get("timeout_sec", base.timeout_sec)),
        )


@dataclass(slots=True)
class PostprocessSettings:
    """F-03(4) 후처리 용어 교정."""

    fuzzy_correction: bool = False
    fuzzy_threshold: int = 88
    #: 전사가 끝나면 자주 나온 전문어를 용어 칸에 자동으로 채워 넣는다.
    #: 프리셋에 바로 저장하지는 않는다(사용자가 확인·수정 후 "저장").
    auto_suggest_glossary: bool = True
    auto_suggest_limit: int = 8
    #: FIX_GUIDE_5.md B-02: 한자/가나 등 기대 언어 밖 문자 구간을 검출해
    #: 저신뢰 마커로 표시한다(삭제·치환은 하지 않는다). 기본 켬 — 원문을
    #: 건드리지 않고 표시만 하므로 꺼서 얻는 이득이 없다.
    foreign_script_detection: bool = True
    #: 검출 임계값. FIX_GUIDE_5.md §5-2 실측으로 확정한 초기값.
    foreign_script_ratio: float = 0.3
    foreign_script_min_count: int = 2

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PostprocessSettings:
        base = cls()
        return cls(
            fuzzy_correction=bool(raw.get("fuzzy_correction", base.fuzzy_correction)),
            fuzzy_threshold=int(raw.get("fuzzy_threshold", base.fuzzy_threshold)),
            auto_suggest_glossary=bool(
                raw.get("auto_suggest_glossary", base.auto_suggest_glossary)
            ),
            auto_suggest_limit=max(0, int(raw.get("auto_suggest_limit", base.auto_suggest_limit))),
            foreign_script_detection=bool(
                raw.get("foreign_script_detection", base.foreign_script_detection)
            ),
            foreign_script_ratio=float(
                raw.get("foreign_script_ratio", base.foreign_script_ratio)
            ),
            foreign_script_min_count=int(
                raw.get("foreign_script_min_count", base.foreign_script_min_count)
            ),
        )


@dataclass(slots=True)
class CoworkSettings:
    """§10 Cowork 연계 설정."""

    workspace_dir: str = "~/Documents/LectureScribe"
    mirror_mode: MirrorMode = "hardlink"
    write_sidecar_json: bool = True
    write_index: bool = True
    index_path: str = "~/Documents/LectureScribe/index.jsonl"
    section_interval_min: int = 10
    low_confidence_marker: str = "⟨?⟩"
    low_confidence_logprob: float = -0.8
    enable_mirror: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CoworkSettings:
        base = cls()
        mode = raw.get("mirror_mode", base.mirror_mode)
        if mode not in ("hardlink", "copy", "symlink"):
            mode = base.mirror_mode
        return cls(
            workspace_dir=str(raw.get("workspace_dir", base.workspace_dir)),
            mirror_mode=mode,
            write_sidecar_json=bool(
                raw.get("write_sidecar_json", base.write_sidecar_json)
            ),
            write_index=bool(raw.get("write_index", base.write_index)),
            index_path=str(raw.get("index_path", base.index_path)),
            section_interval_min=int(
                raw.get("section_interval_min", base.section_interval_min)
            ),
            low_confidence_marker=str(
                raw.get("low_confidence_marker", base.low_confidence_marker)
            ),
            low_confidence_logprob=float(
                raw.get("low_confidence_logprob", base.low_confidence_logprob)
            ),
            enable_mirror=bool(raw.get("enable_mirror", base.enable_mirror)),
        )

    @property
    def workspace_path(self) -> Path:
        return _expand(self.workspace_dir)

    @property
    def index_file(self) -> Path:
        return _expand(self.index_path)


def _clamp_float(raw: Any, default: float, low: float, high: float) -> float:
    """숫자로 해석되지 않거나 범위를 벗어나면 기본값/경계로 흡수한다."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    if value != value:  # NaN
        return default
    return min(high, max(low, value))


def _clamp_int(raw: Any, default: int, low: int, high: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, value))


@dataclass(slots=True)
class VideoSettings:
    """영상 입력 처리 (PLAN_VIDEO_FRAMES.md V-01). 프리셋과 무관한 전역 설정.

    기본값 근거(샘플 1, 18분 화면 녹화, 슬라이드 전환 20개를 눈으로 표시해 비교):
    - 마지막 저장 프레임 대비 10% + 저장본 전체와 3% 미만이면 중복 제외 -> 19/20 포착, 오탐 1.
    - 20%는 11/20만 포착한다(같은 배경에서 본문만 바뀌는 슬라이드를 놓침).
    """

    capture_frames: bool = True
    change_threshold_pct: float = 10.0
    dedupe_threshold_pct: float = 3.0
    min_interval_sec: float = 5.0
    max_frames: int = 300
    image_max_width: int = 1024
    jpeg_quality: int = 80
    ocr_enabled: bool = True
    #: 소리 있는 영상으로 효과 게이트(V-08)를 통과하기 전까지는 꺼 둔다.
    ocr_terms_to_prompt: bool = False
    ocr_max_terms: int = 30
    #: 프레임 여러 장을 격자로 이어붙인 시트를 만든다(FIX_GUIDE_13 S-01).
    #: 채팅 첨부 개수 제한을 피하기 위함. cols·rows가 둘 다 1이면 시트를 만들지 않는다.
    sheets_enabled: bool = True
    #: 1x2(가로 1, 세로 2). 2x2보다 칸이 커서 수식·작은 글자가 덜 뭉개진다(사용자 결정, 2026-09-28).
    sheet_cols: int = 1
    sheet_rows: int = 2
    #: 시트를 만든 뒤 낱장 이미지를 지울지. 기본은 지운다(폴더는 유지, jpg만).
    keep_single_frames: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> VideoSettings:
        base = cls()
        return cls(
            capture_frames=bool(raw.get("capture_frames", base.capture_frames)),
            change_threshold_pct=_clamp_float(
                raw.get("change_threshold_pct"), base.change_threshold_pct, 1.0, 90.0
            ),
            dedupe_threshold_pct=_clamp_float(
                raw.get("dedupe_threshold_pct"), base.dedupe_threshold_pct, 0.0, 20.0
            ),
            min_interval_sec=_clamp_float(
                raw.get("min_interval_sec"), base.min_interval_sec, 1.0, 600.0
            ),
            max_frames=_clamp_int(raw.get("max_frames"), base.max_frames, 1, 2000),
            image_max_width=_clamp_int(
                raw.get("image_max_width"), base.image_max_width, 256, 4096
            ),
            jpeg_quality=_clamp_int(raw.get("jpeg_quality"), base.jpeg_quality, 30, 95),
            ocr_enabled=bool(raw.get("ocr_enabled", base.ocr_enabled)),
            ocr_terms_to_prompt=bool(
                raw.get("ocr_terms_to_prompt", base.ocr_terms_to_prompt)
            ),
            ocr_max_terms=_clamp_int(raw.get("ocr_max_terms"), base.ocr_max_terms, 0, 100),
            sheets_enabled=bool(raw.get("sheets_enabled", base.sheets_enabled)),
            sheet_cols=_clamp_int(raw.get("sheet_cols"), base.sheet_cols, 1, 3),
            sheet_rows=_clamp_int(raw.get("sheet_rows"), base.sheet_rows, 1, 3),
            keep_single_frames=bool(
                raw.get("keep_single_frames", base.keep_single_frames)
            ),
        )


@dataclass(slots=True)
class PerformanceSettings:
    """우선순위·메모리 관리 (실측 기반 기본값).

    - 워커 스레드 기본 QoS는 DEFAULT라 저전력/발열 상황에서 효율 코어로 내려갈 수 있다.
    - 모델은 large-v3 기준 2.4GB를 상주시킨다. 해제하면 1.6GB가 OS로 돌아간다.
    - 가용 메모리가 부족한데 강행하면 스왑이 늘어 오히려 느려진다.
    """

    high_priority: bool = True  # 워커 스레드 QoS를 USER_INITIATED로
    release_memory_after_file: bool = True  # 파일 1건 끝날 때마다 힙 반환
    unload_model_after_idle_min: int = 10  # 유휴 N분 뒤 모델 해제(0이면 유지)
    warn_low_memory: bool = True  # 메모리 빠듯하면 안내

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PerformanceSettings:
        base = cls()
        return cls(
            high_priority=bool(raw.get("high_priority", base.high_priority)),
            release_memory_after_file=bool(
                raw.get("release_memory_after_file", base.release_memory_after_file)
            ),
            unload_model_after_idle_min=max(
                0,
                int(
                    raw.get(
                        "unload_model_after_idle_min", base.unload_model_after_idle_min
                    )
                ),
            ),
            warn_low_memory=bool(raw.get("warn_low_memory", base.warn_low_memory)),
        )


@dataclass(slots=True)
class WindowState:
    """GUI 창 크기·위치 영속화.

    FIX_GUIDE_6.md C-04: 정방형 강제를 풀면서 `size`(한 변) 하나였던 값을
    `width`/`height` 둘로 나눴다. 옛 설정 파일에 `size`만 있으면 폭=높이=그 값으로
    읽어 지금까지와 같은 정방형으로 복원한다(마이그레이션 없이 `from_dict` fallback으로
    처리 — SCHEMA_VERSION은 올리지 않는다).
    """

    width: int = 640
    height: int = 640
    x: int | None = None
    y: int | None = None
    #: 위(설정) 영역이 차지하는 비율. 사용자가 분할선을 끌어 조정한 값을 기억한다.
    split_ratio: float = 0.4

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WindowState:
        base = cls()
        x = raw.get("x")
        y = raw.get("y")
        # 한쪽이 사라진 비율은 쓰지 않는다(창이 깨져 보인다).
        ratio = float(raw.get("split_ratio", base.split_ratio))
        legacy_size = raw.get("size")
        width = raw.get("width")
        height = raw.get("height")
        if width is None and height is None and legacy_size is not None:
            width = height = legacy_size
        return cls(
            width=int(width) if width is not None else base.width,
            height=int(height) if height is not None else base.height,
            x=None if x is None else int(x),
            y=None if y is None else int(y),
            split_ratio=min(0.85, max(0.15, ratio)),
        )


@dataclass(slots=True)
class Settings:
    """전체 설정 트리."""

    version: int = SCHEMA_VERSION
    backend: BackendName = "faster"
    model: str = "large-v3"
    compute_type: str = "int8"
    #: 0 = 라이브러리 자동. 실측(M1 Pro): 자동/6스레드가 최적, 10스레드는 절반 속도
    #: (효율 코어까지 쓰면 오히려 느려진다). 기기가 다르면 조정한다.
    cpu_threads: int = 0
    #: 큐에서 동시에 전사할 파일 수. 모델 가중치는 공유되므로 메모리는 약 10%만 는다.
    #: 실측(M1 Pro): 단일 파일은 CPU를 47%만 쓴다 -> 2개 동시 처리로 1.4~1.7배 향상,
    #: 결과는 순차 처리와 **완전히 동일**함을 확인했다. 1이면 순차.
    max_parallel_files: int = 2
    language: LanguageCode = "ko"
    active_preset: str = "기본"
    presets: dict[str, Preset] = field(
        default_factory=lambda: {"기본": Preset()}
    )
    prompt: PromptSettings = field(default_factory=PromptSettings)
    decoding: DecodingSettings = field(default_factory=DecodingSettings)
    output: OutputSettings = field(default_factory=OutputSettings)
    quick_action: QuickActionSettings = field(default_factory=QuickActionSettings)
    postprocess: PostprocessSettings = field(default_factory=PostprocessSettings)
    correction: CorrectionSettings = field(default_factory=CorrectionSettings)
    cowork: CoworkSettings = field(default_factory=CoworkSettings)
    performance: PerformanceSettings = field(default_factory=PerformanceSettings)
    video: VideoSettings = field(default_factory=VideoSettings)
    window: WindowState = field(default_factory=WindowState)
    recursive_folder_drop: bool = True
    allow_translate_task: bool = False  # F-02 숨은 옵션

    # --- 프리셋 헬퍼 ---

    def current_preset(self) -> Preset:
        """활성 프리셋. 없으면 빈 프리셋을 돌려준다(예외 없음)."""
        return self.presets.get(self.active_preset, Preset())

    def with_preset(self, name: str) -> Settings:
        return replace(self, active_preset=name)

    # --- 직렬화 ---

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["version"] = SCHEMA_VERSION
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        raw = migrate(raw)
        base = cls()
        presets_raw = raw.get("presets", {})
        presets = {
            str(name): Preset.from_dict(p) for name, p in presets_raw.items()
        }
        if not presets:
            presets = {"기본": Preset()}
        backend = raw.get("backend", base.backend)
        if backend not in ("faster", "mlx"):
            backend = base.backend
        language = raw.get("language", base.language)
        if language not in ("ko", "en", "auto"):
            language = base.language
        active = str(raw.get("active_preset", base.active_preset))
        if active not in presets:
            active = next(iter(presets))
        return cls(
            version=SCHEMA_VERSION,
            backend=backend,
            model=str(raw.get("model", base.model)),
            compute_type=str(raw.get("compute_type", base.compute_type)),
            cpu_threads=int(raw.get("cpu_threads", base.cpu_threads)),
            max_parallel_files=max(
                1, int(raw.get("max_parallel_files", base.max_parallel_files))
            ),
            language=language,
            active_preset=active,
            presets=presets,
            prompt=PromptSettings.from_dict(raw.get("prompt", {})),
            decoding=DecodingSettings.from_dict(raw.get("decoding", {})),
            output=OutputSettings.from_dict(raw.get("output", {})),
            quick_action=QuickActionSettings.from_dict(raw.get("quick_action", {})),
            postprocess=PostprocessSettings.from_dict(raw.get("postprocess", {})),
            correction=CorrectionSettings.from_dict(raw.get("correction", {})),
            cowork=CoworkSettings.from_dict(raw.get("cowork", {})),
            performance=PerformanceSettings.from_dict(raw.get("performance", {})),
            video=VideoSettings.from_dict(raw.get("video", {})),
            window=WindowState.from_dict(raw.get("window", {})),
            recursive_folder_drop=bool(
                raw.get("recursive_folder_drop", base.recursive_folder_drop)
            ),
            allow_translate_task=bool(
                raw.get("allow_translate_task", base.allow_translate_task)
            ),
        )


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    """설정 버전 마이그레이션.

    각 단계는 `raw`를 다음 버전 형태로 올린다. 알 수 없는 상위 버전은
    그대로 통과시키되(전방 호환), 필드 파싱은 기본값으로 흡수한다.
    """
    version = int(raw.get("version", 0))
    data = dict(raw)

    if version < 1:
        # v0(필드 없음) -> v1: 구조 자체가 v1과 동일하므로 버전만 부여
        data["version"] = 1
        version = 1

    if version < 2:
        data = _migrate_1_to_2(data)
        version = 2

    if version < 3:
        data = _migrate_2_to_3(data)
        version = 3

    return data


def _migrate_1_to_2(data: dict[str, Any]) -> dict[str, Any]:
    """v1 -> v2: `prompt.use_initial_prompt` 기본값을 False로 내린다.

    실측 근거: initial_prompt를 넣으면 Whisper가 오디오 앞부분을 건너뛴다
    (90초 클립에서 25초 누락). hotwords만으로 용어 인식 효과는 유지된다.
    v1에서 값을 명시적으로 저장한 사용자도 이 시점에는 기본값을 그대로 쓴 것이므로
    일괄 False로 내리고, 필요하면 설정이나 `--initial-prompt`로 다시 켠다.
    """
    migrated = dict(data)
    prompt = dict(migrated.get("prompt", {}))
    if prompt.get("use_initial_prompt") is True:
        prompt["use_initial_prompt"] = False
    migrated["prompt"] = prompt
    migrated["version"] = 2
    return migrated


def _migrate_2_to_3(data: dict[str, Any]) -> dict[str, Any]:
    """v2 -> v3: `correction` 섹션 추가(기본 비활성).

    Ollama가 없는 환경이 정상이므로 기존 사용자에게 켜진 채로 내려가면 안 된다.
    """
    migrated = dict(data)
    migrated.setdefault("correction", {})
    migrated["version"] = 3
    return migrated


def settings_path() -> Path:
    """설정 파일 경로. 환경변수로 덮어쓸 수 있다(테스트·다중 프로필용).

    `SETTINGS_PATH` 상수를 쓰지 않고 매번 `default_app_support_dir()`를 다시
    불러 계산한다 — 그래야 `Path.home()`이 나중에 패치돼도(테스트) 반영된다.
    """
    override = os.environ.get("LECTURE_SCRIBE_SETTINGS")
    return _expand(override) if override else default_app_support_dir() / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    """설정 로드. 파일이 없으면 기본 설정을 돌려준다(파일 생성은 하지 않음)."""
    path = path or settings_path()
    if not path.exists():
        return Settings()
    try:
        raw_text = path.read_text(encoding="utf-8")
        raw = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"설정 파일이 손상되어 읽을 수 없습니다: {path}",
            f"JSON 파싱 실패 {path}: {exc}",
        ) from exc
    except OSError as exc:
        raise ConfigError(
            f"설정 파일을 읽을 수 없습니다: {path}",
            f"설정 읽기 실패 {path}: {exc}",
        ) from exc
    if not isinstance(raw, dict):
        raise ConfigError(
            f"설정 파일 형식이 올바르지 않습니다: {path}",
            f"최상위가 dict가 아님: {type(raw)!r}",
        )
    return Settings.from_dict(raw)


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """원자적 저장(임시 파일 + os.replace)."""
    path = path or settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.to_dict(), ensure_ascii=False, indent=2)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".settings-",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            tmp.write(payload + "\n")
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    except OSError as exc:
        raise ConfigError(
            f"설정을 저장하지 못했습니다: {path}",
            f"설정 저장 실패 {path}: {exc}",
        ) from exc
