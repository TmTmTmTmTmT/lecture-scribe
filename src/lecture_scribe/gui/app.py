"""GUI 진입점.

실행 경로 3가지:
- `lecture-scribe-gui [FILE ...]`
- `lecture-scribe --open-gui FILE ...` (Quick Action "앱에서 열기")
- `LectureScribe.app` (Finder에서 열기 / Dock에 파일 드롭 -> QFileOpenEvent)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from ..logsetup import get_logger, setup_logging
from ..perf import show_in_dock
from ..provenance import log_startup
from . import strings_ko as S
from .dependency_check import check_dependencies, has_any_problem
from .icons import load_app_icon
from .startup_dialog import DependencyDialog

logger = get_logger(__name__)


class LectureScribeApp(QApplication):
    """Finder가 보내는 파일 열기 이벤트를 창으로 전달하는 QApplication."""

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self._window: QObject | None = None
        self._pending: list[Path] = []

    def set_window(self, window: QObject) -> None:
        self._window = window
        if self._pending:
            self._deliver(self._pending)
            self._pending = []

    def _deliver(self, paths: list[Path]) -> None:
        window = self._window
        if window is None:
            self._pending.extend(paths)
            return
        add_files = getattr(window, "add_files", None)
        if callable(add_files):
            add_files(paths)
            return
        # FIX_GUIDE_4.md A-09: 여기서 조용히 넘어가면 "파일을 열었는데 아무
        # 반응이 없다"로만 보인다 — 창 객체 계약이 깨졌다는 걸 로그로 남긴다
        # (§15-6). 예외는 던지지 않는다 — 파일 전달 실패로 앱을 죽이지 않는다.
        logger.warning(
            "창에 add_files()가 없어 파일을 전달하지 못했습니다: %s",
            [str(p) for p in paths],
        )

    def event(self, event: QEvent) -> bool:
        # Finder에서 "다음으로 열기" 또는 Dock 아이콘에 드롭했을 때
        if event.type() == QEvent.Type.FileOpen:
            file_path = getattr(event, "file", None)
            if callable(file_path):
                name = file_path()
                if name:
                    self._deliver([Path(name)])
                    return True
        return super().event(event)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    setup_logging(verbosity=1)
    log_startup("GUI")
    # 번들은 LSUIElement=1(Dock에 안 뜸)로 두고, 창을 띄우는 이 프로세스만 승격한다.
    # 파이썬이 내부적으로 다시 실행하는 보조 프로세스에 아이콘이 생기지 않게 하려는 것.
    show_in_dock()

    app = LectureScribeApp(sys.argv[:1])
    app.setApplicationName(S.APP_TITLE)
    app.setApplicationDisplayName(S.APP_TITLE)
    # FIX_GUIDE_3.md I-02: Dock·메뉴 막대·창·트레이가 전부 이 아이콘을 따라간다.
    # 여기서 설정 안 하면 개발용 래퍼 실행 시 파이썬 기본 아이콘이 뜬다.
    app.setWindowIcon(load_app_icon())

    # 사용자 요청: 실행할 때 ffmpeg/Ollama/gemma 교정 모델이 준비됐는지 확인하고,
    # 안 됐으면 설치를 유도한다. 전부 로컬 점검(Ollama 데몬만 localhost 호출)이라
    # 빠르다 — 문제가 없으면 대화상자를 아예 안 띄운다(매번 뜨면 성가시다).
    dependency_items = check_dependencies()
    if has_any_problem(dependency_items):
        dialog = DependencyDialog(dependency_items)
        dialog.exec()

    from .window import MainWindow  # QApplication 생성 후 임포트

    window = MainWindow(initial_files=[Path(a) for a in args if not a.startswith("-")])
    app.set_window(window)
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
