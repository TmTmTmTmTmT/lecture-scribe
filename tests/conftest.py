"""테스트 공통 픽스처."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from lecture_scribe.backends.base import Segment


@pytest.fixture(autouse=True)
def isolated_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """모든 테스트를 임시 HOME으로 격리한다.

    기본 설정의 `cowork.workspace_dir`/`index_path`/로그/설정 파일이 전부
    `~` 아래를 가리키므로, 격리하지 않으면 테스트가 **사용자의 실제 전사 폴더와
    인덱스를 오염시킨다**(실제로 발생했던 문제).
    """
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("LECTURE_SCRIBE_SETTINGS", raising=False)
    return home


def make_segment(
    seg_id: int,
    start: float,
    end: float,
    text: str,
    avg_logprob: float = -0.3,
) -> Segment:
    return Segment(
        id=seg_id,
        start=start,
        end=end,
        text=text,
        avg_logprob=avg_logprob,
        no_speech_prob=0.01,
        compression_ratio=1.5,
        temperature=0.0,
    )


@pytest.fixture
def segments() -> list[Segment]:
    """무음 간격이 있는 4개 세그먼트(2문단 분리 예상)."""
    return [
        make_segment(0, 0.0, 2.0, " 임피던스 정합을 설명합니다."),
        make_segment(1, 2.0, 4.0, " 반사계수는 감마로 표기합니다."),
        make_segment(2, 10.0, 12.0, " 스미스 차트를 보겠습니다."),
        make_segment(3, 12.0, 14.0, " S-parameter도 함께 다룹니다."),
    ]


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    """실제 오디오가 아닌 경로용 더미(쓰기 테스트 전용)."""
    path = tmp_path / "강의 01.m4a"
    path.write_bytes(b"\x00" * 16)
    return path
