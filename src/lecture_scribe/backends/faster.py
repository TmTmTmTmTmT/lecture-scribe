"""faster-whisper 백엔드 (기본).

설치본 실측(faster-whisper 1.2.1 / transcribe.py) 기준 주의점:

1. `BatchedInferencePipeline.transcribe`는 내부적으로
   `condition_on_previous_text=False`, `hallucination_silence_threshold=None`,
   `temperature[:1]`(폴백 체인 제거)을 하드코딩한다. 즉 배치 모드에서는 §F-04의
   환각 억제 장치 3종이 동작하지 않는다. 그래서 기본은 순차 모드다.
2. `hallucination_silence_threshold`는 `word_timestamps=True`일 때만 효과가 있다.
3. `WhisperModel.get_prompt`은 hotwords와 previous_tokens를 함께 넣으므로
   `condition_on_previous_text=True`와 hotwords 병행이 가능하다(순차 모드).
4. 배치 모드는 initial_prompt를 매 배치 윈도우에 다시 넣는다(주제 유지에 유리).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final

from ..audio import media_arg
from ..errors import BackendUnavailableError, ModelLoadError, TranscriptionFailedError
from ..logsetup import get_logger
from ..logsetup import get_logger
from .base import (
    BackendCapabilities,
    Segment,
    StatusCallback,
    TranscriptionRequest,
    TranscriptionStream,
)

logger = get_logger(__name__)

logger = get_logger(__name__)

BACKEND_NAME: Final[str] = "faster"

# Whisper 컨텍스트 448 토큰의 절반 - 1 = 223 (faster-whisper `max_length // 2 - 1`)
PROMPT_TOKEN_HARD_LIMIT: Final[int] = 223


#: faster-whisper 내장 목록에 없는 추가 모델(별칭 -> HF 리포).
#: CTranslate2로 변환된 리포여야 그대로 로드된다.
#: 한국어 파인튜닝 모델은 실측 결과 강의 오디오에서 출력이 붕괴해 뺐다.
EXTRA_MODELS: Final[dict[str, str]] = {}


def _model_repo(model_name: str) -> str:
    """모델 이름 -> Hugging Face 리포지터리 id.

    내장 별칭 -> EXTRA_MODELS 별칭 -> (그 외는) 입력값 그대로(리포 id로 간주).
    """
    try:
        from faster_whisper.utils import _MODELS
    except ImportError:  # pragma: no cover - 설치본 구조가 바뀐 경우
        return EXTRA_MODELS.get(model_name, model_name)
    repo = _MODELS.get(model_name) or EXTRA_MODELS.get(model_name)
    return str(repo) if repo else model_name


class FasterWhisperBackend:
    """CPU/int8 기반 faster-whisper 백엔드."""

    def __init__(
        self,
        model_name: str = "large-v3",
        compute_type: str = "int8",
        device: str = "cpu",
        cpu_threads: int = 0,
        num_workers: int = 1,
        download_root: Path | None = None,
    ) -> None:
        self._model_name = model_name
        self._compute_type = compute_type
        self._device = device
        self._cpu_threads = cpu_threads
        self._num_workers = max(1, num_workers)
        self._download_root = download_root
        self._model: Any | None = None
        self._pipeline: Any | None = None
        self._standalone_tokenizer: Any | None = None

    # --- 식별 ---

    @property
    def name(self) -> str:
        return BACKEND_NAME

    @property
    def model_name(self) -> str:
        return self._model_name

    # --- 능력 ---

    def capabilities(self, request: TranscriptionRequest) -> BackendCapabilities:
        """배치 모드 여부에 따라 실제 지원 항목이 달라진다(실측 기준)."""
        if request.batched:
            return BackendCapabilities(
                hotwords=True,
                condition_on_previous_text=False,  # 내부 하드코딩 False
                prompt_reset_on_temperature=False,  # 내부 하드코딩 0.5
                temperature_fallback=False,  # temperature[:1]
                hallucination_silence_threshold=False,  # 내부 하드코딩 None
                vad_filter=True,
                word_timestamps=True,
                batched=True,
                beam_search=True,
                parallel_transcribe=self._num_workers > 1,
            )
        return BackendCapabilities(
            hotwords=True,
            condition_on_previous_text=True,
            prompt_reset_on_temperature=True,
            temperature_fallback=True,
            hallucination_silence_threshold=True,
            vad_filter=True,
            word_timestamps=True,
            batched=False,
            beam_search=True,
            parallel_transcribe=self._num_workers > 1,
        )

    # --- 모델 로드 ---

    def ensure_loaded(self, on_status: StatusCallback | None = None) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise BackendUnavailableError(
                "faster-whisper가 설치되어 있지 않습니다. `uv sync`를 실행하세요.",
                f"faster_whisper import 실패: {exc}",
            ) from exc

        if on_status is not None:
            on_status(f"모델 준비 중: {self._model_name} ({self._compute_type})")
        # cpu_threads=0은 CTranslate2가 전체 코어를 쓴다는 뜻이다. num_workers까지
        # 곱해지면 10코어에 스레드 20개가 몰려 UI 스레드가 기아 상태가 되고 창이
        # "응답 없음"으로 멈춘다(실측). 코어 몇 개는 남긴다.
        from ..perf import usable_cpu_threads

        threads = usable_cpu_threads(self._cpu_threads, self._num_workers)
        logger.info(
            "모델 로드 %s: cpu_threads=%d num_workers=%d",
            self._model_name,
            threads,
            self._num_workers,
        )

        def _create() -> None:
            self._model = WhisperModel(
                _model_repo(self._model_name),
                device=self._device,
                compute_type=self._compute_type,
                cpu_threads=threads,
                num_workers=self._num_workers,
                download_root=(
                    str(self._download_root) if self._download_root else None
                ),
            )

        try:
            _download_with_xet_fallback(_create)
        except Exception as exc:  # noqa: BLE001 - 라이브러리 예외 종류가 다양함
            raise ModelLoadError(
                f"모델 '{self._model_name}' 을(를) 불러오지 못했습니다. "
                "네트워크 연결과 디스크 여유 공간을 확인하세요.",
                f"WhisperModel 생성 실패 model={self._model_name} "
                f"device={self._device} compute={self._compute_type}: {exc!r}",
            ) from exc
        if on_status is not None:
            on_status("모델 로드 완료")

    def unload(self) -> None:
        """모델을 메모리에서 내린다(실측: large-v3에서 약 1.6GB 반환)."""
        if self._model is None and self._pipeline is None:
            return
        self._pipeline = None
        self._model = None
        from ..perf import release_memory

        freed = release_memory()
        logger.info("모델 해제: %s (%.0fMB 반환)", self._model_name, freed)

    def _ensure_pipeline(self) -> Any:
        if self._pipeline is None:
            from faster_whisper import BatchedInferencePipeline

            self._pipeline = BatchedInferencePipeline(model=self._model)
        return self._pipeline

    # --- 토큰 카운트 ---

    def count_tokens(self, text: str) -> int:
        """모델 토크나이저 기준 토큰 수.

        모델이 아직 로드되지 않았으면 tokenizer.json만 내려받아 계산한다
        (수 MB, GUI 실시간 표시용).
        """
        if not text:
            return 0
        tokenizer = self._tokenizer()
        return len(tokenizer.encode(text).ids)

    def _tokenizer(self) -> Any:
        if self._model is not None:
            return self._model.hf_tokenizer
        if self._standalone_tokenizer is not None:
            return self._standalone_tokenizer
        try:
            import tokenizers
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(_model_repo(self._model_name), "tokenizer.json")
            self._standalone_tokenizer = tokenizers.Tokenizer.from_file(path)
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadError(
                "토크나이저를 준비하지 못했습니다. 네트워크 연결을 확인하세요.",
                f"tokenizer.json 다운로드 실패 model={self._model_name}: {exc!r}",
            ) from exc
        return self._standalone_tokenizer

    # --- 전사 ---

    def transcribe(
        self,
        request: TranscriptionRequest,
        *,
        on_heartbeat: StatusCallback | None = None,
    ) -> TranscriptionStream:
        # faster-whisper는 세그먼트를 실시간으로 지연 생성하므로(FIX_GUIDE.md 표
        # 참조) 창 단위로 진행이 얼어붙는 mlx의 문제(N-02)가 없다. 인터페이스
        # 일관성을 위해 매개변수만 받고 쓰지 않는다.
        del on_heartbeat
        self.ensure_loaded()
        assert self._model is not None  # ensure_loaded 이후 보장

        caps = self.capabilities(request)
        # hallucination_silence_threshold는 word_timestamps=True에서만 동작한다(실측).
        want_hallucination = (
            request.hallucination_silence_threshold is not None
            and caps.hallucination_silence_threshold
        )
        word_timestamps = request.word_timestamps or want_hallucination

        kwargs: dict[str, Any] = {
            "language": request.language,
            "task": request.task,
            "beam_size": request.beam_size,
            "temperature": request.temperatures,
            "compression_ratio_threshold": request.compression_ratio_threshold,
            "log_prob_threshold": request.log_prob_threshold,
            "no_speech_threshold": request.no_speech_threshold,
            "initial_prompt": request.initial_prompt,
            "hotwords": request.hotwords,
            "condition_on_previous_text": request.condition_on_previous_text,
            "prompt_reset_on_temperature": request.prompt_reset_on_temperature,
            "vad_filter": request.vad_filter,
            "vad_parameters": {
                "min_silence_duration_ms": request.min_silence_duration_ms
            },
            "word_timestamps": word_timestamps,
        }
        if caps.hallucination_silence_threshold:
            kwargs["hallucination_silence_threshold"] = (
                request.hallucination_silence_threshold
            )

        try:
            if request.batched:
                pipeline = self._ensure_pipeline()
                kwargs["batch_size"] = request.batch_size
                raw_segments, info = pipeline.transcribe(
                    media_arg(request.audio_path), **kwargs
                )
            else:
                raw_segments, info = self._model.transcribe(
                    media_arg(request.audio_path), **kwargs
                )
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionFailedError(
                f"전사를 시작하지 못했습니다: {request.audio_path.name}",
                f"transcribe 호출 실패 {request.audio_path}: {exc!r}",
            ) from exc

        return TranscriptionStream(
            language=str(info.language),
            language_probability=float(info.language_probability),
            duration_sec=float(info.duration),
            duration_after_vad_sec=float(info.duration_after_vad),
            segments=_convert(raw_segments, request.audio_path),
        )


def _download_with_xet_fallback(download: "Callable[[], object]") -> None:
    """HF 모델 다운로드 실행. Xet(CAS) 전송 오류면 Xet을 끄고 1회 재시도한다.

    huggingface_hub의 Xet 가속 전송이 네트워크 환경에 따라
    `CAS Client Error: Request middleware error`로 실패하는 사례가 있다
    (2026-09 실측, mlx-community/whisper-large-v3-mlx 2회 연속 실패 ->
    HF_HUB_DISABLE_XET=1로 성공). 사용자가 원인을 알기 어려우므로 자동 우회한다.
    """
    try:
        download()
        return
    except Exception as exc:  # noqa: BLE001
        message = repr(exc)
        if "CAS" not in message and "Xet" not in message and "xet" not in message:
            raise
        logger.warning("HF Xet 전송 실패. HF_HUB_DISABLE_XET=1로 재시도합니다: %s", exc)
    previous = os.environ.get("HF_HUB_DISABLE_XET")
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    try:
        download()
    finally:
        if previous is None:
            os.environ.pop("HF_HUB_DISABLE_XET", None)
        else:
            os.environ["HF_HUB_DISABLE_XET"] = previous


def _convert(raw_segments: Any, audio_path: Path) -> Iterator[Segment]:
    """faster-whisper 세그먼트를 백엔드 중립 Segment로 변환(지연)."""
    try:
        for raw in raw_segments:
            yield Segment(
                id=int(raw.id),
                start=float(raw.start),
                end=float(raw.end),
                text=str(raw.text),
                avg_logprob=float(raw.avg_logprob),
                no_speech_prob=float(raw.no_speech_prob),
                compression_ratio=float(raw.compression_ratio),
                temperature=float(raw.temperature if raw.temperature is not None else 0.0),
            )
    except GeneratorExit:  # 소비자가 취소한 경우 조용히 종료
        raise
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionFailedError(
            f"전사 도중 오류가 발생했습니다: {audio_path.name}",
            f"세그먼트 생성 실패 {audio_path}: {exc!r}",
        ) from exc


def default_download_root() -> Path | None:
    """모델 캐시 위치. 환경변수가 있으면 그 값을 쓴다."""
    env = os.environ.get("LECTURE_SCRIBE_MODEL_DIR")
    return Path(os.path.expanduser(env)) if env else None
