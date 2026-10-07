#!/bin/zsh
# 배포용 DMG 빌드 — 다른 Mac에 그대로 복사해도 동작하는 자립 번들.
#
#   ./packaging/build_dmg.sh [출력경로]        기본: ~/Desktop/LectureScribe-<버전>.dmg
#
# 개발용 경량 앱(`packaging/make_app.py`)과 다르다. 그쪽은 프로젝트 venv를 참조하므로
# 이 기기에서만 동작한다. 배포에는 반드시 이 스크립트를 쓴다.
set -euo pipefail

HERE="${0:A:h}"
PROJECT="${HERE:h}"
VERSION=$(grep -m1 '^version' "$PROJECT/pyproject.toml" | sed 's/.*"\(.*\)".*/\1/')
DMG="${1:-$HOME/Desktop/LectureScribe-$VERSION.dmg}"
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

cd "$PROJECT"

print -r -- "▸ 배포용 의존성 동기화 (torch 제외 — mlx는 torch 없이 동작한다)"
uv sync --extra fuzzy --extra mlx --extra ocr --group build

print -r -- "▸ 아이콘 생성"
uv run python -c "
import sys; sys.path.insert(0, 'packaging')
from pathlib import Path
import shutil, make_app
icns = make_app.make_icns(Path('packaging/_iconwork'))
if icns: shutil.copy2(icns, 'packaging/AppIcon.icns')
"

print -r -- "▸ PyInstaller 번들 빌드"
cd packaging
rm -rf build dist
uv run pyinstaller LectureScribe.spec --noconfirm --distpath dist --workpath build >/dev/null
codesign --force --deep --sign - dist/LectureScribe.app

print -r -- "▸ DMG 구성"
cp -R dist/LectureScribe.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "$HERE/dmg-readme.txt" "$STAGE/먼저 읽어주세요.txt"
mkdir -p "$STAGE/추가 도구"
cp "$HERE/dmg-quickaction.command" "$STAGE/추가 도구/Quick Action 설치.command"
chmod +x "$STAGE/추가 도구/Quick Action 설치.command"

rm -f "$DMG"
hdiutil create -volname "LectureScribe" -srcfolder "$STAGE" -ov -format UDZO -fs HFS+ "$DMG" >/dev/null

print -r -- ""
print -r -- "완료: $DMG  ($(du -h "$DMG" | cut -f1))"
print -r -- "개발 환경 복구: uv sync --extra fuzzy --extra mlx --extra ocr"
