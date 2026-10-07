"""audio.py 입력 검증·수집 테스트 (ffprobe 실행 없는 순수 경로 로직 중심)."""

from __future__ import annotations

from pathlib import Path

import pytest

from lecture_scribe.audio import (
    collect_inputs,
    find_binary,
    icloud_stub_path,
    is_supported,
    probe,
    validate_input,
)
from lecture_scribe.errors import (
    EmptyFileError,
    ICloudStubError,
    MissingFileError,
    UnsupportedFormatError,
)


def test_is_supported_ignores_case() -> None:
    assert is_supported(Path("a.M4A"))
    assert is_supported(Path("a.Mp3"))
    assert is_supported(Path("영상.MOV"))
    assert not is_supported(Path("a.txt"))
    assert not is_supported(Path("확장자없음"))


def test_find_ffprobe_absolute() -> None:
    assert find_binary("ffprobe").is_absolute()


def test_validate_rejects_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "메모.txt"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(UnsupportedFormatError):
        validate_input(path)


def test_validate_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MissingFileError):
        validate_input(tmp_path / "없음.m4a")


def test_validate_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "빈파일.m4a"
    path.write_bytes(b"")
    with pytest.raises(EmptyFileError):
        validate_input(path)


def test_icloud_stub_detected(tmp_path: Path) -> None:
    target = tmp_path / "강의.m4a"
    stub = tmp_path / ".강의.m4a.icloud"
    stub.write_bytes(b"stub")
    assert icloud_stub_path(target) == stub
    with pytest.raises(ICloudStubError):
        validate_input(target)


def test_probe_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "손상.m4a"
    path.write_bytes(b"not really audio")
    from lecture_scribe.errors import CorruptAudioError

    with pytest.raises(CorruptAudioError):
        probe(path)


def test_collect_inputs_rejects_and_accepts(tmp_path: Path) -> None:
    good = tmp_path / "강의 01.m4a"
    good.write_bytes(b"\x00")
    bad = tmp_path / "노트.pdf"
    bad.write_bytes(b"\x00")
    accepted, rejected = collect_inputs([good, bad], recursive=False)
    assert accepted == [good]
    assert rejected and rejected[0][0] == bad


def test_collect_inputs_folder_recursive(tmp_path: Path) -> None:
    (tmp_path / "1주차").mkdir()
    top = tmp_path / "a.m4a"
    nested = tmp_path / "1주차" / "b.MP3"
    top.write_bytes(b"\x00")
    nested.write_bytes(b"\x00")
    accepted, _ = collect_inputs([tmp_path], recursive=False)
    assert accepted == [top]
    accepted_rec, _ = collect_inputs([tmp_path], recursive=True)
    assert set(accepted_rec) == {top, nested}


def test_collect_inputs_dedupes(tmp_path: Path) -> None:
    path = tmp_path / "a.m4a"
    path.write_bytes(b"\x00")
    accepted, _ = collect_inputs([path, path], recursive=False)
    assert accepted == [path]


def test_media_arg_is_absolute_for_colon_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`9:1 전자회로.m4a` 같은 이름을 상대 경로로 넘기면 ffmpeg이 `9:`을
    프로토콜로 오인한다(Protocol not found). 항상 절대 경로여야 한다."""
    from lecture_scribe.audio import media_arg

    path = tmp_path / "9:1 전자회로.m4a"
    path.write_bytes(b"\x00")
    monkeypatch.chdir(tmp_path)
    arg = media_arg(Path("9:1 전자회로.m4a"))
    assert arg.startswith("/")
    assert arg.endswith("9:1 전자회로.m4a")


def test_collect_inputs_returns_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "9:1 강의.m4a"
    path.write_bytes(b"\x00")
    monkeypatch.chdir(tmp_path)
    accepted, _ = collect_inputs([Path("9:1 강의.m4a")], recursive=False)
    assert accepted[0].is_absolute()


@pytest.mark.integration
def test_first_speech_offset_detects_leading_silence(tmp_path: Path) -> None:
    """앞 3초 무음 + 이후 톤 -> 발화 시작이 약 3초로 잡혀야 한다."""
    import subprocess

    from lecture_scribe.audio import find_binary, first_speech_offset

    path = tmp_path / "무음후톤.m4a"
    ffmpeg = find_binary("ffmpeg")
    subprocess.run(
        [
            str(ffmpeg), "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "3",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "3",
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1",
            "-c:a", "aac", str(path),
        ],
        check=True,
        capture_output=True,
    )
    offset = first_speech_offset(path)
    assert 2.5 <= offset <= 3.6, f"발화 시작 {offset}"


def test_first_speech_offset_no_leading_silence(tmp_path: Path) -> None:
    import subprocess

    from lecture_scribe.audio import find_binary, first_speech_offset

    path = tmp_path / "즉시톤.m4a"
    ffmpeg = find_binary("ffmpeg")
    subprocess.run(
        [
            str(ffmpeg), "-nostdin", "-v", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000", "-t", "3",
            "-c:a", "aac", str(path),
        ],
        check=True,
        capture_output=True,
    )
    assert first_speech_offset(path) == 0.0
