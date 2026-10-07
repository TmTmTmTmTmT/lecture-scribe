# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 스펙 — 자립형 LectureScribe.app 생성.

다른 Mac에 그대로 복사해도 동작하도록 Python 런타임과 의존성을 전부 포함한다.
- mlx 백엔드는 torch(3GB)를 끌고 오므로 배포 번들에서 제외한다.
- ffmpeg/ffprobe는 번들하지 않는다(라이선스·용량). 앱이 없으면 안내한다.
- 모델은 첫 실행 시 내려받는다(약 3GB).
"""

from PyInstaller.utils.hooks import collect_all, collect_data_files

datas = []
binaries = []
hiddenimports = []

# C 확장·데이터 파일을 통째로 가져와야 하는 패키지들
# mlx는 Metal GPU 백엔드용. torch는 런타임에 import하지 않으므로 제외해도 동작한다
# (실측: `import mlx_whisper` 시 torch가 sys.modules에 올라오지 않음).
for pkg in (
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "tokenizers",
    "rapidfuzz",
    "mlx",
    "mlx_whisper",
    "numba",
    "tiktoken",
    # 영상 슬라이드 OCR(macOS Vision). extra `ocr`가 설치된 환경에서만 딸려온다.
    "objc",
    "Vision",
    "Quartz",
    "Foundation",
    "CoreFoundation",
    "CoreML",
    "AppKit",
):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:  # noqa: BLE001 - 선택 패키지(OCR)가 없으면 건너뛴다
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# faster-whisper의 Silero VAD 모델 등 assets
datas += collect_data_files("faster_whisper", include_py_files=False)

# FIX_GUIDE_3.md I-01/I-06: 앱 아이콘 원본(gui/icons.py가 importlib.resources로
# 런타임에 읽는다). hiddenimports만으로는 데이터 파일이 안 딸려온다.
datas += collect_data_files("lecture_scribe.assets", include_py_files=False)

hiddenimports += [
    "lecture_scribe.backends.faster",
    "lecture_scribe.backends.mlx",
    "lecture_scribe.gui.window",
    "lecture_scribe.gui.settings_panel",
    "lecture_scribe.gui.dropzone",
    "lecture_scribe.gui.worker",
    "lecture_scribe.assets",
    "lecture_scribe.frames",
    "lecture_scribe.ocr",
    "lecture_scribe.slide_terms",
    "lecture_scribe.video_stage",
]

# 용량을 키우기만 하는 것들 제외
excludes = [
    "torch", "matplotlib", "tkinter",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtMultimedia",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DRender", "PySide6.QtBluetooth",
    "PySide6.QtDesigner", "PySide6.QtNetworkAuth", "PySide6.QtPositioning",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtTest",
    "PySide6.QtWebChannel", "PySide6.QtWebSockets", "pytest", "mypy",
]

a = Analysis(
    ["entry_app.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LectureScribe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,   # Finder에서 파일 열기(argv) 전달
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="LectureScribe",
)
app = BUNDLE(
    coll,
    name="LectureScribe.app",
    icon="AppIcon.icns",
    bundle_identifier="com.local.lecturescribe",
    version="0.1.0",
    info_plist={
        "CFBundleName": "LectureScribe",
        "CFBundleDisplayName": "LectureScribe",
        "CFBundleShortVersionString": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        # 기본은 Dock에 뜨지 않는 액세서리 앱. GUI 프로세스만 코드에서 승격한다.
        # (파이썬 보조 프로세스가 번들을 재실행해 아이콘이 하나 더 생기는 문제 방지)
        "LSUIElement": True,
        "NSHumanReadableCopyright": "로컬 전용 강의 전사 앱",
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "오디오·영상 파일",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": [
                    "public.audio", "public.movie", "com.apple.m4a-audio",
                    "public.mp3", "com.microsoft.waveform-audio",
                    "public.aac-audio", "org.xiph.flac", "org.xiph.ogg",
                    "public.mpeg-4", "com.apple.quicktime-movie",
                ],
            }
        ],
    },
)
