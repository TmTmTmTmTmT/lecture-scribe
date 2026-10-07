"""§10 Cowork 연계: front matter, 저신뢰 마커, 분할, 인덱스, 미러, 핸드오프."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import make_segment
from lecture_scribe.backends.base import Segment
from lecture_scribe.handoff import (
    HandoffContext,
    collect_low_confidence_spans,
    render_handoff,
)
from lecture_scribe.index import (
    IndexEntry,
    append_entry,
    entry_from_markdown,
    query,
    read_entries,
    rebuild,
)
from lecture_scribe.mirror import mirror_filename, mirror_outputs
from lecture_scribe.postprocess import CorrectionEntry
from lecture_scribe.writer import (
    low_confidence_ratio,
    parse_front_matter,
    parse_yaml_list,
    render_front_matter,
    render_md,
    split_segments_by_minutes,
    yaml_scalar,
)


# --- front matter --------------------------------------------------------


def test_yaml_scalar_quotes_colons_and_quotes() -> None:
    assert yaml_scalar("마이크로파공학 — 임피던스: 정합") == '"마이크로파공학 — 임피던스: 정합"'
    assert yaml_scalar('그는 "정합"이라 했다') == '"그는 \\"정합\\"이라 했다"'
    assert yaml_scalar("단순값") == "단순값"
    assert yaml_scalar(True) == "true"
    assert yaml_scalar(None) == "null"
    assert yaml_scalar(3.5) == "3.5"
    assert yaml_scalar("") == '""'


def test_front_matter_roundtrip_with_tricky_topic() -> None:
    meta = {
        "source_audio": "/Users/x/9:1 전자회로.m4a",
        "topic": '전자회로: 채널 "잡음"과 AWGN',
        "glossary": ["잡음", "신호 대 잡음비", "AWGN"],
        "duration_sec": 5412.0,
        "low_confidence_marker": "⟨?⟩",
    }
    text = render_front_matter(meta)
    parsed = parse_front_matter(text + "\n\n본문")
    assert parsed["source_audio"] == "/Users/x/9:1 전자회로.m4a"
    assert parsed["topic"] == '전자회로: 채널 "잡음"과 AWGN'
    assert parse_yaml_list(parsed["glossary"]) == ["잡음", "신호 대 잡음비", "AWGN"]
    assert parsed["duration_sec"] == "5412.0"


def test_front_matter_is_valid_for_downstream_split() -> None:
    """front matter 뒤 본문이 `---`로 잘려도 본문이 살아 있어야 한다."""
    text = render_front_matter({"a": 1}) + "\n\n# 제목\n\n본문"
    assert text.startswith("---\n")
    assert text.split("---", 2)[-1].strip().startswith("# 제목")


# --- 저신뢰 마커 ----------------------------------------------------------


@pytest.fixture
def mixed_segments() -> list[Segment]:
    return [
        make_segment(0, 0, 5, " 정상 인식된 문장입니다.", avg_logprob=-0.3),
        make_segment(1, 5, 10, " 신뢰도 낮은 문장", avg_logprob=-1.4),
        make_segment(2, 10, 15, " 다시 정상입니다.", avg_logprob=-0.2),
    ]


def test_low_confidence_marker_inserted(mixed_segments: list[Segment]) -> None:
    text = render_md(
        mixed_segments,
        paragraph_break_sec=0.0,
        low_confidence_logprob=-0.8,
        low_confidence_marker="⟨?⟩",
    )
    assert "⟨?⟩ 신뢰도 낮은 문장" in text
    assert "⟨?⟩ 정상 인식된 문장" not in text


def test_low_confidence_marker_absent_when_disabled(
    mixed_segments: list[Segment],
) -> None:
    text = render_md(mixed_segments, low_confidence_logprob=None)
    assert "⟨?⟩" not in text


def test_low_confidence_ratio(mixed_segments: list[Segment]) -> None:
    assert low_confidence_ratio(mixed_segments, -0.8) == pytest.approx(1 / 3)
    assert low_confidence_ratio([], -0.8) == 0.0


def test_section_headers_every_interval() -> None:
    segments = [make_segment(i, i * 300.0, i * 300.0 + 10, f" 문장{i}") for i in range(5)]
    text = render_md(segments, section_interval_min=10, paragraph_break_sec=0.0)
    assert "## [00:00:00]" in text
    assert "## [00:10:00]" in text
    assert "## [00:20:00]" in text


# --- 분할 ---------------------------------------------------------------


def test_split_segments_by_minutes() -> None:
    segments = [make_segment(i, i * 30.0, i * 30.0 + 25, f" 문장{i}") for i in range(8)]
    parts = split_segments_by_minutes(segments, 1)
    assert len(parts) == 4
    assert parts[0][0] == 0.0 and parts[0][1] == 60.0
    assert all(part[2] for part in parts)
    assert sum(len(part[2]) for part in parts) == len(segments)


def test_split_disabled_returns_single_part() -> None:
    segments = [make_segment(0, 0, 5, " 하나")]
    assert len(split_segments_by_minutes(segments, 0)) == 1


# --- 인덱스 --------------------------------------------------------------


def make_entry(title: str, topic: str = "", when: str = "2026-09-01T10:00:00") -> IndexEntry:
    return IndexEntry(
        audio_path=f"/a/{title}.m4a",
        transcript_path=f"/a/{title}.md",
        title=title,
        topic=topic,
        transcribed_at=when,
    )


def test_index_append_and_read(tmp_path: Path) -> None:
    index = tmp_path / "index.jsonl"
    append_entry(make_entry("1주차"), index)
    append_entry(make_entry("2주차"), index)
    entries = read_entries(index)
    assert [e.title for e in entries] == ["1주차", "2주차"]


def test_index_skips_broken_lines(tmp_path: Path) -> None:
    index = tmp_path / "index.jsonl"
    append_entry(make_entry("정상"), index)
    with index.open("a", encoding="utf-8") as handle:
        handle.write("{깨진 행\n")
    assert [e.title for e in read_entries(index)] == ["정상"]


def test_index_query_by_topic_and_date(tmp_path: Path) -> None:
    index = tmp_path / "index.jsonl"
    append_entry(make_entry("1주차", topic="임피던스 정합", when="2026-08-01T10:00:00"), index)
    append_entry(make_entry("2주차", topic="채널 잡음", when="2026-09-01T10:00:00"), index)
    entries = read_entries(index)
    assert [e.title for e in query(entries, topic="정합")] == ["1주차"]
    assert [e.title for e in query(entries, since="2026-08-15")] == ["2주차"]
    assert len(query(entries, topic="없는주제")) == 0


def test_index_concurrent_append_does_not_corrupt(tmp_path: Path) -> None:
    """프로세스 2개가 동시에 append해도 행이 깨지지 않아야 한다(§13)."""
    index = tmp_path / "index.jsonl"
    code = (
        "from pathlib import Path;"
        "from lecture_scribe.index import IndexEntry, append_entry;"
        "[append_entry(IndexEntry(audio_path=f'/a/{i}.m4a',"
        "transcript_path=f'/a/{i}.md', title=f'{i}'), Path(r'%s')) for i in range(40)]"
        % index
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", code], cwd=str(Path(__file__).parent.parent))
        for _ in range(2)
    ]
    for proc in procs:
        assert proc.wait(timeout=60) == 0
    lines = index.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 80
    for line in lines:
        json.loads(line)  # 깨진 행이 있으면 예외


def test_reindex_reads_front_matter_without_transcribing(tmp_path: Path) -> None:
    """reindex는 md의 front matter만 읽는다(오디오를 열지 않는다)."""
    md = tmp_path / "1주차.md"
    md.write_text(
        render_front_matter(
            {
                "source_audio": "/a/1주차.m4a",
                "transcribed_at": "2026-09-01T10:00:00",
                "duration_sec": 90.0,
                "language": "ko",
                "topic": "채널 잡음",
                "glossary": ["잡음", "AWGN"],
                "low_confidence_ratio": 0.25,
                "model": "large-v3",
                "backend": "faster",
            }
        )
        + "\n\n# 1주차\n\n본문 단어 셋\n",
        encoding="utf-8",
    )
    index = tmp_path / "index.jsonl"
    entries = rebuild(tmp_path, index, recursive=False)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.audio_path == "/a/1주차.m4a"
    assert entry.glossary == ["잡음", "AWGN"]
    assert entry.low_confidence_ratio == 0.25
    assert entry.word_count > 0
    assert read_entries(index)[0].title == "1주차"


def test_reindex_ignores_markdown_without_front_matter(tmp_path: Path) -> None:
    (tmp_path / "메모.md").write_text("# 그냥 메모\n", encoding="utf-8")
    assert rebuild(tmp_path, tmp_path / "index.jsonl") == []
    assert entry_from_markdown(tmp_path / "메모.md") is None


# --- 미러 ---------------------------------------------------------------


def test_mirror_filename_prefixes_parent_dir() -> None:
    audio = Path("/Users/x/강의/전자회로/week01.m4a")
    assert mirror_filename(Path("/Users/x/강의/전자회로/week01.md"), audio) == (
        "전자회로__week01.md"
    )


def test_mirror_hardlink_same_volume(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    audio = source_dir / "week01.m4a"
    audio.write_bytes(b"\x00")
    md = source_dir / "week01.md"
    md.write_text("본문", encoding="utf-8")
    workspace = tmp_path / "workspace"
    results = mirror_outputs([md], audio, workspace, "hardlink")
    assert len(results) == 1
    assert results[0].mode == "hardlink"
    assert results[0].downgraded_from is None
    assert results[0].target.stat().st_nlink == 2  # 하드링크


def test_mirror_copy_mode(tmp_path: Path) -> None:
    audio = tmp_path / "week01.m4a"
    audio.write_bytes(b"\x00")
    md = tmp_path / "week01.md"
    md.write_text("본문", encoding="utf-8")
    results = mirror_outputs([md], audio, tmp_path / "ws", "copy")
    assert results[0].mode == "copy"
    assert results[0].target.stat().st_nlink == 1


def test_mirror_overwrites_existing(tmp_path: Path) -> None:
    audio = tmp_path / "week01.m4a"
    audio.write_bytes(b"\x00")
    md = tmp_path / "week01.md"
    md.write_text("새 내용", encoding="utf-8")
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / mirror_filename(md, audio)).write_text("옛 내용", encoding="utf-8")
    results = mirror_outputs([md], audio, workspace, "copy")
    assert results[0].target.read_text(encoding="utf-8") == "새 내용"


# --- 핸드오프 -----------------------------------------------------------


def test_collect_low_confidence_spans_merges_adjacent(
    mixed_segments: list[Segment],
) -> None:
    segments = mixed_segments + [
        make_segment(3, 15, 20, " 또 낮음", avg_logprob=-1.2),
        make_segment(4, 20, 25, " 계속 낮음", avg_logprob=-1.1),
    ]
    spans = collect_low_confidence_spans(segments, -0.8)
    assert spans == [(5.0, 10.0), (15.0, 25.0)]


def test_render_handoff_has_required_sections(tmp_path: Path) -> None:
    context = HandoffContext(
        audio_path=tmp_path / "9:1 전자회로.m4a",
        transcript_paths=[tmp_path / "9:1 전자회로.md"],
        title="9:1 전자회로",
        topic="채널 잡음",
        glossary=["잡음", "AWGN"],
        language="ko",
        model="large-v3",
        backend="faster",
        duration_sec=5412.0,
        transcribed_at="2026-09-02T14:22:10+09:00",
        segment_count=812,
        corrections=[CorrectionEntry("자궁", "잡음", 14)],
        low_confidence_spans=[(120.0, 180.0)],
        low_confidence_marker="⟨?⟩",
        low_confidence_ratio=0.037,
    )
    text = render_handoff(context)
    assert "# 9:1 전자회로 — 후속 작업 컨텍스트" in text
    assert "90분 12초" in text
    assert "자궁 → 잡음 (14회)" in text
    assert "[00:02:00–00:03:00]" in text
    assert "⟨?⟩" in text
    assert "절 단위 요약" in text
    assert "핵심 개념" in text
    assert "예상 문제" in text
    # 본문을 복사하지 않고 링크만 넣는다
    assert str(tmp_path / "9:1 전자회로.md") in text


def test_handoff_lists_transcript_paths_not_content(tmp_path: Path) -> None:
    md = tmp_path / "a.md"
    md.write_text("전사 본문 내용 그대로", encoding="utf-8")
    context = HandoffContext(
        audio_path=tmp_path / "a.m4a",
        transcript_paths=[md],
        title="a",
        topic="",
        glossary=[],
        language="ko",
        model="tiny",
        backend="faster",
        duration_sec=10.0,
        transcribed_at="2026-09-02T00:00:00",
        segment_count=1,
        corrections=[],
        low_confidence_spans=[],
        low_confidence_marker="⟨?⟩",
        low_confidence_ratio=0.0,
    )
    text = render_handoff(context)
    assert "전사 본문 내용 그대로" not in text
    assert str(md) in text


def test_empty_transcription_leaves_explanation_not_empty_file(tmp_path: Path) -> None:
    """무음 파일이 0바이트로 저장되면 오류로 오해하기 쉽다(§15-6)."""
    from dataclasses import replace as dc_replace

    from lecture_scribe.config import Settings
    from lecture_scribe.engine import FileResult, _write_outputs

    audio = tmp_path / "무음.m4a"
    audio.write_bytes(b"\x00")
    settings = Settings()
    settings = dc_replace(
        settings, cowork=dc_replace(settings.cowork, enable_mirror=False, write_index=False)
    )
    result = FileResult(audio_path=audio, status="ok", duration_sec=30.0)
    outputs = _write_outputs([], audio, settings, None, result, "stub")
    txt = next(o for o in outputs if o.format == "txt")
    assert txt.path is not None
    content = txt.path.read_text(encoding="utf-8")
    assert content.strip(), "빈 파일을 남기면 안 된다"
    assert "음성이 감지되지 않았습니다" in content
    assert any("음성이 감지되지" in w for w in result.warnings)
