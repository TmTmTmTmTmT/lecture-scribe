"""교정 평가 채점 (FIX_GUIDE_13 E-01).

교정 결과(`corrections.json` 형식 또는 Proposal 리스트)를 정답 목록과 비교한다.

정답 파일 형식(gold_*.json):
{
  "gold":      [{"original": "...", "expected": "...", "kind": "..."}],
  "negatives": [{"original": "...", "note": "..."}]   # 교정하면 안 되는 곳
}

판정:
- 정답(hit):  제안의 original이 gold.original과 전사문에서 같은 자리를 겹치고, correction이 expected와 정규화 일치(포함)
- 오답(wrong): 제안이 gold.original을 건드렸지만 correction이 expected와 다름
- 누락(miss): gold 항목에 해당 제안이 없음
- 오교정(neg): 제안의 original이 negatives.original과 포함관계
- 표기(fmt): 대소문자·밑줄만 다른 제안 — 집계 제외
- 기타(other): 위 어디에도 안 걸리는 제안(정답 목록에 없는 교정 — 사람이 따로 판단)
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def norm(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[\s\-_.,·]+", "", text)


def overlaps(a: str, b: str) -> bool:
    """교정문(correction) vs 기대값(expected) 비교용: 정규화 후 포함관계."""
    na, nb = norm(a), norm(b)
    return bool(na) and bool(nb) and (na in nb or nb in na)


def spans(text: str, needle: str) -> list[tuple[int, int]]:
    """전사문에서 needle이 나오는 모든 위치(대소문자 구분, 글자 그대로)."""
    out: list[tuple[int, int]] = []
    start = text.find(needle)
    while needle and start != -1:
        out.append((start, start + len(needle)))
        start = text.find(needle, start + 1)
    return out


def span_overlap(text: str, a: str, b: str) -> bool:
    """두 문자열이 전사문 안에서 같은 자리를 (일부라도) 겹쳐 가리키는지.

    부분 문자열 비교는 `Wn`이 `AWN`에 걸리는 식의 오탐이 난다. 위치로 비교한다.
    """
    sa, sb = spans(text, a), spans(text, b)
    return any(x0 < y1 and y0 < x1 for x0, x1 in sa for y0, y1 in sb)


def is_format_only(original: str, correction: str) -> bool:
    """표기만 바꾼 제안(대소문자, 밑줄, 공백, 하이픈) — ASR 오류 교정이 아니므로 집계에서 뺀다."""
    def key(t: str) -> str:
        return re.sub(r"[\s_\-$\\{}]+", "", unicodedata.normalize("NFC", t).lower())
    return key(original) == key(correction)


@dataclass
class Score:
    hit: list[str] = field(default_factory=list)
    wrong: list[str] = field(default_factory=list)
    miss: list[str] = field(default_factory=list)
    neg: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    fmt: list[str] = field(default_factory=list)
    proposals: int = 0
    elapsed_sec: float = 0.0

    @property
    def precision(self) -> float:
        counted = len(self.hit) + len(self.wrong) + len(self.neg) + len(self.other)
        return len(self.hit) / counted if counted else 0.0

    @property
    def recall(self) -> float:
        total = len(self.hit) + len(self.wrong) + len(self.miss)
        return len(self.hit) / total if total else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "proposals": self.proposals,
            "hit": len(self.hit),
            "wrong": len(self.wrong),
            "miss": len(self.miss),
            "neg": len(self.neg),
            "other": len(self.other),
            "fmt": len(self.fmt),
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "elapsed_sec": round(self.elapsed_sec, 1),
        }


def load_gold(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def score(
    proposals: list[dict[str, str]],
    gold: dict[str, Any],
    text: str,
    elapsed_sec: float = 0.0,
) -> Score:
    result = Score(proposals=len(proposals), elapsed_sec=elapsed_sec)
    matched_gold: set[int] = set()
    for prop in proposals:
        original, correction = prop["original"], prop["correction"]
        label = f"{original} -> {correction}"
        if is_format_only(original, correction):
            result.fmt.append(label)
            continue
        gold_idx = next(
            (
                i
                for i, g in enumerate(gold["gold"])
                if span_overlap(text, original, g["original"])
            ),
            None,
        )
        if gold_idx is not None:
            expected = gold["gold"][gold_idx]["expected"]
            if any(overlaps(correction, alt) for alt in expected.split("|")):
                result.hit.append(label)
            else:
                result.wrong.append(f"{label} (기대: {expected})")
            matched_gold.add(gold_idx)
            continue
        if any(span_overlap(text, original, n["original"]) for n in gold.get("negatives", [])):
            result.neg.append(label)
            continue
        result.other.append(label)
    for i, g in enumerate(gold["gold"]):
        if i not in matched_gold:
            result.miss.append(f"{g['original']} -> {g['expected']}")
    return result


def proposals_from_sidecar(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"original": c["original"], "correction": c["correction"]}
        for c in data["corrections"]
    ]


if __name__ == "__main__":
    # 저장된 결과 JSON(run_eval.py 산출물)을 다시 채점한다: score.py <gold> <transcript> <result.json>...
    import sys

    gold_path, transcript_path, *result_paths = sys.argv[1:]
    gold_data = load_gold(Path(gold_path))
    segments = json.loads(Path(transcript_path).read_text(encoding="utf-8"))["segments"]
    full_text = " ".join(s["text"] for s in segments)
    rows = []
    for rp in result_paths:
        saved = json.loads(Path(rp).read_text(encoding="utf-8"))
        sc = score(saved["proposals"], gold_data, full_text, saved["summary"]["elapsed_sec"])
        rows.append(sc.summary())
        print(rp.split("/")[-1], json.dumps(sc.summary(), ensure_ascii=False))
    keys = ["proposals", "hit", "wrong", "miss", "neg", "other", "fmt", "precision", "recall", "elapsed_sec"]
    print("MEAN", json.dumps({k: round(sum(r[k] for r in rows) / len(rows), 3) for k in keys}, ensure_ascii=False))
