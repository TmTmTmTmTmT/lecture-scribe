"""FIX_GUIDE_4.md A-02 §5-2 게이트 통과 후 실행분: 백엔드별 기본값 분기.

§5-2 정식 게이트(실사용 3462초 파일 풀 런) 결과 mlx는 `condition_on_previous_text`
기본값을 끔으로 내렸다(속도 2.2배, 외국어 혼입 89% 감소, 저신뢰 비율 개선,
반복 루프 동률 — 5개 중 나빠진 항목 없음). faster-whisper는 이 게이트와 무관해
그대로 켬을 유지한다. `engine.build_request()`가 `settings.backend`를 보고
올바른 필드를 골라야 한다.
"""

from __future__ import annotations

from pathlib import Path

from lecture_scribe.config import Settings
from lecture_scribe.engine import build_request


def test_mlx_backend_uses_mlx_specific_default_off() -> None:
    settings = Settings(backend="mlx")
    assert settings.prompt.condition_on_previous_text_mlx is False  # 게이트 통과 기본값

    request = build_request(Path("강의.m4a"), settings)
    assert request.condition_on_previous_text is False


def test_faster_backend_uses_shared_field_default_on() -> None:
    settings = Settings(backend="faster")
    assert settings.prompt.condition_on_previous_text is True  # 원래 기본값, 안 바뀜

    request = build_request(Path("강의.m4a"), settings)
    assert request.condition_on_previous_text is True


def test_explicit_mlx_override_is_respected() -> None:
    """사용자가 GPU에서 명시적으로 켜면(고급 설정) 그 값을 존중한다."""
    from dataclasses import replace

    settings = Settings(backend="mlx")
    settings = replace(
        settings,
        prompt=replace(settings.prompt, condition_on_previous_text_mlx=True),
    )
    request = build_request(Path("강의.m4a"), settings)
    assert request.condition_on_previous_text is True


def test_faster_backend_ignores_mlx_specific_field() -> None:
    """faster를 쓸 때는 mlx 전용 필드를 꺼도(기본값) 영향받지 않는다."""
    settings = Settings(backend="faster")
    assert settings.prompt.condition_on_previous_text_mlx is False
    assert settings.prompt.condition_on_previous_text is True

    request = build_request(Path("강의.m4a"), settings)
    assert request.condition_on_previous_text is True
