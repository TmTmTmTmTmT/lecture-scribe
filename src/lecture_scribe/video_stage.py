"""영상 입력 처리 단계: 프레임 캡처 -> OCR -> 목록 파일 (PLAN_VIDEO_FRAMES.md V-02/V-03/V-06).

`engine.transcribe_file`이 전사 앞에서 호출한다. 순서가 중요하다 — OCR 용어가 전사 프롬프트에
들어가야 하므로 전사보다 먼저 끝나야 한다.

실패 정책: OCR이 없거나 실패해도 캡처 결과는 남기고 경고만 돌려준다. 캡처 자체가 실패하면
예외를 그대로 올린다(호출부가 오디오가 있으면 전사를 계속하고, 없으면 실패로 처리한다).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .audio import MediaInfo
from .config import ConflictPolicy, Settings
from .errors import CancelledError
from .frames import (
    FrameCaptureResult,
    SheetRecord,
    build_sheets,
    capture_frames,
    cell_position_name,
    format_hms,
)
from .logsetup import get_logger
from .ocr import (
    OcrLine,
    OcrUnavailableError,
    flag_static_lines,
    flag_top_band_lines,
    flag_ui_lines,
    ocr_available,
    recognize,
)
from .slide_terms import extract_slide_terms, normalize_terms
from .writer import dump_json, normalize_text, resolve_conflict

logger = get_logger(__name__)

#: (단계 "frames"|"ocr", 진행률 0~100, 메시지)
StageProgress = Callable[[str, float, str], None]

#: `frames.md` 표의 OCR 칸에 넣을 최대 줄 수 / 글자 수
_MD_MAX_LINES = 8
_MD_MAX_CHARS = 300


@dataclass(slots=True)
class VideoStageResult:
    frames_dir: Path | None = None
    frame_count: int = 0
    truncated: bool = False
    ocr_done: bool = False
    ocr_terms: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False
    #: 만들어진 시트(FIX_GUIDE_13 S-01). 비어 있으면 시트를 안 만들었다(낱장 그대로).
    sheets: list[SheetRecord] = field(default_factory=list)
    #: 낱장 이미지(`NNNN_*.jpg`)를 지우지 않고 남겼는지.
    single_frames_kept: bool = True


def _clean_previous(frames_dir: Path) -> None:
    """덮어쓰기 정책: 이 앱이 만든 파일만 지운다(폴더째 지우지 않는다).

    패턴을 `sheet_*.jpg`/`NNNN_*.jpg`/`frames.md`/`frames.json`으로 좁힌다 — 예전엔
    `*.jpg`라 사용자가 그 폴더에 넣어둔 다른 이미지까지 지울 위험이 있었다.
    """
    for pattern in ("sheet_*.jpg", "[0-9][0-9][0-9][0-9]_*.jpg", "frames.md", "frames.json"):
        for path in frames_dir.glob(pattern):
            path.unlink(missing_ok=True)


def _prepare_dir(
    video: Path, output_dir: Path | None, policy: ConflictPolicy, fallback_dir: Path
) -> Path | None:
    """저장 폴더 결정. None이면 건너뜀. 쓸 수 없는 위치면 대체 폴더로 우회한다."""
    for base in (output_dir if output_dir is not None else video.parent, fallback_dir):
        resolved = resolve_conflict(base / f"{video.stem}.frames", policy)
        if resolved is None:
            return None
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            probe_file = resolved / ".write_test"
            probe_file.write_text("", encoding="utf-8")
            probe_file.unlink()
        except OSError:
            logger.warning("프레임 폴더를 만들 수 없어 대체 폴더를 씁니다: %s", resolved)
            continue
        if policy == "overwrite":
            _clean_previous(resolved)
        return resolved
    return None


def _ocr_cell(lines: Sequence[OcrLine]) -> str:
    texts = [ln.text.replace("|", "/") for ln in lines if not ln.ui][:_MD_MAX_LINES]
    cell = " / ".join(texts)
    return cell if len(cell) <= _MD_MAX_CHARS else cell[: _MD_MAX_CHARS - 1] + "…"


def _sheet_lookup(sheets: Sequence[SheetRecord]) -> dict[int, tuple[SheetRecord, int, int]]:
    """프레임 번호 -> (그 프레임이 든 시트, row, col)."""
    lookup: dict[int, tuple[SheetRecord, int, int]] = {}
    for sheet in sheets:
        for cell in sheet.cells:
            if cell.frame_number is not None:
                lookup[cell.frame_number] = (sheet, cell.row, cell.col)
    return lookup


def render_frames_md(
    video: Path,
    capture: FrameCaptureResult,
    ocr_lines: Sequence[Sequence[OcrLine]] | None,
    *,
    change_threshold_pct: float,
    min_interval_sec: float,
    ocr_terms: Sequence[str],
    sheets: Sequence[SheetRecord] = (),
) -> str:
    lines: list[str] = [
        f"# 화면 캡처 목록 — {video.name}",
        "",
        f"- 원본 영상: `{video}`",
        f"- 캡처 {len(capture.records)}장 (화면 변화 {change_threshold_pct:g}% 이상, 최소 간격 {min_interval_sec:g}초)"
        + (" — **최대 장수에 도달해 뒤쪽이 잘렸습니다**" if capture.truncated else ""),
        "- 시간은 **영상 파일 기준**입니다. 배속으로 녹화한 영상이면 실제 강의 시간과 다릅니다.",
        "- **이미지는 OCR만으로 부족할 때(수식, 그림, 도표)만 여세요.** OCR은 수식을 읽지 못하고 "
        "글자를 잘못 읽을 수 있습니다.",
        "- 화면 메뉴·탭 같은 고정 요소의 글자는 목록에서 제외했습니다.",
    ]
    if sheets:
        lines.append(
            f"- 이미지는 {sheets[0].cols}x{sheets[0].rows} 칸씩 묶은 시트({len(sheets)}장) 형태입니다. "
            "각 칸 좌상단 라벨이 \"번호 · 시간\"입니다."
        )
    lines.append("")
    if ocr_terms:
        lines += ["## 슬라이드에서 추출한 용어", "", ", ".join(ocr_terms), ""]
    lookup = _sheet_lookup(sheets)
    header_col = "시트" if sheets else "파일"
    lines += ["## 캡처 목록", "", f"| # | 시간 | {header_col} | 화면 글자(OCR) |", "|---|---|---|---|"]
    for i, rec in enumerate(capture.records):
        cell = _ocr_cell(ocr_lines[i]) if ocr_lines is not None else "(OCR 없음)"
        if sheets:
            sheet, row, col = lookup[rec.number]
            location = f"`{sheet.filename}` · {cell_position_name(row, col, sheet.rows, sheet.cols)}"
        else:
            location = f"`{rec.filename}`"
        lines.append(f"| {rec.number} | [{format_hms(rec.time_sec)}] | {location} | {cell} |")
    lines.append("")
    return "\n".join(lines)


def render_frames_json(
    video: Path,
    capture: FrameCaptureResult,
    ocr_lines: Sequence[Sequence[OcrLine]] | None,
    ocr_terms: Sequence[str],
    *,
    sheets: Sequence[SheetRecord] = (),
    single_frames_kept: bool = True,
) -> str:
    lookup = _sheet_lookup(sheets)
    frames = []
    for i, rec in enumerate(capture.records):
        entry: dict[str, object] = {
            "number": rec.number,
            "time_sec": rec.time_sec,
            "time": format_hms(rec.time_sec),
            "file": rec.filename if single_frames_kept else None,
            "change": round(rec.change, 4),
        }
        if rec.number in lookup:
            sheet, row, col = lookup[rec.number]
            entry["sheet"] = sheet.filename
            entry["cell"] = {"row": row, "col": col}
        else:
            entry["sheet"] = None
            entry["cell"] = None
        if ocr_lines is not None:
            entry["ocr"] = [
                {
                    "text": ln.text,
                    "confidence": round(ln.confidence, 2),
                    "ui": ln.ui,
                }
                for ln in ocr_lines[i]
            ]
        frames.append(entry)
    return dump_json(
        {
            "video": str(video),
            "time_basis": "video_file",
            "truncated": capture.truncated,
            "ocr_terms": list(ocr_terms),
            "sheets": [
                {
                    "file": sheet.filename,
                    "rows": sheet.rows,
                    "cols": sheet.cols,
                    "time_start": sheet.time_start,
                    "time_end": sheet.time_end,
                }
                for sheet in sheets
            ],
            "single_frames_kept": single_frames_kept,
            "frames": frames,
        }
    )


def run_video_stage(
    video: Path,
    info: MediaInfo,
    settings: Settings,
    *,
    output_dir: Path | None,
    on_progress: StageProgress | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> VideoStageResult:
    """프레임 캡처와 OCR을 수행하고 `<basename>.frames/`를 만든다."""
    video_cfg = settings.video
    result = VideoStageResult()

    def emit(stage: str, percent: float, message: str) -> None:
        if on_progress is not None:
            on_progress(stage, percent, message)

    frames_dir = _prepare_dir(
        video,
        output_dir,
        settings.output.on_conflict,
        settings.output.fallback_path,
    )
    if frames_dir is None:
        result.skipped = True
        result.warnings.append(
            f"이미 {video.stem}.frames 폴더가 있어 화면 캡처를 건너뛰었습니다"
        )
        return result

    emit("frames", 0.0, "화면 변화 분석 중")
    capture = capture_frames(
        video,
        info,
        frames_dir,
        video_cfg,
        on_progress=lambda frac, msg: emit("frames", frac * 100.0, msg),
        is_cancelled=is_cancelled,
    )
    result.frames_dir = frames_dir
    result.frame_count = len(capture.records)
    result.truncated = capture.truncated
    if capture.truncated:
        result.warnings.append(
            f"화면 캡처가 최대 {video_cfg.max_frames}장에 도달해 뒤쪽은 저장하지 않았습니다"
        )
    if not capture.records:
        result.warnings.append("화면 변화가 감지되지 않아 저장된 프레임이 없습니다")

    ocr_lines: list[list[OcrLine]] | None = None
    if video_cfg.ocr_enabled and capture.records:
        if not ocr_available():
            result.warnings.append(
                "OCR 모듈(pyobjc-framework-Vision)이 없어 슬라이드 글자 인식을 건너뛰었습니다"
            )
        else:
            try:
                ocr_lines = _run_ocr(capture, frames_dir, emit, is_cancelled)
            except OcrUnavailableError as exc:
                logger.warning("OCR 건너뜀 %s: %s", video.name, exc.log_message)
                result.warnings.append(f"슬라이드 글자 인식을 건너뛰었습니다: {exc.user_message}")
                ocr_lines = None

    if ocr_lines is not None:
        result.ocr_done = True
        preset = settings.current_preset()
        result.ocr_terms = normalize_terms(
            extract_slide_terms(
                ocr_lines,
                user_terms=preset.glossary,
                max_terms=video_cfg.ocr_max_terms,
            )
        )

    sheets: list[SheetRecord] = []
    sheets_wanted = bool(capture.records) and video_cfg.sheets_enabled and not (
        video_cfg.sheet_cols <= 1 and video_cfg.sheet_rows <= 1
    )
    if sheets_wanted:
        emit("frames", 95.0, "시트 이미지 만드는 중")
        try:
            sheets = build_sheets(
                frames_dir,
                capture.records,
                cols=video_cfg.sheet_cols,
                rows=video_cfg.sheet_rows,
                jpeg_quality=video_cfg.jpeg_quality,
                is_cancelled=is_cancelled,
            )
        except CancelledError:
            raise
        except OSError:
            logger.exception("시트 생성 실패 %s", video.name)
            result.warnings.append(
                "프레임 시트를 만들지 못해 낱장 이미지를 그대로 둡니다"
            )
            sheets = []
    result.sheets = sheets

    # 낱장을 지우려면 시트가 이 실행에서 만든 모든 프레임 번호를 빠짐없이 담고 있어야
    # 한다(FIX_GUIDE_13 S-02). 검증에 실패하면 낱장을 남기고 경고만 남긴다.
    sheet_frame_numbers = {
        cell.frame_number for sheet in sheets for cell in sheet.cells if cell.frame_number
    }
    capture_frame_numbers = {rec.number for rec in capture.records}
    sheets_verified = bool(sheets) and sheet_frame_numbers == capture_frame_numbers
    single_frames_kept = video_cfg.keep_single_frames or not sheets_verified
    if sheets and not sheets_verified:
        logger.warning("시트 검증 실패(프레임 번호 불일치) %s: 낱장을 보존합니다", video.name)
        result.warnings.append("시트 검증에 실패해 낱장 이미지를 그대로 둡니다")

    (frames_dir / "frames.md").write_text(
        normalize_text(
            render_frames_md(
                video,
                capture,
                ocr_lines,
                change_threshold_pct=video_cfg.change_threshold_pct,
                min_interval_sec=video_cfg.min_interval_sec,
                ocr_terms=result.ocr_terms,
                sheets=sheets if sheets_verified else [],
            )
        ),
        encoding="utf-8",
    )
    (frames_dir / "frames.json").write_text(
        normalize_text(
            render_frames_json(
                video,
                capture,
                ocr_lines,
                result.ocr_terms,
                sheets=sheets if sheets_verified else [],
                single_frames_kept=single_frames_kept,
            )
        ),
        encoding="utf-8",
    )

    if sheets_verified and not single_frames_kept:
        # 이번 실행이 만든 파일 이름만 지운다(글롭 금지 — 사용자 파일 보호).
        for rec in capture.records:
            (frames_dir / rec.filename).unlink(missing_ok=True)
    result.single_frames_kept = single_frames_kept

    emit("ocr", 100.0, "화면 캡처 완료")
    return result


def _run_ocr(
    capture: FrameCaptureResult,
    frames_dir: Path,
    emit: Callable[[str, float, str], None],
    is_cancelled: Callable[[], bool] | None,
) -> list[list[OcrLine]]:
    total = len(capture.records)
    emit("ocr", 0.0, "글자 인식 준비 중(처음 한 번은 30초쯤 걸립니다)")
    paths = [frames_dir / rec.filename for rec in capture.records]
    lines: list[list[OcrLine]] = []
    for i, path in enumerate(paths, start=1):
        if is_cancelled is not None and is_cancelled():
            raise CancelledError()
        lines.append(recognize(path))
        emit("ocr", 100.0 * i / total, f"슬라이드 글자 인식 {i}/{total}")
    # 화면 고정 요소(메뉴·탭·배너)를 표시한다. 세 방법을 합친다:
    # 글자 유사도(프레임 40% 이상) + 픽셀 불변성(중앙값 이미지 대비) + 화면 맨 위 띠 위치.
    # 세 번째(FIX_GUIDE_14 U-01)는 앞 두 방법이 놓치는 경우를 잡는다 — 전체화면↔창 모드를
    # 오가는 녹화라 메뉴바가 일부 프레임에만 나오면 빈도·픽셀 불변 둘 다 통과해 버린다.
    flag_ui_lines(lines)
    flag_static_lines(paths, lines)
    flag_top_band_lines(lines)
    return lines

