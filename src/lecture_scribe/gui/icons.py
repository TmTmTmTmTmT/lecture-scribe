"""앱 아이콘 로드 (FIX_GUIDE_3.md I-01/I-02).

패키지 안에 고정된 원본(`assets/appicon.png`)을 읽어 `QIcon`으로 만든다.
`importlib.resources`로 읽으므로 소스 실행(editable install)과 PyInstaller
번들(파일이 `_MEIPASS` 아래 풀리는 경우 포함) 양쪽에서 같은 코드로 동작한다.

원본 자산이 없거나 못 읽으면(개발 중 실수로 지웠거나, 번들 빌드가 자산을
빠뜨렸거나) 조용히 넘어가지 않고 **로그를 남기고** 즉석 도형으로 대체한다
(§15-6 "오류를 조용히 삼키지 않는다").
"""

from __future__ import annotations

import importlib.resources as resources

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from ..logsetup import get_logger

logger = get_logger(__name__)

#: 트레이 아이콘 크기(pt). 레티나에서 흐리지 않게 2배로 그린다.
_FALLBACK_SIZE = 36


def _fallback_icon() -> QIcon:
    """원본 자산을 못 읽을 때만 쓰는 임시 도형 아이콘."""
    pixmap = QPixmap(_FALLBACK_SIZE, _FALLBACK_SIZE)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(120, 120, 120))
    painter.setBrush(QColor(90, 140, 200))
    painter.drawRoundedRect(4, 4, _FALLBACK_SIZE - 8, _FALLBACK_SIZE - 8, 7, 7)
    painter.end()
    return QIcon(pixmap)


def _load_asset(filename: str) -> QIcon | None:
    """`assets/` 안의 아이콘 파일을 읽는다. 실패하면 None(호출부가 대체 결정)."""
    try:
        asset = resources.files("lecture_scribe.assets") / filename
        with resources.as_file(asset) as path:
            icon = QIcon(str(path))
        if not icon.isNull():
            return icon
        logger.warning("앱 아이콘 자산이 비어 있습니다: %s", asset)
    except (ModuleNotFoundError, FileNotFoundError, OSError) as exc:
        logger.warning("앱 아이콘 자산을 읽지 못했습니다(%s): %s", filename, exc)
    return None


def load_app_icon() -> QIcon:
    """Dock·창용 컬러 아이콘. 실패하면 즉석 도형으로 대체(로그 남김)."""
    return _load_asset("appicon.png") or _fallback_icon()


def load_tray_icon() -> QIcon:
    """메뉴 막대(트레이) 전용 단색 실루엣 아이콘 (FIX_GUIDE_4.md A-05).

    컬러 아이콘(`appicon.png`)을 그대로 트레이에 넣으면 다크 메뉴 막대에서
    거의 안 보인다(실측: FIX_GUIDE_3.md 완료 후 스크린샷에서 못 찾음). macOS
    메뉴 막대는 **템플릿 이미지**(단색 실루엣 + 알파)를 기대하고 다크/라이트에
    맞춰 자동으로 색을 뒤집는다.

    `appicon_template.png`는 `appicon.png`의 명암 대비에서 **기계적으로 뽑은
    실루엣**이다(새로 그린 그림이 아니다 — 배경보다 밝은 픽셀만 불투명 검정으로
    남기고 나머지는 투명 처리). 실패하면 컬러 아이콘으로 대체하되(트레이가
    아예 안 뜨는 것보단 낫다) `setIsMask`는 컬러 아이콘엔 걸지 않는다 —
    템플릿이 아닌 이미지에 걸면 색이 다 날아간다.
    """
    icon = _load_asset("appicon_template.png")
    if icon is not None:
        icon.setIsMask(True)
        return icon
    return load_app_icon()


__all__ = ["load_app_icon", "load_tray_icon"]
