"""도메인 예외.

사용자에게 보여줄 메시지(user_message)와 로그용 메시지(log_message)를 분리한다.
GUI/CLI는 user_message만 노출하고, 로그에는 log_message를 남긴다.
"""

from __future__ import annotations

from pathlib import Path


class LectureScribeError(Exception):
    """모든 도메인 예외의 기반 클래스."""

    def __init__(self, user_message: str, log_message: str | None = None) -> None:
        super().__init__(log_message or user_message)
        self.user_message = user_message
        self.log_message = log_message or user_message


# --- 설정 ---------------------------------------------------------------


class ConfigError(LectureScribeError):
    """설정 파일 로드/저장/마이그레이션 실패."""


# --- 입력 오디오 --------------------------------------------------------


class AudioError(LectureScribeError):
    """오디오 입력 관련 오류의 기반 클래스."""

    def __init__(
        self, path: Path, user_message: str, log_message: str | None = None
    ) -> None:
        super().__init__(user_message, log_message)
        self.path = path


class UnsupportedFormatError(AudioError):
    """지원하지 않는 확장자."""


class MissingFileError(AudioError):
    """파일이 존재하지 않음."""


class EmptyFileError(AudioError):
    """0바이트 파일."""


class ICloudStubError(AudioError):
    """iCloud Drive에서 아직 내려받지 않은 스텁 파일."""


class NoAudioTrackError(AudioError):
    """오디오 트랙이 없는 파일(영상 등)."""


class CorruptAudioError(AudioError):
    """ffprobe가 해석하지 못하는 손상 파일."""


class FFmpegNotFoundError(LectureScribeError):
    """ffmpeg/ffprobe 바이너리를 찾을 수 없음."""


# --- 백엔드 -------------------------------------------------------------


class BackendError(LectureScribeError):
    """전사 백엔드 관련 오류의 기반 클래스."""


class BackendUnavailableError(BackendError):
    """백엔드 패키지 미설치 또는 플랫폼 미지원."""


class ModelLoadError(BackendError):
    """모델 다운로드/로드 실패."""


class TranscriptionFailedError(BackendError):
    """전사 도중 복구 불가능한 오류."""


# --- 출력 ---------------------------------------------------------------


class OutputError(LectureScribeError):
    """출력 파일 쓰기 실패."""


class WriteFailedError(OutputError):
    """대체 폴더로도 저장하지 못함."""


# --- 취소 ---------------------------------------------------------------


class CancelledError(LectureScribeError):
    """사용자 취소."""

    def __init__(self, user_message: str = "사용자가 작업을 취소했습니다.") -> None:
        super().__init__(user_message)
