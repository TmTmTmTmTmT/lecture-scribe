"""FIX_GUIDE_4.md A-04/A-09: `LectureScribeApp`(Finder 파일 열기 경로) 테스트.

`LectureScribeApp`은 `QApplication`을 상속한다. Qt는 프로세스당 QApplication을
하나만 허용하는데, 전체 테스트 스위트를 한 프로세스로 돌리면 다른 GUI 테스트
파일이 먼저 평범한 `QApplication`을 만들어 둔다 — 그 위에는 우리 서브클래스를
새로 못 만든다. 그래서 이 파일은 **각 시나리오를 별도 파이썬 프로세스로
격리**해서 돈다(FIX_GUIDE_4.md §3 A-04의 "직접 호출 수준으로 낮춰서라도
커버" 지시를 실제 클래스로 만족시키는 방법).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

_PRELUDE = """
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
from PySide6.QtGui import QFileOpenEvent
from lecture_scribe.gui.app import LectureScribeApp
"""


def _run(script: str) -> subprocess.CompletedProcess[str]:
    full = _PRELUDE + textwrap.dedent(script)
    return subprocess.run(
        [sys.executable, "-c", full],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_file_open_before_window_is_queued_then_delivered_in_order() -> None:
    """창이 뜨기 전에 온 파일들은 큐에 쌓였다가 `set_window()` 뒤 순서대로 한 번 전달된다."""
    result = _run("""
        app = LectureScribeApp([])
        delivered = []

        class FakeWindow:
            def add_files(self, paths):
                delivered.append(list(paths))

        app.event(QFileOpenEvent(str(Path("/tmp/a.m4a"))))
        app.event(QFileOpenEvent(str(Path("/tmp/b.m4a"))))
        assert delivered == [], "창이 없는데 벌써 전달됐다"

        app.set_window(FakeWindow())
        assert delivered == [[Path("/tmp/a.m4a"), Path("/tmp/b.m4a")]], delivered
        assert app._pending == [], "전달 후 대기 큐가 안 비었다"
        print("OK")
    """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_file_open_after_window_delivers_immediately() -> None:
    """창이 이미 있으면 파일이 바로 전달된다(대기 큐를 안 거친다)."""
    result = _run("""
        app = LectureScribeApp([])
        delivered = []

        class FakeWindow:
            def add_files(self, paths):
                delivered.append(list(paths))

        app.set_window(FakeWindow())
        app.event(QFileOpenEvent(str(Path("/tmp/c.m4a"))))
        assert delivered == [[Path("/tmp/c.m4a")]], delivered
        print("OK")
    """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_missing_add_files_logs_warning_instead_of_silently_dropping() -> None:
    """FIX_GUIDE_4.md A-09: `add_files`가 없는 창이면 예외 없이 WARNING을 남긴다."""
    result = _run("""
        import logging
        logging.basicConfig(level=logging.WARNING)
        app = LectureScribeApp([])

        class BrokenWindow:
            pass

        app.set_window(BrokenWindow())
        app.event(QFileOpenEvent(str(Path("/tmp/d.m4a"))))  # 예외 없이 끝나야 한다
        print("OK")
    """)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
    assert "add_files" in result.stderr, "경고 로그가 안 남았다"
