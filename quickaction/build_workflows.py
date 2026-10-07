#!/usr/bin/env python3
"""Automator Quick Action(.workflow) 번들 생성기.

Finder 우클릭 → 빠른 동작에 노출되는 서비스 2종을 만든다.

- 입력은 **한 번의 호출로 모든 경로가 인자로 전달**되어야 한다
  (파일마다 프로세스가 뜨면 안 됨) → `inputMethod = 1` ("as arguments").
- 셸은 `/bin/zsh`, 실행 파일은 전부 절대 경로. Finder 컨텍스트에는
  Homebrew PATH가 없다.
- 절대 경로는 설치 시점에 `install.sh`가 치환한다(`__LECTURE_SCRIBE_BIN__` 등).
"""

from __future__ import annotations

import plistlib
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

TRANSCRIBE_SCRIPT = r"""#!/bin/zsh
# LectureScribe Quick Action — 즉시 전사
# 경로에 공백·한글·따옴표가 있어도 안전하도록 "$@" 인용을 지킨다.
set -u

BIN="__LECTURE_SCRIBE_BIN__"
FFMPEG_DIR="__FFMPEG_DIR__"

export LECTURE_SCRIBE_FFMPEG_DIR="$FFMPEG_DIR"
export PATH="$FFMPEG_DIR:/usr/bin:/bin:/usr/sbin:/sbin"

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"LectureScribe\"" >/dev/null 2>&1
}

if [[ ! -x "$BIN" ]]; then
  notify "실행 파일을 찾을 수 없습니다. quickaction/install.sh를 다시 실행하세요."
  exit 1
fi

if (( $# == 0 )); then
  notify "선택된 파일이 없습니다."
  exit 1
fi

# zsh에서 `status`는 $?의 별칭인 읽기 전용 변수다. 절대 대입하지 말 것.
"$BIN" --notify --quiet "$@"
rc=$?

case $rc in
  0) ;;
  1) notify "일부 파일 전사에 실패했습니다. 로그를 확인하세요." ;;
  2) notify "전사에 실패했습니다. 파일 접근 권한(시스템 설정 > 개인정보 보호 및 보안 > 파일 및 폴더)을 확인하세요." ;;
  130) notify "취소되었습니다." ;;
  *) notify "알 수 없는 오류(코드 $rc). 로그: ~/Library/Logs/LectureScribe/" ;;
esac

exit $rc
"""

OPEN_GUI_SCRIPT = r"""#!/bin/zsh
# LectureScribe Quick Action — 앱에서 열기(주제를 그때그때 바꿔 넣고 싶을 때)
set -u

BIN="__LECTURE_SCRIBE_BIN__"
FFMPEG_DIR="__FFMPEG_DIR__"

export LECTURE_SCRIBE_FFMPEG_DIR="$FFMPEG_DIR"
export PATH="$FFMPEG_DIR:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ ! -x "$BIN" ]]; then
  /usr/bin/osascript -e 'display notification "실행 파일을 찾을 수 없습니다. install.sh를 다시 실행하세요." with title "LectureScribe"' >/dev/null 2>&1
  exit 1
fi

# GUI는 백그라운드로 띄우고 Quick Action은 즉시 반환한다.
"$BIN" --open-gui "$@" >/dev/null 2>&1 &
exit 0
"""


def build_action(script: str, uuid_suffix: str) -> dict[str, object]:
    """Run Shell Script 액션 1개."""
    return {
        "action": {
            "AMAccepts": {
                "Container": "List",
                "Optional": True,
                "Types": ["com.apple.cocoa.string"],
            },
            "AMActionVersion": "2.0.3",
            "AMApplication": ["Automator"],
            "AMParameterProperties": {
                "COMMAND_STRING": {},
                "CheckedForUserDefaultShell": {},
                "inputMethod": {},
                "shell": {},
                "source": {},
            },
            "AMProvides": {
                "Container": "List",
                "Types": ["com.apple.cocoa.string"],
            },
            "ActionBundlePath": (
                "/System/Library/Automator/Run Shell Script.action"
            ),
            "ActionName": "셸 스크립트 실행",
            "ActionParameters": {
                "COMMAND_STRING": script,
                "CheckedForUserDefaultShell": True,
                # 1 = 입력을 인자로 전달(as arguments). 0이면 stdin으로 들어가
                # 다중 파일이 한 번에 넘어오지 않는다.
                "inputMethod": 1,
                "shell": "/bin/zsh",
                "source": "",
            },
            "BundleIdentifier": "com.apple.RunShellScript",
            "CFBundleVersion": "2.0.3",
            "CanShowSelectedItemsWhenRun": False,
            "CanShowWhenRun": True,
            "Category": ["AMCategoryUtilities"],
            "Class Name": "RunShellScriptAction",
            "InputUUID": f"A0000000-0000-0000-0000-0000000000{uuid_suffix}",
            "Keywords": ["Shell", "Script", "Command", "Run", "Unix"],
            "OutputUUID": f"B0000000-0000-0000-0000-0000000000{uuid_suffix}",
            "UUID": f"C0000000-0000-0000-0000-0000000000{uuid_suffix}",
            "UnlocalizedApplications": ["Automator"],
            "arguments": {
                "0": {
                    "default value": 0,
                    "name": "inputMethod",
                    "required": "0",
                    "type": "0",
                    "uuid": "0",
                },
                "1": {
                    "default value": False,
                    "name": "CheckedForUserDefaultShell",
                    "required": "0",
                    "type": "0",
                    "uuid": "1",
                },
                "2": {
                    "default value": "",
                    "name": "source",
                    "required": "0",
                    "type": "0",
                    "uuid": "2",
                },
                "3": {
                    "default value": "",
                    "name": "COMMAND_STRING",
                    "required": "0",
                    "type": "0",
                    "uuid": "3",
                },
                "4": {
                    "default value": "/bin/sh",
                    "name": "shell",
                    "required": "0",
                    "type": "0",
                    "uuid": "4",
                },
            },
            "isViewVisible": 1,
            "location": "309.000000:253.000000",
            "nibPath": (
                "/System/Library/Automator/Run Shell Script.action"
                "/Contents/Resources/Base.lproj/main.nib"
            ),
        },
        "isViewVisible": 1,
    }


def build_document(script: str, uuid_suffix: str) -> dict[str, object]:
    return {
        "AMApplicationBuild": "521",
        "AMApplicationVersion": "2.10",
        "AMDocumentVersion": "2",
        "actions": [build_action(script, uuid_suffix)],
        "connectors": {},
        "workflowMetaData": {
            "applicationBundleIDsByPath": {},
            "applicationPaths": [],
            "inputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "outputTypeIdentifier": "com.apple.Automator.nothing",
            "presentationMode": 11,  # Quick Action
            "processesInput": 0,
            "serviceApplicationBundleID": "com.apple.finder",
            "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
            "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
            "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
            "serviceProcessesInput": 0,
            "systemImageName": "NSTouchBarAudioInputTemplate",
            "useAutomaticInputType": 0,
            "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
        },
    }


def build_info(menu_title: str) -> dict[str, object]:
    return {
        "NSServices": [
            {
                "NSMenuItem": {"default": menu_title},
                "NSMessage": "runWorkflowAsService",
                "NSRequiredContext": {"NSApplicationIdentifier": "com.apple.finder"},
                "NSSendFileTypes": ["public.item"],
            }
        ],
    }


def write_workflow(directory: Path, menu_title: str, script: str, uuid_suffix: str) -> None:
    if directory.exists():
        shutil.rmtree(directory)
    contents = directory / "Contents"
    contents.mkdir(parents=True)
    with (contents / "document.wflow").open("wb") as handle:
        plistlib.dump(build_document(script, uuid_suffix), handle)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(build_info(menu_title), handle)


def main() -> int:
    write_workflow(
        HERE / "Transcribe.workflow",
        "LectureScribe로 전사",
        TRANSCRIBE_SCRIPT,
        "01",
    )
    write_workflow(
        HERE / "TranscribeOpenApp.workflow",
        "LectureScribe에서 열기",
        OPEN_GUI_SCRIPT,
        "02",
    )
    print("생성 완료:")
    for name in ("Transcribe.workflow", "TranscribeOpenApp.workflow"):
        print(f"  {HERE / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
