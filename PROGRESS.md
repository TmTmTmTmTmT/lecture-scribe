# PROGRESS.md

마일스톤 경계에서 갱신. 상세 스펙은 사용자 지시서, 규칙은 `CLAUDE.md` 참조.

---

## 확정된 환경 / 결정

| 항목 | 값 | 근거 |
|---|---|---|
| Python | 3.12.13 (uv 관리) | 시스템 3.14는 PySide6 6.11.2 미지원 |
| 설치 버전 | faster-whisper 1.2.1, ctranslate2 4.8.2, PySide6 6.11.2, av 18.1.0, onnxruntime 1.29.0 | `uv pip list` |
| 기본 모델 | `large-v3` (int8, CPU) | 사용자 선택(정확도 우선) |
| 배포 | CLI 우선, `.app`은 M7에서 판단 | 사용자 승인 |
| mlx 백엔드 | M2 말 optional extra (`uv sync --extra mlx`) | 사용자 승인 |
| 테스트 파일 | `/path/to/강의/9:1 전자회로.m4a` (45분 12초, AAC 48kHz mono) | 사용자 제공 |

---

## §0.4 라이브러리 실측 결과 (기억 아닌 설치본 기준)

`.venv/.../faster_whisper/transcribe.py` 직접 확인:

1. **`BatchedInferencePipeline.transcribe`는 사용자 인자를 일부 무시한다** (L529-549)
   - `condition_on_previous_text=False` 하드코딩
   - `hallucination_silence_threshold=None` 하드코딩
   - `temperature[:1]` — **폴백 체인 제거**
   - `max_initial_timestamp=0.0`
   → 배치 모드에서는 §F-04 환각 억제 장치 3종이 무력화된다.
     그래서 **기본은 순차 모드**, 배치는 `--batched` 명시 시에만.
     무시되는 옵션은 `BackendCapabilities.ignored_options()`로 경고를 남긴다(§15-6 준수).
2. **`hallucination_silence_threshold`는 `word_timestamps=True`에서만 동작** (L1278-1295)
   → 임계값이 설정돼 있으면 `word_timestamps`를 자동으로 켠다(`backends/faster.py`).
3. **`get_prompt`은 hotwords와 previous_tokens를 함께 삽입** (L1136-1150)
   → `condition_on_previous_text=True` + `hotwords` 병행 가능(순차 모드). §F-03 가정 성립.
4. 배치 모드는 `initial_prompt`를 매 배치 윈도우마다 다시 넣는다 (L174-190)
   → 주제 유지에는 오히려 유리. M2에서 정확도/속도 트레이드오프 실측 예정.
5. 프롬프트 하드 한계는 `max_length // 2 - 1 = **223**` 토큰 (설정 기본값 224는 내부에서 223으로 클램프 예정, M2)
6. 모델 리포지터리 매핑: `large-v3` → `Systran/faster-whisper-large-v3`,
   `large-v3-turbo` → `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (`utils._MODELS`)

---

## M1 — 코어 엔진 + CLI 최소 기능 ✅ 완료 (2026-09-02)

### 작성된 파일

| 파일 | 역할 |
|---|---|
| `CLAUDE.md` | 프로젝트 규칙 |
| `pyproject.toml` | py3.12 고정, extras `mlx`/`fuzzy`, mypy strict 설정 |
| `src/lecture_scribe/errors.py` | 도메인 예외 (user_message / log_message 분리) |
| `src/lecture_scribe/config.py` | §7 설정 스키마, 프리셋, `version` 마이그레이션, 원자적 저장 |
| `src/lecture_scribe/audio.py` | ffprobe 메타데이터, 확장자·iCloud 스텁·0바이트 검증, 폴더 수집 |
| `src/lecture_scribe/logsetup.py` | 회전 로그 10MB×3, 콘솔은 항상 stderr |
| `src/lecture_scribe/writer.py` | txt 렌더링(순수 함수), 충돌 정책 3종, 대체 폴더 폴백, 원자적 쓰기 |
| `src/lecture_scribe/backends/base.py` | `TranscriptionBackend` 프로토콜, `BackendCapabilities` |
| `src/lecture_scribe/backends/faster.py` | faster-whisper 구현 |
| `src/lecture_scribe/backends/mlx.py` | 스텁(M2에서 구현) |
| `src/lecture_scribe/engine.py` | 파일 1건 파이프라인, 진행률·취소·오류 격리 |
| `src/lecture_scribe/cli.py` | 최소 CLI |
| `tests/` | writer / config / audio 단위 테스트 34개 |

### 검증 결과 (실행 완료)

| 항목 | 결과 |
|---|---|
| `uv run mypy --strict` | Success (12 files) |
| `uv run pytest -q` | 36 passed |
| 영어 5초(large-v3) | `Today we will discuss impedance matching and the Smith chart in microwave engineering.` |
| 한국어 60초 클립(large-v3) | 실제 강의 발췌 전사 성공, 문장 단위 정상 |
| 출력 위치 | 원본과 동일 폴더·동일 basename·`.txt` (`ls` 확인) |
| 인코딩 | UTF-8, NFC, LF, 권한 644 |
| 충돌 정책 3종 | skip=생성 안 함 / suffix=`_1` 생성 / overwrite=내용 교체 — 실제 CLI로 확인 |
| 지원 외 파일 | 큐 제외 + 사유 출력, 종료 코드 2 |
| 원본 오디오 | mtime·size 불변 |

### 속도 실측 (M1 Pro 16GB, large-v3 int8 CPU, 60초 오디오)

| 모드 | 소요 | 배속 | 45분 강의 환산 |
|---|---|---|---|
| 순차(기본) | 43.0초 | 1.4× | 약 32분 |
| `--batched` | 25.5초 | 2.4× | 약 19분 |

배치 모드 출력은 순차 대비 문장이 짧고 일부 어휘가 다름(예: `1730만원`→`173만원`,
`경북시`→`광역시`). 환각 억제 장치가 빠진 대신 빠르다. M2에서 주제 프롬프트 적용 후 재비교.

### M1에서 발견·수정한 버그

1. **ffmpeg 프로토콜 오인** — `9:1 전자회로.m4a`처럼 `이름:`으로 시작하는 파일을
   상대 경로로 넘기면 ffprobe/PyAV가 `9:`을 프로토콜로 해석해
   `Protocol not found`로 실패. 사용자 실제 강의 파일이 정확히 이 케이스였다.
   → `audio.media_arg()`로 항상 절대 경로 전달, `collect_inputs`도 절대 경로 반환.
   회귀 테스트 2건 추가.
2. **출력 파일 권한 0600** — `tempfile.mkstemp` 기본값이 그대로 남음.
   → umask 반영 권한(0644)으로 `chmod` 후 `os.replace`.

### 알려진 미구현 (계획대로 후속 마일스톤)

- md/srt/vtt/json 출력 → M3
- 프롬프트 합성·토큰 예산·후처리 교정 → M2
- 다중 파일 큐/진행률 JSON/취소 종료 코드 정밀화 → M3


---

## M2 — 프롬프트 파이프라인 + 환각 억제 + 후처리 교정 ✅ 완료 (2026-09-02)

### 작성된 파일

| 파일 | 역할 |
|---|---|
| `prompt.py` | 주제/용어 → 발화형 문장 합성, 조사 자동 선택, 토큰 예산(223 클램프), 뒤에서부터 절삭 + 경고 |
| `postprocess.py` | 정확 매칭 교정, rapidfuzz 유사도 교정(기본 off), 반복 구간 감지, 출력 붕괴·앞 구간 누락 감지 |
| `audio.first_speech_offset()` | ffmpeg silencedetect로 발화 시작 시각 탐지(앞 구간 누락 판정용) |
| `engine.py` | 프롬프트 계획 주입, 2단계 폴백, 후처리 파이프라인 연결 |
| `cli.py` | `--topic` `--preset` `--glossary` `--no-prompt` `--no-initial-prompt` `--no-hotwords` `--no-repeat-glossary` `--fuzzy` |

### ★ 실측으로 확인한 프롬프트 부작용 (M2 최대 발견)

45분 강의의 25분 지점 90초 발췌로 프롬프트 조건만 바꿔 5회 전사:

| 실행 | initial_prompt | hotwords | 앞 구간 | 전문 용어 |
|---|---|---|---|---|
| A | ✗ | ✗ | **보존** | `100대 가중형 경율`, `잡음`(운좋게) |
| B | ✓ (내용 불일치 용어집) | ✓ | **25초 누락** | `백세, 아우션, 방위률`, **`잡음`→`자궁`** |
| C | ✓ (내용 일치, 149토큰) | ✓ | **25초 누락** | `백색, 가우시안, AWGN, 열잡음` ✅ |
| D | ✗ | ✓ | **보존** | `다중 경로`, `백색, 가우시안, AWGN` ✅ |
| E | ✓ (짧게, 96토큰) | ✓ | **25초 누락** | `백색, 가우시안, AWGN` ✅ |

결론 두 가지:
1. **`initial_prompt`가 있으면 오디오 앞부분이 통째로 누락된다.** 프롬프트 길이와 무관하다
   (149토큰·96토큰 모두 동일). Whisper가 프롬프트를 "이미 말한 내용"으로 해석해
   앞 구간을 건너뛰는 것으로 보인다. `hotwords`만 쓰면 발생하지 않는다.
2. **주제와 무관한 용어집은 정확도를 떨어뜨린다** (`잡음`을 `자궁`으로). 프롬프트는
   내용과 맞을 때만 도움이 된다.

### 대응 (구현 완료)

- `audio.first_speech_offset()` + `postprocess.detect_head_loss()`로 앞 구간 누락을 자동 감지
- 2단계 폴백:
  - **전체 붕괴**(빈 출력·프롬프트 반향·반복 붕괴) → 프롬프트 전부 제거 후 재전사
  - **부분 붕괴**(앞 구간 누락) → `initial_prompt`만 제거, `hotwords`는 유지해 용어 효과 보존
- `prompt.repeat_glossary_in_sentence` 옵션 추가(용어를 문장에 중복하지 않아 프롬프트를 짧게 유지)
- 모든 폴백은 경고를 남긴다. 조용히 넘어가지 않는다.

실제 동작 확인:
```
WARNING: 프롬프트 적용 결과가 비정상(앞 구간 25.1초 누락 의심
         (발화 시작 1.6초, 첫 세그먼트 26.8초)). initial_prompt 없이(hotwords 유지) 재전사합니다.
```
재전사 결과는 앞부분(`채널마다 다르게 다중 경로든지…`)이 복구되고 용어도 정확했다.

### 용어 교정 실증 (동일 클립, 교정 사전 적용 전/후)

같은 파라미터로 두 번 돌리면 원문 전사 결과가 **완전히 동일**했다(결정적).
관찰된 오인식을 프리셋 `corrections`에 넣고 재실행하니 그대로 교정되었다.

```
INFO: 용어 교정: 반조체 → 반도체 (2회, 정확)
INFO: 용어 교정: 자극하는 → 작용하는 (1회, 정확)
INFO: 용어 교정: 가우스 → 가우시안 (1회, 정확)
```

### mlx 백엔드 (M2 말 구현, `uv sync --extra mlx`)

설치본 실측(mlx-whisper 0.4.3)으로 확인한 faster-whisper와의 차이:

| 기능 | faster | mlx |
|---|---|---|
| `hotwords` | ✅ | **없음** |
| Silero VAD | ✅ | **없음** |
| 빔 서치 | ✅ | **미구현** (`NotImplementedError`) |
| `prompt_reset_on_temperature` | ✅ | 없음 |
| `initial_prompt` / `condition_on_previous_text` | ✅ | ✅ |
| `hallucination_silence_threshold` | ✅ | ✅ |
| 세그먼트 지연 생성(진행률) | ✅ | **없음**(완료 후 일괄 반환) |

무시되는 옵션은 실행 시 경고로 노출된다:
```
WARNING: mlx 백엔드에서 무시되는 옵션: prompt_reset_on_temperature
WARNING: mlx 백엔드에서 무시되는 옵션: beam_size=5(빔 서치 미구현, 그리디 사용)
WARNING: mlx 백엔드에서 무시되는 옵션: vad_filter
```

**속도 vs 품질 실측 (90초 클립, large-v3)**

| 백엔드/모드 | 소요 | 배속 | 45분 환산 | 품질 |
|---|---|---|---|---|
| faster 순차 | ~64초 | 1.4× | 약 32분 | 기준 |
| faster batched | ~38초 | 2.4× | 약 19분 | 약간 열화 |
| **mlx (GPU)** | **18.1초** | **5.0×** | **약 9분** | **반복·앞구간 누락 발생** |

mlx는 3.5배 빠르지만 빔 서치·VAD가 없어 `가중 경로 어떻게? 가중 경로 어떻게?` 같은
반복과 앞 구간 누락이 나타났다. 기본 백엔드는 faster 유지가 타당하다.

### HF 모델 다운로드 우회 (실측 대응)

`mlx-community/whisper-large-v3-mlx` 다운로드가 Xet(CAS) 전송 오류로 2회 연속 실패했다.
`HF_HUB_DISABLE_XET=1`로 성공. 사용자가 원인을 알기 어려우므로
`_download_with_xet_fallback()`으로 **자동 우회 재시도**를 넣었다(양 백엔드 공통).

### 검증 상태

- `uv run pytest -q` → **88 passed** (prompt 21, postprocess 25, backends 8 신규)
- `uv run mypy --strict` → Success (14 files)
- 224 토큰 초과 절삭: 실제 large-v3 토크나이저로 용어 300개 투입 → 223 토큰 이내 절삭 + 경고
- mlx 백엔드 tiny 모델 전사 성공, capabilities 경고 3종 정상 노출


---

## 기본값 변경 (사용자 승인, 2026-09-02)

`prompt.use_initial_prompt` 기본값 **True → False** (hotwords 단독).
설정 스키마를 **v2**로 올리고 `_migrate_1_to_2()`에서 기존 v1 설정의 True를 False로 내린다.
다시 켜려면 설정 또는 `--initial-prompt`.

---

## M3 — 다중 파일 큐 / 진행률 JSON / 취소 / 출력 포맷 전체 ✅ 완료 (2026-09-02)

### 작성·변경된 파일

| 파일 | 내용 |
|---|---|
| `writer.py` | `render_md`(섹션 헤더 `## [HH:MM:SS]`, front matter 자리), `render_srt`, `render_vtt`, `render_json`, `render()` 디스패처 |
| `engine.py` | `run_queue()` (오디오 **총 길이 가중** 전체 진행률, 파일별 오류 격리, 취소 전파), `build_meta()` |
| `cli.py` | `--format`(반복), `--progress-json`, `--json`, `--stdout`, `--notify`, `--initial-prompt`, `--no-prompt-fallback`, JSON Lines stderr 래퍼 |
| `notify.py` | osascript 알림, Finder reveal |
| `config.py` | 스키마 v2 + 마이그레이션 |
| `tests/test_cli.py` | 스텁 백엔드 기반 큐/CLI 통합 테스트 13건 |

### 검증 결과

| 항목 | 결과 |
|---|---|
| 5개 파일 배치(정상3+손상1+0바이트1+pdf1) | 정상 3건 × 5포맷 = 15파일 생성, 실패 2건 격리, pdf 큐 제외 |
| 까다로운 파일명 | `9:1 전자회로 & 실습.m4a`, `강의 "인용" 포함 🎧.M4A`(대문자 확장자), `lecture'quote.mp3` 전부 통과 |
| 종료 코드 | 전체 성공 0 / 일부 실패 1 / 전체 실패 2 / 대상 없음 2 / 취소 130 — 전부 실측 확인 |
| 취소(SIGINT) | 파일1 저장 완료 후 파일2 진행 중 취소 → 부분 결과 보존, **임시파일 0개**, 종료 130 |
| `--json` | `jq -e`로 stdout 단독 파싱 성공. 실패 케이스에서도 유효 JSON + 종료 코드 2 |
| `--progress-json` | stderr **13줄 전부 유효 JSON**(비-JSON 0줄). 이벤트: `prompt`/`progress`/`log`/`file_done`/`queue_done` |
| `--stdout` | 파일 미생성, 텍스트만 stdout |
| 폴더 재귀 입력 | `--recursive`로 하위 폴더 파일 포함 확인 |

### stderr JSON Lines 처리

`huggingface_hub`가 평문 경고를 stderr로 직접 찍어 JSON Lines 스트림이 깨졌다.
`JsonLineStderr` 래퍼로 stderr 전체를 감싸 평문 줄을 `{"event":"log",...}`로 변환한다.
에이전트가 stderr를 한 줄씩 파싱해도 안전하다.

### 검증 명령

```bash
uv run pytest -q                                   # 117 passed
uv run mypy --strict                               # Success (15 files)
lecture-scribe FILE --json | jq -e .                # stdout 단독 파싱
lecture-scribe FILE --progress-json 2>&1 >/dev/null # 전 라인 JSON
```


---

## M4 — GUI ✅ 완료 (2026-09-02)

### 작성된 파일

| 파일 | 역할 |
|---|---|
| `gui/strings_ko.py` | 한국어 UI 문자열 집중 |
| `gui/worker.py` | `TranscribeWorker` / `TokenCountWorker` (QThread) |
| `gui/settings_panel.py` | 프리셋 CRUD, 주제/용어, 실시간 토큰 표시, 고급 디스클로저 |
| `gui/dropzone.py` | 유휴(`+`) / 큐 / 완료 3상태 전환, 드래그 피드백 |
| `gui/window.py` | 정방형 강제, 40:60 레이아웃, 백엔드 캐시, 워커 배선 |
| `gui/app.py` | 진입점 (`lecture-scribe-gui`, `lecture-scribe --open-gui`) |

### 검증 결과

| 항목 | 결과 |
|---|---|
| 정방형 강제 | 900×600→600×600, 500×820→500×500, 300×300→480×480, 1200×1000→1000×1000 (전부 1:1) |
| 최소 크기 / 레이아웃 | 480×480 / 설정 40 : 드롭존 60 |
| 실제 전사(2파일, tiny) | 12.0초, 진행률 이벤트 16회, 완료 화면 전환, 결과 2건 |
| **UI 응답성** | 50ms 타이머 기준 **최대 지연 143ms** (수정 전 975ms) |
| 고급 설정 | 기본 접힘, 펼치면 백엔드·포맷·충돌·프롬프트·VAD·빔·유사도 표시 |
| 토큰 초과 표시 | 빨간색 + 잘릴 용어 나열 (`248 / 223 토큰 — 2개 용어가 잘립니다: …`) |
| 백엔드 능력 반영 | mlx 선택 시 hotwords/VAD/빔 위젯 비활성 + 툴팁 |

### M4에서 발견·수정한 버그

1. **QFormLayout 안 체크박스 높이 0** — 부모 없이 만든 `QHBoxLayout`을 나중에
   `setLayout()`으로 붙이면 높이가 잡히지 않아 "출력 포맷" 체크박스가 렌더링되지 않았다.
   → 레이아웃을 부모 위젯과 함께 생성. 회귀 테스트 추가.
2. **UI 블로킹 975ms** — `_start_transcription()`이 UI 스레드에서 백엔드를 새로 만들고
   토크나이저를 로드했다. → 백엔드 인스턴스 캐시 + 프롬프트 계획 생성을 워커로 이동.
   최대 지연 975ms → 143ms.
3. **테스트가 모달 다이얼로그에서 무한 대기** — `QMessageBox.information`이 이벤트 루프를
   막았다(스택 샘플로 확인). → 테스트에서 모달을 스텁 처리.

---

## M5 — Quick Action ✅ 완료 (2026-09-02)

### 작성된 파일

| 파일 | 역할 |
|---|---|
| `quickaction/build_workflows.py` | `.workflow` 번들 생성기(plistlib) |
| `quickaction/Transcribe.workflow` | "LectureScribe로 전사" (즉시 전사 + 알림) |
| `quickaction/TranscribeOpenApp.workflow` | "LectureScribe에서 열기" (GUI 큐 적재) |
| `quickaction/install.sh` / `uninstall.sh` | 절대 경로 탐지·치환, `~/Library/Services` 설치, Finder 갱신 |

### 검증 결과

| 항목 | 결과 |
|---|---|
| 번들 유효성 | `plutil -lint` 통과 (document.wflow, Info.plist) |
| 서비스 등록 | `pbs -dump`에 2건 노출("LectureScribe로 전사", "LectureScribe에서 열기"), 비활성 목록 없음 |
| 절대 경로 치환 | `BIN=/Users/…/.venv/bin/lecture-scribe`, `FFMPEG_DIR=/opt/homebrew/bin`, 플레이스홀더 잔여 0 |
| 다중 파일 단일 호출 | `inputMethod=1`, 3개 파일이 한 프로세스에서 순차 처리됨(로그의 모델 재사용 시간으로 확인: 4.2초 → 0.4초 → 0.8초) |
| 까다로운 파일명 | `9:1 통신 시스템 & 실습.m4a`, `강의 "인용" 포함 🎧.M4A`, `lecture's note.m4a` 전부 성공 |
| 깨끗한 환경 실행 | `env -i`(PATH 없음)에서도 성공 — Finder 컨텍스트 재현 |
| 종료 코드 | 성공 0 / 손상 파일 포함 1 / 파일 없음 1 |

### M5에서 발견·수정한 버그

**zsh `status`는 읽기 전용 변수** — `status=$?`가
`read-only variable: status`로 실패해 정상 전사에도 종료 코드 1을 반환했다.
`bash`에서는 문제없지만 Quick Action은 `/bin/zsh`로 돈다.
→ `rc=$?`로 변경. 회귀 테스트 추가.

### 검증 명령

```bash
uv run python quickaction/build_workflows.py && ./quickaction/install.sh
/System/Library/CoreServices/pbs -dump | grep LectureScribe
QT_QPA_PLATFORM=offscreen uv run pytest -q     # 151 passed
```


---

## M6 — Cowork 연계 ✅ 완료 (2026-09-02)

### 작성된 파일

| 파일 | 역할 |
|---|---|
| `writer.py` | YAML front matter 생성·파싱(PyYAML 없이), `⟨?⟩` 저신뢰 마커, N분 분할 |
| `index.py` | `index.jsonl` append(`fcntl.flock`)·조회·쿼리, front matter 기반 `rebuild` |
| `mirror.py` | 워크스페이스 미러, 하드링크→copy 자동 강등, `<상위폴더>__<이름>` 접두 |
| `handoff.py` | `.handoff.md` 템플릿 조립 (**LLM 미사용**) |
| `engine.py` | 사이드카·미러·인덱스·핸드오프까지 배치, 저신뢰 비율 계산 |
| `cli.py` | `--emit-handoff`, `--split-md`, `reindex`/`list` 서브커맨드 |
| `cowork/skills/lecture-transcribe/SKILL.md` | 후속 작업 규칙 포함 스킬 |
| `cowork/install_skill.sh` | 스킬 디렉터리 **탐색**(하드코딩 없음), 실패 시 수동 안내 |

### 검증 결과

| 항목 | 결과 |
|---|---|
| front matter | 콜론·따옴표 포함 주제(`전자회로: 채널 "잡음"과 AWGN`)도 인용되어 왕복 파싱 성공 |
| `⟨?⟩` 마커 | tiny 모델로 저신뢰 유도 → 마커 4개 삽입, `low_confidence_ratio: 1.0` |
| 섹션 헤더 | `## [00:00:00]`, `## [00:10:00]` … 세그먼트 시각 기준 |
| 사이드카 | `<basename>.transcript.json` — 세그먼트별 신뢰도 + 설정 스냅샷 |
| 인덱스 | 전사 2건 → 2행. `reindex`가 **0.1초**에 재구축(전사 재수행 없음) |
| `list` | 텍스트/`--json` 조회, `--topic`/`--since` 필터 |
| 미러 | 같은 볼륨 → 하드링크(`st_nlink == 2`), **다른 볼륨(hdiutil DMG) → copy 자동 강등 + 경고** |
| 동시 append | 프로세스 2개 × 50행 = 100행, 깨진 행 0 |
| `--split-md 1` | `part1.md`, `part2.md` 생성, 각 파트에 `part: 2/2`, `covers: "00:01:00–00:02:00"` |
| `--json` | `outputs: ["md","json","transcript.json","handoff.md"]` — jq 단독 파싱 성공 |
| 핸드오프 | 메타·용어·교정 이력·저신뢰 구간·지시 예시 3종 포함, **본문은 링크만** |
| 스킬 설치 | `~/.claude/skills/lecture-transcribe` 탐색 후 설치, 실행 경로 자동 치환 |
| **Cowork 시연** | 스킬 호출 → 전사 → md 읽기 → `[HH:MM:SS]` 인용 요약까지 한 세션에서 연결 확인 |

### M6에서 발견·수정한 버그

1. **섹션 헤더 누락** — 한 문단이 섹션 경계를 넘으면 `## [00:10:00]` 헤더가 통째로
   빠졌다(문단 기준으로 헤더를 찍고 있었음). → 세그먼트 시각 기준으로 재구성.
2. **`IndexEntry.__dict__` 없음** — `slots=True` 데이터클래스라 `list --json`이
   `AttributeError`로 죽었다. → `dataclasses.asdict()`.
3. **`QPixmap.save()` 조용한 실패** — 대상 폴더가 없으면 False만 돌려주고 예외가 없다
   (아이콘 생성 실패의 원인). → 작업 폴더 선생성.

---

## M7 — 패키징·문서 ✅ 완료 (2026-09-02)

### 작성된 파일

| 파일 | 역할 |
|---|---|
| `packaging/make_app.py` | `LectureScribe.app` 번들 생성기(래퍼 방식), Qt로 아이콘 생성 + `iconutil` |
| `install.sh` / `uninstall.sh` | 전체 설치·제거 (의존성 → 앱 → Quick Action → 스킬) |
| `README.md` | 설치·사용법·주제/용어 작성 요령(좋은 예·나쁜 예)·**Cowork에서 이어서 작업하기** |
| `TROUBLESHOOTING.md` | ffmpeg, PATH, Gatekeeper, 권한, iCloud 스텁, 모델 다운로드, 환각 파라미터, 알려진 함정 |
| `gui/app.py` | `QFileOpenEvent` 처리(Finder "다음으로 열기", Dock 드롭) |

### `.app` 방식 결정

**프로젝트 venv를 실행하는 경량 래퍼 앱**을 택했다.

- 번들 420KB, 빌드 수 초. 아이콘·Dock·Launchpad·"다음으로 열기"·Dock 드롭 모두 동작.
- ad-hoc 서명(`codesign -s -`)으로 Gatekeeper 경고를 줄였다.
- 한계: 이 기기 전용(프로젝트 폴더와 `.venv` 필요). 다른 Mac으로 배포하려면
  PyInstaller 자립 번들이 필요하다 — README에 명시.

### 클린 환경 검증

`.venv`·`dist` 제외하고 프로젝트를 복사한 뒤 문서 절차대로 `./install.sh` 실행:

| 항목 | 결과 |
|---|---|
| `uv sync` | 성공(새 venv) |
| `.app` 생성 | 420K, 아이콘 있음 |
| Quick Action 설치 | 2종, 절대 경로 치환 완료 |
| 스킬 설치 | 성공 |
| CLI 전사 | 성공 |
| 테스트 | **173 passed** (클린 복사본에서도 동일) |

검증 후 원래 설치본으로 복구(Quick Action·스킬 경로 재설치).


---

## 45분 실제 강의 전체 전사 ✅ (2026-09-02)

`9:1 전자회로.m4a` (45분 12초) 전체를 large-v3 순차 모드로 전사.

| 항목 | 값 |
|---|---|
| 오디오 길이 | 2712.9초 (45분 13초) |
| 소요 시간 | **2334초 (38분 54초)** = 1.16× 실시간 |
| 세그먼트 | 547개 |
| 평균 avg_logprob | -0.339 |
| **저신뢰 비율** | **2.01%** (`⟨?⟩` 마커 12개) |
| 섹션 헤더 | 5개 (00:00 / 00:10 / 00:20 / 00:30 / 00:40) |
| 용어 교정 | 1건 (`가우스 → 가우시안`) |
| 메모리(RSS) | 3.3–5.5GB 사이 변동, 누수 없음(16GB 기기에서 여유) |
| 생성물 | `.md`(30K) `.txt`(29K) `.srt`(48K) `.transcript.json`(145K) `.handoff.md`(2.3K) |
| 미러 | `~/Documents/LectureScribe/전자회로__9:1 전자회로.*` (하드링크) |
| 원본 | mtime·size 불변 |

앞서 60초 클립으로 추정한 1.4× 대비 실제 1.16×. 45분 기준 약 39분.

## 추가로 발견·수정한 문제

1. **테스트가 사용자 실제 워크스페이스를 오염** — 기본 `Settings()`의
   `cowork.workspace_dir`이 `~/Documents/LectureScribe`라서 테스트 실행 시
   `test_run_queue_*` 파일과 인덱스 항목이 실제 폴더에 쌓였다.
   → `conftest.py`에 HOME 격리 autouse 픽스처 추가(HOME 환경변수 + `Path.home()` 동시 패치).
   격리 후 "테스트 전 6개 → 후 6개" 확인.
2. **무음 파일이 0바이트로 저장** — 오류로 오해하기 쉽다.
   → 세그먼트가 없으면 이유를 파일 상단 주석으로 남기고 경고에도 넣는다. 테스트 추가.

## §13 체크리스트 최종 상태

| 항목 | 상태 |
|---|---|
| 공백·한글·`&`·따옴표·이모지 파일명 | ✅ |
| 대문자 확장자 `.M4A` | ✅ |
| 충돌 정책 3종 | ✅ |
| 읽기 전용 폴더 → 대체 폴더 | ✅ (단위 테스트) |
| iCloud 스텁 | ✅ (단위 테스트) + 실제 iCloud 파일 전사 성공 |
| 0바이트·손상·오디오 없는 파일 | ✅ |
| 완전 무음 30초 → 환각 없음 | ✅ 세그먼트 0개, 안내 주석 |
| 45분 장시간 → 메모리·진행률 | ✅ |
| 취소 시 임시 파일 잔여 | ✅ 0개 |
| 모델 미다운로드 첫 실행 | ✅ (Xet 실패 자동 우회 포함) |
| 프롬프트 붕괴 폴백 | ✅ 앞 구간 누락 자동 감지 + 재전사 |
| `--json` stdout 순수성 | ✅ `jq -e` 통과 |
| `--json` 실패 케이스 | ✅ 유효 JSON + 종료 코드 2 |
| front matter YAML(콜론·따옴표) | ✅ |
| 다른 볼륨 하드링크 → copy 강등 | ✅ (hdiutil DMG) |
| 인덱스 동시 append | ✅ 100행 무결 |
| reindex가 전사 재수행 안 함 | ✅ 0.1초 |


---

## 모델 비교 + 성능 최적화 (2026-09-03)

### 모델 3종 실측 → 2종으로 정리

같은 강의의 성격 다른 구간 3개(행정 60초 / 기술 90초 / 후반 90초) 동일 조건 비교.

| 모델 | 배속(순수 전사) | 특성 |
|---|---|---|
| `large-v3` | 1.6× | 가장 안정적 |
| `large-v3-turbo` | 5.5× (배치 7.2×) | 3.4배 빠름, 음질 나쁜 구간에서 문장 끊김 |
| `large-v3-turbo-ko` | 2.3× | ❌ 출력 90% 소실 + 반복 루프 → **목록에서 제거** |

한국어 파인튜닝 모델은 프롬프트 문제가 아니었다(`--no-prompt`, VAD off로 격리 확인).
`…라고 조언했다` 같은 기사체가 튀어나오는 것으로 보아 뉴스·방송 도메인 과적합이다.

### 이 비교가 드러낸 안전장치 구멍 3건 (수정 완료)

1. **출력량 붕괴 미감지** — 임계값이 전체 길이 초당 0.15자였다. 정상 한국어는 초당 7.5자인데
   초당 0.25자 출력이 통과했다. → **VAD 발화 구간 기준 초당 0.8자**로 변경(무음 오탐 없음).
2. **세그먼트 안쪽 반복 루프 미감지** — `확보 확보 ×17`이 한 세그먼트 안에 있어 세그먼트 간
   비교로는 안 잡혔다. → `find_repeated_phrases()` 추가.
3. **폴백 재전사 후 재검사 누락** — 프롬프트를 빼고 다시 돌린 결과가 여전히 망가져도 조용했다.
   → 최종 결과 재검사 + 결과 파일 상단 품질 경고 주석.

### 성능 프로파일링 결과

| 구간 | 시간 | 비중 |
|---|---|---|
| 추론(CTranslate2) | 9.76초 | **99.997%** |
| 앱 코드(후처리·교정·렌더링 전체) | 0.3ms | 0.003% |

**앱 코드에는 최적화 여지가 없다.** 성능은 전적으로 모델·파라미터 선택 문제다.

### 파라미터 스윕 (large-v3, 60초 클립, 로드 제외)

| 파라미터 | 결과 | 적용 |
|---|---|---|
| `cpu_threads` | 자동 1.60× / 6 1.61× / 8 1.41× / **10 0.85×** | 자동(0) 유지 + 설정 노출 |
| `compute_type` | int8 1.6× / int8_float32 1.6× / **float32 0.7×** | int8 유지 |
| `beam_size` | 3 → 2.2~2.4× / 5 → 1.4~2.0× (품질 무승부) | 기본 5 유지, `--beam-size`로 노출 |

### 적용한 최적화

1. **ffprobe 중복 호출 제거** — 큐 가중치 계산과 전사에서 같은 파일을 두 번 probe 하던 것을
   (경로, mtime, size) 키 캐시로 제거. 3파일 기준 96.7ms → 0.1ms.
2. `cpu_threads` 설정 노출 (`settings.json`, `--cpu-threads`)
3. `--beam-size` 노출

### 뉴럴 엔진(ANE) — 사용 불가 (실측)

```
ctranslate2 4.8.2  지원 device: ['cpu', 'auto']   # Metal/ANE 없음
mlx                default device: Device(gpu, 0) # Metal GPU, ANE 아님
```

ANE는 Core ML로만 접근 가능하다. 두 런타임 다 Core ML을 쓰지 않으므로 M1 Pro의
16코어 ANE는 이 앱에서 사용되지 않는다. 쓰려면 whisper.cpp(Core ML 인코더) 또는
WhisperKit 같은 런타임 추가가 필요하다(§4 스택 변경 → 승인 필요).


---

## Core ML(ANE) 실측 — 채택하지 않음 (2026-09-03)

사용자 요청으로 whisper.cpp를 Core ML 인코더와 함께 빌드해 직접 측정했다.

### 준비 과정

| 단계 | 내용 |
|---|---|
| 툴체인 | `coremlcompiler`는 **full Xcode 필요**(CLT엔 없음) → 변환 대신 **사전 컴파일본** 사용 |
| 모델 | `ggerganov/whisper.cpp`의 `ggml-large-v3-encoder.mlmodelc.zip`(1.1GB) 다운로드 |
| 빌드 | `cmake -DWHISPER_COREML=1 -DWHISPER_COREML_ALLOW_FALLBACK=1` — CLT SDK에 CoreML.framework 있어 성공 |

### 결과: ANE 이득 없음

| 실행 | 240초 총 시간 | 인코더 1회 |
|---|---|---|
| whisper.cpp + Core ML(ANE) | 45.2초 | 810ms |
| whisper.cpp + Metal GPU만 | **43.4초** | **805ms** |

M1 Pro에서 large-v3 인코더는 ANE와 Metal GPU 성능이 동일하다. 첫 실행은 ANE 컴파일
캐시(28MB, `~/Library/Caches/com.apple.e5rt.e5bundlecache`) 생성으로 오히려 40% 느리다.

### 부수 발견: whisper.cpp(Metal)는 2.5~3.4배 빠르다 — 그러나 채택 불가

| 백엔드 | 배속 | CPU 사용 | 용어 고정 |
|---|---|---|---|
| faster-whisper (CTranslate2 CPU) | 1.6~2.2× | 전 코어 | **hotwords ✅** |
| whisper.cpp (Metal GPU) | **5.5×** | user 2.2초뿐 | **hotwords 없음** |

whisper.cpp에는 `hotwords`가 없고 `--prompt`만 있다. 용어집을 넣으면 **프롬프트가 출력에
그대로 새어 나온다**:

```
--prompt "잡음, AWGN, 열잡음, …"
→ "백색 가우시안, AWGN, 열잡음, 도체, 반도체, 신호 대 잡음, 가우시안, AWGN, …"
```

`--carry-initial-prompt`(매 윈도우 유지)로도 동일했다. 이 앱의 핵심 기능인
**주제·용어 기반 전사 유도를 잃으므로 백엔드로 채택하지 않았다.**

### beam_size 기본값 변경 (사용자 승인)

`decoding.beam_size` **5 → 3**. 7개 클립 실측에서 27% 빠르고 품질은 무승부.
`--beam-size 5`로 되돌릴 수 있다.

### 텍스트 문맥 교정 — 현행 유지 (사용자 결정)

앱은 축자 전사 + `⟨?⟩` 마커 + 결정적 용어 교정까지만 한다.
문맥 기반 추론 교정은 Cowork(Claude) 단계에서 수행한다(§15-1 준수).


---

## 자원 사용 실측 + 병렬 처리 (2026-09-03)

### 디스크 정리

whisper.cpp 실험 산출물 제거로 **17GB 확보**(373GiB → 390GiB 여유).
남은 모델 캐시는 실제 사용분만: large-v3(2.9G), large-v3-turbo(1.5G), mlx large-v3(2.9G), tiny 2종.

### 실측: CPU 절반만 쓰고 GPU는 전혀 안 쓴다

| 항목 | 값 |
|---|---|
| CPU (단일 파일) | 평균 **439%** / 최대 505% (10코어 = 1000%) → **절반 유휴** |
| GPU (Metal) | **0%** — CTranslate2가 CPU 전용 |
| 메모리 | 평균 3.0GB / 최대 **3.5GB** (beam 3 기준) |

CPU를 다 못 쓰는 건 Whisper 디코딩이 자기회귀(autoregressive)라 구조적으로 병렬화가
제한되기 때문이다. 스레드를 늘리면 오히려 느려진다(실측: 10스레드 0.85배속).

### 대응: 파일 단위 동시 전사

같은 모델 인스턴스를 공유하며 여러 파일을 동시에 전사한다(CTranslate2 `num_workers`).

| 동시 수 | 3파일 시간 | CPU | 메모리 peak | 결과 일치 |
|---|---|---|---|---|
| 1 | 105.4초 | 439% | 3.5GB | 기준 |
| **2 (기본값)** | **80.0초 (1.32×)** | 673% | 4.3GB | **완전 동일 ✅** |
| 3 | 90.7초 (1.16×) | 808% | 5.2GB | 동일하나 더 느림 |

- 모델 가중치를 공유하므로 메모리는 **25%만** 증가(2배가 아님)
- 순차/동시 결과가 **바이트 단위로 동일**함을 3개 클립에서 확인
- 기기 사양 자동 상한: `코어 // 4`, `(전체 메모리/2 − 모델 상주분) / 1GB` 중 작은 값
- `--parallel N` / `settings.json`의 `max_parallel_files`

### beam 3의 부수 효과: 메모리 35% 감소

beam 5 → 3으로 낮추면서 메모리 peak도 **5.3GB → 3.5GB**로 줄었다.

### 자동 hotwords 아이디어 실측 — 효과 없음

"1차 전사에서 빈출어를 뽑아 hotwords로 2차 전사" 방식을 실제로 돌려봤다.

| 방식 | 핵심 용어 적중 |
|---|---|
| 1차 (hotwords 없음) | 2/6 |
| 2차 (1차에서 자동 추출) | **2/6 — 개선 없음** |
| 사람이 쓴 용어집 | **6/6** |

추출된 목록: `['가중', '다른', '것은', '가우션', '우리가', '도체', '노이즈']`

**구조적 이유**: 1차에서 제대로 인식된 단어는 hotwords가 필요 없고, 잘못 인식된 단어는
애초에 후보에 오르지 못한다. 오히려 오인식(`가중`←다중, `가우션`←가우시안)이 hotwords로
들어가 2차에서 **오류가 고착**됐다(`가우션 경로`가 더 늘어남).


---

## 배포용 자립 번들 + DMG (2026-09-03)

### 문제

기존 `.app`은 `packaging/make_app.py`가 만든 **래퍼**로, 프로젝트 `.venv`의 절대 경로를
실행한다. 이 기기 전용이라 **공유가 불가능**했다.

### 해결: PyInstaller 자립 번들

| 항목 | 값 |
|---|---|
| `.app` 크기 | 258MB |
| DMG 크기 | **104MB** (UDZO 압축) |
| 포함 | Python 3.12 런타임, PySide6, faster-whisper, ctranslate2, onnxruntime, av, tokenizers, rapidfuzz |
| 제외 | mlx/torch(3GB), PySide6 미사용 모듈 15종, scipy, tkinter |
| 받는 쪽 준비물 | `brew install ffmpeg` 뿐 (모델은 첫 실행 시 자동) |

- `entry_app.py`에 `--cli` 스위치를 넣어 **번들 하나로 GUI와 CLI를 모두** 제공
- ad-hoc 서명(`codesign -s -`), 첫 실행은 우클릭 → 열기 필요
- `packaging/build_dmg.sh`로 전 과정 재현 가능

### DMG 구성

```
LectureScribe.app          자립 실행 번들
Applications ->            드래그 설치용 심볼릭 링크
먼저 읽어주세요.txt          설치·사용·주제/용어 작성법·속도 기준·문제 해결
추가 도구/Quick Action 설치.command   Finder 우클릭 메뉴 설치(번들 경로 기준)
```

### 검증

DMG를 마운트해 **환경변수를 모두 제거한 셸**(`env -i`)에서 실행:

```
{"status":"ok","segs":5,"backend":"faster","out":"/tmp/dmgtest/A_행정공지.txt"}
```

프로젝트 venv와 무관하게 전사 성공. 코드 서명 검증도 통과
(`valid on disk`, `satisfies its Designated Requirement`).

### 이 과정에서 고친 버그

**백엔드 미설치 시 하드 실패** — 사용자 설정이 `backend: mlx`인 상태로 배포 번들을 쓰면
`mlx-whisper가 설치되어 있지 않습니다`로 전사 자체가 실패했다.
→ `make_backend()`가 `is_available()`을 확인해 **faster-whisper로 자동 폴백**(경고 로그).
CLI·GUI 양쪽에 적용, 회귀 테스트 2건 추가.


---

## 사용자 보고 버그 수정 + 큐 재설계 (2026-09-03)

### 버그 1: 전사 중 파일 추가 시 진행률 0으로 초기화

`MainWindow.add_files()`가 `DropZone.show_queue()`를 호출했고, 이 메서드는
`queue_list.clear()` + `_rows.clear()`로 **큐를 통째로 다시 그렸다.**
진행 중인 행이 새 위젯으로 교체되어 진행률이 0이 되고, 전체 진행률 바도 0으로
리셋됐다. 게다가 추가된 파일은 이미 돌고 있는 워커에 전달되지 않았다.

**수정**: 큐를 **작업 큐(job queue)** 방식으로 재설계.

| 이전 | 이후 |
|---|---|
| `run_queue(고정 목록)`을 한 번 실행 | `TranscribeWorker`가 상시 실행되며 `queue.Queue`에서 작업을 꺼냄 |
| 파일 추가 = 큐 전체 재생성 | `add_paths()`가 행을 **덧붙임**(기존 행 불변) |
| 전사 중 설정 잠금 | 잠그지 않음. 작업마다 제출 시점 설정 스냅샷 |
| 전체 파일 하나의 모델 | **파일별 모델 선택**(시작 전까지 변경 가능) |

실제 전사로 검증:
```
1번 파일 전사 시작: B_기술설명.m4a
▶ 진행률 68%에서 2번 파일 추가
  추가 직후 1번 진행률: 68%  (유지 ✅)
최종: B_기술설명 done 100% / A_행정공지 done 100%  전체 2/2 · 100%
```

### 버그 2: Quick Action 진행 표시가 멈춘 것처럼 보임

멈춘 게 아니라 **너무 느렸다.** 사용자 로그:

```
9:2 전자파전파공학 1.m4a   601.7초 오디오 → 1867.6초 소요  (0.32배속)
9:1 이동통신공학.m4a      3014.9초 오디오 → 3172.4초 소요  (0.95배속)
9:2 전자파전파공학 2.m4a  2259.3초 오디오 → 7499.8초 소요  (0.30배속)
17:50:09  동시 전사 2개로 처리합니다(파일 3개)
```

전체 5875초 오디오에 9360초 소요 = **0.63배속**. 벤치마크(1.38배속)의 절반 이하.

**원인**: 동시 전사 2개 + 메모리 부족 → 스왑. 실측으로 확인:

| 2×10분 파일, large-v3 | 시간 | 메모리 peak | 스왑 변화 |
|---|---|---|---|
| 순차 | 871초 (1.38×) | 5,491MB | 없음 |
| 동시 2 | 582초 (2.06×) | **7,706MB** | **+2.2GB** |

여유가 있으면 동시 처리가 1.5배 빠르지만, GUI와 다른 앱이 메모리를 쓰고 있으면
스왑이 터지면서 역전된다(측정 시점 사용자 기기 스왑 2GB 사용 중이었다).

**수정 2가지**:

1. **가용 메모리 기반 동시 실행 제한** — 전체 메모리가 아니라 `vm_stat`의
   실시간 가용량으로 판단한다. 모델 가중치를 공유하므로 첫 1건 5.5GB,
   추가 1건당 2.2GB로 계산한다.

   | 가용 메모리 | 동시 전사 |
   |---|---|
   | 5GB (사용자 상황) | **1개** |
   | 8GB | 1개 |
   | 10GB 이상 | 2개 |

2. **시작 알림** — Quick Action은 진행률을 보여줄 방법이 없어 메뉴 막대 표시만
   돈다. 시작 시점에 예상 시간을 알린다:
   `"37분 분량 전사 시작 · 약 24분 예상"` (모델별 실측 배속 기준)

### 추가된 기능

- **파일별 모델 선택**: 큐 각 행에 모델 콤보박스. 짧은 파일은 turbo, 중요한 강의는
  large-v3처럼 섞어 돌릴 수 있다. 전사가 시작되면 잠긴다.
- **전사 중 프리셋 전환·파일 추가·시작**: 설정 패널을 잠그지 않는다. 작업은 제출
  시점의 설정 스냅샷을 들고 가므로 대기 중인 작업에 영향이 없다.
- **완료 항목이 큐에 남는다**: 결과 파일명을 보여주고 클릭하면 Finder에서 열린다.
  `완료 항목 지우기` 버튼으로 정리.


---

## 우선순위·메모리 최적화 (2026-09-03)

### 실측: 워커 스레드 QoS가 DEFAULT였다

| 컨텍스트 | QoS |
|---|---|
| CLI 메인 스레드 / zsh 워크플로 | USER_INTERACTIVE |
| **QThread / threading.Thread / ThreadPoolExecutor** | **DEFAULT** |

Apple Silicon에서 DEFAULT는 효율 코어로 강등될 수 있다. GUI 전사와 병렬 전사가
전부 워커 스레드에서 도니 해당된다.

**다만 효과는 오차 범위였다.** 경쟁 부하 788% 상태에서 측정:

| QoS | 소요 |
|---|---|
| DEFAULT | 78.2 / 68.4초 |
| USER_INITIATED | 71.3 / 70.9초 |
| USER_INTERACTIVE | 74.6 / 65.4초 |

등급 간 차이보다 실행 간 편차가 컸다. ctranslate2가 모델 로드 시점에 자체 스레드
풀을 만들기 때문으로 보인다(모델 생성 스레드에 QoS를 걸어도 결과 동일).
그래도 의미상 맞는 등급이므로 워커에 `USER_INITIATED`를 지정한다.

**macOS에서 이보다 우선순위를 올리려면 root가 필요하다**(`renice` 음수).
사용자 비밀번호를 요구하지 않는 선에서는 여기가 상한이다.

### 실측: 메모리 반환

| 항목 | 값 |
|---|---|
| large-v3 상주 | 2,412MB |
| large-v3 해제 시 반환 | **1,703MB** (GUI 경로 실측: 2,484 → 781MB) |
| large-v3-turbo 상주 | 1,401MB (**1GB 적음**) |
| 전사 후 힙 반환 | 90초 클립에서는 0MB(반환할 게 없음) |

### 구현

`src/lecture_scribe/perf.py` 신설:

| 함수 | 용도 |
|---|---|
| `set_thread_qos()` | 워커 스레드를 USER_INITIATED로 |
| `release_memory()` | `gc.collect()` + `malloc_zone_pressure_relief` |
| `available_memory_gb()` | `vm_stat` 기반 실시간 가용량 |
| `swap_used_mb()` / `process_rss_mb()` | 진단 |
| `check_memory_headroom()` | 부족하면 가벼운 모델 권고 문구 |

설정 `performance` 절 추가:

```json
"performance": {
  "high_priority": true,
  "release_memory_after_file": true,
  "unload_model_after_idle_min": 10,
  "warn_low_memory": true
}
```

- **유휴 모델 해제**: GUI가 10분 유휴면 모델을 내려 1.7GB를 돌려준다.
  전사가 시작되면 타이머를 멈추고, 전사 중에는 절대 내리지 않는다.
- **파일 단위 메모리 반환**: 전사 1건이 끝날 때마다 힙을 OS에 반환.
- **저메모리 안내**: 시작 전에 가용 메모리를 확인해 부족하면 알린다.
- CLI `--low-priority`로 양보 모드.


---

## GUI 정리 + Dock 중복 아이콘 수정 (2026-09-03)

### 1. 모델 선택지를 2종으로

`MODEL_NAMES = ("large-v3", "large-v3-turbo")`. medium 이하는 한국어 강의 품질이
크게 떨어져 GUI에서 제거했다. CLI는 `--model`로 여전히 아무 모델이나 지정할 수 있다.

### 2. Dock 아이콘 2개 문제

**원인**: `.app` 번들의 `CFBundlePackageType=APPL`이라 **CLI 모드(창 없는 전사
프로세스)도 정식 앱으로 등록**돼 Dock 아이콘이 하나 더 떴다. `lsappinfo`로 확인.

**수정**: `perf.hide_from_dock()` — ApplicationServices의 `TransformProcessType`으로
프로세스를 `kProcessTransformToUIElementApplication`(4)으로 전환한다.
GUI를 띄우지 않는 실행 경로(`cli.main`)에서만 호출한다.

검증:
```
lsappinfo info -only ApplicationType <asn>
  !cgsConnection !signalled type="UIElement"      ← Dock·앱 전환기에서 제외됨
```

### 3. 고급 설정 설명

모든 항목에 툴팁을 붙이고, 고급 설정 상단에 안내 문구를 넣었다.
설명은 전부 이 프로젝트에서 **실측한 내용**을 근거로 쓴다(예: 빔 크기 항목에
"3과 5의 품질 차이가 없었고 3이 27% 빨랐습니다").
테스트로 누락을 막는다(`test_every_advanced_widget_has_explanation`).

### 4. 프리셋 새로 만들기 버튼

`새로 만들기` 버튼 추가. 빈 주제·용어로 프리셋을 만들고 바로 선택하며 주제 입력에
포커스를 준다. 중복 이름이면 안내 후 해당 프리셋으로 전환한다.


---

## GUI·성능 후속 수정 (2026-09-03 저녁)

### 1. Dock 아이콘 2개 — 진짜 원인 발견

이전 수정(CLI 프로세스만 UIElement 전환)으로는 부족했다. 실측:

```
PID 12416  LectureScribe --cli …                          type="UIElement"  ✅
PID 12420  LectureScribe -c "from multiprocessing.reso…"  type="Foreground" ❌
```

**파이썬의 `multiprocessing.resource_tracker`가 번들 실행 파일을 다시 실행**해
정식 앱으로 등록된 것이 두 번째 아이콘이었다.

**수정**: 번들 `Info.plist`에 `LSUIElement=true`(기본은 Dock에 안 뜸)를 넣고,
**창을 띄우는 GUI 프로세스만** `TransformProcessType`으로 Foreground 승격.

검증:
```
GUI 실행       → PID 1개, type="Foreground"   (아이콘 1개)
CLI 전사 중    → PID 2개, 둘 다 type="UIElement"  (아이콘 0개)
```

### 2. 창 크기에 따른 겹침·잘림

설정 패널을 `QScrollArea`에 넣고, 위/아래를 `QSplitter`로 바꿔 사용자가 비율을
조절할 수 있게 했다. 주제 입력의 고정 높이(56px)를 44~96px 범위로 바꿨다.

| 창 크기 | 설정 영역 | 드롭존 |
|---|---|---|
| 480×480 | 190px (스크롤) | 286px |
| 640×640 | 254px | 382px |

### 3. 용어 자동 추가

전사가 끝나면 자주 나온 전문어를 용어 칸에 자동으로 채운다
(`postprocess.suggest_glossary_terms`).

**세 번의 시행착오를 거쳤다**:

| 시도 | 결과 |
|---|---|
| 단순 빈도 | `우리가, 어떻게, 내가, 이게, 뭐야` — 조사 붙은 기능어가 상위 |
| + 조사 분리 | `어떻게, 이렇게, 배웠어, 주시면` — 활용형이 남음 |
| **+ 어미 필터 + 구간 수 기준** | `안테나, 네트워크, 데이터, 전기신호, 시그널, 지향성, CDMA, 인터넷` ✅ |

안전장치:
- **신뢰도 높은 구간에서만**(`avg_logprob >= -0.5`) 뽑는다. 오인식 단어가 용어집에
  들어가면 다음 전사에서 오류가 고착되기 때문(실측 확인).
- 한 구간 반복이 아니라 **서로 다른 3개 이상 구간**에 나온 단어만.
- 용어 **칸에만** 채우고 프리셋에 저장하지는 않는다. 사용자가 보고 고친 뒤 "저장".

### 4. 프롬프트 토큰 한계 (실측)

| 항목 | 값 |
|---|---|
| 하드 한계 | **223 토큰** (Whisper 컨텍스트 448 ÷ 2 − 1). 모델 구조라 못 늘린다 |
| 실제 용어 수용량 | **24개** (실제 강의 용어 기준 221 토큰) |

`initial_prompt`를 끈 기본 설정에서는 223 토큰 전부를 용어에 쓴다.
넘치는 용어는 **교정 사전**(개수 제한 없음)으로 돌리는 게 정답이다.

### 5. GPU 백엔드가 실제로는 CPU로 돌던 문제

사용자가 "GPU 백엔드인데 GPU 사용량이 적다"고 한 이유를 찾았다.
**배포 번들에 mlx가 빠져 있어서** mlx를 골라도 faster-whisper(CPU)로 폴백됐다.

실측(90초 클립, large-v3):

| 백엔드 | 시간 | CPU | **GPU** | 메모리 |
|---|---|---|---|---|
| faster (CPU) | 43.5초 | 415% | **0.4%** | 3.5GB |
| **mlx (Metal GPU)** | **16.7초** | 44% | **72% (최대 100%)** | 2.2GB |

mlx는 **2.6배 빠르고 CPU를 거의 안 쓴다.** 다만 hotwords·VAD·빔 서치가 없어
전문 용어 정확도는 떨어진다.

**수정**: 번들에 mlx 포함. `mlx_whisper`가 torch를 선언만 하고 import하지 않는 것을
확인해 torch(3GB)는 계속 제외했다. numba/llvmlite(123MB)는 `mlx_whisper.timing`이
import 시점에 쓰므로 뺄 수 없었다.

DMG 104MB → **250MB**.

---

## 2026-09-04 — 실사용 버그 6건 수정 (GPU 메모리 / 드롭 / 레이아웃)

사용자 보고 6건. 각각 **원인을 실측으로 특정한 뒤** 고쳤다.

### 1. GPU 전사가 메모리 부족 시 전부 실패 — 원인 확정

`mlx_whisper.transcribe.ModelHolder`가 락 없는 전역 캐시다(설치본 소스 확인).

```python
if cls.model is None or model_path != cls.model_path:
    cls.model = load_model(model_path, dtype=dtype)
```

동일 로직을 그대로 옮겨 재현: **3스레드 동시 진입 → load_model 3회 호출.**
mlx large-v3는 1회 3.1GB → 9.3GB → 16GB 기기에서 전부 OOM.

수정: `_MLX_LOCK`으로 `transcribe()` 직렬화 + `limit_parallel(backend="mlx")`는
항상 1 + 시작 전 가용 메모리 검사(부족하면 Metal 안에서 죽기 전에 대안 안내).

실측 검증: 3스레드 동시 요청 → **로드 1회**, 최고 active 1.51GB.

### 2. 실패 시 메모리 무한 누적 — 누수 2곳

| 누수 | 수정 | 실측 |
|---|---|---|
| `MlxWhisperBackend.unload()`가 `ModelHolder.model`을 안 비움 | `perf.mlx_release_model()` | 2.71GB → **0.00GB** |
| 실패한 백엔드가 `_backend_cache`에 잔류 | 워커가 실패 경로에서 `_dispose_backend()` | 캐시 축출 + `unload()` |

실패 경로 검증: 존재하지 않는 파일로 전사 실패 → 1.20GB 반환, `holder=None`.

### 3. 큐에 행이 있으면 드래그앤드롭 불가

원인 두 가지. `QListWidget`은 **뷰포트**에서 드래그를 가로채는데
`setAcceptDrops(False)`는 위젯에만 걸렸다. 그리고 `dragMoveEvent` 미구현이라
기본 구현이 이벤트를 무시했다. 둘 다 수정.

### 4. 큐 행 내용이 왼쪽에 몰려 붙고 잘림

`item.setSizeHint(row.sizeHint())`가 **폭까지** 내용 기준으로 정해서 행이 좁게
그려졌다. 폭을 뷰포트 폭으로 고정하고, 뷰포트에 이벤트 필터를 걸어 리사이즈에
따라가게 했다(뷰포트 폭은 `DropZone.resizeEvent`보다 늦게 확정된다).
진행 메시지도 18자 잘라내기 → 말줄임 + 툴팁 전체 표시.

### 5. 고급 설정 펼치면 창 자동 확대

`SettingsPanel.advanced_toggled` 신호 추가. 창은 정방형을 유지한 채 필요한
높이만큼 키우고(화면 크기 상한), 접으면 펼치기 직전 크기로 복귀.
실측: 480×480 → 760×760 → 480×480.

### 6. CPU 전사 중 응답 없음 — **재현 실패, 진단 장치 추가**

원인이 아님이 확인된 것:

| 후보 | 실측 |
|---|---|
| UI 스레드 작업량 | 용어 자동 제안 547세그먼트 6.4ms |
| 진행률 시그널 폭주 | 세그먼트 간격 중앙값 3.58초 |
| 전사 중 모달 | 해당 경로 없음 |
| 스레드 과잉 | 45초·동시 2건에서 UI 지연 최대 9.6ms (수정 전에도 정상) |

가장 유력한 건 메모리 압박 → 스왑이고, 그건 위 누수 두 건이 직접 원인이다.
단정할 수 없으므로 `gui/watchdog.py` 추가: 메인 스레드 3초 이상 정지 시
**스택 + RSS + 가용 메모리 + 스왑 + 스레드 수**를 로그에 남긴다.

예방 차원에서 `cpu_threads=0`(전체 코어)도 수정. `perf.usable_cpu_threads()`가
UI 몫 2코어를 남기고 동시 전사 수로 나눈다. 속도 손해 없음(9.7초 → 9.4초).

### 검증

```
uv run pytest -q          # 243 passed  (신규 20건)
uv run mypy --strict src/ # 27 files, no issues
```

신규 테스트는 전부 **수정 전이라면 실패하는** 조건을 검사한다.

---

## 2026-09-04 — F-09 전사 후 LLM 교정 제안 (Ollama gemma4)

사용자 승인(A안) 후 구현. **원문은 고치지 않고 `원문[→교정]` 주석만 붙인다.**

### 왜 Ollama인가 — in-process 대안 전부 실측 후 탈락

| 방식 | 교정 품질 | 판정 |
|---|---|---|
| **Ollama HTTP** | e4b 8/9(89%), e2b 5/7(71%) | ✅ 채택 |
| mlx-lm 4bit | **1/10(10%)**, 구자라트 문자 혼입 | ❌ 품질 붕괴 |
| mlx-lm 8bit | `KeyError: 'model'` | ❌ 로드 실패 |
| mlx-lm bf16 | 12.83GB | ❌ 16GB 기기 부적합 |
| llama-cpp-python | Ollama와 동일 예상 | ❌ **arm64 macOS 휠 없음** |

**핵심**: ollama의 `gemma4:e4b`도 4비트(Q4_K_M)다. 비트 수가 아니라 **양자화 방식**
차이다 — llama.cpp k-quant가 mlx 단순 그룹 양자화보다 품질 보존이 압도적.
파이썬 GGUF 런타임(llama-cpp-python/gpt4all/ctransformers)은 arm64 휠이 전무해
`.app` 번들 불가. 그래서 데몬 경유가 유일하고, 대신 **앱이 수명주기를 관리**한다
(꺼져 있으면 직접 기동, 실측 0.3초).

### 품질을 좌우하는 것은 모델이 아니라 프롬프트

같은 e4b가 **1/7 → 8/9**로 뒤집혔다. 차이는 넷.

1. 주제(topic)를 프롬프트에 넣음
2. 용어집(glossary)을 넣음
3. 재작성이 아니라 **주석용 교정 쌍**을 요구
4. 근거(reason)를 함께 요구

`build_prompt()`가 1·2를 강제한다. 빠지면 안 된다.

### 기계적 검증

LLM은 오디오를 못 듣는다. 그래서 검증 가능한 것만 통과시킨다.

| 필터 | 45분 실측 폐기 수(e4b) |
|---|---|
| 전사문에 없는 문자열(환각) | 0 (e2b는 3) |
| 철자 변환일 뿐(`가우시안→Gaussian`) | 4 |
| 원문과 동일 | 3 (e2b는 17) |
| 다른 제안과 겹침 | 1 |
| 신뢰도 미달(low) | 1 |

음차 판별은 자음 뼈대 비교다(`consonant_skeleton`). 받침 ㅇ은 /ŋ/이라 `g`로 둔다.
**연음 c(device의 ce=/s/)는 일부러 반영하지 않았다** — 넣으면 `디바이스→device`는
잡히지만 진짜 교정인 `라이샤인트→Ricean`까지 폐기된다(실측). 진짜 교정을 잃는 쪽이
잡음 하나 남기는 것보다 나쁘다.

### 45분 강의 전체 실측 (547세그먼트 / 12,200자 / 11구간)

| 모델 | 소요 | 채택 | 폐기 | 환각 |
|---|---|---|---|---|
| gemma4:e4b | **3.7분** | 41 | 9 | 0 |
| gemma4:e2b | 2.5분 | 27 | 21 | 3 |

전사 39분 대비 **+9%**. 다만 채택 41건을 사람이 판정하면 **명백히 유용한 것은 약 21건
(≈51%)**이다. `시리즈하우스→Steve Jobs`, `격석→인원수` 같은 창작이 섞이고,
`오프몬의 하타모델`을 `Shannon의 채널 모델`로 잘못 짚었다(실제는 오쿠무라-하타).
`어댑티브`는 끝내 `Additive`가 아니라 `적응형`으로 잘못 봤다 — 다만 직접 물으면
"AWGN의 A는?" → "Additive"로 맞힌다. 문맥 속에서만 놓친다.

**그래서 주석 방식이 맞다.** 원문이 그대로 남으므로 오답 제안이 있어도 손실이 없다.

### 메모리 수명주기

전사 모델과 교정 모델은 동시에 상주하지 않는다.
Whisper 전사 → **Whisper 해제** + `release_memory()` → gemma 교정 → **gemma 해제**
(실측 4,580MB → 51MB, 1초) → 파일 저장.

`keep_alive`는 구간을 도는 동안 `"5m"`으로 붙잡고 끝나면 한 번만 내린다.
매 요청에 `0`을 주면 구간마다 모델을 다시 올려 로드 비용(e4b 약 7.7초)이
구간 수만큼 붙는다(초기 구현의 실수, 실측으로 발견).

### 산출물

- `<basename>.txt` / `.md` — `원문[→교정]` 주석. **원문 글자는 하나도 지우지 않는다.**
- `<basename>.corrections.json` — 세그먼트 id·타임스탬프·근거·신뢰도·`avg_logprob`·문맥.
  `notice` 필드에 "모델이 오디오를 듣지 못했으므로 확정 사실이 아니다"를 명시.
- `.srt` / `.vtt` / `.transcript.json`은 **주석을 넣지 않는다**(자막은 가독성,
  json은 기계 판독용).

### 인터페이스

```bash
uv run lecture-scribe FILE --correct                          # 기본 e4b
uv run lecture-scribe FILE --correct --correct-model gemma4:e2b
uv run lecture-scribe FILE --correct --correct-confidence high
uv run lecture-scribe FILE --no-correct                        # 설정이 켜져 있어도 끔
```

GUI 고급 설정: 교정 on/off, 모델(e4b/e2b), 채택 신뢰도, 주석 여부.
Ollama가 없으면 체크박스가 비활성화되고 이유를 알려 준다.

설정 스키마 v2 → **v3**(`correction` 섹션 추가, **기본 비활성**).
Ollama 없는 환경이 정상이므로 기존 사용자에게 켜진 채 내려가면 안 된다.

### 검증

```
uv run pytest -q          # 289 passed  (교정 관련 신규 45건)
uv run mypy --strict src/ # 28 files, no issues
```

CLI 전체 파이프라인 실제 실행 확인(45초 클립, large-v3-turbo + gemma4:e4b, 23.2초):
`맥시멈 라이프힘 후드 디텍터 → 최대우도 검파기 (Maximum Likelihood Detector)` 채택,
`transcript.json` 세그먼트에는 주석이 섞이지 않음을 확인.

---

## 2026-09-04 — GPU 즉시 실패 버그 + 영역 직접 조정

### GPU(mlx) 백엔드가 시작하자마자 실패 — 원인 확정

사용자 로그:

```
mlx_whisper.transcribe 실패 /Users/.../9:4 캡스톤디자인.m4a:
FileNotFoundError(2, 'No such file or directory')
```

파일은 존재했다(ffprobe 통과). 못 찾은 것은 **`ffmpeg` 실행 파일**이었다.

`mlx_whisper.audio.load_audio`는 `["ffmpeg", ...]`를 맨 이름으로 실행한다
(설치본 소스 주석: "Requires the ffmpeg CLI in PATH"). 실측:

```
launchctl getenv PATH            -> (비어 있음)
env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin which ffmpeg  -> 없음
```

`.app` 번들과 Quick Action은 이 최소 PATH를 상속받는다. faster-whisper는 PyAV를
쓰므로 멀쩡하고 **GPU 백엔드만** 죽는다.

재현·수정 실측(실제 실패 파일 46분):

| | 결과 |
|---|---|
| 현행(경로 전달, 최소 PATH) | `FileNotFoundError: 'ffmpeg'` — 사용자가 본 그 오류 |
| 수정(PyAV 배열 전달) | 디코드 2.0초 + 전사 230초, 2,032세그먼트 ✅ |

`mlx_whisper.transcribe`의 `audio` 파라미터가 `Union[str, np.ndarray, mx.array]`라
배열을 그대로 받는다. PyAV는 이미 필수 의존성(faster-whisper)이므로 새 의존성이
없다. **파일 객체로 열어서** 넘기므로 콜론 든 파일명도 안전하다.

CLI 검증(.app과 동일한 최소 PATH):

```bash
env PATH=/usr/bin:/bin:/usr/sbin:/sbin LECTURE_SCRIBE_FFMPEG_DIR=/opt/homebrew/bin \
  .venv/bin/lecture-scribe "9:4 캡스톤 조각.m4a" --backend mlx --model large-v3-turbo
# -> 37.4초 오디오, 11세그먼트, 14.0초 소요. 정상.
```

### 설정/파일 영역 직접 조정

`QSplitter`는 원래 있었지만 쓸 수 없는 상태였다.

1. macOS 기본 분할선은 몇 px라 **보이지도 잡히지도 않았다** → 10px + 손잡이 스타일
   + hover 색 변화 + 툴팁.
2. `QScrollArea`의 세로 sizePolicy가 기본값이라 **내용 전체 높이를 요구**해
   분할선 위치를 끌어갔다(0.40으로 설정해도 0.78) → `QSizePolicy.Ignored`.
3. 생성자의 `setSizes()`가 **첫 표시 때 재배치에 덮였다** → `showEvent`에서
   `QTimer.singleShot(0, ...)`으로 재적용.
4. 조정한 비율이 저장되지 않았다 → `WindowState.split_ratio`(0.15~0.85로 제한).
5. 조정 여유가 좁았다 → 최소 높이 설정 140→110, 드롭존 180→140.
6. 고급 설정을 펴면 사용자가 끌어 놓은 비율을 덮었다 → 이미 더 넓으면 존중.

실측: 초기 0.40 → 조정 0.31 → 재시작 복원 0.31.

### 검증

```
uv run pytest -q          # 297 passed (신규 8건)
uv run mypy --strict src/ # 28 files, no issues
```

---

## 2026-09-04 (2) — "여전히 실패" 재조사: 오진 + 진짜 버그 1건

### 결론 먼저

18:04:48 실패는 **낡은 프로세스**였다. GPU 수정(17:58:13)이 들어가기 전에 띄운
GUI가 계속 떠 있었고, 파이썬은 이미 불러온 모듈을 다시 읽지 않는다.

배제 근거(전부 실측):

| 확인 | 결과 |
|---|---|
| 수정이 파일에 있나 | 있음 (`_decode_audio` 197행) |
| `__pycache__` 오염 | 소스와 시각 동일 |
| 다른 체크아웃/사본 | 없음 |
| editable 설치가 소스를 가리키나 | 가리킴 |
| **현재 소스로 그 파일 실행** | **성공** (1,422세그먼트, 46분, 457초) |

**결정적 증거**: 로그 18:04:46이 `가용 메모리 6.8GB 기준으로...`를 찍었다.
현재 코드는 mlx면 그 분기에 도달하기 전에 `mlx 백엔드는 GPU 모델을 공유하므로...`를
찍고 반환한다. 즉 그 프로세스에는 `backend` 인자가 없던 **옛 `limit_parallel`**이
로드돼 있었다.

### 재발 방지 — 낡은 코드 감지

`provenance.py` 추가.

- 시작 시 버전·pid·실행 방식·**핵심 모듈 수정 시각**을 로그에 남긴다.
- `stale_sources()`가 프로세스 적재 시각보다 새로운 소스를 찾는다.
- 전사가 실패했는데 그 사이 코드가 바뀌었으면 **재시작 안내 대화상자**를 띄운다
  (같은 세션에 한 번만).

이제 로그만 보면 "이 로그를 남긴 프로세스가 어느 시점 코드였는지" 바로 알 수 있다.

### 재조사 중 발견한 진짜 버그 — mlx의 NaN

성공한 실행의 메타데이터가 `avg_logprob: nan`이었다. 파고드니 **1,422개 중 22개**
세그먼트에 mlx가 `NaN`을 돌려주고 있었다. 조용히 세 가지가 망가졌다.

1. 하나만 섞여도 **평균 전체가 `nan`**.
2. `nan < -0.8`은 항상 False → **저신뢰 `⟨?⟩` 마커가 안 붙는다.**
   신뢰도를 모르는 구간이 멀쩡한 것처럼 보였다.
3. 기록된 JSON에 맨 `NaN` → **RFC 8259 위반**. 엄격한 파서는 사이드카를
   통째로 거부한다(실측 확인). 에이전트가 읽으라고 만든 파일인데.

3중 방어로 수정:

| 층 | 조치 |
|---|---|
| `backends/mlx.py` | 비유한값을 `-1.0`(저신뢰)로 바꾸고 개수를 경고 |
| `writer.is_low_confidence()` | NaN을 저신뢰로 판정 |
| `writer.dump_json()` | `allow_nan=False` + 비유한값 → `null` |

수정 전후(같은 파일, `.app`과 동일한 최소 PATH):

| | 전 | 후 |
|---|---|---|
| 전사 | `FileNotFoundError: 'ffmpeg'` | ok, 1,267세그먼트 / 423.7초 |
| `avg_logprob` | `nan` | `-0.4801` |
| 엄격 JSON 파서 | 거부 | 통과 |
| 저신뢰 비율 | (계산 불가) | 3.8% |

### 검증

```
uv run pytest -q          # 305 passed (NaN 방어 10건, provenance 6건 신규)
uv run mypy --strict src/ # 29 files, no issues
```

---

## 2026-09-04 (3) — 메모리 누수 진짜 원인 + GUI 5건

### GPU 실패는 또 낡은 프로세스였다 (증거 2개)

1. 로그에 **`GUI 시작` 항목이 0건**. provenance 로깅(18:22 추가) 이전에 띄운 프로세스다.
2. 18:30:29 로그가 `전사 워커 시작(동시 1개)` — **백엔드 이름이 없는 옛 형식**.
   현재 코드는 `전사 워커 시작(동시 1개, 백엔드 mlx)`를 찍는다.

현재 코드로 같은 파일을 `.app`과 동일한 최소 PATH에서 돌리면 성공한다
(1,267세그먼트 / 423.7초). **근본 원인은 앱을 끄기 어려웠다는 것** — ⌘Q가 안 먹으니
켜 둔 채로 두게 되고, 그러면 코드를 고쳐도 옛 코드가 계속 돈다. 그래서 ⌘Q/⌘W와
`QApplication.quit()`을 넣은 것이 이 문제의 실질적 해결이다.

### 실패 시 메모리 미해제 — 진짜 버그였다

`transcribe_file()`은 **예외를 삼키고** `FileResult(status="failed")`를 돌려준다.
그래서 워커의 `except LectureScribeError` 절이 이 경로에서 한 번도 실행되지 않았고,
그 안에 넣어 둔 `_dispose_backend()`도 호출되지 않았다.

앞서(2026-09-04 첫 수정) 넣은 테스트는 `backend_provider`가 raise하는 **드문 경로만**
덮어서 이걸 놓쳤다. 지금은 `result.status == "failed"`를 직접 본다.

실측(GUI 워커 경로 그대로):

| 시점 | mlx active | cache | ModelHolder |
|---|---|---|---|
| 전사 1회 후 | 1.51GB | 1.20GB | loaded |
| 실패 작업 처리 후 | **0.00GB** | **0.00GB** | **None** |

### GUI 5건

| 요청 | 구현 |
|---|---|
| 고급 설정 상시 표시 | 기본 펼침. 접기도 여전히 가능 |
| 분할선 위치 표시 | `gui/splitter.py` — `createHandle()` 재정의로 점 7개를 직접 그린다. 스타일시트로는 못 그린다 |
| ⌘Q / ⌘W 종료 | `StandardKey` 금지(실측: `Quit`=빈 시퀀스, `Close`=⌘F4). `"Ctrl+Q"`/`"Ctrl+W"` 명시 + `QApplication.quit()` |
| 크기·비율 기억 | `window.size` + `window.split_ratio` 저장/복원. 실측 700x700 / 0.66 왕복 확인 |
| 실패 재시도 | 행별 `재시도` 버튼(실패·취소일 때만) + 하단 `실패 재시도` 일괄 버튼. 재시도 시 모델 콤보를 다시 열어 준다 |

### 부수 발견

mlx는 `hallucination_silence_threshold` 때문에 `word_timestamps=True`가 되고,
정렬 계산(`dtw_cpu`)이 **numba JIT 컴파일**을 유발해 첫 실행에 약 3초 멈춘다.
워치독이 스택까지 잡아냈다 — 감시 장치가 제 역할을 했다. 프로세스당 1회뿐이라
동작으로 두고 문서에만 남겼다.

### 검증

```
uv run pytest -q          # 326 passed (신규 15건)
uv run mypy --strict src/ # 30 files, no issues
```

---

## 2026-09-04 (4) — 초반 정체 / GPU 용어집 / 알림 / 진행 표시

### 초반에 0%에서 멈춘 것처럼 보이던 원인 (백엔드마다 다름)

실측(46분 파일):

| 단계 | faster (CPU) | mlx (GPU) |
|---|---|---|
| 모델 로드 | 2.91s | 0.40s |
| `transcribe()` 반환 | 17.88s | **400.70s** |
| 첫 세그먼트 | 16.07s | 0.00s |

**mlx는 지연 생성을 하지 않는다.** 파일 전체를 다 돌린 뒤 한꺼번에 반환한다.
6분 40초 동안 화면이 0%였고 취소도 불가능했다.

수정: 오디오를 창 단위로 잘라 반복 호출(`_stream_windows`). 첫 창 30초,
이후 120초. 창마다 타임스탬프를 밀고, `condition_on_previous_text`면 직전 창의
마지막 문장을 다음 창 프롬프트로 넘겨 문맥을 잇는다.

| | 전 | 후 |
|---|---|---|
| `transcribe()` 반환 | 400.70s | **2.57s** |
| 첫 세그먼트까지 | 33.49s | **5.27s** |
| 진행률 | 0% 고정 → 100% | 창마다 갱신 |
| 취소 | 불가 | `GeneratorExit`로 창 경계에서 |

CPU의 17.88초는 Silero VAD가 전체를 훑는 시간이라 줄일 수 없다.

### GPU에서 용어집이 조용히 버려지고 있었다

mlx는 hotwords를 지원하지 않는다. 그런데 `build_prompt_plan_for()`는 hotwords를
만들어 넘겼고, mlx는 그 인자를 받지 않으므로 **용어가 그냥 사라졌다.**
사용자가 본 "GPU에서 옵션이 비활성화" 뒤에 있던 진짜 문제다.

수정: hotwords 미지원 백엔드면 용어집을 `initial_prompt`로 돌린다.
faster-whisper의 head-loss가 걱정되어 mlx에서 측정했으나 **재현되지 않았다**
(프롬프트 유무 모두 0.00초 시작). 실행 로그에서 확인:

```
프롬프트 58/223 토큰, 용어 4개 반영: ... IMU, 센서, 데이터셋, 흑구 온도 ...
```

### 알림이 스크립트 에디터로 뜨던 문제

`osascript`로 낸 알림은 Script Editor 소유라 누르면 그게 열린다.
`gui/notifier.py` 추가 — `QSystemTrayIcon.showMessage()`로 앱 이름 알림을 내고
`messageClicked`로 창을 올린다. 메뉴 막대 아이콘 클릭도 같은 동작.
트레이가 없는 환경(CLI/Quick Action)에서는 `osascript`로 되돌아간다.

화면 없는 플랫폼에서는 트레이를 아예 만들지 않는다 — 동작하지도 않으면서 객체가
쌓여 정리 시점에 프로세스가 죽었다(실측: 테스트 전체 실행 중 세그폴트).

### 진행 표시

- 행마다 **남은 시간**(`10분 12초 남음`). 끝나면 지운다.
- 하단에 **전체 남은 시간** — 진행 중 파일의 실측 속도를 대기 파일 길이에 적용.
- 취소 버튼은 전사 중 활성(원래 배선되어 있었고, 테스트로 고정).

### 검증

```
uv run pytest -q          # 344 passed (신규 18건)
uv run mypy --strict src/ # 31 files, no issues
```

GPU 전체 실행(최소 PATH): 46분 파일 488초, 진행률·ETA 정상 갱신 확인.

---

## 2026-09-04 (5) — CPU vs GPU / hotwords 실효성 벤치마크

### 속도 (10분 클립, 용어집 없음, 모델 로드 제외)

| 조건 | 시간 | 배속 |
|---|---|---|
| CPU large-v3 | 314.7s | 1.91x |
| CPU large-v3-turbo | 121.5s | 4.94x |
| GPU large-v3 | 255.4s | 2.35x |
| **GPU large-v3-turbo** | **75.4s** | **7.95x** |

**GPU가 빠르다** — turbo 1.61배, large-v3 1.23배.

### 용어 정확도 (220초 구간, 정답 용어 8개, 조건당 2회)

| 조건 | 시간 | 용어 |
|---|---|---|
| CPU turbo + 용어집 | 139.1 / 153.6s | 2/8 |
| CPU turbo 없음 | 53.7 / 53.0s | 2/8 |
| **CPU large-v3 + 용어집** | 276.6 / 185.0s | **6/8** |
| CPU large-v3 없음 | 84.6 / 87.0s | 2/8 |
| GPU large-v3 + 용어집 | 56.5 / 54.6s | 2/8 |
| GPU large-v3 없음 | 52.7 / 54.6s | 2/8 |
| GPU turbo + Gemma 교정 | 46.2 + 58.5 = 104.7s | 4/8 |
| GPU large-v3 + Gemma 교정 | 41.9 + 28.0 = 69.9s | 3/8 |

### 결론 세 가지

**1. hotwords는 large-v3에서만 작동한다.** 2/8 → 6/8 (2회 모두 재현).
turbo에서는 2/8 → 2/8으로 **효과가 전혀 없다.**

**2. turbo에서 hotwords는 순손해다.** 53초 → 139~154초로 **2.7배 느려지는데**
정확도는 그대로다. 켤 이유가 없다.

**3. GPU는 용어집을 못 쓴다.** mlx에 hotwords가 없어 `initial_prompt`로 돌렸지만
(2026-09-04 (4)에서 추가) **효과가 0이다** — 용어집 있으나 없으나 2/8.
해롭지는 않다(56.5s vs 52.7s). 즉 이 앱의 핵심 기능은 **CPU + large-v3 전용**이다.

### 사용자 제안(GPU + Gemma로 용어 교정) 평가

작동한다. 기준선 대비 +2~3 용어(1~2/8 → 3~4/8). 다만
**CPU large-v3 + 용어집(6/8)에는 못 미친다.**

| | 용어 | 시간(220초 구간) |
|---|---|---|
| GPU + Gemma | 3~4/8 | 70~105s |
| CPU large-v3 + 용어집 | 6/8 | 185~277s |

2.6~4배 빠르지만 용어 정확도는 절반. 속도·정확도 트레이드일 뿐 대체재는 아니다.

### 한계

220초 클립 1개, 정답 용어 8개, 조건당 2회. 용어 "포함 여부"만 보는 거친 지표라
문장 단위 정확도는 반영하지 못한다. 방향성은 재현됐지만 절대 수치는 표본이 작다.

## 2026-09-05 (6) — GPU 스톨 버그: FIX_GUIDE.md 실행 (Sonnet)

[FIX_GUIDE.md](FIX_GUIDE.md)(Opus 계획) §6 순서대로 실행. 세부는 [STATUS.md](STATUS.md) 참조.

- **G-01(mlx 캐시 상한 1.5GB) 기각**: 같은 프로세스 내 A/B 교차 검증(3쌍)에서 상한 있는 쪽이 오히려 빠름(평균19.5s vs 22.4s). 이전 별도 프로세스 계측은 편향이었다. 수정 안 함.
- **새 발견**: 실제 앱 로그(`8:3 캡스톤 회의.m4a` 실행)에서 교정 시작 전, 전사만 돌던 구간에 이미 워치독 "UI 3초 무응답 / 스왑 3408MB" 기록. G-07이 가정한 "Ollama 동시 상주" 없이도 mlx GPU 전사 단독으로 스왑 발생 — 재조사 필요.
- **G-02** ETA를 전체 평균 외삽 → 최근 8표본 이동 구간 속도 기준으로 변경(`engine._rolling_eta`).
- **G-03/G-06** GPU+hotwords미지원 시 사용자의 "initial_prompt로 사용" 체크박스를 무조건 켜던 것 제거. 꺼져 있으면 용어집 미적용(로그만), 켜져 있어야 적용. 폴백 재전사 무장도 사용자 의도 밖에서 걸리지 않게 됨.
- **G-05** GUI 빈 진행 메시지 fallback을 stage 인지형으로: `stage=="model"`일 때만 "모델 준비 중…", 전사 중 빈 메시지는 "처리 중…".
- **G-04** 폴백 재전사 시작 메시지에 사유 포함(`재전사 중(...)`).
- 테스트: 356 passed (기존 349 + 분리/신규 7). §5-2 게이트 중 "45분 실파일 교정 병행 완주" 재실행은 비용(~40분) 문제로 보류.

## 2026-09-05 (7) — "0.6%에서 정지" 재조사 + FIX_GUIDE_2.md 실행 (Sonnet)

[FIX_GUIDE_2.md](FIX_GUIDE_2.md)(Opus 계획, "0.6% 정지" 산술 확정 포함) §5 작업 순서 1~4 실행. 세부는 [STATUS.md](STATUS.md) 참조.

- **"0.6%에서 정지" 산술로 확정**: 파일 3462.4초, `percent=end/total*97` → 0.6%=21.4초 지점. 첫 창(30초)이 낼 수 있는 최대치는 0.84% → **첫 창은 정상 완료, 멈춘 건 두 번째 창(120초)**. 지난 세션 수정(G-02/G-04/G-05)의 회귀 아님.
- **N-05** `_stream_windows` 창마다 소요시간·세그먼트 수·최대 temperature·가용 메모리·스왑을 INFO 로그 1줄로 남김(세그먼트 텍스트 없음).
- **N-04(회귀 수정)** G-02 이동평균 ETA가 mlx의 버스트 세그먼트(창 하나 끝나면 한꺼번에 방출) 때문에 표본이 전부 같은 순간에 찍혀 ETA가 0 근처로 튀던 문제. 표본을 세그먼트 단위 → 최소 벽시계 간격(1초) 단위로 변경.
- **N-02** 창이 도는 동안(최대 100초+) 진행률·메시지가 전혀 안 움직여 "멈춤"으로 보이던 문제. `TranscriptionBackend.transcribe()`에 `on_heartbeat` 콜백 추가, mlx가 창이 도는 동안 3초마다 "처리 중… (경과 N초)" 전송. 퍼센트/ETA는 마지막 실제값 유지(추정 안 함).
- **§4-1 교차 측정 → N-01(온도 폴백 리스트 6단) 기각**: 실사용 파일 2종·오프셋 21개 관측 중 온도 폴백 걸린 창은 2개뿐이고, 그마저 가장 느린 창이 아니었음 — 소요시간과 온도 폴백 사이 상관 확인 안 됨. 온도 리스트 수정 안 함.
- **새 발견(가이드 범위 밖)**: 위 측정 대부분을 `condition_on_previous_text=False`로 돌렸다가(불필요한 조치였음을 뒤늦게 확인) 실제 기본값(`True`)으로 재측정하니 그제서야 폴백이 나타났고 창 소요시간도 2~3배(18~21s → 18~50s)로 뛰었다. **`condition_on_previous_text`가 FIX_GUIDE_2.md가 다루지 않은 실제 원인 후보** — 끄면 빨라지지만 창 경계 문맥 캐리 기능과 상충돼 코드는 바꾸지 않고 Opus에 보고만 함.
- **N-01b(word_timestamps 비용)**: 30~45% 비용 확인됐으나 가이드가 제시한 조치("결합을 사용자에게 보이게")가 Sonnet이 임의로 완성하기엔 설계 판단이 필요해 보류.
- 진단 스크립트(앱 코드 아님): `.../5cd4fa6d.../scratchpad/n01/{cross_probe,sample_windows}.py` + 결과 JSON 3개(재검증용 보존).
- 테스트: 361 passed (기존 356 + 신규 5: `test_engine_heartbeat.py`, `test_mlx_stream_windows.py`). `mypy --strict` 통과.
- N-03(메모리 압박 최소 조치)은 이미 구현돼 있음을 확인(`engine.py:465` 파일/교정 경계 `unload()`). N-07(Dock 번들 확인)은 번들이 09-04 구버전이라 검증 불가 — 재빌드 후 재확인 필요.

## 2026-09-06 — 앱 아이콘 / 알림 소유자 수정: FIX_GUIDE_3.md 실행 (Sonnet)

[FIX_GUIDE_3.md](FIX_GUIDE_3.md)(Opus 계획) §5 순서대로 실행. I-05는 사용자가 A(현행 유지) 확정. 세부는 [STATUS.md](STATUS.md) 참조.

- **원인 확정**: 개발용 래퍼(`packaging/make_app.py`)가 번들 밖 `.venv/bin/python3`를 `exec`해 실행 프로세스가 번들 정체성을 잃던 것 — 메뉴 막대 `python3` 이름, 파이썬 기본 아이콘, `TransformProcessType` 실패(FIX_GUIDE_2.md N-07과 동일 원인), 트레이 알림 미동작(→osascript 폴백→Script Editor 소유)의 공통 뿌리.
- **가이드 가정 하나는 실측으로 기각**: 빈 `QIcon()`은 파이썬에서 falsy라(`bool()`→False), `icon or _fallback_icon()` 폴백은 원래도 정상 동작했다. 그 부분은 고치지 않음.
- **아이콘**: `src/lecture_scribe/assets/appicon.png` 원본 고정(기존 `draw_icon()` 결과를 그대로 내보냄, 새 디자인 창작 안 함) + `gui/icons.py`(로드 실패 시 로그 남기고 폴백) + `gui/app.py`에 `setWindowIcon()` 호출 추가. `make_app.py`/`LectureScribe.spec` 둘 다 이 원본을 쓰도록 통일.
- **번들 재빌드로 게이트 검증**: `build_dmg.sh`로 최신 소스 재빌드 후 실행 — 메뉴 막대 이름 `LectureScribe`, Dock 아이콘 정상, `TransformProcessType` 실패 없음, 완료 알림이 트레이(앱 소유)로 감(osascript 폴백 로그 없음) 전부 확인. **N-07은 이걸로 종결**(배포 번들에선 재현 안 됨, 개발 래퍼만의 문제).
- **알림**: osascript 폴백 시 사유를 로그로 남기도록 추가, `notify()` 반환값이 배달 보장이 아님을 문서화. CLI/Quick Action은 구조적으로 계속 Script Editor — TROUBLESHOOTING.md에 반영(I-05=A).
- 부수: 게이트 검증 중 교정(Ollama) 켠 5초 클립이 140초 걸려 처음엔 멈춘 걸로 오인, 확인해보니 정상 완주(gemma4:e2b 웜업 비용, 기존에 문서화된 현상 — 새 버그 아님).
- 테스트: 363 passed(기존 361 + 아이콘 테스트 2). `mypy --strict` 통과.

## 2026-09-06 (2) — 전체 점검 후속 수정: FIX_GUIDE_4.md 실행 (Sonnet)

[FIX_GUIDE_4.md](FIX_GUIDE_4.md)(Opus 계획, 점검 신규 6건 + 이월 3건 통합) §6 순서대로 실행. 세부는 [STATUS.md](STATUS.md) 참조.

- **A-01 교정 host 검증**: `CorrectionSettings.from_dict`에서 로컬 주소(localhost/127.0.0.1/::1)만 허용, 그 외는 기본값 복귀 + WARNING. 탈출구는 환경변수(`LECTURE_SCRIBE_ALLOW_REMOTE_CORRECTION`)로만. config.json 한 줄로 전사문이 조용히 외부로 나갈 수 있던 경로를 막음.
- **A-04+A-09**: `LectureScribeApp`(Finder 파일 열기) 테스트 신규 3건 — QApplication 싱글턴 충돌 피하려 시나리오마다 별도 프로세스로 격리. `add_files` 없는 창엔 이제 WARNING 로그.
- **A-06+A-07**: mlx 하트비트 콜백 예외를 잡아 스레드가 안 죽게 함(전에는 조용히 죽어 하트비트가 영구 정지). 취소 후엔 하트비트 메시지가 "취소 중…"으로 바뀜(전엔 "처리 중…"이 취소 상태를 계속 덮어씀).
- **A-08**: `logsetup.py`(31개 모듈 중 유일하게 테스트 없던 모듈) 최소 회귀 7건 추가.
- **A-03 측정**: hallucination_silence_threshold(=word_timestamps 강제) 비용은 뚜렷(55~60% — 이전 추정 30~45%보다 큼), 반복 억제 효과는 같은 조건에서도 편차가 커 판단 불가(hst=2.0인데 13회 vs 1회). **기본값 유지**, 측정값은 코드 주석으로 남김.
- **A-02 구조 분리**: `condition_on_previous_text`(mlx 내부 30초 서브청크 조건화)와 새 필드 `carry_window_prompt`(우리 120초 창 경계 캐리)를 분리 — 전엔 하나로 묶여 있어 "속도·환각 잡으려면 창 경계 문맥도 버려야" 하는 양자택일이었다. GUI에 새 체크박스 "창 경계 문맥 유지 (GPU 전용)" 추가. **기본값은 둘 다 유지(회귀 없음)**, 정식 게이트(실사용 3462초 풀 런)는 비용 문제로 사용자 승인 대기.
- **A-05**: 트레이 전용 실루엣 아이콘(`appicon_template.png`, 기존 아이콘에서 명암 대비로 기계적 추출 — 새 그림 아님) + `QIcon.setIsMask(True)`로 macOS 템플릿 지정. 컬러 아이콘이 다크 메뉴 막대에서 안 보이던 문제 해결.
- 테스트: 390 passed(기존 363 + 신규 27). `mypy --strict` 통과.
- 진단 스크립트(앱 코드 아님): `.../5cd4fa6d.../scratchpad/a03/*.py` — A-02/A-03 재검증용 보존.

## 2026-09-06 (3) — A-02 §5-2 정식 게이트 실행 및 기본값 변경 (사용자 승인, Sonnet)

사용자 승인 받아 실사용 3462초 파일(`7:31 캡스톤 회의.m4a`) 풀 런으로 A-02 정식 게이트 실행. 세부는 [STATUS.md](STATUS.md) 참조.

- **결과**: 속도 2.2배(1420.5→639.9초), 외국어 혼입 89%↓(102→11세그먼트), 저신뢰 비율 개선(9.61%→8.04%), 반복 루프 동률(4건=4건, 위치·양상 다름), 용어 빈도 거의 동일. 5개 지표 중 나빠진 것 없음 → **게이트 통과.**
- 양쪽 다 파일 도입부(2.0초)에서 같은 문장이 13회 반복 — 이 변수와 무관한 오디오 자체 환각으로 판단, 판정에서 제외.
- **적용**: `PromptSettings.condition_on_previous_text_mlx`(신규, 기본 False) 추가. 기존 `condition_on_previous_text`(faster-whisper용, 기본 True)는 게이트와 무관해 안 건드림 — 필드를 분리해서 백엔드별로 다른 기본값을 유지했다. `engine.build_request()`가 `settings.backend`로 분기.
- GUI: "이전 문맥 유지" 체크박스 하나가 현재 백엔드의 필드만 읽고/쓴다(백엔드 전환해도 서로 안 덮어씀). 툴팁에 게이트 수치 반영.
- 테스트 6건 추가(백엔드별 분기 4 + GUI 체크박스 2). 396 passed. `mypy --strict` 통과.
- 진단 스크립트: `.../5cd4fa6d.../scratchpad/a02_gate/run_gate.py` + 세그먼트 원본 JSON(재검증용 보존).

## 2026-09-06 (4) — Ollama PATH 버그 + 시작 시 의존성 점검 스플래시 (Sonnet, 가이드 문서 없이 직접 처리)

사용자가 "CPU/GPU 둘 다 gemma 교정 칸이 안 켜진다" 보고 + "설치 유도 스플래시 추가" 요청. 세부는 [STATUS.md](STATUS.md) 참조.

- **버그**: `ollama_available()`이 `shutil.which("ollama")`만 봐서, 번들 프로세스의 좁은 PATH(`/usr/bin:/bin:/usr/sbin:/sbin`)에서 Homebrew 설치 위치를 못 찾았다 — ffmpeg가 예전에 겪은 것과 같은 문제, 같은 해법(고정 경로 목록 + PATH 폴백)으로 `find_ollama()` 신설, `ensure_running()`도 같이 수정.
- **덤으로 발견**: `require_model()`이 `gemma4:e4b`/`gemma4:e2b`를 같은 "gemma4" 스템으로 오판하던 버그도 같이 고침(`_model_stem()`으로 교체 — 끝의 `:latest`만 벗김).
- **신기능**: `gui/dependency_check.py` + `gui/startup_dialog.py` — 시작 시 ffmpeg/Ollama/gemma 모델 점검, 문제 있을 때만 대화상자. 실행 파일 없음→명령 복사만(자동 설치 안 함), 데몬만 꺼짐→바로 실행(다운로드 없어 안전), 모델 없음→"지금 받기"(클릭이 다운로드 승인). "계속"으로 언제든 건너뜀.
- 테스트 10건 추가. 406 passed. `mypy --strict` 통과.

**후속(같은 세션)**: 사용자가 "설치된 모든 gemma 버전을 목록에 띄워달라" 요청 — `correction.list_installed_gemma_models()`(Ollama `models()`에서 "gemma" 포함 이름만 필터링) 신규, 설정 패널 교정 모델 드롭다운을 고정 두 개(e4b/e2b) 대신 이걸로 채우고 "새로고침" 버튼 추가. 조회 실패 시 고정 목록으로 폴백. 테스트 6건 추가. 412 passed.

- 2026-09-06 13:58 DMG 재빌드로 반영 완료(바이트코드 디컴파일로 확인).

## 2026-09-07 — 한자/외국어 환각 억제: FIX_GUIDE_5.md 실행 (Sonnet)

사용자 보고: "전사시 자꾸 중국어(한자)가 뜬다." [FIX_GUIDE_5.md](FIX_GUIDE_5.md)(Opus 계획, B-01+B-02)
순서대로 실행. 세부·게이트 수치는 [STATUS.md](STATUS.md) 참조.

- **B-02(완료, 기본 켬)**: `postprocess.find_foreign_script_runs()` 신규 — 한글/라틴 밖 문자
  (한자·가나·키릴 등)가 비율(0.3)·개수(2) 둘 다 넘는 세그먼트를 구간으로 묶어 찾는다.
  검출된 구간은 새 마커를 만들지 않고 기존 `⟨?⟩` 저신뢰 마커로만 표시(원문은 그대로 — 삭제·
  치환 없음). `engine.py`가 헤더 주석·warnings·사이드카 JSON까지 전부 연결. 언어가 ko/en일
  때만 동작(다른 언어 강의는 자동 비활성). 실제 기존 산출물(FIX_GUIDE_4 A-02가 다뤘던 그
  일본어 환각 건 포함)로 오프라인 검증 — 오탐 0건 확인 후 초기 제안 임계값 그대로 확정.
  GUI 체크박스 1개 추가. 테스트 24건 추가.
- **B-01(실패 → 롤백)**: `no_speech_threshold` 0.6→0.5 시도. 실제 57분 강의 파일로 프로덕션
  경로 그대로 게이트 실행(faster/CPU) — 총 글자수 -1.82%(통과선 -1% 초과)에 반복 루프까지
  새로 생겨 명백한 실패. 이 파일에서 외국어 세그먼트 감소 효과는 0.6/0.5 둘 다 0으로 무차이
  (B-02가 이미 그 파일의 진짜 환각 2건을 다 잡아서 이 파라미터로 얻을 게 없었음). **0.6으로
  롤백**, 실측 수치는 코드 주석에 남김.
- 테스트: 관련 스위트 전건 통과, `mypy --strict` 통과.
- 2026-09-07 14:07 DMG 재빌드로 B-02·롤백된 0.6 반영 완료.

## 2026-09-07 — GUI 정리: FIX_GUIDE_6.md 실행 (Sonnet)

사용자 요청: "단어/주제 예시문장들 날리는것, UI적으로 개선할 부분 찾아서 물어보고 fix guide 작성."
[FIX_GUIDE_6.md](FIX_GUIDE_6.md)(Opus 계획, C-01~C-05) 순서대로 실행, 전건 완료. 세부는
[STATUS.md](STATUS.md) 참조.

- **C-02**: 주제/용어 placeholder·팁의 과목 특정 예문(OO대·AWGN 등) 제거, 형식 안내만 유지.
- **C-04**: 창 정방형 강제 해제 — 세로로만 늘릴 수 있게. `WindowState.size`(int) →
  `width`/`height` 분리, 옛 설정 파일은 fallback으로 정방형 그대로 복원.
- **C-01**: B-02(FIX_GUIDE_5)가 검출한 경고가 md 파일 열어야만 보이던 문제 해결 — 큐 행에
  `⚠ N` 배지(품질 경고만 카운트) + 클릭 시 상세 대화상자 추가.
- **C-03**: 고급 설정 14행 평면 나열 → 인식/프롬프트/출력/후처리 4구역 + 소제목/구분선.
- **C-05**: "잘못 켜면 나빠지는" 4항목·"백엔드가 무시하는" 2항목만 선별해 툴팁 밖 한 줄 설명 추가.
- 신규/수정 테스트 다수, `mypy --strict src/` 통과, `pytest -q`(442건) 2회 연속 전건 통과.
- 2026-09-07 14:47 DMG 재빌드로 반영 완료.

## 2026-09-08 — 자동 용어 빈도 관리·토큰 정리: FIX_GUIDE_7.md 실행 (Sonnet)

사용자 요청: "용어란에 자동 입력되는 단어를 최근 감지 많은 순서로 남기고 토큰 제한 지키게."
[FIX_GUIDE_7.md](FIX_GUIDE_7.md)(Opus 계획, E-01·E-02) 순서대로 실행, 전건 완료. 세부는
[STATUS.md](STATUS.md) 참조.

- **E-01**: 신규 `glossary_stats.py` — 프리셋별 용어 등장 점수를 감쇠(0.8)+누적하며 별도 파일에
  저장(`Preset`/`Settings`에 안 넣음 — 저장 시 조용히 사라지는 구조라서). 사용자 용어는 순서
  유지, 자동 추가분만 점수 내림차순 재정렬. 사용자가 칸을 직접 고치면 그 순간 남은 용어는
  전부 "사용자 것"으로 승격돼 이후 자동 삭제 대상에서 빠짐.
- **E-02**: 자동 추가 직후 1회만, 토큰 예산 초과로 잘린 용어 중 자동 추가분만 실제로 삭제.
  기존 `build_prompt_plan()`의 "뒤쪽부터 자름" 동작을 그대로 활용해 새 토큰 계산 경로 없이 구현.
- 실앱 확인(§5-4)으로 정렬·정리·안내 메시지·통계 파일 갱신 전부 눈으로 검증.
- 신규 테스트 25건, `mypy --strict src/` 통과, `pytest -q`(465건) 전건 통과 확인.
- 구현 중 `config.SETTINGS_PATH`가 테스트 격리를 우회해 실제 사용자 설정 파일을 건드리는
  기존 버그를 발견 — 이번 범위 밖이라 별도 task로 분리(내 새 모듈은 같은 함정을 피해
  호출 시점에 경로를 계산하도록 만듦).
- DMG 재빌드 예정(이 항목 마무리 후).

## 2026-09-13 — v0.2 Cohere Transcribe 백엔드 조사·종결: FIX_GUIDE_8~11.md (Sonnet)

사용자 요청: 기존 hotwords 세기 질문에서 시작해 "cohere-transcribe-03-2026 한국어 실측
비교 가이드 작성" → "VAD·GPU·hotwords 다 살려서 Whisper/Cohere 선택 가능한 v0.2 가이드".
Opus가 FIX_GUIDE_8.md로 v0.2 계획(VAD 분할, GPU 백엔드, 백엔드 선택, 비교 측정) 작성 →
선행 실측(H-00) 단계에서 막혀 FIX_GUIDE_9/10/11.md로 이어진 3라운드 진단 끝에 **채택하지
않기로 종결.** 세부는 [STATUS.md](STATUS.md) 참조.

- **모델 리포 함정 발견**: 가이드가 지정한 `mlx-community/...-mlx-8bit`가 이름과 달리
  실제로는 BF16(양자화 안 됨) — scale 텐서 0개 실측. 커뮤니티 변환본 4종(beshkenadze
  fp16/8bit/6bit/4bit) 전부 Swift 포트용이라 파이썬 mlx-audio와 텐서 이름 규약이 안 맞음
  (`transf_decoder.*`·`log_softmax.*` 전부 0개). **정식 게이트 리포만 정상 동작.**
- **원인 진단**: mlx-audio 로더가 `strict=False`로 안 맞는 키를 조용히 버려 디코더·LM헤드가
  미초기화 상태로 돌아간 것이 첫 실패(다국어 뒤섞인 헛소리)의 원인. `strict=True` +
  정식 체크포인트로 **영어는 완벽 통과**("Today we will discuss impedance matching and
  the Smith chart in microwave engineering." — 정답과 완전 일치).
- **한국어는 실패**: 언어×길이 분리 실험(J-01)으로 길이 문제 배제(영어는 8배 길어도 정상,
  한국어는 5초에도 즉시 붕괴). transformers 네이티브 교차검증(J-02)으로 짧은 한국어의
  mlx-audio 고유 포팅 버그 확정, 긴 한국어는 하네스를 바로잡은 뒤에도 mlx-audio·
  transformers 둘 다 반복 루프로 붕괴(모델/디코딩 특성). 가장 쉬운 조건에서도 Cohere
  출력이 large-v3보다 내용어가 뚜렷이 부정확.
- **정답 청취 불가로 CER 측정 대신 질적 판단으로 종결**: 5초 클립 정답을 만들려면 사람이
  직접 들어야 하는데 Sonnet에 오디오 청취 도구가 없어 사용자에게 확인 → CER 생략, 질적
  증거로 종결 결정.
- **판정**: v0.2 Cohere Transcribe 백엔드 미채택. Whisper(large-v3/large-v3-turbo) 유지.
  FIX_GUIDE_8/9/10.md는 종결 배너를 달고 본문 보존(모델 조사·측정 방법론 자산).
- **부산물**: HF Xet(CAS) 다운로드가 2회 재현성 있게 정지 → `hf_xet` 언인스톨 후 순수
  HTTP로 우회하는 패턴 확인(v0.2 후보로 백로그 등록). 비교 측정 방법론을 일반화해
  [COMPARISON_METHOD.md](COMPARISON_METHOD.md)로 분리(다음 large-v3 vs turbo 비교에
  바로 재사용 가능).
- 앱 코드(`src/lecture_scribe/**`) 전 라운드 무변경 — 진단·조사·문서 작업만.
- probe용 임시 자산(체크포인트 3.9GB, 격리 venv 1.6GB, 임시 클립) 전부 정리, 앱 `.venv`
  격리 끝까지 유지 확인.

## 2026-09-14 — Cohere Transcribe 조사 최종 종결 (Sonnet)

2026-09-13 종결(FIX_GUIDE_11) 이후, 사용자가 "리더보드 1위 모델의 한국어가 그렇게
나쁠 리 없다"고 문제 제기 → 실측 확인 결과 비교에 쓴 영어/한국어 샘플의 **녹음 조건
자체가 달랐음**(영어: 22050Hz 합성 추정, 한국어: 48000Hz 실기기 녹음) — 종결 판정을
FIX_GUIDE_12.md로 보류하고 재조사.

- **FLEURS ko_kr 40발화로 재측정**: 조건을 맞추자(낭독체+사람이 만든 정답) Cohere
  CER 5.1%(Whisper large-v3 3.1%, 상대 +64.8%) — **실사용 가능한 수준.** 강의 클립에서
  본 "완전히 뒤섞인 헛소리"와 전혀 다른, 정상적인 한국어 출력 확인.
- **디코딩 파라미터 11종 스윕**(`repetition_penalty`·`no_repeat_ngram_size`·
  `num_beams` 등, 사용자가 직접 지목): 강의 클립의 반복 루프에 **전혀 효과 없음** —
  일부는 오히려 의미 없는 음절 나열로 악화.
- **최종 결론 정정**: "한국어 자체를 못한다"가 아니라 "깨끗한 낭독체는 준수하게
  하지만 길고 반향 있는 실제 강의 녹음 조건에서 인코더 표현이 무너지고, 이는
  디코딩 설정으로 우회되지 않는다"가 정확한 원인. **v0.2 Cohere 백엔드 미채택**
  결론은 FIX_GUIDE_11과 동일하게 유지(이 앱은 실제 강의 녹음을 다루므로).
- 사용자 지시("그냥 이대로 그만해줘")로 L-03(전처리 정합성)·L-04는 미실행, 현재
  데이터로 종결.
- **`COMPARISON_METHOD.md`에 일반 원칙 추가**: 비교군 오디오의 녹음 조건(합성/실녹음,
  샘플레이트, 발화 길이)을 반드시 맞추라 — 이번에 결론을 한 번 뒤집을 뻔한 함정.
  다음 비교 측정(예: large-v3 vs turbo)에 바로 적용됨.
- FIX_GUIDE_11/12.md에 상호 참조 배너 추가, STATUS.md 최종 정리.
- probe 재생성 자산(체크포인트 3.9GB, venv 1.5GB) 재정리, 앱 `.venv` 격리 최종
  확인(끝까지 오염 없음). 앱 코드 전 과정 무변경.
