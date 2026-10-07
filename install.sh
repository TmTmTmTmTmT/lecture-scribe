#!/bin/zsh
# LectureScribe 전체 설치
#   1) 의존성  2) .app 번들  3) Finder Quick Action  4) Claude 스킬
set -euo pipefail

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"

step() { print -r -- ""; print -r -- "▸ $1" }
fail() { print -r -- "오류: $1" >&2; exit 1 }

print -r -- "LectureScribe 설치 — $PROJECT_DIR"

# --- 0) 사전 확인 -------------------------------------------------------
command -v uv >/dev/null 2>&1 || fail "uv가 없습니다. https://astral.sh/uv 설치 후 다시 실행하세요."

FFMPEG_OK=0
for d in /opt/homebrew/bin /usr/local/bin /opt/local/bin /usr/bin; do
  [[ -x "$d/ffprobe" && -x "$d/ffmpeg" ]] && { FFMPEG_OK=1; break }
done
(( FFMPEG_OK )) || fail "ffmpeg/ffprobe가 없습니다. 'brew install ffmpeg' 후 다시 실행하세요."

# --- 1) 의존성 ----------------------------------------------------------
step "의존성 설치 (uv sync)"
EXTRAS=()
[[ "${LECTURE_SCRIBE_WITH_MLX:-0}" == "1" ]] && EXTRAS+=(--extra mlx)
# ocr: 영상의 슬라이드 글자 인식(macOS Vision). 없어도 앱은 동작하고 OCR만 건너뛴다.
uv sync --extra fuzzy --extra ocr $EXTRAS
print -r -- "  완료: $PROJECT_DIR/.venv"

# --- 2) 앱 번들 ---------------------------------------------------------
step "LectureScribe.app 생성"
uv run python packaging/make_app.py

# --- 3) Quick Action ----------------------------------------------------
step "Finder Quick Action 설치"
uv run python quickaction/build_workflows.py >/dev/null
./quickaction/install.sh

# --- 4) Claude 스킬 -----------------------------------------------------
step "Claude 스킬 설치"
./cowork/install_skill.sh || print -r -- "  (스킬 설치는 건너뜁니다 — 위 안내 참조)"

# --- 마무리 -------------------------------------------------------------
print -r -- ""
print -r -- "설치 완료."
print -r -- "  앱      : open '$PROJECT_DIR/dist/LectureScribe.app'"
print -r -- "  CLI     : $PROJECT_DIR/.venv/bin/lecture-scribe --help"
print -r -- "  Finder  : 오디오 파일 우클릭 → 빠른 동작"
print -r -- ""
print -r -- "앱을 Launchpad에 두려면:"
print -r -- "  cp -R '$PROJECT_DIR/dist/LectureScribe.app' /Applications/"
print -r -- ""
print -r -- "문제가 생기면 TROUBLESHOOTING.md 를 보세요."
