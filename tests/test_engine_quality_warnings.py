"""FIX_GUIDE_6.md C-01: FileResult.quality_warnings / info_warnings 분류."""

from __future__ import annotations

from pathlib import Path

from lecture_scribe.engine import FileResult
from lecture_scribe.postprocess import ForeignScriptRun, RepeatRun


def test_quality_warnings_collects_repeats_and_foreign_runs(tmp_path: Path) -> None:
    repeat = RepeatRun(text="안녕하세요", count=5, start=1.0, end=3.0)
    foreign = ForeignScriptRun(
        text="自然に思い出す。", count=1, start=10.0, end=12.0, segment_ids=(0,)
    )
    result = FileResult(
        audio_path=tmp_path / "a.m4a",
        status="ok",
        repeats=[repeat],
        foreign_runs=[foreign],
    )
    assert result.quality_warnings == [repeat.describe(), foreign.describe()]


def test_info_warnings_excludes_quality_warnings(tmp_path: Path) -> None:
    repeat = RepeatRun(text="안녕하세요", count=5, start=1.0, end=3.0)
    info_note = "mlx 백엔드(batched=False)에서 무시되는 옵션: vad_filter"
    result = FileResult(
        audio_path=tmp_path / "a.m4a",
        status="ok",
        repeats=[repeat],
        warnings=[repeat.describe(), info_note],
    )
    assert result.info_warnings == [info_note]
    assert result.quality_warnings == [repeat.describe()]


def test_no_warnings_yields_empty_lists(tmp_path: Path) -> None:
    result = FileResult(audio_path=tmp_path / "a.m4a", status="ok")
    assert result.quality_warnings == []
    assert result.info_warnings == []
