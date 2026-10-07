#!/bin/zsh
# LectureScribe Quick Action 설치
#
# - 워크플로를 ~/Library/Services 에 설치한다.
# - Finder에서 실행되는 컨텍스트에는 Homebrew PATH가 없으므로
#   실행 파일·ffmpeg 경로를 **절대 경로로 치환**해 넣는다.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
SERVICES_DIR="$HOME/Library/Services"

info()  { print -r -- "  $1" }
fail()  { print -r -- "오류: $1" >&2; exit 1 }

print -r -- "LectureScribe Quick Action 설치"
print -r -- "프로젝트: $PROJECT_DIR"

# --- 1) 실행 파일 절대 경로 찾기 ---------------------------------------
BIN=""
for candidate in \
  "$PROJECT_DIR/.venv/bin/lecture-scribe" \
  "$HOME/.local/bin/lecture-scribe" \
  "/opt/homebrew/bin/lecture-scribe"
do
  if [[ -x "$candidate" ]]; then BIN="$candidate"; break; fi
done
if [[ -z "$BIN" ]]; then
  BIN="$(command -v lecture-scribe 2>/dev/null || true)"
fi
[[ -n "$BIN" && -x "$BIN" ]] || fail "lecture-scribe 실행 파일을 찾을 수 없습니다. 먼저 'uv sync'를 실행하세요."
info "실행 파일: $BIN"

# --- 2) ffmpeg 디렉터리 찾기 -------------------------------------------
FFMPEG_DIR=""
for candidate in /opt/homebrew/bin /usr/local/bin /opt/local/bin /usr/bin; do
  if [[ -x "$candidate/ffprobe" && -x "$candidate/ffmpeg" ]]; then
    FFMPEG_DIR="$candidate"; break
  fi
done
[[ -n "$FFMPEG_DIR" ]] || fail "ffmpeg/ffprobe를 찾을 수 없습니다. 'brew install ffmpeg' 후 다시 실행하세요."
info "ffmpeg: $FFMPEG_DIR"

# --- 3) 설치 -----------------------------------------------------------
mkdir -p "$SERVICES_DIR"

install_workflow() {
  local name="$1"
  local src="$SCRIPT_DIR/$name"
  local dst="$SERVICES_DIR/$name"
  [[ -d "$src" ]] || fail "워크플로가 없습니다: $src (python3 build_workflows.py 를 먼저 실행하세요)"
  rm -rf "$dst"
  cp -R "$src" "$dst"

  # 절대 경로 치환 (plist 안의 스크립트 문자열)
  /usr/bin/python3 - "$dst/Contents/document.wflow" "$BIN" "$FFMPEG_DIR" <<'PYEOF'
import plistlib, sys
path, binary, ffmpeg_dir = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "rb") as handle:
    doc = plistlib.load(handle)
for entry in doc["actions"]:
    params = entry["action"]["ActionParameters"]
    script = params["COMMAND_STRING"]
    script = script.replace("__LECTURE_SCRIBE_BIN__", binary)
    script = script.replace("__FFMPEG_DIR__", ffmpeg_dir)
    params["COMMAND_STRING"] = script
with open(path, "wb") as handle:
    plistlib.dump(doc, handle)
PYEOF

  info "설치: $dst"
}

install_workflow "Transcribe.workflow"
install_workflow "TranscribeOpenApp.workflow"

# --- 4) 서비스 메뉴 갱신 ------------------------------------------------
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister \
  -f "$SERVICES_DIR/Transcribe.workflow" "$SERVICES_DIR/TranscribeOpenApp.workflow" 2>/dev/null || true
/usr/bin/pkill -HUP Finder 2>/dev/null || true
/System/Library/CoreServices/pbs -update 2>/dev/null || true

print -r -- ""
print -r -- "설치 완료. Finder에서 오디오 파일을 우클릭 → 빠른 동작(Quick Actions):"
print -r -- "  · LectureScribo로 전사        (저장된 설정으로 즉시 전사)" | sed 's/LectureScribo/LectureScribe/'
print -r -- "  · LectureScribe에서 열기      (앱을 띄우고 큐에 적재)"
print -r -- ""
print -r -- "메뉴에 보이지 않으면 시스템 설정 > 키보드 > 키보드 단축키 > 서비스에서"
print -r -- "'LectureScribe' 항목을 켜세요."
print -r -- "첫 실행 시 파일 접근 권한을 물으면 허용해야 합니다"
print -r -- "(거부했다면 시스템 설정 > 개인정보 보호 및 보안 > 파일 및 폴더)."
