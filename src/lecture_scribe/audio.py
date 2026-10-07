"""오디오 입력 검증 및 메타데이터 조회.

- ffprobe로 duration/스트림 정보를 얻는다(외부 바이너리 절대 경로 사용).
- Finder/Quick Action 컨텍스트에는 Homebrew PATH가 없으므로 절대 경로 탐색이 필수다.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from .errors import (
    CorruptAudioError,
    EmptyFileError,
    FFmpegNotFoundError,
    ICloudStubError,
    MissingFileError,
    NoAudioTrackError,
    UnsupportedFormatError,
)

SUPPORTED_EXTS: Final[frozenset[str]] = frozenset(
    {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".mp4", ".mov"}
)

#: 화면 캡처 대상인 영상 확장자
VIDEO_EXTS: Final[frozenset[str]] = frozenset({".mp4", ".mov"})

# Finder/Automator 컨텍스트에는 PATH가 거의 비어 있다. 우선순위 순 절대 경로.
_BINARY_SEARCH_DIRS: Final[tuple[Path, ...]] = (
    Path("/opt/homebrew/bin"),
    Path("/usr/local/bin"),
    Path("/opt/local/bin"),
    Path("/usr/bin"),
)

_PROBE_TIMEOUT_SEC: Final[int] = 60


@lru_cache(maxsize=4)
def find_binary(name: str) -> Path:
    """ffmpeg/ffprobe 절대 경로 탐색.

    환경변수 LECTURE_SCRIBE_FFMPEG_DIR > 고정 경로 목록 > PATH 순으로 찾는다.
    """
    override = os.environ.get("LECTURE_SCRIBE_FFMPEG_DIR")
    dirs: list[Path] = []
    if override:
        dirs.append(Path(os.path.expanduser(override)))
    dirs.extend(_BINARY_SEARCH_DIRS)
    for directory in dirs:
        candidate = directory / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which(name)
    if found:
        return Path(found)
    raise FFmpegNotFoundError(
        f"{name} 을(를) 찾을 수 없습니다. `brew install ffmpeg` 후 다시 시도하세요.",
        f"{name} 탐색 실패. 검색 경로: {[str(d) for d in dirs]}, PATH={os.environ.get('PATH', '')!r}",
    )


@dataclass(slots=True, frozen=True)
class AudioInfo:
    """ffprobe로 확인한 입력 파일 정보."""

    path: Path
    duration_sec: float
    codec: str
    sample_rate: int
    channels: int
    size_bytes: int


def is_supported(path: Path) -> bool:
    """확장자 대소문자를 무시하고 지원 포맷인지 판단."""
    return path.suffix.lower() in SUPPORTED_EXTS


def icloud_stub_path(path: Path) -> Path | None:
    """아직 내려받지 않은 iCloud 파일의 스텁 경로를 돌려준다(없으면 None).

    iCloud는 미다운로드 파일을 `.<원본명>.icloud` 형태의 숨김 파일로 둔다.
    """
    if path.name.startswith(".") and path.name.endswith(".icloud"):
        return path
    stub = path.with_name(f".{path.name}.icloud")
    return stub if stub.exists() else None


def validate_input(path: Path) -> None:
    """전사 대상으로 쓸 수 있는지 사전 검증. 실패 시 도메인 예외."""
    if not is_supported(path):
        raise UnsupportedFormatError(
            path,
            f"지원하지 않는 형식입니다: {path.suffix or '(확장자 없음)'}",
            f"지원 외 확장자: {path}",
        )
    stub = icloud_stub_path(path)
    if not path.exists():
        if stub is not None:
            raise ICloudStubError(
                path,
                "iCloud Drive에서 아직 내려받지 않은 파일입니다. "
                "Finder에서 파일을 내려받은 뒤 다시 시도하세요.",
                f"iCloud 스텁만 존재: {stub}",
            )
        raise MissingFileError(path, f"파일을 찾을 수 없습니다: {path.name}")
    if stub is not None:
        raise ICloudStubError(
            path,
            "iCloud Drive에서 아직 내려받지 않은 파일입니다. "
            "Finder에서 파일을 내려받은 뒤 다시 시도하세요.",
            f"iCloud 스텁 동시 존재: {stub}",
        )
    if path.stat().st_size == 0:
        raise EmptyFileError(path, f"0바이트 파일입니다: {path.name}")


def media_arg(path: Path) -> str:
    """ffmpeg/ffprobe에 넘길 안전한 경로 문자열.

    ffmpeg 계열은 인자 앞부분의 `이름:`을 **프로토콜**로 해석한다.
    예: `9:1 전자회로.m4a` 를 상대 경로로 넘기면 `9:` 프로토콜을 찾다가
    "Protocol not found"로 실패한다. 절대 경로로 만들면 `/`로 시작하므로
    프로토콜로 오인되지 않는다. PyAV(faster-whisper 내부 디코더)도 동일하다.
    """
    return str(path.resolve())


#: (경로, mtime, size) -> AudioInfo. 같은 파일을 큐 가중치 계산과 전사에서 각각
#: ffprobe 하던 중복 호출을 없앤다. 파일이 바뀌면 키가 달라져 자동 무효화된다.
_PROBE_CACHE: dict[tuple[str, int, int], AudioInfo] = {}


def probe(path: Path) -> AudioInfo:
    """ffprobe로 duration과 오디오 스트림 정보를 얻는다(결과 캐시)."""
    validate_input(path)
    stat = path.stat()
    cache_key = (str(path), int(stat.st_mtime), stat.st_size)
    cached = _PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    ffprobe = find_binary("ffprobe")
    cmd = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-select_streams",
        "a",
        media_arg(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CorruptAudioError(
            path,
            f"파일 분석이 시간 내에 끝나지 않았습니다: {path.name}",
            f"ffprobe 타임아웃: {path}",
        ) from exc
    if proc.returncode != 0:
        raise CorruptAudioError(
            path,
            f"파일을 읽을 수 없습니다(손상되었거나 형식이 올바르지 않음): {path.name}",
            f"ffprobe 실패(rc={proc.returncode}) {path}: {proc.stderr.strip()}",
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CorruptAudioError(
            path,
            f"파일 정보를 해석할 수 없습니다: {path.name}",
            f"ffprobe JSON 파싱 실패 {path}: {exc}",
        ) from exc

    streams = [s for s in data.get("streams", []) if s.get("codec_type") == "audio"]
    if not streams:
        raise NoAudioTrackError(
            path,
            f"오디오 트랙이 없습니다: {path.name}",
            f"오디오 스트림 없음: {path}",
        )
    stream = streams[0]
    fmt = data.get("format", {})

    duration_raw = fmt.get("duration") or stream.get("duration")
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0.0:
        raise CorruptAudioError(
            path,
            f"재생 길이를 확인할 수 없습니다: {path.name}",
            f"duration 없음/0: {path} raw={duration_raw!r}",
        )

    def _int(value: object, default: int = 0) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return default

    info = AudioInfo(
        path=path,
        duration_sec=duration,
        codec=str(stream.get("codec_name", "unknown")),
        sample_rate=_int(stream.get("sample_rate")),
        channels=_int(stream.get("channels"), 1),
        size_bytes=_int(fmt.get("size"), stat.st_size),
    )
    if len(_PROBE_CACHE) > 256:
        _PROBE_CACHE.clear()
    _PROBE_CACHE[cache_key] = info
    return info


@dataclass(slots=True, frozen=True)
class MediaInfo:
    """영상/오디오 스트림 유무와 길이 (PLAN_VIDEO_FRAMES.md V-02b).

    `probe()`는 오디오 전용 경로라 오디오가 없으면 예외를 던진다. 영상 입력은
    오디오가 없어도(화면 녹화) 프레임 캡처가 가능하므로 이 함수로 먼저 확인한다.
    """

    path: Path
    duration_sec: float
    has_audio: bool
    has_video: bool
    width: int = 0
    height: int = 0


def probe_media(path: Path) -> MediaInfo:
    """스트림 구성 확인. 오디오 유무로 예외를 던지지 않는다."""
    validate_input(path)
    ffprobe = find_binary("ffprobe")
    cmd = [
        str(ffprobe),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        media_arg(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise CorruptAudioError(
            path,
            f"파일 분석이 시간 내에 끝나지 않았습니다: {path.name}",
            f"ffprobe 타임아웃: {path}",
        ) from exc
    if proc.returncode != 0:
        raise CorruptAudioError(
            path,
            f"파일을 읽을 수 없습니다(손상되었거나 형식이 올바르지 않음): {path.name}",
            f"ffprobe 실패(rc={proc.returncode}) {path}: {proc.stderr.strip()}",
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CorruptAudioError(
            path,
            f"파일 정보를 해석할 수 없습니다: {path.name}",
            f"ffprobe JSON 파싱 실패 {path}: {exc}",
        ) from exc

    streams = data.get("streams", [])
    video = [
        s
        for s in streams
        if s.get("codec_type") == "video"
        # 앨범 아트(mp3/m4a 표지)는 영상이 아니다
        and not s.get("disposition", {}).get("attached_pic")
    ]
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    fmt = data.get("format", {})
    try:
        duration = float(fmt.get("duration") or (video[0].get("duration") if video else 0))
    except (TypeError, ValueError):
        duration = 0.0

    def _int(value: object) -> int:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return 0

    return MediaInfo(
        path=path,
        duration_sec=duration,
        has_audio=has_audio,
        has_video=bool(video),
        width=_int(video[0].get("width")) if video else 0,
        height=_int(video[0].get("height")) if video else 0,
    )


def probe_duration(path: Path) -> float:
    """큐 가중치·예상 시간용 길이. 오디오 없는 영상(화면 녹화)도 영상 길이를 돌려준다."""
    try:
        return probe(path).duration_sec
    except NoAudioTrackError:
        return probe_media(path).duration_sec


def first_speech_offset(
    path: Path, *, window_sec: int = 120, noise_db: int = -40
) -> float:
    """오디오 앞부분에서 실제 발화가 시작되는 대략적인 시각(초).

    ffmpeg `silencedetect`로 앞 window_sec 구간만 훑는다(디코딩 전체 불필요).
    앞이 무음이면 첫 `silence_end`가 발화 시작이고, 처음부터 소리가 있으면 0.0이다.
    프롬프트로 인한 **앞 구간 누락**을 판정하는 데 쓴다.
    """
    ffmpeg = find_binary("ffmpeg")
    cmd = [
        str(ffmpeg),
        "-nostdin",
        "-v",
        "info",
        "-t",
        str(window_sec),
        "-i",
        media_arg(path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d=0.5",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SEC, check=False
        )
    except subprocess.TimeoutExpired:
        return 0.0
    if proc.returncode != 0:
        return 0.0

    starts_with_silence = False
    first_end = 0.0
    for line in proc.stderr.splitlines():
        if "silence_start:" in line:
            try:
                value = float(line.split("silence_start:")[1].split()[0])
            except (IndexError, ValueError):
                continue
            if value <= 0.2 and not starts_with_silence and first_end == 0.0:
                starts_with_silence = True
        elif "silence_end:" in line and starts_with_silence and first_end == 0.0:
            try:
                first_end = float(line.split("silence_end:")[1].split()[0])
            except (IndexError, ValueError):
                continue
    return first_end


def collect_inputs(paths: list[Path], recursive: bool) -> tuple[list[Path], list[tuple[Path, str]]]:
    """파일/폴더 목록을 전사 대상 파일 목록으로 펼친다.

    Returns:
        (수용된 파일 목록, [(거부된 경로, 사유)] 목록)
    """
    accepted: list[Path] = []
    rejected: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    def _add(candidate: Path) -> None:
        # ffmpeg 프로토콜 오인(`9:1 ...`) 방지 + 중복 제거를 위해 절대 경로로 통일
        resolved = candidate.expanduser().resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        if not is_supported(resolved):
            rejected.append((resolved, f"지원하지 않는 형식({resolved.suffix or '확장자 없음'})"))
            return
        accepted.append(resolved)

    for path in paths:
        path = path.expanduser()
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            for child in sorted(path.glob(pattern)):
                if child.is_file() and not child.name.startswith("."):
                    if is_supported(child):
                        _add(child)
            continue
        _add(path)
    return accepted, rejected
