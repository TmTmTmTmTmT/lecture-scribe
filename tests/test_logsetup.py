"""FIX_GUIDE_4.md A-08: `logsetup.py` 최소 회귀 테스트.

31개 소스 모듈 중 유일하게 테스트가 없던 모듈. 내부 구현에 밀착하지 않고
"중복 호출해도 핸들러가 안 쌓이는지", "로그 파일 경로가 의도한 곳인지",
"verbosity가 콘솔 레벨에 반영되는지"만 본다(가이드 §4 A-08 지시).
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

from lecture_scribe import logsetup


@pytest.fixture(autouse=True)
def _isolated_log_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """실제 `~/Library/Logs/LectureScribe`를 건드리지 않게 임시 경로로 돌린다."""
    log_dir = tmp_path / "Logs"
    log_path = log_dir / "lecture-scribe.log"
    monkeypatch.setattr(logsetup, "LOG_DIR", log_dir)
    monkeypatch.setattr(logsetup, "LOG_PATH", log_path)
    yield log_path
    # 테스트가 남긴 핸들러가 다음 테스트(또는 다른 파일)로 새지 않게 정리한다.
    logger = logging.getLogger("lecture_scribe")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_setup_logging_writes_to_configured_path(_isolated_log_path: Path) -> None:
    logsetup.setup_logging(verbosity=1)
    logging.getLogger("lecture_scribe.test_logsetup").info("hello")
    assert _isolated_log_path.exists()
    assert "hello" in _isolated_log_path.read_text(encoding="utf-8")
    assert logsetup.log_path() == _isolated_log_path


def test_repeated_setup_does_not_stack_handlers(_isolated_log_path: Path) -> None:
    logsetup.setup_logging(verbosity=1)
    first_count = len(logging.getLogger("lecture_scribe").handlers)
    logsetup.setup_logging(verbosity=1)
    logsetup.setup_logging(verbosity=1)
    assert len(logging.getLogger("lecture_scribe").handlers) == first_count


@pytest.mark.parametrize(
    "verbosity,quiet,expected_level",
    [
        (0, False, logging.WARNING),
        (1, False, logging.INFO),
        (2, False, logging.DEBUG),
        (0, True, logging.ERROR),
    ],
)
def test_verbosity_controls_console_level(
    _isolated_log_path: Path, verbosity: int, quiet: bool, expected_level: int
) -> None:
    logsetup.setup_logging(verbosity=verbosity, quiet=quiet)
    console_handlers = [
        h
        for h in logging.getLogger("lecture_scribe").handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert console_handlers, "콘솔 핸들러가 없다"
    assert console_handlers[0].level == expected_level


def test_get_logger_returns_child_of_root_logger() -> None:
    logger = logsetup.get_logger("lecture_scribe.foo")
    assert logger.name == "lecture_scribe.foo"


def test_default_log_path_follows_patched_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """회귀 테스트: 기본 로그 경로가 `Path.home()`을 호출 시점에 다시 계산해야 한다.

    이전엔 `config.py`의 `LOG_DIR`/`LOG_PATH`가 모듈 임포트 시점에 `Final` 상수로
    굳어 있었다. `test_logsetup.py`의 픽스처는 `logsetup.LOG_DIR`/`LOG_PATH`를 직접
    덮어써서 이 문제를 피해 갔지만, `tests/test_cli.py`처럼 `cli.main()`을
    인프로세스로 불러 `setup_logging()`을 그 기본값으로 실행하는 다른 테스트는
    실제 `~/Library/Logs/LectureScribe/lecture-scribe.log`를 건드렸다(실측 확인 —
    이 테스트가 그 클래스의 회귀를 잡는다). 이 테스트는 일부러 `LOG_DIR`/`LOG_PATH`를
    덮어쓰지 않고(기본값 그대로) `Path.home()`만 패치해 기본 경로 계산 자체를 본다.
    """
    monkeypatch.setattr(logsetup, "LOG_DIR", None)
    monkeypatch.setattr(logsetup, "LOG_PATH", None)
    fake_home = Path("/private/tmp/lecture-scribe-log-path-probe")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    assert logsetup.log_path() == fake_home / "Library" / "Logs" / "LectureScribe" / "lecture-scribe.log"
