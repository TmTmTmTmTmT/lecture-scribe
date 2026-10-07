"""macOS 알림 (F-09).

- `osascript`로 알림 센터에 표시한다(추가 의존성 없음).
- 알림 클릭 시 동작은 osascript로 지정할 수 없으므로, 결과 파일을 Finder에서
  선택 상태로 여는 것은 별도 함수(`reveal_in_finder`)로 제공하고 GUI가 호출한다.
- 알림 실패는 치명적이지 않다. 로그만 남기고 진행한다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .logsetup import get_logger

logger = get_logger(__name__)

_OSASCRIPT = Path("/usr/bin/osascript")
_OPEN = Path("/usr/bin/open")
_TIMEOUT_SEC = 10


def _escape(text: str) -> str:
    """AppleScript 문자열 이스케이프."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str, *, subtitle: str = "") -> bool:
    """알림 표시. 성공 여부를 돌려준다."""
    if not _OSASCRIPT.exists():
        return False
    parts = [f'display notification "{_escape(message)}"', f'with title "{_escape(title)}"']
    if subtitle:
        parts.append(f'subtitle "{_escape(subtitle)}"')
    script = " ".join(parts)
    try:
        proc = subprocess.run(
            [str(_OSASCRIPT), "-e", script],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("알림 표시 실패: %s", exc)
        return False
    if proc.returncode != 0:
        logger.warning("알림 표시 실패(rc=%d): %s", proc.returncode, proc.stderr.strip())
        return False
    return True


def reveal_in_finder(path: Path) -> bool:
    """Finder에서 파일을 선택 상태로 연다."""
    if not _OPEN.exists():
        return False
    try:
        subprocess.run(
            [str(_OPEN), "-R", str(path)],
            capture_output=True,
            timeout=_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Finder 열기 실패: %s", exc)
        return False
    return True


#: 모델별 실측 배속(M1 Pro, beam 3). 시작 알림의 예상 시간 계산용.
_SPEED_BY_MODEL: dict[str, float] = {
    "tiny": 30.0,
    "base": 20.0,
    "small": 10.0,
    "medium": 4.0,
    "large-v3-turbo": 5.5,
    "large-v3": 1.6,
}


def estimate_minutes(total_audio_sec: float, model: str) -> int:
    """전사 예상 시간(분). 모델별 실측 배속 기준, 최소 1분."""
    speed = next(
        (v for k, v in _SPEED_BY_MODEL.items() if model.startswith(k)), 1.5
    )
    return max(1, round(total_audio_sec / speed / 60))


def notify_start(file_count: int, total_audio_sec: float, model: str) -> bool:
    """전사 시작 알림.

    Quick Action은 진행률을 보여줄 방법이 없어서 메뉴 막대 표시만 도는데,
    긴 강의는 수십 분이 걸려 사용자가 멈춘 것으로 오해한다. 시작 시점에
    예상 시간을 알려 준다.
    """
    minutes = estimate_minutes(total_audio_sec, model)
    audio_min = max(1, round(total_audio_sec / 60))
    if file_count > 1:
        message = f"{file_count}개 파일({audio_min}분 분량) 전사 시작 · 약 {minutes}분 예상"
    else:
        message = f"{audio_min}분 분량 전사 시작 · 약 {minutes}분 예상"
    return notify("LectureScribe", message, subtitle=f"모델 {model}")


def completion_message(
    ok_count: int, failed_count: int, first_output: Path | None
) -> str:
    """완료 알림 본문. GUI(트레이)와 CLI(osascript)가 같은 문구를 쓴다."""
    if failed_count and ok_count:
        message = f"{ok_count}건 완료, {failed_count}건 실패"
    elif failed_count:
        message = f"{failed_count}건 실패"
    else:
        message = f"{ok_count}건 전사 완료"
    if first_output is not None:
        message = f"{message} — {first_output.name}"
    return message


def notify_completion(
    ok_count: int, failed_count: int, first_output: Path | None
) -> bool:
    """전사 완료 알림(osascript 경로)."""
    subtitle = first_output.name if first_output is not None else ""
    if failed_count and ok_count:
        message = f"{ok_count}건 완료, {failed_count}건 실패"
    elif failed_count:
        message = f"{failed_count}건 실패"
    else:
        message = f"{ok_count}건 전사 완료"
    return notify("LectureScribe", message, subtitle=subtitle)
