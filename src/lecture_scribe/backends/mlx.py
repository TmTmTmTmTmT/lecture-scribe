"""mlx-whisper 백엔드 (Apple Silicon, GPU 가속).

설치본 실측(mlx-whisper 0.4.3) 기준 faster-whisper와의 차이:

| 기능 | faster-whisper | mlx-whisper |
|---|---|---|
| `hotwords` | 지원 | **없음** (소스에 파라미터 자체가 없음) |
| `vad_filter` (Silero VAD) | 지원 | **없음** |
| `prompt_reset_on_temperature` | 지원 | 없음 |
| `initial_prompt` / `condition_on_previous_text` | 지원 | 지원 |
| `hallucination_silence_threshold` | 지원 | 지원 |
| temperature 폴백 체인 | 지원 | 지원 |
| 빔 서치(`beam_size`) | 지원 | **미구현** (그리디만) |
| 세그먼트 지연 생성(진행률) | 지원 | **없음** (전사 완료 후 한 번에 반환) |

hotwords가 없으므로 §F-03의 "지속 반영"은 mlx에서 `initial_prompt` +
`condition_on_previous_text`만으로 이루어진다. GUI는 `capabilities()`를 보고
hotwords 위젯을 비활성화해야 한다.
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

from ..errors import BackendUnavailableError, ModelLoadError, TranscriptionFailedError
from ..logsetup import get_logger
from .faster import _download_with_xet_fallback
from .base import (
    BackendCapabilities,
    Segment,
    StatusCallback,
    TranscriptionRequest,
    TranscriptionStream,
)

logger = get_logger(__name__)

BACKEND_NAME: Final[str] = "mlx"

#: Whisper 입력 샘플레이트.
_SAMPLE_RATE: Final[int] = 16000

#: 첫 창 길이(초). 짧게 잡아 첫 결과를 빨리 보여 준다.
_FIRST_WINDOW_SEC: Final[float] = 30.0

#: 창 하나가 도는 동안 살아있음 메시지를 보내는 주기(초). FIX_GUIDE_2.md N-02.
_HEARTBEAT_INTERVAL_SEC: Final[float] = 3.0

#: mlx-whisper의 모델 캐시(`transcribe.ModelHolder`)는 **프로세스 전역이고 락이 없다.**
#: 스레드 두 개가 동시에 진입하면 둘 다 `model is None`을 보고 각자 모델을 통째로
#: 로드해 메모리를 두 배로 쓰고, 여유가 없으면 양쪽 다 OOM으로 죽는다
#: (실측: GPU 백엔드로 여러 파일을 돌리면 전부 실패하던 원인).
#: 어차피 모델 인스턴스가 하나뿐이라 병렬로 돌려도 이득이 없으므로 직렬화한다.
_MLX_LOCK: Final[threading.Lock] = threading.Lock()

#: mlx는 float32로 모델을 올린다. 실측 상주치(GB).
_MLX_MODEL_GB: Final[dict[str, float]] = {
    "large-v3": 3.1,
    "large-v3-turbo": 1.7,
    "medium": 1.6,
    "small": 0.5,
    "base": 0.3,
    "tiny": 0.2,
}


def _model_memory_gb(model_name: str) -> float:
    for key, value in _MLX_MODEL_GB.items():
        if model_name.startswith(key):
            return value
    return 3.1

#: 모델 이름 -> mlx-community 리포지터리 (2026-09 기준 실제 존재 확인)
MLX_MODELS: Final[dict[str, str]] = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}


def model_repo(model_name: str) -> str:
    """모델 이름 -> HF 리포. 이미 리포 형태(`org/name`)면 그대로 쓴다."""
    if "/" in model_name:
        return model_name
    repo = MLX_MODELS.get(model_name)
    if repo is None:
        raise ModelLoadError(
            f"mlx 백엔드가 지원하지 않는 모델입니다: {model_name} "
            f"(사용 가능: {', '.join(MLX_MODELS)})",
            f"MLX_MODELS 매핑 없음: {model_name}",
        )
    return repo


class MlxWhisperBackend:
    """Apple Silicon GPU(Metal) 기반 mlx-whisper 백엔드."""

    def __init__(self, model_name: str = "large-v3", window_sec: float = 120.0) -> None:
        self._model_name = model_name
        self._repo = model_repo(model_name)
        self._ready = False
        self._tokenizer: Any | None = None
        #: 한 번에 넘길 오디오 길이(초). 짧을수록 진행률·취소가 촘촘해지지만
        #: 창 경계에서 문맥이 끊긴다. 2분이면 46분 파일에 23회 갱신된다.
        self._window_sec = window_sec

    @property
    def name(self) -> str:
        return BACKEND_NAME

    @property
    def model_name(self) -> str:
        return self._model_name

    def capabilities(self, request: TranscriptionRequest) -> BackendCapabilities:
        return BackendCapabilities(
            hotwords=False,  # 실측: 소스에 파라미터 없음
            condition_on_previous_text=True,
            prompt_reset_on_temperature=False,
            temperature_fallback=True,
            hallucination_silence_threshold=True,
            vad_filter=False,  # Silero VAD 미지원
            word_timestamps=True,
            batched=False,
            beam_search=False,  # 실측: NotImplementedError("Beam search decoder is not yet implemented")
            windowed_prompt_carry=True,  # FIX_GUIDE_4.md A-02: 창 단위로 나누는 유일한 백엔드
        )

    def ensure_loaded(self, on_status: StatusCallback | None = None) -> None:
        """가중치를 미리 내려받는다(전사 중 무반응 구간을 줄이기 위함)."""
        if self._ready:
            return
        try:
            import mlx_whisper  # noqa: F401
        except ImportError as exc:
            raise BackendUnavailableError(
                "mlx-whisper가 설치되어 있지 않습니다. `uv sync --extra mlx`를 실행하세요.",
                f"mlx_whisper import 실패: {exc}",
            ) from exc

        from ..perf import available_memory_gb, mlx_limit_cache

        # GPU 전사는 실패하면 Metal 안쪽에서 죽어 원인을 알 수 없는 오류가 난다.
        # 시작 전에 막고 무엇을 하면 되는지 알려 준다.
        needed = _model_memory_gb(self._model_name) + 1.5
        available = available_memory_gb()
        if 0 < available < needed:
            raise ModelLoadError(
                f"GPU 전사를 시작할 메모리가 부족합니다. "
                f"'{self._model_name}' 모델에 약 {needed:.1f}GB가 필요한데 "
                f"지금 쓸 수 있는 메모리는 {available:.1f}GB입니다. "
                f"다른 앱을 닫거나, 더 가벼운 모델(large-v3-turbo) 또는 "
                f"CPU 백엔드를 선택하세요.",
                f"mlx 사전 메모리 검사 실패: 필요 {needed:.1f}GB / 가용 {available:.1f}GB "
                f"model={self._model_name}",
            )
        mlx_limit_cache()

        if on_status is not None:
            on_status(f"모델 준비 중: {self._repo}")
        try:
            from huggingface_hub import snapshot_download

            _download_with_xet_fallback(lambda: snapshot_download(self._repo))
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadError(
                f"모델 '{self._model_name}' 을(를) 내려받지 못했습니다. "
                "네트워크 연결과 디스크 여유 공간을 확인하세요.",
                f"snapshot_download 실패 repo={self._repo}: {exc!r}",
            ) from exc
        self._ready = True
        if on_status is not None:
            on_status("모델 준비 완료")

    def unload(self) -> None:
        """전역 모델 캐시와 mlx 버퍼 캐시까지 실제로 비운다.

        자기 필드만 지우면 아무것도 반환되지 않는다. 메모리를 잡고 있는 주체는
        `mlx_whisper.transcribe.ModelHolder.model`과 mlx 내부 버퍼 캐시다
        (실측: 이것 때문에 실패한 전사의 메모리가 무한히 쌓였다).
        """
        from ..perf import mlx_release_model

        self._tokenizer = None
        self._ready = False
        with _MLX_LOCK:
            mlx_release_model()

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._tokenizer is None:
            try:
                from mlx_whisper.tokenizer import get_tokenizer

                self._tokenizer = get_tokenizer(
                    multilingual=True, language="ko", task="transcribe"
                )
            except ImportError as exc:
                raise BackendUnavailableError(
                    "mlx-whisper가 설치되어 있지 않습니다. `uv sync --extra mlx`를 실행하세요.",
                    f"mlx_whisper.tokenizer import 실패: {exc}",
                ) from exc
        return len(self._tokenizer.encoding.encode(text))

    def _decode_audio(self, audio_path: Path) -> Any:
        """오디오를 16kHz 모노 배열로 디코드한다.

        **경로를 넘기면 안 된다.** `mlx_whisper.audio.load_audio`는
        `["ffmpeg", ...]`를 맨 이름으로 실행한다(소스 주석: "Requires the ffmpeg
        CLI in PATH"). `.app` 번들이나 Quick Action은 PATH에 `/usr/bin:/bin:
        /usr/sbin:/sbin`만 상속받으므로 ffmpeg를 찾지 못하고
        `FileNotFoundError(2, 'ffmpeg')`로 죽는다 — GPU 백엔드만 즉시 실패하던 원인.

        faster-whisper가 쓰는 PyAV로 직접 디코드해 배열을 넘긴다. PyAV는 필수
        의존성이라 외부 ffmpeg가 아예 필요 없고, **파일 객체로 열어서** 넘기므로
        `9:4 캡스톤디자인.m4a`처럼 콜론이 든 이름도 안전하다.
        """
        try:
            from faster_whisper.audio import decode_audio
        except ImportError as exc:  # pragma: no cover - faster-whisper는 필수 의존성
            raise BackendUnavailableError(
                "오디오 디코더를 불러오지 못했습니다. `uv sync`를 실행하세요.",
                f"faster_whisper.audio import 실패: {exc}",
            ) from exc
        try:
            with audio_path.open("rb") as handle:
                return decode_audio(handle, sampling_rate=16000)
        except Exception as exc:  # noqa: BLE001 - PyAV 예외 종류가 다양함
            raise TranscriptionFailedError(
                f"오디오를 읽지 못했습니다: {audio_path.name}",
                f"PyAV 디코드 실패 {audio_path}: {exc!r}",
            ) from exc

    def transcribe(
        self,
        request: TranscriptionRequest,
        *,
        on_heartbeat: StatusCallback | None = None,
    ) -> TranscriptionStream:
        """전사 실행.

        `mlx_whisper.transcribe()`는 **지연 생성을 하지 않는다.** 파일 전체를 다
        돌린 뒤에야 반환한다(실측: 46분 파일에 400.7초). 그대로 쓰면 그 시간 내내
        진행률이 0%에 멈춰 있고 취소도 안 된다.

        그래서 오디오를 창(window) 단위로 잘라 여러 번 호출하고, 창마다 세그먼트를
        내보낸다. 진행률·취소가 창 경계에서 동작한다. 타임스탬프는 창 시작 시각만큼
        밀어 준다.
        """
        self.ensure_loaded()

        audio = self._decode_audio(request.audio_path)
        total_sec = len(audio) / _SAMPLE_RATE

        kwargs: dict[str, Any] = {
            "path_or_hf_repo": self._repo,
            "temperature": tuple(request.temperatures),
            "compression_ratio_threshold": request.compression_ratio_threshold,
            "logprob_threshold": request.log_prob_threshold,  # 이름이 다르다
            "no_speech_threshold": request.no_speech_threshold,
            "condition_on_previous_text": request.condition_on_previous_text,
            "initial_prompt": request.initial_prompt,
            "hallucination_silence_threshold": request.hallucination_silence_threshold,
            # FIX_GUIDE_4.md A-03: 기본값(2.0)이 이 옵션을 무조건 True로 켠다.
            # 실측(우리 backend.transcribe() 경로 그대로, 실사용 반복 루프가
            # 났던 구간 0~270초, condition_on_previous_text=True):
            #   hst=2.0  → 182.8~185.7초, 반복 최대 1~13회(표본마다 큰 편차)
            #   hst=None →  77.9초,       반복 최대 4회
            # 비용은 뚜렷하게(약 55~60%) 크지만, 반복/환각 억제 효과는 표본
            # 간 편차가 너무 커서 "있다/없다"를 가를 수 없었다(같은 hst=2.0인데
            # 13회 vs 1회). §8 "측정 없이 기본값 뒤집기 금지" 규정에 따라
            # 기본값은 유지한다 — 표본을 더 모으거나 Opus가 판단할 사안.
            "word_timestamps": (
                request.word_timestamps
                or request.hallucination_silence_threshold is not None
            ),
            "task": request.task,
        }
        # mlx-whisper 0.4.3은 빔 서치를 구현하지 않았다. beam_size를 넘기면
        # NotImplementedError가 난다. 그리디 디코딩으로 진행한다(경고는 capabilities에서).
        if request.language:
            kwargs["language"] = request.language

        # 첫 창만 미리 돌려 언어를 확정한다(스트림 메타데이터에 필요).
        window = max(60.0, float(self._window_sec))
        return TranscriptionStream(
            language=request.language or "",
            language_probability=1.0,  # mlx는 확률을 돌려주지 않는다
            duration_sec=total_sec,
            duration_after_vad_sec=total_sec,
            segments=self._stream_windows(
                audio, kwargs, request, window, on_heartbeat=on_heartbeat
            ),
        )

    def _stream_windows(
        self,
        audio: Any,
        kwargs: dict[str, Any],
        request: TranscriptionRequest,
        window_sec: float,
        *,
        on_heartbeat: StatusCallback | None = None,
    ) -> Iterator[Segment]:
        """오디오를 창 단위로 돌리며 세그먼트를 내보낸다."""
        import time

        import mlx_whisper

        from ..perf import available_memory_gb, mlx_release_model, swap_used_mb

        # 첫 창은 짧게 잡는다. 사용자가 결과를 빨리 보고 "멈춘 게 아니구나"를
        # 알 수 있어야 한다(첫 창에는 numba JIT 컴파일 비용도 얹힌다).
        step = int(window_sec * _SAMPLE_RATE)
        first_step = int(_FIRST_WINDOW_SEC * _SAMPLE_RATE)
        total = len(audio)
        offset = 0
        next_id = 0
        window_index = 0
        carry_prompt: str | None = kwargs.get("initial_prompt")
        try:
            while offset < total:
                span = first_step if offset == 0 else step
                chunk = audio[offset : offset + span]
                start_sec = offset / _SAMPLE_RATE
                call = dict(kwargs)
                call["initial_prompt"] = carry_prompt
                window_started = time.monotonic()
                # FIX_GUIDE_2.md N-02: 창 하나가 60~100초 넘게 걸리는 동안
                # 진행률·메시지가 전혀 안 움직여 "멈춘 것"처럼 보인다(사용자 보고).
                # 별도 스레드로 살아있음 메시지만 주기적으로 보낸다. 퍼센트는
                # 여기서 손대지 않는다 — 호출부(engine._run_transcription)가
                # 마지막 실제 값을 유지한 채 메시지만 갈아 끼운다.
                stop_heartbeat = threading.Event()
                heartbeat_thread: threading.Thread | None = None
                if on_heartbeat is not None:

                    def _tick(started: float = window_started) -> None:
                        # FIX_GUIDE_4.md A-06: 콜백(결국 Qt 시그널까지 이어짐)이
                        # 예외를 던지면 이 스레드가 조용히 죽어 하트비트가
                        # 영영 멈춘다 — N-02가 고치려던 "멈춘 것처럼 보임"이
                        # 되돌아온다. 예외는 1회만 로그로 남기고 계속 돈다.
                        warned = False
                        while not stop_heartbeat.wait(_HEARTBEAT_INTERVAL_SEC):
                            elapsed = time.monotonic() - started
                            try:
                                on_heartbeat(f"처리 중… (경과 {elapsed:.0f}초)")
                            except Exception:  # noqa: BLE001 - 하트비트는 부가 기능, 전사를 막지 않는다
                                if not warned:
                                    logger.exception("하트비트 콜백 실패 — 이후는 조용히 계속함")
                                    warned = True

                    heartbeat_thread = threading.Thread(
                        target=_tick, name="mlx-heartbeat", daemon=True
                    )
                    heartbeat_thread.start()
                try:
                    with _MLX_LOCK:
                        result = mlx_whisper.transcribe(chunk, **call)
                finally:
                    stop_heartbeat.set()
                    if heartbeat_thread is not None:
                        heartbeat_thread.join(timeout=1.0)
                window_elapsed = time.monotonic() - window_started
                raw = list(result.get("segments", []))
                # FIX_GUIDE_2.md N-05: 창 하나가 끝날 때마다 소요시간·온도 폴백
                # 여부·메모리 압박을 한 줄로 남긴다. 세그먼트 텍스트는 넣지 않는다
                # (전사 내용은 개인정보). 이 로그가 N-01/N-03 측정의 입력이다.
                max_temperature = max(
                    (_finite(r.get("temperature", 0.0), 0.0) for r in raw),
                    default=0.0,
                )
                logger.info(
                    "%s: 창 #%d [%.1f~%.1fs] 소요 %.1f초 · 세그먼트 %d개 · "
                    "최대 temperature %.1f · 가용 메모리 %.1fGB · 스왑 %.0fMB",
                    request.audio_path.name,
                    window_index,
                    start_sec,
                    start_sec + span / _SAMPLE_RATE,
                    window_elapsed,
                    len(raw),
                    max_temperature,
                    available_memory_gb(),
                    swap_used_mb(),
                )
                window_index += 1
                for segment in _convert(raw, request.audio_path, start_id=next_id):
                    next_id += 1
                    yield replace(
                        segment,
                        start=segment.start + start_sec,
                        end=segment.end + start_sec,
                    )
                # 다음 창이 문맥을 잇도록 마지막 문장을 프롬프트로 넘긴다.
                # FIX_GUIDE_4.md A-02: 이 창 경계 캐리는 `condition_on_previous_text`
                # (Whisper 내부 30초 서브청크 조건화, 위 kwargs로 이미 전달됨)와는
                # 별개 메커니즘이다 — 예전엔 같은 플래그 하나에 묶여 있어서 "속도·
                # 환각을 잡으려고 끄면 창 경계 문맥까지 같이 잃는" 양자택일이었다.
                if request.carry_window_prompt and raw:
                    tail = " ".join(str(r.get("text", "")) for r in raw[-2:]).strip()
                    carry_prompt = tail[-200:] or carry_prompt
                offset += span
        except GeneratorExit:
            # 소비 쪽에서 중단(취소)했다. GPU 메모리를 돌려준다.
            mlx_release_model()
            raise
        except Exception as exc:  # noqa: BLE001
            # 실패해도 GPU 메모리는 그대로 남는다. 여기서 반드시 돌려준다.
            mlx_release_model()
            self._ready = False
            raise TranscriptionFailedError(
                f"전사를 시작하지 못했습니다: {request.audio_path.name}",
                f"mlx_whisper.transcribe 실패 {request.audio_path}: {exc!r}",
            ) from exc


#: 신뢰도를 알 수 없을 때 쓰는 값. 기본 저신뢰 임계(-0.8)보다 낮게 잡아
#: `⟨?⟩` 마커가 붙도록 한다. 모르는 것을 "괜찮다"고 표시하지 않기 위함이다.
_UNKNOWN_LOGPROB: Final[float] = -1.0


def _finite(value: Any, fallback: float) -> float:
    """NaN/Inf를 유한값으로 바꾼다.

    mlx-whisper는 일부 세그먼트에 `NaN`을 돌려준다(실측: 46분 녹음 1,422개 중 22개).
    그대로 두면 세 가지가 조용히 망가진다.

    1. 평균이 통째로 `nan`이 된다(하나만 섞여도).
    2. `nan < -0.8`은 False라 **저신뢰 마커가 붙지 않는다** — 모르는 구간이
       멀쩡한 것처럼 보인다.
    3. 기록된 JSON에 맨 `NaN`이 들어가 **RFC 8259 위반**이 되고, 엄격한 파서를
       쓰는 도구는 사이드카를 아예 읽지 못한다(실측 확인).
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if math.isfinite(number) else fallback


def _convert(
    raw_segments: list[dict[str, Any]], audio_path: Path, start_id: int = 0
) -> Iterator[Segment]:
    """mlx-whisper 세그먼트(dict) -> 백엔드 중립 Segment.

    비유한값(NaN/Inf)은 여기서 걸러 낸다. 뒤쪽 코드가 전부 유한값을 가정한다.
    """
    coerced = 0
    try:
        for index, raw in enumerate(raw_segments):
            logprob = _finite(raw.get("avg_logprob", 0.0), _UNKNOWN_LOGPROB)
            if logprob != raw.get("avg_logprob", logprob):
                coerced += 1
            yield Segment(
                id=start_id + index,
                start=_finite(raw.get("start", 0.0), 0.0),
                end=_finite(raw.get("end", 0.0), 0.0),
                text=str(raw.get("text", "")),
                avg_logprob=logprob,
                no_speech_prob=_finite(raw.get("no_speech_prob", 0.0), 0.0),
                compression_ratio=_finite(raw.get("compression_ratio", 0.0), 0.0),
                temperature=_finite(raw.get("temperature", 0.0), 0.0),
            )
        if coerced:
            logger.warning(
                "%s: mlx가 %d/%d 세그먼트에 비유한 신뢰도(NaN)를 돌려줘 "
                "저신뢰(%.1f)로 처리했습니다.",
                audio_path.name,
                coerced,
                len(raw_segments),
                _UNKNOWN_LOGPROB,
            )
    except GeneratorExit:
        raise
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionFailedError(
            f"전사 결과를 해석하지 못했습니다: {audio_path.name}",
            f"mlx 세그먼트 변환 실패 {audio_path}: {exc!r}",
        ) from exc


def is_available() -> bool:
    """mlx-whisper 설치 여부(GUI 백엔드 선택지 비활성화용)."""
    try:
        import mlx_whisper  # noqa: F401
    except ImportError:
        return False
    return os.uname().machine == "arm64"
