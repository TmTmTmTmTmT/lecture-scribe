"""video_stage.run_video_stage의 시트화·낱장 정리 (FIX_GUIDE_13 S-01/S-02/S-03)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from test_frames import make_video

from lecture_scribe.audio import probe_media
from lecture_scribe.config import Settings
from lecture_scribe.video_stage import run_video_stage

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")


def _settings(**video: object) -> Settings:
    settings = Settings()
    settings.video = replace(settings.video, ocr_enabled=False, **video)  # type: ignore[arg-type]
    return settings


@needs_ffmpeg
def test_default_1x2_makes_two_sheets_and_deletes_singles(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    result = run_video_stage(
        video, probe_media(video), _settings(), output_dir=tmp_path
    )
    assert result.frame_count == 3
    assert len(result.sheets) == 2  # 1x2(칸 2개)라 3장이면 시트 2장
    assert result.single_frames_kept is False
    frames_dir = result.frames_dir
    assert frames_dir is not None
    singles = list(frames_dir.glob("[0-9][0-9][0-9][0-9]_*.jpg"))
    assert singles == []  # 낱장은 지워졌다
    sheets_on_disk = list(frames_dir.glob("sheet_*.jpg"))
    assert len(sheets_on_disk) == 2

    data = json.loads((frames_dir / "frames.json").read_text())
    assert data["single_frames_kept"] is False
    assert len(data["sheets"]) == 2
    assert all(f["file"] is None and f["sheet"] is not None for f in data["frames"])
    md = (frames_dir / "frames.md").read_text()
    assert "시트" in md and "1x2" in md


@needs_ffmpeg
def test_keep_single_frames_true_keeps_both(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    result = run_video_stage(
        video, probe_media(video), _settings(keep_single_frames=True), output_dir=tmp_path
    )
    assert len(result.sheets) == 2
    assert result.single_frames_kept is True
    frames_dir = result.frames_dir
    assert frames_dir is not None
    assert len(list(frames_dir.glob("[0-9][0-9][0-9][0-9]_*.jpg"))) == 3
    assert len(list(frames_dir.glob("sheet_*.jpg"))) == 2
    data = json.loads((frames_dir / "frames.json").read_text())
    assert all(f["file"] is not None for f in data["frames"])


@needs_ffmpeg
def test_sheets_disabled_keeps_legacy_single_frame_layout(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    result = run_video_stage(
        video, probe_media(video), _settings(sheets_enabled=False), output_dir=tmp_path
    )
    assert result.sheets == []
    assert result.single_frames_kept is True
    frames_dir = result.frames_dir
    assert frames_dir is not None
    assert len(list(frames_dir.glob("[0-9][0-9][0-9][0-9]_*.jpg"))) == 3
    assert list(frames_dir.glob("sheet_*.jpg")) == []
    md = (frames_dir / "frames.md").read_text()
    assert "파일" in md and "시트" not in md.split("## 캡처 목록")[1].split("\n")[2]


@needs_ffmpeg
def test_grid_1x1_is_equivalent_to_disabled(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    result = run_video_stage(
        video,
        probe_media(video),
        _settings(sheet_cols=1, sheet_rows=1),
        output_dir=tmp_path,
    )
    assert result.sheets == []
    assert result.single_frames_kept is True


@needs_ffmpeg
def test_failed_sheet_build_keeps_singles_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """시트 생성이 실패해도(예: 이미지 손상) 낱장은 보존하고 경고만 남긴다."""
    import lecture_scribe.video_stage as video_stage

    def boom(*args: object, **kwargs: object) -> list[object]:
        raise OSError("디스크 오류(테스트)")

    monkeypatch.setattr(video_stage, "build_sheets", boom)
    video = make_video(tmp_path, audio=False)
    result = run_video_stage(video, probe_media(video), _settings(), output_dir=tmp_path)
    assert result.sheets == []
    assert result.single_frames_kept is True
    assert any("시트" in w for w in result.warnings)
    frames_dir = result.frames_dir
    assert frames_dir is not None
    assert len(list(frames_dir.glob("[0-9][0-9][0-9][0-9]_*.jpg"))) == 3
