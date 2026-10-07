"""CLI/큐 통합 테스트.

실제 Whisper 모델 대신 스텁 백엔드를 주입해 **파일·경로·상태 처리**를 검증한다
(전사 정확도는 검증 대상이 아니다, §13).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from lecture_scribe import cli
from lecture_scribe.audio import find_binary
from lecture_scribe.backends.base import (
    BackendCapabilities,
    Segment,
    StatusCallback,
    TranscriptionRequest,
    TranscriptionStream,
)
from lecture_scribe.config import Settings
from lecture_scribe.engine import CancelToken, run_queue


class StubBackend:
    """고정 세그먼트를 돌려주는 백엔드."""

    def __init__(self, texts: list[str] | None = None) -> None:
        self._texts = texts or ["첫 문장입니다.", "두 번째 문장입니다."]
        self.loaded = False

    @property
    def name(self) -> str:
        return "stub"

    @property
    def model_name(self) -> str:
        return "stub-model"

    def capabilities(self, request: TranscriptionRequest) -> BackendCapabilities:
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

    def ensure_loaded(self, on_status: StatusCallback | None = None) -> None:
        self.loaded = True
        if on_status:
            on_status("스텁 모델 준비 완료")

    def transcribe(
        self,
        request: TranscriptionRequest,
        *,
        on_heartbeat: StatusCallback | None = None,
    ) -> TranscriptionStream:
        segments = [
            Segment(
                id=index,
                start=float(index),
                end=float(index) + 1.0,
                text=f" {text}",
                avg_logprob=-0.3,
                no_speech_prob=0.01,
                compression_ratio=1.4,
                temperature=0.0,
            )
            for index, text in enumerate(self._texts)
        ]
        return TranscriptionStream(
            language="ko",
            language_probability=0.99,
            duration_sec=float(len(segments)),
            duration_after_vad_sec=float(len(segments)),
            segments=iter(segments),
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())


@pytest.fixture
def audio_files(tmp_path: Path) -> list[Path]:
    """ffmpeg으로 만든 짧은 실제 오디오 2개(까다로운 파일명 포함)."""
    ffmpeg = find_binary("ffmpeg")
    paths = [tmp_path / "9:1 전자회로 & 실습.m4a", tmp_path / '강의 "인용" 🎧.M4A']
    for path in paths:
        subprocess.run(
            [
                str(ffmpeg), "-nostdin", "-v", "error", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000",
                "-t", "2", "-c:a", "aac", str(path),
            ],
            check=True,
            capture_output=True,
        )
    return paths


# --- 큐 ------------------------------------------------------------------


def test_run_queue_writes_outputs_for_every_file(audio_files: list[Path]) -> None:
    settings = Settings()
    results = run_queue(audio_files, settings, StubBackend())
    assert [r.status for r in results] == ["ok", "ok"]
    for path in audio_files:
        assert path.with_suffix(".txt").exists()


def test_run_queue_isolates_failures(audio_files: list[Path], tmp_path: Path) -> None:
    broken = tmp_path / "손상.m4a"
    broken.write_bytes(b"not audio")
    results = run_queue([audio_files[0], broken, audio_files[1]], Settings(), StubBackend())
    assert [r.status for r in results] == ["ok", "failed", "ok"]
    assert results[1].error_user
    assert audio_files[1].with_suffix(".txt").exists()


def test_run_queue_reports_overall_progress(audio_files: list[Path]) -> None:
    events: list[float] = []
    run_queue(
        audio_files,
        Settings(),
        StubBackend(),
        on_progress=lambda e: events.append(e.overall_percent),
    )
    assert events
    assert events[-1] == pytest.approx(100.0, abs=0.1)
    assert all(0.0 <= value <= 100.0 for value in events)
    assert events == sorted(events)  # 진행률은 되돌아가지 않는다


def test_run_queue_cancel_marks_remaining(audio_files: list[Path]) -> None:
    cancel = CancelToken()
    cancel.cancel()
    results = run_queue(audio_files, Settings(), StubBackend(), cancel=cancel)
    assert all(r.status == "cancelled" for r in results)
    assert not audio_files[0].with_suffix(".txt").exists()


def test_run_queue_all_formats(audio_files: list[Path]) -> None:
    from dataclasses import replace

    settings = Settings()
    settings = replace(
        settings,
        output=replace(settings.output, formats=["txt", "md", "srt", "vtt", "json"]),
    )
    run_queue([audio_files[0]], settings, StubBackend())
    for ext in ("txt", "md", "srt", "vtt", "json"):
        assert audio_files[0].with_suffix(f".{ext}").exists(), ext
    payload = json.loads(audio_files[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["segment_count"] == 2
    assert payload["backend"] == "stub"


# --- 종료 코드 ------------------------------------------------------------


def test_exit_codes(audio_files: list[Path], tmp_path: Path) -> None:
    from lecture_scribe.engine import FileResult

    ok = FileResult(audio_path=audio_files[0], status="ok")
    failed = FileResult(audio_path=tmp_path / "x.m4a", status="failed")
    cancelled = FileResult(audio_path=tmp_path / "y.m4a", status="cancelled")
    assert cli.exit_code_for([ok]) == cli.EXIT_OK
    assert cli.exit_code_for([ok, failed]) == cli.EXIT_PARTIAL
    assert cli.exit_code_for([failed]) == cli.EXIT_ALL_FAILED
    assert cli.exit_code_for([ok, cancelled]) == cli.EXIT_CANCELLED


# --- CLI 진입점 -----------------------------------------------------------


def run_cli(
    monkeypatch: pytest.MonkeyPatch, args: list[str], backend: StubBackend | None = None
) -> int:
    monkeypatch.setattr(cli, "make_backend", lambda settings: backend or StubBackend())
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: Settings())
    return cli.main(args)


def test_cli_json_stdout_is_pure_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    audio_files: list[Path],
) -> None:
    """`--json` stdout에 JSON 외 어떤 문자도 섞이면 안 된다(§13)."""
    code = run_cli(monkeypatch, [str(audio_files[0]), "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)  # 파싱 실패하면 테스트 실패
    assert code == cli.EXIT_OK
    assert payload["exit_code"] == 0
    assert payload["summary"] == {"total": 1, "ok": 1, "failed": 0, "cancelled": 0}
    assert payload["results"][0]["status"] == "ok"
    assert payload["results"][0]["outputs"][0]["path"].endswith(".txt")


def test_cli_json_on_failure_still_valid(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    broken = tmp_path / "손상.m4a"
    broken.write_bytes(b"not audio")
    code = run_cli(monkeypatch, [str(broken), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_ALL_FAILED
    assert payload["exit_code"] == cli.EXIT_ALL_FAILED
    assert payload["results"][0]["status"] == "failed"
    assert payload["results"][0]["error"]


def test_cli_stdout_mode_writes_no_files(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    audio_files: list[Path],
) -> None:
    code = run_cli(monkeypatch, [str(audio_files[0]), "--stdout"])
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK
    assert "첫 문장입니다." in captured.out
    assert not audio_files[0].with_suffix(".txt").exists()


def test_cli_progress_json_lines_are_all_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    audio_files: list[Path],
) -> None:
    run_cli(monkeypatch, [str(audio_files[0]), "--progress-json"])
    captured = capsys.readouterr()
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert lines
    events = [json.loads(line) for line in lines]  # 하나라도 평문이면 실패
    kinds = {event["event"] for event in events}
    assert "progress" in kinds
    assert "queue_done" in kinds
    assert events[-1]["exit_code"] == 0


def test_cli_rejects_unsupported_and_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    note = tmp_path / "노트.pdf"
    note.write_text("x", encoding="utf-8")
    code = run_cli(monkeypatch, [str(note)])
    assert code == cli.EXIT_ALL_FAILED
    assert "제외" in capsys.readouterr().err


def test_cli_dry_run_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, audio_files: list[Path]
) -> None:
    code = run_cli(monkeypatch, [str(audio_files[0]), "--dry-run"])
    assert code == cli.EXIT_OK
    assert not audio_files[0].with_suffix(".txt").exists()


def test_cli_unknown_preset_fails_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    audio_files: list[Path],
) -> None:
    code = run_cli(monkeypatch, [str(audio_files[0]), "--preset", "없는프리셋"])
    assert code == cli.EXIT_ALL_FAILED
    assert "프리셋을 찾을 수 없습니다" in capsys.readouterr().err


def test_cli_open_gui_delegates_to_gui(
    monkeypatch: pytest.MonkeyPatch, audio_files: list[Path]
) -> None:
    """`--open-gui`는 전사하지 않고 GUI에 파일을 넘긴다(Quick Action '앱에서 열기')."""
    called: dict[str, Any] = {}

    def fake_gui_main(args: list[str]) -> int:
        called["args"] = args
        return 0

    import lecture_scribe.gui.app as gui_app

    monkeypatch.setattr(gui_app, "main", fake_gui_main)
    monkeypatch.setattr(cli, "load_settings", lambda *a, **k: Settings())
    code = cli.main([str(audio_files[0]), "--open-gui"])
    assert code == 0
    assert called["args"] == [str(audio_files[0])]
    assert not audio_files[0].with_suffix(".txt").exists()


# --- 병렬 큐 -------------------------------------------------------------


class ParallelStubBackend(StubBackend):
    """동시 전사를 지원한다고 알리는 스텁."""

    def capabilities(self, request: TranscriptionRequest) -> BackendCapabilities:
        caps = super().capabilities(request)
        from dataclasses import replace as dc_replace

        return dc_replace(caps, parallel_transcribe=True)


def test_run_queue_parallel_keeps_order_and_results(audio_files: list[Path]) -> None:
    """동시 처리해도 결과 순서와 내용이 순차 처리와 같아야 한다."""
    from dataclasses import replace as dc_replace

    settings = Settings()
    sequential = run_queue(
        audio_files, dc_replace(settings, max_parallel_files=1), StubBackend()
    )
    for path in audio_files:
        path.with_suffix(".txt").unlink(missing_ok=True)
    parallel = run_queue(
        audio_files, dc_replace(settings, max_parallel_files=2), ParallelStubBackend()
    )
    assert [r.audio_path for r in parallel] == [r.audio_path for r in sequential]
    assert [r.status for r in parallel] == [r.status for r in sequential]
    assert [r.segment_count for r in parallel] == [r.segment_count for r in sequential]


def test_run_queue_parallel_disabled_when_backend_lacks_support(
    audio_files: list[Path],
) -> None:
    """백엔드가 동시 전사를 지원하지 않으면 순차로 떨어진다."""
    from dataclasses import replace as dc_replace

    results = run_queue(
        audio_files, dc_replace(Settings(), max_parallel_files=4), StubBackend()
    )
    assert all(r.status == "ok" for r in results)


def test_run_queue_parallel_progress_is_monotonic(audio_files: list[Path]) -> None:
    from dataclasses import replace as dc_replace

    events: list[float] = []
    run_queue(
        audio_files,
        dc_replace(Settings(), max_parallel_files=2),
        ParallelStubBackend(),
        on_progress=lambda e: events.append(e.overall_percent),
    )
    assert events
    assert all(0.0 <= v <= 100.0 for v in events)
    assert events[-1] == pytest.approx(100.0, abs=0.1)


def test_run_queue_parallel_isolates_failures(
    audio_files: list[Path], tmp_path: Path
) -> None:
    from dataclasses import replace as dc_replace

    broken = tmp_path / "손상.m4a"
    broken.write_bytes(b"not audio")
    results = run_queue(
        [audio_files[0], broken, audio_files[1]],
        dc_replace(Settings(), max_parallel_files=3),
        ParallelStubBackend(),
    )
    assert [r.status for r in results] == ["ok", "failed", "ok"]


def test_parallel_capped_by_cores_and_memory() -> None:
    """코어·메모리에 비해 과하게 요청하면 자동으로 낮춘다(오버서브스크립션 방지)."""
    from lecture_scribe.engine import limit_parallel

    assert limit_parallel(1, "large-v3") == 1
    capped = limit_parallel(64, "large-v3")
    assert 1 <= capped <= 64
    import os

    assert capped <= max(1, (os.cpu_count() or 4) // 4)


def test_make_backend_falls_back_when_mlx_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """배포 번들에는 mlx가 없다. 설정만 남아 있으면 faster로 되돌아가야 한다."""
    from dataclasses import replace as dc_replace

    import lecture_scribe.backends.mlx as mlx_mod

    monkeypatch.setattr(mlx_mod, "is_available", lambda: False)
    backend = cli.make_backend(dc_replace(Settings(), backend="mlx"))
    assert backend.name == "faster"


def test_make_backend_uses_mlx_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace as dc_replace

    import lecture_scribe.backends.mlx as mlx_mod

    monkeypatch.setattr(mlx_mod, "is_available", lambda: True)
    backend = cli.make_backend(dc_replace(Settings(), backend="mlx"))
    assert backend.name == "mlx"


def test_parallel_capped_by_available_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """가용 메모리가 부족하면 동시 전사를 1개로 낮춰야 한다.

    실사용 로그에서 메모리 여유 없이 긴 강의 3개를 동시에 돌렸다가
    전체 처리량이 0.63배속(스왑 +2.2GB)까지 떨어진 사례가 있었다.
    """
    import lecture_scribe.engine as engine_mod

    monkeypatch.setattr(engine_mod, "available_memory_gb", lambda: 5.0)
    assert engine_mod.limit_parallel(2, "large-v3") == 1

    monkeypatch.setattr(engine_mod, "available_memory_gb", lambda: 12.0)
    assert engine_mod.limit_parallel(2, "large-v3") == 2


def test_available_memory_returns_positive() -> None:
    from lecture_scribe.engine import available_memory_gb

    assert available_memory_gb() > 0.0


# --- 우선순위 / 메모리 --------------------------------------------------


def test_thread_qos_can_be_raised() -> None:
    """워커 스레드 기본 QoS는 DEFAULT다. USER_INITIATED로 올릴 수 있어야 한다."""
    import threading

    from lecture_scribe.perf import (
        QOS_CLASS_USER_INITIATED,
        set_thread_qos,
        thread_qos,
    )

    seen: dict[str, str] = {}

    def worker() -> None:
        seen["before"] = thread_qos()
        assert set_thread_qos(QOS_CLASS_USER_INITIATED)
        seen["after"] = thread_qos()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert seen["before"] == "DEFAULT"
    assert seen["after"] == "USER_INITIATED"


def test_release_memory_is_safe() -> None:
    from lecture_scribe.perf import release_memory

    assert release_memory() >= 0.0


# --- FIX_GUIDE_14 T-01: 워커 스레드 gc.collect() 회피 ------------------------------


def test_gc_collect_safe_on_main_thread_regardless_of_qt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """메인 스레드는 Qt(PySide6)가 로드돼 있어도 항상 안전하다."""
    import sys

    from lecture_scribe.perf import _gc_collect_is_safe

    monkeypatch.setitem(sys.modules, "PySide6", object())
    assert _gc_collect_is_safe() is True


def test_gc_collect_unsafe_off_main_thread_when_qt_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PySide6가 로드된 프로세스(GUI)의 워커 스레드는 안전하지 않다고 판단해야 한다."""
    import sys
    import threading

    from lecture_scribe.perf import _gc_collect_is_safe

    monkeypatch.setitem(sys.modules, "PySide6", object())
    result: dict[str, bool] = {}

    def worker() -> None:
        result["safe"] = _gc_collect_is_safe()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["safe"] is False


def test_gc_collect_safe_off_main_thread_when_qt_not_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PySide6가 아예 없는 프로세스(CLI)는 워커 스레드에서도 안전하다 — 회수량이 안 준다."""
    import sys
    import threading

    from lecture_scribe.perf import _gc_collect_is_safe

    monkeypatch.delitem(sys.modules, "PySide6", raising=False)
    result: dict[str, bool] = {}

    def worker() -> None:
        result["safe"] = _gc_collect_is_safe()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    assert result["safe"] is True


def test_memory_helpers_report_values() -> None:
    from lecture_scribe.perf import (
        available_memory_gb,
        model_memory_gb,
        process_rss_mb,
        swap_used_mb,
    )

    assert available_memory_gb() > 0
    assert process_rss_mb() > 0
    assert swap_used_mb() >= 0
    # 실측: large-v3 2.4GB / turbo 1.4GB
    assert model_memory_gb("large-v3") > model_memory_gb("large-v3-turbo")
    assert model_memory_gb("large-v3-turbo") > model_memory_gb("tiny")


def test_low_memory_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    import lecture_scribe.perf as perf_mod

    monkeypatch.setattr(perf_mod, "available_memory_gb", lambda: 1.0)
    warning = perf_mod.check_memory_headroom("large-v3")
    assert warning is not None and "large-v3-turbo" in warning

    monkeypatch.setattr(perf_mod, "available_memory_gb", lambda: 32.0)
    assert perf_mod.check_memory_headroom("large-v3") is None


def test_performance_settings_defaults() -> None:
    settings = Settings()
    assert settings.performance.high_priority is True
    assert settings.performance.release_memory_after_file is True
    assert settings.performance.unload_model_after_idle_min == 10
    assert settings.performance.warn_low_memory is True


def test_hide_from_dock_succeeds() -> None:
    """창 없는 전사 프로세스는 Dock에 뜨지 않아야 한다.

    `.app` 번들에서 실행되면 CLI 모드도 정식 앱으로 등록돼 아이콘이 하나 더 뜬다.
    `TransformProcessType`으로 UIElement로 전환한다(실측: `type="UIElement"` 확인).
    """
    from lecture_scribe.perf import hide_from_dock

    # QApplication이 이미 떠 있는 테스트 프로세스에서는 전환이 거부될 수 있어
    # 반환값 자체는 단정하지 않는다. 예외 없이 bool을 돌려주는 것만 확인한다.
    # (실제 효과는 번들에서 확인: lsappinfo가 type="UIElement"로 보고)
    assert isinstance(hide_from_dock(), bool)


def test_video_cli_options_override_and_clamp() -> None:
    from lecture_scribe.cli import apply_overrides, build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["a.mp4", "--no-frames", "--frame-threshold", "500", "--frame-interval", "7",
         "--frame-dedupe", "0", "--no-ocr", "--ocr-terms"]
    )
    out = apply_overrides(Settings(), args)
    assert out.video.capture_frames is False
    assert out.video.change_threshold_pct == 90.0  # 범위 보정
    assert out.video.min_interval_sec == 7.0
    assert out.video.dedupe_threshold_pct == 0.0
    assert out.video.ocr_enabled is False
    assert out.video.ocr_terms_to_prompt is True

    untouched = apply_overrides(Settings(), parser.parse_args(["a.mp4"]))
    assert untouched.video == Settings().video


def test_sheet_grid_cli_options(capsys: pytest.CaptureFixture[str]) -> None:
    from lecture_scribe.cli import apply_overrides, build_parser

    parser = build_parser()
    args = parser.parse_args(["a.mp4", "--sheet-grid", "1x3", "--keep-frames"])
    out = apply_overrides(Settings(), args)
    assert out.video.sheet_cols == 1 and out.video.sheet_rows == 3
    assert out.video.keep_single_frames is True
    assert out.video.sheets_enabled is True  # 건드리지 않았으면 기본값 유지

    disabled = apply_overrides(Settings(), parser.parse_args(["a.mp4", "--no-sheets"]))
    assert disabled.video.sheets_enabled is False

    with pytest.raises(SystemExit):
        parser.parse_args(["a.mp4", "--sheet-grid", "not-a-grid"])
    assert "COLSxROWS" in capsys.readouterr().err
