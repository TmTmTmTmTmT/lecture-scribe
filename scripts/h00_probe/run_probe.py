"""H-00-c/f/g 재측정: 정식 CohereLabs 체크포인트로 실제 추론 + 속도 + 메모리.

앱 코드 아님. FIX_GUIDE_9.md §4 재측정용 1회성 스크립트. .venv 오염 안 함
(scripts/h00_probe/.probe_venv 격리 사용).

FIX_GUIDE_9.md §4 지시대로 영어 클립을 먼저 본다 — 정답이 한 줄이라 눈으로 즉시
판정된다. 여기서 정상 문장이 안 나오면 한국어로 넘어가지 않는다(§10-10).

FIX_GUIDE_9.md §5 지시대로 strict=True로 로드한다 — 이전 사고(H-00-c)의 원인이
`strict=False`가 안 맞는 키를 조용히 버린 것이었으므로, 여기서는 안 맞으면 그 자리에서
예외가 나야 한다(그래야 이번엔 진짜 맞는지 확신할 수 있다).
"""
from __future__ import annotations

import gc
import os
import subprocess
import sys
import time

MODEL_DIR = os.path.join(os.path.dirname(__file__), "weights_check")
EN_SAMPLE = "/path/to/lecture-scribe/assets/samples/en_5s.m4a"
EN_REFERENCE = "Today we will discuss impedance matching and the Smith chart in microwave engineering."
KO_SAMPLE = "/path/to/lecture-scribe/assets/samples/9:1 전자회로 클립.m4a"
KO_REFERENCE_FILE = "/path/to/lecture-scribe/assets/samples/9:1 전자회로 클립.txt"
KO_DURATION_S = 60.0  # ffprobe 실측


def rss_mb() -> float:
    out = subprocess.run(
        ["/bin/ps", "-o", "rss=", "-p", str(os.getpid())],
        capture_output=True, text=True, timeout=5,
    )
    return float(out.stdout.strip()) / 1024


def main() -> None:
    print(f"[probe] python={sys.version.split()[0]}")
    print(f"[probe] RSS before import: {rss_mb():.1f} MB")

    t0 = time.time()
    from mlx_audio.stt.utils import load_model  # type: ignore
    import mlx.core as mx

    print(f"[probe] import time: {time.time()-t0:.1f}s, RSS: {rss_mb():.1f} MB")

    # --- 로드 (§5: strict=True — 안 맞는 키가 있으면 여기서 바로 죽는다) ---
    t0 = time.time()
    model = load_model(MODEL_DIR, strict=True)
    load_time = time.time() - t0
    rss_loaded = rss_mb()
    print(f"[probe] H-00-g load(strict=True): {load_time:.1f}s, RSS after load: {rss_loaded:.1f} MB")

    # --- 1단계: 영어 5초 클립 — 정답이 한 줄이라 눈으로 즉시 판정 (§4-1) ---
    t0 = time.time()
    en_result = model.generate(EN_SAMPLE, language="en", vad=False, verbose=False)
    en_infer_time = time.time() - t0
    print("=" * 70)
    print(f"[probe] 영어 5초 클립 추론 시간: {en_infer_time:.1f}s")
    print(f"[probe] 영어 결과: {en_result.text}")
    print(f"[probe] 영어 정답: {EN_REFERENCE}")
    en_ok = any(word.lower() in en_result.text.lower() for word in ["impedance", "smith", "microwave"])
    print(f"[probe] 판정: {'통과(핵심 용어 검출됨)' if en_ok else '실패(핵심 용어 없음 — 여전히 깨짐)'}")
    print("=" * 70)

    if not en_ok:
        print("[probe] §4-1 지시: 영어가 실패했으므로 한국어로 넘어가지 않고 멈춘다.")
        del model
        gc.collect()
        try:
            mx.clear_cache()  # type: ignore[attr-defined]
        except Exception:
            pass
        return

    # --- 2단계: 한국어 60초 클립 (영어 통과 시에만) ---
    t0 = time.time()
    ko_result = model.generate(KO_SAMPLE, language="ko", vad=False, verbose=False)
    ko_infer_time = time.time() - t0
    rtf = KO_DURATION_S / ko_infer_time if ko_infer_time > 0 else float("nan")

    print(f"[probe] 한국어 60초 클립 추론 시간: {ko_infer_time:.1f}s (RTF={rtf:.2f}x)")
    print(f"[probe] 한국어 세그먼트 수: {len(ko_result.segments)}")
    print("[probe] 한국어 전사 결과:")
    print(ko_result.text)
    for seg in ko_result.segments[:5]:
        print(f"    [{seg['start']:.1f}-{seg['end']:.1f}] {seg['text'][:60]}")

    if os.path.exists(KO_REFERENCE_FILE):
        with open(KO_REFERENCE_FILE, encoding="utf-8") as f:
            ref = f.read().strip()
        print(f"[probe] 참고용 large-v3 산출 정답(앞 200자): {ref[:200]}")

    # --- 언로드 (H-00-g는 이미 5사이클로 통과했으므로 1회만 재확인) ---
    del model
    gc.collect()
    try:
        mx.clear_cache()  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"[probe] mx.clear_cache() 실패(무시): {exc!r}")
    rss_after_unload = rss_mb()
    print(f"[probe] unload 후 RSS: {rss_after_unload:.1f} MB "
          f"(load 후 대비 {rss_loaded - rss_after_unload:+.1f} MB 변화)")

    est_45min_sec = 2712 / rtf if rtf > 0 else float("nan")
    print(f"[probe] H-00-f 45분 파일 외삽(RTF 기준): {est_45min_sec:.0f}s ({est_45min_sec/60:.1f}분)")


if __name__ == "__main__":
    main()
