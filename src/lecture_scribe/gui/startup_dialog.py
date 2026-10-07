"""시작 시 의존성 점검 대화상자 (ffmpeg / Ollama / gemma 교정 모델).

`dependency_check.check_dependencies()`가 뭐가 없는지 판정하고, 여기서는 그
결과를 보여주고 버튼 몇 개로 유도한다.

버튼 종류(전부 `dependency_check.Action` 기준):
- "설치 명령 보여주기" 항목(ffmpeg/ollama 실행 파일 자체가 없음): 명령어를
  보여주고 클립보드에 복사만 한다 — **이 앱이 사용자 승인 없이 brew/설치
  프로그램을 대신 실행하지 않는다.** 설치는 사용자가 터미널에서 직접 한다.
- "지금 실행"(Ollama 데몬이 꺼져 있음, 실행 파일은 있음): 이미 설치된 걸
  띄우기만 하므로 다운로드가 없다 — 바로 실행한다.
- "지금 받기"(gemma 모델 미설치): `ollama pull <모델>`을 실행한다. 모델
  다운로드(수백MB~수GB)라 **버튼 클릭 자체를 사용자 승인으로 본다** — 시작
  전에 다시 묻지 않는다(클릭이 이미 명시적 동의).

전사 자체는 이 대화상자와 무관하게 항상 동작한다 — "계속"으로 아무것도
안 고치고 넘어갈 수 있다.
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..correction import OllamaClient, find_ollama
from ..logsetup import get_logger
from . import strings_ko as S
from .dependency_check import DependencyItem, check_dependencies

logger = get_logger(__name__)


class _OllamaActionWorker(QThread):
    """"지금 실행"/"지금 받기" 버튼 하나의 백그라운드 작업.

    둘 다 잠깐(실행) ~ 수 분(모델 다운로드) 걸릴 수 있어 UI 스레드를 막지 않는다.
    """

    log_line = Signal(str)
    finished_ok = Signal()
    finished_failed = Signal(str)

    def __init__(
        self, action: str, model: str = "", parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._action = action
        self._model = model

    def run(self) -> None:  # noqa: D102 - QThread 표준 진입점
        try:
            if self._action == "start_ollama":
                self._start_ollama()
            elif self._action == "pull_model":
                self._pull_model(self._model)
            else:  # pragma: no cover - 방어적 분기
                raise ValueError(f"알 수 없는 동작: {self._action}")
        except Exception as exc:  # noqa: BLE001 - 실패 사유를 UI로 올려야 한다
            logger.exception("의존성 준비 동작 실패: %s", self._action)
            self.finished_failed.emit(str(exc))
            return
        self.finished_ok.emit()

    def _start_ollama(self) -> None:
        self.log_line.emit("Ollama 데몬을 실행합니다…")
        OllamaClient().ensure_running()
        self.log_line.emit("실행됨.")

    def _pull_model(self, model: str) -> None:
        binary = find_ollama()
        if binary is None:
            raise RuntimeError("ollama 실행 파일을 찾을 수 없습니다.")
        self.log_line.emit(f"$ ollama pull {model}")
        proc = subprocess.Popen(  # noqa: S603 - find_ollama()로 찾은 실행 파일
            [str(binary), "pull", model],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line:
                self.log_line.emit(line)
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"ollama pull 종료 코드 {code}")


class _DependencyRow(QFrame):
    """항목 1건: 라벨 + 상태 + (있으면) 버튼."""

    def __init__(self, item: DependencyItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        badge = QLabel(
            S.STARTUP_CHECK_OK_BADGE if item.ok else S.STARTUP_CHECK_MISSING_BADGE
        )
        badge.setStyleSheet(
            "color: #2e7d32;" if item.ok else "color: #c62828; font-weight: bold;"
        )
        layout.addWidget(badge)

        text = QLabel(f"{item.label} — {item.detail}")
        text.setWordWrap(True)
        layout.addWidget(text, stretch=1)

        self.button: QPushButton | None = None
        if item.action == "show_command":
            btn = QPushButton(S.STARTUP_CHECK_COPY_COMMAND)

            def _copy(_checked: bool = False, cmd: str = item.command) -> None:
                clipboard = QGuiApplication.clipboard()
                if clipboard is not None:
                    clipboard.setText(cmd)
                btn.setText(S.STARTUP_CHECK_COMMAND_COPIED)

            btn.clicked.connect(_copy)
            layout.addWidget(btn)
            self.button = btn
        elif item.action == "start_ollama":
            self.button = QPushButton(S.STARTUP_CHECK_START_OLLAMA)
            layout.addWidget(self.button)
        elif item.action == "pull_model":
            self.button = QPushButton(S.STARTUP_CHECK_PULL_MODEL)
            layout.addWidget(self.button)

        self.text_label = text
        self.item = item


class DependencyDialog(QDialog):
    """시작 시 뜨는 의존성 점검 창. 항상 "계속"으로 닫고 넘어갈 수 있다."""

    def __init__(
        self, items: list[DependencyItem], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(S.STARTUP_CHECK_TITLE)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        self._layout = layout
        intro = QLabel(S.STARTUP_CHECK_INTRO)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._rows: list[_DependencyRow] = []
        for item in items:
            row = _DependencyRow(item)
            layout.addWidget(row)
            self._rows.append(row)
            if row.button is not None and item.action in ("start_ollama", "pull_model"):
                row.button.clicked.connect(
                    lambda _checked=False, r=row: self._run_action(r)
                )

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFixedHeight(100)
        self.log_view.hide()
        layout.addWidget(self.log_view)

        buttons = QDialogButtonBox()
        self.recheck_button = buttons.addButton(
            S.STARTUP_CHECK_RECHECK, QDialogButtonBox.ButtonRole.ActionRole
        )
        self.continue_button = buttons.addButton(
            S.STARTUP_CHECK_CONTINUE, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.recheck_button.clicked.connect(self._recheck)
        self.continue_button.clicked.connect(self.accept)
        layout.addWidget(buttons)

        self._worker: _OllamaActionWorker | None = None

    def _run_action(self, row: _DependencyRow) -> None:
        item = row.item
        if row.button is None or self._worker is not None:
            return
        row.button.setEnabled(False)
        self.log_view.show()
        self.log_view.clear()
        busy_text = (
            S.STARTUP_CHECK_STARTING
            if item.action == "start_ollama"
            else S.STARTUP_CHECK_PULLING
        )
        row.text_label.setText(f"{item.label} — {busy_text}")

        worker = _OllamaActionWorker(item.action or "", item.model, self)
        worker.log_line.connect(self._append_log)
        worker.finished_ok.connect(lambda: self._on_action_done(row, True, ""))
        worker.finished_failed.connect(lambda msg: self._on_action_done(row, False, msg))
        self._worker = worker
        worker.start()

    def _append_log(self, line: str) -> None:
        self.log_view.append(line)

    def _on_action_done(self, row: _DependencyRow, ok: bool, error: str) -> None:
        self._worker = None
        if ok:
            self._recheck()
            return
        item = row.item
        fail_text = (
            S.STARTUP_CHECK_START_FAILED
            if item.action == "start_ollama"
            else S.STARTUP_CHECK_PULL_FAILED
        )
        row.text_label.setText(f"{item.label} — {fail_text}: {error}")
        if row.button is not None:
            row.button.setEnabled(True)

    def _recheck(self) -> None:
        """점검을 다시 돌려 대화상자를 새로 채운다(가장 단순하고 안전한 갱신 방법)."""
        fresh = check_dependencies()
        layout = self._layout
        for row in self._rows:
            layout.removeWidget(row)
            row.deleteLater()
        self._rows = []
        for item in fresh:
            row = _DependencyRow(item)
            layout.insertWidget(layout.count() - 2, row)  # 로그창·버튼줄 앞에 끼운다
            self._rows.append(row)
            if row.button is not None and item.action in ("start_ollama", "pull_model"):
                row.button.clicked.connect(
                    lambda _checked=False, r=row: self._run_action(r)
                )


__all__ = ["DependencyDialog"]
