"""FIX_GUIDE_5.md B-02: 기대 언어 밖 문자 검출의 engine/writer 통합 지점."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lecture_scribe.config import Settings
from lecture_scribe.engine import FileResult, _write_outputs
from lecture_scribe.postprocess import find_foreign_script_runs

from conftest import make_segment


def _settings(tmp_path: Path) -> Settings:
    settings = Settings()
    return replace(
        settings,
        output=replace(settings.output, formats=["md"]),
        cowork=replace(
            settings.cowork,
            enable_mirror=False,
            write_index=False,
            write_sidecar_json=True,
        ),
    )


def test_foreign_run_marks_segment_in_md_output(tmp_path: Path) -> None:
    audio = tmp_path / "lec.m4a"
    audio.write_bytes(b"\x00")
    segments = [
        make_segment(0, 0.0, 2.0, "정상적인 한국어 문장입니다"),
        make_segment(1, 2.0, 4.0, "自然に思い出す。"),
        make_segment(2, 4.0, 6.0, "自然に思い出す。"),
    ]
    settings = _settings(tmp_path)
    result = FileResult(audio_path=audio, status="ok", duration_sec=6.0, language="ko")
    result.foreign_runs = find_foreign_script_runs(segments)
    assert result.foreign_runs  # 전제 확인

    outputs = _write_outputs(segments, audio, settings, None, result, "stub")
    md = next(o for o in outputs if o.format == "md")
    assert md.path is not None
    content = md.path.read_text(encoding="utf-8")
    assert "⟨?⟩" in content
    assert "기대 언어 밖 문자" in content  # 헤더 주석


def test_foreign_run_recorded_in_sidecar_json(tmp_path: Path) -> None:
    audio = tmp_path / "lec.m4a"
    audio.write_bytes(b"\x00")
    segments = [make_segment(0, 0.0, 2.0, "自然科學的方法論")]
    settings = _settings(tmp_path)
    result = FileResult(audio_path=audio, status="ok", duration_sec=2.0, language="ko")
    result.foreign_runs = find_foreign_script_runs(segments)

    outputs = _write_outputs(segments, audio, settings, None, result, "stub")
    sidecar = next(o for o in outputs if o.format == "transcript.json")
    assert sidecar.path is not None
    content = sidecar.path.read_text(encoding="utf-8")
    assert '"foreign_script_segment_count": 1' in content


def test_no_foreign_runs_leaves_output_unmarked(tmp_path: Path) -> None:
    audio = tmp_path / "lec.m4a"
    audio.write_bytes(b"\x00")
    segments = [make_segment(0, 0.0, 2.0, "정상적인 한국어 문장입니다")]
    settings = _settings(tmp_path)
    result = FileResult(audio_path=audio, status="ok", duration_sec=2.0, language="ko")
    # result.foreign_runs 기본값([]) 그대로 둔다.

    outputs = _write_outputs(segments, audio, settings, None, result, "stub")
    md = next(o for o in outputs if o.format == "md")
    assert md.path is not None
    content = md.path.read_text(encoding="utf-8")
    body = content.split("---", 2)[-1]  # front matter(마커 정의 자체 포함) 제외
    assert "⟨?⟩" not in body
