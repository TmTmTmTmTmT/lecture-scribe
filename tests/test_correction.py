"""LLM 교정 제안 (F-09) 테스트.

핵심 불변식: **원문은 절대 바뀌지 않는다.** 교정은 주석으로만 붙는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import make_segment
from lecture_scribe.correction import (
    CORRECTION_MODELS,
    CorrectionResult,
    CorrectionUnavailableError,
    OllamaClient,
    Proposal,
    annotate,
    build_prompt,
    build_sidecar,
    chunk_segments,
    consonant_skeleton,
    find_ollama,
    is_mere_transliteration,
    locate,
    ollama_available,
    propose_corrections,
    validate_proposals,
)


# --- 음차 판별 ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("original", "correction"),
    [("가우시안", "Gaussian"), ("화이트", "White"), ("채널", "Channel")],
)
def test_mere_transliteration_is_detected(original: str, correction: str) -> None:
    """올바른 한국어 음차를 영어 철자로 바꾸는 건 교정이 아니다."""
    assert is_mere_transliteration(original, correction)


@pytest.mark.parametrize(
    ("original", "correction"),
    [
        ("레일레일", "Rayleigh"),
        ("라이샤인트", "Ricean"),
        ("맥시스 필터", "Matched Filter"),
        ("아르헨타", "안테나"),
        ("파워색별", "파워 스펙트럼"),
        ("PAD", "Fading"),
    ],
)
def test_real_corrections_survive(original: str, correction: str) -> None:
    """진짜 오인식 교정은 음차 필터에 걸리면 안 된다."""
    assert not is_mere_transliteration(original, correction)


def test_final_ieung_maps_to_ng() -> None:
    """받침 ㅇ은 /ŋ/이라 영어 -ng에 대응한다. 버리면 음차 판별이 흐려진다."""
    assert consonant_skeleton("킹").endswith("g")


def test_ricean_survives_the_filter() -> None:
    """`라이샤인트 -> Ricean`은 진짜 교정이다.

    연음 c(=/s/)를 반영하면 이게 철자 변환으로 오판돼 폐기된다(실측).
    진짜 교정을 잃는 쪽이 잡음 하나 남기는 것보다 나쁘므로 c는 항상 k로 접는다.
    """
    assert not is_mere_transliteration("라이샤인트", "Ricean")


def test_hangul_to_hangul_is_never_transliteration() -> None:
    """한글->한글은 철자 변환일 수 없다."""
    assert not is_mere_transliteration("자기상황학적성", "자기상관성")


def test_consonant_skeleton_drops_vowels_and_repeats() -> None:
    assert consonant_skeleton("가우시안") == consonant_skeleton("Gaussian")
    assert "a" not in consonant_skeleton("Adaptive")


# --- 검증 --------------------------------------------------------------------


TEXT = "그래서 우리가 여기 있는 어댑티브, 화이트, 가우시안, 노이즈. 레일레일 PDF를 따른다."


def _raw(**kwargs: Any) -> dict[str, Any]:
    base = {
        "original": "레일레일",
        "correction": "Rayleigh",
        "reason": "레일리 분포",
        "confidence": "high",
    }
    base.update(kwargs)
    return base


def test_hallucinated_original_is_rejected() -> None:
    """전사문에 없는 문자열을 지어내면 버린다 — 가장 중요한 안전장치."""
    passed, rejected = validate_proposals([_raw(original="존재하지않는말")], TEXT)
    assert passed == []
    assert rejected and "환각" in rejected[0][2]


def test_identical_correction_is_rejected() -> None:
    passed, rejected = validate_proposals(
        [_raw(original="레일레일", correction="레일레일")], TEXT
    )
    assert passed == []
    assert "동일" in rejected[0][2]


def test_low_confidence_is_rejected_by_default() -> None:
    passed, rejected = validate_proposals([_raw(confidence="low")], TEXT)
    assert passed == []
    assert "신뢰도" in rejected[0][2]


def test_low_confidence_passes_when_floor_lowered() -> None:
    passed, _ = validate_proposals([_raw(confidence="low")], TEXT, min_confidence="low")
    assert len(passed) == 1


def test_transliteration_only_is_rejected() -> None:
    passed, rejected = validate_proposals(
        [_raw(original="가우시안", correction="Gaussian")], TEXT
    )
    assert passed == []
    assert "철자 변환" in rejected[0][2]


def test_overlapping_proposals_are_deduped() -> None:
    """`어댑티브`와 `어댑티브, 화이트`가 함께 오면 하나만 남는다."""
    passed, rejected = validate_proposals(
        [
            _raw(original="어댑티브", correction="애디티브"),
            _raw(original="어댑티브, 화이트", correction="애디티브, 화이트"),
        ],
        TEXT,
    )
    assert len(passed) == 1
    assert any("겹침" in r[2] for r in rejected)


def test_empty_values_rejected() -> None:
    passed, rejected = validate_proposals([_raw(original=""), _raw(correction="")], TEXT)
    assert passed == []
    assert all("빈 값" in r[2] for r in rejected)


# --- 주석 --------------------------------------------------------------------


def test_annotate_preserves_original_text() -> None:
    """원문 글자는 하나도 사라지지 않아야 한다."""
    proposals = [Proposal("레일레일", "Rayleigh", "", "high")]
    result = annotate(TEXT, proposals)
    assert "레일레일[→Rayleigh]" in result
    # 주석을 걷어내면 원문과 정확히 같다
    assert result.replace("[→Rayleigh]", "") == TEXT


def test_annotate_is_idempotent() -> None:
    proposals = [Proposal("레일레일", "Rayleigh", "", "high")]
    once = annotate(TEXT, proposals)
    assert annotate(once, proposals) == once


def test_annotate_longest_first_avoids_nesting() -> None:
    """짧은 원문이 긴 원문 안을 먼저 건드리면 주석이 깨진다."""
    proposals = [
        Proposal("어댑티브", "애디티브", "", "high"),
        Proposal("어댑티브, 화이트", "애디티브, 화이트", "", "high"),
    ]
    result = annotate(TEXT, proposals)
    assert "[→[→" not in result
    assert result.count("[→") == 2


def test_annotate_only_first_occurrence_per_proposal() -> None:
    text = "노이즈 그리고 노이즈"
    result = annotate(text, [Proposal("노이즈", "Noise", "", "high")])
    assert result.count("[→Noise]") == 1


# --- 세그먼트 연결 / 청크 ------------------------------------------------------


def test_locate_attaches_timestamps() -> None:
    segments = [
        make_segment(0, 0.0, 3.0, "안녕하세요"),
        make_segment(1, 3.0, 6.0, "레일레일 PDF를 따른다", avg_logprob=-0.42),
    ]
    located = locate([Proposal("레일레일", "Rayleigh", "근거", "high")], segments)
    assert located[0].segment_id == 1
    assert located[0].start == 3.0
    assert located[0].segment_avg_logprob == -0.42
    assert located[0].context == "레일레일 PDF를 따른다"


def test_chunk_segments_respects_boundaries() -> None:
    segments = [make_segment(i, i * 3.0, i * 3.0 + 3.0, "가" * 50) for i in range(10)]
    chunks = chunk_segments(segments, max_chars=120)
    assert len(chunks) > 1
    # 모든 세그먼트가 정확히 한 번씩 들어간다
    ids = [s.id for chunk, _ in chunks for s in chunk]
    assert sorted(ids) == list(range(10))


def test_chunk_skips_empty_segments() -> None:
    segments = [make_segment(0, 0.0, 1.0, "  "), make_segment(1, 1.0, 2.0, "내용")]
    chunks = chunk_segments(segments, max_chars=500)
    assert [s.id for chunk, _ in chunks for s in chunk] == [1]


# --- 프롬프트 -----------------------------------------------------------------


def test_prompt_includes_topic_and_glossary() -> None:
    """주제·용어집이 빠지면 같은 모델이 1/7까지 떨어진다(실측). 반드시 들어가야 한다."""
    prompt = build_prompt("본문", "전자회로 잡음", ["AWGN", "열잡음"])
    assert "전자회로 잡음" in prompt
    assert "AWGN" in prompt and "열잡음" in prompt
    assert "본문" in prompt


def test_prompt_warns_against_transliteration_noise() -> None:
    assert "제안하지 마라" in build_prompt("본문", "주제", [])


def test_prompt_without_slide_terms_is_unchanged() -> None:
    """슬라이드 용어가 없으면 프롬프트가 기존과 완전히 같아야 한다(회귀 방지)."""
    assert build_prompt("본문", "주제", ["AWGN"]) == build_prompt(
        "본문", "주제", ["AWGN"], slide_terms=()
    )
    assert "슬라이드" not in build_prompt("본문", "주제", ["AWGN"])


def test_prompt_slide_terms_go_in_separate_section() -> None:
    """OCR 용어는 '이미 확인된 용어'에 섞이지 않고 오타 가능 표시가 붙은 별도 섹션이다."""
    prompt = build_prompt("본문", "주제", ["AWGN"], slide_terms=["Rician", "Fitters"])
    known_line = next(ln for ln in prompt.splitlines() if ln.startswith("이미 확인된 용어"))
    assert "Rician" not in known_line
    slide_line = next(ln for ln in prompt.splitlines() if ln.startswith("슬라이드에서 읽은 표기"))
    assert "Rician" in slide_line and "Fitters" in slide_line
    assert "오타" in slide_line


# --- 오케스트레이션 (네트워크 없이) ---------------------------------------------


def test_propose_corrections_passes_slide_terms_and_records_them() -> None:
    client = FakeClient([[]])
    result = propose_corrections(
        [make_segment(0, 0.0, 4.0, "라이샤인트 채널")],
        "통신",
        [],
        slide_terms=["Ricean"],
        client=client,
    )
    assert "Ricean" in client.prompts[0]
    assert result.slide_terms == ["Ricean"]
    payload = build_sidecar(
        result,
        source_audio=Path("a.mov"),
        transcript_path=None,
        topic="통신",
        glossary=[],
        generated_at="2026-09-27T00:00:00",
    )
    assert payload["slide_terms_used"] == ["Ricean"]


class FakeClient(OllamaClient):
    def __init__(self, responses: list[list[dict[str, Any]]]) -> None:
        super().__init__()
        self._responses = responses
        self.prompts: list[str] = []

    def ensure_running(self, wait_sec: float = 15.0) -> None:
        return None

    def require_model(self, model: str) -> None:
        return None

    def propose(
        self, prompt: str, model: str, temperature: float = 0.2
    ) -> list[dict[str, Any]]:
        self.prompts.append(prompt)
        return self._responses.pop(0) if self._responses else []


def test_propose_corrections_end_to_end() -> None:
    segments = [make_segment(0, 0.0, 4.0, "레일레일 PDF를 따른다")]
    client = FakeClient([[_raw()]])
    result = propose_corrections(
        segments, "통신", ["AWGN"], client=client, max_chars=500
    )
    assert result.ok
    assert len(result.proposals) == 1
    assert result.proposals[0].segment_id == 0
    assert "통신" in client.prompts[0]


def test_unavailable_ollama_skips_without_raising() -> None:
    """Ollama가 없어도 예외를 올리지 않는다. 전사 결과는 살아야 한다."""

    class DeadClient(OllamaClient):
        def ensure_running(self, wait_sec: float = 15.0) -> None:
            raise CorrectionUnavailableError("Ollama 없음", "테스트")

    result = propose_corrections(
        [make_segment(0, 0.0, 1.0, "내용")], "주제", [], client=DeadClient()
    )
    assert not result.ok
    assert result.skipped_reason == "Ollama 없음"
    assert result.proposals == []


def test_empty_segments_skipped() -> None:
    result = propose_corrections([], "주제", [])
    assert not result.ok
    assert result.proposals == []


def test_cancel_stops_midway() -> None:
    segments = [make_segment(i, i * 3.0, i * 3.0 + 3.0, "가" * 80) for i in range(6)]
    client = FakeClient([[] for _ in range(6)])
    result = propose_corrections(
        segments, "주제", [], client=client, max_chars=100, should_cancel=lambda: True
    )
    assert result.skipped_reason == "사용자가 취소했습니다."
    assert client.prompts == []


def test_duplicate_across_chunks_kept_once() -> None:
    segments = [
        make_segment(0, 0.0, 3.0, "레일레일 하나"),
        make_segment(1, 3.0, 6.0, "레일레일 둘"),
    ]
    client = FakeClient([[_raw(original="레일레일")], [_raw(original="레일레일")]])
    result = propose_corrections(segments, "주제", [], client=client, max_chars=10)
    assert len(result.proposals) == 1


# --- 사이드카 -----------------------------------------------------------------


def test_sidecar_is_valid_json_with_notice() -> None:
    result = CorrectionResult(
        proposals=[
            Proposal("레일레일", "Rayleigh", "레일리 분포", "high", 1, 3.0, 6.0, "문맥", -0.4)
        ],
        rejected=[("가우시안", "Gaussian", "철자 변환일 뿐")],
        model="gemma4:e4b",
        elapsed_sec=12.3,
        chunks=2,
    )
    payload = build_sidecar(
        result,
        source_audio=Path("/tmp/a.m4a"),
        transcript_path=Path("/tmp/a.txt"),
        topic="통신",
        glossary=["AWGN"],
        generated_at="2026-09-04T12:00:00+09:00",
    )
    dumped = json.loads(json.dumps(payload, ensure_ascii=False))
    assert dumped["schema"] == "lecture-scribe/corrections/v1"
    # 읽는 쪽이 "이건 추정"임을 알아야 한다
    assert "수정되지 않았습니다" in dumped["notice"]
    assert "확정 사실이 아닙니다" in dumped["notice"]
    entry = dumped["corrections"][0]
    assert entry["original"] == "레일레일"
    assert entry["segment_avg_logprob"] == -0.4
    assert dumped["stats"]["accepted"] == 1
    assert dumped["stats"]["by_confidence"]["high"] == 1
    assert dumped["rejected_samples"][0]["reason"] == "철자 변환일 뿐"


def test_list_installed_gemma_models_filters_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lecture_scribe import correction as correction_mod

    monkeypatch.setattr(correction_mod, "ollama_available", lambda: True)

    class _Client:
        def alive(self, timeout: float = 1.0) -> bool:
            return True

        def models(self) -> list[str]:
            return ["gemma4:e4b", "llama3:8b", "gemma3:12b", "gemma4:e2b"]

    assert correction_mod.list_installed_gemma_models(_Client()) == [  # type: ignore[arg-type]
        "gemma3:12b",
        "gemma4:e2b",
        "gemma4:e4b",
    ]


def test_list_installed_gemma_models_empty_when_ollama_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lecture_scribe import correction as correction_mod

    monkeypatch.setattr(correction_mod, "ollama_available", lambda: False)
    assert correction_mod.list_installed_gemma_models() == []


def test_list_installed_gemma_models_empty_when_daemon_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lecture_scribe import correction as correction_mod

    monkeypatch.setattr(correction_mod, "ollama_available", lambda: True)

    class _Client:
        def alive(self, timeout: float = 1.0) -> bool:
            return False

    assert correction_mod.list_installed_gemma_models(_Client()) == []  # type: ignore[arg-type]


def test_models_are_selectable() -> None:
    assert "gemma4:e4b" in CORRECTION_MODELS
    assert "gemma4:e2b" in CORRECTION_MODELS


def test_require_model_accepts_latest_tag_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    """`gemma4:e4b`와 `gemma4:e4b:latest`는 같은 모델로 봐야 한다."""
    client = OllamaClient()
    monkeypatch.setattr(client, "models", lambda: ["gemma4:e4b:latest"])
    client.require_model("gemma4:e4b")  # 예외 없이 통과해야 한다


def test_require_model_rejects_sibling_variant(monkeypatch: pytest.MonkeyPatch) -> None:
    """실측 버그: e2b만 설치돼 있어도 e4b 요구가 (같은 'gemma4' 스템이라) 통과해버렸다.

    `gemma4:e4b`와 `gemma4:e2b`는 서로 다른 모델이다 — 첫 콜론까지만 자르면
    안 된다.
    """
    client = OllamaClient()
    monkeypatch.setattr(client, "models", lambda: ["gemma4:e2b:latest"])
    with pytest.raises(CorrectionUnavailableError):
        client.require_model("gemma4:e4b")


# --- 모델 수명주기 -------------------------------------------------------------


def test_model_stays_loaded_across_chunks_then_released() -> None:
    """구간마다 모델을 내렸다 올리면 로드 비용(e4b 7.7초)이 구간 수만큼 붙는다.

    도는 동안은 붙잡아 두고, 끝난 뒤 정확히 한 번 내려야 한다.
    """
    calls: list[Any] = []

    class TracingClient(OllamaClient):
        def ensure_running(self, wait_sec: float = 15.0) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def propose(
            self,
            prompt: str,
            model: str,
            temperature: float = 0.2,
            keep_alive: str | int = "5m",
        ) -> list[dict[str, Any]]:
            calls.append(("propose", keep_alive))
            return []

        def release(self, model: str) -> None:
            calls.append(("release", model))

    segments = [make_segment(i, i * 3.0, i * 3.0 + 3.0, "가" * 80) for i in range(6)]
    result = propose_corrections(segments, "주제", [], client=TracingClient(), max_chars=100)

    proposes = [c for c in calls if c[0] == "propose"]
    releases = [c for c in calls if c[0] == "release"]
    assert len(proposes) == result.chunks > 1
    assert all(c[1] != 0 for c in proposes), "구간 중에 모델을 내리면 안 된다"
    assert len(releases) == 1, "끝난 뒤 정확히 한 번 내려야 한다"
    assert calls[-1][0] == "release", "해제가 마지막이어야 한다"


def test_release_failure_does_not_break_result() -> None:
    """해제 실패가 교정 결과를 망치면 안 된다."""

    class BadRelease(OllamaClient):
        def ensure_running(self, wait_sec: float = 15.0) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def propose(
            self,
            prompt: str,
            model: str,
            temperature: float = 0.2,
            keep_alive: str | int = "5m",
        ) -> list[dict[str, Any]]:
            return [_raw(original="레일레일")]

        def release(self, model: str) -> None:
            raise CorrectionUnavailableError("해제 실패", "테스트")

    result = propose_corrections(
        [make_segment(0, 0.0, 3.0, "레일레일 PDF")], "주제", [], client=BadRelease()
    )
    assert result.ok
    assert len(result.proposals) == 1


def test_cancel_also_releases_model() -> None:
    released: list[str] = []

    class C(OllamaClient):
        def ensure_running(self, wait_sec: float = 15.0) -> None:
            return None

        def require_model(self, model: str) -> None:
            return None

        def release(self, model: str) -> None:
            released.append(model)

    propose_corrections(
        [make_segment(0, 0.0, 3.0, "내용")],
        "주제",
        [],
        client=C(),
        should_cancel=lambda: True,
    )
    assert released == ["gemma4:e4b"], "취소해도 모델은 내려야 한다"


# --- 엔진 통합: 원문 보존 불변식 -------------------------------------------------


def test_engine_annotates_without_losing_original(tmp_path: Path) -> None:
    """엔진이 붙인 주석을 걷어내면 원문 세그먼트와 정확히 같아야 한다."""
    from dataclasses import replace as dc_replace

    from lecture_scribe.config import Settings
    from lecture_scribe.engine import FileResult, _annotate_segments

    segments = [
        make_segment(0, 0.0, 3.0, "레일레일 PDF를 따른다"),
        make_segment(1, 3.0, 6.0, "건드리지 않을 문장"),
    ]
    result = FileResult(audio_path=tmp_path / "a.m4a", status="ok")
    result.llm_corrections = CorrectionResult(
        proposals=[Proposal("레일레일", "Rayleigh", "근거", "high", 0)],
        model="gemma4:e4b",
    )
    settings = Settings()
    settings = dc_replace(
        settings, correction=dc_replace(settings.correction, annotate_transcript=True)
    )

    annotated = _annotate_segments(segments, result, settings)
    assert annotated is not None
    assert annotated[0].text == "레일레일[→Rayleigh] PDF를 따른다"
    assert annotated[0].text.replace("[→Rayleigh]", "") == segments[0].text
    assert annotated[1].text == segments[1].text
    # 타임스탬프·신뢰도 등 나머지 필드는 그대로
    assert annotated[0].start == segments[0].start
    assert annotated[0].avg_logprob == segments[0].avg_logprob


def test_engine_skips_annotation_when_disabled(tmp_path: Path) -> None:
    from dataclasses import replace as dc_replace

    from lecture_scribe.config import Settings
    from lecture_scribe.engine import FileResult, _annotate_segments

    result = FileResult(audio_path=tmp_path / "a.m4a", status="ok")
    result.llm_corrections = CorrectionResult(
        proposals=[Proposal("레일레일", "Rayleigh", "", "high", 0)]
    )
    settings = Settings()
    settings = dc_replace(
        settings, correction=dc_replace(settings.correction, annotate_transcript=False)
    )
    assert _annotate_segments([make_segment(0, 0.0, 3.0, "레일레일")], result, settings) is None


def test_engine_no_corrections_means_no_annotation(tmp_path: Path) -> None:
    from lecture_scribe.config import Settings
    from lecture_scribe.engine import FileResult, _annotate_segments

    result = FileResult(audio_path=tmp_path / "a.m4a", status="ok")
    assert _annotate_segments([make_segment(0, 0.0, 3.0, "내용")], result, Settings()) is None


# --- ollama 탐색: PATH가 부족한 번들 프로세스에서도 찾아야 한다 ------------------


def test_find_ollama_works_without_homebrew_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """실측: GUI 번들 프로세스 PATH는 `/usr/bin:/bin:/usr/sbin:/sbin`뿐이라
    Homebrew로 설치된 `ollama`(보통 `/opt/homebrew/bin`)를 `shutil.which`만으론
    못 찾는다. 실제 설치 경로가 있으면(개발 환경) 고정 경로 탐색으로 찾아야 한다.
    """
    import shutil

    real = shutil.which("ollama")
    if real is None:
        pytest.skip("이 머신에 ollama가 설치돼 있지 않음")

    monkeypatch.setenv("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    found = find_ollama()
    assert found is not None
    assert found.name == "ollama"
    assert ollama_available() is True


def test_find_ollama_none_when_not_installed_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from lecture_scribe import correction as correction_mod

    monkeypatch.setattr(correction_mod, "_OLLAMA_SEARCH_DIRS", ())
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert find_ollama() is None
    assert ollama_available() is False


def test_prompt_targets_korean_misrecognitions_too() -> None:
    """P-01 g: 영어 전문용어뿐 아니라 일반 한글 오인식도 대상이라고 명시해야 한다."""
    prompt = build_prompt("본문", "주제", [])
    assert "일반 한국어" in prompt


def test_prompt_context_is_reference_only_and_optional() -> None:
    """P-01 e: 문맥은 참고용으로만 표시되고, 없으면 섹션 자체가 안 들어간다(회귀 방지)."""
    without = build_prompt("본문", "주제", ["AWGN"])
    assert "앞뒤 문맥" not in without

    with_ctx = build_prompt(
        "본문", "주제", ["AWGN"], context_before=["앞 문장"], context_after=["뒤 문장"]
    )
    assert "앞 문장" in with_ctx and "뒤 문장" in with_ctx
    assert "original로 쓰지 마라" in with_ctx


def test_propose_corrections_passes_neighbor_chunk_context() -> None:
    """청크 여러 개일 때 각 청크 프롬프트에 이웃 청크의 문맥이 들어가야 한다."""
    segments = [
        make_segment(0, 0.0, 1.0, "가" * 50),
        make_segment(1, 1.0, 2.0, "이것은 앞 청크의 마지막 문장이다"),
        make_segment(2, 2.0, 3.0, "나" * 50),
        make_segment(3, 3.0, 4.0, "이것은 뒤 청크의 첫 문장이다"),
    ]
    client = FakeClient([[], []])
    propose_corrections(segments, "주제", [], client=client, max_chars=70)
    assert len(client.prompts) == 2
    assert "이것은 뒤 청크의 첫 문장이다" in client.prompts[0]
    assert "이것은 앞 청크의 마지막 문장이다" in client.prompts[1]
