"""교정 평가 실행기 (FIX_GUIDE_13 E-01).

전사는 1회만 하고(transcript.json 재사용) 교정만 반복한다. 예:

    .venv/bin/python scripts/c_eval/run_eval.py --model gemma4:e4b --runs 3 --tag baseline
    .venv/bin/python scripts/c_eval/run_eval.py --slide-terms-file terms.json --tag ocr

프롬프트 실험 변형은 `--variant`로 이 스크립트 안에서 고른다(앱 코드는 채택 전까지 안 건드린다).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "c_eval"))
sys.path.insert(0, str(ROOT / "src"))

import variants  # noqa: E402
from score import load_gold, score  # noqa: E402

from lecture_scribe import correction  # noqa: E402
from lecture_scribe.backends.base import Segment  # noqa: E402
from lecture_scribe.config import load_settings  # noqa: E402

DEFAULT_TRANSCRIPT = Path(
    "/private/tmp/claude-501/-Users-USER-Documents-Claude/"
    "aed4b199-61c8-4696-8f20-158c4f843fcc/scratchpad/c_eval/2주차 ML검파기.transcript.json"
)
DEFAULT_GOLD = ROOT / "scripts" / "c_eval" / "gold_ml_detector.json"
OUT_DIR = ROOT / "scripts" / "c_eval" / "results"


def load_segments(path: Path) -> list[Segment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        Segment(
            id=s["id"],
            start=s["start"],
            end=s["end"],
            text=s["text"],
            avg_logprob=s.get("avg_logprob", 0.0),
            no_speech_prob=s.get("no_speech_prob", 0.0),
            compression_ratio=s.get("compression_ratio", 0.0),
            temperature=s.get("temperature", 0.0),
        )
        for s in data["segments"]
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", type=Path, default=DEFAULT_TRANSCRIPT)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--tag", default="baseline")
    parser.add_argument("--topic", default="전자회로 강의: 2주차 ML 검파기")
    parser.add_argument(
        "--glossary",
        choices=["preset", "none"],
        default="preset",
        help="preset = 앱 설정의 활성 프리셋 용어집(실제 사용과 동일)",
    )
    parser.add_argument(
        "--slide-terms-from",
        type=Path,
        default=None,
        help="frames.json 경로. 그 파일의 ocr_terms를 교정 프롬프트 슬라이드 용어로 넣는다",
    )
    parser.add_argument("--variant", default="", help="variants.py 변형 이름(a,b,c,d,e,g,h, '+'로 결합)")
    args = parser.parse_args()

    settings = load_settings()
    slide_terms: list[str] = []
    if args.slide_terms_from is not None:
        slide_terms = list(json.loads(args.slide_terms_from.read_text(encoding="utf-8"))["ocr_terms"])
    glossary = [] if args.glossary == "none" else list(settings.current_preset().glossary)
    segments = load_segments(args.transcript)
    full_text = " ".join(s.text for s in segments)
    variants.apply(args.variant, segments)
    gold = load_gold(args.gold)

    OUT_DIR.mkdir(exist_ok=True)
    summaries = []
    for run in range(1, args.runs + 1):
        started = time.monotonic()
        result = correction.propose_corrections(
            segments,
            args.topic,
            glossary,
            model=args.model,
            min_confidence=settings.correction.min_confidence,
            max_chars=settings.correction.chunk_chars,
            slide_terms=slide_terms,
        )
        elapsed = time.monotonic() - started
        proposals = [
            {"original": p.original, "correction": p.correction} for p in result.proposals
        ]
        sc = score(proposals, gold, full_text, elapsed)
        summary = {"run": run, **sc.summary()}
        summaries.append(summary)
        detail = {
            "tag": args.tag,
            "model": args.model,
            "summary": summary,
            "hit": sc.hit,
            "wrong": sc.wrong,
            "neg": sc.neg,
            "other": sc.other,
            "fmt": sc.fmt,
            "proposals": proposals,
            "miss": sc.miss,
            "skipped_reason": result.skipped_reason,
        }
        (OUT_DIR / f"{args.tag}_{args.model.replace(':', '-')}_run{run}.json").write_text(
            json.dumps(detail, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False), flush=True)

    keys = ["proposals", "hit", "wrong", "miss", "neg", "other", "fmt", "precision", "recall", "elapsed_sec"]
    mean = {k: round(sum(s[k] for s in summaries) / len(summaries), 3) for k in keys}
    worst = {"hit_min": min(s["hit"] for s in summaries), "neg_max": max(s["neg"] for s in summaries)}
    print("MEAN", json.dumps(mean, ensure_ascii=False), json.dumps(worst))


if __name__ == "__main__":
    main()
