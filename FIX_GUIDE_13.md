# FIX_GUIDE_13 — OCR 용어 교정 연결 · gemma 교정 프롬프트 개선 · 프레임 시트화

작성: Opus (2026-09-26). 실행: Sonnet. 이 문서 범위 밖 설계 변경 금지 — 막히면 STATUS.md "Opus 확인 필요"로 반환.

## 0. 확정 사항 (사용자 결정)

- 결과물은 **Claude 채팅**에 올린다 → zip 안 씀(채팅은 zip 안 이미지를 못 봄). 대신 **프레임 여러 장을 격자로 이어붙인 시트 이미지**.
- 순서: **E(평가셋) → C(OCR→교정) → P(프롬프트 개선) → S(시트화)**. S는 C/P와 독립이라 병행 가능하나, 한 번에 한 항목씩 완료·기록.
- 전사는 항상 mlx(GPU). CPU 폴백 금지(메모리 규칙).

## 1. 작업 목록

| ID | 내용 | 코드 변경 | 게이트 |
|---|---|---|---|
| E-01 | 교정 평가셋 + 채점 스크립트 | scripts만 | 정답목록 확정 |
| C-01 | OCR 용어를 교정 프롬프트에 별도 섹션으로 전달 | correction/engine/config/cli/gui | E-01로 비교, 기본값 결정 |
| P-01 | 교정 프롬프트 가설 실험 | 실험은 scripts만, 채택분만 correction.py | 가설별 게이트 |
| S-01 | 프레임 시트(격자) 생성 | video_stage/frames/config | 해상도 검증 |
| S-02 | 낱장 이미지 정리(삭제) + 안전장치 | video_stage | 검증 실패 시 보존 |
| S-03 | 하류 반영(md/json/handoff/index/cli/gui/SKILL/README) | 여러 파일 | 전체 테스트 |

---

## E-01. 교정 평가셋

**목적**: 기존 실측이 918자·9건뿐 → 프롬프트 수정 시 과적합 위험. 먼저 기준을 만든다.

**방향**
- 소리 있는 샘플(이전 세션의 "샘플 2", 전자회로 계열)의 mlx 전사 결과(`.json` 세그먼트)를 사용. `LSsamples/`가 현재 비어 있으므로 이전 출력 파일을 먼저 찾고, 없으면 **사용자에게 샘플 재업로드 요청**(임의 대체 금지).
- 평가 구간: 최소 3,000자 이상(청크 3개 이상). 가능하면 전체.
- 정답 목록 `scripts/c_eval/gold_<sample>.json`: 항목 = `original`(전사문 글자 그대로), `expected`(올바른 용어), `kind`(오인식 용어/약어/기타). **Sonnet이 초안 작성 → 사용자 확인 후 확정.** 확정 전 실험 결과는 참고치로만 기록.
- "교정하면 안 되는 곳" 목록(`negatives`)도 함께: 올바른 음차, 말버릇 등.
- 채점 스크립트 `scripts/c_eval/score.py`: 교정 결과 JSON(`corrections.json` 형식) vs 정답 → 정답/오답/누락/negative 오교정 건수, precision, recall, 소요시간. 매칭은 `original` 포함관계 + `expected` 정규화 비교(대소문자·공백 무시).
- 반복: gemma는 temperature 0.2라 결과가 흔들림 → **설정당 3회 실행, 평균과 최소값 기록.**
- 전사는 1회만 하고 세그먼트를 재사용(교정만 반복). 교정 호출은 `propose_corrections`를 스크립트에서 직접 호출.

**영향 범위**: `scripts/c_eval/` 신규만. 앱 코드 변경 없음.

**검증**: 현재 프롬프트로 기준선(baseline) 수치 산출 → STATUS.md에 기록.

---

## C-01. OCR 용어 → 교정 프롬프트

**원인/목적**: 교정은 용어집 유무로 정확도가 1/7↔8/9로 갈린다(실측). 슬라이드 표기는 정답 후보로 가장 직접적인 근거. 전사 프롬프트 주입은 head-loss 붕괴로 실패했지만 교정은 텍스트 후처리라 그 위험이 없다.

**방향**
- OCR 용어는 **"이미 확인된 용어"에 섞지 않는다.** OCR 오타("Fitters", "Windowed-sing")가 정답처럼 취급되면 오교정 유발. 프롬프트에 별도 섹션 추가:
  "슬라이드에서 읽은 표기(OCR, 오타 가능 — 참고만):" + 목록.
- `build_prompt`에 선택 인자(`slide_terms`)를 추가. 비어 있으면 섹션 자체를 넣지 않는다(기존 프롬프트와 바이트 동일 유지 → 기존 테스트 불변).
- 파일별로만 적용. 프리셋·용어 통계·교정 규칙 파일에는 절대 기록하지 않는다(기존 V-06 원칙 동일).
- 설정: `CorrectionSettings.use_ocr_terms: bool`. 전사용 `video.ocr_terms_to_prompt`와 **분리**(전사 쪽은 게이트에서 효과 없음 판정, 교정 쪽은 별개 판정). 기본값은 게이트 결과로 결정 — 실험 전엔 False.
- CLI `--correct-ocr-terms/--no-correct-ocr-terms`, GUI 교정 섹션 체크박스(OCR 불가 또는 교정 꺼짐이면 비활성).
- `corrections.json` 사이드카에 `slide_terms_used`(리스트) 기록 → 결과 추적 가능.
- 검증 규칙 추가 없음(기존 `validate_proposals` 그대로). OCR 일치 가산점은 P-01 가설로 분리.

**영향 범위**: `correction.py`(build_prompt, propose_corrections 인자, sidecar), `engine.py`(교정 호출부에 video_stage_result.ocr_terms 전달), `config.py`, `cli.py`, `gui/settings_panel.py`, `gui/strings_ko.py`, 테스트.

**검증**
- 단위: 슬라이드 섹션 유무에 따른 프롬프트 내용, 빈 목록이면 기존 프롬프트와 동일, 프리셋 불변.
- 게이트(E-01 사용): OCR 용어 없음 vs 있음, 각 3회. OCR 용어는 해당 샘플 영상의 실제 `extract_slide_terms` 결과 사용.
  - **채택(기본 True)**: recall 평균 상승 AND precision 평균 하락 없음 AND negative 오교정 증가 없음.
  - 그 외: 기능은 남기되 기본 False, 수치를 STATUS.md에 기록.

---

## P-01. 교정 프롬프트 개선 실험

**원칙**: 한 번에 가설 하나씩(ablation). 기준선 = C-01 결정 후 상태. 각 가설 3회 실행. 실험용 프롬프트 변형은 `scripts/c_eval/`에서만 만들고, **채택된 가설만** `correction.py`에 반영.

**가설 (우선순위 순)**
1. **P-a temperature 0**: 흔들림 제거. 평가 반복 수도 줄일 수 있음. (단 0에서 recall 저하 여부 확인)
2. **P-b 필드 순서 reason 먼저**: 스키마 `properties` 순서를 reason → original → correction → confidence. 근거를 먼저 쓰게 해 추정 품질 향상 기대.
3. **P-c 예시(few-shot) 2~3개**: 형식 예시. **평가 샘플에 나오는 용어를 예시로 쓰지 말 것**(누수). 다른 분야 예시 사용(예: 전혀 다른 과목의 오인식 사례).
4. **P-d "교정 안 함" 예시**: 올바른 음차·말버릇을 건드리지 않는 사례 1~2개 명시.
5. **P-e 문맥 겹침**: 청크 앞뒤 1~2 세그먼트를 "참고 문맥(교정 대상 아님)"으로 덧붙임. `validate_proposals`의 source_text는 **본문만**으로 유지(문맥 쪽 제안은 폐기되어야 중복 방지).
6. **P-f OCR 일치 가산(기계 규칙)**: `correction`이 OCR 용어와 정규화 일치하면 신뢰도 한 단계 상향(low→medium). 프롬프트가 아니라 검증 단계 변경. C-01 채택 시에만 실험.

**게이트(가설별)**: precision 평균 하락 없음 AND recall 평균 +1건 이상 (또는 recall 동일 + 오답 감소) AND 소요시간 1.5배 이내. 통과한 가설끼리 결합 후 1회 더 재검증(결합 효과가 개별 합과 다를 수 있음).

**영향 범위**: 채택분만 `correction.py`(build_prompt / RESPONSE_SCHEMA / propose 옵션 / chunk_segments / validate_proposals). 모듈 docstring 실측표 갱신.

**주의**
- 모델은 gemma4:e4b 기준. e2b는 채택 결과로 1회만 확인(회귀 여부).
- `think=False` 유지(켜면 빈 응답 — 실측).
- 평가셋이 단일 강의라 과적합 가능 → STATUS.md에 한계로 명시.

---

## S-01. 프레임 시트(격자 이어붙이기)

**원인/목적**: 채팅 첨부 개수 제한. 낱장 20~300장 → 시트로 1/4.

**방향**
- 캡처·OCR은 지금처럼 **낱장 기준**으로 끝낸 뒤, 시트를 만든다(OCR은 낱장 해상도에서 해야 정확).
- 격자 기본 **2×2**(가로 2, 세로 2). 설정 `video.sheet_cols`, `video.sheet_rows`(각 1~3으로 clamp). `video.sheets_enabled`(기본 True). cols=rows=1이면 시트 없이 낱장 유지와 동일하게 취급(시트 생성 생략).
- 크기: 채팅 업로드 시 긴 변 약 1568px로 축소됨 → **시트 긴 변을 1568px 이하로 직접 만든다**(서버 재축소 방지). 2×2·16:9면 칸 약 780×440.
- 칸마다 **프레임 번호 라벨**(좌상단, 기존 시간 스탬프와 같은 반투명 박스 스타일)을 새로 찍는다. 기존 시간 스탬프(우하단)는 칸 축소 후 글자가 너무 작아질 수 있으므로 **칸 라벨에 "번호 · 시간"을 함께** 넣고, 라벨 글자 크기는 칸 높이 기준으로 정한다(예: 칸 높이의 약 5%, 최소 14px).
- 칸 사이 여백 4~8px(경계 구분), 배경 흰색. 마지막 시트의 빈 칸은 비워둔다.
- 파일명: `sheet_NN_HH-MM-SS~HH-MM-SS.jpg`(첫 칸~마지막 칸 시간). JPEG 품질은 `video.jpeg_quality` 재사용.
- 낱장 원본 비율이 제각각이면 칸 크기는 첫 프레임 비율 기준, 나머지는 비율 유지 맞춤(letterbox).

**해상도 검증(게이트)**
- 대리 지표: 시트의 각 칸을 잘라 OCR → 낱장 OCR 대비 비-UI 줄 글자 일치율(문자 단위 유사도 평균). **2×2에서 0.85 이상이면 기본 2×2 확정.** 미달이면 1×2(세로 2장)로 기본 변경하고 STATUS.md 기록.
- 최종 확인: 샘플 시트 2~3장을 사용자가 실제 채팅에 올려 수식/도식이 읽히는지 확인 요청(Sonnet이 STATUS.md에 "사용자 확인 필요"로 남김).

**영향 범위**: `frames.py`(시트 합성 함수 — Pillow, 신규 의존성 없음), `video_stage.py`, `config.py`(VideoSettings 필드 추가, schema 버전 올리지 않음 — 기본값 fallback), 테스트.

---

## S-02. 낱장 이미지 정리

**방향**
- 폴더 `<stem>.frames/`는 **유지**하고, 안의 **낱장 jpg만 삭제**. 폴더에는 시트들 + `frames.md` + `frames.json`만 남는다 → `frames_dir` 경로 참조(engine/handoff/index/cli/gui)가 그대로 유효해 영향 최소화.
- 설정 `video.keep_single_frames`(기본 False = 삭제). True면 낱장도 남김.
- 순서 고정: 캡처 → OCR(낱장) → 시트 생성 → `frames.md/json` 작성 → **검증** → 낱장 삭제.
- 삭제 전 검증(하나라도 실패하면 낱장 보존 + 경고):
  1. 시트 파일이 기대 개수(ceil(프레임수 / (cols×rows)))만큼 존재하고 각각 PIL로 열림(크기>0).
  2. 시트에 배치된 프레임 번호 목록 합 = 캡처 레코드 번호 목록(누락·중복 없음).
  3. `frames.md`, `frames.json` 작성 완료.
- 삭제 대상은 **이번 실행의 `capture.records` 파일명만**. glob 삭제 금지(사용자 파일 보호).
- 덮어쓰기 정책 `_clean_previous`: 기존 `*.jpg` 패턴이 시트도 포함하므로 동작은 유지되나, 사용자 파일 보호를 위해 `sheet_*.jpg`와 `NNNN_*.jpg` 패턴으로 좁힌다.
- 취소(CancelledError) 시: 삭제 단계 전이면 아무것도 지우지 않음.

**영향 범위**: `video_stage.py`, 테스트(삭제 성공, 검증 실패 시 보존, keep 옵션, 취소).

---

## S-03. 하류 반영

- `frames.md`:
  - 캡처 목록 표에 **시트 열**(`sheet_03 · 오른쪽 위`) 추가. 칸 위치 명칭: 2×2는 왼쪽 위/오른쪽 위/왼쪽 아래/오른쪽 아래, 그 외 격자는 "행-열"(예: 2-1).
  - 머리말에 "이미지는 시트(2×2) 형태, 칸 좌상단 라벨 = 번호·시간" 안내. 낱장 삭제 시 `파일` 열은 제거하거나 "(시트에 포함)"으로 표기 — **파일 열 제거, 시트 열로 대체**로 확정.
- `frames.json`: 프레임별 `sheet`(파일명), `cell`(row, col) 추가, 최상위 `sheets` 목록, `single_frames_kept`(bool). 낱장 삭제 시 `file`은 null.
- `handoff.py`: 업로드 안내를 "시트 이미지 N장 + frames.md"로. 채팅 첨부 개수 안내 문구 갱신.
- `index.py`: 변경 없음(frames_dir 유지). 필요하면 `sheet_count` 선택 필드만.
- CLI: `--sheet-grid 2x2`, `--keep-frames`. `--json`의 `frames`에 `sheet_count`, `sheets` 추가.
- GUI: 영상 입력 섹션에 격자(가로·세로 QSpinBox 1~3), "낱장 이미지도 보관" 체크박스. GUI 테스트는 기존 autouse teardown fixture 유지.
- `cowork/skills/lecture-transcribe/SKILL.md` 규칙 7~11 갱신(시트 읽는 법, 칸 라벨로 frames.md와 대응) → `cowork/install_skill.sh` 재설치. README §4.
- DMG 스펙: 신규 모듈 없으면 변경 불필요(확인만).

---

## 2. 전체 검증

- `pytest -q` 전체 통과(현재 504 기준 + 신규), `mypy --strict src/` 통과.
- 실파일: 무음 샘플(화면 녹화) CLI → 시트 생성·낱장 삭제·frames.md 시트 열 확인. 소리 있는 샘플 → 전사(mlx)+교정(C-01 설정)+시트 끝까지.
- 개발 환경은 `uv sync --extra fuzzy --extra mlx --extra ocr` 유지(plain `uv sync` 금지).

## 3. 기록

- 각 ID 완료마다 STATUS.md에 append: 수치(기준선/실험/게이트 판정), 변경 파일, 남은 이슈.
- 게이트 판정이 애매하거나(3회 결과 편차 큼 등) 문서에 없는 설계 판단이 필요하면 "Opus 확인 필요".
- 사용자 확인 필요 항목: E-01 정답 목록 확정, 시트 실제 채팅 가독성.
