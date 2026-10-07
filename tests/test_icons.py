"""FIX_GUIDE_3.md I-01/I-02 실행분 테스트: 앱 아이콘 로드.

원본 자산이 있을 때/없을 때 모두 확인한다. 없을 때 조용히 넘어가지 않고
로그를 남기는지도 확인한다(§15-6).
"""

from __future__ import annotations

import logging

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    assert isinstance(app, QApplication)
    return app


def test_load_app_icon_reads_packaged_asset(qapp: QApplication) -> None:
    """패키지 안에 고정된 원본을 읽어 실제 아이콘을 돌려줘야 한다."""
    from lecture_scribe.gui.icons import load_app_icon

    icon = load_app_icon()
    assert not icon.isNull()
    # 즉석 도형 폴백(36pt)이 아니라 원본 자산(1024pt)이어야 한다.
    sizes = icon.availableSizes()
    assert sizes, "아이콘에 크기 정보가 없다"
    assert max(s.width() for s in sizes) >= 512


def test_load_app_icon_falls_back_and_logs_when_asset_missing(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """자산을 못 읽으면 조용히 넘어가지 말고 로그를 남긴 뒤 도형으로 대체한다."""
    from lecture_scribe.gui import icons as icons_mod

    def _boom() -> None:
        raise FileNotFoundError("자산 없음(테스트)")

    monkeypatch.setattr(
        icons_mod.resources, "files", lambda *_a, **_kw: (_ for _ in ()).throw(FileNotFoundError("자산 없음(테스트)"))
    )

    with caplog.at_level(logging.WARNING, logger="lecture_scribe.gui.icons"):
        icon = icons_mod.load_app_icon()

    assert not icon.isNull(), "폴백 도형조차 없으면 트레이 생성 자체가 실패한다"
    assert any("아이콘" in r.message for r in caplog.records), "실패 사유가 로그에 안 남았다"


# --- FIX_GUIDE_4.md A-05: 트레이 전용 템플릿 아이콘 ---


def test_load_tray_icon_reads_template_asset_and_sets_mask(qapp: QApplication) -> None:
    """트레이 아이콘은 실루엣 자산을 읽고 `isMask()`가 켜져 있어야 한다.

    컬러 아이콘을 그대로 트레이에 넣으면 다크 메뉴 막대에서 거의 안 보인다
    (실측, FIX_GUIDE_3.md 완료 후). 템플릿 지정이 빠지면 이 문제가 되돌아온다.
    """
    from lecture_scribe.gui.icons import load_tray_icon

    icon = load_tray_icon()
    assert not icon.isNull()
    assert icon.isMask() is True


def test_load_tray_icon_falls_back_to_color_icon_without_mask(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실루엣 자산이 없으면 컬러 아이콘으로 대체하되, 거기엔 마스크를 걸지 않는다.

    템플릿이 아닌 이미지에 `setIsMask(True)`를 걸면 색이 다 날아간다 — 트레이가
    안 뜨는 것보단 낫지만, 망가진 아이콘을 보여주는 것보단 컬러 그대로가 낫다.
    """
    from lecture_scribe.gui import icons as icons_mod

    original_load_asset = icons_mod._load_asset

    def _fail_only_template(filename: str) -> object:
        if filename == "appicon_template.png":
            return None
        return original_load_asset(filename)

    monkeypatch.setattr(icons_mod, "_load_asset", _fail_only_template)

    icon = icons_mod.load_tray_icon()
    assert not icon.isNull()
    assert icon.isMask() is False
