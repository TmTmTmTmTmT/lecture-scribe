"""writer.py 순수 함수 및 파일 쓰기 정책 테스트."""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path

import pytest

from lecture_scribe.backends.base import Segment
from lecture_scribe.errors import WriteFailedError
from lecture_scribe.writer import (
    format_timestamp,
    group_paragraphs,
    normalize_text,
    render_txt,
    resolve_conflict,
    target_path,
    write_output,
)


def test_format_timestamp() -> None:
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(61.4) == "00:01:01"
    assert format_timestamp(3723) == "01:02:03"
    assert format_timestamp(-5) == "00:00:00"


def test_group_paragraphs_splits_on_silence(segments: list[Segment]) -> None:
    groups = group_paragraphs(segments, paragraph_break_sec=2.0)
    assert [len(g) for g in groups] == [2, 2]


def test_group_paragraphs_disabled(segments: list[Segment]) -> None:
    groups = group_paragraphs(segments, paragraph_break_sec=0.0)
    assert len(groups) == 1


def test_render_txt_plain(segments: list[Segment]) -> None:
    text = render_txt(segments, timestamps=False, paragraph_break_sec=2.0)
    assert "임피던스 정합을 설명합니다. 반사계수는 감마로 표기합니다." in text
    assert "\n\n" in text  # 문단 분리
    assert text.endswith("\n")
    assert "\r" not in text


def test_render_txt_with_timestamps(segments: list[Segment]) -> None:
    text = render_txt(segments, timestamps=True, paragraph_break_sec=2.0)
    assert text.splitlines()[0].startswith("[00:00:00] ")
    assert "[00:00:10] 스미스 차트를 보겠습니다." in text


def test_render_txt_header_notes(segments: list[Segment]) -> None:
    text = render_txt(segments, header_notes=["동일 문장 5회 반복 감지"])
    assert text.startswith("# 동일 문장 5회 반복 감지\n")


def test_normalize_text_nfc() -> None:
    nfd = unicodedata.normalize("NFD", "강의")
    assert normalize_text(nfd) == unicodedata.normalize("NFC", "강의")
    assert normalize_text("a\r\nb") == "a\nb"


def test_target_path_same_dir_same_stem(audio_file: Path) -> None:
    assert target_path(audio_file, "txt") == audio_file.parent / "강의 01.txt"
    other = audio_file.parent / "다른"
    assert target_path(audio_file, "txt", other) == other / "강의 01.txt"


def test_resolve_conflict_policies(tmp_path: Path) -> None:
    existing = tmp_path / "a.txt"
    existing.write_text("x", encoding="utf-8")
    assert resolve_conflict(existing, "overwrite") == existing
    assert resolve_conflict(existing, "skip") is None
    assert resolve_conflict(existing, "suffix") == tmp_path / "a_1.txt"
    (tmp_path / "a_1.txt").write_text("y", encoding="utf-8")
    assert resolve_conflict(existing, "suffix") == tmp_path / "a_2.txt"
    assert resolve_conflict(tmp_path / "새 파일.txt", "suffix") == tmp_path / "새 파일.txt"


def test_write_output_creates_sibling_file(audio_file: Path, segments: list[Segment]) -> None:
    outcome = write_output(
        render_txt(segments),
        audio_file,
        "txt",
        policy="suffix",
        output_dir=None,
        fallback_dir=None,
    )
    assert outcome.path == audio_file.with_suffix(".txt")
    assert outcome.path.read_text(encoding="utf-8").startswith("임피던스")
    assert not outcome.skipped


def test_write_output_skip_policy(audio_file: Path) -> None:
    audio_file.with_suffix(".txt").write_text("기존", encoding="utf-8")
    outcome = write_output(
        "새 내용", audio_file, "txt", policy="skip", output_dir=None, fallback_dir=None
    )
    assert outcome.skipped and outcome.path is None
    assert audio_file.with_suffix(".txt").read_text(encoding="utf-8") == "기존"


def test_write_output_falls_back_on_readonly_dir(
    tmp_path: Path, audio_file: Path
) -> None:
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    fallback = tmp_path / "fallback"
    os.chmod(readonly, 0o500)
    try:
        outcome = write_output(
            "본문",
            audio_file,
            "txt",
            policy="suffix",
            output_dir=readonly,
            fallback_dir=fallback,
        )
        assert outcome.fallback_used
        assert outcome.path == fallback / "강의 01.txt"
        assert outcome.path.exists()
    finally:
        os.chmod(readonly, 0o700)


def test_write_output_raises_when_no_fallback(tmp_path: Path, audio_file: Path) -> None:
    readonly = tmp_path / "readonly2"
    readonly.mkdir()
    os.chmod(readonly, 0o500)
    try:
        with pytest.raises(WriteFailedError):
            write_output(
                "본문",
                audio_file,
                "txt",
                policy="suffix",
                output_dir=readonly,
                fallback_dir=None,
            )
    finally:
        os.chmod(readonly, 0o700)


def test_no_temp_files_left_behind(audio_file: Path) -> None:
    write_output(
        "본문", audio_file, "txt", policy="suffix", output_dir=None, fallback_dir=None
    )
    leftovers = [p.name for p in audio_file.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


# --- M3: md / srt / vtt / json 포맷 ---------------------------------------


def test_format_timestamp_ms() -> None:
    from lecture_scribe.writer import format_timestamp_ms

    assert format_timestamp_ms(0) == "00:00:00,000"
    assert format_timestamp_ms(1.5) == "00:00:01,500"
    assert format_timestamp_ms(3661.234) == "01:01:01,234"
    assert format_timestamp_ms(1.5, separator=".") == "00:00:01.500"


def test_render_srt(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render_srt

    text = render_srt(segments)
    lines = text.splitlines()
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,000"
    assert lines[2] == "임피던스 정합을 설명합니다."
    assert lines[3] == ""
    assert "4\n00:00:12,000 --> 00:00:14,000" in text


def test_render_vtt(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render_vtt

    text = render_vtt(segments)
    assert text.startswith("WEBVTT\n\n")
    assert "00:00:10.000 --> 00:00:12.000" in text


def test_render_md_has_section_headers(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render_md

    text = render_md(segments, title="강의 01", section_interval_min=1)
    assert text.startswith("# 강의 01\n")
    assert "## [00:00:00]" in text


def test_render_md_without_sections(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render_md

    text = render_md(segments, section_interval_min=0)
    assert "## [" not in text


def test_render_md_front_matter_first(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render_md

    text = render_md(segments, front_matter="---\nlanguage: ko\n---")
    assert text.startswith("---\nlanguage: ko\n---\n")


def test_render_md_warning_notes(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render_md

    text = render_md(segments, header_notes=["동일 문장 5회 반복"])
    assert "> ⚠️ 동일 문장 5회 반복" in text


def test_render_md_force_mark_ids_marks_regardless_of_logprob(
    segments: list[Segment],
) -> None:
    """FIX_GUIDE_5.md B-02: 신뢰도가 높아도 외래 문자 검출 세그먼트는 표시한다."""
    from lecture_scribe.writer import render_md

    text = render_md(
        segments,
        section_interval_min=0,
        timestamps=True,
        low_confidence_logprob=None,
        force_mark_ids=frozenset({2}),
    )
    lines = [line for line in text.splitlines() if segments[2].text.strip() in line]
    assert lines and "⟨?⟩" in lines[0]
    other_lines = [
        line for line in text.splitlines() if segments[0].text.strip() in line
    ]
    assert other_lines and "⟨?⟩" not in other_lines[0]


def test_render_md_force_mark_ids_combines_with_low_confidence(
    segments: list[Segment],
) -> None:
    from lecture_scribe.writer import render_md

    text = render_md(
        segments,
        section_interval_min=0,
        timestamps=True,  # 세그먼트별 줄 분리 -> 마킹 대상 식별이 명확해진다
        low_confidence_logprob=-0.8,  # 전부 -0.3이라 이 기준으로는 아무도 안 걸림
        force_mark_ids=frozenset({1}),
    )
    marked = [line for line in text.splitlines() if line.startswith(
        f"`[{format_timestamp(segments[1].start)}]` ⟨?⟩"
    )]
    assert len(marked) == 1
    assert not any(
        line.startswith(f"`[{format_timestamp(segments[0].start)}]` ⟨?⟩")
        for line in text.splitlines()
    )


def test_render_json_roundtrip(segments: list[Segment]) -> None:
    import json

    from lecture_scribe.writer import render_json

    payload = json.loads(render_json(segments, {"language": "ko", "model": "large-v3"}))
    assert payload["language"] == "ko"
    assert len(payload["segments"]) == 4
    first = payload["segments"][0]
    assert first["start"] == 0.0 and first["end"] == 2.0
    assert first["text"] == "임피던스 정합을 설명합니다."
    assert "avg_logprob" in first and "no_speech_prob" in first


def test_render_dispatch_all_formats(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render

    for fmt in ("txt", "md", "srt", "vtt", "json"):
        assert render(fmt, segments).strip()


def test_render_unknown_format_raises(segments: list[Segment]) -> None:
    from lecture_scribe.writer import render

    with pytest.raises(ValueError):
        render("docx", segments)


def test_all_formats_are_nfc_and_lf(segments: list[Segment]) -> None:
    import unicodedata

    from lecture_scribe.writer import render

    for fmt in ("txt", "md", "srt", "vtt", "json"):
        text = render(fmt, segments)
        assert text == unicodedata.normalize("NFC", text)
        assert "\r" not in text
