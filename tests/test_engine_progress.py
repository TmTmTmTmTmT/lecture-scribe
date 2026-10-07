"""FIX_GUIDE.md 실행분 테스트: ETA 이동 평균(G-02), 빈 메시지 stage 인지(G-05)."""

from __future__ import annotations

from pathlib import Path

from lecture_scribe.engine import ProgressEvent, _rolling_eta


def test_rolling_eta_needs_at_least_two_samples() -> None:
    assert _rolling_eta([], total=100.0) is None
    assert _rolling_eta([(1.0, 10.0)], total=100.0) is None


def test_rolling_eta_uses_recent_rate_not_whole_run_average() -> None:
    """전체 평균이 아니라 최근 표본 구간 속도만 본다.

    앞부분이 아무리 빨랐어도(첫 표본 없음), 최근 구간이 느려지면 그 느린
    속도를 기준으로 남은 시간을 낸다 — 예전 방식(경과/percent 전체 평균)처럼
    과거의 빠른 구간에 눌려 실제보다 작게 나오지 않는다.
    """
    # 최근 구간: 10초 동안 오디오 5초만 진행 (배속 0.5x, 아주 느림)
    recent = [(100.0, 50.0), (110.0, 55.0)]
    eta = _rolling_eta(recent, total=100.0)
    assert eta is not None
    # 남은 오디오 = 100*0.97 - 55 = 42.0, 속도 = 5/10 = 0.5 -> eta = 84.0
    assert eta == 84.0


def test_rolling_eta_none_when_no_progress_in_window() -> None:
    """구간 안에서 오디오 진행이 0이면(같은 지점 반복) 나눗셈 대신 None."""
    recent = [(100.0, 50.0), (110.0, 50.0)]
    assert _rolling_eta(recent, total=100.0) is None


def test_progress_event_stage_field_available_for_gui_fallback() -> None:
    """gui/window.py _on_progress가 stage로 빈 메시지를 구분할 수 있어야 한다."""
    event = ProgressEvent(file=Path("x.m4a"), stage="transcribe", percent=10.0)
    assert event.message == ""
    assert event.stage == "transcribe"
