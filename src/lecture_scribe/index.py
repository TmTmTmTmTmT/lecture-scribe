"""전사 인덱스 (§10.3).

전사 1건당 JSONL 1행. 에이전트가 이 파일 하나만 읽으면 전체 디렉터리를 스캔하지
않고도 대상 강의를 좁힐 수 있다(90분 강의 수십 개를 매번 읽는 것은 컨텍스트 낭비).

- append는 `fcntl.flock`으로 직렬화한다(여러 프로세스가 동시에 써도 행이 깨지지 않게).
- `rebuild()`는 **전사를 다시 하지 않고** md의 front matter만 읽어 인덱스를 만든다.
"""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from .logsetup import get_logger
from .writer import parse_front_matter, parse_yaml_list

logger = get_logger(__name__)


@dataclass(slots=True)
class IndexEntry:
    """인덱스 1행."""

    audio_path: str
    transcript_path: str
    title: str
    topic: str = ""
    glossary: list[str] = field(default_factory=list)
    language: str = ""
    duration_sec: float = 0.0
    transcribed_at: str = ""
    word_count: int = 0
    low_confidence_ratio: float = 0.0
    model: str = ""
    backend: str = ""
    #: 영상 입력의 화면 캡처 폴더(없으면 빈 문자열). 기존 JSONL과 호환되는 선택 필드.
    frames_dir: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> IndexEntry:
        return cls(
            audio_path=str(raw.get("audio_path", "")),
            transcript_path=str(raw.get("transcript_path", "")),
            title=str(raw.get("title", "")),
            topic=str(raw.get("topic", "")),
            glossary=[str(g) for g in raw.get("glossary", [])],
            language=str(raw.get("language", "")),
            duration_sec=float(raw.get("duration_sec", 0.0) or 0.0),
            transcribed_at=str(raw.get("transcribed_at", "")),
            word_count=int(raw.get("word_count", 0) or 0),
            low_confidence_ratio=float(raw.get("low_confidence_ratio", 0.0) or 0.0),
            model=str(raw.get("model", "")),
            backend=str(raw.get("backend", "")),
            frames_dir=str(raw.get("frames_dir", "")),
        )


def append_entry(entry: IndexEntry, index_path: Path) -> None:
    """인덱스에 1행 추가(락 사용). 실패해도 전사 결과를 잃지 않도록 예외를 삼키고 로그만 남긴다."""
    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        with index_path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(entry.to_json() + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        logger.warning("인덱스 기록 실패 %s: %s", index_path, exc)


def read_entries(index_path: Path) -> list[IndexEntry]:
    """인덱스를 읽는다. 깨진 행은 건너뛰고 경고를 남긴다."""
    if not index_path.exists():
        return []
    entries: list[IndexEntry] = []
    with index_path.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            for number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    entries.append(IndexEntry.from_dict(json.loads(text)))
                except json.JSONDecodeError:
                    logger.warning("인덱스 %s의 %d행을 해석할 수 없어 건너뜁니다", index_path, number)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return entries


def query(
    entries: Sequence[IndexEntry],
    *,
    topic: str | None = None,
    since: str | None = None,
) -> list[IndexEntry]:
    """주제 부분일치 / 날짜(ISO, 이후) 필터."""
    result = list(entries)
    if topic:
        needle = topic.lower()
        result = [
            entry
            for entry in result
            if needle in entry.topic.lower()
            or needle in entry.title.lower()
            or any(needle in term.lower() for term in entry.glossary)
        ]
    if since:
        threshold = _parse_date(since)
        if threshold is not None:
            result = [
                entry
                for entry in result
                if (_parse_date(entry.transcribed_at) or datetime.min) >= threshold
            ]
    return result


def _parse_date(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        pass
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def entry_from_markdown(md_path: Path) -> IndexEntry | None:
    """md의 front matter만 읽어 인덱스 항목을 만든다(전사 재수행 없음)."""
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("읽기 실패 %s: %s", md_path, exc)
        return None
    meta = parse_front_matter(text)
    if not meta or "source_audio" not in meta:
        return None
    body = text.split("---", 2)[-1]
    return IndexEntry(
        audio_path=meta.get("source_audio", ""),
        transcript_path=str(md_path),
        title=md_path.stem,
        topic=meta.get("topic", ""),
        glossary=parse_yaml_list(meta.get("glossary", "[]")),
        language=meta.get("language", ""),
        duration_sec=float(meta.get("duration_sec", "0") or 0),
        transcribed_at=meta.get("transcribed_at", ""),
        word_count=len(body.split()),
        low_confidence_ratio=float(meta.get("low_confidence_ratio", "0") or 0),
        model=meta.get("model", ""),
        backend=meta.get("backend", ""),
    )


def iter_markdown(directory: Path, recursive: bool) -> Iterator[Path]:
    pattern = "**/*.md" if recursive else "*.md"
    for path in sorted(directory.glob(pattern)):
        if path.is_file() and not path.name.startswith("."):
            yield path


def rebuild(directory: Path, index_path: Path, *, recursive: bool = False) -> list[IndexEntry]:
    """디렉터리의 md front matter를 읽어 인덱스를 다시 만든다(§10.3)."""
    entries: list[IndexEntry] = []
    for md_path in iter_markdown(directory, recursive):
        entry = entry_from_markdown(md_path)
        if entry is not None:
            entries.append(entry)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(entry.to_json() + "\n" for entry in entries)
    tmp_path = index_path.with_suffix(index_path.suffix + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, index_path)
    logger.info("인덱스 재구축 완료: %d건 -> %s", len(entries), index_path)
    return entries
