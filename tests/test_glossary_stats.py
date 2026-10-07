"""FIX_GUIDE_7.md E-01: glossary_stats.py 순수 함수 테스트."""

from __future__ import annotations

import json
from pathlib import Path

from lecture_scribe.glossary_stats import (
    DECAY,
    FLOOR,
    PresetGlossaryStats,
    load_stats,
    order_glossary,
    save_stats,
    update_scores,
)


def test_update_scores_decays_existing_and_adds_new() -> None:
    existing = {"임피던스": 4.0}
    detected = [("임피던스", 2), ("스미스차트", 3)]
    result = update_scores(existing, detected, decay=0.8, floor=0.1)
    assert result["임피던스"] == 4.0 * 0.8 + 2
    assert result["스미스차트"] == 3.0


def test_update_scores_repeated_appearance_raises_score() -> None:
    """연속으로 계속 나오면 점수가 오른다."""
    score = 0.0
    for _ in range(5):
        score = update_scores({"용어": score}, [("용어", 3)]).get("용어", 0.0)
    assert score > 3.0


def test_update_scores_absence_lowers_score_each_round() -> None:
    """안 나오면 회차마다 줄어든다."""
    scores = {"용어": 10.0}
    prev = 10.0
    for _ in range(3):
        scores = update_scores(scores, [])
        assert scores.get("용어", 0.0) < prev
        prev = scores.get("용어", 0.0)


def test_update_scores_removes_terms_below_floor() -> None:
    """바닥값 아래로 내려간 용어는 사라진다."""
    scores = {"희귀어": 0.15}
    for _ in range(5):
        scores = update_scores(scores, [])
    assert "희귀어" not in scores


def test_order_glossary_keeps_user_order_and_sorts_auto_by_score() -> None:
    user_terms = ["나중에넣음", "먼저넣음"]  # 순서 그대로 유지돼야 함
    auto_terms = ["낮은점수", "높은점수", "중간점수"]
    scores = {"낮은점수": 1.0, "높은점수": 9.0, "중간점수": 5.0}
    result = order_glossary(user_terms, auto_terms, scores)
    assert result == ["나중에넣음", "먼저넣음", "높은점수", "중간점수", "낮은점수"]


def test_order_glossary_unscored_auto_term_treated_as_zero() -> None:
    result = order_glossary([], ["a", "b"], {"a": 1.0})
    assert result == ["a", "b"]


def test_load_stats_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_stats(tmp_path / "없음.json") == {}


def test_load_stats_corrupt_file_returns_empty_not_raises(tmp_path: Path) -> None:
    path = tmp_path / "glossary_stats.json"
    path.write_text("{이건 JSON이 아님", encoding="utf-8")
    assert load_stats(path) == {}


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "glossary_stats.json"
    stats = {
        "전자회로": PresetGlossaryStats(
            scores={"임피던스": 4.2}, auto_added={"임피던스", "스미스차트"}
        )
    }
    save_stats(stats, path)
    loaded = load_stats(path)
    assert loaded["전자회로"].scores == {"임피던스": 4.2}
    assert loaded["전자회로"].auto_added == {"임피던스", "스미스차트"}


def test_save_stats_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "glossary_stats.json"
    save_stats({"a": PresetGlossaryStats()}, path)
    assert path.exists()


def test_saved_json_is_utf8_readable(tmp_path: Path) -> None:
    path = tmp_path / "glossary_stats.json"
    save_stats({"한글프리셋": PresetGlossaryStats(scores={"한글용어": 1.0})}, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "한글프리셋" in raw["presets"]
    assert "\\u" not in path.read_text(encoding="utf-8")


def test_load_stats_ignores_malformed_preset_entry(tmp_path: Path) -> None:
    """한 프리셋 항목이 깨져도 나머지는 읽힌다."""
    path = tmp_path / "glossary_stats.json"
    path.write_text(
        json.dumps(
            {
                "presets": {
                    "정상": {"scores": {"a": 1.0}, "auto_added": ["a"]},
                    "깨짐": {"scores": "이건 dict가 아님", "auto_added": []},
                }
            }
        ),
        encoding="utf-8",
    )
    result = load_stats(path)
    assert "정상" in result
    assert result["정상"].scores == {"a": 1.0}


def test_default_constants_are_sane() -> None:
    assert 0.0 < DECAY < 1.0
    assert 0.0 < FLOOR
