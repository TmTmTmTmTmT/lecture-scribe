"""하단 드롭존 / 큐 영역 (§8).

- 유휴: 큰 `+` 와 안내. 클릭하면 파일 선택 대화상자.
- 큐: 파일별 상태·모델·진행률·제거 버튼. 하단에 전체 진행률과 시작/취소.

큐는 **전사 중에도 계속 쌓을 수 있다.** 행은 새로 그리지 않고 덧붙이므로
진행 중인 파일의 진행률이 초기화되지 않는다(이전 버그).
완료된 행은 결과 경로를 보여주고, 클릭하면 Finder에서 열린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PySide6.QtCore import QEvent, QObject, QSize, Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..audio import is_supported
from ..config import MODEL_NAMES
from ..engine import FileResult
from ..notify import reveal_in_finder
from . import strings_ko as S

PAGE_IDLE = 0
PAGE_QUEUE = 1

RowState = Literal["waiting", "running", "done", "failed", "cancelled", "skipped"]

_STATE_LABEL: dict[str, str] = {
    "waiting": S.STATUS_WAITING,
    "running": S.STATUS_RUNNING,
    "done": S.STATUS_DONE,
    "failed": S.STATUS_FAILED,
    "cancelled": S.STATUS_CANCELLED,
    "skipped": S.STATUS_SKIPPED,
}


@dataclass(slots=True)
class RowInfo:
    """큐 1행의 상태."""

    path: Path
    state: RowState = "waiting"
    percent: float = 0.0
    eta_sec: float | None = None
    duration_sec: float = 0.0
    result_path: Path | None = None
    #: FIX_GUIDE_6.md C-01: 산출물을 확인해야 하는 경고(반복 구간·기대 언어 밖 문자).
    quality_warnings: list[str] = field(default_factory=list)
    #: 정보성 경고(백엔드 무시 옵션 등) — 배지 개수에는 안 들어가되 상세에는 보여준다.
    info_warnings: list[str] = field(default_factory=list)


class _IdlePage(QFrame):
    """유휴 상태 페이지. 클릭하면 파일 선택."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plus = QLabel("+")
        font = self.plus.font()
        font.setPointSize(48)
        self.plus.setFont(font)
        self.plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel(S.DROP_IDLE_TITLE)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint = QLabel(S.DROP_IDLE_HINT)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setEnabled(False)
        self.hint.setWordWrap(True)
        layout.addWidget(self.plus)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def set_drag_active(self, active: bool, valid: bool = True) -> None:
        if active:
            color = "#2d7d46" if valid else "#d13438"
            self.setStyleSheet(f"QFrame {{ border: 2px dashed {color}; }}")
            self.title.setText(S.DROP_ACTIVE if valid else S.DROP_INVALID)
        else:
            self.setStyleSheet("")
            self.title.setText(S.DROP_IDLE_TITLE)


class _QueueRow(QWidget):
    """큐 항목 1줄: 파일명 / 모델 / 상태 / 진행률 / 제거."""

    remove_requested = Signal(object)  # Path
    open_requested = Signal(object)  # Path (결과 파일)
    retry_requested = Signal(object)  # Path

    def __init__(
        self, path: Path, default_model: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.info = RowInfo(path=path)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.name_label = QLabel(path.name)
        self.name_label.setToolTip(str(path))
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        # 긴 파일명이 다른 위젯을 밀어내지 않도록 최소 폭을 낮게 잡는다.
        self.name_label.setMinimumWidth(60)
        # 파일별 모델 선택 — 시작 전까지 바꿀 수 있다
        self.model_combo = QComboBox()
        self.model_combo.addItems(list(MODEL_NAMES))
        index = self.model_combo.findText(default_model)
        if index < 0:
            self.model_combo.addItem(default_model)
            index = self.model_combo.count() - 1
        self.model_combo.setCurrentIndex(index)
        self.model_combo.setToolTip(S.ROW_MODEL_TIP)
        self.model_combo.setFixedWidth(126)

        # 남은 시간. 진행 중일 때만 채운다.
        self.eta_label = QLabel("")
        self.eta_label.setEnabled(False)
        self.eta_label.setMinimumWidth(88)
        self.eta_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.status_label = QLabel(S.STATUS_WAITING)
        # 진행 메시지("전사 중 42%")가 들어가도 잘리지 않을 만큼 확보한다.
        self.status_label.setMinimumWidth(112)
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        # 실패한 파일만 다시 돌릴 수 있게. 전체를 다시 넣을 필요가 없다.
        self.retry_button = QPushButton(S.ROW_RETRY)
        self.retry_button.setToolTip(S.ROW_RETRY_TIP)
        self.retry_button.setFixedHeight(20)
        self.retry_button.setVisible(False)
        self.retry_button.clicked.connect(lambda: self.retry_requested.emit(self.path))

        # FIX_GUIDE_6.md C-01: 품질 경고(반복 구간·기대 언어 밖 문자) 배지.
        # 경고 0건이면 숨긴다 — 0을 보여주면 정상 완료가 문제 있어 보인다.
        # 버튼(자식 위젯)이라 여기 클릭은 행 전체의 mouseReleaseEvent(Finder 열기)로
        # 전파되지 않는다.
        self.warning_badge = QPushButton("")
        self.warning_badge.setFlat(True)
        self.warning_badge.setFixedHeight(20)
        self.warning_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.warning_badge.setVisible(False)
        self.warning_badge.clicked.connect(self._show_warnings_dialog)

        self.remove_button = QPushButton("✕")
        self.remove_button.setFixedSize(20, 20)
        self.remove_button.setFlat(True)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self.path))

        top.addWidget(self.name_label, 1)
        top.addWidget(self.model_combo)
        top.addWidget(self.status_label)
        top.addWidget(self.eta_label)
        top.addWidget(self.warning_badge)
        top.addWidget(self.retry_button)
        top.addWidget(self.remove_button)
        layout.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        layout.addWidget(self.progress)

        self.detail = QLabel("")
        self.detail.setEnabled(False)
        self.detail.setVisible(False)
        self.detail.setWordWrap(True)
        self.detail.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.detail)

    # --- 상태 ---

    @property
    def model_name(self) -> str:
        return self.model_combo.currentText()

    def set_state(self, state: RowState, message: str = "") -> None:
        self.info.state = state
        self.status_label.setText(_STATE_LABEL.get(state, state))
        running = state == "running"
        finished = state in {"done", "failed", "cancelled", "skipped"}
        self.model_combo.setEnabled(not running and not finished)
        self.remove_button.setEnabled(not running)
        # 실패·취소는 다시 시도할 수 있다. 모델을 바꿔서 재시도하는 경우가 많으므로
        # 콤보도 다시 열어 준다.
        retryable = state in {"failed", "cancelled"}
        self.retry_button.setVisible(retryable)
        if retryable:
            self.model_combo.setEnabled(True)
        if finished:
            self.progress.setValue(100 if state == "done" else self.progress.value())
            self.eta_label.setText("")
            self.info.eta_sec = None
        if message:
            self.detail.setText(message)
            self.detail.setVisible(True)

    @staticmethod
    def _format_eta(seconds: float) -> str:
        """남은 시간을 사람이 읽는 형태로."""
        if seconds < 60:
            return f"{int(seconds)}초 남음"
        minutes, rest = divmod(int(seconds), 60)
        if minutes < 60:
            return f"{minutes}분 {rest}초 남음"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}시간 {minutes}분 남음"

    def set_progress(self, percent: float, message: str, eta_sec: float | None = None) -> None:
        self.info.percent = percent
        self.info.eta_sec = eta_sec
        self.progress.setValue(int(percent))
        self.eta_label.setText(self._format_eta(eta_sec) if eta_sec else "")
        if message:
            # 잘라내지 않고 라벨 폭에 맞춰 말줄임한다. 전체는 툴팁으로 보여 준다.
            metrics = self.status_label.fontMetrics()
            self.status_label.setText(
                metrics.elidedText(
                    message,
                    Qt.TextElideMode.ElideRight,
                    max(80, self.status_label.width()),
                )
            )
            self.status_label.setToolTip(message)

    def set_result(self, result: FileResult) -> None:
        outputs = [o.path for o in result.outputs if o.path is not None]
        if result.status == "ok" and outputs:
            self.info.result_path = outputs[0]
            self.detail.setText(f"→ {outputs[0].name}  (클릭하면 Finder에서 열기)")
            self.detail.setVisible(True)
        elif result.error_user:
            self.detail.setText(result.error_user)
            self.detail.setVisible(True)

        # FIX_GUIDE_6.md C-01: 품질 경고 배지. 개수는 quality_warnings 기준(정보성 제외).
        self.info.quality_warnings = list(result.quality_warnings)
        self.info.info_warnings = list(result.info_warnings)
        if self.info.quality_warnings:
            count = len(self.info.quality_warnings)
            self.warning_badge.setText(S.ROW_WARNING_BADGE.format(count=count))
            preview = "\n".join(self.info.quality_warnings[:2])
            self.warning_badge.setToolTip(S.ROW_WARNING_BADGE_TIP.format(preview=preview))
            self.warning_badge.setVisible(True)
        else:
            self.warning_badge.setVisible(False)

    def _show_warnings_dialog(self) -> None:
        """FIX_GUIDE_6.md C-01: 품질/정보성 경고를 구분해 그대로 보여준다(가공 없음)."""
        lines: list[str] = []
        if self.info.quality_warnings:
            lines.append(S.ROW_WARNING_QUALITY_HEADER)
            lines.extend(f"• {w}" for w in self.info.quality_warnings)
        if self.info.info_warnings:
            if lines:
                lines.append("")
            lines.append(S.ROW_WARNING_INFO_HEADER)
            lines.extend(f"• {w}" for w in self.info.info_warnings)
        QMessageBox.information(
            self,
            S.ROW_WARNING_DIALOG_TITLE.format(name=self.path.name),
            "\n".join(lines),
        )

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.info.result_path is not None
        ):
            self.open_requested.emit(self.info.result_path)
        super().mouseReleaseEvent(event)


class DropZone(QWidget):
    """드롭존 + 큐 컨테이너."""

    files_added = Signal(list)  # list[Path]
    start_requested = Signal()
    cancel_requested = Signal()
    remove_requested = Signal(object)  # Path
    retry_requested = Signal(object)  # Path
    unsupported_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._rows: dict[Path, _QueueRow] = {}
        self._items: dict[Path, QListWidgetItem] = {}
        self._default_model = "large-v3"
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 12)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.idle_page = _IdlePage()
        self.idle_page.clicked.connect(self._open_dialog)
        self.stack.addWidget(self.idle_page)

        queue_page = QWidget()
        queue_layout = QVBoxLayout(queue_page)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_list = QListWidget()
        self.queue_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        # QListWidget은 뷰포트에서 드래그를 가로챈다. 위젯에만 setAcceptDrops(False)를
        # 걸어도 뷰포트는 그대로라서, 큐에 행이 있으면 드롭이 먹지 않았다.
        self.queue_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.queue_list.setAcceptDrops(False)
        self.queue_list.viewport().setAcceptDrops(False)
        self.queue_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        # 행 폭은 뷰포트 폭을 따라야 한다. 뷰포트 리사이즈는 DropZone의
        # resizeEvent보다 늦게 확정되므로 뷰포트를 직접 감시한다.
        self.queue_list.viewport().installEventFilter(self)
        queue_layout.addWidget(self.queue_list, 1)

        self.overall_label = QLabel("")
        queue_layout.addWidget(self.overall_label)
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 100)
        queue_layout.addWidget(self.overall_progress)

        button_row = QHBoxLayout()
        self.start_button = QPushButton(S.QUEUE_START)
        self.start_button.setDefault(True)
        self.cancel_button = QPushButton(S.QUEUE_CANCEL)
        self.cancel_button.setEnabled(False)
        self.retry_all_button = QPushButton(S.QUEUE_RETRY_ALL)
        self.retry_all_button.setToolTip(S.QUEUE_RETRY_ALL_TIP)
        self.retry_all_button.setEnabled(False)
        self.clear_button = QPushButton(S.QUEUE_CLEAR_DONE)
        self.add_button = QPushButton(S.QUEUE_ADD_FILES)
        self.start_button.clicked.connect(self.start_requested)
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.retry_all_button.clicked.connect(self._on_retry_all)
        self.clear_button.clicked.connect(self.clear_finished)
        self.add_button.clicked.connect(self._open_dialog)
        button_row.addWidget(self.start_button, 1)
        button_row.addWidget(self.add_button)
        button_row.addWidget(self.retry_all_button)
        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.cancel_button)
        queue_layout.addLayout(button_row)
        self.stack.addWidget(queue_page)

    # --- 드래그 앤 드롭 ---

    @staticmethod
    def _paths_from(event: QDropEvent | QDragEnterEvent) -> list[Path]:
        return [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
        ]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        paths = self._paths_from(event)
        valid = any(p.is_dir() or is_supported(p) for p in paths)
        all_valid = all(p.is_dir() or is_supported(p) for p in paths)
        if valid:
            event.acceptProposedAction()
        else:
            event.ignore()
        if self.stack.currentIndex() == PAGE_IDLE:
            self.idle_page.set_drag_active(True, all_valid)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        """드래그가 위젯 위에서 움직이는 동안에도 계속 수락해야 드롭이 성사된다.

        이 핸들러가 없으면 기본 구현이 이벤트를 무시해서, 특히 큐 위로 지나갈 때
        커서가 '금지'로 바뀌고 놓아도 아무 일이 없었다.
        """
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802
        self.idle_page.set_drag_active(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.idle_page.set_drag_active(False)
        paths = self._paths_from(event)
        if paths:
            event.acceptProposedAction()
            self.files_added.emit(paths)

    def _open_dialog(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self, S.FILE_DIALOG_TITLE, str(Path.home()), S.FILE_DIALOG_FILTER
        )
        if names:
            self.files_added.emit([Path(name) for name in names])

    # --- 큐 조작 ---

    def set_default_model(self, model: str) -> None:
        """새로 추가되는 행의 기본 모델."""
        self._default_model = model

    def add_paths(self, paths: list[Path], durations: dict[Path, float]) -> list[Path]:
        """행을 **덧붙인다**(기존 행과 진행률을 건드리지 않는다)."""
        added: list[Path] = []
        for path in paths:
            if path in self._rows:
                continue
            row = _QueueRow(path, self._default_model)
            row.info.duration_sec = durations.get(path, 0.0)
            row.remove_requested.connect(self._on_remove)
            row.retry_requested.connect(self.retry_requested)
            row.open_requested.connect(reveal_in_finder)
            item = QListWidgetItem(self.queue_list)
            self.queue_list.addItem(item)
            self.queue_list.setItemWidget(item, row)
            self._rows[path] = row
            self._items[path] = item
            item.setSizeHint(self._row_size_hint(row))
            added.append(path)
        if self._rows:
            self.stack.setCurrentIndex(PAGE_QUEUE)
        self.refresh_overall()
        return added

    def _on_remove(self, path: Path) -> None:
        self.remove_requested.emit(path)

    def _on_retry_all(self) -> None:
        for path in self.failed_paths():
            self.retry_requested.emit(path)

    def remove_row(self, path: Path) -> None:
        row = self._rows.pop(path, None)
        item = self._items.pop(path, None)
        if row is None or item is None:
            return
        self.queue_list.takeItem(self.queue_list.row(item))
        if not self._rows:
            self.show_idle()
        else:
            self.refresh_overall()

    def clear_finished(self) -> None:
        for path, row in list(self._rows.items()):
            if row.info.state in {"done", "failed", "cancelled", "skipped"}:
                self.remove_row(path)

    def pending_paths(self) -> list[Path]:
        return [p for p, r in self._rows.items() if r.info.state == "waiting"]

    def failed_paths(self) -> list[Path]:
        return [
            p for p, r in self._rows.items() if r.info.state in {"failed", "cancelled"}
        ]

    def reset_row(self, path: Path) -> None:
        """실패한 행을 대기 상태로 되돌린다(진행률·결과 표시도 지운다)."""
        row = self._rows.get(path)
        if row is None:
            return
        row.info.percent = 0.0
        row.info.result_path = None
        row.info.quality_warnings = []
        row.info.info_warnings = []
        row.warning_badge.setVisible(False)
        row.progress.setValue(0)
        row.detail.setVisible(False)
        row.detail.setText("")
        row.status_label.setToolTip("")
        row.set_state("waiting")
        self._sync_row_height(path)
        self.refresh_overall()

    def all_paths(self) -> list[Path]:
        return list(self._rows)

    def model_for(self, path: Path) -> str:
        row = self._rows.get(path)
        return row.model_name if row else self._default_model

    def has_rows(self) -> bool:
        return bool(self._rows)

    # --- 상태 반영 ---

    def _row_size_hint(self, row: _QueueRow) -> QSize:
        """아이템 크기 힌트. 폭은 **리스트 뷰포트 폭**으로 고정한다.

        `row.sizeHint()`를 그대로 쓰면 폭이 내용 기준으로 좁게 잡혀서, 행 내용이
        왼쪽에 몰려 붙고 오른쪽이 비며 상태 텍스트가 잘린다(실사용 보고).
        """
        width = max(120, self.queue_list.viewport().width())
        row.setFixedWidth(width)
        row.adjustSize()
        return QSize(width, max(row.sizeHint().height(), row.minimumSizeHint().height()))

    def _sync_row_height(self, path: Path) -> None:
        """행 안에 결과·오류 줄이 생기면 리스트 아이템 높이도 늘려야 겹치지 않는다."""
        row = self._rows.get(path)
        item = self._items.get(path)
        if row is not None and item is not None:
            item.setSizeHint(self._row_size_hint(row))

    def _sync_all_rows(self) -> None:
        """리스트 폭이 바뀌면 모든 행의 크기 힌트를 다시 잡는다."""
        for path in self._rows:
            self._sync_row_height(path)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        """리스트 뷰포트 폭이 바뀌면 모든 행의 크기 힌트를 다시 잡는다."""
        if (
            event.type() == QEvent.Type.Resize
            and watched is self.queue_list.viewport()
        ):
            self._sync_all_rows()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_all_rows()

    def set_row_state(self, path: Path, state: RowState, message: str = "") -> None:
        row = self._rows.get(path)
        if row is not None:
            row.set_state(state, message)
            self._sync_row_height(path)
            self.refresh_overall()

    def set_row_progress(
        self, path: Path, percent: float, message: str, eta_sec: float | None = None
    ) -> None:
        row = self._rows.get(path)
        if row is not None:
            row.set_progress(percent, message, eta_sec)
            self.refresh_overall()

    def set_row_result(self, path: Path, result: FileResult) -> None:
        row = self._rows.get(path)
        if row is not None:
            row.set_result(result)
            self._sync_row_height(path)

    def set_running(self, running: bool) -> None:
        """취소 버튼만 토글한다. 시작/추가는 전사 중에도 쓸 수 있어야 한다."""
        self.cancel_button.setEnabled(running)

    def refresh_overall(self) -> None:
        """전체 진행률 = 오디오 길이 가중 평균(길이를 모르면 파일 수 기준)."""
        rows = list(self._rows.values())
        if not rows:
            self.overall_progress.setValue(0)
            self.overall_label.setText("")
            return
        weights = [max(r.info.duration_sec, 1.0) for r in rows]
        total = sum(weights) or 1.0
        progressed = 0.0
        for row, weight in zip(rows, weights):
            if row.info.state in {"done", "skipped"}:
                percent = 100.0
            elif row.info.state in {"failed", "cancelled"}:
                percent = 0.0
            else:
                percent = row.info.percent
            progressed += weight * percent / 100.0
        overall = min(100.0, progressed / total * 100.0)
        done = sum(
            1 for r in rows if r.info.state in {"done", "failed", "cancelled", "skipped"}
        )
        self.overall_progress.setValue(int(overall))
        failed = sum(1 for r in rows if r.info.state in {"failed", "cancelled"})
        self.retry_all_button.setEnabled(failed > 0)
        label = S.QUEUE_TOTAL.format(done=done, total=len(rows), percent=overall)
        remaining = self._overall_eta(rows)
        if remaining:
            label = f"{label} · 전체 {remaining}"
        if failed:
            label = f"{label} · 실패 {failed}건"
        self.overall_label.setText(label)

    @staticmethod
    def _overall_eta(rows: list[_QueueRow]) -> str:
        """큐 전체 남은 시간.

        진행 중인 파일의 실측 ETA에, 아직 시작 안 한 파일은 그 파일의 처리 속도를
        같게 보고 길이에 비례해 더한다.
        """
        running = [r for r in rows if r.info.state == "running" and r.info.eta_sec]
        if not running:
            return ""
        total = sum(float(r.info.eta_sec or 0.0) for r in running)
        # 진행 중 파일의 속도(초/오디오초)를 대기 파일에 적용
        reference = running[0]
        done_ratio = max(0.01, reference.info.percent / 100.0)
        if reference.info.duration_sec > 0:
            rate = (float(reference.info.eta_sec or 0.0) / (1.0 - done_ratio + 1e-6)) / (
                reference.info.duration_sec
            )
            total += sum(
                r.info.duration_sec * rate
                for r in rows
                if r.info.state == "waiting"
            )
        return _QueueRow._format_eta(total)

    def show_idle(self) -> None:
        self.queue_list.clear()
        self._rows.clear()
        self._items.clear()
        self.overall_progress.setValue(0)
        self.overall_label.setText("")
        self.stack.setCurrentIndex(PAGE_IDLE)
