LectureScribe — macOS 강의 녹음 로컬 전사 앱
=============================================

강의 녹음을 이 기기 안에서만 전사합니다. 오디오는 어디로도 전송되지 않습니다.
결과는 원본 오디오와 같은 폴더에 같은 이름으로 저장됩니다.


■ 설치

1) LectureScribe.app 을 오른쪽 Applications 폴더로 끌어다 놓으세요.

2) ffmpeg 이 필요합니다. 터미널에서:

       /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"   ← Homebrew 없을 때만
       brew install ffmpeg

   ffmpeg 이 없으면 앱이 "ffprobe를 찾을 수 없습니다" 라고 알려줍니다.

3) 첫 실행은 우클릭 → "열기" → 대화상자에서 다시 "열기" 를 누르세요.
   (Apple 개발자 인증서가 없는 앱이라 더블클릭만으로는 열리지 않습니다.)


■ 첫 전사

처음 한 번은 음성 인식 모델을 내려받습니다(large-v3 기준 약 3GB, 네트워크 필요).
그 다음부터는 오프라인으로 동작합니다.

1) 앱을 엽니다. 창 위쪽에 전사 주제와 용어를 넣습니다.
2) 아래 넓은 영역에 오디오 파일을 끌어다 놓습니다.
3) "전사 시작".


■ 주제와 용어를 꼭 넣으세요 (정확도가 크게 달라집니다)

  주제 예) OO대학교 전기공학과 전자회로 강의, 채널 잡음과 백색 가우시안 잡음
  용어 예) 잡음, 백색 가우시안 잡음, AWGN, 열잡음, 다중 경로, 반도체

  - 나열식 키워드보다 실제 강의에서 말할 법한 문장이 좋습니다.
  - 그 강의에 실제로 나오는 용어만 넣으세요. 무관한 용어는 오히려 정확도를 떨어뜨립니다.
  - 용어를 입력하면 토큰 사용량(예: 51 / 223)이 바로 표시됩니다.


■ 속도 기준 (Apple M1 Pro 실측)

  모델 large-v3        45분 강의 → 약 30분   (정확도 우선, 기본값)
  모델 large-v3-turbo  45분 강의 → 약 8분    (초벌용, 창 위 "모델"에서 변경)

  파일 여러 개를 한 번에 넣으면 2개씩 동시에 처리해 1.3배 빨라집니다.


■ 결과 파일

  강의01.txt              순수 텍스트 (기본)
  강의01.md               10분 단위 섹션 + 메타데이터
  강의01.srt / .vtt       자막
  강의01.transcript.json  구간별 신뢰도 (근거 확인용)

  md 안의 ⟨?⟩ 표시는 인식 신뢰도가 낮은 구간입니다.
  요약·정리할 때 그 부분은 추측으로 채우지 말고 원음을 확인하세요.

  원본 오디오 파일은 절대 옮기거나 고치지 않습니다.


■ Finder 우클릭 메뉴로 쓰기 (선택)

  "추가 도구" 폴더의 Quick Action 설치.command 를 더블클릭하면
  Finder에서 오디오 파일 우클릭 → 빠른 동작 → "LectureScribe로 전사" 가 생깁니다.


■ 문제가 생기면

  로그: ~/Library/Logs/LectureScribe/lecture-scribe.log
  설정: ~/Library/Application Support/LectureScribe/settings.json

  터미널에서 직접 실행해 오류를 볼 수도 있습니다:
      /Applications/LectureScribe.app/Contents/MacOS/LectureScribe --cli --help
