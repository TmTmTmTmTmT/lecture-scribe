#!/usr/bin/env python3
"""`LectureScribe.app` 번들 생성.

방식: **프로젝트 venv를 실행하는 경량 래퍼 앱**.
- 번들 크기 수십 KB. 빌드 수 초.
- Dock/Launchpad 아이콘, Finder "다음으로 열기", Dock에 파일 드롭이 모두 동작한다.
- 단점: 프로젝트 폴더와 venv가 있어야 한다(이 기기 전용). 다른 Mac으로 복사해
  쓰려면 PyInstaller로 자립 번들을 만들어야 한다(README 참조).

아이콘은 Qt로 그려서 `iconutil`로 .icns를 만든다(외부 이미지 파일 불필요).
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DIST = PROJECT / "dist"
APP_NAME = "LectureScribe"
BUNDLE_ID = "com.local.lecturescribe"

# FIX_GUIDE_3.md I-01: 아이콘 원본은 이제 패키지 안에 고정돼 있다(런타임도 같은
# 파일을 `importlib.resources`로 읽는다 — gui/icons.py 참조). 있으면 이걸 쓰고,
# 지워졌을 때만 즉석 도형으로 대체한다(개발 환경 복구용, §4 "하지 말 것" 아님 —
# 원본이 없는 비정상 상태에서 빌드 자체가 막히지 않게 하려는 폴백).
_FIXED_ICON_SOURCE = PROJECT / "src" / "lecture_scribe" / "assets" / "appicon.png"

AUDIO_UTIS = [
    "public.audio",
    "public.movie",
    "com.apple.m4a-audio",
    "public.mp3",
    "com.microsoft.waveform-audio",
    "public.aac-audio",
    "org.xiph.flac",
    "org.xiph.ogg",
    "public.mpeg-4",
    "com.apple.quicktime-movie",
]

LAUNCHER = """#!/bin/zsh
# LectureScribe.app 런처 — 프로젝트 venv의 GUI를 실행한다.
set -u
PYTHON="__PYTHON__"
FFMPEG_DIR="__FFMPEG_DIR__"

export LECTURE_SCRIBE_FFMPEG_DIR="$FFMPEG_DIR"
export PATH="$FFMPEG_DIR:/usr/bin:/bin:/usr/sbin:/sbin"

if [[ ! -x "$PYTHON" ]]; then
  /usr/bin/osascript -e 'display alert "LectureScribe" message "프로젝트 가상환경을 찾을 수 없습니다. 프로젝트 폴더에서 uv sync 후 install.sh를 다시 실행하세요."'
  exit 1
fi

exec "$PYTHON" -m lecture_scribe.gui.app "$@"
"""


def find_python() -> Path:
    candidate = PROJECT / ".venv" / "bin" / "python3"
    if candidate.exists():
        return candidate
    raise SystemExit("오류: .venv/bin/python3 이 없습니다. 먼저 `uv sync`를 실행하세요.")


def find_ffmpeg_dir() -> str:
    for directory in ("/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "/usr/bin"):
        if (Path(directory) / "ffprobe").exists():
            return directory
    raise SystemExit("오류: ffprobe를 찾을 수 없습니다. `brew install ffmpeg` 후 다시 실행하세요.")


def draw_icon(png_path: Path, size: int = 1024) -> bool:
    """Qt로 아이콘 PNG를 그린다(오프스크린). 실패하면 아이콘 없이 진행."""
    script = f'''
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen, QPixmap

app = QGuiApplication([])
S = {size}
pm = QPixmap(S, S)
pm.fill(Qt.GlobalColor.transparent)
p = QPainter(pm)
p.setRenderHint(QPainter.RenderHint.Antialiasing)

grad = QLinearGradient(0, 0, S, S)
grad.setColorAt(0.0, QColor("#2b5d8a"))
grad.setColorAt(1.0, QColor("#12293d"))
p.setBrush(grad)
p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(QRectF(S*0.06, S*0.06, S*0.88, S*0.88), S*0.22, S*0.22)

# 파형
p.setPen(QPen(QColor("#7fd1ff"), S*0.035, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
import math
bars = [0.30, 0.55, 0.85, 0.45, 0.70, 0.35, 0.60]
x0 = S*0.22
gap = (S*0.56)/(len(bars)-1)
for i, h in enumerate(bars):
    x = x0 + i*gap
    half = S*0.20*h
    p.drawLine(int(x), int(S*0.46-half), int(x), int(S*0.46+half))

# 텍스트 줄(전사)
p.setPen(QPen(QColor("#eaf4ff"), S*0.028, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
for i, w in enumerate((0.52, 0.44, 0.34)):
    y = S*0.66 + i*S*0.085
    p.drawLine(int(S*0.24), int(y), int(S*(0.24+w)), int(y))

p.end()
pm.save("{png_path}")
'''
    result = subprocess.run(
        [str(find_python()), "-c", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  (아이콘 생성 실패, 계속 진행): {result.stderr.strip()[:200]}")
        return False
    return png_path.exists()


def make_icns(work_dir: Path) -> Path | None:
    """PNG -> .icns (sips + iconutil).

    원본은 `_FIXED_ICON_SOURCE`(패키지 내장, 런타임과 공유)를 우선 쓴다.
    지워졌을 때만 `draw_icon()`으로 즉석 도형을 그려 빌드가 막히지 않게 한다.
    """
    work_dir.mkdir(parents=True, exist_ok=True)  # 없으면 QPixmap.save가 조용히 실패한다
    png = work_dir / "icon_1024.png"
    if _FIXED_ICON_SOURCE.exists():
        shutil.copy2(_FIXED_ICON_SOURCE, png)
    elif not draw_icon(png):
        print(f"  (아이콘 원본 없음: {_FIXED_ICON_SOURCE}, 즉석 도형도 실패)")
        return None
    iconset = work_dir / "AppIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()
    sizes = [16, 32, 64, 128, 256, 512]
    for size in sizes:
        for scale, suffix in ((1, ""), (2, "@2x")):
            pixels = size * scale
            target = iconset / f"icon_{size}x{size}{suffix}.png"
            subprocess.run(
                ["/usr/bin/sips", "-z", str(pixels), str(pixels), str(png), "--out", str(target)],
                capture_output=True,
                check=False,
            )
    icns = work_dir / "AppIcon.icns"
    result = subprocess.run(
        ["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(icns)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  (icns 변환 실패, 계속 진행): {result.stderr.strip()[:200]}")
        return None
    return icns


def build_info_plist(has_icon: bool) -> dict[str, object]:
    info: dict[str, object] = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": True,  # GUI 프로세스만 코드에서 Dock에 승격
        "NSHumanReadableCopyright": "로컬 전용 앱",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "오디오·영상 파일",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": AUDIO_UTIS,
            }
        ],
    }
    if has_icon:
        # FIX_GUIDE_3.md I-06: LectureScribe.spec(PyInstaller BUNDLE)과 같은
        # 값(확장자 포함)을 쓴다. 둘 다 동작은 하지만 규약을 통일한다.
        info["CFBundleIconFile"] = "AppIcon.icns"
    return info


def main() -> int:
    python = find_python()
    ffmpeg_dir = find_ffmpeg_dir()
    DIST.mkdir(exist_ok=True)
    app_dir = DIST / f"{APP_NAME}.app"
    if app_dir.exists():
        shutil.rmtree(app_dir)

    macos = app_dir / "Contents" / "MacOS"
    resources = app_dir / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)

    print(f"  python: {python}")
    print(f"  ffmpeg: {ffmpeg_dir}")

    icns = make_icns(DIST / "_iconwork")
    if icns is not None:
        shutil.copy2(icns, resources / "AppIcon.icns")

    launcher = macos / APP_NAME
    launcher.write_text(
        LAUNCHER.replace("__PYTHON__", str(python)).replace("__FFMPEG_DIR__", ffmpeg_dir),
        encoding="utf-8",
    )
    launcher.chmod(0o755)

    with (app_dir / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump(build_info_plist(icns is not None), handle)

    # 서명 없이 실행 시 Gatekeeper 경고가 뜨므로 ad-hoc 서명을 붙인다.
    result = subprocess.run(
        ["/usr/bin/codesign", "--force", "--deep", "--sign", "-", str(app_dir)],
        capture_output=True,
        text=True,
    )
    signed = result.returncode == 0
    if not signed:
        print(f"  (ad-hoc 서명 실패, 계속 진행): {result.stderr.strip()[:200]}")

    shutil.rmtree(DIST / "_iconwork", ignore_errors=True)
    print(f"  생성: {app_dir}")
    print(f"  아이콘: {'있음' if icns else '없음'} / ad-hoc 서명: {'완료' if signed else '실패'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
