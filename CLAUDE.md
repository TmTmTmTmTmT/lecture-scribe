# CLAUDE.md — LectureScribe

## 목적

macOS에서 강의 녹음(`.m4a` 등)을 **로컬 Whisper**로 한국어/영어 전사하는 데스크톱 앱.
전사 결과는 **원본과 동일 디렉터리·동일 basename·확장자만 교체**로 저장.
Finder 우클릭 Quick Action, 정방형 GUI 1창, 비대화형 CLI 세 경로로 실행.

핵심 차별 요소: 사용자가 입력한 **전사 주제(도메인 컨텍스트)** 를 Whisper 디코딩에 지속 반영해
전문 용어 오인식과 주제 이탈을 줄인다. (`prompt.py` 참조)

전사는 최종 산출물이 아니라 중간 산출물. 출력물은 Claude Cowork 등 에이전트가 읽고
**근거를 인용할 수 있는 형태**여야 한다. (front matter, `⟨?⟩` 저신뢰 마커, 사이드카 JSON, 인덱스)

## 환경 (실측 확정값 — 추정 금지)

| 항목 | 값 |
|---|---|
| 기기 | Apple M1 Pro, arm64, 10코어, 16GB |
| macOS | 27.0 |
| Python | **3.12** (uv 관리, `.venv`). 시스템 python3는 3.14 → 사용 금지 |
| ffmpeg | `/opt/homebrew/bin/ffmpeg` |
| ffprobe | `/opt/homebrew/bin/ffprobe` |
| 기본 모델 | `large-v3` (정확도 우선) |
| 기본 백엔드 | `faster-whisper` (CPU / int8) |
| workspace_dir | `~/Documents/LectureScribe` |
| 앱 이름 / 번들 ID | LectureScribe / `com.local.lecturescribe` |
| 교정 LLM(선택) | Ollama `gemma4:e4b` / `gemma4:e2b` (기본 비활성) |

테스트용 실제 강의 파일:
`/path/to/강의/9:1/9:1 전자회로.m4a`
(45분 12초, AAC 48kHz mono. 파일명에 `:` 포함 — Finder 표시는 `9/1`. 경로 인용 필수.
2026-09 기준 날짜별 하위 폴더로 재정리됨 — `전자회로/` 바로 밑이 아니라 `전자회로/9:1/` 아래에 있다.)
**이 파일은 읽기 전용으로만 다룬다. 이동·수정·삭제 금지.**

가벼운 1차 검증용 샘플(정답 텍스트 포함, 원본 45분 파일을 안 건드려도 됨):
- `assets/samples/9:1 전자회로 클립.m4a` — 60초, 한국어. 정답: 같은 이름의 `.txt`
- `assets/samples/en_5s.m4a` — 4.5초, 영어. 정답: 같은 이름의 `.txt`
  ("Today we will discuss impedance matching and the Smith chart in microwave engineering.")

## 디렉터리 구조

```
lecture-scribe/
├── CLAUDE.md, PROGRESS.md, README.md, TROUBLESHOOTING.md
├── pyproject.toml
├── src/lecture_scribe/
│   ├── config.py          # 설정 스키마, 로드/저장, 프리셋, version 마이그레이션
│   ├── prompt.py          # 프롬프트 합성 + 224 토큰 예산 (순수 함수)
│   ├── postprocess.py     # 용어 교정, 문단 분리 (순수 함수)
│   ├── writer.py          # txt/md/srt/vtt/json 출력, 충돌 처리 (순수 함수 위주)
│   ├── audio.py           # ffprobe duration, 포맷 검증, iCloud 스텁 감지
│   ├── backends/base.py   # TranscriptionBackend 프로토콜, capabilities
│   ├── backends/faster.py # faster-whisper 구현
│   ├── backends/mlx.py    # mlx-whisper 구현 (optional extra)
│   ├── engine.py          # 큐, 진행률 콜백, 취소, 오류 격리
│   ├── cli.py             # Quick Action / 에이전트 진입점
│   ├── notify.py          # macOS 알림 (osascript)
│   ├── index.py           # 전사 인덱스 JSONL 기록·조회·재구축
│   ├── handoff.py         # 후속 작업 컨텍스트 파일 (템플릿 조립, LLM 미사용)
│   ├── frames.py          # 영상 화면 변화 감지·프레임 추출·시간 새김 (PLAN_VIDEO_FRAMES.md)
│   ├── ocr.py             # 프레임 OCR(macOS Vision, 선택 extra `ocr`) + 화면 고정 요소 판정
│   ├── slide_terms.py     # OCR 텍스트 -> 전사용 후보 용어 (순수 함수)
│   ├── video_stage.py     # 영상 단계: 캡처 -> OCR -> frames.md/json
│   ├── correction.py      # 전사 후 LLM 교정 제안 (Ollama gemma4, 주석만 추가)
│   ├── perf.py            # QoS·메모리(전사/mlx)·CPU 스레드 예산
│   ├── gui/watchdog.py    # UI 이벤트 루프 정지 감시(진단용)
│   └── gui/               # app / window / dropzone / settings_panel / worker / strings_ko
├── quickaction/           # .workflow 2종 + install.sh / uninstall.sh
├── cowork/skills/lecture-transcribe/SKILL.md
├── tests/
├── scripts/
└── assets/samples/
```

## 실행 / 테스트 명령

```bash
uv sync --extra fuzzy --extra mlx --extra ocr   # 의존성 설치(extra 없이 `uv sync`만 하면 설치된 extra가 제거된다)
uv run lecture-scribe FILE [옵션]          # CLI
uv run python -m lecture_scribe.gui.app   # GUI
uv run pytest -v                          # 테스트
uv run mypy --strict src/                 # 타입 검사
```

## 코딩 규칙

- 타입 힌트 필수. `mypy --strict` 통과 목표.
- 코어 로직(`prompt.py`, `postprocess.py`, `writer.py`, `config.py`)은
  **GUI/백엔드 비의존 순수 함수** 위주. 단위 테스트 필수.
- 예외는 도메인 예외 클래스(`errors.py`)로 감싼다.
  **사용자 표시 메시지와 로그 메시지를 분리**한다.
- 경로는 전부 `pathlib.Path`. 문자열 결합 금지.
- macOS 파일명은 NFD 저장, 파일 *내용*은 NFC 통일. 명시적으로 정규화 처리.
- 전역 상태 금지. 설정은 명시적 주입.
- **주석과 커밋 메시지는 한국어.**
- 외부 라이브러리 시그니처는 기억이 아니라 설치본 실측 기준
  (`python -c "import inspect; ..."`). 문서와 다르면 설치본이 정답.

## 스트림 분리 원칙 (에이전트 연동 필수 조건)

- stdout: `--json` / `--stdout` 결과만.
- stderr: 진행률·로그·경고 전부.
- 어떤 경로에서도 stdin 입력이나 확인 질문 금지. 미결정 사항은 기본값으로 진행하고 결과 JSON에 기록.
- 종료 코드: `0` 전체 성공 / `1` 일부 실패 / `2` 전체 실패 / `130` 사용자 취소.

## 절대 하지 말 것

1. 전사 결과를 요약·윤문·번역·재작성 (이 앱의 출력은 **축자 전사**)
2. 클라우드 STT API로 오디오 전송 (전 과정 로컬)
3. 원본 오디오 파일 이동·수정·삭제
4. 승인 없이 의존성 추가 (§4 고정 스택 외)
5. 검증 없이 마일스톤 완료 선언
6. 오류를 조용히 삼키고 빈 파일 생성
7. 224 토큰 초과 프롬프트를 경고 없이 잘라내기
8. Cowork 스킬 디렉터리 경로 하드코딩 (실행 시점 탐색 또는 사용자 확인)
9. `handoff.md` 등 산출물 생성에 LLM 호출
10. 교정 단계에서 **전사문 원문을 지우거나 바꾸기** — 교정은 `원문[→교정]` 주석으로만 붙인다

## 개발 역할 분담 — Opus / Sonnet

**원칙**: 계획 수립과 실행을 모델별로 분리. 한 모델이 계획+실행 동시 금지.

| 구분 | 담당 모델 | 범위 |
|---|---|---|
| 계획·가이드라인 | Opus 전용 | 개발 계획, 코딩 가이드라인, 오류 수정 가이드라인 |
| 실행 | Sonnet 전용 | 계획·가이드라인에 따른 개발, 테스트, 시뮬레이션, 디버깅, 오류 실제 수정 |

**Opus 담당 (계획 단계)**
- 요구사항 분석, 아키텍처 설계, 작업 분해
- 코딩 가이드라인/컨벤션 작성
- 오류 발생 시: 원인 분석 후 수정 방향을 가이드라인 문서로만 작성 (코드 직접 수정 금지)
- 결과물은 반드시 파일로 남김: `PLAN.md`, `GUIDELINES.md`, `FIX_GUIDE.md` 등
- 코드 실행, 파일 수정, 테스트 실행 금지

**Sonnet 담당 (실행 단계)**
- Opus 작성 계획·가이드라인 문서에 따라 실제 코드 작성
- 테스트 코드 작성·실행, 시뮬레이션 실행
- 디버깅 (원인 추적, 로그/스택트레이스 확인)
- 가이드라인에 명시된 방향에 따른 오류 실제 수정
- 계획 문서에 없는 설계 변경 임의로 하지 않음

**전환 규칙**
1. 새 기능/모듈 착수 → Opus가 계획 작성 후 문서화
2. 계획 문서 완성 → Sonnet 전환해 구현·테스트
3. 오류 발생 → Opus 전환해 원인 분석 + 수정 가이드라인 문서화 → Sonnet 전환해 가이드라인대로 실제 수정
4. Sonnet 작업 중 계획에 없는 설계 이슈 발견 시: 직접 변경 금지 → 이슈 기록 후 Opus 단계로 반환
5. 계획·가이드라인 문서 없는 상태에서 Sonnet이 구현 시작 금지

**핸드오프 규칙**
- Opus 산출물(계획/가이드라인)은 반드시 파일로 저장. 대화 내용으로만 남기지 않음
- Sonnet은 작업 시작 전 해당 문서 먼저 확인. 문서 범위 벗어나는 판단 금지
- 수정 가이드라인 문서 최소 포함 항목: 오류 원인, 수정 방향, 영향 범위, 재현/검증 방법 — **실제 수정 코드는 포함하지 않음**
- 모델 전환 필요 시 가장 마지막에 전환 요청

### 작업 결과 저장 규칙 (STATUS.md)

Sonnet은 작업 완료할 때마다 진행 상황을 별도 파일에 기록한다. 목적: 대화 컨텍스트 매번 다시 채우지 않고, 필요할 때만 파일 읽어 상태 파악.

- 파일: `STATUS.md` (계획 문서와 같은 위치, `PLAN.md`/`GUIDELINES.md`/`FIX_GUIDE.md`와 세트로 관리)
- 기록 내용: 완료한 작업 목록, 변경된 파일 경로, 테스트/시뮬레이션 결과 요약, 미해결 이슈, 다음 단계
- 코드 전문·전체 로그·스택트레이스는 그대로 옮기지 않고 결론만 요약 (원인/결과 한두 줄)
- 작업 단계 끝날 때마다 해당 항목 갱신 — 새로 쓰지 않고 이어서 기록(append)하되, 완료되어 더 이상 참조 필요 없는 항목은 한 줄 요약으로 압축해 분량 계속 늘지 않게 함
- 진행 중 이슈(계획 이탈, 막힌 부분)는 "Opus 확인 필요" 항목으로 별도 표시

### 세션 전환 및 `/clear` 규칙

- `STATUS.md`는 대화 중 매 턴 자동으로 읽지 않는다. 다음 경우에만 읽는다: ① 새 세션/모델 전환 직후, ② 이전 진행 상황 확인 필요할 때, ③ Opus가 검토 단계로 개입할 때
- `/clear`로 세션 새로 시작하는 경우, 새 세션 첫 작업으로 `STATUS.md`(+관련 계획/가이드라인 문서)만 읽고 이어서 진행 — 전체 대화 기록 복원 시도 금지
- Opus 개입 시에도 구현 코드 전체가 아니라 `STATUS.md` + 관련 가이드라인 문서만 근거로 판단
- 세션 넘길 때 요약을 대화창에 다시 출력하지 않는다 — 파일 갱신으로 대체
