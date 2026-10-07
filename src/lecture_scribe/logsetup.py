"""로깅 설정.

- 파일 로그: ~/Library/Logs/LectureScribe/lecture-scribe.log (10MB × 3 회전)
- 콘솔 로그: **항상 stderr**. stdout은 `--json` / `--stdout` 결과 전용이다.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

from .config import default_log_dir

_MAX_BYTES: Final[int] = 10 * 1024 * 1024
_BACKUP_COUNT: Final[int] = 3
_ROOT_LOGGER: Final[str] = "lecture_scribe"

#: 테스트가 직접 덮어쓸 수 있다(`tests/test_logsetup.py`). `None`이면 `setup_logging()`/
#: `log_path()`가 호출 시점에 `default_log_dir()`를 계산한다.
#:
#: `config.py`에서 가져온 `Final[Path]` 상수를 여기서 그대로 썼다면, 모듈 임포트
#: 시점에 `Path.home()`이 굳어 버려 테스트가 나중에 `Path.home`을 패치해도 반영이
#: 안 되고 **실제 사용자 로그 파일에 기록하는 사고**가 난다(실측 확인:
#: `test_cli.py`가 `cli.main()`을 인프로세스로 불러 `setup_logging()`을 실행하는데,
#: 그 경로가 격리되지 않아 진짜 `~/Library/Logs/LectureScribe/lecture-scribe.log`에
#: 테스트 트레이스백이 그대로 남았다 — `config.py`의 옛 `settings_path()`가 가졌던
#: 것과 같은 버그다).
LOG_DIR: Path | None = None
LOG_PATH: Path | None = None


def _resolve_log_dir() -> Path:
    return LOG_DIR if LOG_DIR is not None else default_log_dir()


def _resolve_log_path() -> Path:
    if LOG_PATH is not None:
        return LOG_PATH
    return _resolve_log_dir() / "lecture-scribe.log"


def get_logger(name: str = _ROOT_LOGGER) -> logging.Logger:
    return logging.getLogger(name)


def setup_logging(verbosity: int = 0, quiet: bool = False) -> logging.Logger:
    """로거 초기화. 중복 호출해도 핸들러가 늘어나지 않는다."""
    logger = logging.getLogger(_ROOT_LOGGER)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    resolved_log_path = _resolve_log_path()
    file_ok = True
    try:
        resolved_log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            resolved_log_path,
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)
    except OSError:
        file_ok = False

    if quiet:
        console_level = logging.ERROR
    elif verbosity >= 2:
        console_level = logging.DEBUG
    elif verbosity == 1:
        console_level = logging.INFO
    else:
        console_level = logging.WARNING

    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(console)

    if not file_ok:
        logger.warning("로그 파일을 열 수 없어 콘솔에만 기록합니다: %s", resolved_log_path)
    return logger


def log_path() -> Path:
    return _resolve_log_path()
