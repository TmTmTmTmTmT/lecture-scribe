"""슬라이드 OCR 텍스트에서 전사용 후보 용어 추출 (PLAN_VIDEO_FRAMES.md V-04).

GUI/백엔드 비의존 순수 함수. 새 NLP 의존성(형태소 분석기 등) 없이 휴리스틱만 쓴다.

무엇을 뽑는가
- 영문 약어(`FIR`, `LPF`) — **소문자가 섞인 줄에서만**. 전부 대문자인 제목 줄("FIR FILTER DESIGN")에서는
  모든 단어가 약어처럼 보이므로 약어 후보로 쓰지 않는다.
- 영문 구(제목·짧은 줄): `Nyquist Sampling Theorem`, `Sampling and Reconstruction`
- 여러 프레임에서 반복되는 영어 2~3단어 연어: `impulse response`
- 한글 단어(조사 제거): 제목 줄에 나오거나 여러 프레임에 반복되는 것

무엇을 버리는가: UI 줄, 잡음, **수식 줄**(OCR이 깨뜨림 — 실측), 불용어, 1회만 나온 비제목 한글(오인식),
사용자 용어집과 겹치는 것.

알려진 한계(샘플 1 실측): OCR이 놓친 화면 메뉴 글자("다시보드" 등)가 남을 수 있어 화면 UI 단어
불용어 목록을 둔다. 완전하지 않다 — 효과는 V-08 게이트로 판정한다.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Final

from .ocr import OcrLine, is_noise_text, letters_key

_EN_STOP: Final[frozenset[str]] = frozenset(
    """a an the of and or to in on for with by is are was were be been as at from that this these those
    we you it its our can will should would could may might using use used via into than then also
    not no if when where which what how why so such each any all one two three""".split()
)
#: 화면 밖 공통 표지(대학명 등)와 강의 진행 문구. macOS/브라우저 메뉴 이름도 여기 포함한다
#: (FIX_GUIDE_14 U-01 보조 — `flag_top_band_lines`가 위치로 못 거른 경우의 안전망).
_EN_GENERIC: Final[frozenset[str]] = frozenset(
    "university national jeju contents outline summary example examples reference references thanks"
    " file edit view history bookmarks develop window help go format insert tools search".split()
)

#: 한글 메뉴 어휘(정규화 후 글자만 비교, FIX_GUIDE_14 U-01). OCR이 자주 틀리는 실측 변형
#: ("원도우", "북아크", "컨집")도 그대로 넣는다 — 유사도 계산 없이 정확히 잡기 위함.
_MENU_VOCAB: Final[frozenset[str]] = frozenset(
    letters_key(w)
    for w in (
        "파일", "편집", "보기", "방문기록", "방문 기록", "북마크", "개발자용", "윈도우", "도움말",
        "원도우", "연도우", "북아크", "컨집", "원집",
    )
)
#: 메뉴 어휘와의 유사도 하한. OCR 변형을 흡수하되(`letters_key`가 이미 자모 단위로 겹치는
#: 오인식 상당수를 잡는다), 진짜 용어("파일럿" 등)까지 지우지 않을 만큼 보수적으로 높게 잡는다.
_MENU_SIMILARITY: Final[float] = 0.8


def _is_menu_word(word: str) -> bool:
    key = letters_key(word)
    if not key:
        return False
    if key in _MENU_VOCAB:
        return True
    return any(SequenceMatcher(None, key, vocab).ratio() >= _MENU_SIMILARITY for vocab in _MENU_VOCAB)
_KO_STOP: Final[frozenset[str]] = frozenset(
    """목차 예제 감사합니다 참고문헌 요약 정리 다음 이전 강의 학습 문제 그림 표 페이지
    다시보드 대시보드 과목 캘린더 메시지함 마이페이지 이용안내 전체게시물 수업 계획서 공지사항 강의콘텐츠
    주차별 출결현황 출결 현황 게시판 설문 튜터 화상강의 강의자료실 세부성적채점 커넥트 와이즈 코딩수업
    컴퓨터네트워크 사용자 그룹설정 상태 확인 진행 완료 인정 처리 시청""".split()
)
_JOSA_SUFFIXES: Final[tuple[str, ...]] = (
    "으로", "에서", "에게", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만",
)
_MATH_CHARS: Final[frozenset[str]] = frozenset("=*+<>≤≥·|^_~±")
_MATH_CALL_RE: Final[re.Pattern[str]] = re.compile(r"\b\w{1,3}\s?\([^)]*\)|\w\(\w")
_EN_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z][A-Za-z\-']*")
_KO_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[가-힣]{2,12}")
_CLAUSE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[:;/|]|\s-\s")
#: 화면 위쪽에서 이 거리 안이면 같은 높이의 제목 줄로 본다(정규화 좌표)
_TITLE_BAND: Final[float] = 0.035
#: 제목 줄은 프레임 줄 높이 중앙값의 이 배수 이상이어야 한다.
_TITLE_MIN_HEIGHT_RATIO: Final[float] = 1.15
#: 줄이 이 개수 이하인 프레임(표지 슬라이드 등)은 글자 크기 비교 없이 맨 위 줄을 제목으로 본다.
_SPARSE_SLIDE_LINES: Final[int] = 4

#: 반복 연어로 인정하는 최소 프레임 수. 2로 두면 연속한 두 슬라이드에 반복된 머리글의 조각
#: (`pass linear`, `phase fir` 등)이 쏟아진다(샘플 1 실측).
NGRAM_MIN_FRAMES: Final[int] = 3
#: 글자만 남긴 문자열이 이 이상 비슷하면 OCR 오탈자 변형으로 보고 점수 높은 쪽만 남긴다.
NEAR_DUPLICATE_SIMILARITY: Final[float] = 0.88

TITLE_WEIGHT: Final[int] = 3
#: 점수에서 프레임 수가 기여하는 상한. 화면 고정 요소가 반복 횟수로 상위를 차지하는 것을 막는다.
FRAME_SCORE_CAP: Final[int] = 4


@dataclass(slots=True)
class _Candidate:
    display: str
    frames: set[int] = field(default_factory=set)
    title_hits: int = 0
    first_seen: int = 0

    @property
    def score(self) -> int:
        return min(len(self.frames), FRAME_SCORE_CAP) + TITLE_WEIGHT * min(self.title_hits, 2)


def _strip_leading_icon(text: str) -> str:
    """OCR이 아이콘/글머리표를 한 글자로 읽어 줄 앞에 붙인 것을 제거."""
    parts = text.split(maxsplit=1)
    if len(parts) == 2 and len(parts[0]) == 1:
        return parts[1]
    return text


def _is_math(text: str) -> bool:
    if any(ch in _MATH_CHARS for ch in text):
        return True
    if _MATH_CALL_RE.search(text):
        return True
    visible = [ch for ch in text if not ch.isspace()]
    if not visible:
        return True
    digits_symbols = sum(1 for ch in visible if ch.isdigit() or not ch.isalnum())
    return digits_symbols / len(visible) > 0.3


def _strip_josa(word: str) -> str:
    for suffix in _JOSA_SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 2:
            return word[: -len(suffix)]
    return word


def _is_upper_line(words: Sequence[str]) -> bool:
    """대문자 단어가 절반 이상이면 대문자 제목 줄로 본다.

    `PARKS McCLELLAN PROGRAM`처럼 섞인 줄도 포함한다(모든 단어가 약어처럼 보이는 것을 막는다).
    """
    letters = [w for w in words if len(w) >= 2]
    if not letters:
        return False
    return sum(1 for w in letters if w.isupper()) / len(letters) >= 0.5


def _trim_stop(words: list[str]) -> list[str]:
    while words and words[0].lower() in _EN_STOP:
        words = words[1:]
    while words and words[-1].lower() in _EN_STOP:
        words = words[:-1]
    return words


def _find_titles(lines: Sequence[OcrLine]) -> set[int]:
    """프레임에서 가장 위쪽 높이대이면서 **다른 줄보다 큰 글자**인 줄 번호.

    도표만 있는 슬라이드에서는 가장 위의 줄이 그림 속 라벨일 수 있으므로(실측: "frequency of 1 Hz")
    글자 크기가 눈에 띄게 크지 않으면 제목으로 보지 않는다. 줄 높이 정보가 없으면 위치만 쓴다.
    """
    eligible = [
        (i, ln)
        for i, ln in enumerate(lines)
        if len(_strip_leading_icon(ln.text).split()) >= 2 or len(ln.text.strip()) >= 6
    ]
    if not eligible:
        return set()
    heights = sorted(ln.height for ln in lines if ln.height > 0)
    if heights and len(lines) > _SPARSE_SLIDE_LINES:
        median = heights[len(heights) // 2]
        eligible = [(i, ln) for i, ln in eligible if ln.height >= median * _TITLE_MIN_HEIGHT_RATIO]
        if not eligible:
            return set()
    top = max(ln.top for _, ln in eligible)
    return {i for i, ln in eligible if top - ln.top <= _TITLE_BAND}


def extract_slide_terms(
    frames: Sequence[Sequence[OcrLine]],
    *,
    user_terms: Sequence[str] = (),
    max_terms: int = 30,
) -> list[str]:
    """프레임별 OCR 줄(UI 줄은 `ui=True`)에서 점수순 후보 용어를 만든다."""
    if max_terms <= 0:
        return []
    usable: list[list[OcrLine]] = [
        [ln for ln in lines if not ln.ui and not is_noise_text(ln.text)] for lines in frames
    ]

    # 1) 약어는 소문자가 섞인 줄에서만 확정한다(전부 대문자인 제목 줄에서는 알 수 없다).
    acronyms: dict[str, set[int]] = {}
    for f, lines in enumerate(usable):
        for ln in lines:
            text = _strip_leading_icon(ln.text)
            if _is_math(text):
                continue
            words = _EN_WORD_RE.findall(text)
            if _is_upper_line(words):
                continue
            for w in words:
                if 2 <= len(w) <= 6 and w.isupper():
                    acronyms.setdefault(w, set()).add(f)
    known_acronyms = {
        w for w, fs in acronyms.items() if len(w) >= 3 or len(fs) >= 2
    }

    cands: dict[str, _Candidate] = {}
    order = 0

    def add(key: str, display: str, frame: int, is_title: bool) -> None:
        nonlocal order
        cand = cands.get(key)
        if cand is None:
            order += 1
            cand = cands[key] = _Candidate(display=display, first_seen=order)
        cand.frames.add(frame)
        if is_title:
            cand.title_hits += 1

    ngram_frames: dict[tuple[str, ...], set[int]] = {}
    ngram_display: dict[tuple[str, ...], Counter[str]] = {}

    for f, lines in enumerate(usable):
        titles = _find_titles(lines)
        for i, ln in enumerate(lines):
            is_title = i in titles
            text = _strip_leading_icon(ln.text).strip()
            if _is_math(text):
                continue
            for clause in _CLAUSE_SPLIT_RE.split(text):
                clause = _strip_leading_icon(clause.strip()).rstrip(".,;")
                if not clause:
                    continue
                words = _EN_WORD_RE.findall(clause)

                # 약어
                for w in words:
                    if w in known_acronyms:
                        add(w.lower(), w, f, is_title)

                # 영문 구: 제목이거나 짧은 줄. 문장(긴 줄)은 구로 쓰지 않는다.
                if 2 <= len(words) <= 6 and (is_title or len(words) <= 4):
                    trimmed = _trim_stop(list(words))
                    # 제목이 아닌 줄은 대문자로 시작하는 단어가 둘 이상일 때만 구로 본다.
                    # (문장이 줄바꿈된 조각 "composed by adding together" 등을 거른다)
                    capitalized = sum(1 for w in trimmed if w[0].isupper())
                    lowered_words = [w.lower() for w in trimmed]
                    if (
                        len(trimmed) >= 2
                        and sum(len(w) >= 3 for w in trimmed) >= 2
                        and len(set(lowered_words)) == len(lowered_words)
                        and (is_title or capitalized >= 2)
                        and not any(w.lower() in _EN_GENERIC for w in trimmed)
                    ):
                        if _is_upper_line(trimmed):
                            shown = [
                                w if (w in known_acronyms or not w.isupper()) else w.capitalize()
                                for w in trimmed
                            ]
                        else:
                            shown = trimmed
                        phrase = " ".join(shown)
                        add(phrase.lower(), phrase, f, is_title)

                # 반복 연어(소문자화한 2~3단어)
                lowered = [w.lower() for w in words]
                for n in (2, 3):
                    for s in range(len(lowered) - n + 1):
                        gram = tuple(lowered[s : s + n])
                        if (
                            gram[0] in _EN_STOP
                            or gram[-1] in _EN_STOP
                            or any(len(w) < 3 for w in gram)
                            or any(w in _EN_GENERIC for w in gram)
                        ):
                            continue
                        ngram_frames.setdefault(gram, set()).add(f)
                        ngram_display.setdefault(gram, Counter())[" ".join(words[s : s + n])] += 1

                # 한글 단어
                for raw in _KO_WORD_RE.findall(clause):
                    word = _strip_josa(raw)
                    if len(word) < 2 or word in _KO_STOP or _is_menu_word(word):
                        continue
                    add(word, word, f, is_title)

    for gram, fs in ngram_frames.items():
        if len(fs) >= NGRAM_MIN_FRAMES:
            display = ngram_display[gram].most_common(1)[0][0]
            key = " ".join(gram)
            cand = cands.get(key)
            if cand is None:
                cand = cands[key] = _Candidate(display=display, first_seen=len(cands) + 1)
            cand.frames |= fs

    # 한글은 제목에 나오거나 3프레임 이상 반복될 때만 인정(OCR 오인식·화면 UI 방지)
    def accepted(key: str, cand: _Candidate) -> bool:
        if re.fullmatch(r"[가-힣]+", key):
            return cand.title_hits > 0 or len(cand.frames) >= 3
        return True

    user_keys = [letters_key(t) for t in user_terms if t.strip()]
    ranked = sorted(
        ((k, c) for k, c in cands.items() if accepted(k, c)),
        key=lambda kc: (-kc[1].score, kc[1].first_seen),
    )

    chosen: list[str] = []
    chosen_keys: list[str] = []
    for _key, cand in ranked:
        cand_key = letters_key(cand.display)
        if len(cand_key) < 2:
            continue
        if any(
            SequenceMatcher(None, cand_key, ck).ratio() >= NEAR_DUPLICATE_SIMILARITY
            for ck in chosen_keys
        ):
            continue
        if cand_key in user_keys or (
            len(cand_key) >= 4 and any(cand_key in u for u in user_keys)
        ):
            continue
        if len(cand_key) >= 6 and any(cand_key in ck for ck in chosen_keys):
            continue
        chosen.append(cand.display)
        chosen_keys.append(cand_key)
        if len(chosen) >= max_terms:
            break
    return chosen


def normalize_terms(terms: Sequence[str]) -> list[str]:
    """프롬프트에 넣기 전 정리(NFC, 공백)."""
    return [" ".join(unicodedata.normalize("NFC", t).split()) for t in terms if t.strip()]
