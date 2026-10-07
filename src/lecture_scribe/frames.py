"""강의 영상 프레임 캡처 (PLAN_VIDEO_FRAMES.md V-02).

화면이 바뀐 시점의 프레임을 골라 시간을 새긴 JPEG로 저장한다.

- **변화 감지(`FrameSelector`)는 순수 로직**이다(numpy 배열만 다룬다). ffmpeg/Pillow 입출력과
  분리해 합성 프레임으로 테스트한다.
- 알고리즘은 실측으로 검증된 형태다(샘플 1, 슬라이드 전환 20개: 포착 19, 오탐 1):
  마지막 저장본 대비 변화가 문턱을 넘으면 "대기" 상태에 들어가고, 화면이 안정되면
  그 프레임을 저장한다. 저장본 중 하나와 거의 같으면 저장하지 않는다.
- 시간은 **영상 파일 기준**이다. 배속 녹화여도 변환하지 않는다(같은 파일의 전사와 일치).
"""

from __future__ import annotations

import io
import math
import subprocess
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .audio import MediaInfo, find_binary, media_arg
from .config import VideoSettings
from .errors import CancelledError, LectureScribeError

# --- 실측 상수 (샘플 1: 18분 화면 녹화) --------------------------------------

#: 분석 샘플링 속도. 1fps는 애니메이션 완성 판정이 거칠고, 2fps는 51초/18분(CPU 590%).
SAMPLE_FPS: Final[float] = 2.0
#: 분석 해상도(가로). 높이는 원본 비율.
ANALYSIS_WIDTH: Final[int] = 192
#: 픽셀 변화 문턱(0~255). "이 이상 밝기가 달라진 픽셀"을 변한 픽셀로 센다.
PIXEL_DIFF_THRESHOLD: Final[int] = 25
#: 인접 샘플 변화가 이 값 미만이면 안정.
STABLE_CHANGE_FRACTION: Final[float] = 0.02
#: 안정이 이만큼 지속돼야 저장한다(초). 항목이 하나씩 나타나는 슬라이드의 완성본을 잡는다.
STABLE_HOLD_SEC: Final[float] = 2.0
#: 단색(검은 화면 등) 판정: 밝기 표준편차가 이 값 미만.
SOLID_STD: Final[float] = 3.0

GrayFrame = npt.NDArray[np.uint8]


class FrameCaptureError(LectureScribeError):
    """프레임 캡처 실패."""


@dataclass(slots=True, frozen=True)
class Selection:
    """선택된 시점 1건."""

    sample_index: int
    time_sec: float
    #: 대기 상태로 들어가게 만든 변화율(마지막 저장본 대비, 0~1). 첫 프레임은 0.
    change: float


def changed_fraction(
    a: GrayFrame, b: GrayFrame, pixel_threshold: int = PIXEL_DIFF_THRESHOLD
) -> float:
    """두 프레임에서 밝기 차이가 문턱을 넘은 픽셀의 비율(0~1)."""
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return float((diff > pixel_threshold).mean())


def is_solid(frame: GrayFrame) -> bool:
    return bool(frame.std() < SOLID_STD)


class FrameSelector:
    """스트리밍 변화 감지. `feed()`에 샘플 프레임을 순서대로 넣는다."""

    def __init__(
        self,
        *,
        fps: float = SAMPLE_FPS,
        change_threshold: float,
        dedupe_threshold: float,
        min_interval_sec: float,
        max_frames: int,
        stable_hold_sec: float = STABLE_HOLD_SEC,
    ) -> None:
        self._fps = fps
        self._change_threshold = change_threshold
        self._dedupe_threshold = dedupe_threshold
        self._min_interval_samples = max(1, math.ceil(min_interval_sec * fps))
        self._max_frames = max_frames
        self._hold_samples = max(1, math.ceil(stable_hold_sec * fps))

        self._prev: GrayFrame | None = None
        self._base: GrayFrame | None = None
        self._pending = True  # 첫 안정 프레임을 저장하기 위해 대기 상태로 시작
        self._trigger_change = 0.0
        self._stable = 0
        self._last_saved: int | None = None
        self._saved: list[GrayFrame] = []

    @property
    def full(self) -> bool:
        return len(self._saved) >= self._max_frames

    def feed(self, index: int, frame: GrayFrame) -> Selection | None:
        prev = self._prev
        self._prev = frame
        if self.full:
            return None

        if not self._pending and self._base is not None:
            change = changed_fraction(frame, self._base)
            if change > self._change_threshold:
                self._pending = True
                self._trigger_change = change
                self._stable = 0

        if not self._pending:
            return None

        if self._base is None and is_solid(frame):
            self._stable = 0
            return None

        if prev is not None and changed_fraction(frame, prev) < STABLE_CHANGE_FRACTION:
            self._stable += 1
        else:
            self._stable = 0
        if self._stable < self._hold_samples:
            return None
        if (
            self._last_saved is not None
            and index - self._last_saved < self._min_interval_samples
        ):
            return None  # 간격이 찰 때까지 대기 유지(안정 카운트는 계속 유지)

        # 후보 확정
        self._pending = False
        self._stable = 0
        if self._dedupe_threshold > 0 and any(
            changed_fraction(frame, saved) < self._dedupe_threshold
            for saved in self._saved
        ):
            # 앞뒤 슬라이드를 오가는 경우 등. 기준만 옮기고 저장하지 않는다.
            self._base = frame
            return None

        self._base = frame
        self._saved.append(frame.copy())
        self._last_saved = index
        trigger = self._trigger_change
        self._trigger_change = 0.0
        return Selection(index, index / self._fps, trigger)


def select_frames(
    frames: Iterator[GrayFrame] | list[GrayFrame],
    *,
    fps: float = SAMPLE_FPS,
    change_threshold: float,
    dedupe_threshold: float,
    min_interval_sec: float,
    max_frames: int,
) -> list[Selection]:
    """프레임 시퀀스 전체에서 선택 시점 목록을 만든다(테스트/스크립트용 편의 함수)."""
    selector = FrameSelector(
        fps=fps,
        change_threshold=change_threshold,
        dedupe_threshold=dedupe_threshold,
        min_interval_sec=min_interval_sec,
        max_frames=max_frames,
    )
    out: list[Selection] = []
    for i, frame in enumerate(frames):
        picked = selector.feed(i, frame)
        if picked is not None:
            out.append(picked)
    return out


# --- ffmpeg / Pillow 입출력 ---------------------------------------------------


def analysis_size(width: int, height: int) -> tuple[int, int]:
    """분석 해상도. 높이는 원본 비율에 맞추되 짝수로 한다."""
    if width <= 0 or height <= 0:
        return ANALYSIS_WIDTH, max(2, ANALYSIS_WIDTH * 9 // 16 // 2 * 2)
    h = max(2, round(ANALYSIS_WIDTH * height / width / 2) * 2)
    return ANALYSIS_WIDTH, h


def iter_sample_frames(
    video: Path,
    info: MediaInfo,
    *,
    is_cancelled: Callable[[], bool] | None = None,
) -> Iterator[GrayFrame]:
    """ffmpeg 파이프로 저해상도 흑백 프레임을 스트리밍한다.

    소프트웨어 디코딩을 쓴다. 실측(5분 클립): 소프트웨어 16.6초 vs VideoToolbox 107초,
    출력은 동일 — 이 파이프라인에서는 하드웨어 가속이 오히려 6배 느리다.
    """
    w, h = analysis_size(info.width, info.height)
    frame_bytes = w * h
    cmd = [
        str(find_binary("ffmpeg")),
        "-v",
        "error",
        "-i",
        media_arg(video),
        "-vf",
        f"fps={SAMPLE_FPS:g},scale={w}:{h}:flags=area,format=gray",
        "-f",
        "rawvideo",
        "-",
    ]
    proc = subprocess.Popen(  # noqa: S603 - 인자는 고정 목록
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    assert proc.stdout is not None
    try:
        while True:
            if is_cancelled is not None and is_cancelled():
                raise CancelledError()
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w).copy()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()


def format_hms(seconds: float, sep: str = ":") -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}{sep}{total % 3600 // 60:02d}{sep}{total % 60:02d}"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def stamp_time(image: Image.Image, label: str) -> Image.Image:
    """오른쪽 아래에 반투명 검정 박스 + 흰 글자로 시간을 새긴다.

    설치된 ffmpeg에 `drawtext`(libfreetype)가 없어 Pillow로 그린다(실측 확인).
    """
    base = image.convert("RGBA")
    size = max(14, base.width // 32)
    font = _load_font(size)
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    tw, th = right - left, bottom - top
    pad = max(4, size // 3)
    x1 = base.width - tw - pad * 2 - 6
    y1 = base.height - th - pad * 2 - 6
    draw.rectangle(
        [x1, y1, base.width - 6, base.height - 6], fill=(0, 0, 0, 170)
    )
    draw.text((x1 + pad - left, y1 + pad - top), label, font=font, fill=(255, 255, 255, 255))
    return Image.alpha_composite(base, overlay).convert("RGB")


def extract_frame(
    video: Path,
    time_sec: float,
    dest: Path,
    *,
    max_width: int,
    jpeg_quality: int,
) -> None:
    """`time_sec` 시점 프레임을 축소·시간 새김 후 JPEG로 저장."""
    cmd = [
        str(find_binary("ffmpeg")),
        "-v",
        "error",
        "-ss",
        f"{time_sec:.3f}",
        "-i",
        media_arg(video),
        "-frames:v",
        "1",
        "-vf",
        f"scale='min({max_width},iw)':-2:flags=lanczos",
        "-f",
        "image2pipe",
        "-vcodec",
        "png",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False, timeout=120)  # noqa: S603
    if proc.returncode != 0 or not proc.stdout:
        raise FrameCaptureError(
            f"프레임을 추출하지 못했습니다({format_hms(time_sec)}): {video.name}"
        )
    image = Image.open(io.BytesIO(proc.stdout))
    stamped = stamp_time(image, format_hms(time_sec))
    stamped.save(dest, format="JPEG", quality=jpeg_quality, optimize=True)


#: 시트 이미지 긴 변 목표(px). 채팅 업로드 시 재축소(약 1568px)를 앞서 맞춰 피한다.
SHEET_MAX_LONG_SIDE: Final[int] = 1568
#: 칸 사이 여백(px).
SHEET_GAP: Final[int] = 6
#: 칸 라벨 글자 크기 하한(px).
SHEET_LABEL_MIN_SIZE: Final[int] = 14
#: 칸 라벨 글자 크기 = 칸 높이 * 이 비율(하한과 큰 쪽을 쓴다).
SHEET_LABEL_HEIGHT_RATIO: Final[float] = 0.05


@dataclass(slots=True, frozen=True)
class SheetCell:
    """시트 한 칸. `frame_number`가 None이면 빈 칸(마지막 시트의 나머지)."""

    row: int
    col: int
    frame_number: int | None
    time_sec: float | None


@dataclass(slots=True, frozen=True)
class SheetRecord:
    filename: str
    rows: int
    cols: int
    cells: list[SheetCell]  # 길이는 항상 rows*cols(빈 칸 포함)
    time_start: float
    time_end: float


def cell_position_name(row: int, col: int, rows: int, cols: int) -> str:
    """frames.md에 쓸 칸 위치 이름. 2x2는 상하좌우로, 그 외는 "행-열"."""
    if rows == 2 and cols == 2:
        vert = "위" if row == 0 else "아래"
        horiz = "왼쪽" if col == 0 else "오른쪽"
        return f"{horiz} {vert}"
    return f"{row + 1}-{col + 1}"


def sheet_filename(number: int, time_start: float, time_end: float) -> str:
    return (
        f"sheet_{number:02d}_{format_hms(time_start, '-')}~{format_hms(time_end, '-')}.jpg"
    )


def _sheet_cell_size(aspect: float, cols: int, rows: int, max_long_side: int) -> tuple[int, int]:
    """칸 크기(px)를 정한다. 칸 사이 여백까지 포함한 시트의 긴 변이 `max_long_side`가 되도록 맞춘다."""
    if cols * aspect >= rows:
        cell_w = (max_long_side - (cols + 1) * SHEET_GAP) / cols
        cell_h = cell_w / aspect
    else:
        cell_h = (max_long_side - (rows + 1) * SHEET_GAP) / rows
        cell_w = cell_h * aspect
    return max(1, round(cell_w)), max(1, round(cell_h))


def _draw_cell_label(
    overlay: Image.Image, label: str, x0: int, y0: int, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
) -> None:
    """`stamp_time`과 같은 반투명 검정 박스 + 흰 글자 스타일로, 이번엔 좌상단에."""
    draw = ImageDraw.Draw(overlay)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font)
    tw, th = right - left, bottom - top
    pad = max(3, tw // len(label) // 2 if label else 3)
    box = [x0, y0, x0 + tw + pad * 2, y0 + th + pad * 2]
    draw.rectangle(box, fill=(0, 0, 0, 170))
    draw.text((x0 + pad - left, y0 + pad - top), label, font=font, fill=(255, 255, 255, 255))


def build_sheets(
    frames_dir: Path,
    records: Sequence["FrameRecord"],
    *,
    cols: int,
    rows: int,
    jpeg_quality: int,
    max_long_side: int = SHEET_MAX_LONG_SIDE,
    is_cancelled: Callable[[], bool] | None = None,
) -> list[SheetRecord]:
    """저장된 낱장 프레임을 `cols`x`rows` 격자로 이어붙여 `frames_dir`에 시트로 저장한다.

    낱장에는 이미 `stamp_time`이 우하단에 시간을 새겨 뒀지만, 칸이 작아지면 그 글자가
    안 보일 수 있어 칸마다 좌상단에 "번호 · 시간" 라벨을 새로 찍는다(FIX_GUIDE_13 S-01).
    `cols<=1 and rows<=1`이면 시트를 만들지 않는다(빈 리스트 반환 — 낱장 그대로 사용).
    """
    if (cols <= 1 and rows <= 1) or not records:
        return []
    per_sheet = cols * rows
    with Image.open(frames_dir / records[0].filename) as probe:
        aspect = probe.width / probe.height
    cell_w, cell_h = _sheet_cell_size(aspect, cols, rows, max_long_side)
    label_size = max(SHEET_LABEL_MIN_SIZE, round(cell_h * SHEET_LABEL_HEIGHT_RATIO))
    font = _load_font(label_size)
    sheet_w = cols * cell_w + (cols + 1) * SHEET_GAP
    sheet_h = rows * cell_h + (rows + 1) * SHEET_GAP

    sheets: list[SheetRecord] = []
    for sheet_index, start in enumerate(range(0, len(records), per_sheet), start=1):
        if is_cancelled is not None and is_cancelled():
            raise CancelledError()
        chunk = records[start : start + per_sheet]
        canvas = Image.new("RGB", (sheet_w, sheet_h), (255, 255, 255))
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        cells: list[SheetCell] = []
        for i in range(per_sheet):
            row, col = divmod(i, cols)
            x0 = SHEET_GAP + col * (cell_w + SHEET_GAP)
            y0 = SHEET_GAP + row * (cell_h + SHEET_GAP)
            if i >= len(chunk):
                cells.append(SheetCell(row, col, None, None))
                continue
            rec = chunk[i]
            with Image.open(frames_dir / rec.filename) as frame_img:
                fitted = ImageOps.contain(frame_img.convert("RGB"), (cell_w, cell_h))
            paste_x = x0 + (cell_w - fitted.width) // 2
            paste_y = y0 + (cell_h - fitted.height) // 2
            canvas.paste(fitted, (paste_x, paste_y))
            _draw_cell_label(overlay, f"{rec.number} · {format_hms(rec.time_sec)}", x0, y0, font)
            cells.append(SheetCell(row, col, rec.number, rec.time_sec))
        composited = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
        name = sheet_filename(sheet_index, chunk[0].time_sec, chunk[-1].time_sec)
        composited.save(frames_dir / name, format="JPEG", quality=jpeg_quality, optimize=True)
        sheets.append(SheetRecord(name, rows, cols, cells, chunk[0].time_sec, chunk[-1].time_sec))
    return sheets


@dataclass(slots=True, frozen=True)
class FrameRecord:
    number: int
    time_sec: float
    filename: str
    change: float


@dataclass(slots=True)
class FrameCaptureResult:
    frames_dir: Path
    records: list[FrameRecord] = field(default_factory=list)
    truncated: bool = False  # max_frames 도달로 중단됨


def frame_filename(number: int, time_sec: float) -> str:
    return f"{number:04d}_{format_hms(time_sec, '-')}.jpg"


ProgressFn = Callable[[float, str], None]


def capture_frames(
    video: Path,
    info: MediaInfo,
    frames_dir: Path,
    settings: VideoSettings,
    *,
    on_progress: ProgressFn | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> FrameCaptureResult:
    """영상에서 변화 시점 프레임을 골라 `frames_dir`에 저장한다."""
    if not info.has_video:
        raise FrameCaptureError(f"영상 스트림이 없습니다: {video.name}")
    frames_dir.mkdir(parents=True, exist_ok=True)
    selector = FrameSelector(
        change_threshold=settings.change_threshold_pct / 100.0,
        dedupe_threshold=settings.dedupe_threshold_pct / 100.0,
        min_interval_sec=settings.min_interval_sec,
        max_frames=settings.max_frames,
    )
    result = FrameCaptureResult(frames_dir=frames_dir)
    selections: list[Selection] = []
    total = max(info.duration_sec, 1.0)
    seen = 0
    for i, frame in enumerate(
        iter_sample_frames(video, info, is_cancelled=is_cancelled)
    ):
        seen = i + 1
        picked = selector.feed(i, frame)
        if picked is not None:
            selections.append(picked)
        if on_progress is not None and i % 20 == 0:
            on_progress(min(0.6, 0.6 * (i / SAMPLE_FPS) / total), "화면 변화 분석 중")
        if selector.full:
            result.truncated = True
            break
    if seen == 0:
        raise FrameCaptureError(f"영상 프레임을 읽지 못했습니다: {video.name}")

    for n, sel in enumerate(selections, start=1):
        if is_cancelled is not None and is_cancelled():
            raise CancelledError()
        name = frame_filename(n, sel.time_sec)
        extract_frame(
            video,
            sel.time_sec,
            frames_dir / name,
            max_width=settings.image_max_width,
            jpeg_quality=settings.jpeg_quality,
        )
        result.records.append(FrameRecord(n, sel.time_sec, name, sel.change))
        if on_progress is not None:
            on_progress(0.6 + 0.4 * n / len(selections), f"프레임 저장 {n}/{len(selections)}")
    return result
