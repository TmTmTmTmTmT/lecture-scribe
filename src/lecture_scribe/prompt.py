"""주제 기반 프롬프트 합성과 토큰 예산 관리 (F-03).

설계 근거:
- Whisper의 프롬프트는 "직전 발화 텍스트"로 취급된다. 따라서 명령문
  (`다음을 정확히 받아써라`)은 효과가 없고 오히려 출력에 섞일 수 있다.
  나열식 키워드보다 **실제 발화처럼 읽히는 문장**이 낫다.
- 프롬프트 토큰 한계는 Whisper 컨텍스트 448의 절반 - 1 = **223 토큰**이다
  (faster-whisper `get_prompt`: `previous_tokens[-(max_length // 2 - 1):]`).
  설정 기본값 224는 여기서 223으로 클램프한다.
- `initial_prompt`와 `hotwords`는 같은 프롬프트 구간(sot_prev)에 함께 들어가므로
  **합산 예산**으로 계산한다.
- 초과분은 용어 목록 뒤쪽부터 잘라내고, 잘린 항목을 반드시 보고한다(§15-7).

이 모듈은 GUI/백엔드에 의존하지 않는 순수 함수다. 토크나이저는 주입받는다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

# 텍스트 -> 토큰 수. 백엔드가 실제 모델 토크나이저를 주입한다.
TokenCounter = Callable[[str], int]

#: Whisper 프롬프트 하드 한계 (max_length // 2 - 1)
PROMPT_TOKEN_HARD_LIMIT: Final[int] = 223

_HANGUL_BASE: Final[int] = 0xAC00
_HANGUL_LAST: Final[int] = 0xD7A3

#: 숫자 끝소리에 받침이 있는지 (0 영, 1 일, 3 삼, 6 육, 7 칠, 8 팔)
_DIGIT_HAS_FINAL: Final[dict[str, bool]] = {
    "0": True,
    "1": True,
    "2": False,
    "3": True,
    "4": False,
    "5": False,
    "6": True,
    "7": True,
    "8": True,
    "9": False,
}


def has_final_consonant(word: str) -> bool:
    """마지막 글자에 받침이 있는지 판단(조사 선택용).

    한글 음절은 정확히 계산하고, 숫자는 읽는 소리 기준으로 판단한다.
    라틴 문자로 끝나면 받침 없음으로 취급한다(예: `S-parameter를`).
    """
    for char in reversed(word.strip()):
        if char.isspace():
            continue
        code = ord(char)
        if _HANGUL_BASE <= code <= _HANGUL_LAST:
            return (code - _HANGUL_BASE) % 28 != 0
        if char in _DIGIT_HAS_FINAL:
            return _DIGIT_HAS_FINAL[char]
        if char.isalpha():
            return False
        # 괄호·기호는 건너뛰고 그 앞 글자로 판단
        continue
    return False


def josa(word: str, with_final: str, without_final: str) -> str:
    """받침 유무에 따라 조사를 고른다. 예: josa('정합', '을', '를') -> '을'."""
    return with_final if has_final_consonant(word) else without_final


@dataclass(slots=True, frozen=True)
class PromptPlan:
    """전사 1회에 사용할 프롬프트 구성과 예산 사용 내역."""

    initial_prompt: str | None
    hotwords: str | None
    used_tokens: int
    budget_tokens: int
    included_terms: list[str] = field(default_factory=list)
    dropped_terms: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.initial_prompt and not self.hotwords

    @property
    def over_budget(self) -> bool:
        return bool(self.dropped_terms)


def synthesize_prompt(
    topic: str, glossary: Sequence[str], *, language: str = "ko"
) -> str:
    """주제와 용어를 '실제 발화처럼 읽히는 문장'으로 조립한다.

    나쁜 예: `임피던스, 정합, 스미스차트, S-parameter`
    좋은 예: `이번 시간에는 임피던스 정합과 스미스 차트를 다룹니다.
              반사계수, S-parameter, 특성 임피던스를 함께 설명합니다.`
    """
    topic = topic.strip()
    terms = [t.strip() for t in glossary if t.strip()]
    if language == "en":
        return _synthesize_en(topic, terms)
    return _synthesize_ko(topic, terms)


def _synthesize_ko(topic: str, terms: Sequence[str]) -> str:
    sentences: list[str] = []
    if topic:
        if _looks_like_sentence(topic):
            sentences.append(topic if topic.endswith((".", "!", "?")) else f"{topic}.")
        else:
            sentences.append(f"이번 시간에는 {topic}{josa(topic, '을', '를')} 다룹니다.")
    if terms:
        joined = ", ".join(terms)
        if sentences:
            sentences.append(f"{joined}{josa(terms[-1], '을', '를')} 함께 설명합니다.")
        else:
            sentences.append(f"{joined}{josa(terms[-1], '에', '에')} 대해 설명합니다.")
    return " ".join(sentences)


def _synthesize_en(topic: str, terms: Sequence[str]) -> str:
    sentences: list[str] = []
    if topic:
        if _looks_like_sentence(topic):
            sentences.append(topic if topic.endswith((".", "!", "?")) else f"{topic}.")
        else:
            sentences.append(f"In this lecture we discuss {topic}.")
    if terms:
        joined = ", ".join(terms)
        sentences.append(f"We also cover {joined}.")
    return " ".join(sentences)


def _looks_like_sentence(text: str) -> bool:
    """이미 문장 형태인지(종결어미/마침표) 대략 판단."""
    stripped = text.strip()
    if stripped.endswith((".", "!", "?", "다", "요")):
        return True
    return False


def build_prompt_plan(
    topic: str,
    glossary: Sequence[str],
    count_tokens: TokenCounter,
    *,
    max_tokens: int = 224,
    use_initial_prompt: bool = True,
    use_hotwords: bool = True,
    repeat_glossary_in_sentence: bool = True,
    language: str = "ko",
) -> PromptPlan:
    """예산 안에 들어가는 프롬프트 구성을 만든다.

    초과하면 용어 목록 **뒤쪽부터** 제거하며, 제거된 항목을 `dropped_terms`와
    `warnings`로 보고한다. 조용히 잘라내지 않는다.
    """
    budget = min(max_tokens, PROMPT_TOKEN_HARD_LIMIT)
    terms = [t.strip() for t in glossary if t.strip()]
    topic = topic.strip()
    warnings: list[str] = []

    if not use_initial_prompt and not use_hotwords:
        return PromptPlan(
            initial_prompt=None,
            hotwords=None,
            used_tokens=0,
            budget_tokens=budget,
            warnings=["프롬프트 사용이 설정에서 꺼져 있습니다."],
        )
    if not topic and not terms:
        return PromptPlan(
            initial_prompt=None,
            hotwords=None,
            used_tokens=0,
            budget_tokens=budget,
        )

    included = list(terms)
    dropped: list[str] = []
    # hotwords가 켜져 있으면 용어가 프롬프트 구간에 이미 들어간다. 문장에까지
    # 중복하면 initial_prompt가 길어져 첫 구간 인식이 나빠지는 사례가 있다.
    sentence_terms_enabled = repeat_glossary_in_sentence or not use_hotwords
    while True:
        initial_prompt = (
            synthesize_prompt(
                topic,
                included if sentence_terms_enabled else [],
                language=language,
            )
            if use_initial_prompt
            else ""
        )
        hotwords = ", ".join(included) if (use_hotwords and included) else ""
        used = _count_combined(initial_prompt, hotwords, count_tokens)
        if used <= budget or not included:
            break
        dropped.insert(0, included.pop())

    if dropped:
        warnings.append(
            f"{len(dropped)}개 용어가 프롬프트에서 제외됨 "
            f"({budget} 토큰 한계 초과): {', '.join(dropped)}"
        )
    if used > budget:
        # 용어를 모두 제거해도 주제 문장만으로 초과하는 경우
        warnings.append(
            f"주제 문장만으로 {used}/{budget} 토큰을 초과합니다. 주제를 줄이세요."
        )

    return PromptPlan(
        initial_prompt=initial_prompt or None,
        hotwords=hotwords or None,
        used_tokens=used,
        budget_tokens=budget,
        included_terms=included,
        dropped_terms=dropped,
        warnings=warnings,
    )


def _count_combined(
    initial_prompt: str, hotwords: str, count_tokens: TokenCounter
) -> int:
    """initial_prompt와 hotwords는 같은 프롬프트 구간에 들어가므로 합산한다.

    faster-whisper는 hotwords를 `" " + hotwords.strip()` 형태로 인코딩한다.
    """
    total = 0
    if initial_prompt:
        total += count_tokens(initial_prompt)
    if hotwords:
        total += count_tokens(" " + hotwords.strip())
    return total


def preview_token_usage(
    topic: str,
    glossary: Sequence[str],
    count_tokens: TokenCounter,
    *,
    max_tokens: int = 224,
    language: str = "ko",
) -> tuple[int, int]:
    """GUI 실시간 표시용: (사용 토큰, 예산). 잘라내지 않은 원본 기준."""
    budget = min(max_tokens, PROMPT_TOKEN_HARD_LIMIT)
    terms = [t.strip() for t in glossary if t.strip()]
    initial_prompt = synthesize_prompt(topic, terms, language=language)
    hotwords = ", ".join(terms)
    return _count_combined(initial_prompt, hotwords, count_tokens), budget


def parse_glossary(raw: str) -> list[str]:
    """쉼표 구분 문자열 -> 용어 목록(공백 제거, 중복 제거, 순서 유지)."""
    seen: set[str] = set()
    terms: list[str] = []
    for chunk in raw.replace("\n", ",").split(","):
        term = chunk.strip()
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms
