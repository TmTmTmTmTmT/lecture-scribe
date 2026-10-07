"""prompt.py — 프롬프트 합성과 토큰 예산 (F-03-1, F-03-2)."""

from __future__ import annotations

import pytest

from lecture_scribe.prompt import (
    PROMPT_TOKEN_HARD_LIMIT,
    build_prompt_plan,
    has_final_consonant,
    josa,
    parse_glossary,
    preview_token_usage,
    synthesize_prompt,
)

TOPIC = "OO대학교 전기공학과 마이크로파공학 강의"
GLOSSARY = ["임피던스 정합", "스미스 차트", "반사계수", "S-parameter", "특성 임피던스"]


def word_counter(text: str) -> int:
    """테스트용 결정적 토큰 카운터(어절 수)."""
    return len(text.split())


# --- 합성 ---------------------------------------------------------------


def test_synthesize_reads_like_speech_not_keywords() -> None:
    text = synthesize_prompt(TOPIC, GLOSSARY)
    assert text.startswith("이번 시간에는 ")
    assert "다룹니다." in text
    assert "함께 설명합니다." in text
    # 나열식 키워드만 있는 형태가 아니어야 한다
    assert not text.startswith("임피던스 정합,")


def test_synthesize_topic_only() -> None:
    assert synthesize_prompt(TOPIC, []) == f"이번 시간에는 {TOPIC}를 다룹니다."


def test_synthesize_glossary_only() -> None:
    text = synthesize_prompt("", ["반사계수", "스미스 차트"])
    assert text == "반사계수, 스미스 차트에 대해 설명합니다."


def test_synthesize_keeps_existing_sentence() -> None:
    text = synthesize_prompt("오늘은 전송선로 이론을 다룹니다.", [])
    assert text == "오늘은 전송선로 이론을 다룹니다."


def test_synthesize_english() -> None:
    text = synthesize_prompt("impedance matching", ["Smith chart"], language="en")
    assert text == "In this lecture we discuss impedance matching. We also cover Smith chart."


def test_josa_selection() -> None:
    assert has_final_consonant("정합") is True
    assert has_final_consonant("차트") is False
    assert has_final_consonant("Z0") is True  # 영 -> 받침 ㅇ
    assert has_final_consonant("Z2") is False  # 이 -> 받침 없음
    assert has_final_consonant("S-parameter") is False
    assert josa("정합", "을", "를") == "을"
    assert josa("차트", "을", "를") == "를"


def test_parse_glossary_trims_and_dedupes() -> None:
    assert parse_glossary(" 임피던스 , 정합,임피던스 ,, \n스미스 차트") == [
        "임피던스",
        "정합",
        "스미스 차트",
    ]


# --- 토큰 예산 ----------------------------------------------------------


def test_plan_within_budget_keeps_all_terms() -> None:
    plan = build_prompt_plan(TOPIC, GLOSSARY, word_counter, max_tokens=224)
    assert plan.dropped_terms == []
    assert plan.included_terms == GLOSSARY
    assert plan.initial_prompt is not None
    assert plan.hotwords == ", ".join(GLOSSARY)
    assert plan.used_tokens <= plan.budget_tokens
    assert plan.warnings == []


def test_plan_truncates_from_the_end_and_warns() -> None:
    plan = build_prompt_plan(TOPIC, GLOSSARY, word_counter, max_tokens=12)
    assert plan.dropped_terms, "예산 초과 시 용어가 잘려야 한다"
    # 뒤쪽부터 제거되므로 앞선 용어가 남는다
    assert plan.included_terms == GLOSSARY[: len(plan.included_terms)]
    assert plan.dropped_terms == GLOSSARY[len(plan.included_terms) :]
    assert plan.used_tokens <= plan.budget_tokens
    assert any("제외됨" in w for w in plan.warnings)
    assert plan.over_budget


def test_plan_never_truncates_silently() -> None:
    plan = build_prompt_plan(TOPIC, GLOSSARY, word_counter, max_tokens=8)
    assert plan.dropped_terms
    assert plan.warnings  # 경고 없이 잘라내면 §15 위반


def test_budget_clamped_to_hard_limit() -> None:
    plan = build_prompt_plan(TOPIC, GLOSSARY, word_counter, max_tokens=10_000)
    assert plan.budget_tokens == PROMPT_TOKEN_HARD_LIMIT


def test_budget_counts_initial_prompt_and_hotwords_together() -> None:
    """둘은 같은 프롬프트 구간(sot_prev)에 들어가므로 합산해야 한다."""
    plan = build_prompt_plan(TOPIC, GLOSSARY, word_counter, max_tokens=224)
    only_prompt = word_counter(plan.initial_prompt or "")
    assert plan.used_tokens > only_prompt


def test_topic_alone_over_budget_warns() -> None:
    long_topic = " ".join(["단어"] * 300)
    plan = build_prompt_plan(long_topic, [], word_counter, max_tokens=224)
    assert any("초과" in w for w in plan.warnings)


def test_use_hotwords_disabled() -> None:
    plan = build_prompt_plan(
        TOPIC, GLOSSARY, word_counter, max_tokens=224, use_hotwords=False
    )
    assert plan.hotwords is None
    assert plan.initial_prompt is not None


def test_use_initial_prompt_disabled() -> None:
    plan = build_prompt_plan(
        TOPIC, GLOSSARY, word_counter, max_tokens=224, use_initial_prompt=False
    )
    assert plan.initial_prompt is None
    assert plan.hotwords == ", ".join(GLOSSARY)


def test_both_disabled_yields_empty_plan() -> None:
    plan = build_prompt_plan(
        TOPIC,
        GLOSSARY,
        word_counter,
        use_initial_prompt=False,
        use_hotwords=False,
    )
    assert plan.is_empty
    assert plan.warnings


def test_empty_input_yields_empty_plan_without_warning() -> None:
    plan = build_prompt_plan("", [], word_counter)
    assert plan.is_empty
    assert plan.warnings == []


def test_preview_token_usage_reports_untruncated() -> None:
    used, budget = preview_token_usage(TOPIC, GLOSSARY, word_counter, max_tokens=12)
    assert budget == 12
    assert used > budget  # 잘라내기 전 원본 기준


# --- 실제 모델 토크나이저 기준 검증 ---------------------------------------


@pytest.mark.integration
def test_real_tokenizer_respects_223_limit() -> None:
    """large-v3 토크나이저로 300개 용어를 넣어도 223 토큰을 넘지 않아야 한다."""
    from lecture_scribe.backends.faster import FasterWhisperBackend

    backend = FasterWhisperBackend(model_name="large-v3")
    try:
        backend.count_tokens("테스트")
    except Exception as exc:  # pragma: no cover - 오프라인 환경
        pytest.skip(f"토크나이저 사용 불가: {exc}")

    glossary = [f"전문용어{i}" for i in range(300)]
    plan = build_prompt_plan(TOPIC, glossary, backend.count_tokens, max_tokens=224)
    assert plan.used_tokens <= PROMPT_TOKEN_HARD_LIMIT
    assert len(plan.dropped_terms) > 0
    assert plan.warnings


def test_repeat_glossary_disabled_keeps_terms_only_in_hotwords() -> None:
    """initial_prompt가 있으면 앞 구간이 누락되는 사례가 있어 문장을 짧게 유지하는 옵션."""
    plan = build_prompt_plan(
        TOPIC,
        GLOSSARY,
        word_counter,
        max_tokens=224,
        repeat_glossary_in_sentence=False,
    )
    assert plan.initial_prompt == f"이번 시간에는 {TOPIC}를 다룹니다."
    assert plan.hotwords == ", ".join(GLOSSARY)
    assert "임피던스" not in (plan.initial_prompt or "")


def test_repeat_glossary_disabled_but_hotwords_off_keeps_terms_in_sentence() -> None:
    """hotwords가 꺼져 있으면 용어를 문장에서 빼면 안 된다(전달 경로가 사라짐)."""
    plan = build_prompt_plan(
        TOPIC,
        GLOSSARY,
        word_counter,
        max_tokens=224,
        use_hotwords=False,
        repeat_glossary_in_sentence=False,
    )
    assert "임피던스 정합" in (plan.initial_prompt or "")


# --- 모델별 용어집 전달 통로 (실측 기반) ------------------------------------------


class _Caps:
    """capabilities()만 흉내 내는 최소 백엔드."""

    def __init__(self, name: str, hotwords: bool) -> None:
        self.name = name
        self._hotwords = hotwords

    def capabilities(self, request: object) -> object:
        from lecture_scribe.backends.base import BackendCapabilities

        return BackendCapabilities(
            hotwords=self._hotwords,
            condition_on_previous_text=True,
            prompt_reset_on_temperature=False,
            temperature_fallback=True,
            hallucination_silence_threshold=True,
            vad_filter=self._hotwords,
            word_timestamps=True,
            batched=False,
        )

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 2)


def _settings_with_glossary(backend: str, model: str):  # type: ignore[no-untyped-def]
    from dataclasses import replace as dc_replace

    from lecture_scribe.config import Preset, Settings

    settings = Settings()
    settings.presets["b"] = Preset(topic="통신 강의", glossary=["AWGN", "열잡음"])
    settings.active_preset = "b"
    return dc_replace(settings, backend=backend, model=model)


def test_turbo_skips_glossary_entirely() -> None:
    """turbo는 용어집 효과가 없는데 hotwords를 넣으면 2.7배 느려진다(실측).

    220초 구간·정답 용어 8개·각 2회:
      large-v3 없음 2/8 -> 용어집 6/8   (효과 큼)
      turbo    없음 2/8 -> 용어집 2/8   (효과 없음), 53초 -> 139~154초
    """
    from lecture_scribe.engine import build_prompt_plan_for

    plan = build_prompt_plan_for(
        _settings_with_glossary("faster", "large-v3-turbo"),
        _Caps("faster", hotwords=True),  # type: ignore[arg-type]
    )
    assert plan.hotwords is None, "turbo에 hotwords를 넣으면 2.7배 손해다"
    assert not plan.initial_prompt, "turbo에는 어느 통로로도 넣지 않는다"


def test_large_v3_keeps_hotwords() -> None:
    """large-v3에서는 용어집이 실제로 작동한다(2/8 -> 6/8)."""
    from lecture_scribe.engine import build_prompt_plan_for

    plan = build_prompt_plan_for(
        _settings_with_glossary("faster", "large-v3"),
        _Caps("faster", hotwords=True),  # type: ignore[arg-type]
    )
    assert plan.hotwords and "AWGN" in plan.hotwords


def test_large_v3_without_hotwords_support_drops_glossary_by_default() -> None:
    """FIX_GUIDE.md G-03: mlx large-v3, initial_prompt 옵션 꺼짐(기본값)이면
    hotwords가 없어도 용어집을 조용히 initial_prompt로 밀어 넣지 않는다.

    예전엔 여기서 무조건 initial_prompt를 켰다 — 사용자가 끈 옵션을 조용히
    재활성화하는 것이었고, 폴백 재전사(detect_head_loss)까지 무장시켰다.
    """
    from lecture_scribe.engine import build_prompt_plan_for

    settings = _settings_with_glossary("mlx", "large-v3")
    assert settings.prompt.use_initial_prompt is False  # 기본값 전제
    plan = build_prompt_plan_for(
        settings,
        _Caps("mlx", hotwords=False),  # type: ignore[arg-type]
    )
    assert plan.hotwords is None
    assert not plan.initial_prompt


def test_large_v3_without_hotwords_support_uses_initial_prompt_when_opted_in() -> None:
    """같은 조건에서 사용자가 initial_prompt 옵션을 켜면 용어집이 전달된다."""
    from dataclasses import replace as dc_replace

    from lecture_scribe.engine import build_prompt_plan_for

    settings = _settings_with_glossary("mlx", "large-v3")
    settings = dc_replace(
        settings, prompt=dc_replace(settings.prompt, use_initial_prompt=True)
    )
    plan = build_prompt_plan_for(
        settings,
        _Caps("mlx", hotwords=False),  # type: ignore[arg-type]
    )
    assert plan.hotwords is None
    assert plan.initial_prompt and "AWGN" in plan.initial_prompt


def test_mlx_turbo_gets_nothing() -> None:
    """turbo면 백엔드와 무관하게 용어집을 넣지 않는다."""
    from lecture_scribe.engine import build_prompt_plan_for

    plan = build_prompt_plan_for(
        _settings_with_glossary("mlx", "large-v3-turbo"),
        _Caps("mlx", hotwords=False),  # type: ignore[arg-type]
    )
    assert plan.hotwords is None
    assert not plan.initial_prompt


def test_turbo_detection_is_case_insensitive() -> None:
    from lecture_scribe.engine import _is_turbo

    assert _is_turbo("large-v3-turbo")
    assert _is_turbo("LARGE-V3-TURBO")
    assert not _is_turbo("large-v3")
    assert not _is_turbo("medium")
