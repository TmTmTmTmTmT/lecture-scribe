#!/bin/zsh
# LectureScribe Quick Action 제거
set -euo pipefail
SERVICES_DIR="$HOME/Library/Services"
removed=0
for name in Transcribe.workflow TranscribeOpenApp.workflow; do
  if [[ -d "$SERVICES_DIR/$name" ]]; then
    rm -rf "$SERVICES_DIR/$name"
    print -r -- "  제거: $SERVICES_DIR/$name"
    removed=1
  fi
done
/usr/bin/pkill -HUP Finder 2>/dev/null || true
/System/Library/CoreServices/pbs -update 2>/dev/null || true
if (( removed )); then
  print -r -- "제거 완료."
else
  print -r -- "설치된 Quick Action이 없습니다."
fi
