"""시작 시 의존성 점검(`gui/dependency_check.py`) 테스트.

실제 시스템 상태에 의존하지 않도록 전부 monkeypatch로 격리한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lecture_scribe.errors import FFmpegNotFoundError
from lecture_scribe.gui import dependency_check as dc


def _patch_ffmpeg_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dc.audio, "find_binary", lambda name: Path(f"/opt/homebrew/bin/{name}"))


def test_all_ready_reports_no_problem(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ffmpeg_ok(monkeypatch)
    monkeypatch.setattr(dc, "find_ollama", lambda: Path("/opt/homebrew/bin/ollama"))

    class _Client:
        def alive(self, timeout: float = 1.5) -> bool:
            return True

        def models(self) -> list[str]:
            return ["gemma4:e4b:latest", "gemma4:e2b:latest"]

    monkeypatch.setattr(dc, "OllamaClient", _Client)

    items = dc.check_dependencies()
    assert dc.has_any_problem(items) is False
    assert all(item.ok for item in items)


def test_ffmpeg_missing_offers_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(name: str) -> Path:
        raise FFmpegNotFoundError("없음", "테스트")

    monkeypatch.setattr(dc.audio, "find_binary", _boom)
    monkeypatch.setattr(dc, "find_ollama", lambda: None)

    items = dc.check_dependencies()
    assert dc.has_any_problem(items) is True
    ffmpeg_item = next(i for i in items if i.key == "ffmpeg")
    assert ffmpeg_item.ok is False
    assert ffmpeg_item.action == "show_command"
    assert "brew install ffmpeg" in ffmpeg_item.command


def test_ollama_missing_skips_daemon_and_model_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ffmpeg_ok(monkeypatch)
    monkeypatch.setattr(dc, "find_ollama", lambda: None)

    items = dc.check_dependencies()
    keys = [i.key for i in items]
    assert "ollama" in keys
    ollama_item = next(i for i in items if i.key == "ollama")
    assert ollama_item.ok is False
    assert ollama_item.action == "show_command"
    assert "ollama_daemon" not in keys  # 실행 파일이 없으면 데몬 점검 자체를 안 한다
    assert not any(k.startswith("model:") for k in keys)


def test_daemon_down_marks_models_unknown_but_not_pullable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_ffmpeg_ok(monkeypatch)
    monkeypatch.setattr(dc, "find_ollama", lambda: Path("/opt/homebrew/bin/ollama"))

    class _Client:
        def alive(self, timeout: float = 1.5) -> bool:
            return False

    monkeypatch.setattr(dc, "OllamaClient", _Client)

    items = dc.check_dependencies()
    daemon_item = next(i for i in items if i.key == "ollama_daemon")
    assert daemon_item.ok is False
    assert daemon_item.action == "start_ollama"
    model_items = [i for i in items if i.key.startswith("model:")]
    assert len(model_items) == len(dc.CORRECTION_MODELS)
    assert all(i.action is None for i in model_items)  # 데몬 꺼져 있으면 받기 버튼 안 줌


def test_missing_model_offers_pull_action(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ffmpeg_ok(monkeypatch)
    monkeypatch.setattr(dc, "find_ollama", lambda: Path("/opt/homebrew/bin/ollama"))

    class _Client:
        def alive(self, timeout: float = 1.5) -> bool:
            return True

        def models(self) -> list[str]:
            return []  # 아무 것도 안 받음

    monkeypatch.setattr(dc, "OllamaClient", _Client)

    items = dc.check_dependencies()
    model_items = [i for i in items if i.key.startswith("model:")]
    assert len(model_items) == len(dc.CORRECTION_MODELS)
    for item in model_items:
        assert item.ok is False
        assert item.action == "pull_model"
        assert item.model in dc.CORRECTION_MODELS


def test_model_name_variant_with_tag_still_counts_as_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`gemma4:e4b`와 `gemma4:e4b:latest`처럼 태그 표기가 달라도 있다고 본다."""
    _patch_ffmpeg_ok(monkeypatch)
    monkeypatch.setattr(dc, "find_ollama", lambda: Path("/opt/homebrew/bin/ollama"))

    class _Client:
        def alive(self, timeout: float = 1.5) -> bool:
            return True

        def models(self) -> list[str]:
            return ["gemma4:e4b:latest"]  # e2b는 없음

    monkeypatch.setattr(dc, "OllamaClient", _Client)

    items = dc.check_dependencies()
    e4b = next(i for i in items if i.key == "model:gemma4:e4b")
    e2b = next(i for i in items if i.key == "model:gemma4:e2b")
    assert e4b.ok is True
    assert e2b.ok is False
