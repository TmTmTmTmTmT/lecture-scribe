"""전사 후처리: 용어 교정, 반복 감지, 출력 붕괴 감지 (F-03-4, F-04).

- 요약·윤문·재작성은 하지 않는다. 축자 전사를 유지한 채 **표기만** 바로잡는다(§15-1).
- 정확 매칭 치환은 항상 동작하고, rapidfuzz 유사도 치환은 기본 비활성이다.
- 교정 내역은 `원문 → 교정` 형태로 로그에 남긴다.
- GUI/백엔드에 의존하지 않는 순수 함수.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Final, Sequence

from .backends.base import Segment

#: 붕괴 판정: 이 길이(초) 이상인데 출력이 사실상 비어 있으면 이상으로 본다
_MIN_DURATION_FOR_COLLAPSE_CHECK: Final[float] = 10.0
#: 붕괴 판정: **발화 구간** 초당 글자 수가 이 값 미만이면 이상으로 본다.
#: 정상 한국어 강의는 초당 5~10자다(large-v3 실측 7.5자/초). 0.8은 매우 보수적인 값이다.
#: VAD 이후 길이를 모르면 전체 길이 기준으로 더 느슨한 값(_MIN_CHARS_PER_TOTAL_SEC)을 쓴다.
_MIN_CHARS_PER_SPEECH_SEC: Final[float] = 0.8
_MIN_CHARS_PER_TOTAL_SEC: Final[float] = 0.15
#: 붕괴 판정: 동일 문장이 전체 세그먼트의 이 비율 이상이면 반복 붕괴로 본다
_REPEAT_COLLAPSE_RATIO: Final[float] = 0.6


@dataclass(slots=True, frozen=True)
class CorrectionEntry:
    """교정 1건. `원문 → 교정 (n회)`."""

    source: str
    target: str
    count: int
    fuzzy: bool = False

    def format(self) -> str:
        kind = "유사" if self.fuzzy else "정확"
        return f"{self.source} → {self.target} ({self.count}회, {kind})"


@dataclass(slots=True)
class CorrectionResult:
    """교정 결과."""

    segments: list[Segment]
    log: list[CorrectionEntry] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return sum(entry.count for entry in self.log)


# --- 정확 매칭 치환 -----------------------------------------------------


def apply_corrections(
    segments: Sequence[Segment], corrections: dict[str, str]
) -> CorrectionResult:
    """치환 사전 기반 정확 매칭 교정.

    긴 키부터 적용해 부분 문자열이 먼저 치환되는 문제를 피한다.
    """
    if not corrections:
        return CorrectionResult(segments=list(segments))

    ordered = sorted(corrections.items(), key=lambda kv: len(kv[0]), reverse=True)
    counts: Counter[tuple[str, str]] = Counter()
    updated: list[Segment] = []

    for segment in segments:
        text = segment.text
        for source, target in ordered:
            if not source or source == target:
                continue
            occurrences = text.count(source)
            if occurrences:
                text = text.replace(source, target)
                counts[(source, target)] += occurrences
        updated.append(replace(segment, text=text) if text != segment.text else segment)

    log = [
        CorrectionEntry(source=source, target=target, count=count)
        for (source, target), count in counts.items()
    ]
    log.sort(key=lambda entry: entry.count, reverse=True)
    return CorrectionResult(segments=updated, log=log)


# --- 유사도 치환 (rapidfuzz, 기본 비활성) --------------------------------


class FuzzyUnavailableError(RuntimeError):
    """rapidfuzz 미설치."""


def fuzzy_available() -> bool:
    try:
        import rapidfuzz  # noqa: F401
    except ImportError:
        return False
    return True


def apply_fuzzy_corrections(
    segments: Sequence[Segment],
    glossary: Sequence[str],
    *,
    threshold: int = 88,
) -> CorrectionResult:
    """용어 목록 기준 유사도 치환.

    용어의 어절 수만큼 창을 밀며 비교한다. 임계값 이상이면 용어 표기로 통일한다.
    이미 정확히 일치하는 구간은 건드리지 않는다.
    """
    terms = [t.strip() for t in glossary if t.strip()]
    if not terms:
        return CorrectionResult(segments=list(segments))
    try:
        from rapidfuzz import fuzz
    except ImportError as exc:  # pragma: no cover - 선택 의존성
        raise FuzzyUnavailableError(
            "rapidfuzz가 설치되어 있지 않습니다. `uv sync --extra fuzzy`"
        ) from exc

    counts: Counter[tuple[str, str]] = Counter()
    updated: list[Segment] = []
    max_words = max(len(term.split()) for term in terms)

    for segment in segments:
        original = segment.text
        leading = original[: len(original) - len(original.lstrip())]
        trailing = original[len(original.rstrip()) :]
        words = original.split()
        if not words:
            updated.append(segment)
            continue

        changed = False
        index = 0
        result_words: list[str] = []
        while index < len(words):
            matched = False
            for size in range(min(max_words, len(words) - index), 0, -1):
                window = " ".join(words[index : index + size])
                best_term: str | None = None
                best_score = float(threshold)
                for term in terms:
                    if len(term.split()) != size:
                        continue
                    if window == term:
                        best_term = None
                        break
                    score = fuzz.ratio(window, term)
                    if score >= best_score:
                        best_score = score
                        best_term = term
                if best_term is not None:
                    result_words.append(best_term)
                    counts[(window, best_term)] += 1
                    index += size
                    matched = True
                    changed = True
                    break
            if not matched:
                result_words.append(words[index])
                index += 1

        if changed:
            updated.append(
                replace(segment, text=f"{leading}{' '.join(result_words)}{trailing}")
            )
        else:
            updated.append(segment)

    log = [
        CorrectionEntry(source=source, target=target, count=count, fuzzy=True)
        for (source, target), count in counts.items()
    ]
    log.sort(key=lambda entry: entry.count, reverse=True)
    return CorrectionResult(segments=updated, log=log)


# --- 반복 / 붕괴 감지 ----------------------------------------------------


@dataclass(slots=True, frozen=True)
class RepeatRun:
    """동일 문장이 연속 반복된 구간."""

    text: str
    count: int
    start: float
    end: float

    def describe(self) -> str:
        return (
            f"[{_hms(self.start)}–{_hms(self.end)}] 동일 문장 {self.count}회 연속 반복: "
            f"{self.text[:40]}"
        )


def _hms(seconds: float) -> str:
    total = int(max(0.0, seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def normalize_for_compare(text: str) -> str:
    """비교용 정규화: 공백 축약 + 문장부호 제거."""
    return re.sub(r"[\s.,!?…·]+", "", text).strip()


def find_repeat_runs(
    segments: Sequence[Segment], min_count: int = 3
) -> list[RepeatRun]:
    """동일 문장이 min_count회 이상 연속 반복되는 구간을 찾는다."""
    runs: list[RepeatRun] = []
    if not segments:
        return runs

    run_key = normalize_for_compare(segments[0].text)
    run_start_index = 0
    for index in range(1, len(segments) + 1):
        key = (
            normalize_for_compare(segments[index].text)
            if index < len(segments)
            else None
        )
        if key != run_key:
            length = index - run_start_index
            if run_key and length >= min_count:
                runs.append(
                    RepeatRun(
                        text=segments[run_start_index].text.strip(),
                        count=length,
                        start=segments[run_start_index].start,
                        end=segments[index - 1].end,
                    )
                )
            run_key = key or ""
            run_start_index = index
    return runs


def find_repeated_phrases(text: str, min_repeats: int = 4) -> tuple[str, int] | None:
    """한 세그먼트 **안에서** 같은 어절이 연속 반복되는지 찾는다.

    세그먼트 사이 반복은 `find_repeat_runs`가 잡지만, 붕괴한 모델은
    `확보 확보 확보 확보 …`처럼 **한 세그먼트 안에서** 반복을 뱉는다(실측).
    """
    words = [w for w in normalize_for_compare_words(text) if w]
    if len(words) < min_repeats:
        return None
    best: tuple[str, int] | None = None
    run_word = words[0]
    run_len = 1
    for word in words[1:]:
        if word == run_word:
            run_len += 1
        else:
            if run_len >= min_repeats and (best is None or run_len > best[1]):
                best = (run_word, run_len)
            run_word = word
            run_len = 1
    if run_len >= min_repeats and (best is None or run_len > best[1]):
        best = (run_word, run_len)
    return best


def normalize_for_compare_words(text: str) -> list[str]:
    """비교용 어절 목록(문장부호 제거)."""
    return [re.sub(r"[\s.,!?…·]+", "", token) for token in text.split()]


def detect_collapse(
    segments: Sequence[Segment],
    duration_sec: float,
    *,
    initial_prompt: str | None = None,
    speech_duration_sec: float | None = None,
) -> str | None:
    """프롬프트로 인한 출력 붕괴 의심 여부. 사유 문자열 또는 None.

    파인튜닝 모델이나 특정 조건에서 프롬프트가 출력을 무너뜨리는 사례가 보고되어
    있으므로, 이 판정을 근거로 **프롬프트 없이 재전사**하는 폴백 경로를 쓴다(§F-03-3).
    """
    if duration_sec < _MIN_DURATION_FOR_COLLAPSE_CHECK:
        return None

    joined = " ".join(segment.text.strip() for segment in segments).strip()
    if not segments or not joined:
        return "출력이 비어 있음"

    chars = len(normalize_for_compare(joined))
    # VAD가 알려준 **발화 구간** 길이를 쓰면 무음이 긴 녹음에서도 오탐이 없다.
    if speech_duration_sec is not None and speech_duration_sec > 5.0:
        per_speech = chars / speech_duration_sec
        if per_speech < _MIN_CHARS_PER_SPEECH_SEC:
            return (
                f"출력량 비정상(발화 {speech_duration_sec:.0f}초에 {chars}자, "
                f"초당 {per_speech:.2f}자)"
            )
    else:
        chars_per_sec = chars / max(duration_sec, 1.0)
        if chars_per_sec < _MIN_CHARS_PER_TOTAL_SEC:
            return f"출력량 비정상(초당 {chars_per_sec:.3f}자)"

    # 한 세그먼트 안의 반복 루프
    for segment in segments:
        repeated = find_repeated_phrases(segment.text)
        if repeated is not None:
            word, count = repeated
            return f"한 구간에서 '{word}'가 {count}회 연속 반복(반복 루프)"

    if initial_prompt:
        prompt_key = normalize_for_compare(initial_prompt)
        output_key = normalize_for_compare(joined)
        if prompt_key and output_key.startswith(prompt_key[: max(8, len(prompt_key) // 2)]):
            if len(output_key) <= len(prompt_key) * 1.5:
                return "출력이 프롬프트 반향으로 채워짐"

    if len(segments) >= 5:
        counter = Counter(normalize_for_compare(s.text) for s in segments if s.text.strip())
        if counter:
            _, top_count = counter.most_common(1)[0]
            if top_count / len(segments) >= _REPEAT_COLLAPSE_RATIO:
                return f"동일 문장이 전체의 {top_count}/{len(segments)}를 차지(반복 붕괴)"
    return None


def detect_head_loss(
    segments: Sequence[Segment],
    first_speech_sec: float,
    *,
    tolerance_sec: float = 5.0,
) -> str | None:
    """앞 구간 누락 판정.

    `initial_prompt`를 넣으면 Whisper가 프롬프트를 "이미 말한 내용"으로 해석해
    오디오 앞부분을 건너뛰는 사례가 실측으로 확인되었다(45분 강의 90초 발췌에서
    프롬프트 유무만 바꿔 3회 재현). 발화 시작 시각보다 첫 세그먼트가
    tolerance_sec 이상 늦으면 누락으로 본다.
    """
    if not segments:
        return None
    gap = segments[0].start - first_speech_sec
    if gap >= tolerance_sec:
        return (
            f"앞 구간 {gap:.1f}초 누락 의심"
            f"(발화 시작 {first_speech_sec:.1f}초, 첫 세그먼트 {segments[0].start:.1f}초)"
        )
    return None


#: 한국어 조사 — 명사 뒤에 붙어 빈도 집계를 망친다(우리+가, 잡음+은 …).
#: 긴 것부터 벗겨야 `에서`가 `서`로 잘리지 않는다.
_PARTICLES: Final[tuple[str, ...]] = (
    "에서는", "에서도", "으로는", "이라고", "라고는", "에게서", "한테서",
    "에서", "에게", "한테", "으로", "라고", "처럼", "보다", "부터", "까지",
    "만큼", "조차", "마저", "이나", "든지", "라는", "이라", "와의", "과의",
    "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "로", "와", "과", "야",
)

#: 용어 후보에서 제외할 기능어·일반어(조사를 벗긴 뒤 비교한다)
_GLOSSARY_STOPWORDS: Final[frozenset[str]] = frozenset(
    """
    그거 이거 저거 여기 저기 거기 우리 저희 여러분 오늘 지금 이제 다시 먼저 나중 이번 저번
    그리고 그런데 하지만 그러면 그래서 따라서 만약 만일 경우 때문 정도 자체 관련 이런 저런 그런
    다음 이전 처음 마지막 부분 내용 방법 문제 결과 사용 필요 가능 확인 생각 이야기 설명 시간 사람
    하나 둘 셋 첫번째 두번째 세번째 번째 개요 전체 모두 각각 서로 항상 보통 조금 많이 아주 정말
    있다 없다 하다 되다 이다 같다 보다 주다 받다 알다 시작 종료 그것 이것 저것 무엇 누구 어디
    어떻 어떤 어떠 이렇 저렇 그렇 뭐야 그럼 근데 아니 그냥 진짜 대해 위해 통해 대한 위한 통한
    학기 수업 강의 학생 교수 시험 과제 질문 대답 학점 출석 공부 내년 작년 올해 학교 학과
    여러분들 그다음 그러다 그랬죠 그러면서 그런거 이런거 저런거 뭐냐면 그러니 이러 저러
    말씀 얘기 이야기들 사람들 학생들 친구들 선생님 여기까지 어쨌든 아무튼 물론 사실
    배웠 배운 봤어 했어 하는 되는 있는 없는 같은 하고 되고 라서 니까 는데 습니 입니 니다
    """.split()
)
#: 동사·형용사 활용형과 부사를 걸러내는 어미 패턴.
#: 형태소 분석기(KoNLPy 등)를 쓰면 정확하지만 새 의존성이 필요해 규칙으로 처리한다.
_CONJUGATION_SUFFIXES: Final[tuple[str, ...]] = (
    "습니다", "합니다", "입니다", "됩니다", "십니다", "니다", "세요", "예요", "에요",
    "어요", "아요", "해요", "지요", "대요", "게요", "거야", "거예요", "잖아", "잖아요",
    "니까", "으니까", "해서", "하서", "에서", "면서", "으면", "는데", "려고", "도록",
    "겠어", "었어", "았어", "했어", "봤어", "왔어", "갔어", "이죠", "지만", "든지",
    "라도", "든가", "거든", "구요", "고요", "네요", "군요", "든데", "테니",
    # FIX_GUIDE_14 G-01 추가분(실측: 프리셋 통계 파일 + E-01 평가 전사문에서 발견된 잡음).
    # 짧은 명사와 겹칠 위험이 낮은, 동사·형용사 활용형에 특화된 어미만 골랐다.
    "들어", "뀌어", "니라", "나요", "해봐", "는거", "했",
)
#: 부사·수식어로 끝나는 짧은 말(이렇게, 어떻게, 열심히 …). 짧은 단어에만 적용한다
#: (길면 우연히 이 글자로 끝나는 명사일 가능성이 커진다).
_ADVERB_ENDINGS: Final[tuple[str, ...]] = (
    "게", "히", "서", "며", "고", "면", "지", "하", "해", "될", "함", "적",
)
#: 관형형·연결형 어미(FIX_GUIDE_14 G-01). `_ADVERB_ENDINGS`와 달리 **길이 제한 없이**
#: 적용한다 — 실측(`설명할`, `나타낸`, `커질수록`)이 모두 3~4글자라 길이 제한을 두면
#: 못 걸렀다. `한`/`된`도 원래 `_ADVERB_ENDINGS`에서 4글자 이하로 제한돼 있었는데, 여기로
#: 옮겨 제한을 없앤다.
_ATTRIBUTIVE_ENDINGS: Final[tuple[str, ...]] = (
    "할", "낸", "른", "린", "운", "던", "수록", "는지", "을지", "한", "된",
)
#: 조사로 끝나면 길이와 무관하게 제외한다(FIX_GUIDE_14 G-01). `strip_particle`은 벗긴
#: 나머지가 의미 있는 길이일 때만 벗기므로, `이만큼`(3글자)처럼 짧은 지시어+조사는
#: 안 벗겨지고 그대로 후보가 됐다(실측: 실제 프리셋 용어집에서 발견).
_ALWAYS_EXCLUDE_PARTICLE_ENDINGS: Final[tuple[str, ...]] = (
    "만큼", "처럼", "보다", "까지", "부터",
)
#: 강의 잡담·환각 자막에 흔한 영어 일상어(FIX_GUIDE_14 G-01). 실측(프리셋 통계 파일에서
#: 발견): `going`, `stop`, `here`, `to`, `sorry`가 전부 Whisper 환각 구간의 단어였다.
_EN_CHATTER_WORDS: Final[frozenset[str]] = frozenset(
    "going stop here sorry okay yeah thank thanks please really actually right okay".split()
)

#: 용어 후보 최소 등장 횟수(서로 다른 구간 기준)
_GLOSSARY_MIN_SEGMENTS: Final[int] = 3


def strip_particle(word: str) -> str:
    """한국어 조사를 벗긴다. `우리가` -> `우리`, `잡음은` -> `잡음`."""
    for particle in _PARTICLES:
        if len(word) > len(particle) + 1 and word.endswith(particle):
            return word[: -len(particle)]
    return word


def _is_domain_candidate_english(word: str) -> bool:
    """영문 후보 필터(FIX_GUIDE_14 G-01).

    `AWGN`처럼 대문자가 이어지거나 `5G`/`h1`처럼 숫자가 섞이면 약어·기호일 가능성이
    높아 그대로 인정한다. 그 외 순수 영단어는 5글자 이상이고 강의 잡담·일상어가
    아닐 때만 인정한다 — 짧은 일상어(`to`, `stop`, `here`)와 환각 자막(`going`,
    `sorry` 등)이 이전에는 2글자 이상이면 전부 통과해 실제 통계 파일에 섞여 들어갔다.
    """
    if re.search(r"[0-9]", word):
        return True
    if re.search(r"[A-Z]{2,}", word):
        return True
    return len(word) >= 5 and word.lower() not in _EN_CHATTER_WORDS


def _is_domain_candidate(word: str) -> bool:
    """전문 용어로 볼 만한지.

    일반 대화어를 걸러내려면 빈도만으로는 부족하다(실측: 1차 시도에서 `우리가`,
    `어떻게`가 상위를 차지했다). 명사가 아닌 활용형·부사를 규칙으로 걸러낸다.
    - 조사로 끝나면(길이 무관) 제외한다
    - 라틴 문자·숫자를 포함하면 `_is_domain_candidate_english`로 따로 판단한다
    - 순한글은 3글자 이상만 본다(2글자는 기능어가 대부분)
    - 동사·형용사 활용형(길이 무관)과 부사형 어미(짧은 단어만)로 끝나면 제외한다
    """
    if word.endswith(_ALWAYS_EXCLUDE_PARTICLE_ENDINGS):
        return False
    if re.search(r"[A-Za-z]", word):
        return _is_domain_candidate_english(word)
    if len(word) < 3:
        return False
    if word.endswith(_CONJUGATION_SUFFIXES) or word.endswith(_ATTRIBUTIVE_ENDINGS):
        return False
    if len(word) <= 4 and word.endswith(_ADVERB_ENDINGS):
        return False
    return True


def suggest_glossary_terms(
    segments: Sequence[Segment],
    existing: Sequence[str] = (),
    *,
    limit: int = 12,
    min_segments: int = _GLOSSARY_MIN_SEGMENTS,
    min_logprob: float = -0.5,
) -> list[tuple[str, int]]:
    """전사문에서 다음 강의에 쓸 용어 후보를 뽑는다.

    **신뢰도가 높은 구간만** 본다. 잘못 인식된 단어를 용어집에 넣으면 다음 전사에서
    그 오류가 고착되기 때문이다(실측: 1차 결과를 그대로 재투입했더니 `가우션`이
    hotwords로 들어가 오류가 늘었다).

    한 구간에서 여러 번 반복된 단어보다 **여러 구간에 걸쳐 나온 단어**를 우선한다.

    Returns: [(용어, 등장 구간 수)] — 내림차순.
    """
    known = {strip_particle(term.strip()) for term in existing if term.strip()}
    known |= {term.strip() for term in existing if term.strip()}
    segment_counts: Counter[str] = Counter()
    total_counts: Counter[str] = Counter()
    for segment in segments:
        if segment.avg_logprob < min_logprob:
            continue  # 신뢰도 낮은 구간의 단어는 후보로 쓰지 않는다
        seen_here: set[str] = set()
        for raw in re.findall(r"[가-힣]+|[A-Za-z][A-Za-z0-9\-]+", segment.text):
            word = strip_particle(raw)
            if word in _GLOSSARY_STOPWORDS or word in known:
                continue
            if not _is_domain_candidate(word):
                continue
            total_counts[word] += 1
            seen_here.add(word)
        for word in seen_here:
            segment_counts[word] += 1
    ranked = [
        (word, count)
        for word, count in segment_counts.most_common(limit * 4)
        if count >= min_segments
    ]
    return ranked[:limit]


def build_header_notes(
    repeats: Sequence[RepeatRun],
    corrections: Sequence[CorrectionEntry],
    *,
    include_corrections: bool = False,
    foreign_runs: Sequence["ForeignScriptRun"] = (),
) -> list[str]:
    """결과 파일 상단 주석(옵션). 반복/외래 문자 경고를 사람이 읽을 수 있게 남긴다."""
    notes = [run.describe() for run in repeats]
    notes.extend(run.describe() for run in foreign_runs)
    if include_corrections and corrections:
        notes.extend(f"용어 교정: {entry.format()}" for entry in corrections)
    return notes


# --- 기대 언어 밖 문자(한자/가나/키릴 등) 환각 검출 (FIX_GUIDE_5.md B-02) ---
#
# `language="ko"`를 줘도 무음·잡음 구간에서 CJK/가나 등으로 새는 것이
# Whisper의 알려진 실패 모드다(FIX_GUIDE_5.md §2). 삭제·치환은 하지 않고
# **표시만** 한다(CLAUDE.md §15-1·10 축자 전사 원칙).

#: 기대 문자로 보는 유니코드 범위: 한글 음절/자모 + 라틴(확장 포함, 발음 부호 대응)
_EXPECTED_LETTER_RANGES: Final[tuple[tuple[int, int], ...]] = (
    (0xAC00, 0xD7A3),  # 한글 음절
    (0x1100, 0x11FF),  # 한글 자모
    (0x3130, 0x318F),  # 한글 호환 자모
    (0x0041, 0x005A),  # A-Z
    (0x0061, 0x007A),  # a-z
    (0x00C0, 0x024F),  # 라틴 확장(à, é, ñ 등 — 외래어 표기 대응)
)

#: 검출 판정 기본값. FIX_GUIDE_5.md §5-2 실측으로 확정한다(현재는 초기 제안값).
DEFAULT_FOREIGN_SCRIPT_RATIO: Final[float] = 0.3
DEFAULT_FOREIGN_SCRIPT_MIN_COUNT: Final[int] = 2


def _is_expected_letter(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _EXPECTED_LETTER_RANGES)


def foreign_script_stats(text: str) -> tuple[int, int]:
    """(기대 문자 밖 글자 수, 전체 글자 수). 공백·기본 문장부호는 분모에서 제외.

    분모·정규화는 `normalize_for_compare`와 동일 기준을 쓴다(일관성).
    숫자·기호(문장부호 제거 후 남는 것)는 외래로 세지 않는다 — 알파벳 문자만 본다.
    """
    compact = normalize_for_compare(text)
    total = len(compact)
    foreign = sum(1 for ch in compact if ch.isalpha() and not _is_expected_letter(ch))
    return foreign, total


def is_foreign_script_segment(
    segment: Segment,
    *,
    ratio: float = DEFAULT_FOREIGN_SCRIPT_RATIO,
    min_count: int = DEFAULT_FOREIGN_SCRIPT_MIN_COUNT,
) -> bool:
    """이 세그먼트가 기대 언어(한글/영문) 밖 문자로 채워져 있는지.

    비율과 절대 개수를 **둘 다** 요구한다 — 비율만 쓰면 짧은 세그먼트에서
    오탐이 늘고, 개수만 쓰면 긴 세그먼트에 낀 한자 한두 자를 놓친다(FIX_GUIDE_5.md §4-2).
    """
    foreign, total = foreign_script_stats(segment.text)
    if total == 0 or foreign < min_count:
        return False
    return (foreign / total) >= ratio


@dataclass(slots=True, frozen=True)
class ForeignScriptRun:
    """기대 언어 밖 문자로 채워진 세그먼트가 연속된 구간."""

    text: str
    count: int
    start: float
    end: float
    segment_ids: tuple[int, ...] = ()

    def describe(self) -> str:
        return (
            f"[{_hms(self.start)}–{_hms(self.end)}] 기대 언어 밖 문자 감지"
            f"({self.count}구간, 인식 실패 가능성): {self.text[:40]}"
        )


def find_foreign_script_runs(
    segments: Sequence[Segment],
    *,
    ratio: float = DEFAULT_FOREIGN_SCRIPT_RATIO,
    min_count: int = DEFAULT_FOREIGN_SCRIPT_MIN_COUNT,
) -> list[ForeignScriptRun]:
    """기대 언어 밖 문자 세그먼트를 연속 구간으로 묶어 돌려준다.

    호출부는 이 결과로 **표시만** 한다 — 세그먼트를 지우거나 바꾸지 않는다.
    언어 판단(예: 실제로 중국어/일본어 강의인 경우 비활성화)은 호출부 책임이다.
    """
    runs: list[ForeignScriptRun] = []
    current: list[Segment] = []
    for segment in segments:
        if is_foreign_script_segment(segment, ratio=ratio, min_count=min_count):
            current.append(segment)
            continue
        if current:
            runs.append(_build_foreign_run(current))
            current = []
    if current:
        runs.append(_build_foreign_run(current))
    return runs


def _build_foreign_run(group: Sequence[Segment]) -> ForeignScriptRun:
    return ForeignScriptRun(
        text=group[0].text.strip(),
        count=len(group),
        start=group[0].start,
        end=group[-1].end,
        segment_ids=tuple(s.id for s in group),
    )


def foreign_script_segment_ids(runs: Sequence[ForeignScriptRun]) -> frozenset[int]:
    """검출 구간에 속한 세그먼트 id 전부(저신뢰 마커 강제 표시용)."""
    return frozenset(sid for run in runs for sid in run.segment_ids)
