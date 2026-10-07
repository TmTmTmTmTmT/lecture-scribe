"""실사용에서 보고된 GUI·메모리 버그의 재현·검증 테스트.

각 테스트는 **고치기 전이라면 실패해야 하는** 조건을 검사한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication, QLabel  # noqa: E402

from lecture_scribe.config import Settings  # noqa: E402
from lecture_scribe.engine import limit_parallel  # noqa: E402
from lecture_scribe.gui.dropzone import PAGE_QUEUE, DropZone  # noqa: E402
from lecture_scribe.gui.settings_panel import SettingsPanel  # noqa: E402
from lecture_scribe.perf import usable_cpu_threads  # noqa: E402


@pytest.fixture(autouse=True)
def _tear_down_qt_widgets() -> object:
    """테스트가 만든 최상위 위젯을 **메인 스레드에서** 명시적으로 소멸시킨다.

    창을 `close()`만 하고 두면 참조가 사라진 뒤 어느 스레드의 `gc.collect()`가 우연히 치우게
    되는데, 그 시점에 Qt 객체가 소멸하면 세그폴트가 난다. 위젯 수가 바뀌어 GC 시점이 달라지면서
    드러난 기존 잠복 문제다. 프로덕션 경로의 `perf.release_memory()`는 이제 워커 스레드에서
    `gc.collect()`를 건너뛰도록 고쳤지만(FIX_GUIDE_14 T-01), 테스트 자체가 만드는 위젯 정리는
    이 픽스처로 여전히 메인 스레드에서 명시적으로 한다.
    """
    yield
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    app = QApplication.instance()
    if app is not None:
        for widget in QApplication.topLevelWidgets():
            widget.close()
            widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    gc.collect()


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


#: 이벤트가 참조하는 QMimeData가 GC되면 Qt가 dangling 포인터를 읽어 세그폴트가 난다.
#: 테스트가 끝날 때까지 살려 둔다.
_MIME_KEEPALIVE: list[QMimeData] = []


def _drop_event(paths: list[Path], kind: type) -> object:
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    _MIME_KEEPALIVE.append(mime)
    return kind(
        QPoint(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


# --- 버그 1: 큐에 행이 있으면 드래그앤드롭이 먹지 않는다 -----------------------


def test_drop_works_when_queue_has_rows(qapp: QApplication, tmp_path: Path) -> None:
    """완료/실패 목록이 남아 있어도 새 파일을 드롭할 수 있어야 한다."""
    first = tmp_path / "a.m4a"
    first.write_bytes(b"0")
    second = tmp_path / "b.m4a"
    second.write_bytes(b"0")

    zone = DropZone()
    zone.resize(600, 300)
    zone.add_paths([first], {first: 60.0})
    zone.set_row_state(first, "failed")
    assert zone.stack.currentIndex() == PAGE_QUEUE  # 큐 화면 상태에서 시작

    # 리스트가 드롭을 가로채면 안 된다
    assert zone.queue_list.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
    assert not zone.queue_list.viewport().acceptDrops()

    received: list[list[Path]] = []
    zone.files_added.connect(received.append)

    enter = _drop_event([second], QDragEnterEvent)
    zone.dragEnterEvent(enter)  # type: ignore[arg-type]
    assert enter.isAccepted()  # type: ignore[attr-defined]

    drop = _drop_event([second], QDropEvent)
    zone.dropEvent(drop)  # type: ignore[arg-type]
    assert received == [[second]]


def test_drag_move_is_accepted(qapp: QApplication, tmp_path: Path) -> None:
    """dragMoveEvent가 없으면 커서가 '금지'로 바뀌고 드롭이 성사되지 않는다."""
    audio = tmp_path / "c.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    assert hasattr(zone, "dragMoveEvent")
    from PySide6.QtGui import QDragMoveEvent

    move = _drop_event([audio], QDragMoveEvent)
    zone.dragMoveEvent(move)  # type: ignore[arg-type]
    assert move.isAccepted()  # type: ignore[attr-defined]


# --- 버그 2: 행 내용이 왼쪽에 몰려 붙고 잘린다 --------------------------------


def test_row_spans_full_list_width(qapp: QApplication, tmp_path: Path) -> None:
    """아이템 폭은 뷰포트 폭이어야 한다(좁으면 내용이 왼쪽에 뭉친다)."""
    audio = tmp_path / "아주아주긴파일이름_전자회로_9주차.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.resize(700, 400)
    zone.show()
    qapp.processEvents()
    zone.add_paths([audio], {audio: 60.0})
    qapp.processEvents()

    item = zone._items[audio]
    viewport_width = zone.queue_list.viewport().width()
    assert item.sizeHint().width() == max(120, viewport_width)
    zone.hide()


def test_row_width_follows_resize(qapp: QApplication, tmp_path: Path) -> None:
    """창 크기가 바뀌면 행 폭도 따라가야 한다."""
    audio = tmp_path / "d.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.resize(500, 300)
    zone.show()
    qapp.processEvents()
    zone.add_paths([audio], {audio: 60.0})
    qapp.processEvents()
    narrow = zone._items[audio].sizeHint().width()

    zone.resize(900, 300)
    qapp.processEvents()
    wide = zone._items[audio].sizeHint().width()
    assert wide > narrow
    zone.hide()


def test_progress_message_is_elided_not_truncated(
    qapp: QApplication, tmp_path: Path
) -> None:
    """긴 진행 메시지를 18자로 잘라 버리지 않고 말줄임하고 툴팁에 전체를 남긴다."""
    audio = tmp_path / "e.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.resize(700, 300)
    zone.add_paths([audio], {audio: 60.0})
    message = "모델 준비 중: large-v3 (int8) — 가중치를 내려받는 중입니다"
    zone.set_row_progress(audio, 12.0, message)
    row = zone._rows[audio]
    assert row.status_label.toolTip() == message
    assert row.status_label.text() != message[:18]


# --- 버그 3: 고급 설정을 펼치면 내용이 잘린다 ---------------------------------


def test_advanced_toggle_emits_signal(qapp: QApplication) -> None:
    """기본이 '펼침'이므로 접었다 펴는 순서로 확인한다."""
    panel = SettingsPanel(Settings())
    assert panel.advanced_toggle.isChecked(), "고급 설정은 기본으로 보여야 한다"
    seen: list[bool] = []
    panel.advanced_toggled.connect(seen.append)
    panel.advanced_toggle.setChecked(False)
    assert seen == [False]
    panel.advanced_toggle.setChecked(True)
    assert seen == [False, True]


def test_advanced_expand_grows_window(qapp: QApplication) -> None:
    """접었다 다시 펼치면 창이 커진다(기본이 '펼침'이라 먼저 접는다).

    FIX_GUIDE_6.md C-04: 정방형 강제를 풀었으므로 **높이만** 늘어난다(폭은 그대로).
    """
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    window.panel.advanced_toggle.setChecked(False)
    window.resize(480, 480)
    qapp.processEvents()
    before_width = window.width()
    before_height = window.height()

    window.panel.advanced_toggle.setChecked(True)
    qapp.processEvents()
    assert window.height() > before_height, "고급 설정을 펼쳤는데 창이 그대로다"
    assert window.width() == before_width, "폭이 바뀌면 안 된다(높이만 늘어나야 한다)"
    window.close()


# --- 버그 4: 실패한 백엔드가 캐시에 남아 메모리가 쌓인다 -----------------------


def test_dispose_backend_evicts_and_unloads(qapp: QApplication) -> None:
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    settings = Settings()
    key = window._backend_key(settings)

    unloaded: list[bool] = []

    class FakeBackend:
        def unload(self) -> None:
            unloaded.append(True)

    window._backend_cache[key] = FakeBackend()  # type: ignore[assignment]
    window._dispose_backend(settings)

    assert key not in window._backend_cache, "실패한 백엔드가 캐시에 남았다"
    assert unloaded == [True], "unload()가 불리지 않아 메모리가 반환되지 않는다"
    window.close()


def test_dispose_survives_unload_exception(qapp: QApplication) -> None:
    """정리 중 예외가 나도 캐시에서는 반드시 빠져야 한다."""
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    settings = Settings()
    key = window._backend_key(settings)

    class BrokenBackend:
        def unload(self) -> None:
            raise RuntimeError("해제 실패")

    window._backend_cache[key] = BrokenBackend()  # type: ignore[assignment]
    window._dispose_backend(settings)
    assert key not in window._backend_cache
    window.close()


def test_worker_disposes_backend_on_failure() -> None:
    """워커가 실패 경로에서 disposer를 호출하는지."""
    from lecture_scribe.errors import ModelLoadError
    from lecture_scribe.gui.worker import TranscribeJob, TranscribeWorker

    disposed: list[Settings] = []

    def provider(settings: Settings) -> object:
        raise ModelLoadError("모델 로드 실패", "테스트")

    worker = TranscribeWorker(
        backend_provider=provider,  # type: ignore[arg-type]
        parallel=1,
        backend_disposer=disposed.append,
    )
    job = TranscribeJob(path=Path("/tmp/x.m4a"), settings=Settings())
    worker._run_job(job)
    assert len(disposed) == 1, "실패했는데 백엔드를 내리지 않았다"


# --- 버그 5: GPU 동시 전사로 모델이 중복 적재된다 -----------------------------


def test_mlx_parallel_is_forced_to_one() -> None:
    """mlx는 전역 모델 하나를 공유한다. 동시 실행하면 중복 로드로 OOM."""
    assert limit_parallel(4, "large-v3", "mlx") == 1
    assert limit_parallel(2, "large-v3-turbo", "mlx") == 1


def test_mlx_transcribe_serialised() -> None:
    """전역 ModelHolder 경쟁을 막는 락이 실제로 쓰이는지."""
    import inspect

    from lecture_scribe.backends import mlx as mlx_backend

    source = inspect.getsource(mlx_backend.MlxWhisperBackend._stream_windows)
    assert "with _MLX_LOCK:" in source


def test_mlx_unload_clears_global_model_holder() -> None:
    """unload가 mlx 전역 캐시까지 비우는지(자기 필드만 지우면 메모리가 안 준다)."""
    import inspect

    from lecture_scribe.backends import mlx as mlx_backend

    source = inspect.getsource(mlx_backend.MlxWhisperBackend.unload)
    assert "mlx_release_model" in source


def test_mlx_release_model_is_safe_without_mlx() -> None:
    """mlx가 없거나 로드된 게 없어도 예외 없이 0을 돌려준다."""
    from lecture_scribe.perf import mlx_release_model

    assert mlx_release_model() >= 0.0


# --- FIX_GUIDE_14 T-01: 워커 스레드에서 release_memory()가 gc.collect()를 건너뛴다 ----


def test_release_memory_skips_gc_collect_on_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이 테스트 파일은 PySide6를 이미 로드해 뒀다 — 실제 GUI 프로세스와 같은 조건이다.

    워커 스레드에서 `release_memory()`를 불러도 `gc.collect()`가 돌면 안 된다(Qt 객체가
    다른 스레드에서 소멸할 위험). `malloc_zone_pressure_relief`는 그대로 호출돼야 한다.
    """
    import threading

    from lecture_scribe import perf

    calls: list[bool] = []
    original_collect = perf.gc.collect

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(True)
        return original_collect(*args, **kwargs)

    monkeypatch.setattr(perf.gc, "collect", spy)

    def worker() -> None:
        perf.release_memory()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert calls == [], "워커 스레드에서 gc.collect()가 호출됐다"


def test_release_memory_runs_gc_collect_on_main_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """메인 스레드에서는(Qt가 로드돼 있어도) 평소대로 gc.collect()가 돈다."""
    from lecture_scribe import perf

    calls: list[bool] = []
    original_collect = perf.gc.collect

    def spy(*args: object, **kwargs: object) -> object:
        calls.append(True)
        return original_collect(*args, **kwargs)

    monkeypatch.setattr(perf.gc, "collect", spy)
    perf.release_memory()
    assert calls == [True]


# --- 버그 6: CPU 전사 중 창이 멈춘다 (스레드 과잉 할당) -----------------------


def test_cpu_threads_leave_headroom_for_ui() -> None:
    """전체 코어를 다 쓰면 UI 스레드가 밀려 창이 '응답 없음'이 된다."""
    cores = os.cpu_count() or 4
    auto = usable_cpu_threads(0, 1)
    assert auto < cores, "코어를 전부 점유하면 UI가 멈춘다"
    assert auto >= 1


def test_cpu_threads_split_across_parallel_jobs() -> None:
    """동시 전사 수만큼 나눠 가져야 총 스레드가 코어 수를 넘지 않는다."""
    cores = os.cpu_count() or 4
    assert usable_cpu_threads(0, 2) * 2 <= cores


def test_cpu_threads_respects_explicit_request() -> None:
    assert usable_cpu_threads(3, 1) == 3
    assert usable_cpu_threads(9999, 1) == (os.cpu_count() or 4)


def test_faster_backend_uses_thread_budget() -> None:
    import inspect

    from lecture_scribe.backends import faster

    source = inspect.getsource(faster.FasterWhisperBackend.ensure_loaded)
    assert "usable_cpu_threads" in source
    assert "cpu_threads=threads" in source


# --- UI 정지 감시 장치 -------------------------------------------------------


def test_watchdog_detects_blocked_main_thread(qapp: QApplication, caplog) -> None:  # type: ignore[no-untyped-def]
    """메인 스레드를 실제로 막고, 감시 장치가 기록하는지 확인한다."""
    import logging
    import time

    from lecture_scribe.gui import watchdog as wd

    original = wd._STALL_SEC
    wd._STALL_SEC = 0.5  # 테스트 시간을 줄인다
    try:
        dog = wd.UiWatchdog()
        dog.start()
        qapp.processEvents()
        with caplog.at_level(logging.ERROR):
            time.sleep(1.6)  # 이벤트 루프를 돌리지 않는다 = 멈춘 상태
            qapp.processEvents()
            time.sleep(0.3)
        dog.stop()
    finally:
        wd._STALL_SEC = original

    assert any("응답하지 않습니다" in r.message for r in caplog.records), (
        "메인 스레드가 막혔는데 감시 장치가 아무것도 남기지 않았다"
    )


def test_watchdog_quiet_when_loop_runs(qapp: QApplication, caplog) -> None:  # type: ignore[no-untyped-def]
    """정상 동작 중에는 아무것도 남기지 않아야 한다(오탐 방지)."""
    import logging
    import time

    from lecture_scribe.gui import watchdog as wd

    original = wd._STALL_SEC
    wd._STALL_SEC = 0.5
    try:
        dog = wd.UiWatchdog()
        dog.start()
        with caplog.at_level(logging.ERROR):
            deadline = time.time() + 1.5
            while time.time() < deadline:
                qapp.processEvents()  # 이벤트 루프를 계속 돌린다
                time.sleep(0.02)
        dog.stop()
    finally:
        wd._STALL_SEC = original

    assert not any("응답하지 않습니다" in r.message for r in caplog.records)


# --- 교정 설정 UI (F-09) -------------------------------------------------------


def test_correction_widgets_round_trip(qapp: QApplication) -> None:
    """패널에서 바꾼 교정 설정이 build_settings()에 반영되는지."""
    from dataclasses import replace as dc_replace

    from lecture_scribe.config import Settings

    base = Settings()
    base = dc_replace(base, correction=dc_replace(base.correction, enabled=True))
    panel = SettingsPanel(base)

    panel.correction_model_combo.setCurrentIndex(
        panel.correction_model_combo.findData("gemma4:e2b")
    )
    panel.correction_confidence_combo.setCurrentIndex(
        panel.correction_confidence_combo.findData("high")
    )
    panel.correction_annotate_check.setChecked(False)

    out = panel.build_settings()
    assert out.correction.model == "gemma4:e2b"
    assert out.correction.min_confidence == "high"
    assert out.correction.annotate_transcript is False


def test_both_models_offered(qapp: QApplication) -> None:
    from lecture_scribe.config import Settings

    panel = SettingsPanel(Settings())
    offered = {
        panel.correction_model_combo.itemData(i)
        for i in range(panel.correction_model_combo.count())
    }
    assert {"gemma4:e4b", "gemma4:e2b"} <= offered


def test_correction_disabled_without_ollama(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ollama가 없으면 체크박스를 끄고 이유를 알려 준다."""
    import lecture_scribe.gui.settings_panel as panel_mod
    from lecture_scribe.config import Settings

    monkeypatch.setattr(panel_mod, "ollama_available", lambda: False)
    panel = SettingsPanel(Settings())
    assert not panel.correction_check.isEnabled()
    assert "ollama" in panel.correction_check.toolTip().lower()


def test_model_dropdown_shows_actually_installed_gemma_versions(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """사용자 요청: 설치된 모든 gemma 버전을 찾아서 목록에 띄운다.

    Ollama가 실제로 갖고 있는 목록(고정된 e4b/e2b 두 개가 아니라)을 그대로
    보여줘야 한다 — 다른 버전(gemma3 등)을 받아 뒀으면 그것도 보인다.
    """
    from dataclasses import replace as dc_replace

    import lecture_scribe.gui.settings_panel as panel_mod
    from lecture_scribe.config import Settings

    monkeypatch.setattr(
        panel_mod,
        "list_installed_gemma_models",
        lambda: ["gemma3:12b", "gemma4:e2b"],
    )
    # 저장된 선택(기본값 e4b)이 목록에 없으면 "저장값 보존" 로직이 따로
    # 끼워 넣는다(그건 그것대로 맞는 동작) — 여기서는 그 경로를 안 타게
    # 저장값을 목록 안에 있는 걸로 맞춰서 순수하게 탐색 결과만 본다.
    settings = Settings()
    settings = dc_replace(
        settings, correction=dc_replace(settings.correction, model="gemma4:e2b")
    )
    panel = SettingsPanel(settings)
    offered = [
        panel.correction_model_combo.itemData(i)
        for i in range(panel.correction_model_combo.count())
    ]
    assert offered == ["gemma3:12b", "gemma4:e2b"]
    assert "gemma4:e4b" not in offered  # 실제로 안 받았으면 목록에도 없어야 한다


def test_model_dropdown_refresh_button_re_scans(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """새로고침 버튼을 누르면 그 시점의 설치 목록으로 다시 채운다."""
    import lecture_scribe.gui.settings_panel as panel_mod
    from lecture_scribe.config import Settings

    current = ["gemma4:e4b"]
    monkeypatch.setattr(
        panel_mod, "list_installed_gemma_models", lambda: list(current)
    )
    panel = SettingsPanel(Settings())
    assert panel.correction_model_combo.count() == 1

    current.append("gemma4:e2b")  # Ollama에서 새로 받았다고 가정
    panel.correction_model_refresh.click()

    offered = {
        panel.correction_model_combo.itemData(i)
        for i in range(panel.correction_model_combo.count())
    }
    assert offered == {"gemma4:e4b", "gemma4:e2b"}


def test_model_dropdown_falls_back_to_fixed_list_when_ollama_unreachable(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ollama가 꺼져 있으면 문서화된 기본 두 모델을 그대로 보여준다(화면이 비면 안 된다)."""
    import lecture_scribe.gui.settings_panel as panel_mod
    from lecture_scribe.config import Settings

    monkeypatch.setattr(panel_mod, "list_installed_gemma_models", lambda: [])
    panel = SettingsPanel(Settings())
    offered = {
        panel.correction_model_combo.itemData(i)
        for i in range(panel.correction_model_combo.count())
    }
    assert offered == {"gemma4:e4b", "gemma4:e2b"}


# --- 영역 직접 조정 (분할선) ---------------------------------------------------


def test_splitter_handle_is_grabbable(qapp: QApplication) -> None:
    """macOS 기본 분할선은 몇 px에 아무것도 안 그려져 잡을 곳을 알 수 없다."""
    from PySide6.QtCore import Qt

    from lecture_scribe.gui.splitter import GripSplitter, _GripHandle
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    assert isinstance(window.splitter, GripSplitter)
    assert window.splitter.handleWidth() >= 8
    assert window.splitter.toolTip()

    handle = window.splitter.handle(1)
    assert isinstance(handle, _GripHandle), "손잡이를 직접 그리지 않는다"
    assert handle.cursor().shape() == Qt.CursorShape.SplitVCursor
    window.close()


def test_grip_handle_paints_without_error(qapp: QApplication) -> None:
    """그립 그리기가 예외 없이 끝나야 한다(페인트 중 예외는 창을 깨뜨린다)."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap

    from lecture_scribe.gui.splitter import GripSplitter

    splitter = GripSplitter(Qt.Orientation.Vertical)
    splitter.addWidget(QLabel("위"))
    splitter.addWidget(QLabel("아래"))
    splitter.resize(300, 200)
    handle = splitter.handle(1)
    handle.resize(300, 12)
    pixmap = QPixmap(handle.size())
    handle.render(pixmap)
    assert not pixmap.isNull()


def test_splitter_can_be_dragged_both_ways(qapp: QApplication) -> None:
    """설정 영역을 키우는 방향·줄이는 방향 모두 실제로 움직여야 한다."""
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    window.resize(640, 640)
    window.show()
    qapp.processEvents()

    window.splitter.setSizes([420, 220])
    qapp.processEvents()
    big = window.split_ratio()

    window.splitter.setSizes([150, 490])
    qapp.processEvents()
    small = window.split_ratio()

    assert big > small, "분할선을 끌어도 비율이 바뀌지 않는다"
    assert 0.15 <= small < big <= 0.85
    window.hide()
    window.close()


def test_split_ratio_persists(qapp: QApplication) -> None:
    """조정한 비율이 저장되고 다음 실행에 복원되어야 한다."""
    from lecture_scribe.config import load_settings
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    window.resize(640, 640)
    window.show()
    qapp.processEvents()
    window.splitter.setSizes([440, 200])
    qapp.processEvents()
    expected = window.split_ratio()
    window.close()  # closeEvent가 저장한다
    qapp.processEvents()

    assert abs(load_settings().window.split_ratio - expected) < 0.02

    restored = MainWindow()
    restored.show()
    qapp.processEvents()
    assert abs(restored.split_ratio() - expected) < 0.05, "복원되지 않았다"
    restored.hide()
    restored.close()


def test_advanced_toggle_respects_wider_manual_split(qapp: QApplication) -> None:
    """사용자가 설정 영역을 넓게 끌어 놨으면 고급 설정을 펴도 줄이지 않는다."""
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    window.resize(760, 760)
    window.show()
    qapp.processEvents()
    window.splitter.setSizes([600, 160])
    qapp.processEvents()
    before = window.splitter.sizes()[0]

    window.panel.advanced_toggle.setChecked(True)
    qapp.processEvents()
    assert window.splitter.sizes()[0] >= before
    window.hide()
    window.close()


def test_split_ratio_is_clamped(qapp: QApplication) -> None:
    """극단값을 저장해도 한쪽이 사라지지 않게 잘라 넣는다."""
    from lecture_scribe.config import WindowState

    assert WindowState.from_dict({"split_ratio": 0.99}).split_ratio <= 0.85
    assert WindowState.from_dict({"split_ratio": 0.0}).split_ratio >= 0.15


# --- 낡은 코드로 실행 중 경고 ---------------------------------------------------


def test_failure_warns_when_code_changed_since_launch(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """켜 둔 사이 코드가 바뀌면, 실패 시 반드시 알려야 한다.

    이 경고가 없어서 이미 고친 GPU 버그가 "여전히 재현된다"고 오진됐다.
    """
    import lecture_scribe.gui.window as window_mod
    from lecture_scribe.gui.window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(
        window_mod, "stale_warning", lambda: "코드가 바뀌었습니다. 다시 실행하세요."
    )
    monkeypatch.setattr(window_mod, "stale_sources", lambda: ["backends/mlx"])
    monkeypatch.setattr(
        window_mod.QMessageBox, "warning", lambda *a, **k: shown.append(a[2])
    )

    window = MainWindow()
    window._on_job_failed(Path("/tmp/a.m4a"), "전사 실패")
    assert shown and "다시 실행" in shown[0]

    # 두 번째 실패에는 다시 띄우지 않는다(성가심 방지)
    window._on_job_failed(Path("/tmp/b.m4a"), "전사 실패")
    assert len(shown) == 1
    window.close()


def test_no_stale_warning_when_code_is_current(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lecture_scribe.gui.window as window_mod
    from lecture_scribe.gui.window import MainWindow

    shown: list[str] = []
    monkeypatch.setattr(window_mod, "stale_warning", lambda: None)
    monkeypatch.setattr(
        window_mod.QMessageBox, "warning", lambda *a, **k: shown.append(a[2])
    )
    window = MainWindow()
    window._on_job_failed(Path("/tmp/a.m4a"), "전사 실패")
    assert shown == []
    window.close()


# --- 실패 시 메모리 해제 (실사용 보고) -------------------------------------------


def test_backend_disposed_when_transcribe_file_returns_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`transcribe_file`은 **예외를 삼키고** status="failed"를 돌려준다.

    그래서 워커의 except 절은 이 경로에서 실행되지 않는다. 그런데도 백엔드를
    내리지 않으면 모델이 메모리를 계속 붙든다(GPU 실패 시 점유가 안 풀리던 원인).
    """
    import lecture_scribe.gui.worker as worker_mod
    from lecture_scribe.config import Settings
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui.worker import TranscribeJob, TranscribeWorker

    audio = tmp_path / "a.m4a"
    disposed: list[Settings] = []

    monkeypatch.setattr(
        worker_mod,
        "transcribe_file",
        lambda *a, **k: FileResult(
            audio_path=audio,
            status="failed",
            error_user="GPU 전사 실패",
            error_log="mlx OOM",
        ),
    )
    monkeypatch.setattr(worker_mod, "build_prompt_plan_for", lambda *a, **k: None)

    worker = TranscribeWorker(
        backend_provider=lambda s: object(),  # type: ignore[arg-type,return-value]
        parallel=1,
        backend_disposer=disposed.append,
    )
    worker._run_job(TranscribeJob(path=audio, settings=Settings()))

    assert len(disposed) == 1, "실패했는데 백엔드를 내리지 않아 메모리가 남는다"


def test_failure_signal_emitted_for_absorbed_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """삼켜진 오류도 사용자에게 알려야 한다(조용히 실패 금지)."""
    import lecture_scribe.gui.worker as worker_mod
    from lecture_scribe.config import Settings
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui.worker import TranscribeJob, TranscribeWorker

    audio = tmp_path / "a.m4a"
    monkeypatch.setattr(
        worker_mod,
        "transcribe_file",
        lambda *a, **k: FileResult(
            audio_path=audio, status="failed", error_user="GPU 전사 실패"
        ),
    )
    monkeypatch.setattr(worker_mod, "build_prompt_plan_for", lambda *a, **k: None)

    seen: list[tuple[Path, str]] = []
    worker = TranscribeWorker(
        backend_provider=lambda s: object(),  # type: ignore[arg-type,return-value]
        parallel=1,
        backend_disposer=lambda s: None,
    )
    worker.failed.connect(lambda p, m: seen.append((p, m)))
    worker._run_job(TranscribeJob(path=audio, settings=Settings()))
    assert seen and seen[0][1] == "GPU 전사 실패"


def test_success_does_not_dispose_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """성공했는데 모델을 내리면 다음 파일에서 다시 로드해 느려진다."""
    import lecture_scribe.gui.worker as worker_mod
    from lecture_scribe.config import Settings
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui.worker import TranscribeJob, TranscribeWorker

    audio = tmp_path / "a.m4a"
    disposed: list[object] = []
    monkeypatch.setattr(
        worker_mod,
        "transcribe_file",
        lambda *a, **k: FileResult(audio_path=audio, status="ok"),
    )
    monkeypatch.setattr(worker_mod, "build_prompt_plan_for", lambda *a, **k: None)
    worker = TranscribeWorker(
        backend_provider=lambda s: object(),  # type: ignore[arg-type,return-value]
        parallel=1,
        backend_disposer=disposed.append,
    )
    worker._run_job(TranscribeJob(path=audio, settings=Settings()))
    assert disposed == []


# --- ⌘Q / ⌘W 종료 --------------------------------------------------------------


def test_quit_shortcuts_registered(qapp: QApplication) -> None:
    """메뉴 막대가 없는 창이라 단축키를 직접 붙여야 한다.

    끄기 어려우면 앱을 켜 둔 채로 두게 되고, 그러면 코드를 고쳐도 옛 코드가
    계속 돈다(실제로 이것 때문에 고친 버그가 재현되는 것처럼 보였다).
    """
    from PySide6.QtGui import QKeySequence, QShortcut

    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    bound = {
        s.key().toString(QKeySequence.SequenceFormat.PortableText)
        for s in window.findChildren(QShortcut)
    }
    # macOS에서 Qt는 Ctrl을 ⌘로 매핑한다. StandardKey는 쓰지 않는다 —
    # 실측하니 Quit은 빈 시퀀스, Close는 ⌘F4로 잡혔다.
    assert "Ctrl+Q" in bound, f"⌘Q가 없다: {bound}"
    assert "Ctrl+W" in bound, f"⌘W가 없다: {bound}"

    # 시그널은 생성 시점의 바인드 메서드에 연결되어 있으므로 close를 덮어써도
    # 바뀌지 않는다. 종료가 실제로 일어났는지는 창이 닫혔는지로 확인한다.
    window.show()
    qapp.processEvents()
    assert window.isVisible()
    next(iter(window.findChildren(QShortcut))).activated.emit()
    qapp.processEvents()
    assert not window.isVisible(), "단축키가 종료로 이어지지 않는다"


def test_close_quits_application(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """창을 닫으면 프로세스도 끝나야 한다. 남으면 낡은 코드가 계속 돈다."""
    import lecture_scribe.gui.window as window_mod
    from lecture_scribe.gui.window import MainWindow

    quit_called: list[bool] = []
    monkeypatch.setattr(
        window_mod.QApplication, "quit", lambda self: quit_called.append(True)
    )
    window = MainWindow()
    window.close()
    assert quit_called == [True]


# --- 실패 재시도 ---------------------------------------------------------------


def test_retry_button_only_on_failed_rows(qapp: QApplication, tmp_path: Path) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.add_paths([audio], {audio: 60.0})
    row = zone._rows[audio]

    assert not row.retry_button.isVisibleTo(row)
    zone.set_row_state(audio, "running")
    assert not row.retry_button.isVisibleTo(row)
    zone.set_row_state(audio, "done")
    assert not row.retry_button.isVisibleTo(row)
    zone.set_row_state(audio, "failed")
    # 부모가 화면에 없으면 isVisible()은 항상 False다. isVisibleTo로 확인한다.
    assert row.retry_button.isVisibleTo(row), "실패했는데 재시도 버튼이 없다"
    assert row.model_combo.isEnabled(), "모델을 바꿔 재시도할 수 있어야 한다"


def test_retry_emits_and_resets_row(qapp: QApplication, tmp_path: Path) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.add_paths([audio], {audio: 60.0})
    zone.set_row_progress(audio, 55.0, "전사 중")
    zone.set_row_state(audio, "failed", "GPU 메모리 부족")

    seen: list[Path] = []
    zone.retry_requested.connect(seen.append)
    zone._rows[audio].retry_button.click()
    assert seen == [audio]

    zone.reset_row(audio)
    row = zone._rows[audio]
    assert row.info.state == "waiting"
    assert row.info.percent == 0.0
    assert row.progress.value() == 0
    assert not row.detail.isVisible()
    assert audio in zone.pending_paths()


def test_retry_all_button_enabled_only_with_failures(
    qapp: QApplication, tmp_path: Path
) -> None:
    first, second = tmp_path / "a.m4a", tmp_path / "b.m4a"
    for f in (first, second):
        f.write_bytes(b"0")
    zone = DropZone()
    zone.add_paths([first, second], {first: 60.0, second: 60.0})
    assert not zone.retry_all_button.isEnabled()

    zone.set_row_state(first, "failed")
    assert zone.retry_all_button.isEnabled()
    assert zone.failed_paths() == [first]
    assert "실패 1건" in zone.overall_label.text()

    seen: list[Path] = []
    zone.retry_requested.connect(seen.append)
    zone.retry_all_button.click()
    assert seen == [first]


def test_window_retry_requeues_the_file(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """재시도가 실제로 큐에 다시 넣는지."""
    from lecture_scribe.gui.window import MainWindow

    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    window = MainWindow()
    window.dropzone.add_paths([audio], {audio: 60.0})
    window.dropzone.set_row_state(audio, "failed")

    started: list[list[Path]] = []
    monkeypatch.setattr(
        window, "_start_transcription", lambda: started.append(window.dropzone.pending_paths())
    )
    window._on_retry_row(audio)
    assert started == [[audio]], "재시도했는데 큐에 들어가지 않았다"
    window.close()


# --- 창 크기·비율 복원 ----------------------------------------------------------


def test_window_size_and_ratio_both_restored(qapp: QApplication) -> None:
    """크기와 내부 비율을 함께 기억해 다음 실행에 그대로 나와야 한다."""
    from lecture_scribe.config import load_settings
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    window.resize(720, 720)
    window.show()
    for _ in range(3):
        qapp.processEvents()
    window.splitter.setSizes([500, 220])
    qapp.processEvents()
    ratio = window.split_ratio()
    window.close()
    qapp.processEvents()

    saved = load_settings().window
    assert saved.width == 720
    assert saved.height == 720
    assert abs(saved.split_ratio - ratio) < 0.02

    restored = MainWindow()
    restored.show()
    for _ in range(3):
        qapp.processEvents()
    assert restored.width() == 720
    assert abs(restored.split_ratio() - ratio) < 0.05
    restored.hide()
    restored.close()


def test_window_width_and_height_resize_independently(qapp: QApplication) -> None:
    """FIX_GUIDE_6.md C-04: 정방형 강제를 풀어 폭·높이를 따로 조절할 수 있어야 한다."""
    from lecture_scribe.gui.window import MainWindow

    window = MainWindow()
    window.show()
    for _ in range(3):
        qapp.processEvents()
    window.resize(700, 900)
    for _ in range(3):
        qapp.processEvents()
    assert window.width() == 700
    assert window.height() == 900, "높이가 폭에 맞춰 강제로 되돌아갔다(정방형 강제가 남아 있다)"
    window.close()


def test_window_state_legacy_size_restores_square() -> None:
    """옛 설정 파일(`size`만 있음)은 폭=높이=size로 복원돼야 한다(마이그레이션 없이)."""
    from lecture_scribe.config import WindowState

    state = WindowState.from_dict({"size": 800})
    assert state.width == 800
    assert state.height == 800


def test_window_state_width_height_take_precedence_over_legacy_size() -> None:
    """새 필드가 있으면 옛 `size`는 무시된다."""
    from lecture_scribe.config import WindowState

    state = WindowState.from_dict({"size": 800, "width": 900, "height": 500})
    assert state.width == 900
    assert state.height == 500


# --- 남은 시간(ETA) 표시 --------------------------------------------------------


def test_row_shows_eta(qapp: QApplication, tmp_path: Path) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.add_paths([audio], {audio: 2700.0})
    zone.set_row_state(audio, "running")
    zone.set_row_progress(audio, 25.0, "전사 중", eta_sec=930.0)

    row = zone._rows[audio]
    assert row.eta_label.text() == "15분 30초 남음"
    assert row.info.eta_sec == 930.0


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(45, "45초 남음"), (90, "1분 30초 남음"), (3720, "1시간 2분 남음")],
)
def test_eta_formatting(seconds: float, expected: str) -> None:
    from lecture_scribe.gui.dropzone import _QueueRow

    assert _QueueRow._format_eta(seconds) == expected


def test_eta_cleared_when_finished(qapp: QApplication, tmp_path: Path) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.add_paths([audio], {audio: 600.0})
    zone.set_row_progress(audio, 50.0, "전사 중", eta_sec=300.0)
    assert zone._rows[audio].eta_label.text()
    zone.set_row_state(audio, "done")
    assert zone._rows[audio].eta_label.text() == "", "끝났는데 남은 시간이 남아 있다"


def test_overall_eta_includes_waiting_files(qapp: QApplication, tmp_path: Path) -> None:
    """대기 중인 파일도 전체 예상에 포함해야 실제로 쓸모가 있다."""
    first, second = tmp_path / "a.m4a", tmp_path / "b.m4a"
    for f in (first, second):
        f.write_bytes(b"0")
    zone = DropZone()
    zone.add_paths([first, second], {first: 600.0, second: 600.0})
    zone.set_row_state(first, "running")
    zone.set_row_progress(first, 50.0, "전사 중", eta_sec=300.0)
    assert "전체" in zone.overall_label.text()


def test_progress_event_carries_eta_to_row(
    qapp: QApplication, tmp_path: Path
) -> None:
    """엔진이 계산한 ETA가 실제로 행까지 도달하는지."""
    from lecture_scribe.engine import ProgressEvent
    from lecture_scribe.gui.window import MainWindow

    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    window = MainWindow()
    window.dropzone.add_paths([audio], {audio: 600.0})
    window.dropzone.set_row_state(audio, "running")
    window._on_progress(
        ProgressEvent(file=audio, stage="transcribe", percent=40.0, eta_sec=120.0)
    )
    assert window.dropzone._rows[audio].eta_label.text() == "2분 0초 남음"
    window.close()


def test_empty_message_during_transcribe_does_not_say_model_preparing(
    qapp: QApplication, tmp_path: Path
) -> None:
    """FIX_GUIDE.md G-05: mlx는 VAD가 없어 빈/공백 세그먼트가 흔하다.

    stage='transcribe'에서 메시지가 비어 있다고 '모델 준비 중…'을 보여주면
    사용자가 (재로드 아닌데) 모델이 다시 로드되는 줄 오해한다 — 실사용 보고.
    """
    from lecture_scribe.engine import ProgressEvent
    from lecture_scribe.gui import strings_ko as S
    from lecture_scribe.gui.window import MainWindow

    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    window = MainWindow()
    window.dropzone.add_paths([audio], {audio: 600.0})
    window.dropzone.set_row_state(audio, "running")

    window._on_progress(
        ProgressEvent(file=audio, stage="transcribe", percent=31.5, message="")
    )
    assert window.dropzone._rows[audio].status_label.text() != S.MODEL_PREPARING
    assert window.dropzone._rows[audio].status_label.text() == S.PROCESSING_GENERIC

    window._on_progress(
        ProgressEvent(file=audio, stage="model", percent=0.0, message="")
    )
    assert window.dropzone._rows[audio].status_label.text() == S.MODEL_PREPARING
    window.close()


# --- 취소 --------------------------------------------------------------------


def test_cancel_button_enabled_while_running(qapp: QApplication, tmp_path: Path) -> None:
    audio = tmp_path / "a.m4a"
    audio.write_bytes(b"0")
    zone = DropZone()
    zone.add_paths([audio], {audio: 60.0})
    assert not zone.cancel_button.isEnabled()
    zone.set_running(True)
    assert zone.cancel_button.isEnabled(), "전사 중인데 취소할 수 없다"
    zone.set_running(False)
    assert not zone.cancel_button.isEnabled()


# --- 앱 소유 알림 ---------------------------------------------------------------


def test_notifier_click_raises_window(qapp: QApplication) -> None:
    """알림을 누르면 창이 올라와야 한다(전에는 스크립트 에디터가 열렸다)."""
    from lecture_scribe.gui.notifier import AppNotifier

    raised: list[bool] = []
    notifier = AppNotifier(lambda: raised.append(True))
    notifier._clicked()
    assert raised == [True]
    notifier.hide()


def test_notifier_click_error_does_not_crash(qapp: QApplication) -> None:
    from lecture_scribe.gui.notifier import AppNotifier

    def boom() -> None:
        raise RuntimeError("창 올리기 실패")

    notifier = AppNotifier(boom)
    notifier._clicked()  # 예외가 밖으로 나오면 안 된다
    notifier.hide()


def test_window_prefers_app_notification_over_osascript(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """osascript 알림은 Script Editor 소유라 눌러도 그게 열린다. 앱 알림이 우선."""
    import lecture_scribe.gui.window as window_mod
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui.window import MainWindow

    osascript_used: list[bool] = []
    monkeypatch.setattr(
        window_mod, "notify_completion", lambda **k: osascript_used.append(True)
    )
    window = MainWindow()
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        window._notifier, "notify", lambda t, m: (sent.append((t, m)), True)[1]
    )
    window._results[Path("/tmp/a.m4a")] = FileResult(
        audio_path=Path("/tmp/a.m4a"), status="ok"
    )
    window._on_idle()
    assert sent, "앱 알림이 안 나갔다"
    assert osascript_used == [], "앱 알림이 됐는데 osascript도 썼다"
    window.close()


def test_window_falls_back_to_osascript(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """트레이를 쓸 수 없으면 예전 경로로 되돌아가야 한다(알림이 사라지면 안 됨)."""
    import lecture_scribe.gui.window as window_mod
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui.window import MainWindow

    used: list[bool] = []
    monkeypatch.setattr(window_mod, "notify_completion", lambda **k: used.append(True))
    window = MainWindow()
    monkeypatch.setattr(window._notifier, "notify", lambda t, m: False)
    window._results[Path("/tmp/a.m4a")] = FileResult(
        audio_path=Path("/tmp/a.m4a"), status="ok"
    )
    window._on_idle()
    assert used == [True]
    window.close()


def test_completion_message_shapes() -> None:
    from lecture_scribe.notify import completion_message

    assert completion_message(3, 0, None) == "3건 전사 완료"
    assert completion_message(2, 1, None) == "2건 완료, 1건 실패"
    assert completion_message(0, 2, None) == "2건 실패"
    assert "a.txt" in completion_message(1, 0, Path("/tmp/a.txt"))


def test_video_settings_roundtrip_through_panel(qapp: QApplication) -> None:
    """영상 입력 설정(V-07): 화면에 채워지고, 바꾼 값이 저장 설정으로 돌아온다."""
    from dataclasses import replace as dc_replace

    base = Settings()
    base = dc_replace(
        base, video=dc_replace(base.video, change_threshold_pct=15.0, min_interval_sec=8.0)
    )
    panel = SettingsPanel(base)
    assert panel.video_threshold_spin.value() == 15.0
    assert panel.video_interval_spin.value() == 8.0

    panel.video_capture_check.setChecked(False)
    panel.video_dedupe_spin.setValue(4.5)
    out = panel.build_settings()
    assert out.video.capture_frames is False
    assert out.video.dedupe_threshold_pct == 4.5
    assert out.video.change_threshold_pct == 15.0


def test_video_sheet_settings_roundtrip_through_panel(qapp: QApplication) -> None:
    """FIX_GUIDE_13 S-03: 시트 격자·낱장 보관 설정도 패널에 채워지고 돌아온다."""
    from dataclasses import replace as dc_replace

    base = Settings()
    base = dc_replace(
        base,
        video=dc_replace(base.video, sheet_cols=3, sheet_rows=1, keep_single_frames=True),
    )
    panel = SettingsPanel(base)
    assert panel.video_sheets_check.isChecked() is True
    assert panel.video_sheet_cols_spin.value() == 3
    assert panel.video_sheet_rows_spin.value() == 1
    assert panel.video_keep_singles_check.isChecked() is True

    panel.video_sheets_check.setChecked(False)
    panel.video_sheet_cols_spin.setValue(1)
    panel.video_keep_singles_check.setChecked(False)
    out = panel.build_settings()
    assert out.video.sheets_enabled is False
    assert out.video.sheet_cols == 1
    assert out.video.sheet_rows == 1
    assert out.video.keep_single_frames is False
