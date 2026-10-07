"""J-01: 언어 × 길이 2x2 분리 실험 + max_tokens 상한 확인.

앱 코드 아님. FIX_GUIDE_10.md §2 전용 1회성 스크립트.

목적: FIX_GUIDE_9.md §4의 한국어 결과(반복 루프)가 "한국어라서"인지 "길어서/토큰
상한 때문에"인지를 가른다. §1-2가 지목한 generation_tokens을 반드시 같이 찍는다 —
256(기본 max_tokens)에 붙어 있으면 상한이 물린 것이다.
"""
from __future__ import annotations

import os
import sys
import time

MODEL_DIR = os.path.join(os.path.dirname(__file__), "weights_check")
CLIPS_DIR = os.path.join(os.path.dirname(__file__), "j01_clips")

CELLS = [
    ("영어-짧음(4.5s)", "/path/to/lecture-scribe/assets/samples/en_5s.m4a", "en"),
    ("영어-길음(36.3s)", os.path.join(CLIPS_DIR, "en_long.m4a"), "en"),
    ("한국어-짧음(5.0s)", os.path.join(CLIPS_DIR, "ko_short.m4a"), "ko"),
    ("한국어-길음(60s,기존34.2s청크 재사용)", "/path/to/lecture-scribe/assets/samples/9:1 전자회로 클립.m4a", "ko"),
]


def run_cell(model, label: str, path: str, language: str, max_tokens: int = 256) -> None:
    t0 = time.time()
    result = model.generate(path, language=language, vad=False, max_tokens=max_tokens, verbose=False)
    elapsed = time.time() - t0
    n_seg = max(len(result.segments), 1)
    avg_gen = result.generation_tokens / n_seg
    # STTOutput.generation_tokens는 배치 전체 합산값이다(세그먼트별로 안 쪼개짐, base.py 확인).
    # 세그먼트 평균이 max_tokens 상한의 90% 이상이면 "상한에 붙었다"로 본다.
    near_cap = avg_gen >= max_tokens * 0.9
    print(f"\n--- {label} (max_tokens={max_tokens}) ---")
    print(f"소요: {elapsed:.1f}s, 세그먼트 수: {len(result.segments)}")
    print(f"generation_tokens(합산)={result.generation_tokens}, 세그먼트당 평균={avg_gen:.1f}, "
          f"max_tokens={max_tokens} → 상한 근접: {'예 — 의심' if near_cap else '아니오'}")
    for i, seg in enumerate(result.segments):
        print(f"  세그먼트{i} [{seg['start']:.1f}-{seg['end']:.1f}]: {seg['text'][:200]}")
    print(f"전체 출력: {result.text[:500]}")


def main() -> None:
    from mlx_audio.stt.utils import load_model

    print("[j01] 모델 로드 중...")
    model = load_model(MODEL_DIR, strict=True)
    print("[j01] 로드 완료")

    for label, path, lang in CELLS:
        run_cell(model, label, path, lang, max_tokens=256)

    # §2-3: 한국어 34.2초 청크(60초 클립 그대로)를 max_tokens=1000으로 재시도
    print("\n" + "=" * 70)
    print("[j01] §2-3: 한국어 60초 클립을 max_tokens=1000으로 재시도")
    run_cell(
        model,
        "한국어-길음(max_tokens=1000)",
        "/path/to/lecture-scribe/assets/samples/9:1 전자회로 클립.m4a",
        "ko",
        max_tokens=1000,
    )


if __name__ == "__main__":
    main()
