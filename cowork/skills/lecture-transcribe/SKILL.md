---
name: lecture-transcribe
description: >
  강의 녹음·오디오·영상 파일을 로컬 Whisper로 전사한다. 사용자가 오디오/영상 파일
  전사를 요청하거나, .m4a/.mp3/.wav/.mp4/.mov 파일을 언급하거나, "이 녹음 요약해줘",
  "강의 받아써줘", "이 파일 텍스트로" 같은 요청을 할 때 사용한다. 전사는 전 과정
  로컬에서 이루어지며 클라우드로 오디오를 보내지 않는다.
---

# LectureScribe — 강의 녹음 전사

## 무엇을 하는가

오디오/영상 파일을 로컬 Whisper(faster-whisper)로 전사하고, **원본과 같은 폴더에
같은 이름**으로 결과를 저장한다. 요약·윤문은 하지 않는다. 출력은 **축자 전사**다.

## CLI

실행 파일(절대 경로):

```
/path/to/lecture-scribe/.venv/bin/lecture-scribe
```

### 대표 호출

```bash
# 전사 + 결과를 JSON으로 받기 + 후속 작업 컨텍스트 파일 생성
/path/to/lecture-scribe/.venv/bin/lecture-scribe "/path/to/lecture.m4a" \
  --topic "OO대 전기공학과 전자회로 강의, 채널 잡음" \
  --glossary "잡음, AWGN, 다중 경로, 반도체" \
  --format md --format json --emit-handoff --json
```

- `--json` 결과는 **stdout에만** 나온다. 진행률·로그·경고는 전부 stderr다.
  stdout을 그대로 파싱하면 된다.
- 저장된 프리셋을 쓰려면 `--preset "전자회로"`.
- 진행 상황이 필요하면 `--progress-json` (stderr가 전부 JSON Lines가 된다).
- 긴 파일을 나누려면 `--split-md 10` (10분 단위). 기본은 분할하지 않는다.

### 영상(.mp4/.mov) 입력 — 화면 캡처

영상을 넣으면 전사에 더해 **화면이 바뀐 시점의 프레임**을 이미지로 저장한다(기본 켜짐).

```bash
/path/to/lecture-scribe/.venv/bin/lecture-scribe "/path/to/lecture.mov" --json --emit-handoff
# 옵션: --no-frames  --frame-threshold 10  --frame-dedupe 3  --frame-interval 5  --no-ocr  --ocr-terms
#      --sheet-grid 1x2  --no-sheets  --keep-frames
```

- 결과 폴더: `<원본이름>.frames/` — 기본은 프레임 여러 장을 **1x2 격자로 이어붙인 시트**(수식처럼 작은 글씨가 뭉개지지 않게 2x2보다 칸을 크게 잡음)
  (`sheet_01_00-00-12~00-03-40.jpg` …) + `frames.md` + `frames.json`이다. 채팅 첨부 개수
  제한을 피하려는 것이라, **낱장(`0001_00-14-32.jpg`)은 기본적으로 지워지고 시트만 남는다**
  (`--keep-frames`로 낱장도 보관 가능, `--no-sheets`로 시트 자체를 끄면 예전처럼 낱장만 남는다).
- **오디오 트랙이 없는 영상(화면 녹화)은 전사 없이 캡처만 처리한다.** 이 경우 `--json` 결과의 `frames_only`가 `true`다.
- 시트 각 칸 좌상단에 "번호 · 시간"(`HH:MM:SS`) 라벨이 있다. 시간은 **영상 파일 기준**이라
  전사문의 `[HH:MM:SS]`와 그대로 맞는다(배속 녹화라면 실제 강의 시간과는 다르다).
- `frames.md`의 캡처 목록 표는 시트가 있으면 "시트" 열(예: `sheet_01` · 왼쪽 위)로 어느 시트의
  어느 칸인지 알려준다. 시트가 없으면(옵션으로 끔) 예전처럼 "파일" 열이다.

### 조회

```bash
/path/to/lecture-scribe/.venv/bin/lecture-scribe list --topic 정합 --json    # 인덱스에서 강의 찾기
/path/to/lecture-scribe/.venv/bin/lecture-scribe reindex ~/Documents/LectureScribe --recursive
```

`reindex`는 **전사를 다시 하지 않는다.** md의 front matter만 읽어 인덱스를 다시 만든다.

## 출력 위치와 형식

| 파일 | 내용 |
|---|---|
| `<원본이름>.md` | front matter + `## [HH:MM:SS]` 섹션 본문 |
| `<원본이름>.txt` | 순수 텍스트 |
| `<원본이름>.transcript.json` | 세그먼트별 타임스탬프·신뢰도 + 설정 스냅샷(근거 확인용) |
| `<원본이름>.handoff.md` | 후속 작업 컨텍스트 (`--emit-handoff`) |
| `<원본이름>.frames/` | 영상 입력의 화면 캡처 (`frames.md`, `frames.json`, 시트 이미지) |
| `~/Documents/LectureScribe/` | 위 결과의 미러 (`<상위폴더>__<이름>.md`) |
| `~/Documents/LectureScribe/index.jsonl` | 전사 1건당 1행 인덱스 |

**여러 강의를 찾을 때는 폴더를 통째로 읽지 말고 `index.jsonl` 한 파일만 읽어라.**
90분 강의 수십 개를 매번 읽는 것은 컨텍스트 낭비다.

### front matter 스키마

```yaml
---
source_audio: /path/to/lecture.m4a
transcribed_at: 2026-09-02T14:22:10+09:00
duration_sec: 5412
language: ko
model: large-v3
backend: faster
topic: 마이크로파공학 — 임피던스 정합과 스미스 차트
glossary: [임피던스 정합, 스미스 차트, 반사계수]
segment_count: 812
avg_logprob: -0.41
low_confidence_ratio: 0.037
low_confidence_marker: "⟨?⟩"
marker_meaning: 음성 인식 신뢰도가 낮은 구간. 내용을 추측으로 보완하지 말 것.
---
```

## 후속 작업 규칙 (반드시 지킬 것)

1. **`⟨?⟩` 마커가 붙은 구간은 음성 인식 신뢰도가 낮다.**
   요약·개념 정리에서 이 구간의 내용을 **추측으로 보완하지 마라.**
   필요하면 "해당 구간 확인 필요"로 남겨라. 그럴듯하게 메우는 것이 가장 나쁜 실패다.
2. **인용은 `[HH:MM:SS]` 형식으로 위치를 함께 표기하라.** 본문의 `## [HH:MM:SS]`
   섹션 헤더와 `.transcript.json`의 `start`/`end`로 위치를 확인할 수 있다.
3. **전문 용어 표기는 front matter의 `glossary`를 따르라.** 본문에 다른 표기가 있어도
   glossary 표기로 통일한다.
4. **전사문을 요약본으로 덮어쓰지 마라.** 원본 전사는 불변 자산이다.
   요약은 새 파일에 쓴다.
5. **90분 파일 전사는 수 분~수십 분 걸린다.** 중간에 중단하거나 재실행하지 마라.
   진행 상황이 필요하면 `--progress-json`을 쓴다.
6. 오디오를 클라우드 STT로 보내지 마라. 이 도구는 전 과정 로컬 처리다.

## 화면 캡처(`.frames/`)가 있을 때의 규칙

7. **`frames.md`를 먼저 읽어라.** 슬라이드 시간과 화면 글자(OCR)가 표로 들어 있다.
   이미지는 전부 열지 말고, **OCR만으로 부족할 때(수식, 그림, 도표)만** 필요한 것만 열어라.
   이미지 한 장은 텍스트 수백 줄만큼의 토큰을 쓴다.
8. **OCR은 수식을 읽지 못하고 글자를 잘못 읽을 수 있다**(예: `Filters` → `Fitters`). 수식·기호가
   필요하면 이미지를 열어 확인하고, OCR 글자를 그대로 인용하지 마라.
8b. **이미지는 보통 시트(격자로 여러 프레임을 이어붙인 것)다.** 시트 한 칸이 원하는 프레임이면,
   `frames.md`의 "시트" 열(예: `sheet_01` · 왼쪽 위)로 어느 시트의 어느 칸인지 확인하고 그
   시트 이미지 전체를 열어라(칸만 잘라서 볼 수는 없다). 시트는 칸이 작아 수식이 뭉개질 수 있으니,
   정말 필요하면 사용자에게 `--keep-frames`(낱장 보관)로 다시 처리해 달라고 요청하라.
9. **슬라이드와 발화가 다르면 둘 다 적어라.** 어느 쪽이 맞는지 추측하지 마라.
   `⟨?⟩` 저신뢰 구간에서는 슬라이드를 **참고 근거**로만 쓰고, 발화 내용을 슬라이드로 지어내 메우지 마라.
10. 전사가 없는 결과(`frames_only`)는 **슬라이드에 적힌 내용만** 정리할 수 있다. 강의 음성 내용은 알 수 없다고 밝혀라.
11. 슬라이드에서 뽑은 용어(`frames.md`의 "슬라이드에서 추출한 용어")는 OCR 결과라 오탈자가 섞일 수 있다.
    용어 표기는 front matter의 `glossary`를 우선한다.

## 실패 시 진단 순서

1. **ffmpeg 확인**: `/opt/homebrew/bin/ffprobe -version`
   없으면 `brew install ffmpeg`.
2. **파일 접근 권한**: iCloud Drive·Desktop·Documents 파일은 접근 권한이 필요하다.
   `ls -l` 로 읽을 수 있는지 먼저 확인. 시스템 설정 > 개인정보 보호 및 보안 > 파일 및 폴더.
   `.<이름>.icloud` 스텁이 있으면 아직 내려받지 않은 파일이다.
3. **모델 캐시**: `~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3`
   첫 실행은 약 3GB를 내려받는다. 실패하면 `HF_HUB_DISABLE_XET=1`로 재시도한다
   (도구가 자동으로 한 번 재시도한다).
4. **로그**: `~/Library/Logs/LectureScribe/lecture-scribe.log`

## 종료 코드

`0` 전체 성공 / `1` 일부 실패 / `2` 전체 실패 / `130` 사용자 취소
