"""L-02: 디코딩 파라미터 전수 스윕 (transformers 네이티브 경로).

앱 코드 아님. FIX_GUIDE_12.md §3 전용 스크립트. mlx-audio는 그리디 고정이라 노브가
없음(§1-4) — transformers 경로에서만 가능하다.

FIX_GUIDE_12.md §3-1 지시대로 한 번에 하나씩만 바꾼다. 강의 클립(반복 루프 재현되는
입력)과 FLEURS 몇 개를 같이 본다.
"""
from __future__ import annotations

import io
import os

MODEL_DIR = "scripts/h00_probe/weights_check"
LECTURE_60S = "/path/to/lecture-scribe/assets/samples/9:1 전자회로 클립.m4a"


def load_audio_16k(path: str):
    from faster_whisper.audio import decode_audio
    with open(path, "rb") as f:
        return decode_audio(f, sampling_rate=16000)


def transcribe(model, processor, audio_array, language: str, gen_kwargs: dict):
    import torch

    inputs = processor(audio=audio_array, language=language, sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        generated_ids = model.generate(
            inputs["input_features"],
            decoder_input_ids=inputs["decoder_input_ids"],
            attention_mask=inputs["attention_mask"],
            **gen_kwargs,
        )
    prompt_len = inputs["decoder_input_ids"].shape[-1]
    eos_id = 3
    per_row_tokens = []
    for row in generated_ids[:, prompt_len:].tolist():
        per_row_tokens.append(row.index(eos_id) if eos_id in row else len(row))

    audio_chunk_index = inputs.get("audio_chunk_index")
    if audio_chunk_index is not None and len(audio_chunk_index) > 1:
        text = processor.decode(generated_ids, audio_chunk_index=audio_chunk_index,
                                 language=language, skip_special_tokens=True)
        if isinstance(text, list):
            text = text[0]
    else:
        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return text, per_row_tokens


def main() -> None:
    import torch
    from transformers import AutoProcessor, CohereAsrForConditionalGeneration

    print("[l02] 모델 로드 중...")
    processor = AutoProcessor.from_pretrained(MODEL_DIR)
    model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_DIR, dtype=torch.float32)
    model.eval()
    print("[l02] 로드 완료")

    lecture_audio = load_audio_16k(LECTURE_60S)

    # FIX_GUIDE_12 §3-1: 한 번에 하나씩. 기준(전부 기본값) 대비 비교.
    sweeps = [
        ("기준(그리디, 상한256)", dict(max_new_tokens=256)),
        ("repetition_penalty=1.1", dict(max_new_tokens=256, repetition_penalty=1.1)),
        ("repetition_penalty=1.2", dict(max_new_tokens=256, repetition_penalty=1.2)),
        ("repetition_penalty=1.35", dict(max_new_tokens=256, repetition_penalty=1.35)),
        ("no_repeat_ngram_size=3", dict(max_new_tokens=256, no_repeat_ngram_size=3)),
        ("no_repeat_ngram_size=4", dict(max_new_tokens=256, no_repeat_ngram_size=4)),
        ("no_repeat_ngram_size=5", dict(max_new_tokens=256, no_repeat_ngram_size=5)),
        ("num_beams=4", dict(max_new_tokens=256, num_beams=4)),
        ("num_beams=5,length_penalty=1.0", dict(max_new_tokens=256, num_beams=5, length_penalty=1.0)),
        ("encoder_repetition_penalty=1.05", dict(max_new_tokens=256, encoder_repetition_penalty=1.05)),
        ("max_new_tokens=1000(비교용)", dict(max_new_tokens=1000)),
    ]

    print("\n" + "=" * 70)
    print("[l02] 강의 클립(60초, 청크 2개) — 반복 루프 재현 대상")
    print("=" * 70)
    for label, kwargs in sweeps:
        try:
            text, tokens = transcribe(model, processor, lecture_audio, "ko", kwargs)
        except Exception as exc:
            print(f"\n--- {label} --- 실패: {exc!r}")
            continue
        print(f"\n--- {label} ---")
        print(f"청크별 생성 토큰: {tokens}")
        print(f"출력: {text[:400]}")

    print("\n[l02] 완료")


if __name__ == "__main__":
    main()
