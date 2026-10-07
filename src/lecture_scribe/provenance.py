"""실행 중인 코드의 출처를 기록한다.

소스에서 실행할 때 파이썬은 **이미 불러온 모듈을 다시 읽지 않는다.** 그래서
앱을 켜 둔 채 코드를 고치면, 고치기 전 코드가 계속 돈다. 실제로 이것 때문에
이미 고친 버그가 "여전히 재현된다"고 오진된 적이 있다(2026-09-04).

시작할 때 버전과 **핵심 모듈의 수정 시각**을 남겨 두면, 로그만 보고
"이 로그를 남긴 프로세스가 어느 시점 코드였는지"를 바로 알 수 있다.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from .logsetup import get_logger

logger = get_logger(__name__)

#: 이 모듈이 처음 불린 시각 = 프로세스가 코드를 읽어 들인 시각의 근사값.
#: 이후에 수정된 소스는 **이 프로세스에 반영되어 있지 않다.**
_LOADED_AT: float = time.time()

#: 수정 시각을 확인할 모듈. 버그가 자주 나는 곳 위주.
_TRACKED = (
    "engine",
    "correction",
    "backends/mlx",
    "backends/faster",
    "gui/window",
    "gui/dropzone",
)


def source_fingerprint() -> dict[str, str]:
    """추적 대상 모듈의 수정 시각. 파일이 없으면 건너뛴다(번들 실행 등)."""
    root = Path(__file__).resolve().parent
    stamps: dict[str, str] = {}
    for name in _TRACKED:
        path = root / f"{name}.py"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        stamps[name] = datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M:%S")
    return stamps


def newest_source_time() -> str:
    stamps = source_fingerprint()
    return max(stamps.values()) if stamps else "(번들)"


def stale_sources() -> list[str]:
    """프로세스가 코드를 읽은 뒤에 수정된 모듈 목록.

    비어 있지 않다면 **지금 도는 코드는 디스크의 코드와 다르다.** 파이썬은 이미
    불러온 모듈을 다시 읽지 않으므로, 앱을 다시 시작해야 반영된다.
    """
    root = Path(__file__).resolve().parent
    stale: list[str] = []
    for name in _TRACKED:
        path = root / f"{name}.py"
        try:
            if path.stat().st_mtime > _LOADED_AT + 1.0:
                stale.append(name)
        except OSError:
            continue
    return stale


def stale_warning() -> str | None:
    """사용자에게 보여줄 안내. 최신 코드로 돌고 있으면 None."""
    stale = stale_sources()
    if not stale:
        return None
    return (
        "앱을 켜 둔 사이에 프로그램 코드가 수정되었습니다.\n"
        f"수정된 부분: {', '.join(stale)}\n\n"
        "파이썬은 이미 불러온 코드를 다시 읽지 않습니다. "
        "**앱을 종료했다가 다시 실행해야** 수정 사항이 적용됩니다."
    )


def log_startup(entrypoint: str) -> None:
    """진입점에서 한 번 호출한다."""
    from . import __version__

    frozen = getattr(sys, "frozen", False)
    stamps = source_fingerprint()
    logger.info(
        "%s 시작 — v%s / pid %d / %s / python %s",
        entrypoint,
        __version__,
        os.getpid(),
        "번들(.app)" if frozen else f"소스 {Path(__file__).resolve().parent}",
        ".".join(str(p) for p in sys.version_info[:3]),
    )
    if stamps:
        logger.info(
            "실행 중인 코드 수정 시각: %s",
            ", ".join(f"{name}={stamp}" for name, stamp in stamps.items()),
        )


__all__ = [
    "log_startup",
    "newest_source_time",
    "source_fingerprint",
    "stale_sources",
    "stale_warning",
]
