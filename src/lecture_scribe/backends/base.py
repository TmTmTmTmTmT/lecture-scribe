"""TranscriptionBackend 프로토콜과 공용 데이터 구조.

백엔드마다 지원하는 파라미터가 다르므로(예: mlx-whisper에는 hotwords가 없음)
능력 차이를 `BackendCapabilities`로 명시 노출한다. GUI는 이 값으로 위젯을
비활성화하고, CLI는 무시되는 옵션에 대해 경고를 남긴다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

# 모델 로드/다운로드 등 오래 걸리는 단계의 상태 알림 콜백
StatusCallback = Callable[[str], None]


@dataclass(slots=True, frozen=True)
class Segment:
    """백엔드 중립 세그먼트."""

    id: int
    start: float
    end: float
    text: str
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    temperature: float


@dataclass(slots=True)
class TranscriptionRequest:
    """전사 1회 요청. 백엔드가 이해할 수 있는 형태로 정규화된 값만 담는다."""

    audio_path: Path
    language: str | None = None  # None = 자동 감지
    task: str = "transcribe"

    # --- 프롬프트 (F-03) ---
    initial_prompt: str | None = None
    hotwords: str | None = None
    condition_on_previous_text: bool = True
    #: FIX_GUIDE_4.md A-02: mlx 전용 개념. `condition_on_previous_text`와
    #: 분리된 별도 필드다 — mlx.py 참조. 창 단위로 나누지 않는 백엔드
    #: (faster-whisper)는 무시한다.
    carry_window_prompt: bool = True
    prompt_reset_on_temperature: float = 0.5

    # --- 디코딩 / 환각 억제 (F-04) ---
    beam_size: int = 5
    temperatures: list[float] = field(
        default_factory=lambda: [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    )
    compression_ratio_threshold: float = 2.4
    log_prob_threshold: float = -1.0
    no_speech_threshold: float = 0.6
    vad_filter: bool = True
    min_silence_duration_ms: int = 500
    hallucination_silence_threshold: float | None = 2.0
    word_timestamps: bool = False

    # --- 실행 모드 ---
    batched: bool = False
    batch_size: int = 8


@dataclass(slots=True)
class TranscriptionStream:
    """전사 시작 직후 확보되는 메타데이터 + 지연 세그먼트 이터레이터.

    `segments`는 지연 생성이다. 소비를 중단(close)하면 전사도 중단된다.
    """

    language: str
    language_probability: float
    duration_sec: float
    duration_after_vad_sec: float
    segments: Iterator[Segment]


@dataclass(slots=True, frozen=True)
class BackendCapabilities:
    """백엔드가 실제로 지원하는 기능. 설치본 실측 기준으로 채운다."""

    hotwords: bool
    condition_on_previous_text: bool
    prompt_reset_on_temperature: bool
    temperature_fallback: bool
    hallucination_silence_threshold: bool
    vad_filter: bool
    word_timestamps: bool
    batched: bool
    initial_prompt: bool = True
    beam_search: bool = True
    #: 같은 모델 인스턴스로 여러 파일을 동시에 전사할 수 있는지
    #: (CTranslate2는 num_workers로 지원, mlx는 미검증이라 False)
    parallel_transcribe: bool = False
    #: FIX_GUIDE_4.md A-02: `carry_window_prompt`가 실제로 의미 있는 백엔드인지.
    #: 창 단위로 나누지 않는 백엔드(faster-whisper)는 이 개념 자체가 없다 —
    #: GUI가 이 값으로 관련 설정을 회색으로 비활성화한다.
    windowed_prompt_carry: bool = False

    def ignored_options(self, request: TranscriptionRequest) -> list[str]:
        """요청 값 중 이 백엔드/모드에서 무시될 항목 이름 목록.

        조용히 무시하면 안 되므로(§15) 호출부가 경고를 남기는 데 쓴다.
        """
        ignored: list[str] = []
        if request.hotwords and not self.hotwords:
            ignored.append("hotwords")
        if request.condition_on_previous_text and not self.condition_on_previous_text:
            ignored.append("condition_on_previous_text")
        if not self.prompt_reset_on_temperature:
            ignored.append("prompt_reset_on_temperature")
        if len(request.temperatures) > 1 and not self.temperature_fallback:
            ignored.append("temperature(폴백 체인)")
        if (
            request.hallucination_silence_threshold is not None
            and not self.hallucination_silence_threshold
        ):
            ignored.append("hallucination_silence_threshold")
        if request.beam_size > 1 and not self.beam_search:
            ignored.append(f"beam_size={request.beam_size}(빔 서치 미구현, 그리디 사용)")
        if request.vad_filter and not self.vad_filter:
            ignored.append("vad_filter")
        return ignored


@runtime_checkable
class TranscriptionBackend(Protocol):
    """전사 백엔드 공통 인터페이스."""

    @property
    def name(self) -> str:
        """백엔드 식별자 (`faster` / `mlx`)."""

    @property
    def model_name(self) -> str:
        """로드된(또는 로드할) 모델 이름."""

    def capabilities(self, request: TranscriptionRequest) -> BackendCapabilities:
        """요청 모드(batched 여부 등)에 따른 실제 능력."""

    def ensure_loaded(self, on_status: StatusCallback | None = None) -> None:
        """모델 다운로드/로드. 이미 로드되어 있으면 아무 일도 하지 않는다."""

    def transcribe(
        self,
        request: TranscriptionRequest,
        *,
        on_heartbeat: StatusCallback | None = None,
    ) -> TranscriptionStream:
        """전사 시작. 세그먼트는 지연 생성된다.

        `on_heartbeat`: 세그먼트가 나오지 않는 구간(mlx의 창 하나가 도는 동안 등)에
        "멈춘 게 아니다"를 알리는 콜백(FIX_GUIDE_2.md N-02). 진행률 자체는 바꾸지
        않는다 — 호출부가 메시지만 갱신한다. 세그먼트 단위로 이미 진행이 나오는
        백엔드(faster-whisper)는 무시해도 된다.
        """

    def count_tokens(self, text: str) -> int:
        """모델 토크나이저 기준 토큰 수(프롬프트 예산 계산용)."""

    def unload(self) -> None:
        """모델을 메모리에서 내린다(유휴 시 메모리 반환용)."""
