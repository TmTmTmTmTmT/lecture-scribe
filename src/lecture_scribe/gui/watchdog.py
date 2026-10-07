"""UI 이벤트 루프 정지 감시.

"전사 중에 창이 응답하지 않는다"는 보고는 재현이 어렵다. 증상이 났을 때
**무엇 때문에 멈췄는지 로그에 남기려고** 둔다. 고치는 장치가 아니라 잡는 장치다.

원리: 메인 스레드에서 주기적으로 타이머를 돌려 마지막 심박 시각을 기록하고,
별도 스레드가 그 시각이 오래됐는지 본다. 오래됐다면 이벤트 루프가 막힌 것이므로
메인 스레드의 스택과 그 시점의 메모리·스왑 상태를 남긴다.
"""

from __future__ import annotations

import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer

from ..logsetup import get_logger
from ..perf import available_memory_gb, process_rss_mb, swap_used_mb

logger = get_logger(__name__)

#: 심박 주기(ms). 짧을수록 민감하지만 부하도 커진다.
_HEARTBEAT_MS = 250
#: 이 시간 넘게 심박이 없으면 멈춘 것으로 본다. macOS 무지개 커서 기준보다 넉넉히.
_STALL_SEC = 3.0
#: 같은 정지에 대해 반복해서 남기지 않을 간격.
_REPORT_COOLDOWN_SEC = 30.0


class UiWatchdog(QObject):
    """메인 스레드가 멈추면 그 시점의 스택과 자원 상태를 로그에 남긴다."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._last_beat = time.monotonic()
        self._last_report = 0.0
        self._stop = threading.Event()
        self._main_thread_id = threading.get_ident()

        self._timer = QTimer(self)
        self._timer.setInterval(_HEARTBEAT_MS)
        self._timer.timeout.connect(self._beat)

        self._thread = threading.Thread(
            target=self._watch, name="ui-watchdog", daemon=True
        )

    def start(self) -> None:
        self._timer.start()
        self._thread.start()
        logger.info("UI 감시 시작(정지 %.0f초 이상이면 기록)", _STALL_SEC)

    def stop(self) -> None:
        self._stop.set()
        self._timer.stop()

    def _beat(self) -> None:
        self._last_beat = time.monotonic()

    def _watch(self) -> None:
        while not self._stop.wait(0.5):
            stalled = time.monotonic() - self._last_beat
            if stalled < _STALL_SEC:
                continue
            now = time.monotonic()
            if now - self._last_report < _REPORT_COOLDOWN_SEC:
                continue
            self._last_report = now
            self._report(stalled)

    def _report(self, stalled: float) -> None:
        frame = sys._current_frames().get(self._main_thread_id)
        stack = (
            "".join(traceback.format_stack(frame))
            if frame is not None
            else "(메인 스레드 스택을 얻지 못함)"
        )
        logger.error(
            "UI가 %.1f초째 응답하지 않습니다.\n"
            "  RSS %.0fMB / 가용 메모리 %.1fGB / 스왑 %.0fMB / 스레드 %d개\n"
            "  메인 스레드 스택:\n%s",
            stalled,
            process_rss_mb(),
            available_memory_gb(),
            swap_used_mb(),
            threading.active_count(),
            stack,
        )


__all__ = ["UiWatchdog"]
