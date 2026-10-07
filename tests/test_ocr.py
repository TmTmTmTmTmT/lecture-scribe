"""ocr.py: 순수 함수(UI 줄 판정·잡음 제외)와 Vision 실호출(가능할 때만)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from lecture_scribe.ocr import (
    OcrLine,
    flag_top_band_lines,
    flag_ui_lines,
    is_noise_text,
    letters_key,
    ocr_available,
    recognize,
)


def line(text: str, x: float, top: float, height: float = 0.0) -> OcrLine:
    return OcrLine(text=text, confidence=1.0, x=x, top=top, height=height)


def test_noise_text() -> None:
    assert is_noise_text("00:02")
    assert is_noise_text("1:23:45")
    assert is_noise_text("K")
    assert is_noise_text("⑦")
    assert not is_noise_text("FIR")
    assert not is_noise_text("QPSK")


def test_letters_key_drops_icon_garbage() -> None:
    assert letters_key("13 컴퓨터네트워크") == letters_key("{3 컴퓨터네트워크")
    assert letters_key("프 주차별 강의콘텐츠!") == "프주차별강의콘텐츠"


TITLES = [
    "Nyquist Sampling Theorem",
    "FIR filter design",
    "Raised cosine roll-off",
    "Bandpass and bandstop",
    "Impulse reconstruction",
    "Aliasing effect",
    "Parks McClellan program",
    "Ideal interpolation",
    "Discrete Fourier transform",
    "Convolution property",
]


def _frames(n: int) -> list[list[OcrLine]]:
    frames = []
    for i in range(n):
        frames.append(
            [
                # 매 프레임 같은 위치의 메뉴(OCR이 글자를 조금씩 다르게 읽음)
                line(["컴퓨터네트워크", "13 컴퓨터네트워크", "컴퓨터너트워크"][i % 3], 0.09, 0.55),
                line("주차별 강의콘텐츠", 0.09, 0.73),
                # 슬라이드 제목은 프레임마다 다른 글자
                line(TITLES[i % len(TITLES)], 0.25, 0.83),
            ]
        )
    return frames


def test_flag_ui_lines_marks_recurring_menu_but_not_titles() -> None:
    frames = _frames(10)
    flagged = flag_ui_lines(frames)
    assert flagged == 20
    for lines in frames:
        assert lines[0].ui and lines[1].ui
        assert not lines[2].ui


def test_flag_ui_lines_skipped_for_few_frames() -> None:
    frames = _frames(4)
    assert flag_ui_lines(frames) == 0
    assert not any(ln.ui for lines in frames for ln in lines)


def test_flag_ui_lines_same_text_different_position_is_not_ui() -> None:
    frames = [[line("Nyquist", 0.2 + 0.05 * i, 0.5 + 0.03 * i)] for i in range(8)]
    assert flag_ui_lines(frames) == 0


# --- 화면 맨 위 띠 (FIX_GUIDE_14 U-01) --------------------------------------
#
# 실측(ML검파기 샘플 13프레임 + 채널모델 샘플 6프레임): 메뉴바·주소창·LMS 고정 배너의
# 아래쪽 가장자리(top-height) 최솟값 0.8946, 실제 슬라이드 제목의 top 최댓값 0.8494.
# 아래 좌표는 그 실측 범위 안에서 뽑았다.


def test_flag_top_band_marks_menu_bar_even_in_a_single_frame() -> None:
    """빈도·픽셀 불변 규칙이 놓치는, 딱 한 프레임에만 나온 메뉴바도 위치로 잡는다."""
    frames = [
        [line("파일", 0.06, 0.991, height=0.015), line("ML 검파기", 0.16, 0.813, height=0.042)],
        [line("ML 검파기", 0.16, 0.813, height=0.042)],  # 메뉴 없음(창 모드였던 프레임)
    ]
    flagged = flag_top_band_lines(frames)
    assert flagged == 1
    assert frames[0][0].ui is True
    assert frames[0][1].ui is False
    assert frames[1][0].ui is False


def test_flag_top_band_does_not_touch_slide_titles() -> None:
    """제목이 화면 위쪽 가까이 있어도(0.85 미만) 띠 규칙에 안 걸린다."""
    frames = [[line("ML(Maximum Likelihood) 검파기(Detector)", 0.16, 0.849, height=0.042)]]
    assert flag_top_band_lines(frames) == 0
    assert frames[0][0].ui is False


def test_flag_top_band_ignores_large_boxes_even_inside_band() -> None:
    """띠 안에서 시작해도 줄 높이가 크면(제목이 화면 위쪽까지 걸친 경우) 건드리지 않는다."""
    frames = [[line("큰 제목", 0.1, 0.99, height=0.2)]]
    assert flag_top_band_lines(frames) == 0


def test_flag_top_band_does_not_touch_already_ui_flagged_lines() -> None:
    ln = line("파일", 0.06, 0.991, height=0.015)
    ln.ui = True
    assert flag_top_band_lines([[ln]]) == 0


@pytest.mark.skipif(not ocr_available(), reason="pyobjc-framework-Vision 미설치")
def test_recognize_reads_english_title(tmp_path: Path) -> None:
    img = Image.new("RGB", (1024, 300), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 64)
    draw.text((40, 100), "Nyquist Sampling Theorem", fill="black", font=font)
    path = tmp_path / "t.png"
    img.save(path)
    texts = [ln.text.lower() for ln in recognize(path)]
    assert any("nyquist" in t and "theorem" in t for t in texts)
