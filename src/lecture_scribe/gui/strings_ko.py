"""한국어 UI 문자열 모음.

UI 문자열은 여기 한 곳에만 둔다(§8).
"""

from __future__ import annotations

from typing import Final

APP_TITLE: Final[str] = "LectureScribe"

# --- 설정 영역 ---
PRESET_LABEL: Final[str] = "프리셋"
PRESET_NEW: Final[str] = "새로 만들기"
PRESET_NEW_TITLE: Final[str] = "새 프리셋"
PRESET_NEW_PROMPT: Final[str] = "프리셋 이름 (예: 전자회로, 전자기학)"
PRESET_DUPLICATE: Final[str] = "'{name}' 프리셋이 이미 있습니다."
PRESET_SAVE: Final[str] = "저장"
PRESET_RENAME: Final[str] = "이름 변경"
PRESET_DELETE: Final[str] = "삭제"
PRESET_NEW_NAME: Final[str] = "새 프리셋 이름"
PRESET_RENAME_TITLE: Final[str] = "프리셋 이름 변경"
PRESET_DELETE_CONFIRM: Final[str] = "프리셋 '{name}' 을(를) 삭제할까요?"
PRESET_LAST_ONE: Final[str] = "마지막 프리셋은 삭제할 수 없습니다."

TOPIC_LABEL: Final[str] = "전사 주제"
TOPIC_PLACEHOLDER: Final[str] = (
    "나열식 키워드보다 실제 강의에서 말할 법한 문장이 인식에 유리합니다."
)
GLOSSARY_LABEL: Final[str] = "용어 (쉼표 구분)"
GLOSSARY_PLACEHOLDER: Final[str] = "쉼표로 구분해 입력하세요"
TOKEN_USAGE: Final[str] = "{used} / {budget} 토큰"
TOKEN_OVER: Final[str] = "{used} / {budget} 토큰 — {count}개 용어가 잘립니다: {terms}"
TOKEN_COUNTING: Final[str] = "토큰 계산 중…"
TOKEN_ERROR: Final[str] = "토큰 계산 실패(토크나이저 준비 필요)"

LANGUAGE_LABEL: Final[str] = "언어"
LANGUAGE_KO: Final[str] = "한국어"
LANGUAGE_EN: Final[str] = "영어"
LANGUAGE_AUTO: Final[str] = "자동 감지"
MODEL_LABEL: Final[str] = "모델"
MODEL_TIP: Final[str] = (
    "large-v3 — 정확도 기준. 45분 강의에 약 30분, 메모리 2.4GB\n"
    "large-v3-turbo — 3.4배 빠름. 45분 강의에 약 8분, 메모리 1.4GB\n"
    "음질이 나쁜 구간에서는 large-v3가 더 잘 버팁니다."
)
LANGUAGE_TIP: Final[str] = (
    "자동 감지는 첫 30초로 판단합니다. 언어를 아는 경우 지정하는 편이 정확합니다."
)
TOPIC_TIP: Final[str] = (
    "실제 강의에서 말할 법한 문장으로 적으세요. 나열식 키워드나 명령문은 효과가 없습니다."
)
GLOSSARY_TIP: Final[str] = (
    "그 강의에 실제로 나오는 전문 용어만 쉼표로 구분해 넣으세요.\n"
    "무관한 용어를 넣으면 오히려 정확도가 떨어집니다(실측: '잡음'이 '자궁'으로 인식됨).\n"
    "223 토큰을 넘으면 뒤쪽부터 잘리며, 잘리는 항목을 알려줍니다."
)
ADVANCED: Final[str] = "고급 설정"

# --- 고급 설정 ---
ADVANCED_INTRO: Final[str] = (
    "기본값은 실측으로 정한 값입니다. 문제가 있을 때만 바꾸세요."
)
# FIX_GUIDE_6.md C-03: 14행 평면 나열을 4구역으로 나눈다. 순서는 실행 순서가 아니라
# 사용자가 만질 빈도 기준(인식 → 프롬프트 → 출력 → 후처리).
SECTION_RECOGNITION: Final[str] = "인식"
SECTION_PROMPT: Final[str] = "프롬프트"
SECTION_OUTPUT: Final[str] = "출력"
SECTION_POSTPROCESS: Final[str] = "후처리"
SECTION_VIDEO: Final[str] = "영상 입력"
BACKEND_LABEL: Final[str] = "백엔드"
BACKEND_TIP: Final[str] = (
    "faster-whisper — CPU 전용. 용어 고정(hotwords)·VAD·빔 서치를 모두 지원하는 기본값.\n"
    "mlx — Metal GPU. 약 3배 빠르지만 용어 고정·VAD·빔 서치가 없어 반복과 누락이 생깁니다."
)
FORMATS_LABEL: Final[str] = "출력 포맷"
FORMATS_TIP: Final[str] = (
    "txt — 순수 텍스트\n"
    "md — 10분 단위 섹션 헤더 + 메타데이터(front matter). 요약·정리에 쓰기 좋습니다\n"
    "srt / vtt — 자막 파일\n"
    "json — 구간별 타임스탬프와 신뢰도 전체"
)
TIMESTAMPS_LABEL: Final[str] = "타임스탬프 포함"
TIMESTAMPS_TIP: Final[str] = (
    "txt·md 본문의 각 줄 앞에 [시:분:초]를 붙입니다. 나중에 특정 지점을 찾을 때 유용합니다."
)
CONFLICT_LABEL: Final[str] = "파일명 충돌"
CONFLICT_TIP: Final[str] = (
    "같은 이름의 결과 파일이 이미 있을 때 어떻게 할지.\n"
    "_1 붙이기 — 기존 파일을 두고 새로 만듭니다(기본, 가장 안전)\n"
    "덮어쓰기 — 기존 결과를 대체합니다\n"
    "건너뛰기 — 전사하지 않고 넘어갑니다"
)
CONFLICT_OVERWRITE: Final[str] = "덮어쓰기"
CONFLICT_SUFFIX: Final[str] = "_1 붙이기"
CONFLICT_SKIP: Final[str] = "건너뛰기"
USE_INITIAL_PROMPT: Final[str] = "주제 문장을 initial_prompt로 사용"
USE_INITIAL_PROMPT_TIP: Final[str] = (
    "켜면 오디오 앞부분이 누락되는 사례가 있습니다(실측). "
    "누락이 감지되면 자동으로 hotwords 단독으로 재전사합니다."
)
USE_INITIAL_PROMPT_NOTE: Final[str] = "켜면 오디오 앞부분이 누락될 수 있습니다(실측)."
USE_HOTWORDS: Final[str] = "용어를 hotwords로 고정"
USE_HOTWORDS_TIP: Final[str] = (
    "위 용어 목록을 매 구간의 인식 힌트로 넣습니다. 이 앱의 핵심 기능입니다.\n"
    "끄면 전문 용어 인식률이 크게 떨어집니다(실측: 핵심 용어 적중 6/6 → 2/6)."
)
USE_HOTWORDS_UNSUPPORTED: Final[str] = (
    "이 백엔드는 hotwords를 지원하지 않습니다. "
    "'주제 문장을 initial_prompt로 사용'을 켜면 용어집이 그 경로로 대신 전달됩니다"
    "(꺼져 있으면 이 백엔드에서는 용어집이 적용되지 않습니다)."
)
CONDITION_PREV: Final[str] = "이전 문맥 유지"
CONDITION_PREV_TIP: Final[str] = (
    "앞 구간의 인식 결과를 다음 구간의 문맥으로 넘깁니다(condition_on_previous_text).\n"
    "문장 연결이 자연스러워지지만, 한 번 잘못 인식하면 그 오류가 뒤로 번질 수 있습니다.\n"
    "반복 루프가 생기면 이 옵션을 꺼 보세요.\n"
    "GPU(mlx)에서는 최대 120초 구간 *내부*의 짧은 조각들끼리만 영향을 줍니다 — "
    "120초 구간과 구간 사이의 문맥은 아래 '창 경계 문맥 유지'가 따로 맡습니다.\n"
    "GPU 기본값은 꺼짐입니다(실측: 켜면 2.2배 느려지고 외국어 문장이 섞여 나오는 "
    "빈도가 9배 높았습니다). CPU(faster-whisper) 기본값은 켬입니다 — 백엔드를 "
    "바꾸면 이 체크박스도 그 백엔드의 값으로 바뀝니다."
)
CARRY_WINDOW_PROMPT: Final[str] = "창 경계 문맥 유지 (GPU 전용)"
CARRY_WINDOW_PROMPT_TIP: Final[str] = (
    "GPU(mlx)는 오디오를 120초 구간으로 잘라 처리합니다. 이 옵션을 켜면 한 구간의 "
    "마지막 문장을 다음 구간에 넘겨 구간 경계에서도 문맥·용어 표기가 이어집니다.\n"
    "위 '이전 문맥 유지'와는 별개입니다 — 그건 120초 구간 *안*에서만 영향을 주고, "
    "이 옵션은 구간과 구간 *사이*에만 영향을 줍니다. 둘 다 꺼도 서로 독립적으로 동작합니다.\n"
    "CPU(faster-whisper)는 구간을 나누지 않아 해당 없음."
)
CARRY_WINDOW_PROMPT_UNSUPPORTED: Final[str] = (
    "이 백엔드는 오디오를 구간으로 나누지 않아 해당 없습니다."
)
CONDITION_PREV_NOTE: Final[str] = (
    "GPU 기본값은 꺼짐 — 켜면 외국어 혼입이 9배 늘었습니다(실측)."
)
CARRY_WINDOW_PROMPT_NOTE: Final[str] = "GPU 전용 — CPU에서는 해당 없음."
VAD_LABEL: Final[str] = "무음 구간 제거 (VAD)"
VAD_TIP: Final[str] = (
    "Silero VAD로 말이 없는 구간을 미리 걸러냅니다.\n"
    "강의 녹음은 무음이 길어 이 옵션이 없으면 없는 말을 지어내는 환각이 잘 생깁니다.\n"
    "특별한 이유가 없으면 켜 두세요."
)
VAD_UNSUPPORTED: Final[str] = "이 백엔드는 VAD를 지원하지 않습니다."
#: FIX_GUIDE_6.md C-05: 백엔드가 무시하는 항목은 인라인 문구를 바꿔 바로 보이게 한다.
VAD_BACKEND_NOTE: Final[str] = "현재 백엔드에서 무시됩니다."
BEAM_LABEL: Final[str] = "빔 크기"
BEAM_TIP: Final[str] = (
    "디코딩할 때 동시에 검토하는 후보 문장 수.\n"
    "클수록 이론상 정확하지만 실측에서는 3과 5의 품질 차이가 없었고 3이 27% 빨랐습니다.\n"
    "결과가 자꾸 무너지면 5로 올려 보세요."
)
BEAM_UNSUPPORTED: Final[str] = "이 백엔드는 빔 서치를 지원하지 않습니다(그리디)."
BEAM_BACKEND_NOTE: Final[str] = "현재 백엔드에서 무시됩니다(그리디)."
FUZZY_LABEL: Final[str] = "유사도 용어 교정"
FUZZY_TIP: Final[str] = (
    "전사가 끝난 뒤, 위 용어 목록과 비슷하게 들린 단어를 용어 표기로 바꿉니다.\n"
    "예) '임피던스 정함' → '임피던스 정합'\n"
    "비슷한 다른 단어까지 바꿔버릴 수 있어 기본은 꺼져 있습니다."
)
FUZZY_UNAVAILABLE: Final[str] = "rapidfuzz 미설치 — `uv sync --extra fuzzy`"
FOREIGN_SCRIPT_LABEL: Final[str] = "기대 언어 밖 문자 감지(한자/가나 등)"
FOREIGN_SCRIPT_TIP: Final[str] = (
    "한국어/영어 강의인데 한자·가나·키릴 문자가 섞여 나오면 Whisper 환각일 가능성이 큽니다.\n"
    "그런 구간을 저신뢰 마커(⟨?⟩)로 표시합니다. 원문은 지우거나 바꾸지 않습니다.\n"
    "언어가 한국어/영어로 인식된 경우에만 동작합니다(중국어/일본어 강의는 자동 비활성)."
)
BATCHED_LABEL: Final[str] = "배치 모드 (빠르지만 환각 억제 일부 비활성)"
BATCHED_TIP: Final[str] = (
    "약 1.7배 빠르지만 condition_on_previous_text / "
    "hallucination_silence_threshold / temperature 폴백이 무시됩니다."
)
# FIX_GUIDE_6.md C-05: 잘못 켜면 결과가 나빠지는 항목만 툴팁 밖으로 한 줄 더 낸다.
# 나머지는 툴팁 유지(상세는 호버로).
BATCHED_NOTE: Final[str] = "켜면 일부 환각 억제 기능이 꺼집니다(실측 1.7배 빠름)."

# --- 드롭존 ---
DROP_IDLE_TITLE: Final[str] = "파일을 여기에 놓으세요"
DROP_IDLE_HINT: Final[str] = "클릭해서 고를 수도 있습니다 · m4a, mp3, wav, mp4 …"
DROP_ACTIVE: Final[str] = "놓으면 큐에 추가됩니다"
DROP_INVALID: Final[str] = "지원하지 않는 파일이 섞여 있습니다"
QUEUE_START: Final[str] = "전사 시작"
QUEUE_CANCEL: Final[str] = "취소"
QUEUE_REMOVE: Final[str] = "제거"
QUEUE_CLEAR: Final[str] = "새 파일 놓기"
QUEUE_CLEAR_DONE: Final[str] = "완료 항목 지우기"
QUEUE_ADD_FILES: Final[str] = "파일 추가"
ROW_MODEL_TIP: Final[str] = "이 파일에 쓸 모델. 전사가 시작되기 전까지 바꿀 수 있습니다."
#: FIX_GUIDE_6.md C-01: 반복 구간·기대 언어 밖 문자 등 "산출물을 확인해야 하는" 경고만 센다.
#: 백엔드 무시 옵션 같은 정보성 경고는 세지 않는다(매 파일 뜨면 배지가 무의미해진다).
ROW_WARNING_BADGE: Final[str] = "⚠ {count}"
ROW_WARNING_BADGE_TIP: Final[str] = "클릭하면 상세 내용을 봅니다:\n{preview}"
ROW_WARNING_DIALOG_TITLE: Final[str] = "전사 경고 — {name}"
ROW_WARNING_QUALITY_HEADER: Final[str] = "산출물을 확인하세요"
ROW_WARNING_INFO_HEADER: Final[str] = "참고"
STATUS_QUEUED_WHILE_RUNNING: Final[str] = "전사 중에도 파일을 추가하고 시작할 수 있습니다."
GLOSSARY_AUTO_ADDED: Final[str] = "전사에서 자주 나온 용어 {count}개를 추가했습니다: {terms}"
# FIX_GUIDE_7.md E-02: 자동 추가 직후 토큰 한도 때문에 일부를 다시 뺐을 때 안내.
GLOSSARY_AUTO_ADDED_AND_PRUNED: Final[str] = (
    "전사에서 자주 나온 용어 {added_count}개를 추가했지만, 토큰 한도 때문에 "
    "최근 등장이 적었던 {removed_count}개를 다시 뺐습니다: {removed_terms}"
)
#: FIX_GUIDE_14 G-03: 오래 안 나온 자동 추가분을 만료로 뺐을 때 안내.
GLOSSARY_AUTO_EXPIRED: Final[str] = (
    "한동안 다시 나오지 않은 자동 추가 용어 {count}개를 뺐습니다: {terms}"
)
GLOSSARY_AUTO_PRUNED: Final[str] = (
    "토큰 한도 때문에 최근 등장이 적었던 자동 추가 용어 {count}개를 뺐습니다: {terms}"
)
QUEUE_NOTHING_PENDING: Final[str] = "대기 중인 파일이 없습니다. 파일을 추가하세요."
QUEUE_TOTAL: Final[str] = "전체 {done}/{total} · {percent:.1f}%"
QUEUE_ETA: Final[str] = "남은 시간 약 {minutes}분 {seconds}초"
STATUS_WAITING: Final[str] = "대기"
STATUS_RUNNING: Final[str] = "전사 중"
STATUS_DONE: Final[str] = "완료"
STATUS_FAILED: Final[str] = "실패"
STATUS_CANCELLED: Final[str] = "취소됨"
STATUS_SKIPPED: Final[str] = "건너뜀"

RESULT_HEADER: Final[str] = "전사 완료"
RESULT_OPEN_HINT: Final[str] = "결과 파일을 클릭하면 Finder에서 열립니다."
FILE_DIALOG_TITLE: Final[str] = "전사할 파일 선택"
FILE_DIALOG_FILTER: Final[str] = (
    "오디오·영상 (*.m4a *.mp3 *.wav *.aac *.flac *.ogg *.mp4 *.mov);;모든 파일 (*)"
)
UNSUPPORTED_FILES: Final[str] = "제외된 파일 {count}개: {names}"
ERROR_TITLE: Final[str] = "오류"
MODEL_PREPARING: Final[str] = "모델 준비 중…"
PROCESSING_GENERIC: Final[str] = "처리 중…"

# --- 전사 후 교정 (F-09) ---
CORRECTION_LABEL = "전사 후 교정"
CORRECTION_ENABLE = "gemma로 오인식 교정 제안"
CORRECTION_TIP = (
    "전사가 끝난 뒤 로컬 LLM(Ollama의 gemma4)에게 음성인식 오류로 보이는 곳을 묻는다.\n"
    "전사문은 고치지 않는다. 원문을 그대로 두고 `원문[→교정]` 주석만 붙이고,\n"
    "근거를 담은 <파일명>.corrections.json 을 함께 낸다.\n\n"
    "Ollama가 설치되어 있어야 한다(`brew install ollama`).\n"
    "데몬은 앱이 알아서 띄운다. 교정 모델은 응답 직후 메모리에서 내려간다.\n\n"
    "주의: 이 모델은 오디오를 듣지 못하고 문맥만 보고 추정한다. 교정은 참고용이다."
)
CORRECTION_MODEL_LABEL = "교정 모델"
CORRECTION_MODEL_TIP = (
    "Ollama가 켜져 있으면 실제로 받아 둔 gemma 계열 모델을 전부 보여준다.\n"
    "꺼져 있으면 아래 두 개(문서화된 기본값)만 보여준다.\n\n"
    "실측(전자회로 강의 918자 구간):\n"
    "  gemma4:e4b — 제안 9건 중 8건 정답(89%), 33.5초. 정확하지만 느리고 메모리 4.6GB.\n"
    "  gemma4:e2b — 제안 7건 중 5건 정답(71%), 19.7초. 빠르고 가볍다.\n"
    "다른 버전을 쓰려면 `ollama pull <모델명>`으로 받은 뒤 오른쪽 새로고침을 누르면 된다."
)
CORRECTION_MODEL_REFRESH = "새로고침"
CORRECTION_MODEL_REFRESH_TIP = (
    "Ollama에 실제로 받아져 있는 gemma 모델 목록을 다시 훑는다.\n"
    "앱을 켠 뒤에 Ollama를 새로 켰거나 모델을 새로 받았으면 눌러서 반영한다."
)
CORRECTION_CONFIDENCE_LABEL = "채택 신뢰도"
CORRECTION_CONFIDENCE_TIP = (
    "모델이 스스로 매긴 신뢰도의 하한. low를 넣으면 제안이 늘지만 잡음도 늘어난다.\n"
    "기본값 medium 권장."
)
CORRECTION_ANNOTATE = "전사문에 주석 달기"
CORRECTION_ANNOTATE_TIP = (
    "끄면 전사문은 손대지 않고 corrections.json만 낸다.\n"
    "켜도 원문 글자는 지워지지 않는다. `원문[→교정]` 형태로 덧붙일 뿐이다."
)
CORRECTION_OCR_TERMS = "슬라이드 용어를 교정에 참고(영상 입력, 실험)"
CORRECTION_OCR_TERMS_TIP = (
    "영상에서 뽑은 슬라이드 글자(OCR) 용어를 교정 모델에 참고용으로 알려준다.\n"
    "OCR 오타가 섞여 있을 수 있어 '확인된 용어'와 따로 표시한다. 이 파일에만 적용되고 저장되지 않는다."
)
CORRECTION_UNAVAILABLE = "Ollama를 찾을 수 없습니다 (`brew install ollama` 필요)"

SPLITTER_TIP = "이 선을 위아래로 끌어 설정 영역과 파일 영역의 크기를 조정한다"

ROW_RETRY = "재시도"
ROW_RETRY_TIP = "이 파일만 다시 전사한다. 모델을 바꿔서 다시 시도할 수도 있다"
QUEUE_RETRY_ALL = "실패 재시도"
QUEUE_RETRY_ALL_TIP = "실패·취소된 파일을 모두 다시 큐에 넣는다"

# --- 시작 시 의존성 점검(스플래시) -------------------------------------------

STARTUP_CHECK_TITLE = "시작 전 확인"
STARTUP_CHECK_INTRO = (
    "전사·교정에 필요한 몇 가지가 아직 준비되지 않았습니다.\n"
    "지금 준비하거나, 나중에 다시 확인할 수 있습니다(전사 기능 자체는 그대로 씁니다)."
)
STARTUP_CHECK_OK_BADGE = "✓ 준비됨"
STARTUP_CHECK_MISSING_BADGE = "✕ 없음"
STARTUP_CHECK_COPY_COMMAND = "명령 복사"
STARTUP_CHECK_COMMAND_COPIED = "복사됨"
STARTUP_CHECK_START_OLLAMA = "지금 실행"
STARTUP_CHECK_STARTING = "실행하는 중…"
STARTUP_CHECK_START_FAILED = "실행 실패"
STARTUP_CHECK_PULL_MODEL = "지금 받기"
STARTUP_CHECK_PULLING = "받는 중… (모델 크기에 따라 수 분 걸릴 수 있습니다)"
STARTUP_CHECK_PULL_FAILED = "받기 실패"
STARTUP_CHECK_RECHECK = "다시 확인"
STARTUP_CHECK_CONTINUE = "계속"
STARTUP_CHECK_DONT_SHOW_AGAIN = "모두 준비됨 — 다음부터 자동으로 건너뜁니다"


# --- 영상 입력(화면 캡처) — PLAN_VIDEO_FRAMES.md V-07 ---
VIDEO_CAPTURE_LABEL: Final[str] = "화면이 바뀔 때마다 캡처"
VIDEO_CAPTURE_TIP: Final[str] = (
    "mp4/mov 영상을 넣으면 화면이 바뀐 시점을 이미지로 저장합니다(시간이 새겨집니다).\n"
    "결과는 원본과 같은 위치의 '<파일명>.frames' 폴더에 들어가며, 슬라이드 글자 목록(frames.md)도 함께 만듭니다.\n"
    "오디오 트랙이 없는 화면 녹화는 전사 없이 캡처만 처리합니다."
)
VIDEO_THRESHOLD_LABEL: Final[str] = "화면 변화 기준"
VIDEO_THRESHOLD_TIP: Final[str] = (
    "마지막으로 저장한 화면과 이 비율 이상 달라지면 새 장면으로 봅니다(기본 10%).\n"
    "값이 클수록 큰 화면 전환만 잡습니다. 본문만 바뀌는 슬라이드는 5~15% 정도만 변하므로\n"
    "20% 이상으로 올리면 이런 전환을 놓칩니다."
)
VIDEO_DEDUPE_LABEL: Final[str] = "중복 제외 기준"
VIDEO_DEDUPE_TIP: Final[str] = (
    "이미 저장한 화면과 이 비율 미만으로만 다르면 저장하지 않습니다(기본 3%).\n"
    "앞뒤 슬라이드를 왔다 갔다 하거나 구석 아이콘이 움직일 때 같은 장면이 여러 번 저장되는 것을 막습니다.\n"
    "0이면 끕니다."
)
VIDEO_INTERVAL_LABEL: Final[str] = "최소 캡처 간격"
VIDEO_INTERVAL_TIP: Final[str] = "저장하는 두 장면 사이의 최소 시간(영상 기준, 기본 5초)."
VIDEO_OCR_LABEL: Final[str] = "슬라이드 글자 인식(OCR)"
VIDEO_OCR_TIP: Final[str] = (
    "캡처한 화면의 글자를 Mac 안에서 읽어 frames.md에 넣습니다. 이미지는 기기 밖으로 나가지 않습니다.\n"
    "수식은 읽지 못하고 글자를 잘못 읽을 수 있습니다. 처음 한 번은 준비에 30초쯤 걸립니다."
)
VIDEO_OCR_UNAVAILABLE: Final[str] = "OCR 모듈 미설치 — `uv sync --extra ocr`"
VIDEO_OCR_TERMS_LABEL: Final[str] = "슬라이드 용어를 전사 프롬프트에 추가(실험)"
VIDEO_OCR_TERMS_TIP: Final[str] = (
    "슬라이드에서 뽑은 용어를 이 파일의 전사에만 덧붙입니다(사용자 용어 뒤, 프리셋에는 저장 안 함).\n"
    "아직 효과를 검증하지 않아 기본은 꺼져 있습니다. 전사가 없는 화면 녹화에는 해당 없습니다."
)
VIDEO_SHEETS_LABEL: Final[str] = "프레임을 시트로 묶기"
VIDEO_SHEETS_TIP: Final[str] = (
    "캡처한 프레임 여러 장을 격자 이미지 한 장으로 이어붙입니다(채팅 첨부 개수 제한 회피).\n"
    "끄면 낱장 이미지를 그대로 둡니다."
)
VIDEO_SHEET_COLS_LABEL: Final[str] = "시트 가로 칸 수"
VIDEO_SHEET_ROWS_LABEL: Final[str] = "시트 세로 칸 수"
VIDEO_SHEET_GRID_TIP: Final[str] = "한 시트에 넣을 칸 수(1~3). 기본 1x2(가로1 x 세로2). 둘 다 1이면 시트를 안 만듭니다."
VIDEO_KEEP_SINGLES_LABEL: Final[str] = "낱장 이미지도 보관"
VIDEO_KEEP_SINGLES_TIP: Final[str] = "시트를 만든 뒤에도 원본 낱장 이미지(NNNN_*.jpg)를 지우지 않습니다."
