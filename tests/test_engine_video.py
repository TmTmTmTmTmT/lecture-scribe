"""engine.transcribe_file의 영상 입력 경로 (PLAN_VIDEO_FRAMES.md V-02b/V-05)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from test_frames import make_video

from lecture_scribe import engine
from lecture_scribe.backends.base import (
    BackendCapabilities,
    Segment,
    StatusCallback,
    TranscriptionRequest,
    TranscriptionStream,
)
from lecture_scribe.config import Preset, Settings
from lecture_scribe.engine import transcribe_file
from lecture_scribe.video_stage import VideoStageResult

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")


class RecordingBackend:
    def __init__(self) -> None:
        self.loaded = False
        self.requests: list[TranscriptionRequest] = []

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

    def transcribe(
        self, request: TranscriptionRequest, *, on_heartbeat: StatusCallback | None = None
    ) -> TranscriptionStream:
        self.requests.append(request)
        seg = Segment(
            id=0, start=0.0, end=1.0, text=" 안녕하세요.", avg_logprob=-0.3,
            no_speech_prob=0.01, compression_ratio=1.4, temperature=0.0,
        )
        return TranscriptionStream(
            language="ko", language_probability=0.99, duration_sec=1.0,
            duration_after_vad_sec=1.0, segments=iter([seg]),
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def unload(self) -> None:
        self.loaded = False


def settings_for_test(**video: object) -> Settings:
    settings = Settings()
    settings.video = replace(settings.video, ocr_enabled=False, **video)  # type: ignore[arg-type]
    return settings


@pytest.mark.integration
@needs_ffmpeg
def test_silent_video_is_processed_frames_only(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    backend = RecordingBackend()
    result = transcribe_file(video, settings_for_test(), backend, emit_handoff=True)  # type: ignore[arg-type]
    assert result.status == "ok"
    assert result.frames_only and result.frame_count == 3
    assert not backend.loaded  # 모델을 불러오지 않는다
    assert result.outputs[0].format == "frames"
    frames_dir = result.outputs[0].path
    assert frames_dir is not None and frames_dir.name == "silent.frames"
    # 기본 1x2 시트(칸 2개): 프레임 3장이 시트 2장으로 묶이고 낱장은 지워진다(FIX_GUIDE_13 S-01/S-02).
    jpgs = sorted(p.name for p in frames_dir.glob("*.jpg"))
    assert len(jpgs) == 2 and all(name.startswith("sheet_") for name in jpgs)
    assert sorted(p.suffix for p in frames_dir.iterdir()) == [".jpg"] * 2 + [".json", ".md"]
    data = json.loads((frames_dir / "frames.json").read_text())
    assert data["time_basis"] == "video_file" and len(data["frames"]) == 3
    assert data["single_frames_kept"] is False
    assert data["frames"][0]["file"] is None and data["frames"][0]["sheet"] in jpgs
    assert "캡처 3장" in (frames_dir / "frames.md").read_text()
    assert (tmp_path / "silent.handoff.md").exists()
    assert not (tmp_path / "silent.txt").exists() and not (tmp_path / "silent.md").exists()
    assert any("오디오 트랙이 없어" in w for w in result.warnings)


@pytest.mark.integration
@needs_ffmpeg
def test_silent_video_with_capture_off_still_reports_no_audio(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    result = transcribe_file(
        video, settings_for_test(capture_frames=False), RecordingBackend()  # type: ignore[arg-type]
    )
    assert result.status == "failed"
    assert result.error_user is not None and "오디오 트랙" in result.error_user


@pytest.mark.integration
@needs_ffmpeg
def test_video_with_audio_transcribes_and_captures(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=True)
    backend = RecordingBackend()
    result = transcribe_file(video, settings_for_test(), backend)  # type: ignore[arg-type]
    assert result.status == "ok" and not result.frames_only
    assert backend.loaded
    assert result.frame_count == 3
    formats = [o.format for o in result.outputs]
    assert formats[0] != "frames" and formats[-1] == "frames"  # 전사문이 outputs[0]
    assert (tmp_path / "with_audio.txt").exists()


@pytest.mark.integration
@needs_ffmpeg
def test_existing_frames_dir_is_skipped_with_skip_policy(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    (tmp_path / "silent.frames").mkdir()
    settings = settings_for_test()
    settings.output.on_conflict = "skip"
    result = transcribe_file(video, settings, RecordingBackend())  # type: ignore[arg-type]
    assert result.status == "skipped"


def test_audio_file_path_is_unchanged(tmp_path: Path) -> None:
    """오디오 파일은 영상 단계를 건드리지 않는다(회귀)."""
    sample = Path(__file__).parent.parent / "assets" / "samples" / "en_5s.m4a"
    if not sample.exists():
        pytest.skip("샘플 오디오 없음")
    audio = tmp_path / "en_5s.m4a"
    shutil.copy(sample, audio)
    backend = RecordingBackend()
    result = transcribe_file(audio, Settings(), backend)  # type: ignore[arg-type]
    assert result.status == "ok"
    assert result.frames_dir is None and result.frame_count == 0
    assert all(o.format != "frames" for o in result.outputs)


def _fake_stage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, terms: list[str]) -> None:
    frames_dir = tmp_path / "x.frames"
    frames_dir.mkdir(exist_ok=True)

    def fake(*args: object, **kwargs: object) -> VideoStageResult:
        return VideoStageResult(
            frames_dir=frames_dir, frame_count=2, ocr_done=True, ocr_terms=list(terms)
        )

    monkeypatch.setattr(engine, "run_video_stage", fake)


@pytest.mark.integration
@needs_ffmpeg
def test_ocr_terms_are_added_to_prompt_only_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = make_video(tmp_path, audio=True)
    _fake_stage(monkeypatch, tmp_path, ["Nyquist Sampling Theorem", "LPF"])

    settings = settings_for_test()
    settings.presets["기본"] = Preset(topic="통신", glossary=["임피던스"])
    settings.prompt.use_hotwords = True

    off = RecordingBackend()
    result_off = transcribe_file(video, settings, off)  # type: ignore[arg-type]
    assert "LPF" not in (off.requests[0].hotwords or "")
    assert result_off.ocr_terms_applied == []

    settings.video = replace(settings.video, ocr_terms_to_prompt=True)
    on = RecordingBackend()
    result_on = transcribe_file(video, settings, on)  # type: ignore[arg-type]
    hotwords = on.requests[0].hotwords or ""
    assert "임피던스" in hotwords and "LPF" in hotwords
    assert hotwords.index("임피던스") < hotwords.index("LPF")  # 사용자 용어가 앞
    assert result_on.ocr_terms_applied  # 실제 반영된 용어 기록
    # 프리셋(영구 설정)은 오염되지 않는다
    assert settings.presets["기본"].glossary == ["임피던스"]


@pytest.mark.integration
@needs_ffmpeg
def test_ocr_terms_reach_correction_prompt_only_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """교정용 OCR 용어는 `correction.use_ocr_terms`가 켜졌을 때만, 파일별로만 전달된다."""
    from lecture_scribe.correction import CorrectionResult

    video = make_video(tmp_path, audio=True)
    _fake_stage(monkeypatch, tmp_path, ["Ricean", "LPF"])
    seen: list[list[str]] = []

    def fake_propose(*args: object, **kwargs: object) -> CorrectionResult:
        seen.append(list(kwargs.get("slide_terms", [])))  # type: ignore[call-overload]
        return CorrectionResult(model="stub")

    monkeypatch.setattr(engine, "propose_corrections", fake_propose)

    settings = settings_for_test()
    settings.presets["기본"] = Preset(topic="통신", glossary=["임피던스"])
    settings.correction = replace(settings.correction, enabled=True)

    transcribe_file(video, settings, RecordingBackend())  # type: ignore[arg-type]
    assert seen[-1] == []  # 기본은 꺼짐

    settings.correction = replace(settings.correction, use_ocr_terms=True)
    transcribe_file(video, settings, RecordingBackend())  # type: ignore[arg-type]
    assert seen[-1] == ["Ricean", "LPF"]
    assert settings.presets["기본"].glossary == ["임피던스"]  # 프리셋 불변
