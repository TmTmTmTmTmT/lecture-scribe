"""J-02/K-01: transformers 네이티브 경로로 mlx-audio 결과와 교차 검증.

앱 코드 아님. FIX_GUIDE_10.md §3 / FIX_GUIDE_11.md §3-1 전용 대조군 스크립트. 앱에 이
경로를 배선하지 않는다 — 순수 진단용. torch/librosa/faster-whisper는 이 probe venv
전용으로 설치됨(앱 .venv 무관).

[FIX_GUIDE_11.md §1 수정 이력] 최초 버전은 긴(35초 초과) 오디오에서 세 가지가 틀려
있었다: ① attention_mask를 generate()에 안 넘김(feature_extraction_cohere_asr.py:235가
"batched inference 시 항상 넘겨야 한다"고 명시) ② 35초 초과 입력은
_split_audio_chunks_energy()가 실제로 청크 2개=배치 2로 쪼개는데 그 사실을 모르고
단일 샘플처럼 다룸 ③ batch_decode(...)[0]으로 청크 1을 버림 + 토큰 수를 배치 패딩
포함 최대 길이로 잘못 계산. 이 버전은 attention_mask 전달 + audio_chunk_index 기반
재조립(processor.decode) + 청크별 토큰 계수로 고쳤다. 짧은(35초 이하) 클립 결과는
애초에 배치 1·패딩 없음이라 이 수정의 영향을 받지 않는다(기존 결론 유효).
"""
from __future__ import annotations

import os

MODEL_DIR = os.path.join(os.path.dirname(__file__), "weights_check")


def transcribe(model, processor, audio_path: str, language: str, max_new_tokens: int):
    import torch
    from faster_whisper.audio import decode_audio  # probe venv 전용 설치(크로스벤브 sys.path 안 씀)

    with open(audio_path, "rb") as f:
        audio = decode_audio(f, sampling_rate=16000)

    inputs = processor(audio=audio, language=language, sampling_rate=16000, return_tensors="pt")
    with torch.no_grad():
        generated_ids = model.generate(
            inputs["input_features"],
            decoder_input_ids=inputs["decoder_input_ids"],
            attention_mask=inputs["attention_mask"],  # §1-1: 반드시 넘겨야 함(라이브러리 명시 경고)
            max_new_tokens=max_new_tokens,
        )

    # 청크(배치)별 실제 생성 토큰 수를 센다(§1-3) — eos_token_id(=3) 이전까지만 센다.
    # generated_ids.shape[-1] 전체는 배치 중 가장 긴 행 기준 패딩 포함 길이라 그대로 쓰지 않는다.
    prompt_len = inputs["decoder_input_ids"].shape[-1]
    eos_id = model.config.decoder.eos_token_id if hasattr(model.config, "decoder") else 3
    per_row_tokens = []
    for row in generated_ids[:, prompt_len:].tolist():
        if eos_id in row:
            per_row_tokens.append(row.index(eos_id))
        else:
            per_row_tokens.append(len(row))

    # audio_chunk_index로 청크를 원래 순서대로 재조립한다(§1-3) — [0]만 읽지 않는다.
    audio_chunk_index = inputs.get("audio_chunk_index")
    if audio_chunk_index is not None and len(audio_chunk_index) > 1:
        text = processor.decode(
            generated_ids, audio_chunk_index=audio_chunk_index, language=language,
            skip_special_tokens=True,
        )
        if isinstance(text, list):
            text = text[0]
    else:
        text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]

    n_chunks = len(audio_chunk_index) if audio_chunk_index else 1
    return text, per_row_tokens, n_chunks


def main() -> None:
    import torch
    from transformers import AutoProcessor, CohereAsrForConditionalGeneration

    print("[j02] transformers 네이티브 경로로 모델/프로세서 로드 중...")
    processor = AutoProcessor.from_pretrained(MODEL_DIR)
    # 체크포인트가 BF16인데 CPU conv 커널이 float32/BF16 혼용을 거부함(실측) — float32로 통일
    model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_DIR, dtype=torch.float32)
    model.eval()
    print("[j02] 로드 완료")

    cases = [
        ("한국어-짧음(5.0s)", "/path/to/lecture-scribe/scripts/h00_probe/j01_clips/ko_short.m4a", "ko", 256),
        ("한국어-길음(60s, §1 수정판)", "/path/to/lecture-scribe/assets/samples/9:1 전자회로 클립.m4a", "ko", 256),
        ("영어-짧음(4.5s, 대조)", "/path/to/lecture-scribe/assets/samples/en_5s.m4a", "en", 256),
    ]

    for label, path, lang, max_new in cases:
        text, per_row_tokens, n_chunks = transcribe(model, processor, path, lang, max_new)
        near_cap = [t >= max_new * 0.9 for t in per_row_tokens]
        print(f"\n--- {label} ---")
        print(f"청크 수: {n_chunks}, 청크별 생성 토큰: {per_row_tokens} "
              f"(max_new_tokens={max_new}, 상한 근접 청크: {near_cap})")
        print(f"출력(재조립됨): {text[:800]}")


if __name__ == "__main__":
    main()
