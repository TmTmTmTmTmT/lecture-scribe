"""GUI 위젯 동작 테스트 (오프스크린).

창을 실제로 띄우지 않고 위젯 상태·레이아웃 규칙만 검증한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from lecture_scribe.backends.base import BackendCapabilities  # noqa: E402
from lecture_scribe.config import Preset, Settings  # noqa: E402
from lecture_scribe.gui.dropzone import PAGE_IDLE, PAGE_QUEUE, DropZone  # noqa: E402
from lecture_scribe.gui.settings_panel import SettingsPanel  # noqa: E402
from lecture_scribe.gui.worker import TokenUsage  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    return app


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    """모달 다이얼로그는 테스트를 영구 대기시키므로 전부 스텁으로 바꾼다."""
    from PySide6.QtWidgets import QMessageBox

    from lecture_scribe.gui import settings_panel as panel_mod
    from lecture_scribe.gui import window as window_mod

    monkeypatch.setattr(
        panel_mod.QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        panel_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        panel_mod.QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        window_mod.QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        window_mod.QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok
    )


@pytest.fixture
def settings() -> Settings:
    base = Settings()
    base.presets["전자회로"] = Preset(
        topic="전자회로 강의",
        glossary=["잡음", "AWGN"],
        corrections={"자궁": "잡음"},
    )
    base.active_preset = "전자회로"
    return base


# --- 설정 패널 -----------------------------------------------------------


def test_panel_loads_active_preset(qapp: QApplication, settings: Settings) -> None:
    panel = SettingsPanel(settings)
    assert panel.current_topic() == "전자회로 강의"
    assert panel.current_glossary() == ["잡음", "AWGN"]
    assert panel.preset_combo.currentText() == "전자회로"


def test_panel_advanced_is_visible_by_default(
    qapp: QApplication, settings: Settings
) -> None:
    """고급 설정은 상시 표시한다.

    접어 두면 어떤 설정이 켜져 있는지 알 수 없어 문제 추적이 어렵다(사용자 요청).
    """
    panel = SettingsPanel(settings)
    assert panel.advanced_toggle.isChecked()
    assert panel.advanced_box.isVisible() or not panel.isVisible()


def test_panel_format_checkboxes_have_size(
    qapp: QApplication, settings: Settings
) -> None:
    """폼 레이아웃 안의 체크박스가 높이 0으로 사라지지 않아야 한다(회귀 테스트)."""
    panel = SettingsPanel(settings)
    panel.advanced_toggle.setChecked(True)
    panel.resize(600, 600)
    panel.show()
    qapp.processEvents()
    for fmt, check in panel.format_checks.items():
        assert check.height() > 0, fmt
        assert check.width() > 0, fmt
    panel.hide()


def test_panel_token_usage_normal(qapp: QApplication, settings: Settings) -> None:
    panel = SettingsPanel(settings)
    panel.set_token_usage(TokenUsage(used=51, budget=223, dropped_terms=[]))
    assert panel.token_label.text() == "51 / 223 토큰"
    assert "color" not in panel.token_label.styleSheet()


def test_panel_token_usage_over_budget_is_red_and_lists_terms(
    qapp: QApplication, settings: Settings
) -> None:
    panel = SettingsPanel(settings)
    panel.set_token_usage(
        TokenUsage(used=248, budget=223, dropped_terms=["임펄스 응답", "컨볼루션"])
    )
    text = panel.token_label.text()
    assert "248 / 223" in text
    assert "2개 용어가 잘립니다" in text
    assert "임펄스 응답" in text
    assert "color" in panel.token_label.styleSheet()


def test_panel_capabilities_disable_unsupported_widgets(
    qapp: QApplication, settings: Settings
) -> None:
    panel = SettingsPanel(settings)
    mlx_caps = BackendCapabilities(
        hotwords=False,
        condition_on_previous_text=True,
        prompt_reset_on_temperature=False,
        temperature_fallback=True,
        hallucination_silence_threshold=True,
        vad_filter=False,
        word_timestamps=True,
        batched=False,
        beam_search=False,
    )
    panel.apply_capabilities(mlx_caps)
    assert panel.hotwords_check.isEnabled() is False
    assert panel.hotwords_check.toolTip()
    assert panel.vad_check.isEnabled() is False
    assert panel.beam_spin.isEnabled() is False


def test_panel_build_settings_roundtrip(
    qapp: QApplication, settings: Settings
) -> None:
    panel = SettingsPanel(settings)
    panel.topic_edit.setPlainText("새 주제")
    panel.glossary_edit.setText("가, 나, 가")
    panel.format_checks["md"].setChecked(True)
    panel.timestamps_check.setChecked(True)
    built = panel.build_settings()
    preset = built.current_preset()
    assert preset.topic == "새 주제"
    assert preset.glossary == ["가", "나"]  # 중복 제거
    assert preset.corrections == {"자궁": "잡음"}  # 교정 사전은 보존
    assert "md" in built.output.formats
    assert built.output.timestamps is True


def test_foreign_script_checkbox_loads_and_saves(
    qapp: QApplication, settings: Settings
) -> None:
    """FIX_GUIDE_5.md B-02: 체크박스가 설정을 읽고, 토글하면 저장에 반영된다."""
    from dataclasses import replace

    off_settings = replace(
        settings,
        postprocess=replace(settings.postprocess, foreign_script_detection=False),
    )
    panel = SettingsPanel(off_settings)
    assert panel.foreign_script_check.isChecked() is False

    panel.foreign_script_check.setChecked(True)
    built = panel.build_settings()
    assert built.postprocess.foreign_script_detection is True


def test_condition_checkbox_shows_backend_specific_default(
    qapp: QApplication, settings: Settings
) -> None:
    """FIX_GUIDE_4.md A-02: 체크박스 하나가 백엔드별로 다른 필드/기본값을 보여준다.

    §5-2 게이트 통과로 mlx 기본값은 꺼짐, faster-whisper는 그대로 켬이다.
    """
    from dataclasses import replace

    faster_settings = replace(settings, backend="faster")
    panel = SettingsPanel(faster_settings)
    assert panel.condition_check.isChecked() is True  # faster 기본값

    mlx_settings = replace(settings, backend="mlx")
    mlx_panel = SettingsPanel(mlx_settings)
    assert mlx_panel.condition_check.isChecked() is False  # mlx 게이트 통과 기본값


def test_condition_checkbox_save_does_not_clobber_other_backend(
    qapp: QApplication, settings: Settings
) -> None:
    """mlx에서 토글해 저장해도 faster-whisper 쪽 저장값은 그대로여야 한다."""
    from dataclasses import replace

    mlx_settings = replace(settings, backend="mlx")
    panel = SettingsPanel(mlx_settings)
    assert panel.condition_check.isChecked() is False
    panel.condition_check.setChecked(True)  # mlx에서 명시적으로 켬

    built = panel.build_settings()
    assert built.prompt.condition_on_previous_text_mlx is True
    assert built.prompt.condition_on_previous_text is True  # faster 쪽은 안 건드림(기본값 유지)


def test_panel_preset_delete_guard(qapp: QApplication) -> None:
    single = Settings()
    panel = SettingsPanel(single)
    before = len(single.presets)
    panel._on_preset_delete()  # 마지막 프리셋 삭제 시도 -> 거부
    assert len(single.presets) == before


def test_panel_inputs_lock_during_transcription(
    qapp: QApplication, settings: Settings
) -> None:
    panel = SettingsPanel(settings)
    panel.set_inputs_enabled(False)
    assert panel.topic_edit.isEnabled() is False
    assert panel.preset_combo.isEnabled() is False
    panel.set_inputs_enabled(True)
    assert panel.topic_edit.isEnabled() is True


# --- 드롭존 ---


def test_dropzone_starts_idle(qapp: QApplication) -> None:
    zone = DropZone()
    assert zone.stack.currentIndex() == PAGE_IDLE


def test_dropzone_add_paths_appends(qapp: QApplication, tmp_path: Path) -> None:
    zone = DropZone()
    a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
    assert zone.add_paths([a], {a: 60.0}) == [a]
    assert zone.stack.currentIndex() == PAGE_QUEUE
    assert zone.add_paths([b], {b: 60.0}) == [b]
    assert zone.all_paths() == [a, b]
    # 중복은 추가되지 않는다
    assert zone.add_paths([a], {}) == []


def test_dropzone_add_during_run_keeps_progress(
    qapp: QApplication, tmp_path: Path
) -> None:
    """전사 중 파일을 추가해도 진행 중인 행의 진행률이 초기화되면 안 된다(회귀).

    이전에는 `show_queue()`가 큐를 통째로 다시 그려 진행률이 0으로 돌아갔다.
    """
    zone = DropZone()
    running = tmp_path / "running.m4a"
    zone.add_paths([running], {running: 100.0})
    zone.set_row_state(running, "running")
    zone.set_row_progress(running, 62.0, "전사 중")
    before = zone.overall_progress.value()

    added = tmp_path / "added.m4a"
    zone.add_paths([added], {added: 100.0})

    row = zone._rows[running]
    assert row.info.state == "running"
    assert row.progress.value() == 62
    # 전체 진행률은 분모가 늘어 낮아지지만 0으로 초기화되지는 않는다
    assert 0 < zone.overall_progress.value() <= before
    assert zone._rows[added].info.state == "waiting"


def test_dropzone_per_file_model(qapp: QApplication, tmp_path: Path) -> None:
    zone = DropZone()
    zone.set_default_model("large-v3")
    a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
    zone.add_paths([a], {})
    zone.set_default_model("large-v3-turbo")
    zone.add_paths([b], {})
    assert zone.model_for(a) == "large-v3"
    assert zone.model_for(b) == "large-v3-turbo"
    # 시작 전에는 바꿀 수 있다
    zone._rows[a].model_combo.setCurrentText("large-v3-turbo")
    assert zone.model_for(a) == "large-v3-turbo"


def test_dropzone_model_locked_once_running(qapp: QApplication, tmp_path: Path) -> None:
    zone = DropZone()
    path = tmp_path / "a.m4a"
    zone.add_paths([path], {})
    assert zone._rows[path].model_combo.isEnabled()
    zone.set_row_state(path, "running")
    assert not zone._rows[path].model_combo.isEnabled()


def test_dropzone_pending_paths_excludes_finished(
    qapp: QApplication, tmp_path: Path
) -> None:
    zone = DropZone()
    a, b, c = (tmp_path / f"{n}.m4a" for n in "abc")
    zone.add_paths([a, b, c], {})
    zone.set_row_state(a, "running")
    zone.set_row_state(b, "done")
    assert zone.pending_paths() == [c]


def test_dropzone_remove_and_clear_finished(
    qapp: QApplication, tmp_path: Path
) -> None:
    zone = DropZone()
    a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
    zone.add_paths([a, b], {})
    zone.remove_row(a)
    assert zone.all_paths() == [b]
    zone.set_row_state(b, "done")
    zone.clear_finished()
    assert zone.all_paths() == []
    assert zone.stack.currentIndex() == PAGE_IDLE


def test_dropzone_row_result_and_error(qapp: QApplication, tmp_path: Path) -> None:
    from lecture_scribe.engine import FileResult
    from lecture_scribe.writer import WriteOutcome

    zone = DropZone()
    ok, bad = tmp_path / "ok.m4a", tmp_path / "bad.m4a"
    zone.add_paths([ok, bad], {})
    zone.set_row_result(
        ok,
        FileResult(
            audio_path=ok,
            status="ok",
            outputs=[WriteOutcome(format="txt", path=tmp_path / "ok.txt")],
        ),
    )
    zone.set_row_result(
        bad, FileResult(audio_path=bad, status="failed", error_user="손상된 파일")
    )
    assert zone._rows[ok].info.result_path == tmp_path / "ok.txt"
    assert "ok.txt" in zone._rows[ok].detail.text()
    assert "손상된 파일" in zone._rows[bad].detail.text()


def test_dropzone_warning_badge_shown_for_quality_warnings(
    qapp: QApplication, tmp_path: Path
) -> None:
    """FIX_GUIDE_6.md C-01: 반복 구간·기대 언어 밖 문자가 있으면 배지가 뜬다."""
    from lecture_scribe.engine import FileResult
    from lecture_scribe.postprocess import RepeatRun

    zone = DropZone()
    path = tmp_path / "a.m4a"
    zone.add_paths([path], {})
    zone.set_row_result(
        path,
        FileResult(
            audio_path=path,
            status="ok",
            repeats=[RepeatRun(text="안녕하세요", count=5, start=1.0, end=3.0)],
        ),
    )
    row = zone._rows[path]
    # zone이 show() 안 된 상태라 isVisible()은 조상 표시 여부까지 본다.
    # setVisible() 자체가 건 explicit hidden 플래그만 확인한다.
    assert not row.warning_badge.isHidden()
    assert row.warning_badge.text() == "⚠ 1"


def test_dropzone_warning_badge_hidden_when_no_quality_warnings(
    qapp: QApplication, tmp_path: Path
) -> None:
    """정보성 경고(백엔드 무시 옵션 등)만 있으면 배지를 띄우지 않는다."""
    from lecture_scribe.engine import FileResult

    zone = DropZone()
    path = tmp_path / "a.m4a"
    zone.add_paths([path], {})
    zone.set_row_result(
        path,
        FileResult(
            audio_path=path,
            status="ok",
            warnings=["mlx 백엔드(batched=False)에서 무시되는 옵션: vad_filter"],
        ),
    )
    row = zone._rows[path]
    assert not row.warning_badge.isVisible()


def test_dropzone_warning_badge_click_shows_dialog_not_finder(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """배지 클릭은 상세 대화상자를 열고, 행의 Finder 열기를 발동시키지 않는다."""
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui import dropzone as dropzone_mod
    from lecture_scribe.postprocess import RepeatRun
    from lecture_scribe.writer import WriteOutcome

    zone = DropZone()
    path = tmp_path / "a.m4a"
    zone.add_paths([path], {})
    zone.set_row_result(
        path,
        FileResult(
            audio_path=path,
            status="ok",
            outputs=[WriteOutcome(format="txt", path=tmp_path / "a.txt")],
            repeats=[RepeatRun(text="안녕하세요", count=5, start=1.0, end=3.0)],
        ),
    )
    row = zone._rows[path]

    shown: list[str] = []
    monkeypatch.setattr(
        dropzone_mod.QMessageBox,
        "information",
        lambda *args, **kwargs: shown.append(args[2] if len(args) > 2 else ""),
    )
    opened: list[Path] = []
    row.open_requested.connect(lambda p: opened.append(p))

    row.warning_badge.click()
    assert shown, "배지 클릭이 대화상자를 안 띄웠다"
    assert "안녕하세요" in shown[0]
    assert opened == [], "배지 클릭이 Finder 열기까지 발동시켰다"


def test_dropzone_overall_progress_weighted_by_duration(
    qapp: QApplication, tmp_path: Path
) -> None:
    zone = DropZone()
    short, long = tmp_path / "s.m4a", tmp_path / "l.m4a"
    zone.add_paths([short, long], {short: 60.0, long: 540.0})
    zone.set_row_state(short, "done")
    # 짧은 파일 1개 완료 = 전체의 10%
    assert zone.overall_progress.value() == 10


def test_dropzone_start_button_stays_enabled_while_running(
    qapp: QApplication, tmp_path: Path
) -> None:
    """전사 중에도 파일 추가 후 시작할 수 있어야 한다."""
    zone = DropZone()
    path = tmp_path / "a.m4a"
    zone.add_paths([path], {})
    zone.set_running(True)
    assert zone.start_button.isEnabled()
    assert zone.add_button.isEnabled()
    assert zone.cancel_button.isEnabled()


# --- 메인 창 -------------------------------------------------------------


class _StubBackend:
    """네트워크·모델 로드 없이 즉시 응답하는 백엔드(테스트 전용)."""

    @property
    def name(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return "stub"

    def capabilities(self, request: object) -> BackendCapabilities:
        return BackendCapabilities(
            hotwords=True,
            condition_on_previous_text=True,
            prompt_reset_on_temperature=True,
            temperature_fallback=True,
            hallucination_silence_threshold=True,
            vad_filter=True,
            word_timestamps=True,
            batched=False,
        )

    def ensure_loaded(self, on_status: object = None) -> None:
        return None

    def transcribe(
        self, request: object, *, on_heartbeat: object = None
    ) -> object:  # pragma: no cover
        raise NotImplementedError

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def unload(self) -> None:
        return None


@pytest.fixture
def isolated_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """사용자 설정 파일과 네트워크를 건드리지 않는 창 팩토리."""
    from lecture_scribe.gui import window as window_mod

    monkeypatch.setattr(window_mod, "load_settings", lambda *a, **k: Settings())
    monkeypatch.setattr(window_mod, "save_settings", lambda *a, **k: None)
    monkeypatch.setattr(window_mod, "make_backend", lambda settings: _StubBackend())

    created: list[object] = []

    def factory() -> object:
        win = window_mod.MainWindow()
        win._token_timer.stop()  # 디바운스 타이머가 테스트 종료를 막지 않게
        created.append(win)
        return win

    yield factory
    for win in created:
        win.close()


def test_window_resizes_independently(qapp: QApplication, isolated_window) -> None:
    """FIX_GUIDE_6.md C-04: 정방형 강제를 풀었다 — 폭·높이를 따로 조절할 수 있다.

    최소 크기(480×480)만 유지한다.
    """
    win = isolated_window()
    win.show()
    qapp.processEvents()
    for width, height in [(900, 600), (500, 820), (300, 300)]:
        win.resize(width, height)
        qapp.processEvents()
        assert win.width() == max(width, 480), f"{width}x{height}"
        assert win.height() == max(height, 480), f"{width}x{height}"
    from lecture_scribe.gui.window import MIN_SIDE

    assert win.minimumSize().width() == MIN_SIDE
    assert win.minimumSize().height() == MIN_SIDE


def test_window_layout_ratio(qapp: QApplication, isolated_window) -> None:
    """설정:드롭존 = 40:60. 사용자가 스플리터로 조절할 수 있다."""
    win = isolated_window()
    assert win.splitter.count() == 2
    assert not win.splitter.childrenCollapsible()  # 접혀서 사라지지 않는다
    sizes = win.splitter.sizes()
    assert sizes[1] > sizes[0]  # 드롭존이 더 크다 (약 40:60)


def test_settings_panel_scrolls_instead_of_clipping(
    qapp: QApplication, isolated_window
) -> None:
    """창이 작거나 고급 설정을 펼쳐도 내용이 잘리지 않고 스크롤된다."""
    win = isolated_window()
    win.show()
    win.resize(480, 480)
    win.panel.advanced_toggle.setChecked(True)
    qapp.processEvents()
    scroll = win.panel_scroll
    assert scroll.widgetResizable()
    # 내용이 보이는 영역보다 커지면 세로 스크롤이 가능해야 한다
    assert win.panel.sizeHint().height() > 0
    assert scroll.verticalScrollBarPolicy() != Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    # 사용자가 분할선으로 직접 조정하므로 하한은 낮다. 다만 큐가 한 줄은 보여야 한다.
    assert win.dropzone.minimumHeight() >= 120
    # 두 최소값을 합쳐도 최소 창 크기 안에 조정 여유가 남아야 한다
    assert win.panel_scroll.minimumHeight() + win.dropzone.minimumHeight() < 480
    win.close()


def test_window_resizes_independently_with_advanced_open(
    qapp: QApplication, isolated_window
) -> None:
    """FIX_GUIDE_6.md C-04: 고급 설정을 펼친 상태에서도 정방형 강제가 없어야 한다."""
    win = isolated_window()
    win.show()
    win.panel.advanced_toggle.setChecked(True)
    for width, height in ((900, 600), (480, 480), (520, 900)):
        win.resize(width, height)
        qapp.processEvents()
        assert win.width() == max(width, 480)
        assert win.height() == max(height, 480)
    win.close()


def test_window_token_count_uses_worker(qapp: QApplication, isolated_window) -> None:
    """토큰 계산은 워커 스레드에서 돌고 결과가 라벨에 반영된다."""
    win = isolated_window()
    win._start_token_count()
    worker = win._token_worker
    assert worker is not None
    worker.wait(5000)
    qapp.processEvents()
    assert "토큰" in win.panel.token_label.text()


def test_window_backend_instance_is_cached(qapp: QApplication, isolated_window) -> None:
    """백엔드를 매번 새로 만들면 토크나이저 로드로 UI가 멈춘다(회귀 테스트)."""
    win = isolated_window()
    settings = win.panel.build_settings()
    first = win._backend_for(settings)
    assert win._backend_for(settings) is first


# --- 전사 중 큐 조작 (버그 수정 회귀 테스트) ---------------------------------


class _RecordingWorker:
    """submit된 작업을 기록하는 가짜 워커."""

    def __init__(self) -> None:
        self.jobs: list[object] = []
        self.rearmed = 0
        self.cancelled = 0

    @property
    def busy(self) -> bool:
        """실물 TranscribeWorker와 같은 인터페이스(메모리 확보 판단에 쓰인다)."""
        return False

    def rearm(self) -> None:
        self.rearmed += 1

    def submit(self, job: object) -> None:
        self.jobs.append(job)

    def cancel_all(self) -> None:
        self.cancelled += 1

    def stop(self) -> None:
        return None

    def wait(self, msec: int = 0) -> bool:
        return True

    def isRunning(self) -> bool:  # noqa: N802 - Qt 호환 이름
        return False


@pytest.fixture
def window_with_worker(isolated_window, monkeypatch: pytest.MonkeyPatch):
    win = isolated_window()
    worker = _RecordingWorker()
    monkeypatch.setattr(win, "_ensure_worker", lambda: worker)
    win._worker = worker  # 취소 경로에서도 쓰인다
    return win, worker


def test_start_submits_only_pending(window_with_worker, tmp_path: Path) -> None:
    win, worker = window_with_worker
    a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
    win.dropzone.add_paths([a, b], {a: 60.0, b: 60.0})
    win.dropzone.set_row_state(a, "done")
    win._start_transcription()
    assert [j.path for j in worker.jobs] == [b]


def test_add_and_start_during_run(window_with_worker, tmp_path: Path) -> None:
    """전사 중에 파일을 추가하고 다시 시작할 수 있어야 한다."""
    win, worker = window_with_worker
    first = tmp_path / "first.m4a"
    win.dropzone.add_paths([first], {first: 60.0})
    win._start_transcription()
    win.dropzone.set_row_state(first, "running")
    win.dropzone.set_row_progress(first, 40.0, "전사 중")

    second = tmp_path / "second.m4a"
    win.dropzone.add_paths([second], {second: 60.0})
    win._start_transcription()

    assert [j.path for j in worker.jobs] == [first, second]
    # 진행 중인 파일의 상태·진행률이 유지된다
    row = win.dropzone._rows[first]
    assert row.info.state == "running"
    assert row.progress.value() == 40


def test_job_snapshots_settings_at_submit_time(
    window_with_worker, tmp_path: Path
) -> None:
    """제출 후 프리셋·용어를 바꿔도 이미 큐에 들어간 작업에는 영향이 없다."""
    win, worker = window_with_worker
    first = tmp_path / "first.m4a"
    win.panel.glossary_edit.setText("잡음, AWGN")
    win.dropzone.add_paths([first], {first: 60.0})
    win._start_transcription()

    win.panel.glossary_edit.setText("완전히 다른 용어")
    second = tmp_path / "second.m4a"
    win.dropzone.add_paths([second], {second: 60.0})
    win._start_transcription()

    assert worker.jobs[0].settings.current_preset().glossary == ["잡음", "AWGN"]
    assert worker.jobs[1].settings.current_preset().glossary == ["완전히 다른 용어"]


def test_job_uses_per_file_model(window_with_worker, tmp_path: Path) -> None:
    win, worker = window_with_worker
    a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
    win.dropzone.add_paths([a, b], {})
    win.dropzone._rows[a].model_combo.setCurrentText("large-v3")
    win.dropzone._rows[b].model_combo.setCurrentText("large-v3-turbo")
    win._start_transcription()
    models = {j.path: j.settings.model for j in worker.jobs}
    assert models[a] == "large-v3"
    assert models[b] == "large-v3-turbo"


def test_settings_panel_not_locked_during_run(window_with_worker, tmp_path: Path) -> None:
    """전사 중에도 프리셋·주제·모델을 바꿀 수 있어야 한다."""
    win, _ = window_with_worker
    path = tmp_path / "a.m4a"
    win.dropzone.add_paths([path], {})
    win._start_transcription()
    win.dropzone.set_row_state(path, "running")
    assert win.panel.preset_combo.isEnabled()
    assert win.panel.topic_edit.isEnabled()
    assert win.panel.model_combo.isEnabled()


def test_cancel_marks_pending_rows(window_with_worker, tmp_path: Path) -> None:
    win, worker = window_with_worker
    a, b = tmp_path / "a.m4a", tmp_path / "b.m4a"
    win.dropzone.add_paths([a, b], {})
    win.dropzone.set_row_state(a, "running")
    win._cancel_transcription()
    assert worker.cancelled == 1
    assert win.dropzone._rows[b].info.state == "cancelled"


def test_dropzone_row_height_grows_with_detail(
    qapp: QApplication, tmp_path: Path
) -> None:
    """결과 줄이 생기면 리스트 아이템 높이도 늘어야 다음 행과 겹치지 않는다."""
    from lecture_scribe.engine import FileResult
    from lecture_scribe.writer import WriteOutcome

    zone = DropZone()
    path = tmp_path / "a.m4a"
    zone.add_paths([path], {})
    before = zone._items[path].sizeHint().height()
    zone.set_row_result(
        path,
        FileResult(
            audio_path=path,
            status="ok",
            outputs=[WriteOutcome(format="txt", path=tmp_path / "a.txt")],
        ),
    )
    assert zone._items[path].sizeHint().height() > before


def test_idle_unload_clears_backend_cache(qapp: QApplication, isolated_window) -> None:
    """유휴 상태가 되면 모델을 내려 메모리를 돌려준다(실측 large-v3 1.7GB 반환)."""
    win = isolated_window()
    settings = win.panel.build_settings()
    win._backend_for(settings)  # 캐시에 넣는다(스텁 백엔드)
    assert win._backend_cache
    win._unload_models()
    assert not win._backend_cache


def test_idle_unload_skipped_while_busy(
    qapp: QApplication, isolated_window, monkeypatch: pytest.MonkeyPatch
) -> None:
    """전사 중에는 모델을 내리면 안 된다."""
    win = isolated_window()
    win._backend_for(win.panel.build_settings())

    class _Busy:
        busy = True

        def cancel_all(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def wait(self, msec: int = 0) -> bool:
            return True

    win._worker = _Busy()  # type: ignore[assignment]
    win._unload_models()
    assert win._backend_cache


# --- 고급 설정 설명 / 프리셋 추가 -------------------------------------------


def test_every_advanced_widget_has_explanation(
    qapp: QApplication, settings: Settings
) -> None:
    """고급 설정의 모든 항목에 설명(툴팁)이 있어야 한다."""
    panel = SettingsPanel(settings)
    widgets = {
        "백엔드": panel.backend_combo,
        "배치 모드": panel.batched_check,
        "타임스탬프": panel.timestamps_check,
        "충돌 정책": panel.conflict_combo,
        "initial_prompt": panel.initial_prompt_check,
        "hotwords": panel.hotwords_check,
        "이전 문맥": panel.condition_check,
        "창 경계 문맥": panel.carry_window_check,
        "VAD": panel.vad_check,
        "빔 크기": panel.beam_spin,
        "유사도 교정": panel.fuzzy_check,
        "기대 언어 밖 문자 감지": panel.foreign_script_check,
    }
    missing = [name for name, w in widgets.items() if not w.toolTip().strip()]
    assert not missing, f"설명 없는 항목: {missing}"


def test_basic_inputs_have_explanation(qapp: QApplication, settings: Settings) -> None:
    panel = SettingsPanel(settings)
    for name, widget in (
        ("주제", panel.topic_edit),
        ("용어", panel.glossary_edit),
        ("언어", panel.language_combo),
        ("모델", panel.model_combo),
    ):
        assert widget.toolTip().strip(), name


def test_model_choices_limited_to_two(qapp: QApplication, settings: Settings) -> None:
    """실사용 모델 2종만 노출한다."""
    from lecture_scribe.config import MODEL_NAMES

    assert MODEL_NAMES == ("large-v3", "large-v3-turbo")
    panel = SettingsPanel(settings)
    items = [panel.model_combo.itemText(i) for i in range(panel.model_combo.count())]
    assert items == ["large-v3", "large-v3-turbo"]


def test_preset_new_button_creates_empty_preset(
    qapp: QApplication, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lecture_scribe.gui import settings_panel as panel_mod

    panel = SettingsPanel(settings)
    before = len(settings.presets)
    monkeypatch.setattr(
        panel_mod.QInputDialog, "getText", lambda *a, **k: ("전자기학", True)
    )
    panel._on_preset_new()
    assert len(settings.presets) == before + 1
    assert settings.active_preset == "전자기학"
    assert panel.preset_combo.currentText() == "전자기학"
    assert panel.current_topic() == ""
    assert panel.current_glossary() == []


def test_preset_new_rejects_duplicate(
    qapp: QApplication, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lecture_scribe.gui import settings_panel as panel_mod

    panel = SettingsPanel(settings)
    before = len(settings.presets)
    monkeypatch.setattr(
        panel_mod.QInputDialog, "getText", lambda *a, **k: ("전자회로", True)
    )
    panel._on_preset_new()
    assert len(settings.presets) == before  # 중복이면 만들지 않는다
    assert panel.preset_combo.currentText() == "전자회로"


def test_preset_new_cancelled(
    qapp: QApplication, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lecture_scribe.gui import settings_panel as panel_mod

    panel = SettingsPanel(settings)
    before = len(settings.presets)
    monkeypatch.setattr(panel_mod.QInputDialog, "getText", lambda *a, **k: ("", False))
    panel._on_preset_new()
    assert len(settings.presets) == before


def test_auto_glossary_appends_to_field(qapp: QApplication, isolated_window) -> None:
    """전사가 끝나면 자주 나온 용어가 용어 칸에 자동으로 채워진다."""
    from lecture_scribe.engine import FileResult

    from conftest import make_segment

    win = isolated_window()
    win.panel.glossary_edit.setText("잡음")
    segments = [
        make_segment(i, i * 10, i * 10 + 5, "안테나와 네트워크 데이터 설명", -0.3)
        for i in range(5)
    ]
    result = FileResult(
        audio_path=Path("/tmp/a.m4a"), status="ok", segments=segments
    )
    win._auto_suggest_glossary(result)
    glossary = win.panel.current_glossary()
    assert "잡음" in glossary  # 기존 용어 유지
    assert "안테나" in glossary and "네트워크" in glossary
    assert win.panel.status_label.isVisibleTo(win.panel)
    assert "안테나" in win.panel.status_label.text()


def test_auto_glossary_can_be_disabled(
    qapp: QApplication, isolated_window
) -> None:
    from dataclasses import replace as dc_replace

    from lecture_scribe.engine import FileResult

    from conftest import make_segment

    win = isolated_window()
    win._settings = dc_replace(
        win._settings,
        postprocess=dc_replace(
            win._settings.postprocess, auto_suggest_glossary=False
        ),
    )
    win.panel.glossary_edit.setText("잡음")
    result = FileResult(
        audio_path=Path("/tmp/a.m4a"),
        status="ok",
        segments=[make_segment(i, i, i + 1, "안테나 네트워크", -0.3) for i in range(5)],
    )
    win._auto_suggest_glossary(result)
    assert win.panel.current_glossary() == ["잡음"]


# --- FIX_GUIDE_7.md E-01/E-02: 자동 추가 용어 빈도 관리·토큰 예산 정리 ------------


def test_glossary_auto_terms_ordered_by_score(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """새로 감지된 용어는 등장 구간 수(점수) 내림차순으로 자동 추가분 뒤쪽에 온다."""
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.clear()
    added = panel.record_glossary_detections(
        [("낮은빈도", 1), ("높은빈도", 5), ("중간빈도", 3)]
    )
    assert set(added) == {"낮은빈도", "높은빈도", "중간빈도"}
    assert panel.current_glossary() == ["높은빈도", "중간빈도", "낮은빈도"]


def test_glossary_user_terms_keep_original_order_and_position(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """사용자가 친 용어는 순서가 바뀌지 않고 항상 앞에 온다."""
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.setText("두번째용어, 첫번째용어")  # 사용자가 이 순서로 입력
    panel.record_glossary_detections([("자동용어", 9)])
    assert panel.current_glossary() == ["두번째용어", "첫번째용어", "자동용어"]


def test_glossary_prune_only_removes_auto_terms(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """토큰 예산 초과로 잘린 후보 중 자동 추가분만 실제로 지운다."""
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.setText("사용자용어")
    panel.record_glossary_detections([("자동용어", 2)])
    assert panel.current_glossary() == ["사용자용어", "자동용어"]

    removed = panel.prune_glossary_terms(["사용자용어", "자동용어"])
    assert removed == ["자동용어"]
    assert panel.current_glossary() == ["사용자용어"]


def test_glossary_user_edit_keeps_untouched_auto_terms(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """FIX_GUIDE_14 G-02: 편집해도 **건드리지 않은** 자동 추가분은 계속 자동 추가분이다.

    예전(FIX_GUIDE_7.md E-01 §2-5)에는 용어 칸을 아무 데나 한 글자만 고쳐도 그 순간
    남아 있는 자동 추가분이 전부 사용자 용어로 승격돼, 관련 없는 잡음 용어까지
    영구 고착됐다(실제 설정 파일에서 재현).
    """
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.clear()
    panel.record_glossary_detections([("자동용어", 5)])
    assert panel.current_glossary() == ["자동용어"]

    # 사용자가 새 용어를 덧붙인다 — setText는 프로그램이 아니라 사용자 입력을 흉내낸다.
    # 기존 "자동용어"는 그대로 두고 옆에만 추가했다.
    panel.glossary_edit.setText("자동용어, 사람이덧붙임")

    removed = panel.prune_glossary_terms(["자동용어", "사람이덧붙임"])
    assert removed == ["자동용어"], "건드리지 않은 자동 추가분은 여전히 정리 대상이어야 한다"
    assert panel.current_glossary() == ["사람이덧붙임"]


def test_glossary_user_edit_untracks_only_the_removed_auto_term(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """FIX_GUIDE_14 G-02: 사용자가 자동 추가분 하나를 직접 지우면 그것만 추적에서 빠진다."""
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.clear()
    panel.record_glossary_detections([("자동A", 5), ("자동B", 3)])
    assert set(panel.current_glossary()) == {"자동A", "자동B"}

    panel.glossary_edit.setText("자동A")  # 사용자가 자동B를 직접 지움

    removed = panel.prune_glossary_terms(["자동A", "자동B"])
    assert removed == ["자동A"]  # 자동B는 이미 칸에 없어 정리 대상이 아니다
    assert panel.current_glossary() == []


def test_glossary_expire_removes_long_unseen_auto_terms(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """FIX_GUIDE_14 G-03: 한동안 다시 안 나온 자동 추가분은 칸에서도 빠진다.

    최소 등장 구간 수(3점)짜리는 감쇠 0.8/건으로 5건 연속 미등장하면
    3*0.8**5 ≈ 0.98 < 1.0(만료 기준)로 떨어진다.
    """
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.clear()
    panel.record_glossary_detections([("자동용어", 3)])
    assert panel.current_glossary() == ["자동용어"]

    for _ in range(4):
        # 다시 등장하지 않고 점수만 감쇠(0으로 재감지 — 새로 추가되지 않음).
        assert panel.record_glossary_detections([("자동용어", 0)]) == []
        assert panel.expire_stale_auto_terms() == []  # 아직 만료 기준 미달

    panel.record_glossary_detections([("자동용어", 0)])  # 5번째 감쇠 -> 0.98
    expired = panel.expire_stale_auto_terms()
    assert expired == ["자동용어"]
    assert panel.current_glossary() == []
    assert "자동용어" not in panel._auto_glossary_terms


def test_glossary_expire_never_touches_user_terms(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.setText("사용자용어")
    assert panel.expire_stale_auto_terms() == []
    assert panel.current_glossary() == ["사용자용어"]


def test_glossary_expire_keeps_terms_that_keep_reappearing(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """매번 다시 나오는 자동 추가분은 점수가 계속 보충돼 만료되지 않는다."""
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.clear()
    panel.record_glossary_detections([("자동용어", 3)])
    for _ in range(10):
        panel.record_glossary_detections([("자동용어", 3)])  # 매번 다시 등장
        assert panel.expire_stale_auto_terms() == []
    assert panel.current_glossary() == ["자동용어"]


def test_glossary_stats_persist_across_panel_instances(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """통계가 파일에 남아 새 패널 인스턴스에서도 점수가 이어진다."""
    stats_path = tmp_path / "stats.json"
    panel1 = SettingsPanel(settings, glossary_stats_path=stats_path)
    panel1.glossary_edit.clear()
    panel1.record_glossary_detections([("용어", 3)])
    assert stats_path.exists()

    panel2 = SettingsPanel(settings, glossary_stats_path=stats_path)
    assert panel2._glossary_stats["전자회로"].scores["용어"] == 3.0


def test_glossary_stats_scoped_per_preset(
    qapp: QApplication, settings: Settings, tmp_path: Path
) -> None:
    """다른 프리셋으로 전환하면 그 프리셋 몫만 보인다(통계가 섞이지 않는다)."""
    settings.presets["다른과목"] = Preset(topic="", glossary=[])
    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.clear()
    panel.record_glossary_detections([("통신용어", 4)])
    assert panel.current_glossary() == ["통신용어"]
    panel._on_preset_save()  # 저장해야 프리셋을 오갈 때 남는다(기존 동작)

    panel.preset_combo.setCurrentText("다른과목")
    assert panel.current_glossary() == []
    assert panel._auto_glossary_terms == set()

    panel.preset_combo.setCurrentText("전자회로")
    assert "통신용어" in panel.current_glossary()
    assert "통신용어" in panel._auto_glossary_terms, "재방문 시 자동 추가분으로 다시 인식돼야 한다"


def test_glossary_e2e_add_then_prune_via_token_callback(
    qapp: QApplication, isolated_window, tmp_path: Path
) -> None:
    """자동 추가 직후 토큰 초과가 나면 그 자동 추가분만 실제로 빠진다(E-02 통합)."""
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui.worker import TokenUsage

    from conftest import make_segment

    win = isolated_window()
    win.panel._glossary_stats_path = tmp_path / "stats.json"
    win.panel.glossary_edit.setText("사용자용어")
    result = FileResult(
        audio_path=Path("/tmp/a.m4a"),
        status="ok",
        segments=[
            make_segment(i, i * 10, i * 10 + 5, "안테나와 네트워크 데이터 설명", -0.3)
            for i in range(5)
        ],
    )
    win._auto_suggest_glossary(result)
    assert win._glossary_prune_pending is True
    glossary_after_add = win.panel.current_glossary()
    assert "안테나" in glossary_after_add

    # 토큰 계산 결과가 "안테나"를 예산 초과로 잘랐다고 시뮬레이션한다.
    win._on_token_counted(TokenUsage(used=300, budget=223, dropped_terms=["안테나"]))

    assert "안테나" not in win.panel.current_glossary()
    assert "사용자용어" in win.panel.current_glossary()
    assert win._glossary_prune_pending is False
    assert "안테나" in win.panel.status_label.text()
    assert "한도" in win.panel.status_label.text()


def test_glossary_auto_suggest_expires_stale_terms_across_files(
    qapp: QApplication, isolated_window, tmp_path: Path
) -> None:
    """FIX_GUIDE_14 G-03: 여러 파일을 거치며 다시 안 나온 자동 추가분이 실제로 빠진다."""
    from lecture_scribe.engine import FileResult

    from conftest import make_segment

    win = isolated_window()
    win.panel._glossary_stats_path = tmp_path / "stats.json"

    def result_with(text: str, n: int = 3) -> FileResult:
        return FileResult(
            audio_path=Path("/tmp/a.m4a"),
            status="ok",
            segments=[make_segment(i, i * 10, i * 10 + 5, text, -0.3) for i in range(n)],
        )

    # 최소 등장(3구간)만 채워 초기 점수를 3.0으로 만든다 — 3*0.8**5 ≈ 0.98 < 1.0(만료 기준).
    win._auto_suggest_glossary(result_with("안테나와 네트워크 데이터 설명"))
    assert "안테나" in win.panel.current_glossary()

    # 이후 파일들에서는 "안테나" 없이, 매번 새로운 단어가 하나씩 나온다(다시 감지되지 않아
    # 점수만 감쇠 — 같은 단어를 반복하면 "이미 아는 용어"라 새 감지가 없어 감쇠도 멈춘다).
    filler = ["컨스텔레이션", "임피던스", "반사파", "방정식", "하드웨어"]
    for word in filler:
        win._auto_suggest_glossary(result_with(f"{word}에 대한 새로운 이야기 {word} 설명 {word}"))

    assert "안테나" not in win.panel.current_glossary()
    assert "다시 나오지 않은" in win.panel.status_label.text()


def test_glossary_prune_never_applies_outside_the_add_cycle(
    qapp: QApplication, isolated_window, tmp_path: Path
) -> None:
    """자동 추가와 무관한(사용자가 타이핑해서 도는) 토큰 계산은 절대 정리하지 않는다."""
    from lecture_scribe.gui.worker import TokenUsage

    win = isolated_window()
    win.panel._glossary_stats_path = tmp_path / "stats.json"
    win.panel.glossary_edit.setText("아무거나, 사용자가입력한긴용어")

    assert win._glossary_prune_pending is False
    win._on_token_counted(TokenUsage(used=300, budget=223, dropped_terms=["아무거나"]))
    assert "아무거나" in win.panel.current_glossary(), "사용자 입력 중에 용어가 지워졌다"


def test_glossary_prune_flag_consumed_once(
    qapp: QApplication, isolated_window, tmp_path: Path
) -> None:
    """정리 게이트는 한 번 쓰고 내린다 — 다음 토큰 계산엔 다시 적용되지 않는다."""
    from lecture_scribe.engine import FileResult
    from lecture_scribe.gui.worker import TokenUsage

    from conftest import make_segment

    win = isolated_window()
    win.panel._glossary_stats_path = tmp_path / "stats.json"
    result = FileResult(
        audio_path=Path("/tmp/a.m4a"),
        status="ok",
        segments=[make_segment(i, i, i + 1, "안테나 네트워크", -0.3) for i in range(5)],
    )
    win._auto_suggest_glossary(result)
    win._on_token_counted(TokenUsage(used=100, budget=223, dropped_terms=[]))
    assert win._glossary_prune_pending is False

    # 이후 사용자가 뭘 입력해서 dropped_terms가 생겨도 더는 자동 정리되지 않는다.
    remaining_before = win.panel.current_glossary()
    win._on_token_counted(
        TokenUsage(used=300, budget=223, dropped_terms=remaining_before[:1])
    )
    assert win.panel.current_glossary() == remaining_before


def test_glossary_preset_rename_moves_stats(
    qapp: QApplication, settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """프리셋 이름을 바꾸면 통계도 같이 옮겨간다(안 옮기면 새 이름엔 통계가 없다)."""
    from lecture_scribe.gui import settings_panel as panel_mod

    panel = SettingsPanel(settings, glossary_stats_path=tmp_path / "stats.json")
    panel.glossary_edit.clear()
    panel.record_glossary_detections([("용어", 3)])

    monkeypatch.setattr(
        panel_mod.QInputDialog,
        "getText",
        lambda *a, **k: ("새이름", True),
    )
    panel._on_preset_rename()
    assert "새이름" in panel._glossary_stats
    assert "전자회로" not in panel._glossary_stats
    assert panel._glossary_stats["새이름"].scores.get("용어") == 3.0
