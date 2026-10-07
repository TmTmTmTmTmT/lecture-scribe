"""slide_terms.py: OCR 줄 -> 후보 용어 (합성 입력)."""

from __future__ import annotations

from lecture_scribe.ocr import OcrLine
from lecture_scribe.slide_terms import extract_slide_terms


def ln(text: str, top: float, x: float = 0.25, height: float = 0.03, ui: bool = False) -> OcrLine:
    return OcrLine(text=text, confidence=1.0, x=x, top=top, width=0.4, height=height, ui=ui)


def frames_basic() -> list[list[OcrLine]]:
    return [
        [
            ln("FIR FILTER DESIGN USING", 0.82, height=0.05),
            ln("Low-pass digital FIR filter with a cutoff", 0.7),
            ln("h(m)= sin(2πFc m)/π(m)", 0.5),
        ],
        [
            ln("Nyquist Sampling Theorem", 0.82, height=0.05),
            ln("the impulse response is finite", 0.7),
            ln("impulse response of the filter", 0.6),
        ],
        [
            ln("Sampling and Reconstruction", 0.82, height=0.05),
            ln("impulse response again", 0.7),
            ln("과목", 0.7, x=0.09, ui=True),
        ],
        [
            ln("Sampling and Reconstruction", 0.82, height=0.05),
            ln("impulse response once more", 0.7),
        ],
    ]


def test_titles_acronyms_and_repeated_collocations() -> None:
    terms = extract_slide_terms(frames_basic())
    lowered = [t.lower() for t in terms]
    assert "fir filter design" in lowered  # 대문자 제목 -> 약어는 유지, 나머지는 첫 글자만 대문자
    assert "FIR" in terms  # 소문자가 섞인 줄에서 확정된 약어
    assert "Nyquist Sampling Theorem" in terms
    assert "Sampling and Reconstruction" in terms
    assert "impulse response" in lowered  # 3개 프레임에서 반복


def test_all_caps_title_words_are_not_acronyms() -> None:
    terms = extract_slide_terms(frames_basic())
    assert "FILTER" not in terms and "DESIGN" not in terms and "USING" not in terms


def test_math_lines_and_ui_lines_are_excluded() -> None:
    terms = extract_slide_terms(frames_basic())
    joined = " ".join(terms)
    assert "sin(2" not in joined and "h(m)" not in joined
    assert "과목" not in terms


def test_user_terms_are_not_repeated() -> None:
    terms = extract_slide_terms(
        frames_basic(), user_terms=["Nyquist sampling theorem", "FIR"]
    )
    lowered = [t.lower() for t in terms]
    assert "nyquist sampling theorem" not in lowered
    assert "fir" not in lowered


def test_korean_needs_title_or_repetition_and_josa_is_stripped() -> None:
    frames = [
        [ln("전송필터와 수신필터", 0.8, height=0.05), ln("표본화정리는 중요하다", 0.6)],
        [ln("다른 슬라이드", 0.8, height=0.05), ln("오인식글자", 0.6)],
    ]
    terms = extract_slide_terms(frames)
    assert "전송필터" in terms  # 제목 + 조사 '와' 제거
    assert "수신필터" in terms
    assert "오인식글자" not in terms  # 1회만 나온 비제목 한글


def test_near_duplicate_ocr_variants_are_merged() -> None:
    frames = [
        [ln("Linear Time-Invariant Digital Filters", 0.82, height=0.05), ln("a body line here", 0.6)],
        [ln("Linear Time-Invariant Digital Fitters", 0.82, height=0.05), ln("another body text", 0.6)],
    ]
    terms = [t for t in extract_slide_terms(frames) if t.startswith("Linear")]
    assert len(terms) == 1


def test_max_terms_and_empty_inputs() -> None:
    assert extract_slide_terms([], max_terms=5) == []
    assert extract_slide_terms(frames_basic(), max_terms=0) == []


def test_menu_words_are_excluded_even_when_not_flagged_ui() -> None:
    """FIX_GUIDE_14 U-01 보조: 위치 규칙(`flag_top_band_lines`)이 못 미치는 자리에
    메뉴가 나와도(예: 창이 화면 중간에 걸쳐 있는 녹화), 알려진 메뉴 어휘·OCR 변형은
    용어 목록에서 빠진다. (`방문 기록`처럼 두 단어로 갈라지는 항목은 이 안전망의
    범위 밖 — 실측 사례는 위치 규칙으로 이미 잡힌다.)
    """
    frames = [
        [ln("파일 보기 북마크 개발자용 원도우 도움말", 0.6, height=0.03), ln("ML 검파기", 0.8, height=0.05)],
        [ln("파일 보기 북아크 개발자용 도움말", 0.6, height=0.03), ln("ML 검파기", 0.8, height=0.05)],
        [ln("파일 컨집 보기 북아크 개발자용 원도우 도움말", 0.6, height=0.03), ln("ML 검파기", 0.8, height=0.05)],
    ]
    terms = extract_slide_terms(frames)
    menu_words = {"파일", "보기", "북마크", "북아크", "개발자용", "원도우", "연도우", "도움말", "편집", "컨집"}
    assert not any(t in menu_words for t in terms)
    assert "검파기" in terms  # 실제 용어는 그대로 남는다


def test_english_menu_words_are_excluded_from_ngrams() -> None:
    frames = [
        [ln("File Edit View History Bookmarks Window Help", 0.99, height=0.03), ln("Matched filter design", 0.8, height=0.05)],
        [ln("File Edit View History Bookmarks Window Help", 0.99, height=0.03), ln("Matched filter theory", 0.8, height=0.05)],
        [ln("File Edit View History Bookmarks Window Help", 0.99, height=0.03), ln("Matched filter basics", 0.8, height=0.05)],
    ]
    terms = extract_slide_terms(frames)
    lowered = [t.lower() for t in terms]
    assert not any(w in lowered for w in ("file", "edit", "view", "history", "bookmarks", "window", "help"))
    assert len(extract_slide_terms(frames_basic(), max_terms=2)) == 2
