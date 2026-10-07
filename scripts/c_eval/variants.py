"""교정 프롬프트 가설 변형 (FIX_GUIDE_13 P-01).

앱 코드는 건드리지 않고, 실험 중에만 `correction` 모듈의 함수/상수를 바꿔 끼운다.
채택된 가설만 나중에 correction.py에 반영한다. 가설 하나씩(ablation) 또는 `+`로 결합해 쓴다.

  a  temperature 0
  b  스키마 필드 순서: reason 먼저
  c  예시(few-shot) — 평가 샘플과 무관한 분야(운영체제/컴파일러) 예시만 사용(누수 방지)
  d  "교정하지 않는 것" 예시(올바른 음차·표기 변이·말버릇·수식 기호)
  e  청크 앞뒤 문맥(교정 대상 아님)을 참고로 덧붙임. 검증(source_text)은 본문만 유지
  g  한글 오인식도 대상에 포함(현재 프롬프트는 영어 전문용어 오인식만 겨냥)
  h  수식·확률 표기를 새로 지어내지 말라는 규칙
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from typing import Any

from lecture_scribe import correction
from lecture_scribe.backends.base import Segment

_MARK_TEXT = "녹취록:\n---"

_FEWSHOT = """다음은 다른 분야 강의에서의 예시다(형식과 판단 기준만 참고하라):
- 녹취록: "프로세스가 대기 상태에서 준비 상태로 저이되면 스케줄러가 고릅니다. 링커가 오브젝트 파일을 합칠 때 최적화 옵션 오투를 켜면 …"
  -> {"original": "저이되면", "correction": "전이되면", "reason": "상태 전이 맥락에서 '저이'는 뜻이 통하지 않고 발음이 같다", "confidence": "high"}
  -> {"original": "오투", "correction": "-O2", "reason": "컴파일러 최적화 옵션 맥락의 O2를 발음대로 적은 것", "confidence": "medium"}
"""

_NEGATIVE = """다음은 **교정하면 안 되는** 예시다:
- "심벌"을 "심볼"로, "노이즈"를 "noise"로 바꾸는 것(표기 차이일 뿐 오류가 아님)
- 변수·기호 이름(예: 첨자가 붙은 문자)을 다른 문자로 바꾸는 것. 기호는 발음이 같아도 이름이 다르면 다른 기호다
- "어", "그러니까", "뭐야" 같은 구어체
"""

_KOREAN_RULE = (
    "영어 전문용어뿐 아니라 **일반 한국어 단어**도 발음이 비슷한 다른 말로 잘못 받아쓴 경우"
    "(예: '전이되면'을 '저이되면'으로)를 찾아라. 문맥상 뜻이 통하지 않을 때만 제안하라.\n"
)

_NO_MATH_RULE = (
    "- 수식·확률 표기(P(...) 등)나 첨자를 새로 만들어 넣지 마라. 교정은 발음이 비슷한 "
    "단어·기호로 되돌리는 것뿐이다.\n"
)


def _insert_before_transcript(prompt: str, block: str) -> str:
    assert _MARK_TEXT in prompt
    return prompt.replace(_MARK_TEXT, block + "\n" + _MARK_TEXT, 1)


def _apply_prompt_transform(transform: Callable[[str, str], str]) -> None:
    original_build = correction.build_prompt

    def patched(
        text: str, topic: str, glossary: Sequence[str], slide_terms: Sequence[str] = ()
    ) -> str:
        return transform(original_build(text, topic, glossary, slide_terms), text)

    correction.build_prompt = patched  # type: ignore[assignment]


def apply(names: str, segments: Sequence[Segment]) -> None:
    """`names`는 'a', 'c+d' 같은 문자열. 빈 문자열이면 변형 없음(기준선)."""
    for name in [n for n in names.split("+") if n]:
        if name == "a":
            original_propose = correction.OllamaClient.propose

            def propose0(
                self: correction.OllamaClient,
                prompt: str,
                model: str,
                temperature: float = 0.2,
                *args: Any,
                **kwargs: Any,
            ) -> list[dict[str, Any]]:
                return original_propose(self, prompt, model, 0.0, *args, **kwargs)

            correction.OllamaClient.propose = propose0  # type: ignore[method-assign]
        elif name == "b":
            schema = copy.deepcopy(correction.RESPONSE_SCHEMA)
            item = schema["properties"]["corrections"]["items"]
            props = item["properties"]
            item["properties"] = {k: props[k] for k in ("reason", "original", "correction", "confidence")}
            item["required"] = ["reason", "original", "correction", "confidence"]
            correction.RESPONSE_SCHEMA = schema  # type: ignore[misc]
        elif name == "c":
            _apply_prompt_transform(lambda p, _t: _insert_before_transcript(p, _FEWSHOT))
        elif name == "d":
            _apply_prompt_transform(lambda p, _t: _insert_before_transcript(p, _NEGATIVE))
        elif name == "e":
            lines = [s.text.strip() for s in segments if s.text.strip()]

            def add_context(prompt: str, text: str) -> str:
                body = text.split("\n")
                start = next(
                    (
                        i
                        for i in range(len(lines) - len(body) + 1)
                        if lines[i : i + len(body)] == body
                    ),
                    None,
                )
                if start is None:
                    return prompt
                before = "\n".join(lines[max(0, start - 3) : start])
                after = "\n".join(lines[start + len(body) : start + len(body) + 3])
                extra = (
                    "\n앞뒤 문맥(참고용. 여기 있는 문자열은 original로 쓰지 마라):\n"
                    f"[앞]\n{before or '(없음)'}\n[뒤]\n{after or '(없음)'}\n"
                )
                return prompt + extra

            _apply_prompt_transform(add_context)
        elif name == "g":
            _apply_prompt_transform(
                lambda p, _t: p.replace("규칙:\n", _KOREAN_RULE + "\n규칙:\n", 1)
            )
        elif name == "h":
            _apply_prompt_transform(
                lambda p, _t: p.replace("- \"reason\"은", _NO_MATH_RULE + "- \"reason\"은", 1)
            )
        else:
            raise SystemExit(f"알 수 없는 변형: {name}")
