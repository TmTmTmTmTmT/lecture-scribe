# TROUBLESHOOTING

문제가 생기면 먼저 로그를 본다: `~/Library/Logs/LectureScribe/lecture-scribe.log`

---

## ffmpeg / ffprobe를 찾을 수 없습니다

```
ffprobe 을(를) 찾을 수 없습니다. `brew install ffmpeg` 후 다시 시도하세요.
```

```bash
brew install ffmpeg
which ffprobe          # /opt/homebrew/bin/ffprobe 여야 정상
```

Homebrew가 다른 위치에 있으면 환경변수로 지정한다:

```bash
export LECTURE_SCRIBE_FFMPEG_DIR=/usr/local/bin
```

Quick Action에서만 실패한다면 아래 "Quick Action에서만 실패한다"를 보라.

---

## Quick Action에서만 실패한다 (PATH 문제)

Finder가 실행하는 컨텍스트에는 Homebrew PATH가 없다. 그래서 설치 스크립트가
실행 파일과 ffmpeg의 **절대 경로를 워크플로 안에 직접 써 넣는다.**

프로젝트를 옮겼거나 `.venv`를 다시 만들었다면 경로가 어긋난 것이다. 다시 설치한다:

```bash
./quickaction/install.sh
```

현재 워크플로에 박힌 경로 확인:

```bash
python3 -c "
import plistlib
d = plistlib.load(open('$HOME/Library/Services/Transcribe.workflow/Contents/document.wflow','rb'))
print(d['actions'][0]['action']['ActionParameters']['COMMAND_STRING'])" | head -8
```

---

## 우클릭 메뉴에 안 보인다

1. 시스템 설정 → 키보드 → 키보드 단축키 → **서비스** → "LectureScribe" 항목 체크
2. Finder 재시작: `pkill -HUP Finder`
3. 서비스 등록 확인:

```bash
/System/Library/CoreServices/pbs -dump | grep -c LectureScribe   # 2가 나와야 정상
```

---

## "확인되지 않은 개발자" / Gatekeeper 경고

`LectureScribe.app`은 ad-hoc 서명만 되어 있다(Apple 개발자 인증서 없음).

- 처음 열 때: **우클릭 → 열기** → 대화상자에서 다시 **열기**
- 또는 시스템 설정 → 개인정보 보호 및 보안 → 아래쪽 "확인 없이 열기"
- 격리 속성을 직접 지우려면:

```bash
xattr -dr com.apple.quarantine dist/LectureScribe.app
```

---

## 파일 접근 권한 거부

```
파일을 찾을 수 없습니다 / 결과 파일을 저장하지 못했습니다
```

Desktop·Documents·Downloads·iCloud Drive의 파일은 접근 권한이 필요하다.

- 시스템 설정 → 개인정보 보호 및 보안 → **파일 및 폴더** → Finder/Automator/터미널 항목 허용
- 그래도 안 되면 **전체 디스크 접근 권한**에 터미널(또는 앱)을 추가
- 쓰기가 막힌 볼륨(읽기 전용·네트워크)이면 결과는 `output.fallback_dir`
  (기본 `~/Documents/LectureScribe`)에 저장되고 그 사실이 알림에 표시된다

## iCloud에서 아직 내려받지 않은 파일

```
iCloud Drive에서 아직 내려받지 않은 파일입니다.
```

`.<파일명>.icloud` 스텁만 있는 상태다. Finder에서 파일을 열어 내려받은 뒤 다시 시도한다.

```bash
ls -a "폴더" | grep icloud     # 스텁 확인
brctl download "파일경로"       # 강제 내려받기(비공식)
```

---

## 모델 다운로드 실패

```
모델 'large-v3' 을(를) 불러오지 못했습니다.
```

로그에 `CAS Client Error` 또는 `Xet`이 보이면 Hugging Face의 Xet 전송 문제다.
**도구가 자동으로 한 번 우회 재시도**하지만, 수동으로 하려면:

```bash
HF_HUB_DISABLE_XET=1 uv run lecture-scribe "파일.m4a"
```

그 외 확인:

```bash
du -sh ~/.cache/huggingface/hub/*      # 캐시 상태 (large-v3 약 3GB)
df -h ~                                 # 디스크 여유
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-large-v3   # 손상 시 재다운로드
```

모델 캐시 위치를 바꾸려면 `export LECTURE_SCRIBE_MODEL_DIR=/경로`.

---

## 환각(hallucination)·반복이 생긴다

무음이 긴 강의 녹음에서 잘 발생한다. 조정 순서:

| 증상 | 조정 |
|---|---|
| 같은 문장이 반복됨 | `decoding.no_speech_threshold` ↑ (0.6 → 0.7), `compression_ratio_threshold` ↓ (2.4 → 2.0) |
| 무음 구간에서 없는 말이 생김 | `decoding.vad_filter: true` 유지, `min_silence_duration_ms` ↓ (500 → 300) |
| 신뢰도 낮은 문장이 많음 | 모델을 `large-v3`로, `beam_size` ↑ (5 → 8) |
| 앞부분이 통째로 빠짐 | `prompt.use_initial_prompt: false` (기본값). `--no-initial-prompt` |
| 프롬프트를 넣으니 결과가 무너짐 | `--no-prompt`로 비교. 붕괴가 감지되면 자동 폴백이 동작한다 |

`--batched`는 빠르지만 **`condition_on_previous_text` / `hallucination_silence_threshold` /
temperature 폴백 체인이 무시된다**(faster-whisper 내부 하드코딩). 환각이 문제라면 배치를 끄라.

결과 md의 `⟨?⟩` 마커와 front matter의 `low_confidence_ratio`로 품질을 먼저 확인하라.

---

## 전문 용어가 계속 틀린다

1. **용어 목록에 실제 표기를 넣는다** (GUI "용어" 칸 또는 `--glossary`).
2. 그래도 틀리면 **교정 사전**에 넣는다.
   `~/Library/Application Support/LectureScribe/settings.json`:

```json
"presets": {
  "전자회로": {
    "corrections": { "자궁": "잡음", "반조체": "반도체" }
  }
}
```

같은 파일·같은 설정이면 전사 결과는 **결정적**이다. 한 번 돌려서 나온 오인식을
사전에 넣고 다시 돌리면 그대로 교정된다.

3. 유사도 교정(오타 허용)은 `--fuzzy` (rapidfuzz 필요: `uv sync --extra fuzzy`).

---

## 한국어 파인튜닝 모델로 바꿨더니 결과가 엉망이다

정상이다. `large-v3-turbo-ko`(`ghost613/faster-whisper-large-v3-turbo-korean`)를
실측한 결과 강의 녹음에서 **출력의 90% 이상이 소실**되고 `확보 확보 확보 …` 같은
반복 루프에 빠졌다. 뉴스·방송체(`…라고 조언했다`)가 섞여 나오는 것으로 보아
좁은 도메인에 과적합된 모델이다.

앱이 이 상태를 자동 감지해 다음을 수행한다:

1. 프롬프트를 빼고 재전사
2. 재전사 후에도 비정상이면 경고
3. **결과 파일 상단에 품질 경고 주석** 삽입

```
# 전사 품질 경고: 한 구간에서 '확보'가 12회 연속 반복(반복 루프)
```

이 경고가 보이면 `--model large-v3`(또는 `large-v3-turbo`)로 되돌려라.

## 주제와 무관한 용어를 넣었더니 더 나빠졌다

정상이다. 프롬프트는 내용과 맞을 때만 도움이 된다.
실측에서 변조 관련 용어집을 잡음 강의에 넣었더니 `잡음` → `자궁`으로 잘못 인식됐다.
용어는 그 강의에 실제로 나오는 것만 넣는다.

---

## GUI가 안 뜬다 / 창이 멈춘다

```bash
uv run python -m lecture_scribe.gui.app      # 터미널에서 직접 실행해 오류 확인
```

- `ModuleNotFoundError: PySide6` → `uv sync`
- 앱은 뜨는데 아무 반응이 없다 → 모델 다운로드 중일 수 있다. 상단에 "모델 준비 중"이 표시된다.
- 전사 중에도 창은 반응해야 한다(실측 최대 지연 143ms). 완전히 멈추면 로그를 첨부해 보고하라.

---

## 종료 코드가 이상하다

| 코드 | 의미 |
|---|---|
| 0 | 전체 성공 |
| 1 | 일부 실패 (나머지는 정상 저장됨) |
| 2 | 전체 실패 또는 처리할 파일 없음 |
| 130 | 사용자 취소 (진행 중이던 파일은 저장하지 않음, 임시 파일도 남기지 않음) |

`--json`을 쓰면 실패해도 유효한 JSON이 stdout으로 나오고, `exit_code` 필드에 같은 값이 담긴다.

---

## GPU(Metal) 전사가 시작도 못 하고 전부 실패한다

메모리가 넉넉하지 않을 때 나던 증상이다. 원인은 mlx-whisper 0.4.3의 전역 모델 캐시다.

```python
class ModelHolder:          # mlx_whisper/transcribe.py
    model = None
    @classmethod
    def get_model(cls, model_path, dtype):
        if cls.model is None or model_path != cls.model_path:   # 락 없음
            cls.model = load_model(model_path, dtype=dtype)
```

검사-후-행동(check-then-act) 경쟁 상태다. 스레드 3개가 동시에 들어가면 **셋 다**
`model is None`을 보고 각자 모델을 통째로 올린다(실측 재현: 3스레드 → 3회 로드).
large-v3는 mlx에서 1회 3.1GB라 3배면 9.3GB — 16GB 기기에서 전부 OOM으로 죽는다.

해결(앱에 반영됨):

- `backends/mlx.py`의 `_MLX_LOCK`으로 `transcribe()` 호출을 직렬화한다.
- `limit_parallel(..., backend="mlx")`는 항상 1을 돌려준다. 모델 인스턴스가
  하나뿐이라 동시에 돌려도 빨라지지 않는다.
- 시작 전에 가용 메모리를 재고, 부족하면 Metal 안쪽에서 죽기 전에 막고
  대안(가벼운 모델 / CPU 백엔드 / 다른 앱 닫기)을 안내한다.

---

## 전사가 실패할수록 메모리가 계속 늘어난다

두 군데서 새고 있었다.

1. `MlxWhisperBackend.unload()`가 자기 필드(`_tokenizer`, `_ready`)만 비웠다.
   실제로 메모리를 쥐고 있는 것은 `ModelHolder.model`과 mlx 버퍼 캐시다.
   지금은 `perf.mlx_release_model()`이 둘 다 비운다(실측: 2.71GB → 0.00GB).
2. 전사에 실패한 백엔드가 GUI의 `_backend_cache`에 그대로 남았다. 반쯤 로드된
   모델이 메모리를 계속 붙들고, 다음 작업이 같은 인스턴스를 다시 써서 또 실패했다.
   지금은 워커가 실패 경로에서 `_dispose_backend()`를 불러 캐시에서 빼고
   `unload()` + `release_memory()`를 한다.

확인:

```bash
uv run pytest tests/test_gui_fixes.py -q
```

---

## 큐에 파일 목록이 있으면 드래그앤드롭이 안 된다

`QListWidget`은 **뷰포트**에서 드래그를 가로챈다. 위젯 자체에
`setAcceptDrops(False)`를 걸어도 뷰포트는 그대로다. 그리고 `dragMoveEvent`를
구현하지 않으면 드래그가 위젯 위를 지나는 동안 기본 구현이 이벤트를 무시해서
커서가 '금지'로 바뀌고 놓아도 아무 일이 없다. 둘 다 필요하다.

```python
self.queue_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
self.queue_list.viewport().setAcceptDrops(False)
# + DropZone.dragMoveEvent 에서 acceptProposedAction()
```

---

## 큐 행의 내용이 왼쪽에 몰려 붙고 상태 글자가 잘린다

`item.setSizeHint(row.sizeHint())`는 **폭까지** 내용 기준으로 정한다. 그 폭이
뷰포트보다 좁으면 행이 좁게 그려져 내용이 왼쪽에 뭉친다. 폭은 뷰포트 폭으로
고정해야 한다. 뷰포트 크기는 `DropZone.resizeEvent`보다 늦게 확정되므로
뷰포트에 이벤트 필터를 걸어 `Resize`를 받아 다시 계산한다.

---

## 전사 중 창이 멈춘다(응답 없음)

재현되지 않았다. 실측으로 다음은 **원인이 아님**이 확인됐다.

| 후보 | 실측 |
|---|---|
| UI 스레드 작업량 | 용어 자동 제안 547세그먼트에 6.4ms |
| 진행률 시그널 폭주 | 세그먼트 간격 중앙값 3.58초 |
| 전사 중 모달 대화상자 | 해당 경로 없음 |
| 스레드 과잉 할당 | 45초 클립·동시 2건에서 UI 지연 최대 9.6ms |

가장 유력한 것은 **메모리 압박에 따른 스왑**이다(위 누수 두 건이 직접 원인).
그래도 단정할 수 없으므로 `gui/watchdog.py`를 넣었다. 메인 스레드가 3초 이상
멈추면 그 시점의 **스택·RSS·가용 메모리·스왑·스레드 수**를 로그에 남긴다.

증상이 다시 나면 로그를 확인하라:

```bash
grep -A 30 "응답하지 않습니다" ~/Library/Logs/LectureScribe/lecture-scribe.log
```

예방 차원에서 `cpu_threads=0`(전체 코어)도 손봤다. CTranslate2가 코어를 전부
가져가고 `num_workers`까지 곱해지면 10코어에 스레드 20개가 몰린다.
`perf.usable_cpu_threads()`가 UI 몫으로 2코어를 남기고 동시 전사 수로 나눈다.
실측상 속도 손해는 없었다(45초 클립 9.7초 → 9.4초).

---

## 교정(--correct)이 동작하지 않는다

교정은 **선택 기능**이고 기본은 꺼져 있다. 전사는 교정 없이도 완결된다.

```bash
brew install ollama
ollama pull gemma4:e4b     # 또는 gemma4:e2b (더 빠르고 가벼움)
uv run lecture-scribe FILE --correct
```

데몬은 **앱이 알아서 띄운다**(실측 0.3초). `ollama serve`를 직접 돌릴 필요 없다.
그래도 안 되면:

```bash
curl -s http://localhost:11434/api/version    # 데몬 응답 확인
ollama list                                    # 모델 설치 확인
grep "교정" ~/Library/Logs/LectureScribe/lecture-scribe.log
```

Ollama가 없거나 모델이 없으면 **교정만 건너뛰고 전사 결과는 그대로 저장된다.**
건너뛴 이유는 결과 파일 상단 경고와 로그에 남는다.

---

## 교정이 이상한 걸 제안한다

정상이다. 교정 모델은 **오디오를 듣지 못하고 문맥만 보고 추정한다.**
그래서 전사문은 고치지 않고 `원문[→교정]` 주석만 붙인다. 원문 글자는 하나도 지워지지 않는다.

실측(전자회로 강의 918자 구간):

| 모델 | 제안 | 정답 | 정확도 | 소요 |
|---|---|---|---|---|
| gemma4:e4b | 9 | 8 | 89% | 33.5s |
| gemma4:e2b | 7 | 5 | 71% | 19.7s |

품질을 좌우하는 것은 모델보다 **프롬프트에 주제·용어집이 들어갔는지**다.
둘을 빼면 같은 모델이 1/7까지 떨어진다(실측). GUI의 "전사 주제"와 "용어" 칸을 채워라.

제안이 너무 많으면 신뢰도 하한을 올린다:

```bash
uv run lecture-scribe FILE --correct --correct-confidence high
```

기계적으로 걸러지는 것들(자동):

| 폐기 사유 | 예 |
|---|---|
| 전사문에 없는 문자열(환각) | 모델이 지어낸 원문 |
| 철자 변환일 뿐 | `가우시안 → Gaussian`, `화이트 → White` |
| 원문과 동일 / 중복 / 겹침 | `어댑티브` vs `어댑티브, 화이트` |
| 신뢰도 미달 | 기본은 `low` 제외 |

폐기된 제안 일부는 `<파일명>.corrections.json`의 `rejected_samples`에 남는다.

---

## 교정 중 메모리가 걱정된다

전사 모델과 교정 모델은 **동시에 상주하지 않는다.** 순서가 이렇다.

1. Whisper 전사
2. **Whisper 모델 해제** + `release_memory()`
3. gemma 교정 (구간을 도는 동안만 상주)
4. **gemma 해제** — 실측 4,580MB → 51MB, 1초
5. 파일 저장

gemma는 별도 프로세스(ollama)라 앱 메모리와 아예 분리돼 있다. 확인:

```bash
curl -s http://localhost:11434/api/ps      # 적재된 모델 (교정 후 비어 있어야 정상)
```

---

## GPU(mlx) 백엔드가 시작하자마자 실패한다

```
mlx_whisper.transcribe 실패 ...: FileNotFoundError(2, 'No such file or directory')
```

파일은 멀쩡한데 이 오류가 난다면 **찾지 못한 것은 오디오가 아니라 `ffmpeg` 실행 파일**이다.

`mlx_whisper.audio.load_audio`는 `["ffmpeg", ...]`를 **맨 이름으로** 실행한다
(소스 주석: "Requires the ffmpeg CLI in PATH"). `.app` 번들과 Quick Action은
`launchctl getenv PATH`가 비어 있어 `/usr/bin:/bin:/usr/sbin:/sbin`만 상속받고,
거기에 Homebrew의 ffmpeg는 없다. faster-whisper는 PyAV를 쓰므로 멀쩡한데
**GPU 백엔드만** 죽는 이유가 이것이다.

수정됨: `backends/mlx.py`가 경로 대신 **PyAV로 디코드한 배열**을 넘긴다. 외부
ffmpeg가 아예 필요 없고, 파일 객체로 열어 넘기므로 `9:4 캡스톤디자인.m4a`처럼
콜론이 든 이름도 안전하다.

직접 확인:

```bash
env PATH=/usr/bin:/bin:/usr/sbin:/sbin LECTURE_SCRIBE_FFMPEG_DIR=/opt/homebrew/bin \
  .venv/bin/lecture-scribe "파일.m4a" --backend mlx --model large-v3-turbo
```

---

## 설정 영역과 파일 영역 크기를 바꾸고 싶다

두 영역 사이의 **가로 분할선을 위아래로 끌면** 된다. 조정한 비율은 저장되어
다음 실행에 그대로 복원된다(`window.split_ratio`).

macOS 기본 분할선은 몇 px라 보이지도 잡히지도 않아서, 두께를 10px로 넓히고
손잡이를 그려 두었다. 마우스를 올리면 색이 바뀐다.

조정 범위는 설정 영역 최소 110px ~ 파일 영역 최소 140px 사이다.

---

## 고쳤는데도 같은 오류가 계속 난다 (가장 흔한 착각)

**앱을 껐다가 다시 켜라.**

파이썬은 이미 불러온 모듈을 다시 읽지 않는다. 앱을 켜 둔 채 소스를 고치면
그 프로세스는 **고치기 전 코드로 계속 돈다.** 이미 고친 버그가 그대로 재현되는
것처럼 보인다(실제로 2026-09-04에 이렇게 오진했다).

지금은 앱이 알아서 알려 준다.

- 시작할 때: 로그에 `실행 중인 코드 수정 시각: engine=..., backends/mlx=...`
- 전사가 실패했는데 그 사이 코드가 바뀌었으면: **경고 대화상자**로 재시작 안내

로그로 직접 확인:

```bash
grep -E "시작 —|실행 중인 코드 수정 시각" ~/Library/Logs/LectureScribe/lecture-scribe.log | tail -4
```

찍힌 수정 시각이 실제 파일보다 오래됐으면 낡은 프로세스다.

```bash
stat -f "%Sm %N" src/lecture_scribe/backends/mlx.py
```

---

## 사이드카 JSON을 다른 도구가 읽지 못한다

mlx 백엔드에서 나온 결과라면 `NaN` 때문이었다. mlx-whisper는 일부 세그먼트에
`avg_logprob: NaN`을 돌려준다(실측: 46분 녹음 1,422개 중 22개). 맨 `NaN`은
RFC 8259 위반이라 엄격한 파서가 **파일 전체를 거부한다.**

같은 원인으로 두 가지가 더 조용히 망가졌다.

- 하나만 섞여도 `avg_logprob` 평균 전체가 `nan`이 된다.
- `nan < -0.8`은 항상 False라 **저신뢰 `⟨?⟩` 마커가 붙지 않는다** —
  신뢰도를 모르는 구간이 멀쩡한 것처럼 보인다.

수정됨(3중 방어):

1. `backends/mlx.py`가 비유한값을 경계에서 `-1.0`(저신뢰)으로 바꾸고 개수를 경고한다.
2. `writer.is_low_confidence()`가 NaN을 저신뢰로 판정한다.
3. `writer.dump_json()`이 `allow_nan=False`로 직렬화하고 비유한값을 `null`로 바꾼다.

확인:

```bash
python3 -c "
import json,sys
raw=open(sys.argv[1]).read()
json.loads(raw, parse_constant=lambda c:(_ for _ in ()).throw(ValueError(c)))
print('유효')" "파일.transcript.json"
```

---

## 전사 실패 후 메모리가 안 풀린다

수정됨. 원인은 예외 처리 구조였다.

`transcribe_file()`은 **예외를 삼키고** `FileResult(status="failed")`를 돌려준다
(큐를 계속 돌리려고). 그래서 워커의 `except LectureScribeError` 절이 이 경로에서
**한 번도 실행되지 않았고**, 그 안에 있던 백엔드 정리도 호출되지 않았다.
실패한 백엔드가 캐시에 남아 모델이 메모리를 계속 붙들었다.

지금은 `result.status == "failed"`를 직접 보고 정리한다. 실측:

```
전사 1회 후      mlx active=1.51GB cache=1.20GB holder=loaded
실패 작업 처리 후  mlx active=0.00GB cache=0.00GB holder=None
```

---

## ⌘Q / ⌘W 가 안 먹는다

수정됨. 메뉴 막대가 없는 창이라 기본 단축키가 붙지 않았다.

`QKeySequence.StandardKey`는 **쓰면 안 된다.** 실측하니 `Quit`은 빈 시퀀스가 되고
`Close`는 ⌘W가 아니라 ⌘F4로 잡혔다. macOS에서 Qt는 Ctrl을 ⌘로 매핑하므로
`"Ctrl+Q"` / `"Ctrl+W"`라고 명시해야 실제로 ⌘Q/⌘W가 된다.

창을 닫으면 `QApplication.quit()`까지 호출한다. 프로세스가 남아 있으면 코드를
고쳐도 옛 코드가 계속 돌기 때문이다.

---

## GPU 전사 첫 실행에서 3초쯤 멈춘다

정상이다. mlx는 `hallucination_silence_threshold`를 쓰면 `word_timestamps=True`가
되고, 그 정렬 계산(`dtw_cpu`)이 **numba JIT 컴파일**을 유발한다. 프로세스당 한 번뿐이고
두 번째 파일부터는 없다. 워치독 로그에 `numba/core/dispatcher.py`가 보이면 이것이다.

---

## 전사 시작까지 오래 걸린다 / 초반에 0%에서 멈춘 것 같다

백엔드마다 원인이 달랐다(실측, 46분 파일).

| 단계 | faster (CPU) | mlx (GPU) |
|---|---|---|
| 모델 로드 | 2.91s | 0.40s |
| `transcribe()` 반환 | 17.88s | **400.70s** |
| 첫 세그먼트 | 16.07s | 0.00s |

**mlx는 지연 생성을 하지 않는다.** 파일 전체를 다 돌린 뒤 한꺼번에 반환해서,
6분 40초 내내 0%에 멈춰 있고 취소도 되지 않았다.

수정: 오디오를 창 단위로 잘라 여러 번 호출한다(첫 창 30초, 이후 120초).

| | 전 | 후 |
|---|---|---|
| `transcribe()` 반환 | 400.70s | **2.57s** |
| 첫 세그먼트까지 | 33.49s | **5.27s** |
| 진행률 | 0% 고정 후 100% | 창마다 갱신 |
| 취소 | 불가 | 창 경계에서 가능 |

CPU의 17.88초는 Silero VAD가 파일 전체를 훑는 시간이다. 줄일 수 없다.
급하면 `decoding.vad_filter: false`로 끄되, 무음 구간 환각이 늘어난다.

---

## GPU 전사에서 hotwords·VAD 체크박스가 꺼져 있다

mlx-whisper가 그 기능들을 구현하지 않았다. `capabilities()`가 이를 알려 주고
GUI가 위젯을 비활성화한다. 정상 동작이다.

다만 **용어집은 계속 전달된다.** hotwords를 못 쓰는 백엔드에서는
`build_prompt_plan_for()`가 용어를 `initial_prompt`로 돌린다. 그러지 않으면
사용자가 입력한 용어가 조용히 버려진다(이 앱의 핵심 기능인데 GPU에서만 동작하지
않는 셈이 된다).

로그로 확인:

```
프롬프트 58/223 토큰, 용어 4개 반영: 이번 시간에는 ... IMU, 센서, 데이터셋 ...
```

faster-whisper에서 `initial_prompt`를 켜면 앞부분이 잘리는 문제가 있었지만
**mlx에서는 재현되지 않았다**(실측: 프롬프트 유무 모두 0.00초에서 시작).

GPU에서 빔 서치도 쓸 수 없다(mlx 0.4.3 미구현, 그리디만). 정확도가 중요하면
CPU 백엔드를 쓰라.

---

## 알림을 눌렀더니 스크립트 에디터가 열린다

GUI에서는 수정됨. `osascript`로 낸 알림은 **Script Editor 소유**라 눌러도 그게 열린다.

GUI에서는 `QSystemTrayIcon.showMessage()`로 앱 이름으로 알림을 내고, 클릭하면
창이 올라온다(`messageClicked`). 메뉴 막대 아이콘을 눌러도 창이 올라온다.
트레이를 쓸 수 없는 환경(화면 없는 실행 등)으로 폴백할 때는 로그에
"트레이 알림을 쓸 수 없어 osascript로 대체합니다"가 남는다(원인 추적용).

**CLI / Quick Action 경로는 여전히 `osascript`이고, 여기서는 계속 스크립트
에디터가 열린다.** Qt가 없는 경로라 GUI와 같은 방식으로 못 고친다
(FIX_GUIDE_3.md I-05 — 검토 결과 "A. 현행 유지 + 안내"로 결정, 2026-09-06).
번들에 알림 전용 모드를 만들어 앱 소유로 띄우는 방안(I-05 선택지 B)은
검토는 됐지만 착수 안 함 — Quick Action 사용 빈도 대비 복잡도가 크다고 판단.
필요해지면 FIX_GUIDE_3.md §3 I-05를 다시 본다.

---

## 알려진 함정 (개발자용)

- **zsh에서 `status`는 읽기 전용 변수다** (`$?`의 별칭). Quick Action 스크립트는
  `/bin/zsh`로 돌기 때문에 `status=$?`를 쓰면 실패한다. `rc=$?`를 쓴다.
- **`9:1 전자회로.m4a`처럼 `이름:`으로 시작하는 상대 경로**는 ffmpeg이 `9:`을
  프로토콜로 해석해 `Protocol not found`로 실패한다. 항상 절대 경로를 넘긴다
  (`audio.media_arg()`가 처리).
- **`BatchedInferencePipeline`은 일부 인자를 무시한다**(내부 하드코딩).
  `capabilities().ignored_options()`가 무시되는 항목을 알려준다.
- **`hallucination_silence_threshold`는 `word_timestamps=True`에서만 동작한다.**
- **mlx-whisper는 `avg_logprob`에 NaN을 돌려준다.** 백엔드 경계에서 걸러야 한다.
  `nan < threshold`가 False라 저신뢰 판정이 조용히 빠지고, JSON도 무효해진다.
- **`json.dumps`는 기본으로 맨 `NaN`을 쓴다**(`allow_nan=True`). 사이드카는
  `writer.dump_json()`을 써라.
- **`mlx_whisper.transcribe()`는 지연 생성을 하지 않는다.** 전체를 다 돌린 뒤
  반환한다. 진행률·취소가 필요하면 호출자가 오디오를 잘라 여러 번 불러야 한다.
- **`osascript` 알림은 Script Editor 소유다.** 앱 소유 알림은
  `QSystemTrayIcon.showMessage()`.
- **화면 없는 플랫폼에서 `QSystemTrayIcon`은 만들어지지만 동작하지 않는다.**
  여러 개 쌓이면 정리 시점에 프로세스가 죽는다(실측: 테스트 전체 실행 중 세그폴트).
  `platformName()`이 offscreen/minimal이면 만들지 않는다.
- **`transcribe_file()`은 예외를 삼키고 `status="failed"`를 돌려준다.** 호출부에서
  `except`만 믿으면 실패 처리가 통째로 빠진다(실제로 메모리 해제가 빠졌다).
- **`QKeySequence.StandardKey.Quit`은 빈 시퀀스, `Close`는 ⌘F4다.** ⌘Q/⌘W는
  `"Ctrl+Q"`/`"Ctrl+W"`로 명시한다.
- **`QSplitter` 손잡이는 스타일시트로 점을 못 그린다.** `createHandle()`을 재정의해
  직접 그려야 한다(`gui/splitter.py`).
- **부모가 화면에 없으면 `isVisible()`은 항상 False다.** 테스트에서는 `isVisibleTo()`.
- **소스를 고쳐도 실행 중인 프로세스에는 반영되지 않는다.** 재시작해야 한다.
  `provenance.stale_sources()`가 이 상태를 감지한다.
- **`mlx_whisper`에 오디오 *경로*를 넘기면 안 된다.** 내부에서 맨 이름 `ffmpeg`를
  실행하므로 PATH가 최소인 실행 컨텍스트(.app, Quick Action)에서 죽는다.
  PyAV로 디코드한 배열을 넘긴다.
- **QScrollArea를 QSplitter에 넣을 때는 세로 sizePolicy를 `Ignored`로.** 기본값이면
  스크롤 영역이 내용 전체 높이를 요구해 분할선 위치가 그 값에 끌려간다
  (실측: 0.40으로 설정해도 0.78이 됐다).
- **생성자에서 건 `QSplitter.setSizes()`는 첫 표시 때 재배치에 덮인다.**
  `showEvent`에서 `QTimer.singleShot(0, ...)`으로 다시 적용해야 정확하다.
- **Ollama `think`는 기본이 켜짐이다.** 끄지 않으면 은닉 사고 토큰이 출력 예산을
  다 먹어 **빈 응답**이 오고 17배 느려진다(실측 20.7초 → 1.2초). 항상 `think: false`.
- **`keep_alive: 0`을 매 요청에 주면 구간마다 모델을 다시 올린다.** 로드 비용이
  구간 수만큼 붙는다(e4b 약 7.7초). 도는 동안은 `"5m"`으로 붙잡고 끝나면 한 번만 내린다.
- **mlx-lm의 4bit gemma-3n은 쓸 수 없다.** 같은 과제에서 ollama(Q4_K_M) 89%인데
  mlx 4bit는 10%였고 구자라트 문자가 섞여 나왔다. 비트 수가 아니라 양자화 방식 차이다
  (llama.cpp k-quant vs mlx 단순 그룹 양자화). arm64 macOS 휠을 내는 파이썬 GGUF
  런타임은 없다(llama-cpp-python/gpt4all/ctransformers 전부).
