#!/bin/zsh
# LectureScribe Finder Quick Action 설치 (배포 번들용)
set -euo pipefail

APP="/Applications/LectureScribe.app"
BIN="$APP/Contents/MacOS/LectureScribe"
SERVICES="$HOME/Library/Services"

print -r -- "LectureScribe Quick Action 설치"

if [[ ! -x "$BIN" ]]; then
  print -r -- "오류: /Applications/LectureScribe.app 이 없습니다." >&2
  print -r -- "      먼저 앱을 Applications 폴더로 옮긴 뒤 다시 실행하세요." >&2
  read -k1 "?계속하려면 아무 키나 누르세요..."
  exit 1
fi

FFMPEG_DIR=""
for d in /opt/homebrew/bin /usr/local/bin /opt/local/bin /usr/bin; do
  [[ -x "$d/ffprobe" ]] && { FFMPEG_DIR="$d"; break }
done
if [[ -z "$FFMPEG_DIR" ]]; then
  print -r -- "오류: ffmpeg/ffprobe를 찾을 수 없습니다. 'brew install ffmpeg' 후 다시 실행하세요." >&2
  read -k1 "?계속하려면 아무 키나 누르세요..."
  exit 1
fi

mkdir -p "$SERVICES"

make_workflow() {
  local name="$1" menu="$2" cli_args="$3"
  local dir="$SERVICES/$name.workflow/Contents"
  rm -rf "$SERVICES/$name.workflow"
  mkdir -p "$dir"

  /usr/bin/python3 - "$dir" "$menu" "$BIN" "$FFMPEG_DIR" "$cli_args" <<'PYEOF'
import plistlib, sys
directory, menu, binary, ffmpeg_dir, cli_args = sys.argv[1:6]

script = f'''#!/bin/zsh
# zsh에서 status는 읽기 전용 변수다. rc를 쓴다.
set -u
BIN="{binary}"
export LECTURE_SCRIBE_FFMPEG_DIR="{ffmpeg_dir}"
export PATH="{ffmpeg_dir}:/usr/bin:/bin:/usr/sbin:/sbin"

notify() {{ /usr/bin/osascript -e "display notification \\"$1\\" with title \\"LectureScribe\\"" >/dev/null 2>&1 }}

if [[ ! -x "$BIN" ]]; then
  notify "LectureScribe.app을 찾을 수 없습니다."
  exit 1
fi
if (( $# == 0 )); then
  notify "선택된 파일이 없습니다."
  exit 1
fi

{cli_args}
'''

action = {{
    "action": {{
        "AMAccepts": {{"Container": "List", "Optional": True,
                       "Types": ["com.apple.cocoa.string"]}},
        "AMActionVersion": "2.0.3",
        "AMApplication": ["Automator"],
        "AMParameterProperties": {{"COMMAND_STRING": {{}}, "CheckedForUserDefaultShell": {{}},
                                   "inputMethod": {{}}, "shell": {{}}, "source": {{}}}},
        "AMProvides": {{"Container": "List", "Types": ["com.apple.cocoa.string"]}},
        "ActionBundlePath": "/System/Library/Automator/Run Shell Script.action",
        "ActionName": "셸 스크립트 실행",
        "ActionParameters": {{"COMMAND_STRING": script, "CheckedForUserDefaultShell": True,
                              "inputMethod": 1, "shell": "/bin/zsh", "source": ""}},
        "BundleIdentifier": "com.apple.RunShellScript",
        "CFBundleVersion": "2.0.3",
        "CanShowSelectedItemsWhenRun": False,
        "CanShowWhenRun": True,
        "Category": ["AMCategoryUtilities"],
        "Class Name": "RunShellScriptAction",
        "InputUUID": "A0000000-0000-0000-0000-000000000011",
        "OutputUUID": "B0000000-0000-0000-0000-000000000011",
        "UUID": "C0000000-0000-0000-0000-000000000011",
        "UnlocalizedApplications": ["Automator"],
        "isViewVisible": 1,
        "location": "309.000000:253.000000",
    }},
    "isViewVisible": 1,
}}
doc = {{
    "AMApplicationBuild": "521", "AMApplicationVersion": "2.10", "AMDocumentVersion": "2",
    "actions": [action], "connectors": {{}},
    "workflowMetaData": {{
        "serviceInputTypeIdentifier": "com.apple.Automator.fileSystemObject",
        "serviceOutputTypeIdentifier": "com.apple.Automator.nothing",
        "serviceApplicationBundleID": "com.apple.finder",
        "serviceApplicationPath": "/System/Library/CoreServices/Finder.app",
        "serviceProcessesInput": 0, "presentationMode": 11, "processesInput": 0,
        "useAutomaticInputType": 0,
        "workflowTypeIdentifier": "com.apple.Automator.servicesMenu",
    }},
}}
info = {{"NSServices": [{{"NSMenuItem": {{"default": menu}},
                          "NSMessage": "runWorkflowAsService",
                          "NSRequiredContext": {{"NSApplicationIdentifier": "com.apple.finder"}},
                          "NSSendFileTypes": ["public.item"]}}]}}
with open(f"{{directory}}/document.wflow", "wb") as h: plistlib.dump(doc, h)
with open(f"{{directory}}/Info.plist", "wb") as h: plistlib.dump(info, h)
PYEOF
  print -r -- "  설치: $SERVICES/$name.workflow"
}

make_workflow "LectureScribe 전사" "LectureScribe로 전사" \
  '"$BIN" --cli --notify --quiet "$@"
rc=$?
case $rc in
  0) ;;
  1) notify "일부 파일 전사 실패. 로그를 확인하세요." ;;
  2) notify "전사 실패. 파일 접근 권한을 확인하세요." ;;
  130) notify "취소되었습니다." ;;
esac
exit $rc'

make_workflow "LectureScribe 열기" "LectureScribe에서 열기" \
  '/usr/bin/open -a "/Applications/LectureScribe.app" "$@"
exit 0'

/usr/bin/pkill -HUP Finder 2>/dev/null || true
/System/Library/CoreServices/pbs -update 2>/dev/null || true

print -r -- ""
print -r -- "완료. Finder에서 오디오 파일 우클릭 → 빠른 동작에서 확인하세요."
print -r -- "보이지 않으면 시스템 설정 > 키보드 > 키보드 단축키 > 서비스 에서 켜세요."
print -r -- ""
read -k1 "?창을 닫으려면 아무 키나 누르세요..."
