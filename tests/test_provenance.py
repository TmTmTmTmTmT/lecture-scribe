"""실행 중인 코드의 출처 추적.

이 모듈이 존재하는 이유: 앱을 켜 둔 채 소스를 고치면 파이썬은 이미 불러온 모듈을
다시 읽지 않는다. 그래서 **이미 고친 버그가 그대로 재현되는 것처럼 보인다.**
2026-09-04에 실제로 그렇게 오진했다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lecture_scribe import provenance


def test_fingerprint_covers_bug_prone_modules() -> None:
    stamps = provenance.source_fingerprint()
    for name in ("engine", "backends/mlx", "gui/window", "correction"):
        assert name in stamps, f"{name}의 수정 시각을 추적하지 않는다"


def test_fingerprint_values_look_like_timestamps() -> None:
    for value in provenance.source_fingerprint().values():
        assert len(value) == 14  # "MM-DD HH:MM:SS"
        assert value[2] == "-" and value[5] == " "


def test_no_stale_sources_right_after_load() -> None:
    """방금 불러왔으면 낡은 것이 없어야 한다(오탐 방지)."""
    assert provenance.stale_sources() == []
    assert provenance.stale_warning() is None


def test_stale_source_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """소스가 프로세스 적재 시각보다 새로우면 잡아내야 한다.

    `now - 3600`처럼 상대 시각을 쓰면 최근 한 시간 안에 고친 파일이 없을 때 실패한다
    (실제로 깨졌다). 에포크로 고정해 벽시계와 무관하게 만든다.
    """
    monkeypatch.setattr(provenance, "_LOADED_AT", 0.0)
    stale = provenance.stale_sources()
    assert stale, "소스가 더 새로운데 낡음을 감지하지 못했다"

    warning = provenance.stale_warning()
    assert warning is not None
    assert "다시 실행" in warning
    assert stale[0] in warning


def test_stale_check_survives_missing_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """번들 실행처럼 .py가 없어도 예외 없이 빈 결과를 준다."""
    monkeypatch.setattr(provenance, "_TRACKED", ("존재하지않는모듈",))
    assert provenance.stale_sources() == []
    assert provenance.source_fingerprint() == {}
    assert provenance.newest_source_time() == "(번들)"


def test_log_startup_records_version_and_pid(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.INFO):
        provenance.log_startup("테스트")
    joined = "\n".join(r.message for r in caplog.records)
    assert "테스트 시작" in joined
    assert "수정 시각" in joined
