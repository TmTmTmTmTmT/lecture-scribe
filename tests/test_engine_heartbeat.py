"""FIX_GUIDE_2.md 실행분 테스트: 창 하트비트(N-02), ETA 버스트 표본 회귀 수정(N-04).

FIX_GUIDE.md G-02(이동 평균 ETA)가 만든 회귀: mlx는 창 하나가 끝나면 세그먼트를
버스트로 한꺼번에 내보낸다. 세그먼트마다 표본을 찍으면 이동 구간(최근 8개)이
전부 같은 버스트 안에 들어가 벽시계 간격이 사실상 0이 되어 ETA가 터진다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from lecture_scribe.backends.base import (
    BackendCapabilities,
    Segment,
    StatusCallback,
    TranscriptionRequest,
    TranscriptionStream,
)
from lecture_scribe.engine import CancelToken, FileResult, ProgressEvent, _run_transcription


def _segment(index: int, end: float) -> Segment:
    return Segment(
        id=index,
        start=end - 1.0,
        end=end,
        text=f"세그먼트 {index}",
        avg_logprob=-0.2,
        no_speech_prob=0.01,
        compression_ratio=1.4,
        temperature=0.0,
    )


class _BurstyHeartbeatBackend:
    """mlx처럼 창 하나가 끝나야 세그먼트를 버스트로 내보내는 가짜 백엔드.

    창 진행 중에는 `on_heartbeat`를 호출하고, 창이 끝나면 세그먼트 여러 개를
    거의 동시(벽시계 기준)에 yield한다.
    """

    name = "fake-mlx"
    model_name = "fake"

    def __init__(self, clock: list[float]) -> None:
        self._clock = clock  # time.monotonic()이 순서대로 돌려줄 값들

    def capabilities(self, request: TranscriptionRequest) -> BackendCapabilities:
        return BackendCapabilities(
            hotwords=False,
            condition_on_previous_text=True,
            prompt_reset_on_temperature=False,
            temperature_fallback=True,
            hallucination_silence_threshold=True,
            vad_filter=False,
            word_timestamps=True,
            batched=False,
        )

    def ensure_loaded(self, on_status: StatusCallback | None = None) -> None:
        return None

    def transcribe(
        self,
        request: TranscriptionRequest,
        *,
        on_heartbeat: StatusCallback | None = None,
    ) -> TranscriptionStream:
        def _segments() -> Iterator[Segment]:
            # 창 #1: 60초 걸림, 하트비트 1번 온 뒤 세그먼트 3개가 버스트로 나온다.
            if on_heartbeat is not None:
                on_heartbeat("처리 중… (경과 30초)")
            yield _segment(0, 20.0)
            yield _segment(1, 40.0)
            yield _segment(2, 60.0)
            # 창 #2: 또 60초 걸림, 세그먼트 3개가 버스트로 나온다.
            if on_heartbeat is not None:
                on_heartbeat("처리 중… (경과 30초)")
            yield _segment(3, 80.0)
            yield _segment(4, 100.0)
            yield _segment(5, 120.0)

        return TranscriptionStream(
            language="ko",
            language_probability=1.0,
            duration_sec=120.0,
            duration_after_vad_sec=120.0,
            segments=_segments(),
        )

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def unload(self) -> None:
        return None


def _request() -> TranscriptionRequest:
    return TranscriptionRequest(audio_path=Path("fake.m4a"))


def test_heartbeat_keeps_last_percent_and_eta(monkeypatch: object) -> None:
    """하트비트는 메시지만 갱신하고 퍼센트/ETA는 마지막 실제 값을 유지해야 한다.

    추정치로 올리면 다음 실제 emit에서 그 값이 되감기는 것처럼 보인다
    (FIX_GUIDE_2.md N-02 — "하지 말 것" 4번).
    """
    # 창 경계마다 30초씩 벽시계가 흐른다고 가정: 하트비트 시점, 버스트 시점을
    # 충분히 떨어뜨려 N-04 표본 로직이 각 창을 별도 표본으로 잡게 한다.
    clock = iter([0.0, 30.0, 30.1, 30.2, 30.3, 60.0, 60.1, 60.2])

    import lecture_scribe.engine as engine_mod

    monkeypatch.setattr(engine_mod.time, "monotonic", lambda: next(clock))  # type: ignore[union-attr]

    events: list[ProgressEvent] = []
    backend = _BurstyHeartbeatBackend(clock=[])
    result = FileResult(audio_path=Path("fake.m4a"), status="failed")

    def emit(stage: str, percent: float, message: str = "", eta: float | None = None) -> None:
        events.append(
            ProgressEvent(file=Path("fake.m4a"), stage=stage, percent=percent, eta_sec=eta, message=message)
        )

    _run_transcription(
        backend,  # type: ignore[arg-type]
        _request(),
        result,
        CancelToken(),
        emit,
        base_percent=0.0,
    )

    heartbeat_events = [e for e in events if "경과" in e.message]
    assert heartbeat_events, "하트비트 이벤트가 하나도 없다 — on_heartbeat가 전달되지 않았다"

    # 첫 하트비트는 창 #1이 시작하기 전(아직 세그먼트 없음)이라 base_percent(0.0) 그대로.
    assert heartbeat_events[0].percent == 0.0

    # 두 번째 하트비트(창 #2 시작 전)는 창 #1의 마지막 실제 percent를 유지해야 한다.
    # 세그먼트가 없어야 하는데 추정으로 올라가면 회귀. ("전사 시작" 초기 이벤트는 제외)
    segment_events = [
        e for e in events if "경과" not in e.message and e.message != "전사 시작"
    ]
    assert segment_events, "세그먼트 이벤트가 없다"
    last_before_second_heartbeat_percent = segment_events[2].percent  # 창 #1의 마지막 세그먼트
    assert heartbeat_events[1].percent == last_before_second_heartbeat_percent


def test_burst_segments_do_not_collapse_eta_to_zero(monkeypatch: object) -> None:
    """창 하나가 끝나 세그먼트가 버스트(벽시계 간격 ~0)로 나와도 ETA가 0 근처로
    잘못 찍히면 안 된다(N-04). 표본은 창 경계 단위로만 찍혀야 한다.
    """
    # 창 #1은 t=30에 끝나며 세그먼트 3개가 사실상 동시(30.0, 30.001, 30.002)에 나온다.
    # 창 #2는 t=60에 끝나며 마찬가지로 버스트.
    clock = iter(
        [
            0.0,  # 하트비트(창1) — 사용 안 함, 세그먼트 이전
            30.0, 30.001, 30.002,  # 창 #1 버스트 3개
            30.0,  # 하트비트(창2)
            60.0, 60.001, 60.002,  # 창 #2 버스트 3개
        ]
    )

    import lecture_scribe.engine as engine_mod

    monkeypatch.setattr(engine_mod.time, "monotonic", lambda: next(clock))  # type: ignore[union-attr]

    events: list[ProgressEvent] = []
    backend = _BurstyHeartbeatBackend(clock=[])
    result = FileResult(audio_path=Path("fake.m4a"), status="failed")

    def emit(stage: str, percent: float, message: str = "", eta: float | None = None) -> None:
        events.append(
            ProgressEvent(file=Path("fake.m4a"), stage=stage, percent=percent, eta_sec=eta, message=message)
        )

    _run_transcription(
        backend,  # type: ignore[arg-type]
        _request(),
        result,
        CancelToken(),
        emit,
        base_percent=0.0,
    )

    segment_events = [
        e for e in events if "경과" not in e.message and e.message != "전사 시작"
    ]
    # 창 #2의 세그먼트들(오디오 진행은 계속되는데 창 내부 버스트라 dt≈0)에서
    # ETA가 극단적으로 작은 값(수 초 미만)으로 튀면 회귀 — 버스트 표본이 그대로
    # 이동 구간에 들어갔다는 뜻이다.
    burst_etas = [e.eta_sec for e in segment_events[3:] if e.eta_sec is not None]
    assert burst_etas, "창 #2에서 ETA가 하나도 안 나왔다"
    assert all(eta > 1.0 for eta in burst_etas), (
        f"버스트 표본이 이동 구간을 오염시켜 ETA가 비정상적으로 작다: {burst_etas}"
    )


def test_heartbeat_shows_cancelling_once_cancel_requested() -> None:
    """FIX_GUIDE_4.md A-07: 취소 후에는 하트비트가 "처리 중"을 덮어쓰면 안 된다.

    취소는 창 경계에서만 확인되므로(구 N-06) 창이 도는 동안 취소를 눌러도
    그 창의 하트비트는 계속 온다. 그 메시지가 계속 "처리 중…"이면 취소가
    안 먹힌 것처럼 보인다 — 취소 이후엔 "취소 중…"으로 바뀌어야 한다.
    """
    token = CancelToken()

    class _CancelDuringWindowBackend:
        name = "fake-mlx"
        model_name = "fake"

        def capabilities(self, request: TranscriptionRequest) -> BackendCapabilities:
            return BackendCapabilities(
                hotwords=False, condition_on_previous_text=True,
                prompt_reset_on_temperature=False, temperature_fallback=True,
                hallucination_silence_threshold=True, vad_filter=False,
                word_timestamps=True, batched=False,
            )

        def ensure_loaded(self, on_status: StatusCallback | None = None) -> None:
            return None

        def transcribe(
            self,
            request: TranscriptionRequest,
            *,
            on_heartbeat: StatusCallback | None = None,
        ) -> TranscriptionStream:
            def _segments() -> Iterator[Segment]:
                if on_heartbeat is not None:
                    on_heartbeat("처리 중… (경과 30초)")  # 취소 전
                yield _segment(0, 30.0)
                token.cancel()  # 사용자가 이 시점에 취소를 눌렀다고 가정
                if on_heartbeat is not None:
                    on_heartbeat("처리 중… (경과 30초)")  # 취소 후 — "취소 중"이어야 함
                yield _segment(1, 60.0)

            return TranscriptionStream(
                language="ko", language_probability=1.0,
                duration_sec=60.0, duration_after_vad_sec=60.0,
                segments=_segments(),
            )

        def count_tokens(self, text: str) -> int:
            return len(text.split())

        def unload(self) -> None:
            return None

    events: list[ProgressEvent] = []

    def emit(stage: str, percent: float, message: str = "", eta: float | None = None) -> None:
        events.append(
            ProgressEvent(file=Path("fake.m4a"), stage=stage, percent=percent, eta_sec=eta, message=message)
        )

    with pytest.raises(Exception):  # cancel.raise_if_cancelled()이 다음 세그먼트 확인 시 던짐
        _run_transcription(
            _CancelDuringWindowBackend(),  # type: ignore[arg-type]
            _request(),
            FileResult(audio_path=Path("fake.m4a"), status="failed"),
            token,
            emit,
            base_percent=0.0,
        )

    heartbeat_events = [e for e in events if "중" in e.message and "전사" not in e.message]
    assert len(heartbeat_events) == 2
    assert heartbeat_events[0].message == "처리 중… (경과 30초)", "취소 전엔 그대로여야 한다"
    assert heartbeat_events[1].message == "취소 중…", "취소 후엔 상태가 바뀌어야 한다"
