"""프레임 이미지 OCR (PLAN_VIDEO_FRAMES.md V-03).

macOS Vision(`VNRecognizeTextRequest`)을 로컬로 호출한다. 이미지는 기기 밖으로 나가지 않는다.
`pyobjc-framework-Vision`은 선택 설치(extra `ocr`)이며, 없으면 `OcrUnavailableError`를 던진다.
호출부는 이 예외를 잡아 경고만 남기고 전사를 계속해야 한다.

실측(샘플 1, 화면 녹화 슬라이드, ko-KR+en-US, accurate):
- 최초 호출은 모델 워밍업으로 약 28초, 이후 장당 약 0.4초.
- 영어·한국어 제목/본문은 정확하고 **수식은 깨진다.**
- 신뢰도가 0.3/0.5/1.0으로 뭉쳐 나온다 -> 신뢰도 필터로는 0.3 이하만 거를 수 있다.
- 한 화면 40~60줄 중 30줄 이상이 LMS 메뉴·탭·고정 배너(UI 줄)다 -> `flag_ui_lines`.
- 영상 플레이어 시각 표시("00:02")가 섞인다 -> `is_noise_text`.
"""

from __future__ import annotations

import re
import unicodedata
import numpy as np
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Final

from PIL import Image

from .errors import LectureScribeError

#: 이 미만은 버린다. Vision 신뢰도가 0.3/0.5/1.0으로 뭉쳐 나와 이 이상의 세분화는 의미가 없다.
MIN_CONFIDENCE: Final[float] = 0.35
#: UI 줄 판정: 전체 프레임 중 이 비율 이상에 (거의) 같은 위치·같은 글자로 등장.
#: 실측(샘플 1, 프레임 20장, 화면 가장자리 = UI로 간주해 채점): UI 줄 놓침 / 슬라이드 줄 오표시
#: 0.6 -> 61/602, 0/202 · 0.5 -> 39/602, 0/202 · 0.4 -> 23/602, 0/202 · 0.3 이하는 오표시 7/202.
UI_FRAME_RATIO: Final[float] = 0.4
#: 프레임이 이보다 적으면 빈도로 UI를 판정할 수 없으므로 규칙을 끈다.
UI_MIN_FRAMES: Final[int] = 5
_UI_MAX_DX: Final[float] = 0.04
_UI_MAX_DY: Final[float] = 0.02
#: 글자만 남긴 문자열의 유사도. 0.75는 OCR이 글자를 2개쯤 다르게 읽으면 놓친다(101/602 놓침).
_UI_MIN_SIMILARITY: Final[float] = 0.6

_TIMESTAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*\d{1,2}\s*:\s*\d{2}(\s*:\s*\d{2})?\s*$"  # OCR이 "00: 06:24"처럼 공백을 넣기도 함
)

#: 화면 맨 위 띠 판정(FIX_GUIDE_14 U-01): 줄의 아래쪽 가장자리(top-height)가 이 값 이상이면
#: "화면 맨 위 13% 안에 완전히 들어간 줄"로 본다. macOS 메뉴바·브라우저 주소창은 창을 전체화면/
#: 창 모드로 오가는 녹화에서 **일부 프레임에만** 나타날 수 있어(실측: ML검파기 샘플 13장 중
#: 5장), 빈도 기반(`flag_ui_lines`)·픽셀 불변 기반(`flag_static_lines`) 둘 다 놓친다. 위치만으로
#: 판별하면 1장에만 나와도 잡는다.
#: 실측 근거(ML검파기 13프레임 + 채널모델 6프레임, macOS Vision 좌표 top=화면 위쪽일수록 1에 가까움):
#: 메뉴바·주소창·LMS 고정 배너의 아래쪽 가장자리 최솟값 0.8946, 실제 슬라이드 제목의 top 최댓값
#: 0.8494 — 둘 사이 간격(0.045)의 중간값으로 정했다.
UI_TOP_BAND: Final[float] = 0.87
#: 위 띠 안에 있어도 줄 높이가 이보다 크면(예: 화면을 꽉 채운 큰 제목) 건드리지 않는다.
#: 실측한 메뉴바류 줄의 최대 높이는 0.024 — 넉넉히 2배로 잡는다.
UI_TOP_BAND_MAX_HEIGHT: Final[float] = 0.05


class OcrUnavailableError(LectureScribeError):
    """OCR을 쓸 수 없음(pyobjc 미설치, macOS 아님, Vision 오류)."""


@dataclass(slots=True)
class OcrLine:
    """OCR 한 줄. 좌표는 Vision 정규화 좌표(원점 왼쪽 아래)이고 `top`은 줄 위쪽 가장자리다."""

    text: str
    confidence: float
    x: float
    top: float
    #: 정규화된 너비/높이. 정적 영역 판정(`flag_static_lines`)에서 줄이 차지하는 픽셀을 구한다.
    width: float = 0.0
    height: float = 0.0
    ui: bool = False


def ocr_available() -> bool:
    try:
        import Vision  # noqa: F401
    except ImportError:
        return False
    return True


def normalize_text(text: str) -> str:
    """비교용 정규화: NFC, 소문자, 공백 정리."""
    return " ".join(unicodedata.normalize("NFC", text).lower().split())


def letters_key(text: str) -> str:
    """UI 줄 묶기용 키: 글자(한글·영문)만 남긴다.

    OCR은 아이콘을 "13", "{3", "프" 같은 글자로 읽어 줄 앞에 붙인다. 이를 제거해야
    같은 메뉴 항목끼리 묶인다.
    """
    return "".join(ch for ch in normalize_text(text) if ch.isalpha())


def is_noise_text(text: str) -> bool:
    """용어·목록에 쓸 수 없는 줄(플레이어 시각, 한 글자 등)."""
    stripped = text.strip()
    if _TIMESTAMP_RE.match(stripped):
        return True
    if stripped.isdigit():  # 플레이어 카운터("0003") 등
        return True
    return sum(ch.isalnum() for ch in stripped) < 2


def recognize(image_path: Path) -> list[OcrLine]:
    """이미지 한 장을 OCR한다. 신뢰도 미만·잡음 줄은 이미 제외되어 나온다."""
    try:
        import objc
        import Quartz
        import Vision
        from Foundation import NSURL
    except ImportError as exc:
        raise OcrUnavailableError(
            "OCR 모듈(pyobjc-framework-Vision)이 설치되지 않아 슬라이드 글자 인식을 건너뜁니다. "
            "`uv sync --extra ocr`로 설치할 수 있습니다.",
            f"pyobjc import 실패: {exc}",
        ) from exc

    with objc.autorelease_pool():
        url = NSURL.fileURLWithPath_(str(image_path.resolve()))
        source = Quartz.CGImageSourceCreateWithURL(url, None)
        if source is None:
            raise OcrUnavailableError(
                f"이미지를 열 수 없습니다: {image_path.name}",
                f"CGImageSource 생성 실패: {image_path}",
            )
        image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["ko-KR", "en-US"])
        request.setUsesLanguageCorrection_(True)
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            image, None
        )
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise OcrUnavailableError(
                f"글자 인식에 실패했습니다: {image_path.name}",
                f"Vision performRequests 실패: {error}",
            )
        lines: list[OcrLine] = []
        for observation in request.results() or []:
            candidate = observation.topCandidates_(1)[0]
            text = unicodedata.normalize("NFC", str(candidate.string())).strip()
            confidence = float(candidate.confidence())
            if confidence < MIN_CONFIDENCE or is_noise_text(text):
                continue
            box = observation.boundingBox()
            lines.append(
                OcrLine(
                    text=text,
                    confidence=confidence,
                    x=float(box.origin.x),
                    top=float(box.origin.y + box.size.height),
                    width=float(box.size.width),
                    height=float(box.size.height),
                )
            )
    # 위에서 아래로, 같은 높이면 왼쪽부터 = 읽는 순서
    lines.sort(key=lambda ln: (-round(ln.top, 2), ln.x))
    return lines


@dataclass(slots=True)
class _Cluster:
    text: str
    x: float
    top: float
    frames: set[int]


def flag_ui_lines(
    frames: Sequence[Sequence[OcrLine]],
    *,
    ratio: float = UI_FRAME_RATIO,
    min_frames: int = UI_MIN_FRAMES,
) -> int:
    """전체 프레임의 `ratio` 이상에 같은 위치·같은 글자로 나오는 줄에 `ui=True`를 표시한다.

    화면 녹화에는 LMS 메뉴, 브라우저 탭, 고정 안내 배너가 매 프레임 찍힌다. 이 줄들이
    용어 후보 상위를 차지하지 못하게 한다. OCR이 프레임마다 글자를 조금씩 다르게 읽으므로
    (예: "부정행위"/"부정형위") 글자는 유사도로, 위치는 허용 오차로 묶는다.

    프레임이 `min_frames`보다 적으면 아무것도 표시하지 않는다. 반환값은 표시한 줄 수.
    """
    total = len(frames)
    if total < min_frames:
        return 0

    clusters: list[_Cluster] = []
    membership: list[list[int]] = []  # 프레임별, 줄별 클러스터 번호
    for frame_no, lines in enumerate(frames):
        row: list[int] = []
        for line in lines:
            norm = letters_key(line.text)
            best: int | None = None
            best_score = 0.0
            for idx, cluster in enumerate(clusters):
                if (
                    abs(cluster.x - line.x) > _UI_MAX_DX
                    or abs(cluster.top - line.top) > _UI_MAX_DY
                ):
                    continue
                if not cluster.text or not norm:
                    continue
                score = SequenceMatcher(None, cluster.text, norm).ratio()
                if score >= _UI_MIN_SIMILARITY and score > best_score:
                    best, best_score = idx, score
            if best is None:
                clusters.append(_Cluster(norm, line.x, line.top, {frame_no}))
                best = len(clusters) - 1
            else:
                clusters[best].frames.add(frame_no)
            row.append(best)
        membership.append(row)

    flagged = 0
    for lines, row in zip(frames, membership, strict=True):
        for line, idx in zip(lines, row, strict=True):
            if len(clusters[idx].frames) / total >= ratio:
                line.ui = True
                flagged += 1
    return flagged


#: 정적 영역 판정: 프레임 묶음의 중앙값 이미지와 이 이상(0~255) 달라진 픽셀을 "변한 픽셀"로 센다.
STATIC_DIFF_LEVEL: Final[int] = 20
#: 줄 영역에서 변한 픽셀이 이 비율 미만이면 화면 고정 요소로 본다.
#: 실측 근거(샘플 1): 슬라이드 글줄은 글자 픽셀이 중앙값(배경)과 달라 10~25%가 변하고,
#: 메뉴·탭·배너는 거의 0%다.
STATIC_MAX_CHANGED: Final[float] = 0.04
_MEDIAN_SAMPLE_LIMIT: Final[int] = 60


def flag_static_lines(
    image_paths: Sequence[Path],
    frames: Sequence[Sequence[OcrLine]],
    *,
    min_frames: int = UI_MIN_FRAMES,
) -> int:
    """모든 프레임에서 **픽셀이 거의 변하지 않는** 영역의 줄에 `ui=True`를 표시한다.

    글자 모양이 OCR마다 달라져도(`flag_ui_lines`가 놓치는 경우) 화면 메뉴·탭·고정 배너는
    픽셀이 그대로다. 프레임들의 중앙값 이미지와 비교해, 줄이 차지한 영역이 거의 안 변했으면 UI다.
    프레임이 `min_frames`보다 적으면 중앙값이 의미 없으므로 아무것도 하지 않는다.
    """
    if len(image_paths) < min_frames or len(image_paths) != len(frames):
        return 0
    gray = [np.asarray(Image.open(p).convert("L")) for p in image_paths]
    shape = gray[0].shape
    if any(g.shape != shape for g in gray):
        return 0
    step = max(1, len(gray) // _MEDIAN_SAMPLE_LIMIT)
    median = np.median(np.stack(gray[::step]), axis=0).astype(np.int16)
    height, width = shape

    flagged = 0
    for img, lines in zip(gray, frames, strict=True):
        diff = np.abs(img.astype(np.int16) - median) > STATIC_DIFF_LEVEL
        for line in lines:
            if line.ui or line.width <= 0 or line.height <= 0:
                continue
            x0 = max(0, int(line.x * width))
            x1 = min(width, int((line.x + line.width) * width) + 1)
            y0 = max(0, int((1.0 - line.top) * height))
            y1 = min(height, int((1.0 - line.top + line.height) * height) + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            if float(diff[y0:y1, x0:x1].mean()) < STATIC_MAX_CHANGED:
                line.ui = True
                flagged += 1
    return flagged


def flag_top_band_lines(
    frames: Sequence[Sequence[OcrLine]],
    *,
    band: float = UI_TOP_BAND,
    max_height: float = UI_TOP_BAND_MAX_HEIGHT,
) -> int:
    """화면 맨 위 띠(macOS 메뉴바·브라우저 주소창 위치)에 완전히 들어간 줄에 `ui=True`.

    `flag_ui_lines`/`flag_static_lines`와 달리 **빈도·픽셀 불변에 기대지 않는다** — 위치만
    본다. 그래서 전체화면↔창 모드를 오가는 녹화에서 크롬이 일부 프레임에만 나와도 잡는다
    (FIX_GUIDE_14 U-01). 이미 `ui=True`인 줄은 건드리지 않는다.
    """
    flagged = 0
    for lines in frames:
        for line in lines:
            if line.ui or line.height <= 0:
                continue
            if line.top - line.height >= band and line.height <= max_height:
                line.ui = True
                flagged += 1
    return flagged
