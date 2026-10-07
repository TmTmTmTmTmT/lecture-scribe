"""전사 결과 파일 출력.

규칙(F-05):
- 기본 저장 위치는 **원본과 같은 디렉터리**, **같은 basename**, 확장자만 교체.
- 파일명 충돌은 overwrite / suffix / skip 정책으로 처리.
- 쓰기 실패(읽기 전용 볼륨·권한 없음) 시 대체 폴더로 저장하고 그 사실을 알린다.
- 파일 *내용*은 NFC 정규화, 개행 LF, UTF-8(BOM 없음).

렌더링 함수는 순수 함수다(파일시스템 비의존).
"""

from __future__ import annotations

import json
import math
import textwrap
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from .backends.base import Segment
from .config import ConflictPolicy
from .errors import WriteFailedError

_MAX_SUFFIX_TRIES = 1000


# --- 순수 렌더링 -------------------------------------------------------


def format_timestamp(seconds: float, *, always_hours: bool = True) -> str:
    """초 -> HH:MM:SS."""
    total = int(max(0.0, seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if always_hours or hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def group_paragraphs(
    segments: Sequence[Segment], paragraph_break_sec: float
) -> list[list[Segment]]:
    """무음 간격이 임계값 이상이면 문단을 나눈다."""
    paragraphs: list[list[Segment]] = []
    current: list[Segment] = []
    previous_end: float | None = None
    for segment in segments:
        if (
            previous_end is not None
            and paragraph_break_sec > 0
            and segment.start - previous_end >= paragraph_break_sec
            and current
        ):
            paragraphs.append(current)
            current = []
        current.append(segment)
        previous_end = segment.end
    if current:
        paragraphs.append(current)
    return paragraphs


def _wrap(text: str, width: int) -> str:
    if width <= 0:
        return text
    return "\n".join(
        textwrap.fill(line, width=width) if line else "" for line in text.split("\n")
    )


def render_txt(
    segments: Sequence[Segment],
    *,
    timestamps: bool = False,
    paragraph_break_sec: float = 2.0,
    line_width: int = 0,
    header_notes: Iterable[str] = (),
) -> str:
    """txt 본문 렌더링.

    header_notes는 반복/환각 경고 등 결과 파일 상단 주석(옵션)이다.
    """
    lines: list[str] = []
    for note in header_notes:
        lines.append(f"# {note}")
    if lines:
        lines.append("")

    for paragraph in group_paragraphs(segments, paragraph_break_sec):
        if timestamps:
            for segment in paragraph:
                lines.append(
                    f"[{format_timestamp(segment.start)}] {segment.text.strip()}"
                )
        else:
            body = " ".join(s.text.strip() for s in paragraph).strip()
            lines.append(_wrap(body, line_width))
        lines.append("")

    text = "\n".join(lines).rstrip("\n")
    return normalize_text(text + "\n" if text else "")


# --- YAML front matter (§10.1) -----------------------------------------
#
# PyYAML을 쓰지 않는다(§4 고정 스택 외 의존성 금지). 우리가 쓰는 스칼라 종류가
# 제한적이므로 안전한 인용 규칙만 직접 구현한다.

_YAML_NEEDS_QUOTE = set(':#{}[]&*!|>%@`,"\'')


def yaml_scalar(value: object) -> str:
    """YAML 스칼라 직렬화. 콜론·따옴표가 든 문자열도 안전하게 인용한다."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if text == "":
        return '""'
    needs_quote = (
        any(char in _YAML_NEEDS_QUOTE for char in text)
        or text.strip() != text
        or text[0] in "-?"
        or text.lower() in {"true", "false", "null", "yes", "no", "on", "off"}
    )
    if "\n" in text:
        text = text.replace("\n", " ")
        needs_quote = True
    if needs_quote:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def yaml_list(values: Sequence[object]) -> str:
    return "[" + ", ".join(yaml_scalar(value) for value in values) + "]"


def render_front_matter(meta: dict[str, Any]) -> str:
    """`---`로 감싼 YAML front matter. 값 순서는 사람이 읽기 좋은 순서로 고정한다."""
    lines = ["---"]
    for key, value in meta.items():
        if isinstance(value, (list, tuple)):
            lines.append(f"{key}: {yaml_list(value)}")
        else:
            lines.append(f"{key}: {yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def parse_front_matter(text: str) -> dict[str, str]:
    """front matter를 되읽는다(reindex용, 전사 재수행 없이 메타만 취득).

    값은 문자열로 돌려준다. 리스트는 `[a, b]` 형태 그대로 둔다.
    """
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith(" "):
            continue
        key, _, raw = line.partition(":")
        value = raw.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        result[key.strip()] = value
    return result


def parse_yaml_list(value: str) -> list[str]:
    """`[a, "b, c"]` 형태를 리스트로 되돌린다."""
    text = value.strip()
    if not (text.startswith("[") and text.endswith("]")):
        return []
    body = text[1:-1]
    items: list[str] = []
    current = ""
    quoted = False
    for char in body:
        if char == '"':
            quoted = not quoted
            continue
        if char == "," and not quoted:
            items.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        items.append(current.strip())
    return [item for item in items if item]


def format_timestamp_ms(seconds: float, *, separator: str = ",") -> str:
    """초 -> HH:MM:SS,mmm (SRT) / HH:MM:SS.mmm (VTT)."""
    total_ms = int(round(max(0.0, seconds) * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def render_srt(segments: Sequence[Segment]) -> str:
    """SRT 자막."""
    blocks: list[str] = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            f"{index}\n"
            f"{format_timestamp_ms(segment.start)} --> {format_timestamp_ms(segment.end)}\n"
            f"{segment.text.strip()}\n"
        )
    return normalize_text("\n".join(blocks))


def render_vtt(segments: Sequence[Segment]) -> str:
    """WebVTT 자막."""
    blocks = ["WEBVTT", ""]
    for segment in segments:
        blocks.append(
            f"{format_timestamp_ms(segment.start, separator='.')} --> "
            f"{format_timestamp_ms(segment.end, separator='.')}"
        )
        blocks.append(segment.text.strip())
        blocks.append("")
    return normalize_text("\n".join(blocks))


DEFAULT_LOW_CONFIDENCE_MARKER = "⟨?⟩"


def is_low_confidence(segment: Segment, threshold: float) -> bool:
    """세그먼트 신뢰도가 임계값 미만인지.

    NaN은 **저신뢰로 본다.** `nan < threshold`는 항상 False라서, 그냥 두면
    신뢰도를 알 수 없는 구간이 멀쩡한 것처럼 표시된다(실측: mlx가 NaN을 낸다).
    """
    if math.isnan(segment.avg_logprob):
        return True
    return segment.avg_logprob < threshold


def low_confidence_ratio(segments: Sequence[Segment], threshold: float) -> float:
    """저신뢰 세그먼트 비율(front matter용)."""
    if not segments:
        return 0.0
    low = sum(1 for s in segments if is_low_confidence(s, threshold))
    return low / len(segments)


def render_md(
    segments: Sequence[Segment],
    *,
    title: str = "",
    timestamps: bool = False,
    paragraph_break_sec: float = 2.0,
    section_interval_min: int = 10,
    header_notes: Iterable[str] = (),
    front_matter: str = "",
    low_confidence_logprob: float | None = None,
    low_confidence_marker: str = DEFAULT_LOW_CONFIDENCE_MARKER,
    force_mark_ids: frozenset[int] = frozenset(),
) -> str:
    """마크다운 본문.

    - `section_interval_min` 간격으로 `## [HH:MM:SS]` 섹션 헤더를 넣어 후속 작업에서
      위치 지정과 인용이 가능하게 한다(§10.1). 0이면 헤더를 넣지 않는다.
    - `avg_logprob`이 임계값 미만인 구간 앞에 저신뢰 마커를 넣는다. 요약 에이전트가
      잘못 인식된 문장을 그럴듯하게 메우는 것을 막기 위한 장치다.
    - `force_mark_ids`에 속한 세그먼트는 `avg_logprob`과 무관하게 같은 마커로
      표시한다(FIX_GUIDE_5.md B-02: 기대 언어 밖 문자 감지). 마커는 하나로 통일한다 —
      마킹 사유가 둘이 됐다고 새 마커를 만들지 않는다.
    """
    lines: list[str] = []
    if front_matter:
        lines.append(front_matter.rstrip("\n"))
        lines.append("")
    if title:
        lines.append(f"# {title}")
        lines.append("")
    for note in header_notes:
        lines.append(f"> ⚠️ {note}")
    if header_notes:
        lines.append("")

    def mark(segment: Segment) -> str:
        text = segment.text.strip()
        should_mark = segment.id in force_mark_ids or (
            low_confidence_logprob is not None
            and is_low_confidence(segment, low_confidence_logprob)
        )
        if should_mark:
            return f"{low_confidence_marker} {text}"
        return text

    def emit_paragraphs(part: Sequence[Segment]) -> None:
        for paragraph in group_paragraphs(part, paragraph_break_sec):
            if not paragraph:
                continue
            if timestamps:
                for segment in paragraph:
                    lines.append(
                        f"`[{format_timestamp(segment.start)}]` {mark(segment)}"
                    )
            else:
                lines.append(" ".join(mark(s) for s in paragraph).strip())
            lines.append("")

    # 섹션 헤더는 **세그먼트 시각** 기준으로 나눈다. 문단 기준으로 나누면
    # 한 문단이 섹션 경계를 넘을 때 헤더가 통째로 빠진다.
    if section_interval_min > 0:
        for section_start, _section_end, part in split_segments_by_minutes(
            segments, section_interval_min
        ):
            if not part:
                continue
            lines.append(f"## [{format_timestamp(section_start)}]")
            lines.append("")
            emit_paragraphs(part)
    else:
        emit_paragraphs(segments)

    text = "\n".join(lines).rstrip("\n")
    return normalize_text(text + "\n" if text else "")


def split_segments_by_minutes(
    segments: Sequence[Segment], minutes: int
) -> list[tuple[float, float, list[Segment]]]:
    """N분 단위로 세그먼트를 나눈다(§10.6).

    Returns: [(구간 시작초, 구간 끝초, 세그먼트들)] — 빈 구간은 넣지 않는다.
    """
    if minutes <= 0 or not segments:
        return [(0.0, segments[-1].end if segments else 0.0, list(segments))]
    window = minutes * 60
    parts: list[tuple[float, float, list[Segment]]] = []
    current: list[Segment] = []
    start = 0.0
    limit = window
    for segment in segments:
        while segment.start >= limit:
            if current:
                parts.append((start, limit, current))
                current = []
            start = limit
            limit += window
        current.append(segment)
    if current:
        parts.append((start, max(limit, current[-1].end), current))
    return parts


def _json_safe(value: Any) -> Any:
    """NaN/Inf를 None으로 바꾼다(JSON에는 그런 값이 없다)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def dump_json(payload: Any, indent: int = 2) -> str:
    """JSON 직렬화. **NaN/Inf가 새어 나가지 못하게 막는다.**

    맨 `NaN`은 RFC 8259 위반이라 엄격한 파서가 파일 전체를 거부한다. 사이드카는
    에이전트가 읽으라고 만든 것이므로 반드시 유효해야 한다(실측: mlx의 NaN이
    `.transcript.json`을 통째로 못 읽게 만들었다).
    """
    return json.dumps(
        _json_safe(payload),
        ensure_ascii=False,
        indent=indent,
        sort_keys=False,
        allow_nan=False,
    )


def render_json(
    segments: Sequence[Segment], meta: dict[str, Any] | None = None
) -> str:
    """세그먼트 + 타임스탬프 + 메타데이터 JSON."""
    payload: dict[str, Any] = dict(meta or {})
    payload["segments"] = [
        {
            "id": segment.id,
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip(),
            "avg_logprob": round(segment.avg_logprob, 4),
            "no_speech_prob": round(segment.no_speech_prob, 4),
            "compression_ratio": round(segment.compression_ratio, 4),
            "temperature": segment.temperature,
        }
        for segment in segments
    ]
    return normalize_text(dump_json(payload) + "\n")


def render(
    fmt: str,
    segments: Sequence[Segment],
    *,
    timestamps: bool = False,
    paragraph_break_sec: float = 2.0,
    line_width: int = 0,
    section_interval_min: int = 10,
    header_notes: Iterable[str] = (),
    title: str = "",
    front_matter: str = "",
    meta: dict[str, Any] | None = None,
    low_confidence_logprob: float | None = None,
    low_confidence_marker: str = DEFAULT_LOW_CONFIDENCE_MARKER,
    force_mark_ids: frozenset[int] = frozenset(),
) -> str:
    """포맷 이름으로 렌더링 함수를 고른다."""
    notes = list(header_notes)
    if fmt == "txt":
        return render_txt(
            segments,
            timestamps=timestamps,
            paragraph_break_sec=paragraph_break_sec,
            line_width=line_width,
            header_notes=notes,
        )
    if fmt == "md":
        return render_md(
            segments,
            title=title,
            timestamps=timestamps,
            paragraph_break_sec=paragraph_break_sec,
            section_interval_min=section_interval_min,
            header_notes=notes,
            front_matter=front_matter,
            low_confidence_logprob=low_confidence_logprob,
            low_confidence_marker=low_confidence_marker,
            force_mark_ids=force_mark_ids,
        )
    if fmt == "srt":
        return render_srt(segments)
    if fmt == "vtt":
        return render_vtt(segments)
    if fmt == "json":
        return render_json(segments, meta)
    raise ValueError(f"지원하지 않는 출력 포맷: {fmt}")


def normalize_text(text: str) -> str:
    """파일 내용용 정규화: NFC + LF."""
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")


# --- 경로 결정 / 쓰기 --------------------------------------------------


@dataclass(slots=True, frozen=True)
class WriteOutcome:
    """출력 1건 결과."""

    format: str
    path: Path | None  # skip이면 None
    skipped: bool = False
    fallback_used: bool = False
    overwritten: bool = False


def target_path(audio_path: Path, ext: str, output_dir: Path | None = None) -> Path:
    """원본과 같은 basename + 새 확장자. output_dir 지정 시 그 폴더로."""
    directory = output_dir if output_dir is not None else audio_path.parent
    return directory / f"{audio_path.stem}.{ext.lstrip('.')}"


def resolve_conflict(path: Path, policy: ConflictPolicy) -> Path | None:
    """충돌 정책 적용. None을 돌려주면 건너뛴다."""
    if not path.exists():
        return path
    if policy == "overwrite":
        return path
    if policy == "skip":
        return None
    for index in range(1, _MAX_SUFFIX_TRIES):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise WriteFailedError(
        f"저장할 파일명을 찾지 못했습니다: {path.name}",
        f"suffix 후보 소진: {path}",
    )


def write_output(
    content: str,
    audio_path: Path,
    ext: str,
    *,
    policy: ConflictPolicy,
    output_dir: Path | None,
    fallback_dir: Path | None,
) -> WriteOutcome:
    """본문을 파일로 쓴다. 실패 시 대체 폴더로 재시도."""
    primary = target_path(audio_path, ext, output_dir)
    resolved = resolve_conflict(primary, policy)
    if resolved is None:
        return WriteOutcome(format=ext, path=None, skipped=True)

    overwritten = resolved.exists()
    payload = normalize_text(content)
    try:
        _atomic_write(resolved, payload)
        return WriteOutcome(format=ext, path=resolved, overwritten=overwritten)
    except OSError as primary_exc:
        if fallback_dir is None:
            raise WriteFailedError(
                f"결과 파일을 저장하지 못했습니다: {resolved}",
                f"쓰기 실패 {resolved}: {primary_exc}",
            ) from primary_exc

    # 대체 폴더 시도 (읽기 전용 볼륨/권한 거부 대응)
    try:
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_target = target_path(audio_path, ext, fallback_dir)
        fallback_resolved = resolve_conflict(fallback_target, policy)
        if fallback_resolved is None:
            return WriteOutcome(
                format=ext, path=None, skipped=True, fallback_used=True
            )
        _atomic_write(fallback_resolved, payload)
        return WriteOutcome(
            format=ext, path=fallback_resolved, fallback_used=True
        )
    except OSError as exc:
        raise WriteFailedError(
            f"결과 파일을 원본 위치와 대체 폴더 어디에도 저장하지 못했습니다: {audio_path.name}",
            f"대체 폴더 쓰기도 실패 {fallback_dir}: {exc}",
        ) from exc


def _atomic_write(path: Path, payload: str) -> None:
    """같은 디렉터리 임시 파일에 쓴 뒤 교체. 취소/실패 시 부분 파일이 남지 않는다."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.stem}-", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
        # mkstemp는 0600으로 만든다. 일반 문서처럼 umask를 반영한 권한으로 되돌린다.
        current_umask = os.umask(0)
        os.umask(current_umask)
        os.chmod(tmp_path, 0o666 & ~current_umask)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
