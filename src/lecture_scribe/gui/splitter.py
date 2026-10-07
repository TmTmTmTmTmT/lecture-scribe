"""손잡이가 보이는 세로 분할선.

macOS 기본 `QSplitter` 손잡이는 몇 px 두께에 아무것도 그려지지 않아, 여기를
끌 수 있다는 사실 자체를 알 수 없다. 가운데에 점을 찍어 잡는 위치를 표시한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QSplitter, QSplitterHandle, QWidget

#: 그립 점 개수·크기·간격(px)
_DOTS = 7
_DOT = 3
_GAP = 5


class _GripHandle(QSplitterHandle):
    """가운데에 점을 찍어 잡는 위치를 보여 주는 손잡이."""

    def __init__(self, orientation: Qt.Orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self.setCursor(
            Qt.CursorShape.SplitVCursor
            if orientation == Qt.Orientation.Vertical
            else Qt.CursorShape.SplitHCursor
        )
        self._hover = False

    def enterEvent(self, event: object) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event: object) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.window())

        line = QColor(palette.mid().color())
        line.setAlpha(110)
        painter.setPen(line)
        painter.drawLine(0, 0, self.width(), 0)
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

        dot = QColor(
            palette.highlight().color() if self._hover else palette.mid().color()
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        span = _DOTS * _DOT + (_DOTS - 1) * _GAP
        x = (self.width() - span) // 2
        y = (self.height() - _DOT) // 2
        for _ in range(_DOTS):
            painter.drawEllipse(x, y, _DOT, _DOT)
            x += _DOT + _GAP
        painter.end()


class GripSplitter(QSplitter):
    """`_GripHandle`을 쓰는 분할선."""

    def createHandle(self) -> QSplitterHandle:  # noqa: N802
        return _GripHandle(self.orientation(), self)


__all__ = ["GripSplitter"]
