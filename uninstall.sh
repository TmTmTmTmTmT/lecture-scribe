#!/bin/zsh
# LectureScribe 제거 (설정·전사 결과는 지우지 않는다)
set -euo pipefail
PROJECT_DIR="${0:A:h}"

print -r -- "LectureScribe 제거"

"$PROJECT_DIR/quickaction/uninstall.sh"

for target in "$HOME/.claude/skills/lecture-transcribe" \
              "$HOME/Library/Application Support/Claude/skills/lecture-transcribe"; do
  if [[ -d "$target" ]]; then rm -rf "$target"; print -r -- "  제거: $target"; fi
done

if [[ -d "/Applications/LectureScribe.app" ]]; then
  rm -rf "/Applications/LectureScribe.app"
  print -r -- "  제거: /Applications/LectureScribe.app"
fi
if [[ -d "$PROJECT_DIR/dist/LectureScribe.app" ]]; then
  rm -rf "$PROJECT_DIR/dist/LectureScribe.app"
  print -r -- "  제거: $PROJECT_DIR/dist/LectureScribe.app"
fi

print -r -- ""
print -r -- "다음은 그대로 둡니다(원하면 직접 지우세요):"
print -r -- "  설정   : ~/Library/Application Support/LectureScribe/"
print -r -- "  로그   : ~/Library/Logs/LectureScribe/"
print -r -- "  전사물 : ~/Documents/LectureScribe/"
print -r -- "  모델   : ~/.cache/huggingface/hub/"
print -r -- "  가상환경: $PROJECT_DIR/.venv  (rm -rf 로 제거)"
