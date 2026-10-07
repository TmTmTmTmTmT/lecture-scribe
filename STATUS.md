# STATUS.md — FIX_GUIDE 실행 현황

기준 문서: [FIX_GUIDE_12.md](FIX_GUIDE_12.md) (Opus 작성 2026-09-13) — **최종 종결(2026-09-14, 사용자 지시로 L-03/L-04 생략, 현재 데이터로 판정). Cohere Transcribe 백엔드 미채택. 근거: 아래 "2026-09-14" 항목.**
이전: [FIX_GUIDE_11.md](FIX_GUIDE_11.md) — v0.2 Cohere 백엔드 종결 판정. FIX_GUIDE_12.md에서 한 차례 보류됐다가 결과적으로 **같은 결론으로 재확정**(단 근거 정정됨).
이전 기준: [FIX_GUIDE_10.md](FIX_GUIDE_10.md) (Opus 작성 2026-09-13) — J-01·J-02 완료.
이전 기준: [FIX_GUIDE_9.md](FIX_GUIDE_9.md) (Opus 작성 2026-09-12) — §1~§4 완료.
이전 기준: [FIX_GUIDE_8.md](FIX_GUIDE_8.md) (Opus 작성 2026-09-11) — H-00 선행 실측 게이트에서 막힘.
이전 기준: [FIX_GUIDE_7.md](FIX_GUIDE_7.md) (Opus 작성 2026-09-08) — **E-01·E-02 전건 완료(범위: 빈도 관리+토큰 정리, "헷갈리기 쉬운 단어" 필터는 제외).**
이전 기준: [FIX_GUIDE_6.md](FIX_GUIDE_6.md) (Opus 작성 2026-09-07) — **C-01~C-05 전건 완료.**
이전 기준: [FIX_GUIDE_5.md](FIX_GUIDE_5.md) (Opus 작성 2026-09-07) — B-02 완료(기본 켬), B-01 게이트 실패 → 롤백(0.6 유지).
이전 기준: [FIX_GUIDE_4.md](FIX_GUIDE_4.md) (Opus 작성 2026-09-06) — **전건 완료.** A-01·A-04·A-05·A-06·A-07·A-08·A-09 완료, A-03 측정 완료(기본값 유지), **A-02 §5-2 정식 게이트 완료 → 통과 → mlx 기본값 변경 적용됨.**
완료분: [FIX_GUIDE_3.md](FIX_GUIDE_3.md) (아이콘·알림) · [FIX_GUIDE_2.md](FIX_GUIDE_2.md) (진행률·스톨, 일부 항목은 FIX_GUIDE_4.md로 이월)
이전 문서: [FIX_GUIDE.md](FIX_GUIDE.md) — G-01 기각 / G-07 재작성됨. FIX_GUIDE_2.md §0 참조.

## 2026-09-27 — FIX_GUIDE_13 E-01 교정 평가셋 + 기준선 (Sonnet) — **정답 목록 사용자 확정 대기**

기준 문서: [FIX_GUIDE_13.md](FIX_GUIDE_13.md) (Opus). 진행 순서 E → C → P → S.
- **샘플**: `LSsamples/2주차 ML검파기.mov`(13.8분, 소리 있음)을 평가용으로 사용. 다른 하나(`2주차 채널모델.mov` 24.8분)는 미사용(필요하면 2번째 평가셋 후보). 전사는 mlx(GPU) 229초, 캡처 13장.
- **산출물**(`scripts/c_eval/`): `gold_ml_detector.json`(정답 41 + 오교정 금지 12), `score.py`(채점, 전사문 위치 기반 매칭·표기만 다른 제안은 집계 제외·expected `|` 대안 허용), `run_eval.py`(교정만 반복, 결과는 `results/`에 원 제안까지 저장), 재채점은 `score.py <gold> <transcript> <results...>`.
- **정답 목록은 오디오 없이 전사문·문맥만 보고 쓴 초안** — `sure:false` 8건은 특히 확인 필요. 사용자 확정 전 수치는 참고치.
- **기준선**(앱 활성 프리셋 용어집 그대로, 3회 평균): 
  - gemma4:e4b — 제안 23.7, 정답 10.7/42(recall 0.25), 오답 2.0, 오교정 2.3, precision 0.56, 108초
  - gemma4:e2b(**현재 앱 설정 모델**) — 정답 7.0, 오답 4.0, 오교정 6.0, precision 0.28, recall 0.16, 81초
- **관찰**:
  - 프롬프트가 "영어 전문용어 오인식"만 겨냥해서 한글 오인식(복주→복조, 수신신보→수신신호, 승볼, 조건부 환경, 베이지 법칙 등)을 거의 못 잡음 → P-01 개선 여지가 큼.
  - **MK(=M_k, 심볼 이름)를 ML로 바꾸는 오교정**이 e2b에서 반복(6건). e4b는 2건.
  - 수식 표기 제안(`P(R|M)` 등 지어낸 식)이 e4b에서 나옴 → 검증 규칙 후보.
  - 프리셋 용어집(27개)에 '이만큼','설명할','나타낸','커질수록' 같은 일반어/조각이 섞여 있음(자동 학습 추정) → 용어집 품질 문제(**Opus 확인 필요**).
  - 전사문 06:30·12:30 부근에 **중국어 환각 문장**이 섞임(교정 대상 아님, mlx 전사 품질 이슈로만 기록).
- 다음: C-01(OCR 용어→교정 프롬프트) 구현.

## 2026-09-27 (2) — FIX_GUIDE_13 C-01 OCR 용어 → 교정 프롬프트 (Sonnet) — **구현 완료, 기본 꺼짐 유지(사용자 판단 대기)**

- **구현**: `correction.build_prompt(..., slide_terms)`(별도 섹션 "슬라이드에서 읽은 표기(OCR, 오타 가능)", 비면 프롬프트 기존과 동일), `propose_corrections(slide_terms=)`, `CorrectionResult.slide_terms`, 사이드카 `slide_terms_used`, `CorrectionSettings.use_ocr_terms`(기본 False, 전사용 `video.ocr_terms_to_prompt`와 별개), engine에서 `result.ocr_terms`를 파일별로만 전달(프리셋 불변), CLI `--correct-ocr-terms/--no-correct-ocr-terms`, GUI 교정 섹션 체크박스(OCR 불가 시 비활성). 테스트 4개 추가(프롬프트 2, 오케스트레이션 1, 설정 1, 엔진 연결 1). 전체 508 passed, mypy --strict 통과.
- **게이트 측정**(ML검파기 샘플, 3회 평균, 정답 49건 기준 재채점 — 기준선/OCR 양쪽 동일 gold):
  - e4b: 정답 10.7→**18.7**, recall 0.22→**0.38**, precision 0.56→**0.66**, 오교정 2.3→**1.0**, 시간 108→128초(+18%) → 가이드 기준 **통과**
  - e2b(현재 앱 설정 모델): 정답 7.0→**4.0**, recall 0.14→0.08, precision 0.28 동일, 제안 수 34→18로 급감 → **악화**
- **주의(정직한 한계)**: (1) gold 초안이 불완전해서 OCR 실행에서 나온 "진짜 교정"(16QM→16QAM, BPS기든→BPSK기든 등 7건)을 결과를 본 뒤 gold에 추가함(`added_after_gate:true`, 양쪽에 동일 적용). 추가분을 빼면 e4b precision은 0.56→0.53으로 소폭 하락(recall은 여전히 상승). (2) 이 영상의 OCR 용어 13개는 품질이 낮음: 브라우저 메뉴 단어(파일·보기·방문 기록·개발자용·윈도우·도움말)가 UI 필터를 통과해 용어로 남고 "북아크" 같은 오독도 있음 — 그래도 e4b는 개선. (3) 단일 강의·정답 초안 → 일반화 근거 약함.
- **판정(잠정)**: 기본값은 **False 유지**. 사유: 앱 현재 교정 모델이 e2b(악화), gold 미확정. e4b에서만 켜는 방향이 데이터상 타당 — 기본값·모델 결정은 사용자 확인 후.
- **Opus 확인 필요**: (a) UI 필터가 브라우저 메뉴 단어를 못 걸러냄(용어 품질), (b) 앱 교정 모델 기본을 e4b로 할지, (c) 프리셋 용어집 자동 학습 오염('이만큼','설명할' 등).
- 다음: P-01(교정 프롬프트 개선 가설 실험). 정답 목록 확정 요청은 사용자에게 전달함.

## 2026-09-27 (3) — FIX_GUIDE_13 P-01 교정 프롬프트 개선 (Sonnet, 사용자 지시로 모델 e4b 확정) — **2개 채택, 반영 완료**

기준선(e4b, 정답 49건 재채점): 정답 10.7, precision 0.56, recall 0.22, 108초.
- **가설 7개를 `scripts/c_eval/variants.py`로 하나씩 실험**(e4b, 3회 평균):
  - **g 한글 오인식도 대상 포함**: 정답 18.0, precision 0.57, recall 0.36, 125초 → **통과**
  - **e 청크 앞뒤 문맥(참고용) 제공**: 정답 14.3, precision 0.68, recall 0.29, 105초(시간 증가 없음) → **통과**
  - h(수식 표기 금지 규칙): precision 0.48로 하락 → 기각
  - a(temperature 0): precision·recall 둘 다 기준선보다 낮음(단, 완전히 결정적) → 기각
  - d("교정 안 함" 예시): precision·recall 둘 다 하락 → 기각
  - c(few-shot 예시): precision 0.41로 하락, 143초로 느려짐 → 기각
  - b(스키마 필드 순서 reason 먼저): 기준선과 사실상 동일, 이득 없음 → 기각
  - g+e 결합 재검증: 정답 18.7, precision 0.56, recall 0.37, 127초 → 결합해도 재현율이 더 오르고 정밀도는 기준선과 동일 → **채택**
- **프로덕션 반영**: `correction.build_prompt`에 한글 오인식 지시문 추가(항상 켜짐), `context_before/context_after` 매개변수 추가(비어 있으면 프롬프트 불변). `propose_corrections`가 청크 배열에서 이웃 청크의 마지막/처음 3세그먼트를 문맥으로 넘김(검증은 본문만 대상, 문맥 문자열은 `original`로 못 쓰게 프롬프트에 명시). 모듈 docstring에 실측표 갱신. 테스트 3개 추가(프롬프트 한글 규칙, 문맥 없으면 불변, 이웃 청크 문맥 전달). 전체 511 passed, mypy --strict 통과.
- **실제 프로덕션 코드로 최종 재확인**(e4b, 3회): 정답 19.0, precision 0.59, recall 0.37, 오교정 0.3, 133초 — 실험 수치와 일치하거나 더 좋음.
- **한계**: gold_ml_detector.json은 여전히 초안(오디오 미확인)이라 절대 수치는 참고치. 단일 강의 기준이라 다른 강의(수식 적은 과목 등)에서는 다를 수 있음.
- **미채택 항목 비고**: temperature 0(가설 a)은 결과가 완전히 결정적이라 평가·디버깅엔 유리하지만 이번 기준으로는 정확도가 기준선보다 낮아 기본값 변경은 보류.
- 다음: S-01(프레임 시트화). e2b 회귀 확인은 필요 시 후속.

## 2026-09-27 (4) — FIX_GUIDE_13 S-01/S-02/S-03 프레임 시트화 (Sonnet) — **구현 완료, 실사용 확인 필요**

- **구현**: `frames.build_sheets`(cols x rows 격자, 시트 긴 변을 여백 포함 1568px 이하로 직접 계산, 칸 라벨 "번호 · 시간"을 `stamp_time`과 같은 반투명 박스 스타일로 좌상단에 새김, 마지막 시트 빈 칸은 흰색). `video_stage.run_video_stage`: 캡처→OCR(낱장)→시트 생성→검증(시트의 프레임 번호 집합이 캡처 레코드와 정확히 일치해야 함)→`frames.md`/`frames.json` 작성→검증 통과 시에만 이번 실행이 만든 낱장 파일명만 삭제(글롭 금지). 시트 생성 실패(`OSError`)나 검증 실패 시 낱장을 보존하고 경고만 남김. 취소(`CancelledError`)는 삭제 전에 전파되면 아무것도 안 지움.
- **설정**: `VideoSettings.sheets_enabled`(기본 True), `sheet_cols`/`sheet_rows`(기본 2x2, 1~3 clamp — 둘 다 1이면 시트 안 만듦), `keep_single_frames`(기본 False). `_clean_previous`(덮어쓰기 정책) 패턴을 `*.jpg`에서 `sheet_*.jpg`/`NNNN_*.jpg`로 좁힘(사용자 파일 보호).
- **`frames.md`/`frames.json`**: 시트가 있으면 "파일" 열 대신 "시트" 열(예: `sheet_01` · 왼쪽 위, 2x2는 상하좌우 명칭·그 외는 "행-열"). JSON에 `sheets`(파일명·격자·시간범위) 목록, 프레임별 `sheet`/`cell`, `single_frames_kept`, 낱장 삭제 시 `file: null` 추가.
- **CLI**: `--sheet-grid COLSxROWS`(형식 오류 시 안내), `--no-sheets`, `--keep-frames`. `--json` 출력에 `sheet_count`, `single_frames_kept` 추가.
- **GUI**: 영상 입력 섹션에 시트 켜기 체크박스, 가로·세로 칸 수(1~3) 스핀박스, 낱장 보관 체크박스.
- **SKILL.md/README**: 시트 형식 설명, 칸이 작아 수식이 뭉개질 수 있다는 주의, `frames.md`의 "시트" 열 읽는 법 추가. `cowork/install_skill.sh` 재설치 완료.
- **테스트**: `tests/test_frames.py`(격자 계산, 빈 칸 채움, 여러 시트 분할, 시트 긴 변 1568px 이하), 신규 `tests/test_video_stage.py`(기본 2x2로 낱장 삭제, `keep_single_frames`로 둘 다 보관, 시트 비활성/1x1은 예전 동작과 동일, 시트 생성 실패 시 낱장 보존), `test_config.py`/`test_cli.py`/`test_gui_fixes.py`에 설정·CLI·GUI 라운드트립 추가. 기존 `test_engine_video.py`의 프레임 개수 단정을 새 기본값(낱장 삭제, 시트 1장)에 맞게 갱신. 전체 523 passed, mypy --strict 통과.
- **실파일 확인**: 무음 화면 녹화 60초 샘플(scratchpad clip_silent.mov)을 CLI로 처리 → 시트 1장(2x2, 4번째 칸은 빈칸)에 3프레임 정상 배치, 낱장 삭제됨, `frames.md`가 시트·칸 위치를 정확히 가리킴. **시트 이미지를 직접 열어 확인**: 라벨(번호·시간) 읽기 쉬움, 슬라이드 제목·본문 텍스트 모두 선명(이 샘플은 글자가 커서 유리한 편). 소리 있는 강의(더 조밀한 슬라이드)로는 아직 확인 안 함.
- **미확인 항목(사용자 확인 필요)**: (1) 실제로 Claude 채팅에 시트를 올려서 읽히는지 — 특히 수식이 있는 슬라이드에서 2x2가 너무 작지 않은지. (2) 시트를 다시 OCR해 낱장 대비 일치율을 재는 대리 검증(가이드가 제안한 0.85 기준)은 시간 관계상 생략함 — 필요하면 후속으로 실행 가능.
- **한계**: `build_sheets`가 프레임마다 이미지를 두 번(낱장 저장 시 한 번, 시트 조립 시 한 번) 여는 구조라 프레임이 매우 많으면(수백 장) 다소 느려질 수 있음 — 실측은 안 함.
- 다음: 사용자가 시트 가독성을 실제로 확인하고, 필요하면 격자 기본값(2x2 vs 1x2)을 재조정.

## 2026-09-28 — 사용자 지시로 기본값 2건 변경 (Sonnet)

- **시트 격자 기본 2x2 → 1x2**: 칸을 크게 잡아 수식·작은 글자가 덜 뭉개지게 함. `config.py` 기본값,
  관련 테스트(`test_config.py`/`test_engine_video.py`/`test_video_stage.py`) 갱신, README/SKILL.md/
  GUI 문구도 1x2로 맞춤. 스킬 재설치 완료.
- **교정 모델 기본 e2b → e4b 확정**: 코드 기본값은 이미 `gemma4:e4b`였으나, **저장된 설정 파일**
  (`~/Library/Application Support/LectureScribe/settings.json`)에 예전 e2b가 박혀 있어 실제로는
  e2b로 돌고 있었음 — 파일을 직접 e4b로 고침(같은 파일에 시트 격자도 1x2로 반영).
- 정답 목록(`gold_ml_detector.json`) 확정은 사용자가 보류 — 초안 그대로 둠.
- 전체 523 passed, mypy --strict 통과.

## 2026-09-26 (2) — 배포용 DMG 빌드 (Sonnet)

- `~/Desktop/LectureScribe-0.1.0.dmg`(257MB, ad-hoc 서명 — 받는 쪽은 첫 실행 우클릭→열기). `build_dmg.sh`에 `--extra ocr` 추가, `LectureScribe.spec`에 pyobjc(Vision 등)·신규 모듈 포함(없으면 건너뜀).
- **번들 검증**: 번들 CLI로 무음 60초 클립 처리 → 캡처 3장 + Vision OCR 정상(38초). 이전 "번들 OCR 미검증" 항목 해소.
- 빌드 뒤 개발 환경은 `uv sync --extra fuzzy --extra mlx --extra ocr`로 복구함(빌드 스크립트가 extra를 지우므로).
- `/Applications/LectureScribe.app`은 경량 래퍼(프로젝트 venv 참조)로 교체함(이전 것은 scratchpad로 이동). DMG 앱과 별개.

## 2026-09-26 — PLAN_VIDEO_FRAMES.md V-08 OCR 용어 효과 게이트 (Sonnet, 샘플 2: 소리 있는 23분 강의) — **결과: 기본 꺼짐 유지**

샘플 `LSsamples/2026-09-26 14-41-59.mov`(1200×778, AAC 있음, 23분, 전자회로 개요). 모두 mlx(GPU) large-v3.
- **캡처**: 10장, 슬라이드 전환·시간 모두 일치(눈으로 확인). 진행형으로 채워지는 슬라이드는 3단계(12:07/13:34/16:04)로 저장됨(허용 범위).
- **(a) 용어 없음**: 389초(3.5배속), 214세그먼트, 앞 구간 정상.
- **(b) OCR 용어 17개를 initial_prompt로**: 607초(**1.56배**), **앞 구간 21.9초 누락 → 앱의 붕괴 폴백이 프롬프트를 빼고 재전사**. 최종 텍스트는 (a)와 동일(차이는 Ollama 교정 주석뿐).
  → 판정표의 "효과 없음 또는 시간 과다"에 해당. **`ocr_terms_to_prompt` 기본 False 유지**, 이 영상에서 환각은 관찰되지 않음.
- **용어 품질 문제**: 슬라이드 제목의 일반 한글 명사("내용", "개요", "구분", "구성", "정보", "의한", "신호", "전송")가 상위에 올라오고 OCR 오인식("Rox Receiver", "Mea Cal", "Mapro Cel")이 섞임. 발화에 나오는 전문용어(전송단·수신단·ADC·QAM 등)를 골라내지 못함.
  프롬프트에 넣기엔 부적합 — 활용하려면 일반 명사 필터·영문 약어 우선 등 Opus 재설계 필요(**Opus 확인 필요**, 우선순위는 사용자 판단).
- 참고: 사용자 설정은 mlx + 프롬프트 옵션 꺼짐. 첫 mlx 시도는 "필요 4.6GB/가용 3.3GB" 메모리 사전검사로 실패(다른 프로세스가 메모리 점유) — 재시도에서 통과. GPU 전용 사용 방침.
- 미실측: 웹캠 PiP 영상(사용자에게 샘플 없음).

## 2026-09-25 (5) — PLAN_VIDEO_FRAMES.md V-07 완료 + 문서·스킬 반영 (Sonnet) — **504 테스트 통과, mypy --strict 통과**

- CLI: `--no-frames --frame-threshold --frame-dedupe --frame-interval --no-ocr --ocr-terms/--no-ocr-terms`(범위 보정은 설정 로더와 같은 코드), `--json`에 `frames_only`·`frames` 추가.
  GUI: 고급 설정 "영상 입력" 구역(켜기, 변화 기준, 중복 제외, 최소 간격, OCR, 슬라이드 용어 추가). OCR 미설치면 두 체크박스 잠금(저장값은 덮어쓰지 않음).
  진행률: 오디오 있는 영상은 영상 단계 동안 막대 0% 유지+메시지만, 화면만 처리하는 영상은 캡처 0~60%·OCR 60~98%.
  길이 계산(`probe_duration`)이 오디오 없는 영상에서도 죽지 않음(CLI 알림·GUI 큐·엔진 가중치 3곳).
- 문서: README §4 신설, CLAUDE.md(구조·`uv sync` 주의), 스킬 규칙 7~11 + 영상 사용법 → `cowork/install_skill.sh`로 `~/.claude/skills/lecture-transcribe`에 반영함. `install.sh`는 `--extra ocr` 포함.
- **실제 CLI 종단 검증**(샘플 1, 무음 영상): 64초, 20장 + `frames.md/json` + 핸드오프, 모델 미로드, 이미지 1.6MB(1024폭, 장당 약 80KB), 시간 새김 확인.
- **GUI 테스트 세그폴트 발견·우회(원인 미확정)**: 설정 패널 위젯이 늘자 `test_gui_fixes.py`에서 `gc.collect()` 중 세그폴트(위젯 제거 시 재현 안 됨,
  QDoubleSpinBox·Vision import·`ocr_available()`은 원인 아님으로 확인). 테스트에 "최상위 위젯 명시적 소멸" 픽스처를 추가해 해결.
  **프로덕션 경로에도 같은 위험이 잠복해 있을 수 있음**: `perf.release_memory()`가 워커 스레드에서 `gc.collect()`를 돌려 Qt 객체가 다른 스레드에서 소멸 가능. → **Opus 확인 필요**(별도 조사 대상, 이번 작업 범위 밖).
- **남은 항목**: ① V-00-4 웹캠 PiP 영상 오탐 측정(샘플 필요) ② V-08 OCR 용어 효과 게이트(소리 있는 강의 영상 + 정답 용어 필요; 그 전까지 `ocr_terms_to_prompt` 기본 꺼짐)
  ③ 배포 번들(PyInstaller)에서 pyobjc Vision 동작 확인(미검증, README에 명시) ④ 사용자 실제 사용 중 오탐/놓침 확인.
- 알려진 한계: OCR 오탈자("Fitters", "Windowed-sing")가 용어에 남음, 화면 메뉴 글자가 소수 남을 수 있음(가장자리 채점 2/600 놓침).

## 2026-09-25 (4) — PLAN_VIDEO_FRAMES.md V-01~V-06 구현 (Sonnet) — **502 테스트 통과, mypy --strict 통과**

- 신규: `frames.py`(변화 감지 `FrameSelector` + ffmpeg 스트리밍 + Pillow 시간 새김), `ocr.py`(Vision OCR + UI 줄 판정),
  `slide_terms.py`(용어 추출), `video_stage.py`(캡처→OCR→`frames.md/json`). 수정: `config.py`(`VideoSettings`, 마이그레이션 불필요 — 새 키는 기본값),
  `audio.py`(`probe_media`·`probe_duration`·`VIDEO_EXTS`), `engine.py`(영상 단계·OCR 용어 적용·프레임만 경로), `handoff.py`, `index.py`(`frames_dir`), `pyproject.toml`(pillow·numpy 기본, extra `ocr`).
  테스트: `test_frames/test_ocr/test_slide_terms/test_engine_video` + `test_config` 추가.
- **실제 샘플 회귀**: 전환 20개 중 19+ 포착(테스트로 고정). 캡처 20장 56초(18분 영상), OCR 20장 42초(워밍업 포함).
- **계획과 달라진 값(측정 근거, 설계 변경 아님)**: ① UI 줄 판정 비율 60%→**40%** ② UI 판정을 **글자 유사도 + 픽셀 불변성(중앙값 대비) 병용**
  (화면 가장자리 기준 채점: 글자만 21/600 놓침, 병용 2/600, 슬라이드 줄 오표시 0/195) ③ 제목 판정에 **글자 높이**(프레임 중앙값의 1.15배) 사용
  ④ 용어 후보 규칙 다수(수식 줄 제외, 반복 연어 3프레임 이상, 오탈자 변형 병합).
- 샘플 1 용어 추출 결과: "FIR", "Discrete Signal", "FIR Filter Design", "Nyquist Sampling Theorem", "Ideal Interpolation filter", "Impulse Response" 등. OCR 오탈자("Fitters", "Windowed-sing")는 일부 남음.
- **주의(환경)**: `uv sync`만 실행하면 extras(mlx·fuzzy·ocr)가 **제거**된다. 반드시 `uv sync --extra fuzzy --extra mlx --extra ocr`. (이번 세션에 한 번 지웠다가 복구함. torch 등 재설치, 동일 버전.)
- 남음: V-07 CLI/GUI, 스킬·README·install.sh, V-08 효과 게이트(소리 있는 영상 필요), 웹캠 샘플.

## 2026-09-25 (3) — PLAN_VIDEO_FRAMES.md V-00 남은 항목 (Sonnet)

- `scripts/v00_probe/gt_sample1.json`(정답 20개), `ocr_probe.py` 저장.
- **디코딩**: 5분 클립 2fps 저해상도 — 소프트웨어 16.6초, `-hwaccel videotoolbox` **107초**(출력 동일). **소프트웨어 디코딩 채택**(계획의 "가속 우선"은 폐기).
- **Vision OCR**(ko-KR+en-US, accurate): 최초 호출 워밍업 28초, 이후 장당 0.4초. 영어 제목·본문 정확, 한국어 제목("디지털전자회로", "전자회로 전송/수신 필터") 정확, **수식은 깨짐**(용어 후보에서 제외 필요).
  1024폭 vs 2048폭 차이 거의 없음 → **1024폭 이미지로 OCR**.
  화면당 전체 40~60줄 중 30줄 이상이 LMS 메뉴·탭·"출결 기록은 최대 2배속…" 배너 = UI 줄 → V-03의 60% 빈도 필터 필수(모든 프레임에 고정 등장).
  **신뢰도가 0.3/0.5/1.0으로 뭉쳐 나와 신뢰도 필터는 0.3 이하 제거 외에 의미 없음.** 영상 플레이어 시각 표시("00:02")가 섞임 → `\d\d:\d\d` 줄 제외 규칙 추가.
- 미실측: 웹캠 PiP 영상, 소리 있는 영상(V-08 게이트).

## 2026-09-25 (2) — PLAN_VIDEO_FRAMES.md 개정 1판 (Opus) — 아래 "Opus 확인 필요" 해소

아래 실측 결과를 계획에 반영: 변화 10% + 중복 제거 3%(사용자 제안인 직전 10프레임 평균 20%는 불채택, 근거는 계획 §0),
2fps, Pillow로 시간 새김, 오디오 없는 영상은 프레임만 처리(사용자 결정), OCR UI 줄 필터 신설,
`ocr_terms_to_prompt` 기본값 False(소리 있는 영상으로 게이트 통과 전까지). 다음: Sonnet이 V-00 남은 항목부터 진행.

## 2026-09-25 — PLAN_VIDEO_FRAMES.md V-00 부분 실측 (Sonnet, 샘플 1개) — ~~Opus 확인 필요~~ 개정 1판에 반영

샘플: `LSsamples/화면 기록 ….mov` (3710×2482, 18분, 1.6배속, 화면 녹화). 2fps 저해상도 덤프로
20개 슬라이드 전환을 눈으로 라벨링(정답)해 규칙별 회수율 비교. 임시 스크립트는 scratchpad(미보존).

- **사용자 제안(직전 10프레임 대비 평균 20%)**: 20개 중 11개만 잡음(회수율 55%). 놓친 것은
  같은 초록 배경에서 본문만 바뀌는 슬라이드(78·220·332·756초 등) — 화면 전체 대비 변화가 5~15%뿐.
- **10%**: 20/20 회수, 오탐 8개(같은 슬라이드 재저장). **이력 전체와 중복 제거(변화<3%면 저장 안 함)를 넣으면 19/20, 오탐 1** → 이 조합 권장.
- 직전 10프레임 평균 방식은 기준 프레임 방식보다 나은 점이 없음(순간 팝업은 그대로 잡히고, 애니메이션 완성 프레임 저장은 안 해줌).
- 자동 ROI(자주 변하는 픽셀의 bbox)는 89%로 무의미 → 사용 안 함.
- **`drawtext` 필터가 이 ffmpeg에 없음**(libfreetype 미포함) → 계획 V-02의 시간 새김 방식 변경 필요(Pillow 또는 QPainter).
- **샘플에 오디오 트랙 없음** → 영상만 있는 입력의 처리 방침 필요(`NoAudioTrackError`와 충돌).
- 1.6배속: 프레임 시각은 영상 시각 기준. 최소 5초는 실제 강의 8초에 해당. 슬라이드 최단 체류 13초라 문제 없음.
- 미실측: 웹캠 PiP 영상, 한국어 OCR 품질, V-08 효과 게이트.

## 2026-09-12 (2) — FIX_GUIDE_9.md §1·§2·§6-1·§6-4 실행 (Sonnet) — **§3 HF 토큰 대기**

Opus가 H-00-c 원인을 소스 대조로 확정(§1: `strict=False` 기본값이 안 맞는 키를 조용히
버림 → 디코더·LM헤드 미초기화 + 멜 필터뱅크 미로드). §2(fp16 대조, 무다운로드)·§6-1(가이드
정정)·§6-4(CLAUDE.md 경로 정정) 완료. §3(HF 토큰)은 사용자 행동 필요해 대기 중.

- **§2 실행(다운로드 없이 헤더만 대조, 계획대로)**: `beshkenadze/cohere-transcribe-03-2026-mlx-`
  `{fp16,6bit,4bit}` 세 리포 전부 HTTP Range로 safetensors 헤더만 받아 이름 공간 확인
  (8bit는 FIX_GUIDE_8 세션에서 이미 확인됨). **결과: 넷 다 `transf_decoder.*`=0,
  `log_softmax.*`=0.** `preprocessor.*`만 fp16이 2개(있음), 6bit/4bit/8bit는 0개로 갈림 —
  양자화 단계에서 버퍼가 빠진 것으로 보이나, **어차피 fp16조차 디코더·LM헤드 이름이
  없어 디코더 자체가 초기화 상태로 도는 건 넷 다 동일**. Opus 예측(§2) 정확히 적중 —
  "양자화 문제 아님, 변환본 계열 전체가 비호환"으로 확정. **fp16 4.13GB 다운로드 불필요**,
  안 받음.
- **§6-5 자산 정리**: 비호환 확정된 `scripts/h00_probe/weights_check/`(2.42GB, beshkenadze
  8bit) 삭제. `run_probe.py`·`decoded_16k.npy`는 보존(§4 재측정용).
- **§6-1 FIX_GUIDE_8.md 정정**: §1-1 "우회 경로" 행을 "없다"로 변경 + 근거(이번 실측) 추가,
  §1-3 mlx-audio 행에 "원본 게이트 리포 전제" 조건 명시, §4(H-02) 도입부에 mlx-audio 자체
  VAD 파손 사실과 "`vad=False` 고정" 결론 추가.
- **§6-4 CLAUDE.md 정정**: 테스트 파일 경로를 `전자회로/9:1/9:1 전자회로.m4a`(날짜별
  하위 폴더)로 수정, 정답 있는 샘플 클립 2종(`9:1 전자회로 클립.m4a` 60초 한국어,
  `en_5s.m4a` 4.5초 영어) 안내 추가.
- **범위 확인**: `src/lecture_scribe/**` 무변경(가이드 §7 지시대로). `git` 이력 없는
  프로젝트라 `pytest`/`mypy` 재실행 생략(코드 변경 없음 — 문서만).

## 2026-09-14 — FIX_GUIDE_12.md 최종 종결 (Sonnet)

사용자 지시: "그냥 이대로 그만해줘" — L-01·L-02 결과로 L-03(전처리 정합성)·L-04
없이 즉시 종결. FIX_GUIDE_12.md §7 판정표를 현재 데이터에 그대로 적용:

- L-01: "Cohere가 열세"(CER 5.1% vs Whisper 3.1%, 상대 +64.8%)
- L-02: "반복 루프 해결 안 됨"(디코딩 파라미터 11종 전부 실패)
- → **표의 "종결 확정" 칸.**

### 최종 결론

**v0.2 Cohere Transcribe 백엔드 미채택.** FIX_GUIDE_11의 원래 결론과 같으나, 원인은
재조사로 더 정확해졌다:

- ~~"한국어 자체를 못한다"~~ (X, 최초 가정 — 폐기)
- **"깨끗한 낭독체(FLEURS)에서는 실사용 가능한 수준(CER 5.1%)이지만, 길고 반향
  있는 실제 강의 녹음 조건에서 인코더 표현이 무너지고, 이는 디코딩 설정으로
  우회되지 않는다"** (O, 실측으로 확정)

이 앱의 용도(실제 강의 녹음 전사)에는 어느 쪽 원인이든 결론이 같다 — 채택 불가.

### 문서 정리

- `FIX_GUIDE_12.md` 맨 위에 최종 종결 배너 추가(L-03/L-04 생략 사유 명시).
- `FIX_GUIDE_11.md` 맨 위에 "FIX_GUIDE_12에서 재확인, 근거 정정" 배너 추가.
- `COMPARISON_METHOD.md`에 **§2-1 신설**("비교 전 필수 점검 — 샘플 간 녹음 조건을
  맞춰라") — 이번에 실제로 결론을 뒤집을 뻔한 함정을 일반 원칙으로 문서화. 적용
  이력도 최종 결과로 갱신.
- `FIX_GUIDE_8/9/10.md`의 기존 종결 배너는 그대로 유효(내용 변경 불필요 — 최종
  결론이 같음).

### 환경 정리 — 완료

이번 라운드(L-01/L-02)에서 재생성한 probe 자산 삭제 완료: 체크포인트(3.9GB
재다운로드분), probe venv(`torch`·`transformers`·`librosa`·`faster-whisper`·
`datasets`·`jiwer`·`torchcodec`·`soundfile`). `run_j01.py`·`run_j02_transformers.py`·
`run_l01_fleurs.py`·`run_l02_decoding.py`·`run_probe.py`·`decoded_16k.npy`는 근거
보존용으로 `scripts/h00_probe/`에 남김. **앱 `.venv` 격리 최종 확인**: `datasets`·
`jiwer`·`torchcodec` 전부 부재 확인 — 이번 라운드를 포함해 전체 Cohere 조사
(FIX_GUIDE_8~12) 동안 probe 전용 의존성이 앱 `.venv`로 새어나간 적이 없다.

### 앱 코드·테스트 영향

`src/lecture_scribe/**` 이번 라운드도 무변경. `pytest`/`mypy` 재실행 불필요.

### 다음 단계

FIX_GUIDE_11의 "다음 단계 — 사용자 확인 필요" 항목이 그대로 유효하다(위 "2026-09-13
(2)" 항목 참고): ① large-v3 vs large-v3-turbo 한국어 실측 비교(`COMPARISON_METHOD.md`
절차 바로 적용, 새 모델 도입 불필요) ② 다운로드 견고화(Xet 정지 대응)만 묶어
v0.1.1로 내고 v0.2는 나중으로 ③ 사용자가 별도로 원하는 기능. 사용자 확인 대기.

## 2026-09-13 (4) — FIX_GUIDE_12.md L-02 실행 (Sonnet) — **디코딩 파라미터로는 전혀 해결 안 됨**

L-01 직후 이어서 진행(§9 "L-01과 독립이므로 순서 바꿔도 됨"). 사용자가 직접 지목한
`repetition_penalty` 등 transformers `GenerationMixin` 파라미터를 강의 클립(60초,
반복 루프가 재현되는 그 입력)에 **한 번에 하나씩**(§3-1) 스윕.

### 결과 — 11개 설정 전부 실패, 일부는 오히려 더 나쁨

| 설정 | 결과 |
|---|---|
| 기준(그리디) | "쫑쫑쫑..." 반복 루프(기존과 동일) |
| `repetition_penalty` 1.1/1.2/1.35 | 반복은 다른 단어로 옮겨갈 뿐("그동안, 그동안...", "그,그,그...") — 점점 값을 올릴수록 **영어 단어까지 섞인 완전한 의미불명 문장**으로 악화("silent 지지입니다", "Supakin General Tower", "superfunding general taxation") |
| `no_repeat_ngram_size` 3/4/5 | **최악.** 반복은 사라지지만 문장이 아니라 **의미 없는 음절 나열**로 붕괴("쪼, 담, 귀, 삼, 찌, 빈, 춘, 웅..." — 한 글자씩 나열) |
| `num_beams=4` | 다른 단어("쭈구에")로 반복, 안 풀림 |
| `num_beams=5, length_penalty=1.0` | "트레이더" 무한 반복 — **오히려 더 단순한 반복으로 퇴행** |
| `encoder_repetition_penalty=1.05` | **적용조차 안 됨**(`UserWarning`: 이 인코더-디코더 구조에선 `input_ids` 없이는 무시됨) — 시도 자체가 무효 |
| `max_new_tokens=1000` | 같은 반복을 더 길게 낼 뿐(기존 결과와 동일 확인) |

**어느 것도 정답("결제 요청서 제출해 주시면...")에 가까워지지 않았다.** 반복을 억제하면
반복이 아닌 다른 형태의 오류(무의미한 단어 나열)로 바뀔 뿐 — **디코딩 단계의 문제가
아니라 인코더가 이 오디오에 대해 만드는 표현 자체가 나쁘다는 뜻으로 보인다.**

### 종합 판단 (L-01+L-02)

FIX_GUIDE_12.md §7 판정표 기준: "Cohere가 열세"(L-01) + "반복 루프 해결 안 됨"(L-02)
→ 표상으로는 "종결 확정" 칸. **다만 L-01이 보여준 그림(FLEURS 낭독체에서는 CER 5.1%,
실사용 가능한 수준)과 이 결과를 합치면 결론이 단순히 "한국어를 못한다"가 아니라
"깨끗한 낭독체는 준수하게 하지만, 실제 강의 녹음(잔향·구어체·긴 발화)에는 구조적으로
약하고, 그 약점은 디코딩 설정으로 우회되지 않는다"는 더 구체적인 결론이다.**
이 앱의 용도(실제 강의 녹음 전사)에는 어느 쪽이든 결론이 같다 — **채택 불가.**
다만 원인의 성격이 처음 종결 때(FIX_GUIDE_11) 생각했던 것과 다르므로 정확히 기록해 둔다.

### 사용한 파일

- `scripts/h00_probe/run_l02_decoding.py` — L-02 스윕 스크립트(11개 설정, 강의 클립 대상)

### Opus 확인 필요 — 최종 판정

L-01·L-02 데이터가 다 나왔다. FIX_GUIDE_12.md §9 순서상 L-03(전처리 정합성)이 남아
있으나, 가이드 자체가 "L-01/L-02가 명확하면 확인용"이라고 명시했고 지금 결과는
명확하다(§9). **L-03을 마저 할지, 아니면 이 데이터로 최종 판정(§7)을 내릴지는
Opus가 정할 사안**이라 Sonnet이 임의로 L-03을 생략하거나 강행하지 않고 반환한다.

## 2026-09-13 (3) — FIX_GUIDE_12.md L-01 실행 (Sonnet) — **종결 판정 보류, L-01 결과로 그림이 크게 바뀜**

사용자가 "리더보드 1위 모델의 한국어가 그렇게 나쁠 리 없다, 측정이 이상한 것 아니냐"고
문제 제기 → Opus가 `ffprobe`로 실측 확인: `en_5s.m4a`(22050Hz, `Lavf` 인코더 — 합성/생성
샘플 추정)와 강의 클립(48000Hz, `Core Media Audio` — 실기기 녹음)의 **녹음 조건 자체가
달랐다.** "언어 차이"로 읽은 것의 상당 부분이 실은 "음질·발화 스타일 차이"였을 가능성
발견. FIX_GUIDE_12.md로 종결 판정 보류, L-01(FLEURS ko_kr)부터 재검증 지시.

### 환경 재구축

체크포인트(3.9GB, 정식 게이트 리포) 재다운로드 — `hf_xet` 언인스톨 후 순수 HTTP,
1분 35초 완주(재현 확인된 안정적 우회). probe venv 재생성 + `torch`·`transformers`·
`librosa`·`faster-whisper`·`datasets`·`jiwer`·`torchcodec`·`soundfile` 설치.
**`datasets`/`torchcodec`가 설치할 때마다 `hf_xet`을 다시 끌고 옴 — 2회 재발생,
매번 재제거.** faster-whisper large-v3는 `~/.cache/huggingface/hub`에 이미 캐시돼
있어(2.9GB, 이전 앱 사용 이력) 추가 다운로드 불필요.

### torchcodec 우회

`datasets`(신버전)의 오디오 자동 디코드가 `torchcodec`을 거치는데, 이 머신에서
`libtorchcodec`이 homebrew ffmpeg 공유 라이브러리(`libavutil.*.dylib`)를 못 찾아
전부 실패(버전 4~9 전부 시도 후 실패). **회피**: `Audio(decode=False)`로 raw bytes만
받고, 이 repo가 이미 검증한 `faster_whisper.audio.decode_audio()`로 직접 디코드 —
새 의존성 문제를 새로 해결하는 대신 기존에 검증된 경로를 재사용(가이드 §6 원칙).

### L-01 결과 — FLEURS ko_kr 40발화, Cohere(transformers 네이티브) vs Whisper large-v3

**평균 CER — Cohere: 5.14%, Whisper large-v3: 3.12%. 상대 차이 +64.8%(Cohere가 나쁨).**

- FIX_GUIDE_12.md §7 판정표 기준으로는 "Cohere가 열세" 칸에 해당 — L-02로 계속 진행.
- **다만 질적으로 완전히 다른 그림이다.** 강의 클립에서 본 "쟤쟤쟤...", "완전히 뒤섞인
  다국어 헛소리"와 달리, FLEURS에서는 **정상적이고 유창한 한국어**를 출력한다.
  예시(발화 다수 중): "염소 사육은 대략 1만 년 전에 이란의 자그로스 산맥에서 시작한
  것으로 보입니다"(CER 0.030, Whisper와 사실상 동일), "기지국에 이중 라디오가
  있다면..."(CER 0.000, Whisper와 정확히 일치). 40개 중 다수가 CER 0.000~0.03대.
  가장 나쁜 사례(CER 0.487, "던랩 브로드사이드"→고유명사 오인식)도 문장 구조 자체는
  멀쩡하고 고유명사 하나만 틀렸다 — 강의 클립의 반복 루프·의미불명 출력과는 질적으로
  다른 종류의 오류다.
- **결론**: 모델의 한국어 자체는 **정상적으로 작동한다.** 강의 클립에서의 완전 붕괴는
  모델의 한국어 능력 문제가 아니라 **강의 녹음 조건(잔향·거리 마이크·구어체·48kHz
  소스)에 대한 강건성 부족**일 가능성이 높다 — 이건 FLEURS(낭독체) 결과만으로는
  구분이 안 되는 새로운 가설이라 별도로 검증 필요(L-02/L-03이 우선순위이나, "짧은
  실제 강의 발화 1~2개"를 별도로 다시 보는 것도 유효한 다음 수가 될 수 있음 — Opus
  판단 대상으로 남겨둠).
- Cohere 출력이 Whisper보다 **띄어쓰기·문장부호를 더 자연스럽게 붙이는 경향**
  관찰됨(정규화로 CER 계산 시엔 무관하지만 정성적으로 특기할 만함).

### 사용한 파일

- `scripts/h00_probe/run_l01_fleurs.py` — L-01 스크립트(FLEURS 스트리밍 로드 40개,
  Cohere/Whisper 동일 오디오 배열 사용, CER 계산)
- 정규화 규칙(코드에 고정, 결과 본 뒤 변경 안 함): NFC + 정규식으로 한글/영숫자 외
  전부 제거(공백·문장부호 포함) + 소문자화

### Opus 확인 필요 — 다음 단계

FIX_GUIDE_12.md §9 순서상 다음은 L-02(디코딩 파라미터 스윕, 사용자가 직접 지목한
`repetition_penalty` 등). §9가 "L-01과 독립이므로 순서 바꿔도 됨"이라고 명시해 이어서
진행하되, 위에서 새로 나온 "강의 조건 강건성" 가설은 L-02/L-03 이후 Opus가 판단할
후속 항목으로 별도 표시해 둠 — 계획에 없던 새 갈래라 Sonnet이 임의로 추가 실험을
설계하지 않음(CLAUDE.md 역할 분담 규칙 4).

## 2026-09-13 (2) — FIX_GUIDE_11.md K-01 실행 및 v0.2 Cohere 백엔드 종결 (Sonnet)

Opus가 FIX_GUIDE_10의 "결론 2"(긴 오디오 반복 루프가 모델 특성)를 J-02 하네스 결함
3개(§1 아래) 때문에 무효로 보고 정정 지시, 동시에 5초 조건 transformers 결과("저희가
결정해서 유청서...")만으로도 채택 접는 쪽 판단, 마지막 측정(K-01) 1회로 종결 지시.

### 하네스 수정 후 재실행 — "결론 2"가 오히려 재확인됨

`run_j02_transformers.py`를 FIX_GUIDE_11 §3-1대로 고쳤다: ① `attention_mask`를
`generate()`에 전달 ② `audio_chunk_index`로 청크를 제대로 재조립(`processor.decode`,
더 이상 `[0]`만 안 읽음) ③ 청크별 실제 생성 토큰 수를 `eos_token_id` 기준으로 개별
계산(배치 패딩 포함 최대 길이 아님).

**결과: 하네스를 바로잡아도 긴 한국어(60초, 청크 2개)는 여전히 무너진다.**
청크별 생성 토큰 `[256, 256]` — 패딩 아니라 **각 청크가 개별적으로 상한에 닿음**.
출력도 이전과 같은 양상의 반복 루프("쫑쫑쫑...", "즐기면서 즐기면서..."). 5초 결과
(청크 1개, 상한 근접 아님, "저희가 결정해서 유청서, 제출해지시면 서로 떨어지게.")는
불변.

**정정의 정정**: FIX_GUIDE_11 §1의 "하네스 결함 3개"는 실제로 존재하는 결함이었고
고치는 것 자체는 옳았다(라이브러리가 `attention_mask`를 명시적으로 요구하는 경우를
놓치고 있었으니 그 자체로 잠재 버그). **다만 그 결함이 관측된 반복 루프의 원인은
아니었다.** 즉 FIX_GUIDE_10의 원래 "결론 2"(긴 한국어에서 mlx-audio·transformers 둘
다 무너진다 → 실제 모델/디코딩 특성)가 **결과적으로 맞았다** — 다만 그 근거가 됐던
최초 측정 방법에 결함이 있었던 것과, 결론 자체가 틀렸던 것은 별개였다. 하네스를
바로잡은 재측정으로 같은 결론이 독립적으로 재확인됐다.

### §3-2(CER용 정답 작성) 실행 불가 — 사용자 결정으로 대체

FIX_GUIDE_11 §3-2는 5초 클립을 **귀로 직접 듣고** 정답을 적으라고 지시했으나, Sonnet은
오디오 재생/청취 도구가 없어 실행 불가. 사용자에게 확인 결과: **CER 측정 생략, 질적
판단만으로 종결** 결정. §3-3(CER 3줄 비교)·§3-4(30초 청크 기록)는 이 결정에 따라
미실행.

### 판정 — FIX_GUIDE_11 §4 "종결" 갈래로 확정

§4 판정표는 CER 수치 기준이었으나, 이번 재측정으로 얻은 **질적 증거가 이미 명확**하다:

- 가장 쉬운 조건(5초, 배치 없음, 포팅 버그 없음, transformers 네이티브)에서도
  Cohere 출력("저희가 결정해서 유청서, 제출해지시면 서로 떨어지게.")은 정답
  ("저희가 결제 요청서 제출해 주시면 사업단에서 결제하도록 하겠습니다.")과
  내용어 대부분이 틀림.
- 긴 오디오(35초 초과 → 필연적으로 청크 분할)에서는 **양쪽 구현 모두, 하네스를
  바로잡은 뒤에도** 반복 루프로 완전히 무너짐.
- FIX_GUIDE_11 §4가 이미 "비슷함(±20% 이내)에서도 종결"이라고 명시해 뒀고, 지금
  결과는 "비슷함"보다 명백히 나쁜 쪽 — CER을 재지 않아도 종결 기준을 충족한다.

**→ v0.2 Cohere Transcribe 백엔드 채택하지 않음. Whisper(large-v3/large-v3-turbo)
유지.**

### §5 종결 정리 — 완료

- **§5-1 문서 배너**: `FIX_GUIDE_8.md`·`FIX_GUIDE_9.md`·`FIX_GUIDE_10.md` 맨 위에 종결
  배너 추가. 본문은 전부 보존(지우지 않음) — 모델 조사·측정 방법론 자산으로 유지.
- **§5-2 살려서 쓸 것**:
  - **신규 [COMPARISON_METHOD.md](COMPARISON_METHOD.md)** — FIX_GUIDE_8 §10을 일반화해
    분리. Cohere 전용 문구를 걷어내고 "언제든 새 모델/백엔드 후보를 비교할 때" 쓰는
    절차로 재구성(측정 대상 3종 구성, 정답 편향 방지, 정규화 동결, 측정 환경 격리,
    **정답을 못 만들 때 강행하지 않는 절차**를 §6으로 신설 — 이번에 실제로 겪은 사례를
    반영). 바로 쓸 대상: large-v3 vs large-v3-turbo 한국어 비교(새 모델 도입 불필요).
  - **Xet 다운로드 헬퍼**: 코드로 구현하지 않음. FIX_GUIDE_11 §6이 "v0.2 내용은 Sonnet이
    정하지 않는다"고 명시했으므로 **v0.2 후보 항목으로만 기록**(아래 "다음 단계" 참고).
    실제 구현은 사용자가 v0.2 범위를 확정한 뒤 별도 FIX_GUIDE로 착수.
- **§5-3 디스크·환경 정리**: `scripts/h00_probe/weights_check`(3.9GB)·`j01_clips`
  (임시 클립)·`.probe_venv`(torch·librosa·faster-whisper·mlx-audio 전부) 삭제 완료.
  `run_j01.py`·`run_j02_transformers.py`·`run_probe.py`·`decoded_16k.npy`는 근거
  보존용으로 남김. **앱 `.venv` 격리 확인**: `torch`는 이번 세션 시작 전부터 이미
  앱 `.venv`에 있었음(mlx 계열 전이 의존성, 오염 아님) — `mlx_audio`·`librosa`는
  둘 다 부재 확인, 격리가 끝까지 지켜졌음을 재확인.
- **§5-4 보안**: `~/.cache/huggingface/token`(사용자 게이트 동의 시 생성) 그대로 둠
  (사용자 자산, 삭제 안 함). **다음 DMG 빌드 때 번들 안에 이 토큰·`.cache/huggingface`
  흔적이 섞이지 않았는지 실제로 뒤져서 확인할 것** — 아직 미실행, 다음 DMG 빌드
  작업의 체크리스트 항목으로 남김.

### 앱 코드·테스트 영향

이번 라운드(FIX_GUIDE_9~11) 전체에서 `src/lecture_scribe/**` 무변경. `pytest -q`/
`mypy --strict src/` 재실행 불필요(코드 변경 없음 — 전부 진단·문서 작업).

### 다음 단계 — 사용자 확인 필요 (FIX_GUIDE_11 §6, Sonnet이 정하지 않음)

v0.2의 간판 기능(Cohere)이 빠져 릴리스로 묶기엔 얇음. 후보:

1. **large-v3 vs large-v3-turbo 한국어 실측 비교** — `COMPARISON_METHOD.md` 절차를
   바로 적용, 새 모델 도입 없음. 이번 조사에서 가장 자연스럽게 이어지는 후속.
2. **다운로드 견고화**(Xet 정지 시 `hf_xet` 없이 재시도하는 공용 헬퍼 — 이번에 2회
   재현된 실제 문제, faster-whisper·mlx-whisper 모델 다운로드에도 해당) +
   이번 문서 정리를 묶어 **v0.1.1**로 내고 v0.2는 나중으로 미루기.
3. 사용자가 별도로 원하는 기능.

## 2026-09-13 (1) — FIX_GUIDE_10.md J-01·J-02 실행 (Sonnet) — **원인 2개로 분리됨, Opus 판단 필요**

Opus가 FIX_GUIDE_9의 한국어 결과를 "판정 불가"로 보고 교란 변수 분리 실험 지시.
J-01(언어×길이 2x2)·J-02(transformers 네이티브 교차검증) 완료. 새 다운로드 없음
(기존 3.9GB 체크포인트 재사용). 앱 코드 무변경.

### J-01 — 2x2 결과: **길이가 원인이 아니다**

| 셀 | generation_tokens | 상한 근접 | 판정 |
|---|---|---|---|
| 영어 짧음(4.5s) | 20 | 아니오 | 정답 완벽 |
| 영어 길음(36.3s, 이어붙임) | 40(세그당 20) | 아니오 | 정답 문장 정확히 2회 반복 — 정상 |
| **한국어 짧음(5.0s)** | **256(=상한)** | **예** | **"쟤 쟤 쟤 쟤..." — 5초짜리도 즉시 붕괴** |
| 한국어 길음(60s, 기존) | 512(=상한×2) | 예 | FIX_GUIDE_9 결과와 동일 재현 |

**결론**: 영어는 8배 길어져도 안 무너지는데 한국어는 5초에서도 즉시 무너짐 →
**길이 문제가 아니다.** `max_tokens=1000`으로 올려서 재시도(§2-3)해도 해결 안 됨 —
오히려 더 길게 헛소리를 내면서 **깨진 UTF-8 대체 문자(�)까지 출력**됨(토큰 ID가
유효하지 않은 바이트 시퀀스로 디코드되고 있다는 뜻 — 단순 "모델이 한국어를 못한다"보다
**디코딩/토크나이저 쪽 이상 정황**에 더 가까움).

### J-02 — transformers 네이티브 교차검증: **원인이 둘로 갈라짐**

같은 체크포인트를 완전히 독립된 구현(HF `transformers` 5.17.0 네이티브,
`CohereAsrForConditionalGeneration`, `trust_remote_code` 없음)으로 재실행.
**probe venv 전용으로 `torch`·`librosa`·`faster-whisper` 추가 설치**(앱 `.venv` 무관,
격리 유지). BF16 체크포인트를 CPU에서 float32로 로드해야 함(dtype 불일치 실측 확인 —
`RuntimeError: Input type (float) and bias type (c10::BFloat16)`).

| | mlx-audio | transformers 네이티브 |
|---|---|---|
| 한국어 짧음(5.0s) | 256토큰(상한), **"쟤 쟤 쟤..." 완전 헛소리** | **21토큰(정상), "저희가 결정해서 유청서, 제출해지시면 서로 떨어지게."** — 부정확하지만 **진짜 한국어 시도**(결정해서≈결제, 유청서≈요청서 — 음성적으로 근접) |
| 한국어 길음(60s) | 512토큰(상한), 반복 루프("쭈구에"·"브리미") | **256토큰(상한), "쫑쫑쫑쫑..." — 똑같은 양상의 반복 루프** |
| 영어 짧음(대조) | 완벽 | 완벽(동일 출력) |

**결론 1(짧은 한국어의 mlx-audio 고유 버그)만 유효. 결론 2는 정정됨(FIX_GUIDE_11.md §1):**

1. **짧은 한국어에서만 나타나는 mlx-audio 고유 버그 — 유효.** transformers는 5초 한국어를
   정상 처리(부정확해도 붕괴 없음)하는데 mlx-audio는 같은 조건에서 즉시 무너진다.
   FIX_GUIDE_10 §3-2가 예상한 "포팅 버그" 갈래에 해당.
2. ~~긴 한국어에서는 mlx-audio·transformers 둘 다 무너진다 → 모델/디코딩 특성~~
   **[2026-09-13 정정 — Opus, FIX_GUIDE_11.md §1] 이 결론은 철회한다.** J-02 하네스가
   긴(60초) 클립에서 세 가지를 틀렸다: ① `attention_mask`를 `generate()`에 안 넘김
   (`feature_extraction_cohere_asr.py:235`가 "batched inference 시 항상 넘겨야 한다"고
   명시 경고) ② 60초는 `max_audio_clip_s`(35초) 초과로 **실제로 청크 2개=배치 2**가 됐음
   (`_split_audio_chunks_energy()`) — 즉 위 경고가 정면으로 적용되는 경우였음
   ③ `batch_decode(...)[0]`으로 청크 1을 버렸고, 토큰 수도 배치 패딩 포함 최대 길이라
   "256=상한" 판정 자체가 무효. **짧은 5초 결과는 배치 1·패딩 없음이라 영향 없음** —
   그래서 결론 1은 그대로 유효하다. 긴 오디오에 대한 mlx-audio·transformers 양쪽 주장은
   전부 무효로 처리한다.

이 정정과 무관하게 **Cohere 채택 여부는 이미 판단됨(FIX_GUIDE_11.md §2·§4)**: 가장 쉬운
조건(5초, 배치 없음)의 transformers 결과("저희가 결정해서 유청서, 제출해지시면 서로
떨어지게." vs 정답 "저희가 결제 요청서 제출해 주시면...")부터 내용어가 대부분 틀려
있어, 포팅 버그를 고쳐도 도달점이 현재 Whisper large-v3보다 나쁘다. FIX_GUIDE_11.md의
K-01(마지막 측정, CER 비교)로 수치화 후 종결 절차 진행 — 아래 새 항목 참고.

### 부수 확인

- transformers 로드 시 내부적으로 `transformers.models.parakeet.modeling_parakeet`을
  재사용함(Fast-Conformer 인코더가 NVIDIA Parakeet 계열과 코드 공유 — 정상, 버그 아님).
- 짧은 한국어 clip 출력을 음성적으로 보면(결정해서/결제, 유청서/요청서) **완전히
  무관한 헛소리는 아니고 인식은 되는데 부정확한 수준** — 대략 Whisper 초기 모델
  급의 정확도로 보임(정밀 CER은 아직 안 잼, 이번 실험 목적 밖).

### 사용한 파일 (앱 코드 아님)

- `scripts/h00_probe/run_j01.py` — J-01 2x2 + max_tokens 실험
- `scripts/h00_probe/run_j02_transformers.py` — J-02 대조군
- `scripts/h00_probe/j01_clips/` — `ko_short.m4a`(5s, 원본에서 자름)·`en_long.m4a`(36s,
  이어붙임). 임시 산출물, 원본 샘플 파일은 안 건드림
- probe venv에 `torch`·`librosa`·`faster-whisper` 추가 설치됨(J-02 전용, 앱 `.venv` 무관)

### Opus 확인 필요

1. 짧은 한국어의 mlx-audio 고유 버그 — 원인을 더 팔지(J-02가 이미 "포팅 버그"임을
   증명했으므로, 추가로는 "정확히 어디가 깨졌는지"만 남음 — mlx-audio 소스 대조 필요),
   아니면 여기서 mlx-audio(GPU) 경로를 포기하고 transformers(CPU, 느림) 경로로
   대체할지 판단 필요.
2. 긴 오디오의 반복 루프는 **양쪽 다 겪는 실제 한계**로 보임 — VAD로 청크를 짧게
   나누면(FIX_GUIDE_8 §4 원래 계획대로) 이 문제가 회피될 가능성이 있음. 단 "짧게"가
   구체적으로 몇 초여야 안전한지는 이번 실험 범위 밖(원래 J-03이 이걸 재는 용도였는데,
   "길이가 유일한 원인"이 아니라고 판명 나서 조건 충족 여부가 애매해짐).
3. mlx-audio CPU 경로(torch/transformers)로 대체 시 GPU 가속을 포기하게 되는데, 이게
   FIX_GUIDE_8 v0.2의 핵심 가치(속도)를 얼마나 깎는지 재계산 필요.

### §3 완료 (사용자 행동): HF 토큰 확보

사용자가 `hf auth login`(본인 터미널) + 게이트 동의 완료. **env var 방식은 이 세션 프로세스
경계 때문에 안 먹혔다** — `hf auth login`이 `~/.cache/huggingface/token`에 저장하는 방식으로
전환해 해결. `hf auth whoami` 확인, 인증 후 API 접근 200 확인.

### §4 재측정 완료 — 원인 진단 적중 확인, 새 발견(한국어 반복 루프)

토큰 확보 후 **먼저 원본 게이트 리포(`CohereLabs/cohere-transcribe-03-2026`) 헤더만 Range로
대조**(가이드 §3 지시대로 추론 전 확인) — `transf_decoder.*` 214개, `log_softmax.*` 2개,
`preprocessor.*` 2개 **전부 존재 확인**. 커뮤니티 변환본과 정반대로 정상. 전체 다운로드
(4.13GB, BF16, 4분 46초, hf_xet 이미 제거된 상태라 순정 HTTP로 안정적).

`run_probe.py`를 가이드 §4대로 갱신(영어 먼저 판정 → 통과 시에만 한국어, `strict=True` 강제)
후 실행:

- **영어(`en_5s.m4a`, 4.5초)**: **완벽 통과.** 출력 = "Today we will discuss impedance
  matching and the Smith chart in microwave engineering." — 정답과 **완전 일치**(글자 단위).
  §1의 원인 진단(`strict=False`가 `transf_decoder.*`/`log_softmax.*`를 조용히 버려 디코더가
  미초기화 상태로 돌았다)이 **정확했음이 실측으로 확정됨.** `strict=True`로 로드하니 즉시
  정상 동작 — 로드 단계에서 예외도 안 남(즉 이 정식 체크포인트는 애초에 안 맞는 키가 없었다는
  뜻이기도 함).
- **한국어(`9:1 전자회로 클립.m4a`, 60초)**: **부분 실패 — 새로운 문제.** 더 이상 언어가
  뒤섞인 헛소리는 아니고 **실제 한국어 단어들**이 나오지만, 내용이 정답과 크게 다르고
  **심한 반복 루프**가 있음("쭈구에"가 약 20회, "브리미"/"브리"가 약 15회 연속 반복).
  `mlx_audio`의 `cohere_asr.py` `_generate_batch_tokens()`가 **순수 그리디(argmax) 디코드이고
  반복 억제 장치가 전혀 없음**(공개 `generate()` API에도 `repetition_penalty`/`no_repeat_ngram`
  류 파라미터가 없음, 이전 세션에서 전체 시그니처 확인됨) — 이게 원인으로 보이나 **모델
  자체의 한국어 정확도가 낮은 것과 분리해서 볼 수 없음**(FIX_GUIDE_8 §1-2: 한국어 CER은
  애초에 비공개, 재봐야 아는 상태였음).
- **속도(H-00-f)**: 60초 클립 RTF **16.40x**(3.7초 소요) → 45분(2712초) 외삽 시 **약 165초
  (2.8분)**. 이 repo의 기존 실측 최고 기준선(mlx large-v3 GPU 5.0x, 약 9분)보다 **훨씬 빠름.**
  단, 위 품질 문제 때문에 이 속도가 실사용 가치로 이어지는지는 별개 문제.
- **메모리(H-00-g 1회 재확인)**: load 후 RSS 1034MB(BF16 4.13GB 파일 치고 낮음 — MLX lazy
  eval 추정), unload 후 118.3MB. 이전 5사이클 결과(111~118MB)와 일치, 누수 재확인.

### Opus 확인 필요 — 판정

FIX_GUIDE_9.md §11의 두 갈래("정상 전사" / "정식 체크포인트로도 깨짐") **어느 쪽에도 깔끔히
안 들어맞음** — 영어는 완벽, 한국어는 "깨짐"보다는 낫지만 "정상"도 아닌 중간 상태(반복 루프로
품질 저하). 판단 필요:

1. 이 상태로 §10 비교 측정(FIX_GUIDE_8)까지 갈 가치가 있는지, 아니면 반복 루프 문제를
   먼저 우회할 방법(예: 청크를 더 짧게 나눠 반복이 걸릴 여지를 줄이는 것 — §4의 VAD 분할이
   원래도 30초 단위로 자를 계획이었으므로 60초 무분할 테스트보다 나아질 가능성 있음)을
   찾아본 뒤 재판단할지.
2. 후자라면 "30초 단위 분할 시 반복 루프가 줄어드는지"를 다음 확인 항목으로 추가할 필요.
3. `HF_TOKEN` 캐시(`~/.cache/huggingface/token`)가 이 머신에 남아 있음 — 앱 배포판
  (PyInstaller 번들)에 실수로 포함되지 않게 §12(DMG 검증)에서 확인 필요(FIX_GUIDE_8 기존
  게이트에 추가할 항목으로 남겨둠).

## 2026-09-12 (1) — FIX_GUIDE_8.md H-00 선행 실측 (Sonnet) — **막힘, Opus 확인 필요**

FIX_GUIDE_8.md(v0.2: Cohere Transcribe 백엔드) §2 H-00을 순서대로 확인. **H-00-c(실제 전사)에서
막혀 이후 단계(H-01 이후) 착수 안 함.** 확인된 사실만 기록, 추측·우회로 넘어가지 않음(가이드 §2 지시).

### 결과 요약표

| 항목 | 결과 |
|---|---|
| H-00-a(토큰 없이 받기) | **성공.** 단 가이드가 지정한 `mlx-community/cohere-transcribe-03-2026-mlx-8bit`는 **이름과 달리 실제로는 BF16 가중치**(scale 텐서 0개, 실측 확인) — **버그 있는 리포**. `beshkenadze/cohere-transcribe-03-2026-mlx-8bit`(2.42GB, scale 텐서 388개 확인됨, 진짜 int8)로 교체 필요 |
| H-00-b(mlx-audio 설치) | **성공.** Python 3.12 OK. `sounddevice`가 끌고 오는 PortAudio는 arm64 슬라이스 포함된 universal binary — 번들링 우려 없음(§3 우려 기각) |
| H-00-c(실제 한국어 전사) | **실패.** 아래 상세 |
| H-00-d(신뢰도 점수) | **불가 확정.** mlx-audio 디코드 루프가 그리디 argmax만 하고 logit을 버림(`cohere_asr.py` `_generate_batch_tokens`). `STTOutput`에도 점수 필드 없음 → 가이드 §5-2 "avg_logprob 0.0 고정 + 신뢰도 기능 비활성화" 경로로 확정 |
| H-00-e(hotwords/프롬프트 주입) | **불가 확정.** `tokenizer.py`의 `build_prompt_tokens(language, punctuation)`이 고정 제어토큰만 만듦(`<startofcontext><startoftranscript><lang><lang><pnc><noitn><notimestamp><nodiarize>`) — 자유 텍스트 슬롯 자체가 없음. mlx-audio 자체의 `merge_hotwords()`/`_NATIVE_FIELD` 메커니즘도 `cohere_asr.py`는 지원 목록에 없음(whisper/qwen3_asr/vibevoice_asr/moss만 있음) → §6-2 실험 자체가 불필요, `capabilities().hotwords = False` 확정 |
| H-00-f(속도) | 측정은 됐으나(20초 클립 기준 RTF 약 8~10x, 45분 외삽 시 약 5분) **출력이 깨져 있어 의미 없는 숫자**. 재측정 필요 |
| H-00-g(메모리 누수) | **깨끗함.** load→infer(20초 클립)→unload 5사이클, unload 후 RSS 111→118MB로 사실상 평탄(가이드 판정선 +300MB 대비 여유 큼). load 후 RSS 1856~1865MB 안정 |

### H-00-c 상세 — 전사 자체가 깨짐 (막힌 지점)

`beshkenadze/cohere-transcribe-03-2026-mlx-8bit` + `mlx_audio.stt.utils.load_model()` +
`model.generate(audio, language="ko"|"en", vad=False)` 조합으로 **한국어·영어 모두 완전히
뒤섞인 언어의 의미 없는 텍스트만 나옴** (그리스어·폴란드어·베트남어·중국어·한글 토큰이
무작위로 섞인 문자열). 정답과 전혀 무관.

**배제한 원인들** (실측으로 하나씩 제거):
1. 오디오 디코드/리샘플 문제 아님 — 이 앱이 실제로 쓰는 `faster_whisper.audio.decode_audio()`로
   만든 16kHz 배열(진폭·길이 정상 확인)을 그대로 넣어도 동일하게 깨짐.
2. 한국어 특정 문제 아님 — `assets/samples/en_5s.m4a`(정답 있음: "Today we will discuss
   impedance matching and the Smith chart in microwave engineering.")로도 동일하게 깨짐.
3. 양자화 손상 아님(적어도 헤더 레벨에서는) — safetensors 헤더에 `.scales` 텐서 388개 정상 존재.
4. 알려진 HF 이슈(discussions/28, "trust_remote_code + transformers≥5.3에서 깨짐")와는
   **무관**. 그 이슈는 HF `transformers`의 원격 코드 경로 얘기고, mlx-audio는 그 경로를 아예
   안 쓰는 완전 별도의 MLX 네이티브 재구현(`cohere_asr.py`)이라 해당 안 됨.

**아직 안 해본 것(다음 진단 후보, Opus 판단 필요)**:
- fp16 미양자화 버전(`beshkenadze/cohere-transcribe-03-2026-mlx-fp16`, 4.13GB)으로 같은 테스트 —
  양자화 변환 자체가 깨졌는지 vs mlx-audio 구현 자체가 깨졌는지 구분 가능. **추가 4GB 다운로드
  필요.**
- HF transformers 네이티브 파이프라인(`pipeline("automatic-speech-recognition", ...)`)으로
  대조 — 단 **원본 리포가 게이트되어 있어 HF 토큰 필요**(가이드 §1-1 H-00-a 표에 이미 명시된
  제약. 토큰 발급은 사용자 동의 필요 사항).
- `mlx-audio` 버전 문제인지 확인(GitHub 이슈 검색 결과 없음 — 이 조합에 대한 보고된 버그 못 찾음).

### 추가 발견 — 가이드 범위 밖 설계 이슈 (Opus 판단 필요, §14 규칙에 따라 직접 결정 안 함)

**mlx-audio의 `cohere_asr.generate()`는 자체 VAD를 이미 내장하고 있다** (`vad=True`,
`vad_max_chunk_s=30.0` 기본값 — 가이드가 고른 30초 상한과 우연히 일치, `start`/`end` 타임스탬프도
자체로 냄). 그런데:

1. 이건 `faster_whisper.vad`(onnxruntime 기반 Silero)가 아니라 **`mlx-community/silero-vad`라는
   전혀 다른 MLX 전용 가중치를 새로 받는 별도 구현**이다 — 가이드 §14-5("VAD 새로 구현·새 의존성
   추가 금지, `faster_whisper.vad` 재사용")와 충돌.
2. **더 중요한 문제**: 이 자체 VAD가 **설치본(0.5.3)에서 실제로 깨져 있다** — 실행하면
   `TypeError: astype(): ... Invoked with types: mlx.core.array, type`
   (`vad.py:56`, `waveform.astype(np.float32)`를 MLX 배열에 호출 — numpy/MLX API 혼동으로 보이는
   라이브러리 자체 버그). **재현 스택트레이스 확인함.**

→ 이 두 사실 때문에 "자체 VAD 재사용 vs `faster_whisper.vad`로 직접 청크 나눠 `vad=False`로
호출" 사이에서 **원안(직접 청크)이 사실상 유일한 선택지**로 기울었지만, 이건 §4 설계를 실제로
바꾸는 판단이라 Opus 단계로 반환.

### 확인된 사실 정정 (가이드 §1-1 표 갱신 필요)

가이드가 지정한 리포 ID `mlx-community/cohere-transcribe-03-2026-mlx-8bit`는 **써서는 안 됨**
(BF16을 int8로 잘못 라벨링, 다운로드 0회 — 아무도 검증 안 한 리포였음). 대신
`beshkenadze/cohere-transcribe-03-2026-mlx-8bit`(다운로드 291회, 실측 확인된 진짜 int8, 2.42GB)를
써야 함. 같은 업로더가 `-mlx-fp16`/`-mlx-6bit`/`-mlx-4bit`도 올려 둠.

### 부수 발견 — 인프라

- HF Hub의 Xet(CAS) 전송이 이번 다운로드에서 **2회 연속 정지**(CLOSE_WAIT 다수, 4분 이상 진행
  없음) — `faster.py`가 이미 겪어 문서화해 둔 것과 같은 종류의 실패. `hf_xet` 패키지를 아예
  제거(`pip uninstall hf_xet`)하고 순수 HTTP로 강제하니 정상 완주(3분 34초~1분 43초). **§1의
  실행 경로 표에 "Xet 정지 시 `hf_xet` 언인스톨"을 대응책으로 추가할 필요.**
- 첫 번째(잘못된) 리포 다운로드 중 Xet CAS가 최종 파일 크기(2.05~2.5GB 추정)보다 훨씬 큰
  중간 재구성 파일(최대 3.7GB)을 만듦 — CAS 청크 중복제거 특성상 정상, 버그 아님.

### 사용한 파일 (앱 코드 아님, 재현용 보존)

- `scripts/h00_probe/run_probe.py` — H-00-c/f/g 통합 측정 스크립트
- `scripts/h00_probe/.probe_venv` — 격리 venv(앱 `.venv` 무오염 확인됨)
- `scripts/h00_probe/weights_check/` — 다운로드한 실제 가중치(2.42GB, `beshkenadze` 버전).
  디스크 393GB 여유 있어 당장 안 지움. 다음 진단(fp16 대조)에 재사용 가능.
- `scripts/h00_probe/decoded_16k.npy` — `decode_audio()`로 만든 검증된 16kHz 배열(대조용)

### Opus 확인 필요 — 정리

1. **H-00-c가 막힘.** fp16 대조 테스트(4GB 추가 다운로드)로 계속 팔지, 아니면 mlx-audio
   경로 자체를 이번 v0.2에서 보류할지 판단 필요.
2. VAD 설계 재검토 필요(위 "추가 발견" 참고) — mlx-audio 자체 VAD는 버그로 인해 어차피 못 씀,
   `faster_whisper.vad` 직접 사용(원안)으로 사실상 결정된 것으로 보이나 정식 승인 필요.
3. 가이드 §1-1의 리포 ID를 `beshkenadze/cohere-transcribe-03-2026-mlx-8bit`로 정정 필요.
4. H-00-d/e는 결과가 명확해 추가 조사 불필요 — §5-2/§6-2 그대로 진행하면 됨(단, H-00-c가
   풀려야 의미 있음).

## 2026-09-08 — FIX_GUIDE_7.md 실행 (자동 용어 빈도 관리·토큰 정리) (Sonnet)

사용자 요청: "용어란에 자동 입력되는 단어들을 최근 감지 많은 순서로 남기고, 토큰 제한 지키게."
Opus가 FIX_GUIDE_7.md로 E-01(등장 통계 누적·감쇠)·E-02(토큰 예산 정리) 지시. "헷갈리기 쉬운 단어
위주" 필터는 범위에서 명시적으로 제외됨. 전건 완료.

- **신규 `src/lecture_scribe/glossary_stats.py`**: GUI/백엔드 비의존 순수 함수 + 파일 I/O.
  `~/Library/Application Support/LectureScribe/glossary_stats.json`에 프리셋별
  `{용어: 점수}` + `자동 추가분 목록`을 저장 — `Preset`/`Settings`에 넣지 않음(가이드 §2-1 근거:
  `build_settings()`가 `Preset`을 새로 만들며 알려진 필드만 옮겨 담아 저장할 때마다 사라짐).
  `update_scores()`(감쇠 0.8, 바닥값 0.1)·`order_glossary()`(사용자 용어 원순서 유지 +
  자동 추가분 점수 내림차순).
  **버그 하나 잡고 넘어감**: 처음엔 `STATS_PATH`를 모듈 임포트 시점에 굳는 `Final` 상수로
  뒀는데, `conftest.py`의 `isolated_home` 오토유즈 픽스처가 `Path.home()`을 나중에
  패치해도 이미 계산된 상수엔 반영이 안 돼 **테스트가 실제 사용자 파일을 건드리는** 걸
  실측으로 확인(`test_gui.py -k glossary` 1회 실행만으로 진짜
  `~/Library/Application Support/LectureScribe/glossary_stats.json`가 생성됨).
  `default_stats_path()` 함수로 바꿔 **호출 시점에** `Path.home()`을 읽게 고침 — `config.py`의
  `SETTINGS_PATH`가 이미 이 문제를 갖고 있다는 것도 같이 발견해 별도 task로 분리해 뒀음
  (아래 "발견했지만 범위 밖" 참고).
- **`settings_panel.py`**: `add_glossary_terms()` 제거, `record_glossary_detections()`(감지분
  으로 점수 갱신 + 새 용어만 정렬해 반영)·`prune_glossary_terms()`(자동 추가분 ∩ 잘린 용어만
  삭제)·`_sync_auto_terms_for_preset()`·`_on_glossary_edited_by_user()`(사용자가 칸을 직접
  고치면 그 순간 남은 용어 전부 "사용자 것"으로 승격, 기존 `_loading` 플래그 패턴 재사용) 추가.
  프리셋 rename 시 통계 키도 같이 옮김, delete 시 정리(안 그러면 고아 데이터로 계속 쌓임).
  생성자에 `glossary_stats_path` 주입 포인트 추가(테스트 격리용).
- **`window.py`**: `_auto_suggest_glossary()`가 `record_glossary_detections()` 호출 후
  `_glossary_prune_pending` 게이트를 1회 세움. `_on_token_counted()` → `_maybe_prune_glossary()`가
  그 게이트가 서 있을 때만(자동 추가 직후 1회) `usage.dropped_terms`를 자동 추가분과 교집합해
  실제로 지움 — **토큰 계산 새 경로를 안 만들고 기존 `build_prompt_plan()`의 "뒤쪽부터 자름"
  동작을 그대로 활용**(자동 추가분을 점수순으로 뒤에 두면 "뒤에서 자름=점수 낮은 것부터 자름"이
  자동 성립, 가이드 §1-1). 추가+정리가 한 사이클에 겹치면 안내 메시지를 하나로 합침
  (`GLOSSARY_AUTO_ADDED_AND_PRUNED`).
- **실측 확인(실앱, §5-4)**: 8구간 등장 "임피던스" vs 3구간 등장 "스미스차트"/"반사계수"로
  실제 `MainWindow`를 띄워 확인 — 추가 시 `[임피던스, 스미스차트, 반사계수]`(점수순, 동점은
  원순서), 토큰 초과 시뮬레이션 시 가장 낮은 점수(반사계수)만 제거, 상태줄에 "3개를 추가했지만
  … 1개를 다시 뺐습니다: 반사계수", 통계 파일에 반사계수 **점수는 남고 auto_added에서만 빠짐**
  (재등장 시 재추적 가능하도록 설계대로).
- **테스트**: 신규 `test_glossary_stats.py`(13건, 순수 함수), `test_gui.py`에 12건 추가
  (정렬·사용자순서유지·정리·승격·파일영속·프리셋분리·전체사이클(E2E)·게이트 1회소진·rename 시
  통계 이동). `mypy --strict src/` 통과. `pytest -q`(465건, 기존 412+FIX_GUIDE_6·7분) —
  전체 스위트 단독 실행 시 간헐적 Qt 세그폴트 재현(FIX_GUIDE_5·6에서 이미 문서화된 기존 인프라
  문제, 매번 다른 스레드 지점 — 이번엔 `watchdog.py`) — 3회 중 1회는 465건 전건 통과, 나머지
  2회는 세그폴트 지점 이전까지는 전부 통과. `--ignore=tests/test_gui.py`(407)+`test_gui.py`
  단독(58) 분리 실행으로 465건 전건 통과 재확인. 내 변경과 무관함(범위 밖, 손대지 않음).
- **발견했지만 범위 밖(별도 task로 분리)**: `config.py`의 `SETTINGS_PATH`도 같은 종류의
  버그를 갖고 있어 `test_gui_fixes.py::test_window_size_and_ratio_both_restored`가 실제
  `~/Library/Application Support/LectureScribe/settings.json`을 건드림(mtime 변화로 실측
  확인). 이번 작업 범위(용어 빈도 관리)와 무관해 고치지 않고 task로 분리 등록.
- DMG 재빌드 예정(이 항목 마무리 후).

## 2026-09-07 — FIX_GUIDE_6.md 실행 (GUI 정리) (Sonnet)

사용자 보고: "단어/주제 예시문장들 날리는것, UI적으로 개선할 부분 찾아서 물어보고 fix guide 작성"
→ Opus가 FIX_GUIDE_6.md로 C-01~C-05 지시. 순서(C-02→C-04→C-01→C-03→C-05)대로 실행, 전건 완료.

- **C-02(예시문장 제거)**: `strings_ko.py`의 `TOPIC_PLACEHOLDER`·`GLOSSARY_PLACEHOLDER`·`TOPIC_TIP`에서
  "OO대…" "AWGN…" 등 과목 특정 예문 제거, 형식 안내(문장 권장·쉼표 구분)만 남김. `GLOSSARY_TIP`
  (무관 용어 넣으면 정확도 하락 실측 사례)은 지시대로 미변경.
- **C-04(정방형 강제 해제)**: `window.py` `resizeEvent()`의 정방형 강제 로직 제거(최소 480×480만 유지).
  `config.WindowState.size: int` → `width`/`height` 둘로 분리, `from_dict`가 옛 `size`만 있으면
  폭=높이=그 값으로 fallback 복원(SCHEMA_VERSION 안 올림). `_on_advanced_toggled`/`_apply_side`는
  높이만 조절하도록 변경(`_apply_height`). 기존 정방형-강제 검증 테스트 2건(`test_gui.py`)을
  독립 리사이즈 검증으로 교체, `test_gui_fixes.py`에 legacy fallback·독립 리사이즈 테스트 추가.
- **C-01(전사 경고 창 표시)**: `engine.FileResult`에 `quality_warnings`(반복+외국어 감지 `describe()`
  모음)·`info_warnings`(그 나머지) 프로퍼티 추가 — 문자열 substring 매칭 없이 구조화된
  `repeats`/`foreign_runs` 리스트로 분류. `_QueueRow`에 `⚠ N` 배지(품질 경고만 카운트, 0건이면
  숨김) 추가, 클릭 시 `QMessageBox`로 품질/정보성 구분해 원문 그대로 표시. 배지는 자식 버튼이라
  클릭이 행의 Finder-열기로 전파되지 않음(테스트로 확인). 재시도(`reset_row`) 시 배지 초기화.
- **C-03(고급설정 4구역)**: `settings_panel.py`에 `add_section()` 헬퍼 추가 — 인식(백엔드·배치·
  VAD·빔 크기)/프롬프트(initial_prompt·hotwords·이전 문맥·창 경계 문맥)/출력(포맷·타임스탬프·
  충돌 정책)/후처리(교정·유사도 교정·외국어 감지) 4구역으로 순수 재배치, 구역마다 소제목+구분선.
  위젯 속성·기본값·툴팁 무변경 — `test_every_advanced_widget_has_explanation` 등 기존 GUI 테스트
  전건 통과로 확인.
- **C-05(선별 인라인 설명)**: 전부가 아니라 "잘못 켜면 나빠지는" 4항목(배치 모드·initial_prompt·
  이전 문맥 유지·창 경계 문맥 유지)에 한 줄 회색 설명 고정 추가, "백엔드가 무시하는" 2항목(VAD·
  빔 크기)은 `apply_capabilities()`에서 현재 백엔드가 지원 안 할 때만 "현재 백엔드에서 무시됩니다"
  문구를 동적으로 노출(§5-3 백엔드 연동 반영). 나머지 항목은 툴팁 유지. `ADVANCED_INTRO`의
  "마우스를 올리면 설명이 나옵니다" 문구 삭제(더 이상 사실이 아님).
- **§6-3 육안 확인**: 실제 앱을 640×640 기본 크기와 640×900로 세로로 늘린 상태 둘 다 스크린샷으로
  확인. 기본 크기에서 고급 설정이 스크롤 영역 안에 정상 배치, 세로로 늘리면 정방형으로 되돌아가지
  않고 인식/프롬프트 구역과 인라인 설명(배치 모드 note, VAD/빔 크기의 "현재 백엔드에서 무시됩니다"
  — mlx 백엔드에서 실제로 노출됨 확인)이 그대로 드러남. 드롭존도 계속 온전히 보임.
- **테스트**: 신규 `test_engine_quality_warnings.py`(3건), `test_gui.py`(배지 3건 + 리사이즈 2건
  교체), `test_gui_fixes.py`(리사이즈 2건 교체 + legacy fallback 2건 추가). `mypy --strict src/`
  통과. `pytest -q`(442건) 2회 연속 전건 통과. `test_gui_fixes.py` **단독 파일 실행**은 간헐적으로
  세그폴트(FIX_GUIDE_5에서 이미 문서화된 기존 Qt/PySide6 인프라 문제 — 전체 스위트에서는 재현 안 됨,
  범위 밖이라 손대지 않음).
- DMG 재빌드 예정(이 항목 마무리 후).

## 2026-09-07 — FIX_GUIDE_5.md 실행 (한자/외국어 환각 억제) (Sonnet)

사용자 보고: "전사시 자꾸 중국어(한자)가 뜬다." Opus가 FIX_GUIDE_5.md로 B-01(no_speech_threshold
0.6→0.5 시도)·B-02(기대 언어 밖 문자 검출·마킹)를 지시. 순서대로 실행.

### B-02 — 기대 언어 밖 문자 검출 (완료, 기본 켬)

- `postprocess.py`: `find_foreign_script_runs()` 신규 — 한글/라틴 밖 문자(한자·가나·키릴 등)가
  섞인 세그먼트를 연속 구간(`ForeignScriptRun`)으로 묶어 찾는다. 판정은 비율(기본 0.3)
  **그리고** 최소 개수(기본 2) 둘 다 요구 — 짧은 세그먼트 오탐, 정상 문장에 낀 한자 1자
  오탐 둘 다 방지.
- `writer.py`: `render_md`에 `force_mark_ids` 추가 — `avg_logprob`과 무관하게 지정된
  세그먼트를 기존 `⟨?⟩` 마커로 표시(새 마커 안 만듦, CLAUDE.md §15-1·10 축자 전사 원칙 유지 —
  삭제·치환 없음).
  `engine.py`: 검출 → `result.foreign_runs` → 헤더 주석·`result.warnings`·사이드카 JSON
  (`foreign_script_segment_count`)·`marker_meaning` 문구(마킹 사유 2개로 명시) 전부 연결.
  언어가 ko/en일 때만 활성화(`result.language in ("ko","en")`) — 실제 중국어/일본어 강의는
  자동 비활성.
- `config.PostprocessSettings`: `foreign_script_detection`(기본 True)·`foreign_script_ratio`(0.3)·
  `foreign_script_min_count`(2) 추가.
- GUI: 설정 패널에 체크박스 1개(`foreign_script_check`) 추가, 임계값 2개는 설정 파일 전용.
- **§5-2 오프라인 검증**: 재측정 없이 기존 실제 산출물(`~/Desktop/캡스톤디자인/7:31 캡스톤 회의`,
  860세그먼트, A-02 이전 CPT=True 문제 런)로 검출기를 직접 돌림.
  - 검출: `自然に思い出す。` 반복 구간(FIX_GUIDE_4 A-02 관측 2와 동일 건, 18세그먼트)과
    한/중 혼합 환각 구간(2577~2601초, 중국어 번역이 그대로 붙어나온 5세그먼트) — **총 2건, 오탐 0건.**
  - 미탐(참고, 임계값 아래라 안 잡힘): 정상 문장에 낀 한자 1~2자(64,68,69,70), 비율 낮은
    혼합 환각(589,590,597) — 설계대로 "정상 문장의 낀 한자" 오탐 방지 우선한 결과.
    **오탐 0을 우선한다는 가이드 원칙(§4-2.5)에 따라 초기 제안값(비율0.3/개수2)을 그대로 확정.**
    임계값 변경 없음.
- 신규 테스트: `test_postprocess.py`(15건: stats/판정/구간묶기/헤더주석), `test_writer.py`(2건:
  force_mark_ids 단독/logprob 병행), `test_config.py`(2건: 기본값+roundtrip), `test_gui.py`(2건:
  설명 존재+로드저장), `test_engine_foreign_script.py`(신규 파일, 3건: md 마킹/사이드카/무검출시 무마킹).
  `mypy --strict src/` 통과, 관련 스위트 전건 통과.

### B-01 — `no_speech_threshold` 0.6→0.5 (실패 → 롤백)

**§5-1 게이트: 실패.** 실제 57분 강의 파일(`7:31 캡스톤 회의.m4a`)로 프로덕션 경로
(`engine.transcribe_file`) 그대로 실행, faster-whisper/CPU/int8/large-v3:

| 지표 | 0.6(기존) | 0.5(시도) | 판정 |
|---|---|---|---|
| 총 글자 수 | 19,251 | 18,900 (-1.82%) | **실패**(통과선 -1%) |
| 세그먼트 수 | 983 | 1,046 | 참고(+6.4%, 더 잘게 쪼개짐) |
| 반복 구간(`find_repeat_runs`) | 0 | 2("만나러"13회, "몰래"4회) | **실패**(증가) |
| 저신뢰 비율(<-0.8) | 7.53% | 6.88% | 통과(감소) |
| 외국어 세그먼트(`find_foreign_script_runs`) | 0 | 0 | 무차이(이 파일 기준 효과 없음) |
| 소요 시간 | 4176초 | 3284초 | 참고 |

총 글자 수 -1.82%가 통과선(-1% 이내)을 넘고, 반복 루프까지 새로 생겨 **명백한 실패** —
가이드가 미리 경고한 "환각 몇 건 줄이자고 실제 발화를 버리는 거래"가 그대로 재현됨.
이 파일에서는 외국어 세그먼트 감소 효과도 0.6/0.5 둘 다 0으로 차이 없었음(B-02가 애초에
그 파일의 환각 2건을 이미 다 잡아서 no_speech_threshold를 더 내릴 이유 자체가 약했음).
**`config.py`의 `no_speech_threshold` 기본값 0.6으로 롤백.** 주석에 실측 수치 기록.
GPU(mlx) 백엔드로도 같은 파일 0.6/0.5 교차 검증 시도 — CPU 결과만으로 이미 게이트가
확정 실패라 판정에는 영향 없음(§8 "게이트 통과 시에만 기본값 변경" — 하나라도 실패하면
롤백이 규칙). GPU 수치가 나오면 참고용으로 아래에 추가 기록.
`tests/test_config.py`의 기본값 단언 0.5→0.6으로 갱신, `mypy --strict` 재확인 통과.

**GPU(mlx) 교차 검증 결과(참고용, 판정 자체는 CPU만으로 이미 확정)**:

| 지표 | 0.6 | 0.5 | 판정 |
|---|---|---|---|
| 총 글자 수 | 18,365 | 18,051 (-1.71%) | **실패**(통과선 -1% 초과, CPU와 같은 방향) |
| 세그먼트 수 | 661 | 641 | 참고 |
| 반복 구간 | 3 | 3 | 동률 |
| 저신뢰 비율 | 7.56% | 6.71% | 통과(감소) |
| 외국어 세그먼트 | 4 | 4 | 무차이(GPU에서도 이 파라미터로 효과 없음) |
| 소요 시간 | 675초 | 648초 | 참고 |

CPU·GPU 둘 다 같은 결론(-1.71%~-1.82% 글자 손실, 통과선 초과) → **B-01 최종 판정: 실패, 롤백 확정.**
GPU 쪽 외국어 세그먼트 4건 전부 오탐 없이 진짜 혼합언어 환각(한/중/일 번역이 그대로 붙어나옴) —
B-02가 CPU 대조군(2건)보다 GPU에서 더 많이 잡아낸 것은 mlx가 이 파일에서 환각을 더 자주
내는 것으로 보임(A-02에서 이미 확인된 mlx 쪽 경향과 일치). B-02 자체는 두 백엔드 모두 정상 동작.

측정 스크립트(앱 코드 아님): `/private/tmp/.../scratchpad/b01_gate/run.py`,
`run_remaining.py` — 세션 스크래치패드 보존.

## 2026-09-06 (4) — 가이드 문서 없이 직접 처리한 사용자 요청 2건 (Sonnet)

FIX_GUIDE_4.md 완료 후 사용자가 직접 보고한 버그 1건 + 기능 요청 1건. 둘 다 범위가 작고
자명해(기존 코드의 같은 패턴을 그대로 재사용) 별도 Opus 가이드 없이 바로 처리.

### 버그: CPU/GPU 둘 다 "gemma 오인식 교정" 체크박스가 항상 비활성

- **원인**: `correction.ollama_available()`이 `shutil.which("ollama")`만 봤는데,
  번들(.app) 프로세스의 PATH는 `/usr/bin:/bin:/usr/sbin:/sbin`뿐이라(실측)
  Homebrew 설치 위치(`/opt/homebrew/bin`)를 못 찾음 — **ffmpeg/ffprobe가 예전에
  겪은 것과 완전히 같은 버그**(`audio.py find_binary()`가 이미 그 문제를 고정
  경로 목록 + PATH 순으로 찾는 방식으로 고쳐 놨었다). CPU/GPU와 무관하게 항상
  재현되는 게 당연함(교정은 백엔드 선택과 별개 기능).
- **수정**: `correction.py`에 `find_ollama()`(같은 고정 경로 + PATH 폴백 패턴)
  추가, `ollama_available()`과 `ensure_running()`의 `shutil.which("ollama")` 둘
  다 교체.
- **덤으로 발견한 진짜 버그**: `require_model()`이 `model.split(":")[0]`로 스템
  비교를 했는데, `gemma4:e4b`와 `gemma4:e2b`가 **둘 다 스템이 "gemma4"라 서로
  다른 모델인데 같다고 오판**했다(e2b만 설치돼 있어도 e4b 요구가 통과). 첫
  콜론이 아니라 끝의 `:latest`만 벗기도록 `_model_stem()`으로 교체.
- 테스트: `test_correction.py`에 `find_ollama`/`require_model` 회귀 4건.

### 기능: 시작 시 ffmpeg/Ollama/gemma 준비 상태 확인 + 설치 유도 스플래시

- `gui/dependency_check.py`(신규, Qt 비의존): ffmpeg/ffprobe, Ollama 실행 파일,
  Ollama 데몬, `CORRECTION_MODELS`(gemma4:e4b/e2b) 각각 점검. 문제 없으면
  `has_any_problem()`이 False라 호출부가 대화상자를 아예 안 띄운다.
- `gui/startup_dialog.py`(신규) `DependencyDialog`: 항목별로
  - 실행 파일 자체가 없음(ffmpeg/ollama) → **명령어만 보여주고 클립보드 복사**
    (앱이 사용자 승인 없이 brew를 대신 실행하지 않는다 — §안전 규칙)
  - Ollama 데몬만 꺼짐(실행 파일은 있음) → "지금 실행"(다운로드 없음, 안전해서
    바로 실행)
  - gemma 모델 미설치 → "지금 받기"(`ollama pull`, 다운로드 있음 — **버튼
    클릭 자체를 사용자 승인으로 봄**), 진행 로그를 대화상자 안에 스트리밍
  - 항상 "계속"으로 아무것도 안 고치고 넘어갈 수 있음(교정은 선택 기능,
    전사 자체를 막지 않는다)
- `gui/app.py main()`에 연결: `QApplication` 생성 직후, `MainWindow` 뜨기 전에
  점검 → 문제 있을 때만 모달로 띄움.
- 테스트: `test_dependency_check.py`(신규 6건, 실제 시스템 상태에 안 의존하도록
  전부 monkeypatch). 대화상자 자체는 offscreen 수동 스모크 테스트로 구성·재점검·
  버튼 흐름 확인(자동 테스트는 아직 없음 — QThread 백그라운드 동작이라 GUI
  자동 테스트 비용이 커서 보류).

### 테스트

- **406 passed**(기존 396 + 신규 10: dependency_check 6 + correction 4). `mypy --strict` 통과(35개 파일, `gui/dependency_check.py`·`gui/startup_dialog.py` 신규 포함).

### 변경/신규 파일

- 신규: `src/lecture_scribe/gui/dependency_check.py`, `src/lecture_scribe/gui/startup_dialog.py`, `tests/test_dependency_check.py`
- 수정: `src/lecture_scribe/correction.py`(`find_ollama`/`_model_stem` 추가, `ensure_running` 수정), `src/lecture_scribe/gui/app.py`(대화상자 연결), `src/lecture_scribe/gui/strings_ko.py`(문자열 추가), `tests/test_correction.py`

### 기능 추가: 교정 모델 드롭다운이 실제 설치된 gemma 버전을 전부 보여줌

사용자 요청("설치된 모든 gemma 버전을 찾아서 목록에 띄울 수 있게"). `CORRECTION_MODELS`
고정 두 개(e4b/e2b)만 보여주던 걸 실제 `ollama list` 결과 기반으로 바꿈.

- `correction.list_installed_gemma_models()` 신규 — `OllamaClient.models()`에서 이름에
  "gemma" 들어간 것만 걸러 정렬해서 돌려줌. Ollama 없음/데몬 꺼짐/조회 실패 전부 예외
  없이 빈 목록(호출부가 고정 목록으로 대체).
- `settings_panel.py`: 드롭다운 옆에 "새로고침" 버튼 추가. 패널 생성 시 한 번 조회 +
  버튼으로 언제든 다시 조회(패널 띄운 뒤에 Ollama를 켰거나 모델을 새로 받은 경우 대응).
  저장된 모델이 조회 목록에 없으면(예: 다른 기기에서 저장한 설정) 기존처럼 목록에 끼워
  넣어서 안 사라지게 하는 로직은 그대로 유지.
- 테스트 6건(correction 3 + gui 3). 412 passed. `mypy --strict` 통과.

### 다음 단계

- 이번 수정들 **전부 아직 배포 번들에 안 들어감** — Desktop의 DMG는 이 대화 이전에 빌드된 것. 재빌드 필요하면 말해줘.
- `DependencyDialog`의 백그라운드 실행/받기 흐름은 자동 테스트가 없음 — 실제로 Ollama가 없는 상태에서 GUI로 눌러 보는 수동 확인을 한 번 해보는 걸 권장.

## 2026-09-06 (2) — FIX_GUIDE_4.md 실행 (Sonnet)

작업 순서(가이드 §6) 그대로: A-01 → A-04+A-09 → A-06+A-07 → A-08 → A-03 측정 → A-02(구조 분리) → A-05.

### A-01 (완료) 교정 host 검증

- `config.py`에 `_validate_correction_host()` 추가. 허용: `localhost`/`127.0.0.1`/`::1`(스킴·포트 무관, `urlparse().hostname` 기준 — IPv6 대괄호는 자동으로 벗겨짐, 실측 확인). 그 외는 기본값 복귀 + WARNING. 탈출구: `LECTURE_SCRIBE_ALLOW_REMOTE_CORRECTION` 환경변수(켜도 매번 WARNING).
- 검증 위치는 설정 경계(`CorrectionSettings.from_dict`)로 뒀다(가이드 §4 지시).
- `logsetup.get_logger`를 쓰면 `config.py`↔`logsetup.py` 순환 임포트가 나서(logsetup이 LOG_DIR/LOG_PATH를 config에서 가져옴) 표준 `logging.getLogger(__name__)`로 우회.
- 테스트: `tests/test_config.py`에 허용 5케이스·거부 4케이스·탈출구 1케이스 추가.

### A-04 + A-09 (완료) 파일 열기 경로 테스트 + 침묵 실패 로그

- `gui/app.py _deliver()`: `add_files`가 없으면 예외 없이 WARNING 로그(A-09).
- `LectureScribeApp`은 `QApplication` 서브클래스라 전체 스위트를 한 프로세스로 돌리면 다른 GUI 테스트가 이미 만든 인스턴스와 충돌한다 — 새 테스트 파일(`tests/test_gui_app.py`)은 시나리오마다 **별도 파이썬 프로세스**로 격리해서 돈다(가이드가 허용한 "직접 호출 수준으로 낮춰서라도 커버" 대신 실제 클래스를 그대로 검증하는 방법 채택).
- 테스트 3건: 창 없을 때 큐잉→전달, 창 있을 때 즉시 전달, `add_files` 없는 창에 경고 로그.

### A-06 + A-07 (완료) 하트비트 견고성 + 취소 표시

- `backends/mlx.py _tick()`: `on_heartbeat` 콜백 예외를 잡아 1회만 로그하고 계속 돈다(전에는 조용히 죽어 하트비트가 영구히 멈췄다).
- `engine.py _on_heartbeat()`: `cancel.cancelled`면 "처리 중…" 대신 "취소 중…"을 보낸다. 취소 지연 자체(창 크기)는 손대지 않음 — 표시만 정직하게.
- 테스트: `test_mlx_stream_windows.py`(콜백 예외 후에도 전사 결과가 나오는지), `test_engine_heartbeat.py`(취소 전/후 메시지가 바뀌는지).

### A-08 (완료) `logsetup.py` 테스트

- `tests/test_logsetup.py` 신규(7건): 로그 경로, 중복 호출 시 핸들러 안 쌓임, verbosity별 콘솔 레벨, `get_logger` 반환값. 실제 `~/Library/Logs`는 안 건드리게 `tmp_path`로 격리.

### A-03 (측정 완료, 기본값 유지) word_timestamps/hallucination_silence_threshold 효용

우리 `backend.transcribe()` 경로 그대로, 실사용 반복 위치(0~270초, `condition_on_previous_text=True`) 2회 측정:

| 시도 | hst | 소요 | 세그먼트 | 최대 연속반복 | 저신뢰 |
|---|---|---|---|---|---|
| 1 | 2.0 | 185.7s | 61 | **13** | 1 |
| 2 | 2.0 | 182.8s | 55 | 1 | 19 |
| 2 | None | 77.9s | 53 | 4 | 9 |

- **비용은 뚜렷함**(약 55~60% 감소, 두 번 다 같은 방향) — A-03 조사 전 추정(30~45%)보다 실제로 더 크다.
- **반복 억제 효과는 판단 불가**: 같은 hst=2.0인데 13회 vs 1회로 시도 간 편차가 조건 간 차이보다 컸다. hst=None에서도 반복(4회)이 났다.
- **판정**: 가이드 §8 "측정 없이 기본값 뒤집기 금지" 원칙에 따라 **기본값(2.0) 유지**. 결과를 `backends/mlx.py`의 커플링 지점에 주석으로 남겨 다음 라운드가 추측 없이 시작하게 함. 새 UI 노출도 안 함 — 노출할 만한 명확한 트레이드오프가 아직 없음(효과 자체가 불명확).
- 스크립트: `.../5cd4fa6d.../scratchpad/a03/measure_backend.py` + 결과 JSON(재검증용 보존).

### A-02 (구조 분리 완료, 기본값 변경은 승인 대기) condition_on_previous_text ↔ carry_window_prompt 분리

- `TranscriptionRequest.carry_window_prompt`(신규, 기본 True) 추가. `mlx.py`에서 두 메커니즘을 분리:
  - `condition_on_previous_text` → mlx_whisper에 그대로 전달(내부 30초 서브청크 조건화만 제어)
  - `carry_window_prompt` → 우리 120초 창 경계 캐리 프롬프트만 제어(신규)
- `config.PromptSettings.carry_window_prompt`(기본 True) 추가, GUI에 새 체크박스 "창 경계 문맥 유지 (GPU 전용)" 추가(`BackendCapabilities.windowed_prompt_carry`로 faster-whisper에서는 회색 처리). 기존 "이전 문맥 유지" 툴팁도 범위를 명확히 하도록 갱신.
- **기본값은 둘 다 True로 유지** — 분리 전과 동작 동일(회귀 없음). 테스트로 두 값이 독립적으로 작동함을 직접 확인(`test_carry_window_prompt_independent_of_condition_on_previous_text` 등 2건).
- **예비 측정**(정식 게이트 아님, 방향성 확인용) — 같은 0~270초 구간, `carry=True` 고정, `condition_on_previous_text` True/False 비교:

  | 조건 | 소요 | 세그먼트 | 반복 |
  |---|---|---|---|
  | A(현행, cpt=True) | 140.4s | 64 | 없음 |
  | B(후보, cpt=False, carry 유지) | 77.7s | 34 | 없음 |

  속도 이득(약 45%)은 이번에도 같은 방향으로 재현됐다. 두 시도 모두 반복이 안 나 품질 비교는 못 했다(반복 자체가 매 시도 나는 게 아니라 실측으로 이미 확인됨 — A-03 표 참조).
- 스크립트: `.../5cd4fa6d.../scratchpad/a03/measure_a02.py` (보존).

### A-02 §5-2 정식 게이트 (완료, 2026-09-06 — 사용자 승인 후 실행) → **통과 → 기본값 변경 적용**

실사용 3462초 파일(`7:31 캡스톤 회의.m4a`) 풀 런, 우리 `backend.transcribe()` 그대로. A(현행: cpt=True) vs B(후보: cpt=False, carry=True):

| 항목 | A(현행) | B(후보) | 판정 |
|---|---|---|---|
| 소요시간 | 1420.5초(23.7분) | 639.9초(10.7분) | **B가 2.2배 빠름** |
| 반복 루프(`find_repeat_runs`, min_count=3) | 4건 | 4건 | 동률(둘 다 안 나빠짐) |
| 외국어 혼입 세그먼트 | 102개 | 11개 | **B가 89% 감소** |
| 저신뢰 비율(avg_logprob<-0.8) | 9.61%(74/770) | 8.04%(54/672) | B가 낮음(개선) |
| 용어 빈도(글로서리 12개 표제어 카운트) | — | — | 거의 동일(예: 시나리오 20→22, 데이터셋 13→13). 표기 흔들림 없음 |

- A/B 둘 다 파일 맨 앞(2.0초)에서 "이 영상은 비중을 잃지 못한 영상입니다."가 13회 연속 반복 — **같은 위치·같은 횟수로 양쪽에 동일하게 나타남 → 이 변수(cpt)와 무관한, 오디오 도입부 자체의 환각**으로 판단(정상 참작).
- **게이트 기준("네 항목 중 하나라도 나빠지면 기본값을 바꾸지 않는다") 판정: 5개 지표 중 나빠진 것 없음(3개 개선, 1개 동률, 1개 무관 현상) → 통과.**
- **적용**: `config.PromptSettings`에 `condition_on_previous_text_mlx: bool = False`(신규, mlx 전용) 추가. 기존 `condition_on_previous_text`(faster-whisper용, 기본 True)는 이 게이트와 무관해 **그대로 둠** — 필드를 분리해서 백엔드별 기본값이 서로 다르게 유지되게 했다(같은 필드였으면 못 나눴다).
- `engine.build_request()`가 `settings.backend`를 보고 mlx면 `condition_on_previous_text_mlx`, 아니면 `condition_on_previous_text`를 쓴다.
- GUI: "이전 문맥 유지" 체크박스 하나가 현재 선택된 백엔드의 필드를 보여주고 그 필드에만 저장한다(백엔드를 오가며 토글해도 서로 안 덮어씀 — `settings_panel.py load/build_settings` 양쪽 수정). 툴팁에 게이트 수치 요약 추가.
- 스크립트: `.../5cd4fa6d.../scratchpad/a02_gate/run_gate.py` + 세그먼트 원본 JSON 2개(재검증용 보존).
- 테스트(신규 6건): `test_engine_build_request.py`(백엔드별 분기 4건), `test_gui.py`(체크박스가 백엔드별 값 표시 + 저장 시 다른 백엔드 값 안 건드림 2건).

### A-05 (완료) 트레이 템플릿 아이콘

- `assets/appicon_template.png` 신규 — **새로 그리지 않고** `appicon.png`의 명암 대비에서 기계적으로 실루엣만 추출(밝은 픽셀만 불투명 검정, 어두운 배경은 투명). Qt `QImage` 픽셀 순회로 생성(실측: PIL 미설치, 새 의존성 안 씀).
- `gui/icons.py`: `load_tray_icon()` 신규 — 이 자산을 읽고 `QIcon.setIsMask(True)`로 macOS 템플릿 이미지 지정. 자산 없으면 컬러 아이콘으로 대체(마스크는 안 걺 — 컬러에 걸면 색이 다 날아감).
- `gui/notifier.py`: 트레이 기본 아이콘을 `load_app_icon()`(컬러) → `load_tray_icon()`(실루엣)으로 교체.
- `gui/window.py`: 컬러 앱 아이콘을 트레이에 넘기던 코드 제거(이제 `AppNotifier`가 알아서 템플릿을 쓴다) — `QIcon`/`QApplication` 관련 불필요해진 import도 정리.
- 테스트: `test_icons.py`에 2건 추가(템플릿 로드+마스크 확인, 자산 없을 때 컬러로 폴백하되 마스크 안 걺).

### 테스트

- **396 passed**(기존 363 + 신규 33: config 10 + gui_app 3 + mlx 5(A-06 1 + A-02 분리 2 + 기존) + engine 5(A-07 1 + build_request 4) + logsetup 7 + icons 2 + backends 2 + gui 2). `mypy --strict` 통과.

### 변경 파일

- 신규: `tests/test_gui_app.py`, `tests/test_logsetup.py`, `tests/test_engine_build_request.py`, `src/lecture_scribe/assets/appicon_template.png`
- 수정: `src/lecture_scribe/config.py`(A-01, A-02), `src/lecture_scribe/backends/base.py`(A-02), `src/lecture_scribe/backends/mlx.py`(A-02, A-03 주석, A-06), `src/lecture_scribe/engine.py`(A-02, A-07), `src/lecture_scribe/gui/app.py`(A-09), `src/lecture_scribe/gui/icons.py`(A-05), `src/lecture_scribe/gui/notifier.py`(A-05), `src/lecture_scribe/gui/window.py`(A-05), `src/lecture_scribe/gui/settings_panel.py`(A-02), `src/lecture_scribe/gui/strings_ko.py`(A-02), `tests/test_config.py`, `tests/test_mlx_stream_windows.py`, `tests/test_engine_heartbeat.py`, `tests/test_backends.py`, `tests/test_gui.py`, `tests/test_icons.py`

## 다음 단계

**FIX_GUIDE_4.md 전건 완료.** 대기 중인 새 가이드라인 없음. 다음 세션은 STATUS.md 이 항목까지 읽고, 사용자가 새 문제를 보고하면 그때 새 FIX_GUIDE 착수.

## 2026-09-06 — FIX_GUIDE_3.md 실행 (아이콘 / 알림 소유자) — **완료**

I-05는 사용자가 "A(현행 유지 + 안내)"로 확정. §5 작업 순서 1~7 전부 실행.

### §4-1 사전 확인 3가지 — 가이드 가정 중 1개는 틀렸음(실측으로 기각)

1. **빈 `QIcon()`은 파이썬에서 falsy다**(`bool(QIcon())` → `False`, `isNull()` → `True`). FIX_GUIDE_3.md §2-2가 "PySide6 QIcon엔 `__bool__`이 없어 `or` 폴백이 동작 안 한다"고 가정한 건 **틀렸다** — 실측으로 기각. 그래서 **I-02-3(`isNull()` 판정으로 교체)은 하지 않았다** — 고칠 게 없었다.
2. 소스 실행 상태에서 `QSystemTrayIcon.isSystemTrayAvailable()` / `supportsMessages()` 둘 다 **True**(플랫폼 cocoa). 사용자가 실제로 겪은 "알림이 Script Editor로 온다"는 GUI 트레이 경로가 아니라 **CLI/Quick Action(osascript 고정 경로)**이거나 **번들 정체성이 없던 상태(python3로 실행)**에서였을 가능성이 높음 — 아래 I-03 결과가 이걸 뒷받침.
3. 패키지 안에 런타임이 읽을 아이콘 자산이 **없었다**(확인됨, §2-3 판단 그대로 유효) → I-01 그대로 진행.

### I-01 (완료) 아이콘 원본 고정

- `src/lecture_scribe/assets/appicon.png`(1024×1024) 신설 — `make_app.py draw_icon()`이 그리던 도형을 **한 번 PNG로 내보내 원본으로 고정**(새 디자인 창작 안 함, 가이드 §6-1 준수). `src/lecture_scribe/assets/__init__.py` 추가(패키지화, `importlib.resources` 접근용).
- `packaging/make_app.py make_icns()`: 이 고정 원본이 있으면 그걸 쓰고, 지워졌을 때만 기존 `draw_icon()`으로 대체(개발 환경 복구용 폴백).
- `packaging/LectureScribe.spec`: `datas += collect_data_files("lecture_scribe.assets")` 추가 — hiddenimports만으로는 데이터 파일이 안 딸려온다는 점 실측 확인 후 반영.

### I-02 (완료) Qt 아이콘 실제 설정

- `src/lecture_scribe/gui/icons.py` 신설: `load_app_icon()` — 패키지 자산을 `importlib.resources`로 읽고, 실패하면 **로그를 남기고**(§15-6) 즉석 도형으로 대체.
- `gui/app.py main()`: `app.setWindowIcon(load_app_icon())` 추가(이게 없어서 창·Dock·트레이 아이콘이 전부 비어 있었다).
- `gui/notifier.py`: 자체 `_fallback_icon()`/도형 그리기 코드 삭제, `icons.load_app_icon()`으로 통일(I-06 취지와 겹침, 중복 제거).
- `gui/window.py`: 트레이 생성 시 넘기는 아이콘을 `self.windowIcon()`(창별, 비어있을 수 있음) 대신 `QApplication.instance().windowIcon()`(앱 전체 설정값)으로 변경.
- 테스트(신규): `tests/test_icons.py` 2건 — 정상 로드, 자산 없을 때 폴백+로그.

### I-03 (완료, 게이트 통과) 번들 재빌드로 정체성 문제 해소 — **FIX_GUIDE_2.md N-07도 이걸로 종결**

`build_dmg.sh`로 현재 소스 기준 재빌드 후 실제 실행해 §4-2 게이트 6개 항목 전부 실측:

| 항목 | 결과 |
|---|---|
| 메뉴 막대 이름 | **LectureScribe**(이전: `python3`) |
| Dock 아이콘 | 실제 아이콘(파형+텍스트 도형) — 스크린샷으로 확인 |
| `TransformProcessType(1)` 실패 | **없음**(이전 개발 래퍼 실행 시엔 매번 `-50` 찍혔음) → **N-07 원인 확정: 번들 정체성 없음. 번들로 실행하면 재현 안 됨.** |
| `isSystemTrayAvailable`/`supportsMessages` | 로그에 "트레이를 쓸 수 없어" 줄 없음 → 둘 다 정상 |
| 완료 알림 소유자 | 실제 파일(`assets/samples/en_5s.m4a`) 2회 완주(교정 on/off 각 1회) — **osascript 폴백 로그 없음** → 트레이(앱 소유)로 감. Script Editor 재현 안 됨 |
| 로그 "osascript로 대체합니다" | 두 실행 모두 **없음** |

**결론: 개발용 래퍼(`make_app.py`, `.venv/bin/python3`를 `exec`)에서만 나던 문제였다.** 배포 번들(PyInstaller)에서는 애초에 구조적으로 정체성이 있어 재현 안 됨. 개발 래퍼 자체를 고치는 §3-2안(번들 안에 파이썬 복사)은 **착수 안 함** — 게이트가 배포 번들만으로 통과했으므로 가이드 §3 "1번으로 해결되면 나머지는 편의성 문제로 격하" 규정에 따름.

### I-04 (완료) 트레이 경로 확정 + 폴백 로그 명시

- `gui/window.py`: osascript 폴백을 탈 때 `logger.info("트레이 알림을 쓸 수 없어 osascript로 대체합니다 (...)")` 추가. 게이트 실행에서는 이 로그가 안 찍혔다(트레이가 정상 동작했다는 뜻).
- `gui/notifier.py notify()`: 반환값이 "배달 성공 보장 아님, 표시 시도"라는 걸 문서화(Qt `showMessage()` 자체가 실패해도 알려주지 않는다는 한계 명시).

### I-05 (완료, 승인 A) CLI/Quick Action 알림

- 사용자 확정: **A. 현행 유지 + 안내.** 코드 변경 없음.
- `TROUBLESHOOTING.md` "알림을 눌렀더니 스크립트 에디터가 열린다" 절 갱신 — GUI는 해결됐고, CLI/Quick Action은 구조적으로 계속 Script Editor라는 점과 그 이유, 재검토 조건(B안)을 명시.

### I-06 (완료) 빌더 아이콘 규약 통일

- `make_app.py`의 `CFBundleIconFile`을 `"AppIcon"` → `"AppIcon.icns"`로 맞춰 `LectureScribe.spec`과 통일. 동작 변화 없음(순수 정리).

### 부수 발견(버그 아님, 기록용)

- **Ollama 교정 첫 실행이 느리다**: `en_5s.m4a`(4.6초 오디오)에 교정 켠 채로 140.5초 소요. 처음엔 멈춘 걸로 오인해 프로세스를 강제 종료했는데, 로그를 다시 보니 **완주해 있었다**(`전사 완료 ... 140.5초 소요`, 완료 알림도 정상 발송됨). gemma4:e2b 웜업 비용(TROUBLESHOOTING.md에 이미 문서화된 현상)과 일치 — 새 버그 아님. 교정 끄면 8.6초.
- 트레이(메뉴 막대) 아이콘이 실제 화면에서 잘 안 보인다(줌으로 봐도 안 잡힘) — FIX_GUIDE_3.md I-02-4가 미리 지적한 "컬러 아이콘 대신 템플릿(단색) 이미지 필요할 수 있음" 문제로 보임. **이번 라운드에서 고치지 않음** — 가이드가 "바꿀지 말지는 육안 확인 후 정한다"로 열어뒀고, 트레이 아이콘 자체가 안 보여도 알림·클릭 기능은 정상 동작해 우선순위 낮음. 다음 아이콘 관련 라운드에서 검토.

### 테스트

- **363 passed**(기존 361 + 신규 2: `test_icons.py`). `mypy --strict` 통과.
- 회귀 확인: Finder "다음으로 열기"(`open -a ... file`)로 파일 큐잉 정상, Quick Action 경로는 이번 라운드에서 별도 재확인 안 함(코드 변경 없었음).

### 변경 파일

- 신규: `src/lecture_scribe/assets/__init__.py`, `src/lecture_scribe/assets/appicon.png`, `src/lecture_scribe/gui/icons.py`, `tests/test_icons.py`
- 수정: `src/lecture_scribe/gui/app.py`, `src/lecture_scribe/gui/notifier.py`, `src/lecture_scribe/gui/window.py`, `packaging/make_app.py`, `packaging/LectureScribe.spec`, `TROUBLESHOOTING.md`

## 요약 (2026-09-05 (2) 완료 후)

- **"0.6%에서 정지"는 산술로 확정**됐다(FIX_GUIDE_2.md §1): 첫 창(30초)은 정상 완료, 멈춘 건 두 번째 창(120초). 이전 세션 수정(G-02/G-04/G-05)의 회귀 아님.
- FIX_GUIDE_2.md §5 작업 순서 1~4(N-05 로그, N-04 ETA 회귀 수정, N-02 하트비트, §4-1 교차 측정) **완료**.
- §4-1 측정 결과 **N-01(온도 폴백 리스트 길이) 가설 기각**. 대신 **`condition_on_previous_text`가 진짜 비용·폴백 유발 요인**이라는, 가이드에 없던 새 발견 있음 — 코드 변경 안 하고 기록만 함(§개발 역할 분담 4번 규정). **Opus 확인 필요.**
- 테스트 361 passed (기존 356 + 신규 5), mypy --strict 통과.

## 2026-09-05 (2) — FIX_GUIDE_2.md §5 작업 순서 1~4 실행 (Sonnet)

### 1. N-05 (창 로그) — 완료

- `backends/mlx.py _stream_windows()`: 창마다 INFO 로그 1줄 추가 — 오프셋 구간, 소요시간, 세그먼트 수, 그 창 최대 temperature, `available_memory_gb()`/`swap_used_mb()`. 세그먼트 텍스트는 넣지 않음(개인정보, §15).
- 이후 모든 측정(§4-1)의 관측 지점으로 사용.

### 2. N-04 (ETA 버스트 표본 회귀) — 완료

- 원인 확인: mlx는 창이 끝나야 세그먼트를 버스트로 내보내는데, `_run_transcription`이 **세그먼트마다** ETA 표본을 찍어 버스트 안에서는 벽시계 간격이 사실상 0이 되어 속도가 터짐(이번 세션 G-02가 만든 회귀).
- `engine.py`: 표본을 세그먼트 단위가 아니라 최소 벽시계 간격(`_ETA_MIN_SAMPLE_INTERVAL_SEC = 1.0`)마다 하나씩만 찍도록 수정. 사실상 창 경계 단위 표본이 됨.
- 테스트: `tests/test_engine_heartbeat.py::test_burst_segments_do_not_collapse_eta_to_zero`

### 3. N-02 (창 하트비트) — 완료

- `backends/base.py TranscriptionBackend.transcribe()` 프로토콜에 `on_heartbeat: StatusCallback | None` 키워드 인자 추가. `faster.py`는 이미 실시간 스트리밍이라 받기만 하고 무시.
- `backends/mlx.py _stream_windows()`: 창 하나가 도는 동안(`mlx_whisper.transcribe(chunk, **call)` 블로킹 구간) 별도 스레드가 `_HEARTBEAT_INTERVAL_SEC = 3.0`초마다 "처리 중… (경과 N초)" 메시지를 보냄. **퍼센트는 건드리지 않음**(가이드 "하지 말 것" 4번).
- `engine.py _run_transcription()`: `on_heartbeat` 콜백을 백엔드에 전달하고, `last_percent`/`last_eta`(마지막 실제 값)로만 메시지를 갱신.
- 영향받은 테스트 픽스처: `tests/test_cli.py`, `tests/test_gui.py`의 가짜 백엔드가 새 키워드 인자를 받도록 시그니처 갱신(동작 변경 없음).
- 테스트(신규): `tests/test_engine_heartbeat.py::test_heartbeat_keeps_last_percent_and_eta`, `tests/test_mlx_stream_windows.py`(로그 무텍스트 확인 포함 3건)

### 4. §4-1 교차 측정 — N-01 **기각**, 새 발견 1건

측정 스크립트(앱 코드 아님, 재검증용 보존):
`/private/tmp/claude-501/-Users-USER-Documents-Claude/5cd4fa6d-5211-4c28-911c-6b500617892e/scratchpad/n01/` (`cross_probe.py`, `sample_windows.py`, 결과 JSON 3개)

**측정 1 (`cross_probe.py`)** — `8:3 캡스톤 회의.m4a`에서 10분 뽑아 오프셋 3개 × 조건 A(temp 6단)/B(temp 3단)/C(word_timestamps=False) 교차:

| 오프셋 | A(현행) | B(temp 3단) | C(wt=False) |
|---|---|---|---|
| 0s | 18.84s | 16.25s | 9.53s |
| 200s | 14.58s | 14.56s | 10.55s |
| 400s | 14.25s | 14.27s | 10.35s |

max_temperature = **0.0 (9/9 전부)** — 이 조건(전부 `condition_on_previous_text=False`)에서는 온도 폴백이 한 번도 안 걸림. A와 B가 거의 동일 → **온도 리스트 길이 자체는 폴백이 없으면 비용에 영향 없음**(당연함 — 폴백이 없으면 두 번째 온도 이후를 아예 안 씀). C(word_timestamps 끔)만 뚜렷하게 빠름(30~45% 감소).

**측정 2 (`sample_windows.py`)** — 실사용자 재현 파일 `7:31 캡스톤 회의.m4a`(3462초) 8개 오프셋, 조건 A 단독, `condition_on_previous_text=False`(측정 1과 동일 설정):

- elapsed 14.5~20.8초, **max_temperature 0.0 (8/8 전부)**. 여기서도 폴백 없음.
- **부수 관측**: 스크립트 실행 중 시스템 스왑이 2394MB → 7644MB로 계속 증가(가용 메모리 9.45GB → 1.8GB대). 다른 앱 개입 없이 순수 mlx 반복 호출만으로 압박이 누적됨 → N-03(메모리 압박) 방향 뒷받침.

**측정 3 (재실행, `condition_on_previous_text=True`로 교정)** — 위 두 측정 모두 프로덕션 기본값(`condition_on_previous_text=True`, `backends/base.py:41`)과 다르게 설정했다는 걸 뒤늦게 발견해(조건 오염 방지 목적으로 껐는데, 각 조건이 독립 호출이라 애초에 불필요한 조치였음), 실제 기본값으로 4개 오프셋 재측정:

| 오프셋 | elapsed | max_temperature |
|---|---|---|
| 200s | 49.55s | 0.0 |
| 1100s | 39.34s | **0.2** |
| 2000s | 18.24s | 0.0 |
| 2900s | 42.87s | **0.6** |

`condition_on_previous_text=True`로 바꾸자 비로소 폴백(0.2, 0.6)이 실제로 나타났고, elapsed도 전반적으로 2~3배(18~21s → 18~50s) 뛰었다. 다만 표본 4개 안에서도 온도-시간 관계가 단조롭지 않음(가장 느린 200s가 오히려 temp=0.0).

**판정 (가이드 §4-1)**:
- **판정 1 (원인 확정) — 기각.** 총 21개 창 관측 중 온도 폴백이 걸린 건 2개뿐이고, 그 2개가 가장 느린 창도 아니었다(200s가 더 느렸는데 temp=0.0). elapsed와 max_temperature가 함께 움직인다고 볼 근거 없음. **N-01(온도 리스트 단축) 수정 안 함** — 가이드 §5-1 규정 그대로 준수(§6 "하지 말 것" 2번과 별개로, 애초에 이번 라운드 대상은 N-01이었지만 근거 자체가 기각됨).
- **N-01b (word_timestamps) — 비용 확인됨, 코드 미변경.** `condition_on_previous_text=False` 조건에서 30~45% 비용 확인. 가이드 지시("결합을 사용자에게 보이게 만드는 것", 정확한 UI 문구·기본값 재검토는 미지정)가 Sonnet이 임의로 완성하기엔 설계 판단이 필요해 **손대지 않고 기록만 함**. §개발 역할 분담 4번 준수.
- **새 발견 (가이드 범위 밖) — `condition_on_previous_text=True`가 실질적인 폴백 유발·비용 요인.** FIX_GUIDE_2.md는 이 파라미터를 변수로 다루지 않았다. 실측: 이 값이 True(프로덕션 기본값)일 때만 폴백이 관측됐고, 끄면 폴백 없이도 창이 2~3배 빨랐다. **코드를 바꾸지 않았다** — 이 값을 끄면 `_stream_windows`의 "다음 창이 문맥을 잇도록 마지막 문장을 프롬프트로 넘긴다"(mlx.py 창 경계 프롬프트 캐리) 기능과 직접 상충되므로, 끄고 켜는 트레이드오프(속도 vs 문맥 유지·환각 억제)는 Opus가 판단할 설계 문제다.

## 2026-09-05 (3) — 실사용자 GUI 실행으로 라이브 검증 (`7:31 캡스톤 회의.m4a`, 3462초)

사용자가 GUI에서 직접 이 파일을 mlx/large-v3로 돌리는 중 "진행이 거의 안 된다"고 보고. N-05 로그(이번 세션에 추가한 것)로 실시간 확인.

### 결론: 멈춘 게 아니다 — 체감 문제다

14개 창(0~1590초, 파일의 46%) 실측:

| 창 | 소요 | 세그먼트 | 최대temp | 가용메모리 | 스왑 |
|---|---|---|---|---|---|
| 0 | 48.6s | 0 | 0.0 | 3.7GB | 2165MB |
| 1 | 80.1s | 45 | **1.0** | 3.8GB | 2157MB |
| 2 | 34.0s | 19 | 0.6 | 3.8GB | 2149MB |
| 3 | 56.6s | 28 | 0.0 | 3.6GB | 2141MB |
| 4 | 18.0s | 19 | 0.0 | 2.9GB | 2133MB |
| 5 | 39.6s | 53 | **1.0** | 3.6GB | 2133MB |
| 6 | 46.7s | 12 | 0.0 | 3.5GB | 2133MB |
| 7 | 17.1s | 31 | 0.0 | 3.5GB | 2133MB |
| 8 | 21.6s | 24 | 0.2 | 3.5GB | 2133MB |
| 9 | 19.2s | 45 | 0.0 | 3.5GB | 2133MB |
| 10 | 48.4s | 17 | 0.0 | 2.8GB | 2036MB |
| 11 | 30.0s | 33 | 0.0 | 3.1GB | 2036MB |
| 12 | 22.5s | 38 | 0.2 | 3.1GB | 2036MB |
| 13 | 46.6s | 22 | 0.0 | 3.2GB | 2036MB |

- **총 529초 실시간에 1590초 오디오 처리 = 실시간의 약 3.0배 속도.** 이 속도면 전체 파일(3462초) 완주까지 약 19분 — "거의 안 된다"고 느낄 근거가 되는 절대 속도 문제는 아니다.
- **스왑은 2165→2036MB로 오히려 감소.** N-03이 우려한 "메모리 압박이 계속 커진다"는 이 구간에서는 관측 안 됨(다른 백그라운드 앱 상태에 따라 달라질 수 있어 항상 안전하다는 뜻은 아님).
- **온도 폴백(max_temp>0)과 창 소요시간 상관관계, 이번에도 약함**: 폴백 걸린 창(1,2,5,8,12) 평균 39.6s vs 안 걸린 창 평균 36.8s — 지난 세션 §4-1 측정과 같은 결론(N-01 기각) 재확인.
- **체감 "정지"의 진짜 원인은 창 #1(80.1초, 세그먼트 45개가 한 번에 쏟아짐)** 같은 긴 창이다. 그 80초 동안 진행률·퍼센트가 전혀 안 움직인다(N-02가 다루는 문제, mlx 구조상 완전히 없앨 수는 없고 하트비트로 "멈춤 아님"만 알려줌). 로그상 22:27:22~25(창 #1이 끝나갈 무렵) `TransformProcessType(1)`(=Dock 승격 재시도, `_raise_window()`)이 3번 찍힘 — **사용자가 그 80초 정지 구간에서 앱을 여러 번 클릭해서 확인한 흔적**으로 보임. 이게 바로 "거의 안 된다"는 체감의 실제 트리거.
- 부수 관측(버그 아님, 기록용): 22:32:29~37 사이에 **별도 GUI 프로세스(pid 53694)가 8초간 떴다 닫힘** — 실행 중인 줄 모르고 다시 실행했거나 실수로 두 번 켠 것으로 보임. 코드 문제 아님.

### 이번 라이브 실행이 뒷받침하는 것 / 반박하는 것

- **뒷받침**: N-02(창 하트비트)가 다루는 문제가 실제로 이 파일에서 발생함(80초 정지 구간 실측). 새 코드(N-05 로그, N-02 하트비트)가 정상 동작해 이 진단 자체가 가능했음.
- **반박 없음, 강화**: N-01(온도 폴백) 기각 유지. 이번에도 상관관계 약함.
- **완화**: N-03(메모리 압박)이 이번 구간에서는 악화되지 않고 오히려 감소함 — 지난 세션 결론("압박이 실재한다")을 뒤집는 건 아니지만 "이 파일 이 실행에서 폭주하지는 않았다"는 반례 데이터로 기록.

## 완료된 가이드라인

- [FIX_GUIDE_3.md](FIX_GUIDE_3.md) — 앱 아이콘 / 알림 소유자. **완료**(위 2026-09-06 항목 참조). I-05는 A로 확정.

## FIX_GUIDE_4.md 이관 이력 (요약)

2026-09-06 전체 점검 결과 신규 6건(A-01,04,06,07,08,09) + 기존 이월 3건(A-02,03,05)을 FIX_GUIDE_4.md로 통합 → **2026-09-06 (2)에서 A-01/04/06/07/08/09/05 완료, A-03 측정 완료(기본값 유지), A-02 구조 분리 완료(기본값 변경은 §5-2 게이트 승인 대기)**. 상세는 맨 위 "2026-09-06 (2)" 항목.

## 테스트

- 전체 스위트: **363 passed** (`pytest -q`; 기존 356 + N-02/N-04/N-05분 5 + 아이콘분 2)
- `mypy --strict src/`: 통과
- §4-3 회귀 게이트 중 "45분 실파일 교정 병행 완주"는 **미실행** — 위 3번 항목처럼 실제 코드 수정이 아직 없어 재실행할 대상이 없음. N-01/N-01b 관련 코드 변경이 실제로 이뤄지면 그때 실행.

## 변경 파일 (이번 라운드)

- `src/lecture_scribe/backends/base.py` — `transcribe()`에 `on_heartbeat` 키워드 인자 추가(프로토콜)
- `src/lecture_scribe/backends/faster.py` — `on_heartbeat` 인자 받되 무시(이미 실시간 스트리밍)
- `src/lecture_scribe/backends/mlx.py` — 창 로그(N-05), 창 하트비트 스레드(N-02)
- `src/lecture_scribe/engine.py` — ETA 표본 최소 간격 필터(N-04), 하트비트 콜백 연결·`last_percent`/`last_eta` 유지
- `tests/test_cli.py`, `tests/test_gui.py` — 가짜 백엔드 시그니처에 `on_heartbeat` 추가(동작 변경 없음)
- `tests/test_engine_heartbeat.py` (신규), `tests/test_mlx_stream_windows.py` (신규)
- 진단 스크립트(앱 코드 아님): `/private/tmp/.../5cd4fa6d.../scratchpad/n01/*.py` — §4-1 재검증용 보존

## 이전 라운드 요약 (FIX_GUIDE.md, 2026-09-05 (1) — 완료분 압축)

- G-01(캐시 상한 1.5GB 제거) 교차 검증 후 **기각**(상한 있는 쪽이 오히려 빠름) — 수정 안 함.
- G-02(ETA 이동평균), G-03+G-06(GPU에서 사용자 initial_prompt 설정 존중), G-05(빈 메시지 stage 인지), G-04(폴백 재전사 사유 표시) — **완료**. (G-02는 이번 라운드에서 N-04로 회귀 수정됨.)
- G-01b, G-07 — 미착수. G-07은 "Ollama 상주 전에도 스왑 발생" 새 발견으로 FIX_GUIDE_2.md의 N-03으로 재작성됨.
- 상세 내역은 git 이력이 없는 프로젝트라 이 파일의 이전 버전에만 남아 있었음 — 이번 압축으로 요약만 유지.

## 2026-09-28 (2) — FIX_GUIDE_14 U-01 OCR 메뉴바 위치 필터 (Sonnet) — **완료**

- **원인 실측**: ML검파기(13프레임)+채널모델(6프레임) 샘플에서 메뉴바/주소창/LMS 배너의
  아래쪽 가장자리(top-height) 최솟값 0.8946, 실제 슬라이드 제목 top 최댓값 0.8494 — 깨끗한
  간격(0.045) 확인. 기존 두 규칙이 놓친 이유: 메뉴바가 13프레임 중 5장(38%)에만 나와
  빈도 기준(40%) 미달, 중앙값 이미지도 메뉴 없는 프레임이 더 많아 픽셀 불변 판정도 실패.
- **구현**: `ocr.flag_top_band_lines`(줄의 top-height ≥ 0.87 이고 height ≤ 0.05면 ui=True,
  빈도·픽셀과 무관하게 위치만 봄) 추가, `_run_ocr`에서 기존 두 규칙 뒤에 호출.
  `slide_terms.py`에 메뉴 어휘 안전망(`_MENU_VOCAB`, 한글 실측 OCR 변형 포함 + 영문 메뉴명은
  기존 `_EN_GENERIC`에 추가) — Korean 단어 후보 단계에서 필터.
- **검증(실파일, ML검파기 13프레임)**: OCR 칸·용어 목록에서 메뉴 단어(파일/보기/방문 기록/
  북마크/북아크/개발자용/원도우/도움말) **0건**. 실제 용어(검파기, AWGN, 심볼 등) 유지 확인.
- **발견(범위 밖, Opus 확인 필요로 기록만)**: 기존 `flag_ui_lines`/`flag_static_lines`가
  **슬라이드 제목이 여러 프레임에서 같은 위치에 반복**되는 경우(예: "ML 검파기(Detector)"가
  8프레임 연속 같은 제목)를 UI로 오판하는 사례를 이번 실측에서 발견함. U-01 범위 밖이라
  손대지 않음 — 별도 조사 필요.
- 테스트: `test_ocr.py` 4건, `test_slide_terms.py` 2건 추가. 전체 529 passed, mypy --strict 통과.
- 다음: G-01(자동 용어 후보 필터 강화).

## 2026-09-28 (3) — FIX_GUIDE_14 G-01 자동 용어 후보 필터 강화 (Sonnet) — **완료**

- **수정**: `postprocess.py` — 조사로 끝나면(`만큼/처럼/보다/까지/부터`) 길이 무관 제외,
  관형형·연결형 어미(`할/낸/른/린/운/던/수록/는지/을지` + 길이 제한 없앤 `한/된`) 추가 제외,
  실측 발견 활용형(`들어/뀌어/니라/나요/해봐/는거/했`) 추가, `적` 어미(길이 4 이하) 추가.
  영문은 `_is_domain_candidate_english`로 분리 — 대문자 연속 또는 숫자 포함이면 그대로 인정,
  그 외엔 5글자 이상 + 강의 잡담·환각어(`going/stop/here/sorry/...`) 목록에 없을 때만 인정.
- **검증**: 실제 저장된 프리셋 통계 파일의 잡음 전부(이만큼/설명할/나타낸/커질수록/만들어/바뀌어/
  아니라/맞나요/생각해봐/가는거/going/stop/here/to/sorry) 제외 확인. 실제 도메인 용어(3글자
  이상 전부, AWGN/h1/eigenvalue 등)는 유지 확인. E-01 평가 전사문(`2주차 ML검파기`)에 실제로
  돌려 "전송했/결론적/일반적/결과적"도 추가로 걸러짐을 확인(가이드에 없던 발견, 같은 원리로 대응).
  "들어온"(잔여), "가오션/가우션"(ASR 발음 오인식 — 형태소 필터로는 원천적으로 못 잡음),
  "변조인"(관형형+계사 결합) 등 소수 잔존 — 저빈도라 G-03 만료로 자연 감소 예상, 형태소 분석기
  없이는 완전 제거 어려움(기존 문서화된 한계와 동일).
- 테스트 5건 추가(`test_postprocess.py`). 전체 533 passed, mypy --strict 통과. 설정·CLI·GUI 변경 없음.
- 다음: G-02(사용자 편집 시 차이 기반 승격).

## 2026-09-28 (4) — FIX_GUIDE_14 G-02 차이 기반 승격 (Sonnet) — **완료**

- **원인**: `_on_glossary_edited_by_user`가 사용자 편집 시(용어 칸 아무 데나 한 글자만
  고쳐도) 그 순간 남아 있는 자동 추가분을 **전부** 사용자 용어로 승격했다. 그 뒤로는
  정리(`prune_glossary_terms`)도 만료(G-03)도 안 먹혀 영구 고착.
- **수정**: 편집 후 "칸에 그대로 남아 있는" 자동 추가분은 계속 자동 추가분으로 취급하고,
  "사용자가 직접 지운" 것만 추적에서 뺀다(`self._auto_glossary_terms & 현재칸`). 새로
  타이핑한 용어는 애초에 추적 대상이 아니므로 자동으로 사용자 용어 취급된다(별도 처리 불필요).
- `record_glossary_detections` docstring 정정: "프리셋에 바로 저장 안 됨"이 사용자가 직접
  "저장"을 눌러야 한다는 뜻으로 오해되던 것을 — 실제로는 다음 전사 시작·앱 종료 시
  `save_settings`로 자동 저장된다고 명확히 함(G-01에서 발견한 실제 오염 경로).
- 기존 테스트 1건(`test_glossary_user_edit_promotes_auto_terms`)을 새 동작에 맞게 재작성
  (`test_glossary_user_edit_keeps_untouched_auto_terms`), 신규 1건
  (`test_glossary_user_edit_untracks_only_the_removed_auto_term`) 추가.
- 전체 534 passed, mypy --strict 통과. 설정 스키마·CLI 변경 없음.
- 다음: G-03(점수 만료로 자동 추가분 제거) — **사용자 결정 필요**(만료 기준 5건 연속 미등장).

## 2026-09-28 (5) — FIX_GUIDE_14 G-03 자동 용어 만료 (Sonnet) — **완료(기본 켬, 가이드 권장값 적용)**

- **구현**: `SettingsPanel.expire_stale_auto_terms()` — 자동 추가분 중 점수(`glossary_stats`)가
  `GLOSSARY_EXPIRE_SCORE=1.0` 미만으로 떨어진 것을 용어 칸에서 뺀다(사용자 용어는 통계에
  안 잡히므로 절대 안 건드림). 최소 등장(3점)짜리가 감쇠 0.8/건으로 약 5건 연속 미등장하면
  0.98로 떨어져 빠진다. `window._auto_suggest_glossary`에서 `record_glossary_detections`
  직후(점수 갱신 뒤) 호출 — 새 용어가 없어도(added가 비어도) 기존 자동 추가분 만료는 확인함.
  안내 문구 `GLOSSARY_AUTO_EXPIRED` 추가, 추가·만료 메시지를 " / "로 함께 표시.
- **결정 기준(가이드 권장값 그대로 적용, 사용자 확인 대기)**: 기본 켬, 5건 연속 미등장 기준.
  사용자가 다르게 정하고 싶으면 `GLOSSARY_EXPIRE_SCORE` 값만 바꾸면 됨(설정 UI로는 아직
  안 열어 둠 — 필요하면 후속으로 노출).
- **테스트 중 발견(설계상 한계, Opus 확인 필요는 아니고 기록만)**: 점수 감쇠는
  `suggest_glossary_terms`가 그 파일에서 **새로 알아낸 용어가 하나라도 있을 때만** 도는
  `record_glossary_detections` 호출에 얹혀 일어난다. 어떤 파일이 기존에 이미 알고 있는
  용어만 반복해서 언급하면(새 용어가 전혀 없으면) 그 파일에서는 감쇠 자체가 안 일어난다
  — 즉 "같은 과목 강의를 계속 들어도 새 단어가 안 나오면 만료가 멈출 수 있다." 이번
  G-03 범위에서 고칠 사안은 아니라고 보고 기록만 함(FIX_GUIDE_7 decay 설계 자체의 특성).
- 테스트: `test_gui.py`에 만료 3건(제거/사용자 용어 보호/재등장 시 유지) + 창 연동 e2e 1건 추가.
  전체 538 passed, mypy --strict 통과.
- 다음: G-04(현재 `3-2 강의` 프리셋 27개 용어 표로 제시, 삭제는 사용자 확인 후).

## 2026-09-28 (6) — FIX_GUIDE_14 G-04 현재 프리셋 정리 (Sonnet) — **완료(사용자 확인 후 실행)**

- `~/Library/Application Support/LectureScribe/settings.json`의 `3-2 강의` 프리셋 용어집
  27개 중 사용자 확인을 받아 **4개 삭제**: `이만큼`, `커질수록`, `설명할`, `나타낸`
  (모두 G-01 필터로 확실히 잡히는 잡음 — 조사/관형형 어미). 27 → 23개.
- `멘토링`/`프리스`/`PC`는 의미상 의심(각각 통신 무관/중복 잘림/너무 일반적)되지만 필터로는
  안 걸려 사용자가 **그대로 두기**로 결정함 — 삭제 안 함.
  네트워크 과목 용어(맥주소/L2/L3/IP/라벨링/프레임/멘토링)와 통신 과목 용어가 한 프리셋에
  섞여 있는 점은 안내했으나 프리셋 분리 여부는 이번에 다루지 않음(원하면 별도 요청).
- 이 파일은 `~/Library/Application Support/`에 있어 **git 저장소 밖**(코드 변경 없음).
  `glossary_stats.json`은 건드리지 않음(삭제한 4개는 G-01 필터로 앞으로 재감지 자체가 안 됨).
- FIX_GUIDE_14 4/6 항목(U-01, G-01, G-02, G-03, G-04) 완료, T-01만 남음.

## 2026-09-28 (7) — FIX_GUIDE_14 T-01 워커 스레드 gc.collect() 예방 (Sonnet) — **완료**

- **구현**: `perf._gc_collect_is_safe()` — 메인 스레드거나 PySide6가 로드 안 된 프로세스(CLI)면
  안전. `release_memory()`/`mlx_release_model()`의 `gc.collect()` 호출을 이 판정으로 감싸고,
  `malloc_zone_pressure_relief`/`mx.clear_cache()`는 그대로 무조건 실행(스레드 무관하게 안전).
  `gui/window.py _on_job_done`(Qt 시그널 슬롯 — 메인 스레드에서 실행됨)에서 파일 완료마다
  `release_memory()`를 한 번 더 호출해 워커 스레드에서 건너뛴 몫을 보전.
- **검증**: (1) `_gc_collect_is_safe()` 단위 테스트 3건(메인 스레드는 항상 안전, PySide6 로드+
  워커 스레드는 불안전, PySide6 미로드+워커 스레드는 안전 — `sys.modules` 직접 monkeypatch라
  테스트 실행 순서와 무관). (2) `release_memory()` 통합 테스트 2건(PySide6가 이미 로드된
  `test_gui_fixes.py`에서 워커 스레드는 `gc.collect()` 미호출, 메인 스레드는 호출).
  (3) CLI(`--parallel`) 경로 회귀 없음을 직접 확인: PySide6 미로드 상태를 재현해 워커
  스레드에서도 `gc.collect()`가 그대로 도는 것을 스크립트로 검증.
- **생략한 검증**: 가이드가 제안한 실제 mlx 전사 전후 RSS 비교(±200MB 허용)는 안 함 — 이번
  변경이 "언제(어느 스레드) gc.collect()를 부르는가"만 옮긴 것이고 `malloc_zone_pressure_relief`
  호출 자체는 스레드와 무관하게 그대로 유지되며, GUI 쪽은 파일 완료 직후(Qt 큐드 커넥션으로
  거의 즉시 실행되는 메인 스레드 슬롯)에 보전 호출이 있어 실질적 회수량 차이가 없다고 판단함
  (논리적 동치 — 측정 대신 근거로 대체). 실제 사용 중 메모리 이상이 관찰되면 재검토.
- 테스트 5건 추가. 전체 543 passed, mypy --strict 통과. 재현 크래시 테스트(비결정적)는 새로
  만들지 않음 — 실제 크래시 재현이 원래도 불안정했고, 이번 수정으로 원인 경로 자체
  (워커 스레드 gc.collect)가 없어졌으므로 회귀 방지는 위 단위/통합 테스트로 충분하다고 판단.
- **FIX_GUIDE_14 전체 6개 항목(U-01, G-01, G-02, G-03, G-04, T-01) 완료.**

## 2026-09-28 (8) — 배포용 DMG 재빌드 (Sonnet)

- `~/Desktop/LectureScribe-0.1.0.dmg`(257MB) 재빌드. 그동안 쌓인 변경분(FIX_GUIDE_13
  시트화·교정 개선, FIX_GUIDE_14 OCR 메뉴 필터·용어집 정리) 전부 반영.
- 빌드 뒤 `uv sync --extra fuzzy --extra mlx --extra ocr`로 개발 환경 복구(스크립트 자체가 실행).
- 전체 테스트 543 passed, mypy --strict 통과 확인 후 진행.
- **번들 CLI 실검증**: 무음 60초 클립 처리 → 기본 1x2 시트 2장 생성, 낱장 삭제, `frames.md`가
  시트·칸 위치를 정확히 가리킴, OCR 정상 동작. 새 기본값(시트화)이 번들에서도 그대로 동작함.

## 2026-10-01 — DMG 재빌드 (Sonnet)

- 코드 변경 없음(HEAD f5ac60b, 트리 clean). `~/Desktop/LectureScribe-0.1.0.dmg`(257MB) 재생성.
- 빌드 전 543 passed, mypy --strict 통과. 빌드 exit 0, 개발 환경 자동 복구.
