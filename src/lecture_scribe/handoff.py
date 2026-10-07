"""후속 작업 핸드오프 파일 생성 (§10.7).

사용자가 Cowork에 이 파일 하나만 넘겨도 문맥이 갖춰지도록 한다.

**이 파일은 템플릿 문자열 조립으로 만든다. LLM을 호출하지 않는다**(§15-9).
전사 본문은 복사하지 않고 경로로 링크한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from .backends.base import Segment
from .postprocess import CorrectionEntry
from .writer import format_timestamp, is_low_confidence, normalize_text


@dataclass(slots=True, frozen=True)
class HandoffContext:
    """핸드오프 파일에 들어갈 재료."""

    audio_path: Path
    transcript_paths: list[Path]
    title: str
    topic: str
    glossary: list[str]
    language: str
    model: str
    backend: str
    duration_sec: float
    transcribed_at: str
    segment_count: int
    corrections: list[CorrectionEntry]
    low_confidence_spans: list[tuple[float, float]]
    low_confidence_marker: str
    low_confidence_ratio: float
    #: 영상 입력이면 화면 캡처 폴더(PLAN_VIDEO_FRAMES.md V-06). 없으면 None.
    frames_dir: Path | None = None
    frame_count: int = 0
    ocr_terms: list[str] = field(default_factory=list)


def collect_low_confidence_spans(
    segments: Sequence[Segment], threshold: float, *, limit: int = 40
) -> list[tuple[float, float]]:
    """저신뢰 구간을 인접한 것끼리 합쳐 목록으로 만든다."""
    spans: list[tuple[float, float]] = []
    start: float | None = None
    end: float = 0.0
    for segment in segments:
        if is_low_confidence(segment, threshold):
            if start is None:
                start = segment.start
            end = segment.end
        elif start is not None:
            spans.append((start, end))
            start = None
    if start is not None:
        spans.append((start, end))
    return spans[:limit]


def _duration_text(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes}분 {int(seconds % 60)}초"


def _frames_section(
    frames_dir: Path | None, frame_count: int, ocr_terms: list[str]
) -> str:
    """화면 캡처 안내. 캡처가 없으면 빈 문자열."""
    if frames_dir is None:
        return ""
    terms = ", ".join(ocr_terms) if ocr_terms else "(없음)"
    return f"""## 화면 캡처 (영상 입력)

- 폴더: `{frames_dir}` ({frame_count}장)
- **먼저 `{frames_dir / "frames.md"}`를 읽을 것.** 시간과 슬라이드 글자(OCR)가 표로 들어 있다.
- 이미지는 OCR만으로 부족할 때(수식, 그림, 도표)만 열 것. 이미지에도 영상 시간이 새겨져 있다.
- 시간은 영상 파일 기준이라 전사문의 `[HH:MM:SS]`와 그대로 맞출 수 있다.
- 슬라이드에서 뽑은 용어: {terms}
- 슬라이드 글자와 발화가 다르면 둘 다 적고 어느 쪽이 맞는지 추측하지 말 것.

"""


def render_frames_only_handoff(
    video_path: Path,
    frames_dir: Path,
    frame_count: int,
    duration_sec: float,
    ocr_terms: list[str],
    generated_at: str,
) -> str:
    """오디오 트랙이 없는 영상(화면 녹화)의 핸드오프. 전사가 없다."""
    section = _frames_section(frames_dir, frame_count, ocr_terms)
    text = f"""# {video_path.stem} — 후속 작업 컨텍스트 (화면 캡처만)

## 강의 메타

| 항목 | 값 |
|---|---|
| 원본 영상 | `{video_path}` |
| 처리 일시 | {generated_at} |
| 길이 | {_duration_text(duration_sec)} |
| 전사 | **없음 — 오디오 트랙이 없는 영상** |

{section}## 바로 쓸 수 있는 후속 작업 지시 예시

1. **슬라이드 내용 정리**
   > `frames.md`를 읽고 슬라이드를 시간 순서대로 정리해줘. 각 항목에 `[HH:MM:SS]`를 붙이고,
   > OCR이 깨진 수식은 해당 이미지를 열어 확인한 뒤 옮겨 적어줘. 화면에 없는 내용은 추가하지 말 것.

## 주의

- 전사가 없으므로 강의 음성 내용은 알 수 없다. 슬라이드에 적힌 내용만 근거로 삼을 것.
"""
    return normalize_text(text)


def render_handoff(context: HandoffContext) -> str:
    """핸드오프 마크다운 조립."""
    transcripts = "\n".join(f"- `{path}`" for path in context.transcript_paths) or "- (없음)"
    glossary = ", ".join(context.glossary) if context.glossary else "(없음)"
    corrections = (
        "\n".join(
            f"- {entry.source} → {entry.target} ({entry.count}회)"
            for entry in context.corrections
        )
        or "- (교정 없음)"
    )
    if context.low_confidence_spans:
        spans = "\n".join(
            f"- `[{format_timestamp(start)}–{format_timestamp(end)}]`"
            for start, end in context.low_confidence_spans
        )
    else:
        spans = "- (없음)"

    text = f"""# {context.title} — 후속 작업 컨텍스트

## 강의 메타

| 항목 | 값 |
|---|---|
| 원본 오디오 | `{context.audio_path}` |
| 주제 | {context.topic or "(없음)"} |
| 전사 일시 | {context.transcribed_at} |
| 길이 | {_duration_text(context.duration_sec)} |
| 언어 | {context.language} |
| 모델 / 백엔드 | {context.model} / {context.backend} |
| 세그먼트 수 | {context.segment_count} |
| 저신뢰 비율 | {context.low_confidence_ratio:.1%} |

## 전사 본문 (내용 복사 아님, 링크)

{transcripts}

{_frames_section(context.frames_dir, context.frame_count, context.ocr_terms)}## 용어

{glossary}

## 용어 교정 이력

{corrections}

## 저신뢰 구간 — 이 구간은 추측으로 보완하지 말 것

마커 `{context.low_confidence_marker}` 는 음성 인식 신뢰도가 낮은 구간을 뜻한다.
요약·정리에서 내용을 지어내지 말고, 필요하면 "해당 구간 확인 필요"로 남길 것.

{spans}

## 바로 쓸 수 있는 후속 작업 지시 예시

1. **절 단위 요약**
   > 위 전사 본문을 `## [HH:MM:SS]` 섹션 단위로 요약해줘. 각 요약 문장 끝에
   > 근거 위치를 `[HH:MM:SS]` 형식으로 붙이고, `{context.low_confidence_marker}` 구간은
   > 요약하지 말고 "확인 필요"로 표시해줘.

2. **핵심 개념·수식 정리**
   > 이 강의에서 다룬 핵심 개념과 수식을 정리해줘. 용어 표기는 위 "용어" 목록을 따르고,
   > 각 항목에 등장 위치 `[HH:MM:SS]`를 표기해줘. 본문에 없는 내용은 추가하지 말 것.

3. **예상 문제 생성**
   > 이 강의 내용만으로 시험 예상 문제 10개와 정답을 만들어줘. 각 문제에 근거 위치
   > `[HH:MM:SS]`를 표기하고, 전사에 없는 내용은 출제하지 말 것.

4. **슬라이드와 발화를 맞춰 절별 요약** (영상 입력일 때)
   > `frames.md`의 슬라이드 시간과 전사문의 `[HH:MM:SS]`를 맞춰, 슬라이드 단위로 그 구간에서
   > 설명한 내용을 요약해줘. 슬라이드 글자와 발화가 다르면 둘 다 적고, 수식은 필요할 때만
   > 이미지를 열어 확인해줘.

## 주의

- 전사문은 **불변 자산**이다. 요약본으로 덮어쓰지 말 것.
- 인용은 `[HH:MM:SS]` 형식으로 위치를 함께 표기할 것.
"""
    return normalize_text(text)
