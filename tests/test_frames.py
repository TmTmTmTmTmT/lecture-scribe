"""frames.py: 변화 감지(합성 프레임)와 ffmpeg 입출력(합성 영상, 실제 샘플 회귀)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from lecture_scribe.audio import probe_media
from lecture_scribe.config import VideoSettings
from lecture_scribe.frames import (
    FrameSelector,
    analysis_size,
    build_sheets,
    capture_frames,
    cell_position_name,
    changed_fraction,
    format_hms,
    frame_filename,
    select_frames,
    sheet_filename,
    stamp_time,
)

H, W = 54, 96


def slide(seed: int) -> np.ndarray:
    """서로 다른 시드끼리는 대부분의 픽셀이 다른 프레임."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(H, W), dtype=np.uint8)


def run(frames: list[np.ndarray], **kw: float | int) -> list[float]:
    params: dict[str, float | int] = dict(
        change_threshold=0.10,
        dedupe_threshold=0.03,
        min_interval_sec=5.0,
        max_frames=300,
    )
    params.update(kw)
    return [s.time_sec for s in select_frames(frames, **params)]  # type: ignore[arg-type]


def test_changed_fraction_basics() -> None:
    a = slide(1)
    assert changed_fraction(a, a) == 0.0
    assert changed_fraction(a, slide(2)) > 0.5
    # uint8 오버플로 없이 차이를 계산해야 한다
    assert changed_fraction(np.zeros((4, 4), np.uint8), np.full((4, 4), 255, np.uint8)) == 1.0


def test_single_transition_saves_both_after_stable_hold() -> None:
    times = run([slide(1)] * 20 + [slide(2)] * 20)
    assert len(times) == 2
    assert times[0] == pytest.approx(2.0)  # 안정 4샘플(2초) 뒤 첫 안정 프레임
    assert 10.0 <= times[1] <= 12.0  # 전환(10초) 뒤 2초 안정


def test_animation_saves_only_the_completed_frame() -> None:
    a, done = slide(1), slide(2)
    building = [slide(10 + i) for i in range(4)]  # 매 샘플 크게 바뀌는 중
    seq = [a] * 20 + building + [done] * 20
    selections = select_frames(
        seq, change_threshold=0.10, dedupe_threshold=0.03, min_interval_sec=5, max_frames=300
    )
    assert len(selections) == 2
    assert changed_fraction(seq[selections[1].sample_index], done) == 0.0


def test_cursor_jitter_is_ignored() -> None:
    frames = []
    for i in range(60):
        f = slide(1).copy()
        f[5:8, (i * 2) % W : (i * 2) % W + 3] = 255  # 작은 점이 움직임(<1%)
        frames.append(f)
    assert len(run(frames)) == 1


def test_min_interval_delays_second_save() -> None:
    times = run([slide(1)] * 6 + [slide(2)] * 30)
    assert len(times) == 2
    assert times[1] - times[0] >= 5.0


def test_returning_to_earlier_slide_is_deduped() -> None:
    a, b = slide(1), slide(2)
    seq = [a] * 20 + [b] * 20 + [a] * 20
    assert len(run(seq)) == 2
    assert len(run(seq, dedupe_threshold=0.0)) == 3


def test_solid_first_frames_are_skipped() -> None:
    black = np.zeros((H, W), np.uint8)
    seq = [black] * 10 + [slide(1)] * 20
    selections = select_frames(
        seq, change_threshold=0.10, dedupe_threshold=0.03, min_interval_sec=5, max_frames=300
    )
    assert len(selections) == 1
    assert changed_fraction(seq[selections[0].sample_index], slide(1)) == 0.0


def test_max_frames_stops_selection() -> None:
    seq = [slide(i) for i in range(1, 6) for _ in range(30)]
    selector = FrameSelector(
        change_threshold=0.10, dedupe_threshold=0.03, min_interval_sec=5, max_frames=2
    )
    picked = [selector.feed(i, f) for i, f in enumerate(seq)]
    assert sum(p is not None for p in picked) == 2
    assert selector.full


def test_change_threshold_is_respected() -> None:
    a = slide(1)
    b = a.copy()
    b[: H // 5, :] = 255 - b[: H // 5, :]  # 약 20%를 크게 바꿈
    b_small = a.copy()
    b_small[: H // 20, :] = 255 - b_small[: H // 20, :]  # 약 5%
    assert len(run([a] * 20 + [b] * 20)) == 2
    assert len(run([a] * 20 + [b_small] * 20)) == 1  # 10% 미만은 무시


def test_helpers() -> None:
    assert format_hms(3725.9) == "01:02:05"
    assert format_hms(3725, "-") == "01-02-05"
    assert frame_filename(3, 872.0) == "0003_00-14-32.jpg"
    assert analysis_size(3710, 2482)[0] == 192
    assert analysis_size(3710, 2482)[1] % 2 == 0
    stamped = stamp_time(Image.new("RGB", (640, 360), "white"), "00:14:32")
    assert stamped.size == (640, 360)
    assert stamped.getpixel((600, 340)) != (255, 255, 255)  # 오른쪽 아래에 박스가 그려짐


# --- 합성 영상 (ffmpeg) ---------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg 없음")


def make_video(tmp_path: Path, *, audio: bool) -> Path:
    """슬라이드 3장(각 8초, 2fps 프레임 2장씩만 쓰지 않도록 10fps로 생성)."""
    frames_dir = tmp_path / "png"
    frames_dir.mkdir(exist_ok=True)
    n = 0
    for seed in (1, 2, 3):
        img = Image.fromarray(np.kron(slide(seed), np.ones((8, 8), np.uint8)))
        for _ in range(80):  # 8초 @10fps
            img.save(frames_dir / f"{n:04d}.png")
            n += 1
    out = tmp_path / ("with_audio.mp4" if audio else "silent.mp4")
    cmd = ["ffmpeg", "-v", "error", "-y", "-framerate", "10", "-i", str(frames_dir / "%04d.png")]
    if audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-shortest", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)]
    subprocess.run(cmd, check=True)
    return out


@pytest.mark.integration
@needs_ffmpeg
def test_probe_media_distinguishes_silent_video(tmp_path: Path) -> None:
    silent = probe_media(make_video(tmp_path, audio=False))
    assert silent.has_video and not silent.has_audio
    assert (silent.width, silent.height) == (768, 432)
    assert silent.duration_sec == pytest.approx(24.0, abs=0.5)
    with_audio = probe_media(make_video(tmp_path, audio=True))
    assert with_audio.has_video and with_audio.has_audio


@pytest.mark.integration
@needs_ffmpeg
def test_capture_frames_on_synthetic_video(tmp_path: Path) -> None:
    video = make_video(tmp_path, audio=False)
    result = capture_frames(
        video, probe_media(video), tmp_path / "out.frames", VideoSettings()
    )
    assert [r.number for r in result.records] == [1, 2, 3]
    assert [round(r.time_sec) for r in result.records] == [2, 10, 18]  # 슬라이드 시작 + 안정 2초
    for rec in result.records:
        path = result.frames_dir / rec.filename
        assert path.exists()
        assert Image.open(path).size[0] == 768  # 원본이 max_width보다 작으면 그대로


# --- 시트(FIX_GUIDE_13 S-01) ------------------------------------------------


def test_cell_position_name_2x2_uses_corners_others_use_row_col() -> None:
    assert cell_position_name(0, 0, 2, 2) == "왼쪽 위"
    assert cell_position_name(0, 1, 2, 2) == "오른쪽 위"
    assert cell_position_name(1, 0, 2, 2) == "왼쪽 아래"
    assert cell_position_name(1, 1, 2, 2) == "오른쪽 아래"
    assert cell_position_name(0, 2, 1, 3) == "1-3"


def test_build_sheets_disabled_when_grid_is_1x1() -> None:
    assert build_sheets(Path("."), [], cols=1, rows=1, jpeg_quality=80) == []


def test_build_sheets_groups_frames_and_fills_last_sheet_with_blanks(
    tmp_path: Path,
) -> None:
    video = make_video(tmp_path, audio=False)
    frames_dir = tmp_path / "out.frames"
    capture = capture_frames(video, probe_media(video), frames_dir, VideoSettings())
    assert len(capture.records) == 3  # 2x2 격자에 넣으면 시트 1장 + 빈 칸 1개

    sheets = build_sheets(
        frames_dir, capture.records, cols=2, rows=2, jpeg_quality=80
    )
    assert len(sheets) == 1
    sheet = sheets[0]
    assert sheet.filename == sheet_filename(1, capture.records[0].time_sec, capture.records[-1].time_sec)
    assert (frames_dir / sheet.filename).exists()
    with Image.open(frames_dir / sheet.filename) as img:
        assert img.width <= 1568 and img.height <= 1568  # 채팅 재축소보다 먼저 맞춘다

    filled = [c for c in sheet.cells if c.frame_number is not None]
    blank = [c for c in sheet.cells if c.frame_number is None]
    assert [c.frame_number for c in filled] == [1, 2, 3]
    assert len(blank) == 1  # 4칸 중 3장만 채움


def test_build_sheets_splits_into_multiple_sheets_when_more_than_one_grid(
    tmp_path: Path,
) -> None:
    video = make_video(tmp_path, audio=False)
    frames_dir = tmp_path / "out.frames"
    capture = capture_frames(video, probe_media(video), frames_dir, VideoSettings())
    sheets = build_sheets(frames_dir, capture.records, cols=1, rows=2, jpeg_quality=80)
    assert len(sheets) == 2  # 3장을 1x2(칸 2개)에 나누면 2장
    numbers = [c.frame_number for s in sheets for c in s.cells if c.frame_number is not None]
    assert numbers == [1, 2, 3]  # 프레임 번호가 누락·중복 없이 시트에 다 들어간다


REAL_SAMPLE = Path("/path/to/LSsamples/화면 기록 2026-09-25 오후 2.27.35.mov")
GT_FILE = Path(__file__).parent.parent / "scripts" / "v00_probe" / "gt_sample1.json"


@pytest.mark.integration
@pytest.mark.skipif(not REAL_SAMPLE.exists(), reason="실제 샘플 영상 없음")
def test_real_sample_recall(tmp_path: Path) -> None:
    """실측 기준선: 슬라이드 전환 20개 중 19개 이상 포착, 불필요 저장 2개 이하."""
    gt = json.loads(GT_FILE.read_text())["transitions_sec"]
    result = capture_frames(
        REAL_SAMPLE, probe_media(REAL_SAMPLE), tmp_path / "s.frames", VideoSettings()
    )
    times = [r.time_sec for r in result.records]
    hit = sum(any(g - 1 <= t <= g + 20 for t in times) for g in gt)
    assert hit >= 19
    assert len(times) - hit <= 2
