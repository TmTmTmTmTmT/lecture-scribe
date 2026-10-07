"""postprocess.py — 용어 교정, 반복 감지, 붕괴 감지 (F-03-4, F-04)."""

from __future__ import annotations

import pytest

from conftest import make_segment
from lecture_scribe.postprocess import (
    apply_corrections,
    apply_fuzzy_corrections,
    build_header_notes,
    detect_collapse,
    find_foreign_script_runs,
    find_repeat_runs,
    foreign_script_segment_ids,
    foreign_script_stats,
    fuzzy_available,
    is_foreign_script_segment,
    normalize_for_compare,
)


# --- 정확 매칭 교정 ------------------------------------------------------


def test_exact_corrections_replace_and_count() -> None:
    segments = [
        make_segment(0, 0, 2, "스미스차트를 봅시다."),
        make_segment(1, 2, 4, "스미스차트와 에스파라미터."),
    ]
    result = apply_corrections(
        segments, {"스미스차트": "스미스 차트", "에스파라미터": "S-parameter"}
    )
    assert result.segments[0].text == "스미스 차트를 봅시다."
    assert result.segments[1].text == "스미스 차트와 S-parameter."
    entries = {(e.source, e.target): e.count for e in result.log}
    assert entries[("스미스차트", "스미스 차트")] == 2
    assert entries[("에스파라미터", "S-parameter")] == 1
    assert result.total_count == 3


def test_exact_corrections_longest_key_first() -> None:
    segments = [make_segment(0, 0, 1, "특성임피던스 값")]
    result = apply_corrections(
        segments, {"임피던스": "임피던스", "특성임피던스": "특성 임피던스"}
    )
    assert result.segments[0].text == "특성 임피던스 값"


def test_exact_corrections_noop_keeps_identity() -> None:
    segments = [make_segment(0, 0, 1, "변화 없음")]
    result = apply_corrections(segments, {})
    assert result.segments == segments
    assert result.log == []


def test_correction_entry_format() -> None:
    result = apply_corrections(
        [make_segment(0, 0, 1, "스미스차트")], {"스미스차트": "스미스 차트"}
    )
    assert result.log[0].format() == "스미스차트 → 스미스 차트 (1회, 정확)"


# --- 유사도 교정 ---------------------------------------------------------


@pytest.mark.skipif(not fuzzy_available(), reason="rapidfuzz 미설치")
def test_fuzzy_correction_fixes_near_miss() -> None:
    segments = [make_segment(0, 0, 2, "임피던스 정함을 설명합니다")]
    result = apply_fuzzy_corrections(segments, ["임피던스 정합"], threshold=80)
    assert "임피던스 정합" in result.segments[0].text
    assert result.log[0].fuzzy is True


@pytest.mark.skipif(not fuzzy_available(), reason="rapidfuzz 미설치")
def test_fuzzy_correction_leaves_exact_matches_alone() -> None:
    segments = [make_segment(0, 0, 2, "임피던스 정합 설명")]
    result = apply_fuzzy_corrections(segments, ["임피던스 정합"], threshold=80)
    assert result.log == []
    assert result.segments[0].text == "임피던스 정합 설명"


@pytest.mark.skipif(not fuzzy_available(), reason="rapidfuzz 미설치")
def test_fuzzy_correction_ignores_unrelated_words() -> None:
    segments = [make_segment(0, 0, 2, "오늘 날씨가 좋습니다")]
    result = apply_fuzzy_corrections(segments, ["임피던스 정합"], threshold=88)
    assert result.segments[0].text == "오늘 날씨가 좋습니다"


def test_fuzzy_with_empty_glossary_is_noop() -> None:
    segments = [make_segment(0, 0, 1, "그대로")]
    assert apply_fuzzy_corrections(segments, []).segments == segments


# --- 반복 감지 -----------------------------------------------------------


def test_find_repeat_runs() -> None:
    segments = [
        make_segment(0, 0, 2, "시청해주셔서 감사합니다."),
        make_segment(1, 2, 4, "시청해주셔서 감사합니다."),
        make_segment(2, 4, 6, "시청해주셔서 감사합니다."),
        make_segment(3, 6, 8, "다음 내용입니다."),
    ]
    runs = find_repeat_runs(segments, min_count=3)
    assert len(runs) == 1
    assert runs[0].count == 3
    assert runs[0].start == 0.0 and runs[0].end == 6.0
    assert "00:00:00" in runs[0].describe()


def test_find_repeat_runs_below_threshold() -> None:
    segments = [
        make_segment(0, 0, 2, "같은 문장"),
        make_segment(1, 2, 4, "같은 문장"),
    ]
    assert find_repeat_runs(segments, min_count=3) == []


def test_repeat_detection_ignores_punctuation_differences() -> None:
    segments = [
        make_segment(0, 0, 2, "감사합니다."),
        make_segment(1, 2, 4, " 감사합니다 "),
        make_segment(2, 4, 6, "감사합니다!"),
    ]
    assert len(find_repeat_runs(segments, min_count=3)) == 1


def test_normalize_for_compare() -> None:
    assert normalize_for_compare(" 감사 합니다! ") == "감사합니다"


# --- 붕괴 감지 -----------------------------------------------------------


def test_detect_collapse_empty_output() -> None:
    assert detect_collapse([], 60.0) == "출력이 비어 있음"


def test_detect_collapse_short_audio_is_skipped() -> None:
    assert detect_collapse([], 3.0) is None


def test_detect_collapse_prompt_echo() -> None:
    prompt = "이번 시간에는 임피던스 정합과 스미스 차트를 다룹니다."
    segments = [make_segment(0, 0, 20, prompt)]
    reason = detect_collapse(segments, 600.0, initial_prompt=prompt)
    assert reason is not None


def test_detect_collapse_repetition() -> None:
    segments = [make_segment(i, i * 2, i * 2 + 2, "감사합니다.") for i in range(10)]
    reason = detect_collapse(segments, 20.0)
    assert reason is not None and "반복 붕괴" in reason


def test_detect_collapse_normal_output_returns_none() -> None:
    segments = [
        make_segment(0, 0, 5, "오늘은 임피던스 정합에 대해 알아보겠습니다."),
        make_segment(1, 5, 10, "반사계수는 감마로 표기하며 크기는 1보다 작습니다."),
        make_segment(2, 10, 15, "스미스 차트를 이용하면 계산이 쉬워집니다."),
    ]
    assert detect_collapse(segments, 15.0) is None


def test_detect_collapse_low_output_volume() -> None:
    segments = [make_segment(0, 0, 2, "네.")]
    reason = detect_collapse(segments, 600.0)
    assert reason is not None and "출력량" in reason


# --- 헤더 주석 -----------------------------------------------------------


def test_build_header_notes() -> None:
    segments = [make_segment(i, i * 2, i * 2 + 2, "반복") for i in range(4)]
    runs = find_repeat_runs(segments, min_count=3)
    result = apply_corrections(
        [make_segment(0, 0, 1, "스미스차트")], {"스미스차트": "스미스 차트"}
    )
    notes = build_header_notes(runs, result.log, include_corrections=True)
    assert any("반복" in n for n in notes)
    assert any("용어 교정" in n for n in notes)


# --- 앞 구간 누락 감지 ---------------------------------------------------


def test_detect_head_loss_flags_missing_opening() -> None:
    from lecture_scribe.postprocess import detect_head_loss

    segments = [make_segment(0, 26.8, 30.0, "잡음이라고 하는 것은")]
    reason = detect_head_loss(segments, first_speech_sec=1.6)
    assert reason is not None and "25.2초 누락" in reason


def test_detect_head_loss_within_tolerance() -> None:
    from lecture_scribe.postprocess import detect_head_loss

    segments = [make_segment(0, 3.0, 6.0, "정상 시작")]
    assert detect_head_loss(segments, first_speech_sec=1.6) is None


def test_detect_head_loss_no_segments() -> None:
    from lecture_scribe.postprocess import detect_head_loss

    assert detect_head_loss([], first_speech_sec=1.6) is None


# --- 붕괴 감지 강화 (한국어 파인튜닝 모델 실측 기반) -----------------------


def test_detect_collapse_uses_speech_duration() -> None:
    """무음이 긴 녹음에서 오탐 없이, 실제 붕괴는 잡아야 한다."""
    from lecture_scribe.postprocess import detect_collapse

    # 90초 파일 중 발화 60초인데 22자만 나옴 -> 붕괴
    segments = [make_segment(0, 0, 90, "이 아홉 명의 발언은 이어지고 있다")]
    reason = detect_collapse(segments, 90.0, speech_duration_sec=60.0)
    assert reason is not None and "출력량 비정상" in reason

    # 같은 파일인데 발화가 3초뿐이면(대부분 무음) 오탐하지 않는다
    assert detect_collapse(segments, 90.0, speech_duration_sec=3.0) is None


def test_detect_collapse_normal_korean_speech_rate() -> None:
    """정상 한국어 강의는 초당 5~10자다. 오탐하면 안 된다."""
    from lecture_scribe.postprocess import detect_collapse

    text = "저희가 결제 요청서 제출해주시면 사업단에서 결제하도록 하겠습니다. " * 6
    segments = [make_segment(0, 0, 60, text)]
    assert detect_collapse(segments, 60.0, speech_duration_sec=55.0) is None


def test_find_repeated_phrases_in_single_segment() -> None:
    """붕괴한 모델은 한 세그먼트 안에서 같은 어절을 반복한다(실측)."""
    from lecture_scribe.postprocess import find_repeated_phrases

    found = find_repeated_phrases("결재 확보 확보 확보 확보 확보 확보 되었다")
    assert found is not None
    word, count = found
    assert word == "확보" and count == 6
    assert find_repeated_phrases("정상적인 문장입니다 반복이 없습니다") is None


def test_detect_collapse_catches_intra_segment_loop() -> None:
    """출력량은 충분한데 한 구간이 반복 루프에 빠진 경우."""
    from lecture_scribe.postprocess import detect_collapse

    filler = "저희가 결제 요청서 제출해주시면 사업단에서 처리하도록 하겠습니다. " * 4
    segments = [
        make_segment(0, 0, 60, filler + "확보 확보 확보 확보 확보 확보 확보 확보")
    ]
    reason = detect_collapse(segments, 60.0, speech_duration_sec=55.0)
    assert reason is not None and "반복 루프" in reason


# --- 용어 자동 추천 -------------------------------------------------------


def test_suggest_glossary_strips_particles() -> None:
    from lecture_scribe.postprocess import strip_particle

    assert strip_particle("우리가") == "우리"
    assert strip_particle("안테나는") == "안테나"
    assert strip_particle("네트워크에서") == "네트워크"
    assert strip_particle("잡음") == "잡음"  # 조사 없음


def test_suggest_glossary_picks_domain_terms() -> None:
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [
        make_segment(i, i * 10, i * 10 + 5,
                     "안테나의 지향성과 네트워크 데이터를 이렇게 보겠습니다", -0.3)
        for i in range(5)
    ]
    terms = [w for w, _ in suggest_glossary_terms(segments)]
    assert "안테나" in terms
    assert "네트워크" in terms
    assert "데이터" in terms
    # 부사·기능어는 빠진다
    assert "이렇게" not in terms
    assert "우리가" not in terms


def test_suggest_glossary_ignores_low_confidence() -> None:
    """잘못 인식된 단어를 용어집에 넣으면 다음 전사에서 오류가 고착된다(실측)."""
    from lecture_scribe.postprocess import suggest_glossary_terms

    bad = [make_segment(i, i, i + 1, "가우션경로 가우션경로", -1.5) for i in range(5)]
    assert suggest_glossary_terms(bad) == []


def test_suggest_glossary_excludes_existing() -> None:
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [
        make_segment(i, i * 10, i * 10 + 5, "안테나와 네트워크 이야기", -0.3)
        for i in range(5)
    ]
    terms = [w for w, _ in suggest_glossary_terms(segments, existing=["안테나"])]
    assert "안테나" not in terms
    assert "네트워크" in terms


def test_suggest_glossary_needs_multiple_segments() -> None:
    """한 구간에서만 반복된 단어는 후보로 올리지 않는다."""
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [make_segment(0, 0, 5, "안테나 안테나 안테나 안테나", -0.3)]
    assert suggest_glossary_terms(segments) == []


def test_suggest_glossary_keeps_latin_terms() -> None:
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [
        make_segment(i, i * 10, i * 10 + 5, f"CDMA 방식과 LTE 비교 {i}", -0.3)
        for i in range(4)
    ]
    terms = [w for w, _ in suggest_glossary_terms(segments)]
    assert "CDMA" in terms and "LTE" in terms


def test_suggest_glossary_excludes_short_particle_and_conjugation_noise() -> None:
    """FIX_GUIDE_14 G-01: 실제 프리셋 용어집에 섞여 있던 잡음 재현.

    `이만큼`(짧은 지시어+조사), `설명할`/`나타낸`/`커질수록`(관형형·연결형 어미)은
    길이 조건 때문에 기존 필터를 통과했었다.
    """
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [
        make_segment(
            i, i * 10, i * 10 + 5,
            "이만큼 설명할 내용이 나타낸 그림처럼 커질수록 컨스텔레이션이 중요하다",
            -0.3,
        )
        for i in range(4)
    ]
    terms = [w for w, _ in suggest_glossary_terms(segments)]
    assert not ({"이만큼", "설명할", "나타낸", "커질수록"} & set(terms))
    assert "컨스텔레이션" in terms  # 실제 용어는 남는다


def test_suggest_glossary_excludes_verb_conjugation_variants() -> None:
    """FIX_GUIDE_14 G-01: 프리셋 통계 파일에서 발견된 그 외 활용형 잡음."""
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [
        make_segment(
            i, i * 10, i * 10 + 5,
            "그래프를 만들어 보면 값이 바뀌어 있는데 사실 아니라 다시 맞나요 생각해봐 가는거 확인",
            -0.3,
        )
        for i in range(4)
    ]
    terms = [w for w, _ in suggest_glossary_terms(segments)]
    noise = {"만들어", "바뀌어", "아니라", "맞나요", "생각해봐", "가는거"}
    assert not (noise & set(terms))


def test_suggest_glossary_excludes_english_chatter_and_hallucination_words() -> None:
    """FIX_GUIDE_14 G-01: 짧은 일상어와 5글자 이상 환각 잡담어를 함께 거른다.

    실제 프리셋 통계 파일에 `going`/`stop`/`here`/`to`/`sorry`가 전부 섞여 있었다
    (Whisper 환각 구간에서 나온 것으로 추정).
    """
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [
        make_segment(
            i, i * 10, i * 10 + 5,
            "going stop here to sorry eigenvalue eigenvalue channel channel",
            -0.3,
        )
        for i in range(4)
    ]
    terms = [w for w, _ in suggest_glossary_terms(segments)]
    assert not ({"going", "stop", "here", "to", "sorry"} & {t.lower() for t in terms})
    assert "eigenvalue" in {t.lower() for t in terms}  # 5글자 이상 실제 용어는 유지


def test_suggest_glossary_keeps_acronyms_and_alphanumeric_short_words() -> None:
    """짧아도 대문자 연속이나 숫자가 섞이면(약어·기호) 그대로 인정한다."""
    from lecture_scribe.postprocess import suggest_glossary_terms

    segments = [
        make_segment(i, i * 10, i * 10 + 5, "AWGN 채널에서 h1 값과 QAM 방식", -0.3)
        for i in range(4)
    ]
    terms = [w for w, _ in suggest_glossary_terms(segments)]
    assert "AWGN" in terms and "h1" in terms and "QAM" in terms


# --- 기대 언어 밖 문자 검출 (FIX_GUIDE_5.md B-02) -------------------------


def test_foreign_script_stats_pure_korean_is_zero() -> None:
    assert foreign_script_stats("안녕하세요 오늘 강의를 시작합니다") == (0, 15)


def test_foreign_script_stats_pure_english_is_zero() -> None:
    foreign, total = foreign_script_stats("This is a normal English sentence")
    assert foreign == 0
    assert total > 0


def test_foreign_script_stats_counts_han_characters() -> None:
    foreign, total = foreign_script_stats("이건 自然科學 강의입니다")
    assert foreign == 4  # 自然科學
    assert total == foreign + len("이건강의입니다")


def test_foreign_script_stats_counts_kana() -> None:
    foreign, total = foreign_script_stats("自然に思い出す")
    assert foreign == total  # 전부 가나/한자


def test_foreign_script_stats_ignores_punctuation_and_space() -> None:
    foreign, total = foreign_script_stats("안녕, 하세요!  반갑습니다.")
    assert foreign == 0
    assert total == len("안녕하세요반갑습니다")


def test_is_foreign_script_segment_true_for_han_block() -> None:
    segment = make_segment(0, 0, 2, "自然科學的方法論")
    assert is_foreign_script_segment(segment) is True


def test_is_foreign_script_segment_false_for_normal_korean() -> None:
    segment = make_segment(0, 0, 2, "오늘은 임피던스 정합을 배웁니다")
    assert is_foreign_script_segment(segment) is False


def test_is_foreign_script_segment_false_for_single_hanja_in_normal_sentence() -> None:
    """정상 문장에 한자 한 자만 섞이면(예: 표기 확인) 오탐하지 않는다."""
    segment = make_segment(0, 0, 2, "이 한자는 中 이라고 씁니다 발음은 중입니다")
    assert is_foreign_script_segment(segment, ratio=0.3, min_count=2) is False


def test_is_foreign_script_segment_respects_min_count() -> None:
    """비율은 100%여도 개수가 min_count 미만이면 오탐 방지 위해 걸리지 않는다."""
    segment = make_segment(0, 0, 1, "中")
    assert is_foreign_script_segment(segment, ratio=0.3, min_count=2) is False


def test_is_foreign_script_segment_empty_text_is_false() -> None:
    segment = make_segment(0, 0, 1, "")
    assert is_foreign_script_segment(segment) is False


def test_find_foreign_script_runs_groups_consecutive_segments() -> None:
    segments = [
        make_segment(0, 0, 2, "정상적인 한국어 문장입니다"),
        make_segment(1, 2, 4, "自然に思い出す。"),
        make_segment(2, 4, 6, "自然に思い出す。"),
        make_segment(3, 6, 8, "다시 정상으로 돌아왔습니다"),
    ]
    runs = find_foreign_script_runs(segments)
    assert len(runs) == 1
    assert runs[0].count == 2
    assert runs[0].start == 2.0 and runs[0].end == 6.0
    assert runs[0].segment_ids == (1, 2)
    assert "기대 언어 밖 문자" in runs[0].describe()


def test_find_foreign_script_runs_none_when_clean() -> None:
    segments = [make_segment(i, i, i + 1, "정상 한국어 문장") for i in range(3)]
    assert find_foreign_script_runs(segments) == []


def test_foreign_script_segment_ids_flattens_runs() -> None:
    segments = [
        make_segment(5, 0, 2, "自然科學的方法"),
        make_segment(6, 2, 4, "自然科學的方法"),
    ]
    runs = find_foreign_script_runs(segments)
    assert foreign_script_segment_ids(runs) == frozenset({5, 6})


def test_build_header_notes_includes_foreign_runs() -> None:
    segments = [
        make_segment(0, 0, 2, "自然科學的方法"),
        make_segment(1, 2, 4, "自然科學的方法"),
    ]
    runs = find_foreign_script_runs(segments)
    notes = build_header_notes([], [], foreign_runs=runs)
    assert any("기대 언어 밖 문자" in n for n in notes)
