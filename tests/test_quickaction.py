"""Quick Action 워크플로 검증.

Finder 컨텍스트에서 실패하기 쉬운 부분만 본다:
절대 경로, 인용, 다중 파일 단일 호출, zsh 문법.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
QUICKACTION = PROJECT / "quickaction"
WORKFLOWS = ("Transcribe.workflow", "TranscribeOpenApp.workflow")


def load_action(workflow: Path) -> dict[str, object]:
    with (workflow / "Contents" / "document.wflow").open("rb") as handle:
        document = plistlib.load(handle)
    actions = document["actions"]
    assert len(actions) == 1, "액션이 하나여야 다중 파일이 한 번에 전달된다"
    params: dict[str, object] = actions[0]["action"]["ActionParameters"]
    return params


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_bundle_is_valid(name: str) -> None:
    workflow = QUICKACTION / name
    assert (workflow / "Contents" / "document.wflow").is_file()
    assert (workflow / "Contents" / "Info.plist").is_file()
    result = subprocess.run(
        ["/usr/bin/plutil", "-lint", str(workflow / "Contents" / "document.wflow")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_passes_input_as_arguments(name: str) -> None:
    """inputMethod=1이어야 다중 파일 선택 시 한 번의 호출로 모든 경로가 넘어온다."""
    params = load_action(QUICKACTION / name)
    assert params["inputMethod"] == 1
    assert params["shell"] == "/bin/zsh"


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_script_quotes_arguments(name: str) -> None:
    """공백·한글·따옴표가 든 경로를 위해 "$@" 인용을 지켜야 한다."""
    script = str(load_action(QUICKACTION / name)["COMMAND_STRING"])
    assert '"$@"' in script
    assert "$*" not in script


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_script_is_valid_zsh(name: str, tmp_path: Path) -> None:
    script = str(load_action(QUICKACTION / name)["COMMAND_STRING"])
    path = tmp_path / "action.zsh"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        ["/bin/zsh", "-n", str(path)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_script_does_not_assign_readonly_status(name: str) -> None:
    """zsh에서 `status`는 $?의 별칭인 읽기 전용 변수다(실측 회귀 테스트)."""
    script = str(load_action(QUICKACTION / name)["COMMAND_STRING"])
    assert "status=$?" not in script


@pytest.mark.parametrize("name", WORKFLOWS)
def test_workflow_uses_absolute_paths(name: str) -> None:
    """Finder 컨텍스트에는 Homebrew PATH가 없다. 상대 명령 호출 금지."""
    script = str(load_action(QUICKACTION / name)["COMMAND_STRING"])
    assert "/usr/bin/osascript" in script
    # 치환 전 템플릿에는 플레이스홀더가, 설치본에는 절대 경로가 들어간다
    assert "__LECTURE_SCRIBE_BIN__" in script or script.count('BIN="/') == 1
    assert "export PATH=" in script


def test_install_script_exists_and_is_executable() -> None:
    for name in ("install.sh", "uninstall.sh"):
        path = QUICKACTION / name
        assert path.is_file()
        assert path.stat().st_mode & 0o111, f"{name} 실행 권한 없음"


def test_install_script_is_valid_zsh() -> None:
    for name in ("install.sh", "uninstall.sh"):
        result = subprocess.run(
            ["/bin/zsh", "-n", str(QUICKACTION / name)], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr


def test_info_plist_declares_finder_service() -> None:
    for name in WORKFLOWS:
        with (QUICKACTION / name / "Contents" / "Info.plist").open("rb") as handle:
            info = plistlib.load(handle)
        service = info["NSServices"][0]
        assert service["NSMessage"] == "runWorkflowAsService"
        assert "LectureScribe" in service["NSMenuItem"]["default"]
        assert service["NSSendFileTypes"] == ["public.item"]
