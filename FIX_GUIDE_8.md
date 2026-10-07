# FIX_GUIDE_8.md — v0.2: Cohere Transcribe 백엔드 추가 (VAD 분할 · GPU · 백엔드 선택)

> **[2026-09-13 종결] v0.2 Cohere Transcribe 백엔드는 채택하지 않는다.**
> 사유·근거: [FIX_GUIDE_11.md](FIX_GUIDE_11.md) §2·§4, STATUS.md "2026-09-13 (2)" 항목.
> 요약 — 한국어 정확도가 짧고 쉬운 조건에서도 large-v3보다 뚜렷이 나쁘고, 긴 오디오는
> mlx-audio·transformers 네이티브 양쪽 모두 반복 루프로 붕괴한다(하네스 결함을 바로잡은
> 뒤에도 재확인됨). Whisper(large-v3/large-v3-turbo) 유지.
> **이 문서는 지우지 않고 기록으로 보존한다** — 모델 구조·라이선스·실행 경로·측정 방법론
> 조사 내용이 다음에 다른 모델을 검토할 때 그대로 쓸 자산이다. 아래 본문은 착수 당시
> 그대로다.

작성: Opus, 2026-09-11
이전 문서: [FIX_GUIDE_7.md](FIX_GUIDE_7.md) — E-01/E-02 전건 완료
대상 릴리스: **v0.2** (`pyproject.toml` version 0.1.0 → 0.2.0) — **채택하지 않음(위 배너 참고)**

이 문서는 **계획서다. 코드는 여기에 쓰지 않는다.** 실행은 Sonnet이 하고, 진행 상황은
STATUS.md(최신 위) / PROGRESS.md(최신 아래)에 남긴다 — CLAUDE.md 규약.

---

## 0. 요구사항 (사용자 확정)

1. Cohere Transcribe 앞에 **VAD를 적용**해 오디오를 잘라 넣는다.
2. **GPU 가속**과 **hotwords 등 기존 기능**을 최대한 그대로 쓸 수 있게 한다.
3. 최종적으로 사용자가 **Whisper / Cohere 중 골라서** 돌릴 수 있다.
4. **테스트·비교 후 장단점 정리**를 v0.2 빌드 과정에 포함한다.
5. **메모리 누수, 프로세스 무응답·미종료가 생기지 않게** 한다.

---

## 1. 조사로 확정된 사실 — 다시 조사하지 말 것

전부 2026-09-11에 실측·1차 출처로 확인했다. Sonnet은 이 표를 신뢰하고 바로 구현에 들어간다.
**단, §2의 H-00만은 반드시 직접 확인한다.**

### 1-1. 모델

| 항목 | 값 | 근거 |
|---|---|---|
| 정식 repo | `CohereLabs/cohere-transcribe-03-2026` | HF API, 다운로드 219,582 |
| 라이선스 | **Apache-2.0** | HF cardData. 상업·개인 사용 제한 없음 |
| 원본 repo 접근 | **게이트됨** — 약관 동의 + HF 토큰 필요. **선택이 아니라 필수 전제**(아래 정정 참고) | raw 파일 요청이 "Access restricted" 반환 |
| ~~우회 경로~~ | **없다.** `mlx-community/...-mlx-8bit`는 게이트 없이 받아지지만 **BF16을 8bit로 오라벨**(scale 텐서 0개, 실측). `beshkenadze/...-mlx-{fp16,8bit,6bit,4bit}` 전부 게이트 없이 받아지지만 **네 개 다 `transf_decoder.*`/`log_softmax.*` 텐서가 0개** — Swift 포트(`mlx-audio-swift`)용 변환본이라 파이썬 `mlx-audio`의 `cohere_asr.py`와 키 규약 자체가 다르다. **커뮤니티 MLX 변환본 어디로도 우회되지 않는다.**(FIX_GUIDE_9.md §1·§2 실측, STATUS.md 2026-09-12 참고) | HF API + safetensors 헤더 실측(HTTP Range로 4개 리포 전부 확인, 전체 다운로드 불필요) |
| 한국어 | **공식 지원** (14개 언어: ar de el en es fr it ja ko nl pl pt vi zh) | HF cardData `language` |
| 구조 | 2B encoder-decoder. Fast-Conformer 인코더, 파라미터 90% 이상이 인코더 | 공식 블로그 |
| 인코더 | 48층 / hidden 1280 / heads 8 / mel 128 / conv stride 2 | `config.json` |
| 디코더 | 8층 / hidden 1024 / `max_position_embeddings` **1024** | `config.json` |
| **오디오 프런트엔드** | **16000 Hz**, n_fft 512, win 400, hop 160, mel 128, preemphasis 0.97 | `preprocessor_config.json` |
| 최대 클립 | `max_audio_clip_s` **35.0**, `overlap_chunk_second` 5.0 | `preprocessor_config.json` |
| 크기 | fp16 4.13GB / int8 약 2.05GB / 4bit 약 1.21GB | HF blob 크기, GGUF 변환본 |

> 참고: Cohere도 **16kHz**다. Whisper의 16kHz는 Whisper만의 제약이 아니라 음성 인식 모델의
> 공통 규격이다. "다운샘플링이 과하다"는 가설은 여기서 최종적으로 기각한다.

### 1-2. 성능 수치의 함정 — 이번 작업의 존재 이유

- 널리 인용되는 **WER 5.42%는 영어 전용**이다. Open ASR Leaderboard(AMI, Earnings22,
  GigaSpeech, LibriSpeech, SPGISpeech, TED-LIUM, VoxPopuli — 전부 영어)의 평균이다.
- 한국어는 **CER**로 측정했고(zh/ja/ko는 CER), FLEURS·CommonVoice 17·MLS·Wenet 기준이다.
  공식 블로그에 **그래프만 있고 숫자는 공개되지 않았다.**
- 즉 **한국어 강의에서 Whisper large-v3보다 나은지는 아무도 모른다.** 재는 수밖에 없다.
  이것이 §10 비교 측정을 v0.2 빌드 과정에 넣는 이유다.

### 1-3. 실행 경로 — 무엇이 되고 무엇이 안 되나

| 경로 | 가능? | 비고 |
|---|---|---|
| **mlx-audio (MLX/Metal)** | **가능. 이걸 쓴다 — 단, 원본 게이트 리포가 전제**(위 정정 참고) | PyPI 0.5.3, `requires_python >=3.10`, 순수 파이썬 휠. 출시일부터 Cohere Transcribe 지원. `post_load_hook()`이 체크포인트에서 `preprocessor.featurizer.fb`/`.window`를 직접 재로드하는 구조라 원본 NeMo 계열 파일만 맞는다(커뮤니티 변환본 불가) |
| `mlx-speech` | **불가** | 전 버전이 Python **>=3.13** 요구. 이 repo는 `>=3.12,<3.13` 고정. **mlx-community 모델 카드의 예제가 `mlx_speech`를 쓰므로 그대로 따라 하면 실패한다** |
| transformers + torch (CPU/MPS) | 가능하나 느림 | 정합성 대조용으로만. 상시 경로 아님 |
| vLLM | **불가** | macOS arm64 휠 0개 |
| GGUF / CrispASR (CPU) | 비권장 | 8스레드 RTFx 0.80~1.08x. 지금 CPU 기준선(large-v3 1.16x)보다 느림 |

### 1-4. 치명적 제약 — 설계가 여기서 갈린다

**Cohere Transcribe는 타임스탬프도, 세그먼트별 신뢰도도 내보내지 않는다.**

이 앱은 둘 다에 의존한다 — SRT/VTT 출력, 문단·섹션 분리, `⟨?⟩` 저신뢰 마커,
`postprocess.suggest_glossary_terms()`의 `avg_logprob < -0.5` 필터가 전부 여기에 걸려 있다.

→ **VAD가 단순 전처리가 아니라 타임스탬프 공급원이다.** §4가 이 설계다.

### 1-5. 기존 자산 (새로 만들지 말 것)

| 있는 것 | 위치 | 용도 |
|---|---|---|
| Silero VAD 일체 | `faster_whisper.vad` | 이미 설치됨(`onnxruntime 1.29.0`이 그 흔적). **새 VAD 의존성 추가 금지** |
| `get_speech_timestamps(audio, vad_options, sampling_rate)` | 같은 곳 | 샘플 단위 begin/end 목록 |
| `collect_chunks(audio, chunks, sampling_rate, max_duration)` | 같은 곳 | **`max_duration`으로 35초 상한을 바로 걸 수 있다.** `offset`/`duration`/`segments` 메타 반환 |
| `SpeechTimestampsMap` | 같은 곳 | VAD 기준 시각 → 원본 타임라인 역매핑 |
| `perf.release_memory()` | `perf.py:138` | `gc.collect()` + `malloc_zone_pressure_relief` |
| `perf.mlx_limit_cache(limit_gb=1.5)` | `perf.py:328` | `mx.set_cache_limit`. MLX 버퍼 캐시 무한 증가 차단 |
| `perf.MODEL_MEMORY_GB` / `model_memory_gb()` | `perf.py:215` | 저메모리 경고 |
| `perf.check_memory_headroom()` | `perf.py:339` | 메모리 빠듯할 때 안내 문구 |
| `BackendCapabilities` + `ignored_options()` | `backends/base.py:83` | **"이 백엔드는 이걸 못 한다"를 이미 모델링한다.** GUI가 이 값으로 위젯을 비활성화한다 |
| 백엔드 언로드 패턴 | `backends/faster.py:177` | 참조 None → `release_memory()` → 반환량 로그 |
| 이중 로드 방지 락 | `backends/mlx.py:56` | 같은 패턴을 Cohere에도 적용 |

### 1-6. 기존 실측 기준선 (비교 대상)

M1 Pro 16GB, 45분 13초 실강의:

| 구성 | 속도 | 메모리 |
|---|---|---|
| faster large-v3 int8 CPU 순차 | 1.16~1.6x 실시간 (약 30~39분) | RSS 3.3~5.5GB, 상주 2.4GB |
| faster large-v3 batched | 2.4x (약 19분) | — |
| mlx large-v3 GPU | 5.0x (약 9분) | 상주 3.1GB |
| large-v3-turbo | 5.5x / 배치 7.2x | 1.4~1.7GB |

Cohere MLX int8 예상은 **추정치일 뿐 M1 Pro 실측이 없다.** H-00에서 직접 잰다.

---

## 2. H-00 — 선행 실측 게이트 (다른 모든 작업보다 먼저)

**여기서 막히면 v0.2 범위를 줄이고 Opus로 반환한다. 우회하거나 추측으로 넘어가지 않는다.**

작업 디렉터리는 `scripts/` 아래 임시 스크립트로 하고, 앱 코드는 건드리지 않는다.

확인 항목 — 전부 **실제로 돌려서** 답을 낸다:

| # | 확인할 것 | 실패 시 |
|---|---|---|
| H-00-a | `mlx-community/...-mlx-8bit`를 토큰 없이 받을 수 있나 | 원본 repo 게이트 동의를 **사용자에게 요청**. Sonnet이 대신 동의하지 않는다 |
| H-00-b | `mlx-audio`가 Python 3.12 + 이 venv에 설치되나. `uv sync --extra cohere`가 기존 잠금을 깨지 않나 | 의존성 충돌 내용을 기록하고 반환 |
| H-00-c | 30초짜리 한국어 오디오가 실제로 한국어로 전사되나 | 반환 |
| H-00-d | **`avg_logprob`에 해당하는 점수를 뽑을 수 있나** (generate 계열의 score 반환 옵션) | §5-2의 대체 정책으로 진행 |
| H-00-e | **프롬프트/용어 주입 경로가 있나** — 디코더 프리픽스 주입이 먹히나 | §6의 판정에 반영 |
| H-00-f | 45분 파일 기준 예상 속도 (30초 샘플로 RTF 측정 후 외삽) | 기준선보다 느리면 STATUS.md에 기록하고 계속 |
| H-00-g | 모델 로드/해제 1회 후 RSS가 원래대로 돌아오나 | §8 설계에 반영 |

결과는 **STATUS.md에 표로 남긴다.** 이 표가 이후 모든 판단의 근거다.

> `trust_remote_code=True`가 필요한 모델이다(`custom_code` 태그). 원격 코드를 실행한다는 뜻이니
> 의식적으로 선택한 사항임을 STATUS.md에 한 줄 명시한다. 출처는 CohereLabs 공식 repo여야 한다.

---

## 3. H-01 — 의존성 격리

**기본 설치를 바꾸지 않는다.** 기존 `mlx` extra와 같은 방식으로 선택 extra를 만든다.

- `pyproject.toml`에 `cohere` extra 신설. 들어갈 것: `mlx-audio`(+`stt` extra).
  그게 끌고 오는 것: `transformers`, `miniaudio`, `sounddevice`, `tqdm`, `sentencepiece`, `zstandard`.
  이미 있는 것: `huggingface-hub 1.29.0`, `numpy 2.5.2`, `scipy 1.18.1`, `mlx 0.32.2`, `torch 2.13.0`.
- `mypy` overrides에 `mlx_audio.*`(및 실제 임포트하는 모듈) `ignore_missing_imports` 추가.
- **`sounddevice`는 PortAudio 바이너리를 끌고 온다.** 이 앱은 PyInstaller 자립 번들로 배포한다 —
  §12의 DMG 실행 확인이 형식적 절차가 아닌 이유다.
- extra 미설치 상태에서 Cohere를 고르면 **`BackendUnavailableError`로 즉시, 명확히 실패**한다.
  `mlx.py`가 ffmpeg PATH 문제에서 겪었던 것과 같은 류의 사고를 반복하지 않는다.

---

## 4. H-02 — VAD 분할 모듈 (공용, 순수 함수)

> **정정(FIX_GUIDE_9.md 실측)**: `mlx-audio`의 `cohere_asr.generate()`는 `vad=True`라는
> 자체 내장 VAD 옵션을 갖고 있으나, **설치본(0.5.3)에서 실제로 깨져 있다**
> (`vad.py:56`, `TypeError: astype(): ... Invoked with types: mlx.core.array, type` —
> MLX 배열에 numpy dtype을 넘기는 라이브러리 자체 버그, 재현 확인됨). 그리고 애초에
> `mlx-community/silero-vad`라는 **별도 MLX 전용 가중치**를 새로 받는 다른 구현이라
> 아래 4-1의 "새 VAD 의존성 추가 금지" 원칙과도 맞지 않았을 것이다. **항상 `vad=False`로
> 호출하고 청크는 이 절의 `faster_whisper.vad` 경로로만 만든다.** 서드파티 버그를
> 고치려 들지 않는다.

### 4-1. 위치와 성격

**신규 `src/lecture_scribe/vad_split.py`.** GUI·백엔드 비의존. 단위 테스트 필수 (CLAUDE.md 코딩 규칙).
`faster_whisper.vad`를 감싸기만 한다. **VAD 알고리즘을 직접 구현하지 않는다.**

### 4-2. 무엇을 하나

1. 16kHz mono float32 배열을 받는다(디코드는 기존 `faster_whisper.audio.decode_audio` 재사용 —
   `mlx.py:237`이 이미 쓰는 경로다. ffmpeg 외부 의존을 다시 만들지 않는다).
2. `get_speech_timestamps()`로 발화 구간을 얻는다.
3. `collect_chunks(..., max_duration=...)`로 **모델 상한 이하**로 묶는다.
4. 각 청크에 대해 `(오디오 배열, 원본 시작 시각, 원본 끝 시각)`을 돌려준다.

### 4-3. 상한값

- Cohere `max_audio_clip_s`는 35.0이지만 **상한을 30초로 잡는다.** 이유: 전처리 패딩·
  `speech_pad_ms`(기본 400ms 양쪽)로 실제 길이가 늘어나 35를 넘기면 모델이 조용히 자른다.
  **여유 없이 상한에 붙이지 않는다.**
- 상한은 **백엔드가 알려 주는 값**으로 받는다. 코드에 35나 30을 박지 않는다.

### 4-4. 타임스탬프 책임

**청크의 시작 시각이 곧 그 청크에서 나온 텍스트의 시작 시각이다.** 청크 내부 단어 단위
타임스탬프는 **만들지 않는다.** 없는 정보를 지어내지 않는다.

- 한 청크 = 한 `Segment`를 기본으로 한다.
- 이 정밀도로 SRT/VTT가 실용적인지는 §10-4에서 사람이 눈으로 확인한다.

---

## 5. H-03/H-04 — Cohere 백엔드

### 5-1. 위치와 인터페이스

**신규 `src/lecture_scribe/backends/cohere.py`.** `backends/base.py`의 `TranscriptionBackend`
프로토콜을 그대로 만족시킨다 — `name`, `model_name`, `capabilities()`, `ensure_loaded()`,
`transcribe()`, `count_tokens()`, `unload()`. **프로토콜을 수정하지 않는다.**

`transcribe()`는 `TranscriptionStream`을 돌려주고 `segments`는 **지연 생성**이다.
청크 루프를 제너레이터로 돌린다. 이게 진행률·취소·메모리 세 문제를 동시에 푼다(§8, §9).

### 5-2. `Segment` 필드를 무엇으로 채우나

`Segment`는 `avg_logprob`·`no_speech_prob`·`compression_ratio`·`temperature`를 요구한다.
**빈 값을 그럴듯한 숫자로 채우지 않는다.** 정책:

| 필드 | 값 | 근거 |
|---|---|---|
| `id` / `start` / `end` / `text` | 청크 인덱스, VAD 시작·끝, 모델 출력 | §4-4 |
| `compression_ratio` | **직접 계산한다.** 텍스트만으로 나오는 통계다(원문 길이 ÷ zlib 압축 길이) | Whisper와 같은 정의를 쓰면 기존 반복 탐지가 그대로 동작 |
| `no_speech_prob` | **VAD 확률에서 유도한다** (발화 구간으로 뽑혔으므로 낮은 값) | VAD가 판단 주체 |
| `avg_logprob` | H-00-d가 성공하면 실제 점수. **실패하면 `0.0` 고정 + `BackendCapabilities`에 신뢰도 미지원 표기** | 아래 주의 |
| `temperature` | `0.0` | 온도 폴백 체인이 없다 |

> **`avg_logprob`을 못 뽑는 경우의 파급을 반드시 확인할 것.** `0.0`은 "매우 자신 있음"으로
> 읽힌다 — `⟨?⟩` 마커가 영원히 안 붙고, `suggest_glossary_terms()`의 `avg_logprob < -0.5`
> 필터가 **모든 후보를 통과시킨다.** 두 곳이 조용히 잘못 동작하느니, 신뢰도 기능을
> **명시적으로 비활성화**하는 쪽이 옳다. 어느 쪽을 골랐는지 STATUS.md에 남긴다.

### 5-3. `capabilities()` — 정직하게 신고한다

`BackendCapabilities`는 능력 차이를 드러내라고 만든 장치다(`base.py:1-6` 주석). 거짓 신고 금지.

- `hotwords`: **H-00-e 결과대로.** 확인 전에는 `False`.
- `condition_on_previous_text` / `prompt_reset_on_temperature` / `temperature_fallback`
  / `hallucination_silence_threshold`: 전부 `False`(해당 개념이 없다).
- `vad_filter`: **`True`** — VAD가 이 백엔드의 필수 경로다.
- `word_timestamps`: `False`.
- `batched`: 초기 `False`. 배치는 v0.2 범위 밖.
- `parallel_transcribe`: `False`.
- `beam_search`: 설정의 `decoding.strategy`가 beam이나, **요청의 `beam_size`를 그대로
  전달할 수 있는지 확인되기 전에는 `False`**로 두어 `ignored_options()`가 경고하게 한다.

`ignored_options()`가 이미 경고 문구를 만들어 준다. **무시되는 옵션을 조용히 넘기지 않는다**
(CLAUDE.md 절대 하지 말 것 §15/§7 취지).

### 5-4. `count_tokens()`

프롬프트 예산(223)은 **Whisper 토크나이저 기준값이다.** Cohere는 토크나이저가 다르고
디코더 `max_position_embeddings`가 1024다.

- Cohere 백엔드의 `count_tokens()`는 **Cohere 토크나이저로 센다.**
- **`prompt.PROMPT_TOKEN_HARD_LIMIT`(223)을 바꾸지 않는다.** Whisper 경로가 그 값에 묶여 있다.
  백엔드별 예산이 필요하면 그건 별도 문서 과제다. v0.2에서는 Cohere가 프롬프트를 쓰지
  않거나(§6에서 미지원 판정) 쓰더라도 223 이하이므로 안전한 쪽으로 남는다.

---

## 6. H-05 — hotwords / 용어 주입

### 6-1. 현실

Cohere는 **추론 시점 hotword·컨텍스트 바이어싱 API를 공개하지 않았다.** 공식 블로그의
"punctuation customizable in the prompt"는 학습 단계 이야기다.

사용자 요구 3번("기존 hotwords 기능 등 모두 사용 가능")은 **Cohere 쪽에서는 그대로 달성할 수 없다.**
이 사실을 숨기지 않는다. 대신:

### 6-2. 실험 1회 (H-00-e 연장)

디코더는 평범한 seq2seq 디코더이므로, Whisper의 `initial_prompt`처럼 **디코더 입력 프리픽스로
용어를 주입**하는 것이 통할 가능성이 있다. **1회만 시도한다:**

- 용어가 포함된 짧은 문장을 디코더 프리픽스로 넣고, 안 넣은 결과와 **핵심 용어 적중 수**를 비교한다
  (§10-3의 지표. 이 repo는 hotwords 검증에서 "6/6 → 2/6" 방식을 이미 써 봤다).
- **효과가 없거나 출력이 오염되면 즉시 접는다.** `capabilities().hotwords = False`로 확정하고
  GUI가 관련 위젯을 회색 처리하게 둔다. 그게 이미 설계된 동작이다.
- 성공하면 `initial_prompt`·`hotwords` 지원으로 신고하고 §10에서 효과를 수치로 남긴다.

**둘 중 어느 쪽이든 STATUS.md에 결론과 근거를 남긴다.** "해 봤는데 안 됐다"도 결과다.

### 6-3. Whisper 쪽은 그대로 둔다

`prompt.py`, `postprocess.py`, 용어 통계(`glossary_stats.py`)는 **손대지 않는다.**
Whisper를 고르면 v0.1과 100% 같은 동작이어야 한다. 이것이 v0.2의 회귀 기준이다.

---

## 7. H-06 — 백엔드 선택 (사용자 요구 3번)

### 7-1. 기존 구조를 따른다

백엔드는 이미 `faster` / `mlx` 둘이 선택 가능하다. **Cohere는 세 번째 선택지로 붙인다.
새 선택 메커니즘을 만들지 않는다.**

- `config.py`: 모델 목록·백엔드 목록에 항목 추가. **`SCHEMA_VERSION` 마이그레이션 규칙을
  기존 방식대로 처리한다**(설정 파일에 없는 새 값은 기본값으로 채워지고, 구버전 설정이
  깨지지 않아야 한다). 기본 백엔드는 **v0.1과 동일하게 유지한다** — 기본값을 바꾸면
  기존 사용자가 예고 없이 다른 모델로 갈아타게 된다.
- `gui/settings_panel.py`: 기존 백엔드 선택 위젯에 항목 추가. `apply_capabilities()`가
  이미 능력에 따라 위젯을 비활성화하므로, `capabilities()`만 정직하면 UI는 따라온다.
- `gui/strings_ko.py`: 문구는 **여기 한 곳에만.** Cohere 선택 시의 제약(타임스탬프 정밀도,
  신뢰도·hotwords 미지원 여부)을 §5-3의 확정 결과에 맞춰 인라인 설명으로 넣는다.
  FIX_GUIDE_6 C-05에서 정한 원칙 — **위험하거나 무시되는 항목에만** 설명을 붙인다.
- `cli.py`: `--backend cohere` 추가. 무시되는 옵션은 `ignored_options()`로 **stderr에 경고**.
  stdout 오염 금지.

### 7-2. 전환 시 모델 교체

백엔드를 바꾸면 **이전 모델을 반드시 내린다.** §8.

---

## 8. H-07 — 메모리 (사용자 요구 5번 前半)

### 8-1. 동시 상주 금지 — 가장 중요한 규칙

Whisper large-v3(상주 2.4~3.1GB) + Cohere(약 2.5GB) + PySide6가 동시에 뜨면 16GB에서
스왑으로 들어간다. **어느 시점에도 전사 모델은 하나만 상주한다.**

- 백엔드 전환 시 이전 백엔드의 `unload()`를 **먼저** 호출하고, 그다음에 새 모델을 로드한다.
  순서를 뒤집으면 전환 순간 피크가 두 배가 된다.
- `perf.check_memory_headroom()`에 Cohere 실측값을 반영한다.
  `perf.MODEL_MEMORY_GB`에 H-00-g에서 **실제로 잰 값**을 넣는다. 추정치를 넣지 않는다.

### 8-2. `unload()` 구현 기준

`backends/faster.py:177`의 패턴을 그대로 따른다: 참조 None → `perf.release_memory()` →
반환량 로그. **추가로 MLX 경로이므로:**

- `perf.mlx_limit_cache()`를 `ensure_loaded()`에서 호출한다 (`mlx.py:166`과 같은 위치).
  MLX 버퍼 캐시는 걸어 두지 않으면 계속 커진다.
- `unload()`에서 MLX 캐시를 명시적으로 비운다. `release_memory()`만으로는 Metal 버퍼가
  안 돌아온다 — 파이썬 힙이 아니다.

### 8-3. 누수 검증 (구현 대상이 아니라 검증 절차)

**전사 → 언로드 사이클을 5회 반복하고 매 회 `perf.process_rss_mb()`를 기록한다.**

- RSS가 회차마다 **단조 증가하면 누수다.** 톱니 모양이면 정상.
- 판정선: 5회 후 RSS가 1회 후 대비 **+300MB를 넘으면 실패**로 보고 원인을 찾는다.
- 백엔드 **전환** 사이클(Whisper→Cohere→Whisper)도 3회 돌려 같은 기준으로 본다.
- 수치를 STATUS.md에 남긴다. "누수 없음"만 적지 않는다.

### 8-4. 청크 루프의 메모리

- 45분 오디오의 float32 배열은 약 173MB다. **청크를 만들 때 전체 배열의 복사본을
  통째로 또 만들지 않는다.** 뷰/슬라이스로 넘기고, 다 쓴 청크 참조는 즉시 버린다.
- 디코드된 전체 오디오를 백엔드 인스턴스 속성에 **보관하지 않는다.** 지역 변수로 두어
  제너레이터가 끝나면 같이 사라지게 한다.

---

## 9. H-08 — 무응답·미종료 (사용자 요구 5번 後半)

### 9-1. 이 repo는 이미 이 사고를 겪었다

`mlx.py`의 docstring: `mlx_whisper.transcribe()`는 지연 생성을 하지 않아 46분 파일에
400.7초 동안 **진행률 0% 고정, 취소 불가**였다. 그래서 창 단위로 쪼갰다.

**Cohere도 같은 성질이다.** VAD 청크 루프가 그 해법을 그대로 제공한다 —
**청크 하나 = 진행률 1틱 = 취소 체크포인트.**

### 9-2. 지켜야 할 것

1. **제너레이터는 청크마다 yield한다.** 파일 전체를 다 돌고 한 번에 내보내지 않는다.
2. **`TranscriptionStream`의 계약을 지킨다** — "소비를 중단(close)하면 전사도 중단된다"
   (`base.py:71`). `GeneratorExit`를 삼키지 말고, 그 경로에서 청크 자원을 반드시 놓는다.
3. **`on_heartbeat`을 청크 시작마다 호출한다.** 긴 청크에서 "멈춘 게 아니다"를 알린다
   (FIX_GUIDE_2 N-02의 목적).
4. **어떤 경로에서도 stdin을 읽지 않는다.** HF 토큰이 없을 때 `huggingface_hub`가
   대화형 로그인 프롬프트로 빠지면 **CLI가 영구 정지한다.** 비대화형을 강제하고,
   인증 실패는 `BackendUnavailableError`로 **즉시** 올린다 (CLAUDE.md 스트림 분리 원칙).
5. **모델 다운로드에 타임아웃과 진행 보고를 건다.** 4GB 다운로드 중 무한 대기 금지.
6. **이중 로드 락**을 `mlx.py:56`과 같은 방식으로 건다. 두 스레드가 동시에 4GB를 각자 받으면
   메모리가 두 배로 뛴다.
7. **QThread 종료 확인**: 취소 후 워커 스레드가 실제로 끝나는지 본다. MLX 연산이 도는 중에는
   파이썬 레벨 취소가 안 먹으므로, **취소는 청크 경계에서만** 반영된다는 점을 전제로 설계한다.
   청크가 30초 상한이므로 최악 대기가 유한하다 — 이것도 §4-3 상한의 이유다.

### 9-3. 검증 절차

- 45분 파일 전사 중 **10초 시점에 취소** → ① UI가 즉시 반응 ② 30초 안에 스레드 종료
  ③ 프로세스 RSS가 원래대로 ④ 앱 종료가 걸리지 않음.
- 전사 도중 **앱 종료(⌘Q)** → 좀비 프로세스가 남지 않는지 `pgrep`으로 확인.
- 두 경우 모두 결과를 STATUS.md에 남긴다.

---

## 10. H-09 — 비교 측정 (사용자 요구 4번)

**v0.2 빌드의 일부다. 이게 끝나야 v0.2다.**

### 10-1. 측정 대상 3종 — 이 구성이 핵심

| # | 구성 | 목적 |
|---|---|---|
| A | Whisper large-v3, **프롬프트 없음** | 공정 비교 기준선 |
| B | **Cohere**, 프롬프트 없음(또는 §6-2 성공 시 있음) | 비교 대상 |
| C | Whisper large-v3, **주제+용어 프롬프트 켬** | **앱이 실제로 출하하는 구성** |

> **판단은 B vs C로 한다.** B가 A를 이겨도 C에 지면 도입 이득이 없다.
> 이 앱의 차별 요소가 프롬프트 유도이기 때문이다. A는 "모델 자체 성능"을 분리해 보는 용도다.

### 10-2. 측정 자료 2단계

- **1단계 — FLEURS `ko_kr`**: 게이트 없음, CC-BY-4.0, 정답 전사 포함. Cohere가 자기 한국어
  수치를 낸 바로 그 테스트셋. **객관적 교정점.**
  단, 낭독체 짧은 문장이다. **강의가 아니다.** 여기 숫자를 강의 성능으로 읽지 않는다.
- **2단계 — 실강의**: CLAUDE.md의 전자회로 파일(45분 12초). **읽기 전용. 이동·수정·삭제 금지.**
  전체를 손으로 교정하는 건 비현실적이므로 **앞·중간·끝에서 3분씩 3구간(합 9분)**만 정답을 만든다.
  - **정답 만들 때의 편향 주의**: 한쪽 모델 출력을 고쳐서 정답을 만들면 그 모델에 유리해진다.
    → **두 출력을 나란히 놓고, 서로 다른 구간만 오디오를 들어 판정**한다. 오차는 거의 전부
    불일치 구간에 있다.

### 10-3. 지표 — 한국어는 CER이 주다

| 지표 | 비고 |
|---|---|
| **CER (공백 제거)** — 주 지표 | 한국어 띄어쓰기는 인식 오류가 아니다. Cohere 공식도 ko는 CER |
| CER (공백 유지) | 보조 |
| WER (어절 기준) | 참고용. 조사·어미 때문에 과대평가된다 |
| **핵심 용어 적중률** | **이 앱에서는 CER보다 중요할 수 있다.** 도메인 용어 N개 중 몇 개가 맞게 나왔나 |
| 속도(실시간 배수) | §1-6 기준선과 비교 |
| 피크 RSS | §8-3과 함께 |

### 10-4. 정규화 규칙 — 먼저 정하고 얼리기

**이게 제일 많이 틀리는 부분이다.**

- NFC 통일(이 repo의 기존 규칙), 문장부호 제거, 숫자 표기·외래어 표기(`network` vs `네트워크`)는
  **규칙을 하나로 정해 세 텍스트(정답·A·B·C) 전부에 똑같이 적용**한다.
- 간투사(음, 어)는 제거본과 유지본을 **둘 다** 낸다. 이 앱은 축자 전사이므로 간투사도 산출물이다.
- **점수를 본 뒤에 정규화 규칙을 고치지 않는다.** 고치면 원하는 답에 규칙을 맞추는 셈이다.
  규칙을 먼저 확정하고 STATUS.md에 적은 뒤 측정한다.

### 10-5. 측정 환경 격리

- 측정 스크립트는 `scripts/` 아래에 두고 **삭제하지 않는다.** 재현 가능해야 한다.
- 측정 전용 의존성(`jiwer` 등)은 **앱 `.venv`에 넣지 않는다.** 별도 임시 venv를 쓴다.
  CLAUDE.md §4 "승인 없이 의존성 추가 금지"를 지키는 방법이다.
- 두 모델에 **같은 오디오 배열**을 넣는다. 각자 디코드하게 두면 리샘플 차이가 섞인다.

### 10-6. 산출물

**`COMPARISON.md` 신규 작성.** 포함:
- 위 지표 표 (A/B/C 3열)
- 장단점 정리 — 정확도, 속도, 메모리, 타임스탬프 정밀도, 신뢰도 지원, hotwords 지원,
  언어 커버리지(Whisper 99 vs Cohere 14), 라이선스, 모델 다운로드 크기
- **"어느 쪽을 언제 쓰면 되는지" 한 문단.** 이게 사용자가 실제로 읽을 부분이다
- 측정 조건(정규화 규칙, 정답 구간, 하드웨어, 날짜) 전부 명시 — 없으면 재현 불가

---

## 11. 영향 범위

| 파일 | 변경 |
|---|---|
| **신규** `src/lecture_scribe/vad_split.py` | VAD 분할. 순수 함수 + 단위 테스트 |
| **신규** `src/lecture_scribe/backends/cohere.py` | Cohere 백엔드 |
| **신규** `COMPARISON.md` | 비교 결과·장단점 |
| **신규** `scripts/` 측정 스크립트 | 재현용. 삭제 금지 |
| `src/lecture_scribe/config.py` | 백엔드·모델 목록 추가, 마이그레이션. **기본값 변경 금지** |
| `src/lecture_scribe/perf.py` | Cohere 실측 메모리값, MLX 캐시 해제 |
| `src/lecture_scribe/gui/settings_panel.py` | 백엔드 선택 항목 |
| `src/lecture_scribe/gui/strings_ko.py` | 제약 안내 문구 |
| `src/lecture_scribe/cli.py` | `--backend cohere` |
| `pyproject.toml` | `cohere` extra, mypy overrides, version 0.2.0 |
| `backends/base.py` | **변경 없음.** 프로토콜·`BackendCapabilities`를 그대로 만족시킨다 |
| `prompt.py` / `postprocess.py` / `glossary_stats.py` / `writer.py` | **변경 없음** |

---

## 12. 검증 게이트

1. `uv run mypy --strict src/` 통과 (tests/ 대상 아님)
2. `uv run pytest -q` 전건 통과. Qt/PySide6 간헐 세그폴트는 FIX_GUIDE_5·6·7에 문서화된
   **기존 인프라 문제 — 고치려 들지 말 것**(범위 밖)
3. **회귀**: Whisper 경로가 v0.1과 동일하게 동작(§6-3). extra 미설치 환경에서도 앱이 정상 기동
4. **메모리**: §8-3 사이클 수치
5. **취소·종료**: §9-3 3항목
6. **비교**: §10 측정 완료 + `COMPARISON.md`
7. **DMG**: 재빌드 후 **번들에서 실제로 실행**해 Cohere 백엔드까지 동작 확인.
   소스에서 되는 것과 번들에서 되는 것은 다르다(§3의 PortAudio·`trust_remote_code` 위험)
8. STATUS.md / PROGRESS.md 갱신

---

## 13. 순서

1. **H-00 선행 실측** → 결과를 STATUS.md에. **여기서 막히면 Opus로 반환**
2. H-01 의존성 extra → `uv sync` 충돌 없음 확인
3. H-02 VAD 분할 모듈 + 단위 테스트 (다른 코드 비의존, 여기부터)
4. H-03/H-04 Cohere 백엔드 + `capabilities()` 정직 신고
5. H-05 프롬프트 주입 실험 1회 → 결론 확정
6. H-06 백엔드 선택 배선 (GUI/CLI/config)
7. H-07/H-08 메모리·취소 — **구현이 아니라 검증 단계.** 수치를 낸다
8. H-09 비교 측정 → `COMPARISON.md`
9. 게이트 전건 → STATUS.md·PROGRESS.md → version 0.2.0 → DMG 재빌드 → 번들 실행 확인

**각 단계 끝에 게이트를 돌린다. 전부 만든 뒤 한 번에 돌리지 않는다.**

---

## 14. 하지 말 것

1. **H-00을 건너뛰지 않는다.** 추측으로 구현하고 나중에 확인하지 않는다.
2. **`backends/base.py`의 프로토콜·`BackendCapabilities`를 수정하지 않는다.** Cohere가
   프로토콜에 맞춘다. 반대가 아니다.
3. **`capabilities()`를 거짓으로 신고하지 않는다.** 못 하는 걸 `True`로 두면 GUI가 쓸 수 있는
   것처럼 보여 주고 결과는 조용히 무시된다 — `base.py`가 막으려던 바로 그 사고다.
4. **`avg_logprob`에 그럴듯한 가짜 값을 넣지 않는다.** `⟨?⟩` 마커와 용어 추천 필터가
   조용히 망가진다(§5-2).
5. **VAD를 새로 구현하거나 새 VAD 의존성을 추가하지 않는다.** `faster_whisper.vad`가 이미 있다.
6. **`prompt.PROMPT_TOKEN_HARD_LIMIT`(223)을 바꾸지 않는다.** Whisper 경로가 묶여 있다.
7. **기본 백엔드·기본 모델을 바꾸지 않는다.** 기존 사용자가 예고 없이 갈아타게 된다.
8. **Whisper 경로 코드를 "겸사겸사" 리팩터링하지 않는다.** v0.1 동작 동일이 회귀 기준이다.
9. **두 모델을 동시에 상주시키지 않는다.** 전환 시 언로드 먼저(§8-1).
10. **파일 전체를 한 번에 돌리고 끝에 몰아서 내보내지 않는다.** 진행률 정지·취소 불가
    사고를 그대로 재현한다(§9-1).
11. **어떤 경로에서도 stdin을 읽거나 대화형 프롬프트로 빠지지 않는다.** HF 로그인 포함(§9-2).
12. **측정 의존성을 앱 `.venv`에 넣지 않는다.** 별도 venv(§10-5).
13. **점수를 본 뒤 정규화 규칙을 고치지 않는다**(§10-4).
14. **FLEURS 숫자를 강의 성능으로 보고하지 않는다.** 낭독체다(§10-2).
15. **원본 강의 파일을 이동·수정·삭제하지 않는다.** 읽기 전용.
16. **"한국어가 더 좋다/나쁘다"를 측정 없이 쓰지 않는다.** 공개된 한국어 수치가 없다(§1-2).
17. **게이트 수치·번들 실행 확인 없이 "v0.2 완료"라고 적지 않는다.**

---

## 15. 판정 — v0.2 이후 무엇을 할지

§10 결과에 따라 갈린다. **Sonnet이 임의로 정하지 않고 STATUS.md에 수치를 적은 뒤 Opus로 반환한다.**

| 결과 | 다음 |
|---|---|
| B가 C보다 CER·용어 적중 모두 우세 | Cohere를 기본 후보로 검토. 별도 문서 |
| B가 C와 비슷 | 선택지로 유지. 기본은 Whisper. 속도/메모리로 판단 |
| B가 C보다 열세 | **선택지로는 남기되 기본은 Whisper 고정.** 이유를 `COMPARISON.md`에 명시 |
| 타임스탬프 정밀도가 SRT/VTT에 부적합 | Cohere는 txt/md 전용으로 제한하는 안을 검토 |
