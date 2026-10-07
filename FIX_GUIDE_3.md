# FIX_GUIDE_3.md — 앱 아이콘 / 알림 소유자(Script Editor) 수정 가이드라인

작성: 2026-09-05 / 작성자 단계: **Opus(계획)** / 실행 단계: **Sonnet**
관련 문서: [FIX_GUIDE_2.md](FIX_GUIDE_2.md)(진행률·스톨), [STATUS.md](STATUS.md)

이 문서는 **수정 방향만** 기술한다. 실제 수정 코드는 포함하지 않는다.
문서에 없는 설계 변경이 필요하면 직접 바꾸지 말고 이슈로 기록한 뒤 Opus 단계로 되돌린다.
(CLAUDE.md §개발 역할 분담)

---

## 1. 증상

1. **최신 버전 앱에 아이콘이 제대로 안 붙는다.** Dock·메뉴 막대에 `python3`와 파이썬 기본 아이콘이 뜬다.
2. **알림이 "스크립트 편집기(Script Editor)" 소유로 뜬다.** 눌러도 앱이 아니라 스크립트 편집기가 열린다.

관측 근거(이번 세션 실측):

- 사용자 화면 캡처에서 메뉴 막대 앱 이름이 **`python3`**.
- 실행 중 GUI 프로세스: `.venv/bin/python3 -m lecture_scribe.gui.app` (pid 53324).
- 앱 로그: `perf: TransformProcessType(1) 실패: -50` — Dock 승격(`show_in_dock()`) 실패.
- 앱 로그(테스트 실행분): `시스템 트레이를 쓸 수 없어 알림은 osascript로 대체합니다`.
  단, **이번 실사용 GUI 실행(22:15:09 이후)에는 이 줄이 없다** → 트레이 객체 자체는 만들어졌다.
  즉 osascript로 빠지는 경로는 `_tray is None`이 아니라 **`QSystemTrayIcon.supportsMessages()`가 False**인 쪽이다(notifier.py:85).

---

## 2. 원인 (한 뿌리에서 갈라진 두 증상)

### 2-1. 실행 중인 프로세스가 **번들 정체성(bundle identity)을 갖고 있지 않다** — 두 증상의 공통 원인

개발용 앱은 `packaging/make_app.py`가 만드는 **껍데기 래퍼**다. 런처 스크립트(make_app.py:38~55)의 마지막 줄이:

```
exec "$PYTHON" -m lecture_scribe.gui.app "$@"
```

`$PYTHON`은 `<프로젝트>/.venv/bin/python3` — **번들 밖 경로**다. `exec` 순간 실행 이미지가 번들 밖 바이너리로 바뀌므로, macOS 입장에서 화면에 뜬 앱은 `LectureScribe.app`이 아니라 **파이썬 프레임워크 번들**이 된다. 그 결과:

- Dock/메뉴 막대 이름과 아이콘 = 파이썬 것 (`Info.plist`의 `CFBundleIconFile=AppIcon`은 실행되지 않는 껍데기 쪽 값이라 무시된다)
- `TransformProcessType(1)`(= `show_in_dock()`, perf.py:102)이 `paramErr(-50)`으로 실패
- 알림 권한·소유자가 앱 번들에 귀속되지 않아 **Qt의 트레이 메시지가 지원 불가로 떨어지고**, notifier.py:85 조건에서 False → window.py:666~670이 `notify_completion()`(notify.py, `/usr/bin/osascript display notification`)으로 폴백 → **알림 소유자가 스크립트 편집기**

배포용 PyInstaller 번들(`packaging/LectureScribe.spec`, `build_dmg.sh`)은 `Contents/MacOS/LectureScribe`가 진짜 실행 파일이라 이 문제가 없어야 한다. 다만 **현재 `packaging/dist/LectureScribe.app`은 2026-09-04 11:36 빌드**로, 이번 세션(engine/mlx/backends 수정) 이전 코드다. "최신 버전"이라고 부를 수 있는 번들이 지금 없다.

### 2-2. Qt 아이콘을 코드가 한 번도 설정하지 않는다 — 번들이어도 메뉴 막대 아이콘은 비어 있다

- `gui/app.py main()`은 `setApplicationName` / `setApplicationDisplayName`만 부르고 **`app.setWindowIcon(...)`을 호출하지 않는다.**
- 그래서 `gui/window.py:159`가 넘기는 `self.windowIcon()`은 **빈 QIcon**이다.
- `gui/notifier.py:66` `QSystemTrayIcon(icon or _fallback_icon(), self)` — **여기가 함정이다.** PySide6의 `QIcon`은 `__bool__`을 정의하지 않으므로 **빈 QIcon도 파이썬에서는 truthy**다. 즉 `or` 폴백이 절대 동작하지 않고 **빈 아이콘이 그대로 트레이에 설정**된다(메뉴 막대 아이콘이 보이지 않거나 빈 칸).
  → 이 truthiness 동작은 **Sonnet이 먼저 한 줄로 실측 확인**할 것(§4-1 1번). 추정으로 고치지 말 것.
- 번들에는 `.icns`가 있지만(`Contents/Resources/AppIcon.icns`), **파이썬 코드가 읽을 수 있는 아이콘 자산이 패키지 안에 없다.** 소스 실행 경로에서는 참조할 파일 자체가 없다.

### 2-3. 아이콘 원본이 "코드로 그린 임시 그림"이다

`make_app.py draw_icon()`이 Qt로 즉석에서 그린 도형(그라디언트 사각형 + 파형 + 3줄)을 `sips`/`iconutil`로 `.icns`를 만든다. `build_dmg.sh`도 같은 함수를 호출해 `packaging/AppIcon.icns`를 만든 뒤 PyInstaller에 넘긴다. 즉 **두 빌더가 같은 임시 그림을 공유**한다. "아이콘을 제대로 씌운다"는 요구를 만족하려면 원본을 **파일로 고정**해야 한다(아래 I-01).

### 2-4. CLI/Quick Action 경로는 구조적으로 osascript다

`notify.py notify()`는 `/usr/bin/osascript -e 'display notification …'`을 직접 실행한다. **osascript로 낸 알림은 항상 스크립트 편집기 소유**다(사용자 클릭 시 스크립트 편집기가 열림). 이건 코드 품질 문제가 아니라 osascript의 성질이다. GUI는 트레이 경로로 피할 수 있지만, **Qt가 없는 CLI/Quick Action 경로는 대안을 정해야 한다**(I-04, 승인 필요).

---

## 3. 이슈 목록

우선순위: **P0** 사용자가 요구한 두 증상의 직접 원인 / **P1** 정확도·일관성 / **P2** 정리

### I-01 (P0) 아이콘 원본을 파일로 고정하고, 런타임·빌드가 같은 원본을 쓴다

- **원인**: §2-3. 원본이 코드 안 도형이라 "제대로 된 아이콘"을 넣을 자리가 없고, 런타임(Qt)에서 쓸 수 있는 자산도 없다.
- **수정 방향**:
  1. **아이콘 원본 1개를 파일로 둔다.** 1024×1024 PNG(투명 배경, macOS 아이콘 여백 규칙 준수). 위치는 **패키지 안**(예: `src/lecture_scribe/assets/appicon.png`) — `importlib.resources`로 읽어야 소스 실행·PyInstaller 번들 양쪽에서 같은 코드로 접근된다. `assets/`(프로젝트 루트)에 두면 휠·번들에 안 들어간다.
  2. `make_app.py draw_icon()`은 **원본 PNG가 있으면 그걸 쓰고, 없을 때만 지금처럼 그린다**(개발 환경이 깨지지 않게 폴백 유지). `make_icns()`의 `sips`/`iconutil` 파이프라인은 그대로 재사용한다.
  3. `LectureScribe.spec`의 `datas`에 이 PNG를 추가해 번들 안에서도 읽히게 한다. `.icns` 경로(BUNDLE `icon=`)는 지금 구조 유지.
  4. **그림 자체(디자인)는 이 문서가 정하지 않는다.** 사용자가 원본 PNG를 주면 그걸 쓰고, 없으면 현재 draw_icon 결과를 PNG로 한 번 내보내 원본으로 고정한 뒤 나중에 교체 가능하게 한다. **Sonnet이 새 디자인을 임의로 그리지 말 것.**
- **영향 범위**: `packaging/make_app.py`, `packaging/LectureScribe.spec`, 새 자산 파일, `pyproject.toml`(hatch가 패키지 데이터를 포함하는지 확인 필요).

### I-02 (P0) Qt 아이콘을 실제로 설정한다 (창·메뉴 막대·알림)

- **원인**: §2-2. `setWindowIcon` 미호출 + `icon or _fallback_icon()` 폴백이 빈 QIcon에서 동작하지 않음.
- **수정 방향**:
  1. `gui/app.py main()`에서 I-01의 자산으로 **`app.setWindowIcon(QIcon(...))`**을 호출한다. 자산이 없으면 지금처럼 `_fallback_icon()`으로 내려가되 **로그로 남긴다**(조용히 넘어가지 않는다 — §15-6).
  2. `gui/window.py:159`가 넘기는 값을 `self.windowIcon()` 대신 **`QApplication.windowIcon()`** 기준으로 바꾼다(창별 아이콘은 macOS에서 비어 있을 수 있다).
  3. `gui/notifier.py:66`의 `icon or _fallback_icon()`을 **`isNull()` 기준 판정**으로 바꾼다. `or`는 QIcon에서 신뢰할 수 없다(§2-2).
  4. 트레이 아이콘은 메뉴 막대용이므로 **템플릿 이미지(단색 실루엣)** 규칙을 검토한다. 컬러 아이콘을 그대로 쓰면 다크/라이트 모드에서 지저분해진다. **바꿀지 말지는 §4-1 3번 육안 확인 결과로 정한다.**
- **영향 범위**: `gui/app.py`, `gui/window.py`, `gui/notifier.py`, 관련 테스트.

### I-03 (P0) 실행 프로세스가 번들 정체성을 갖게 한다 — "python3" 이름·아이콘·알림 소유자 문제의 뿌리

- **원인**: §2-1. 개발용 래퍼가 번들 밖 `python3`를 `exec`한다.
- **수정 방향** (순서대로 시도, 각 단계는 §4-2 측정으로 통과 여부 판정):
  1. **배포 번들을 최신 소스로 다시 빌드한다**(`packaging/build_dmg.sh`). PyInstaller 번들은 `Contents/MacOS/LectureScribe`가 실제 실행 파일이라 정체성 문제가 원래 없어야 한다. **먼저 이걸로 두 증상이 사라지는지 확인**한다. 사라지면 이 항목의 나머지는 "개발용 래퍼 편의성" 문제로 격하된다.
  2. 개발용 래퍼(`make_app.py`)를 계속 쓰려면, **번들 안 경로의 실행 파일로 파이썬을 실행**해야 한다. 방향: `Contents/MacOS/` 안에 venv 파이썬 바이너리의 **복사본**을 두고 그것을 `exec`한다(심볼릭 링크는 정체성이 유지되지 않을 수 있으므로 **복사/링크 중 무엇이 통하는지 실측으로 결정**).
  3. 2가 안 되면 개발용 래퍼는 **정체성 없이 쓰는 도구**로 문서화하고(README/TROUBLESHOOTING), 아이콘·알림 검증은 항상 배포 번들에서 한다. **이 경우 코드로 억지 우회를 만들지 말 것.**
- **영향 범위**: `packaging/make_app.py`(런처 스크립트), `packaging/build_dmg.sh` 재실행, README/TROUBLESHOOTING 문구.
- **주의**: FIX_GUIDE_2.md **N-07**(Dock 승격 `TransformProcessType(1)` 실패)이 이 항목과 같은 뿌리다. **N-07은 여기서 함께 판정하고, 별도로 손대지 않는다.**

### I-04 (P1) GUI 알림을 트레이 경로로 확정하고, osascript 폴백을 정직하게 만든다

- **원인**: §2-1 / §2-4. `AppNotifier.notify()`(notifier.py:84~91)는 `supportsMessages()`만 보고 **True를 돌려준다 — 실제 배달 성공 여부를 모른다.** 반대로 지원 불가 판정이 나면 window.py:666~670이 osascript로 내려가 스크립트 편집기 알림이 뜬다.
- **수정 방향**:
  1. I-03으로 번들 정체성이 생긴 뒤 **`isSystemTrayAvailable()` / `supportsMessages()` / 실제 배달 여부를 다시 측정**한다(§4-2). 트레이 경로가 동작하면 **GUI에서는 osascript 폴백을 타지 않는 것이 정상**이 된다.
  2. 폴백을 없애지는 말되(트레이가 없는 환경도 있다), **폴백을 탈 때 로그로 명시**한다: "트레이 알림 불가 → osascript 폴백(알림 소유자가 스크립트 편집기가 됩니다)". 지금은 사용자가 왜 스크립트 편집기가 열리는지 알 방법이 없다.
  3. `notify()`의 반환값 의미를 문서화한다("표시 시도함"이지 "배달 성공"이 아니다). 배달 성공을 알 방법이 없으면 **없다고 적는다.** 없는 보증을 만들지 말 것.
- **영향 범위**: `gui/notifier.py`, `gui/window.py`(폴백 분기), 문자열, 테스트.

### I-05 (P1/승인 필요) CLI·Quick Action 알림의 소유자 문제

- **제약**: `osascript`로 낸 알림은 **항상** 스크립트 편집기 소유다. Qt가 없는 CLI 경로에서는 이걸 코드 정리로 피할 수 없다.
- **선택지(사용자 승인 후 하나 고른다. Sonnet이 임의 선택 금지)**:
  - **A. 현행 유지 + 안내.** CLI/Quick Action 알림은 스크립트 편집기 소유로 남고, 그 사실을 README/TROUBLESHOOTING에 적는다. 코드 변경 없음. 비용 0.
  - **B. 번들에 위임.** 번들이 설치돼 있으면 CLI가 `/usr/bin/open -b com.local.lecturescribe --args --notify …` 로 알림 전용 모드를 깨워 앱 소유로 띄운다. 새 의존성 없음. 대신 `entry_app.py`에 알림 전용 모드가 필요하고, Launch Services 등록/미설치 상황 폴백을 설계해야 한다. **중간 규모 변경.**
  - **C. PyObjC + `UNUserNotificationCenter`.** 가장 정석이지만 **새 의존성**이라 CLAUDE.md §15-4에 따라 승인이 필요하고, 번들 정체성 + 서명이 있어야 동작한다(현재 ad-hoc 서명).
- **권고**: 먼저 **A로 두고**, I-03·I-04 결과로 GUI 쪽이 깨끗해진 뒤에 B를 검토한다. Quick Action 사용 빈도가 낮다면 B의 복잡도를 살 이유가 약하다.
- **영향 범위**: 선택지에 따라 다름. A는 문서만.

### I-06 (P2) 빌더가 둘인데 아이콘 규약이 다르다

- `make_app.py`는 `CFBundleIconFile = "AppIcon"`(확장자 없음), `LectureScribe.spec`은 `AppIcon.icns`. 둘 다 macOS에서 동작하지만 규약이 갈린다.
- **수정 방향**: I-01을 하면서 **두 빌더가 같은 키·같은 파일명을 쓰도록 통일**한다. 동작 변화는 없어야 한다(순수 정리).

---

## 4. 검증 절차 (Sonnet 실행)

### 4-1. 코드 수정 **전** 확인할 사실 3가지 (추정 금지)

1. **QIcon truthiness**: 빈 `QIcon()`이 파이썬 `or`에서 truthy인지 한 줄로 확인한다. truthy면 §2-2 판정 확정, falsy면 I-02-3은 불필요하므로 **하지 않는다.**
2. **현재 트레이 상태**: 소스 실행 상태에서 `QSystemTrayIcon.isSystemTrayAvailable()` / `supportsMessages()` 값을 로그로 찍어 확인한다. 실사용 로그에 "트레이를 쓸 수 없어" 줄이 없었다는 §1 관측과 맞는지 대조한다.
3. **아이콘 자산 유무**: 패키지 안에 런타임이 읽을 아이콘 파일이 실제로 없는지 확인한다(있으면 I-01-1의 범위가 줄어든다).

### 4-2. I-03 판정 게이트 (아이콘·알림 수정의 전제)

`build_dmg.sh`로 **현재 소스 기준 번들을 새로 빌드**한 뒤, 그 번들을 실행해 아래를 표로 기록한다.

| 확인 항목 | 통과 기준 |
|---|---|
| 메뉴 막대 앱 이름 | `python3`가 아니라 `LectureScribe` |
| Dock 아이콘 | 파이썬 기본 아이콘이 아님 |
| `TransformProcessType(1)` | 로그에 `실패: -50`이 없음 (FIX_GUIDE_2.md N-07 동시 판정) |
| `isSystemTrayAvailable()` / `supportsMessages()` | 둘 다 True |
| 완료 알림 소유자 | 알림 배너에 앱 이름이 뜨고, 눌렀을 때 **스크립트 편집기가 아니라** LectureScribe 창이 올라옴 |
| 로그 | `osascript로 대체합니다` 줄이 **없음** |

- 이 표가 전부 통과하면 **I-03은 "배포 번들을 쓴다"로 종료**하고, 개발용 래퍼(2단계)는 편의성 항목으로 낮춘다.
- 하나라도 실패하면 실패 항목만 들고 **Opus 단계로 되돌린다.** 임의 우회 금지.

### 4-3. 수정 후 회귀 게이트

| 항목 | 기준 |
|---|---|
| 아이콘 | 소스 실행/번들 실행 **양쪽에서** 창·메뉴 막대 아이콘이 기본 도형이 아닌 실제 아이콘 |
| 메뉴 막대 아이콘 가시성 | 다크·라이트 모드 **둘 다** 육안 확인(I-02-4 판단 근거) |
| 알림 | 번들에서 완료 알림이 앱 소유로 뜨고 클릭 시 창이 올라옴 |
| 폴백 로그 | 트레이 불가 환경(테스트 등)에서 폴백 사유가 로그에 남음 |
| 기존 동작 | Finder "다음으로 열기", Dock 파일 드롭, Quick Action 경로 회귀 없음 |
| 테스트 | 전체 스위트 통과(현재 361 passed). 아이콘 로드 실패 시 폴백 경로에 테스트 추가 |
| 빌드 | `build_dmg.sh` 완주, DMG 생성 확인 |

---

## 5. 작업 순서

1. §4-1 세 가지 사실 확인 → 결과 기록(추정으로 넘어가지 말 것)
2. **I-01** 아이콘 원본 고정(디자인은 만들지 말고 기존 결과를 PNG로 고정하거나 사용자 제공본 사용)
3. **I-02** Qt 아이콘 설정 + `isNull()` 판정
4. **I-03-1** 최신 소스로 번들 재빌드 → **§4-2 게이트 측정** (여기서 두 증상이 사라지는지 확인. FIX_GUIDE_2.md N-07도 같이 판정)
5. **I-04** 게이트 결과 반영: 트레이 경로 확정, 폴백 로그 명시, `notify()` 반환값 의미 정리
6. **I-06** 빌더 아이콘 규약 통일
7. **I-05**는 사용자에게 A/B/C를 물어 선택을 받은 뒤에만 착수
8. §4-3 회귀 게이트 → PROGRESS.md·STATUS.md에 결과 기록

---

## 6. 하지 말 것

1. 새 아이콘 디자인을 임의로 그려 넣기(원본은 파일로 고정하고, 교체는 사용자 몫)
2. 새 의존성 추가(PyObjC 등) — CLAUDE.md §15-4, I-05는 승인 후에만
3. `notify()`가 배달 성공을 보장하는 것처럼 반환값·문서를 쓰기(모르면 모른다고 적는다)
4. osascript 폴백을 **조용히** 타기 — 폴백은 남기되 사유를 반드시 로그로 남길 것
5. 개발용 래퍼(`make_app.py`)에서 번들 정체성을 흉내 내는 우회를 발명하기(§4-2 실패 시 Opus로 되돌릴 것)
6. `LSUIElement`/`show_in_dock()` 정책을 이 문서 범위 밖에서 바꾸기 — N-07과 함께 §4-2로만 판정
7. 아이콘·알림 확인을 **오래된 번들**(`packaging/dist`, 2026-09-04 빌드)로 하기 — 반드시 재빌드본으로 확인
