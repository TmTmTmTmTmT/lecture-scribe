"""앱 소유 알림 (macOS).

`osascript`로 낸 알림은 **Script Editor 소유**라서, 눌러도 스크립트 에디터가
열린다(실사용 보고). Qt의 `QSystemTrayIcon.showMessage()`는 알림을 앱 이름으로
내보내고, 클릭을 `messageClicked`로 받을 수 있다. 그래서 GUI에서는 이쪽을 쓰고,
CLI/Quick Action처럼 Qt가 없는 경로에서만 `notify.notify()`로 되돌아간다.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from ..logsetup import get_logger
from .icons import load_tray_icon
from . import strings_ko as S

logger = get_logger(__name__)


class AppNotifier(QObject):
    """앱 이름으로 알림을 내고, 누르면 창을 띄운다."""

    def __init__(
        self,
        on_clicked: Callable[[], None],
        icon: QIcon | None = None,
        parent: QObject | None = None,
    ) -> None:
        """`icon`은 테스트/호출부가 특정 아이콘을 강제하고 싶을 때만 넘긴다.

        비워 두면 FIX_GUIDE_4.md A-05의 트레이 전용 템플릿 실루엣
        (`icons.load_tray_icon()`)을 쓴다 — 컬러 아이콘을 그대로 넣으면
        다크 메뉴 막대에서 거의 안 보인다(실측).
        """
        super().__init__(parent)
        self._on_clicked = on_clicked
        self._tray: QSystemTrayIcon | None = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("시스템 트레이를 쓸 수 없어 알림은 osascript로 대체합니다")
            return
        # 화면 없는 플랫폼(offscreen/minimal)에서는 트레이가 실제로 동작하지 않는데
        # 객체는 만들어진다. 여러 개가 쌓이면 정리 시점에 프로세스가 죽는다
        # (실측: 전체 테스트 실행 중 세그폴트). 어차피 알림도 뜨지 않으므로 만들지 않는다.
        app = QGuiApplication.instance()
        platform = (
            app.platformName() if isinstance(app, QGuiApplication) else ""
        )
        if platform in {"offscreen", "minimal", ""}:
            logger.info("화면 없는 플랫폼(%s)이라 트레이 알림을 쓰지 않습니다", platform)
            return
        tray = QSystemTrayIcon(icon or load_tray_icon(), self)
        tray.setToolTip(S.APP_TITLE)
        tray.messageClicked.connect(self._clicked)
        tray.activated.connect(lambda _reason: self._clicked())
        tray.show()
        self._tray = tray

    @property
    def available(self) -> bool:
        return self._tray is not None and QSystemTrayIcon.supportsMessages()

    def _clicked(self) -> None:
        try:
            self._on_clicked()
        except Exception:  # noqa: BLE001 - 알림 클릭이 앱을 죽이면 안 된다
            logger.exception("알림 클릭 처리 실패")

    def notify(self, title: str, message: str) -> bool:
        """알림 **표시를 시도**한다. 트레이를 쓸 수 없으면 False(호출자가 대체 경로를 쓴다).

        FIX_GUIDE_3.md I-04: 반환값은 "트레이로 시도했다"는 뜻이지 **배달·표시
        성공을 보장하지 않는다.** `QSystemTrayIcon.showMessage()`는 실패해도
        예외나 신호를 주지 않는다(Qt 자체의 한계 — macOS 알림 센터 권한이
        꺼져 있어도 이 함수는 True를 돌려준다). 배달 성공 여부를 알 방법이
        없으므로 없다고 문서화한다.
        """
        if self._tray is None or not QSystemTrayIcon.supportsMessages():
            return False
        self._tray.showMessage(
            title, message, QSystemTrayIcon.MessageIcon.Information, 8000
        )
        return True

    def hide(self) -> None:
        """트레이를 내리고 객체도 확실히 정리한다."""
        tray, self._tray = self._tray, None
        if tray is not None:
            tray.hide()
            tray.setParent(None)
            tray.deleteLater()


__all__ = ["AppNotifier"]
