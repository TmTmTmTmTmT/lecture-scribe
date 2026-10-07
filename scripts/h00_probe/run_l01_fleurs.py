"""L-01: FLEURS ko_kr로 Cohere vs Whisper large-v3 한국어 CER 비교.

앱 코드 아님. FIX_GUIDE_12.md §2 전용 스크립트. probe venv 전용 의존성만 사용
(datasets, jiwer, transformers, faster-whisper) — 앱 .venv 무관.

FIX_GUIDE_12.md §1의 두 구멍(음질 교란, 정답이 Whisper 출력)을 동시에 해결한다:
FLEURS는 깨끗한 낭독체 + 사람이 만든 정답이다. Cohere 공식 한국어 수치도 이 셋으로
낸 것이므로 저자 의도와 같은 조건이다.

정규화 규칙(§4, COMPARISON_METHOD.md §4)은 아래 normalize()에 고정한다 — 결과를 본
뒤 바꾸지 않는다: NFC 통일 + 문장부호 제거 + 공백 전부 제거(CER 공백 제거 기준).
"""
from __future__ import annotations

import re
import unicodedata

MODEL_DIR = "scripts/h00_probe/weights_check"
N_UTTERANCES = 40  # FIX_GUIDE_12 §2-1: 30~50발화면 충분, 전체(382) 안 돌림


def normalize(text: str) -> str:
    """정규화 규칙 — 측정 전 고정, 점수 본 뒤 바꾸지 않는다(COMPARISON_METHOD.md §4)."""
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"[^\w가-힣a-zA-Z0-9]", "", text)  # 문장부호·공백 전부 제거
    return text.lower()


def cer(ref: str, hyp: str) -> float:
    import jiwer
    ref_n, hyp_n = normalize(ref), normalize(hyp)
    if not ref_n:
        return float("nan")
    return jiwer.cer(ref_n, hyp_n)


def load_fleurs_subset(n: int):
    import io
    from datasets import load_dataset, Audio
    from faster_whisper.audio import decode_audio

    print(f"[l01] FLEURS ko_kr test 스트리밍 로드, 앞 {n}개만...")
    # datasets 최신판의 자동 오디오 디코드(torchcodec)가 이 머신에서 libavutil을 못 찾아
    # 로드 실패함(homebrew ffmpeg 공유 라이브러리 경로 문제) — decode=False로 raw bytes만
    # 받고, 이 repo가 이미 검증한 decode_audio()로 직접 디코드한다.
    ds = load_dataset("google/fleurs", "ko_kr", split="test", streaming=True)
    ds = ds.cast_column("audio", Audio(decode=False))
    items = []
    for i, ex in enumerate(ds):
        if i >= n:
            break
        audio_bytes = ex["audio"]["bytes"]
        arr = decode_audio(io.BytesIO(audio_bytes), sampling_rate=16000)
        items.append({"array": arr, "sampling_rate": 16000, "transcription": ex["transcription"]})
    print(f"[l01] {len(items)}개 발화 로드 완료")
    return items


def transcribe_cohere(model, processor, audio_array, sr: int) -> str:
    import torch

    if sr != 16000:
        import librosa
        audio_array = librosa.resample(audio_array, orig_sr=sr, target_sr=16000)
    inputs = processor(audio=audio_array, language="ko", sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        generated_ids = model.generate(
            inputs["input_features"],
            decoder_input_ids=inputs["decoder_input_ids"],
            attention_mask=inputs["attention_mask"],
            max_new_tokens=256,
        )
    audio_chunk_index = inputs.get("audio_chunk_index")
    if audio_chunk_index is not None and len(audio_chunk_index) > 1:
        text = processor.decode(generated_ids, audio_chunk_index=audio_chunk_index,
                                 language="ko", skip_special_tokens=True)
        if isinstance(text, list):
            text = text[0]
    else:
        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return text


def transcribe_whisper(whisper_model, audio_array, sr: int) -> str:
    import numpy as np
    if sr != 16000:
        import librosa
        audio_array = librosa.resample(audio_array, orig_sr=sr, target_sr=16000)
    audio_array = audio_array.astype(np.float32)
    segments, _ = whisper_model.transcribe(audio_array, language="ko", beam_size=5)
    return "".join(seg.text for seg in segments)


def main() -> None:
    import torch
    from transformers import AutoProcessor, CohereAsrForConditionalGeneration
    from faster_whisper import WhisperModel

    items = load_fleurs_subset(N_UTTERANCES)

    print("[l01] Cohere(transformers 네이티브) 로드 중...")
    processor = AutoProcessor.from_pretrained(MODEL_DIR)
    cohere_model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_DIR, dtype=torch.float32)
    cohere_model.eval()

    print("[l01] Whisper large-v3(faster-whisper, CPU/int8) 로드 중...")
    whisper_model = WhisperModel("large-v3", device="cpu", compute_type="int8")

    results = []
    for i, ex in enumerate(items):
        arr = ex["array"]
        sr = ex["sampling_rate"]
        ref = ex["transcription"]

        cohere_text = transcribe_cohere(cohere_model, processor, arr, sr)
        whisper_text = transcribe_whisper(whisper_model, arr, sr)

        cohere_cer = cer(ref, cohere_text)
        whisper_cer = cer(ref, whisper_text)

        results.append({
            "idx": i, "ref": ref, "cohere": cohere_text, "whisper": whisper_text,
            "cohere_cer": cohere_cer, "whisper_cer": whisper_cer,
        })
        print(f"\n[{i}] 정답: {ref}")
        print(f"    Cohere({cohere_cer:.3f}): {cohere_text}")
        print(f"    Whisper({whisper_cer:.3f}): {whisper_text}")

    valid = [r for r in results if r["cohere_cer"] == r["cohere_cer"]]  # NaN 제외
    avg_cohere = sum(r["cohere_cer"] for r in valid) / len(valid)
    avg_whisper = sum(r["whisper_cer"] for r in valid) / len(valid)

    print("\n" + "=" * 70)
    print(f"[l01] 평균 CER — Cohere: {avg_cohere:.4f} ({avg_cohere*100:.1f}%), "
          f"Whisper large-v3: {avg_whisper:.4f} ({avg_whisper*100:.1f}%)")
    print(f"[l01] 발화 수: {len(valid)}/{len(results)}")
    rel_diff = (avg_cohere - avg_whisper) / avg_whisper * 100 if avg_whisper > 0 else float("nan")
    print(f"[l01] 상대 차이(Cohere 기준, +면 Cohere가 나쁨): {rel_diff:+.1f}%")


if __name__ == "__main__":
    main()
