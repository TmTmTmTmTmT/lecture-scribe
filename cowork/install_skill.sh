#!/bin/zsh
# Cowork / Claude Code 스킬 설치
#
# 스킬 디렉터리 경로를 추정해서 하드코딩하지 않는다(§10.5).
# 존재하는 후보를 실행 시점에 탐색하고, 못 찾으면 경로를 출력하고 수동 배치를 안내한다.
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
PROJECT_DIR="${SCRIPT_DIR:h}"
SKILL_SRC="$SCRIPT_DIR/skills/lecture-transcribe"

[[ -d "$SKILL_SRC" ]] || { print -r -- "오류: 스킬 폴더가 없습니다: $SKILL_SRC" >&2; exit 1 }

# --- 실행 파일 절대 경로를 SKILL.md에 반영 -----------------------------
BIN=""
for candidate in "$PROJECT_DIR/.venv/bin/lecture-scribe" "$HOME/.local/bin/lecture-scribe"; do
  [[ -x "$candidate" ]] && { BIN="$candidate"; break }
done
[[ -n "$BIN" ]] || BIN="$(command -v lecture-scribe 2>/dev/null || true)"
[[ -n "$BIN" ]] || { print -r -- "오류: lecture-scribe 실행 파일을 찾을 수 없습니다. 'uv sync'를 먼저 실행하세요." >&2; exit 1 }

# --- 스킬 디렉터리 후보 탐색 -------------------------------------------
typeset -a CANDIDATES
CANDIDATES=(
  "$HOME/.claude/skills"
  "$HOME/Library/Application Support/Claude/skills"
  "$HOME/.config/claude/skills"
)
TARGET_ROOT=""
for dir in $CANDIDATES; do
  if [[ -d "$dir" ]]; then TARGET_ROOT="$dir"; break; fi
done

if [[ -z "$TARGET_ROOT" ]]; then
  print -r -- "스킬 디렉터리를 찾지 못했습니다. 아래 중 실제 경로에 직접 복사하세요:"
  for dir in $CANDIDATES; do print -r -- "  $dir/lecture-transcribe/"; done
  print -r -- ""
  print -r -- "복사할 원본: $SKILL_SRC"
  print -r -- "복사 후 SKILL.md 안의 실행 경로가 아래와 맞는지 확인하세요:"
  print -r -- "  $BIN"
  exit 2
fi

TARGET="$TARGET_ROOT/lecture-transcribe"
mkdir -p "$TARGET"
cp -R "$SKILL_SRC/." "$TARGET/"

/usr/bin/python3 - "$TARGET/SKILL.md" "$BIN" <<'PYEOF'
import re, sys
path, binary = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()
text = text.replace("__LECTURE_SCRIBE_BIN__", binary)
# 이전 설치본의 경로도 현재 경로로 갱신
text = re.sub(r"/[^\s`\"]*/\.venv/bin/lecture-scribe", binary, text)
open(path, "w", encoding="utf-8").write(text)
PYEOF

print -r -- "스킬 설치 완료: $TARGET"
print -r -- "  실행 경로: $BIN"
print -r -- ""
print -r -- "Cowork/Claude Code 세션에서 이렇게 요청할 수 있습니다:"
print -r -- "  \"이 녹음 전사해서 절 단위로 요약해줘\" (파일 첨부 또는 경로 지정)"
