"""FIX_GUIDE_2.md 실행분 테스트: 창 로그(N-05), 창 하트비트(N-02).

`mlx_whisper.transcribe()`를 실제로 돌리지 않고(모델 로드 없이) 가짜 함수로
바꿔치기해 `_stream_windows` 자체의 로깅·하트비트 동작만 검증한다.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from lecture_scribe.backends import mlx as mlx_backend
from lecture_scribe.backends.base import TranscriptionRequest


def _fake_audio(seconds: float) -> Any:
    return np.zeros(int(seconds * mlx_backend._SAMPLE_RATE), dtype=np.float32)


def _fake_result(temperature: float = 0.0, text: str = "안녕하세요") -> dict[str, Any]:
    return {
        "segments": [
            {
                "text": text,
                "start": 0.0,
                "end": 1.0,
                "avg_logprob": -0.2,
                "no_speech_prob": 0.01,
                "compression_ratio": 1.4,
                "temperature": temperature,
            }
        ]
    }


def test_window_loop_logs_one_line_per_window_without_segment_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """창마다 소요시간·세그먼트 수·최대 temperature·메모리를 로그로 남긴다(N-05).

    전사 내용(세그먼트 텍스트)은 개인정보이므로 로그에 들어가면 안 된다.
    """
    import mlx_whisper

    monkeypatch.setattr(
        mlx_whisper, "transcribe", lambda chunk, **kw: _fake_result(temperature=0.4, text="이 텍스트는 로그에 없어야 한다")
    )

    backend = mlx_backend.MlxWhisperBackend(model_name="large-v3-turbo", window_sec=60.0)
    request = TranscriptionRequest(audio_path=Path("강의.m4a"))
    kwargs: dict[str, Any] = {"initial_prompt": None}
    audio = _fake_audio(90.0)  # 첫 창(30초) + 다음 창(60초) = 창 2개

    with caplog.at_level(logging.INFO, logger="lecture_scribe.backends.mlx"):
        segments = list(backend._stream_windows(audio, kwargs, request, window_sec=60.0))

    assert len(segments) == 2, "창 2개 * 세그먼트 1개"

    window_logs = [r for r in caplog.records if "창 #" in r.message]
    assert len(window_logs) == 2, "창마다 로그 1줄이어야 한다"
    for record in window_logs:
        assert "소요" in record.message
        assert "세그먼트" in record.message
        assert "temperature" in record.message
        assert "가용 메모리" in record.message
        assert "스왑" in record.message
        assert "이 텍스트는 로그에 없어야 한다" not in record.message


def test_heartbeat_fires_while_window_call_is_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """창 하나가 하트비트 주기보다 오래 걸리면 그 사이에 최소 1번은 불려야 한다(N-02)."""
    monkeypatch.setattr(mlx_backend, "_HEARTBEAT_INTERVAL_SEC", 0.02)

    import mlx_whisper

    def _slow_transcribe(chunk: Any, **kw: Any) -> dict[str, Any]:
        time.sleep(0.08)  # 하트비트 주기(0.02초)보다 충분히 길게
        return _fake_result()

    monkeypatch.setattr(mlx_whisper, "transcribe", _slow_transcribe)

    backend = mlx_backend.MlxWhisperBackend(model_name="large-v3-turbo", window_sec=60.0)
    request = TranscriptionRequest(audio_path=Path("강의.m4a"))
    kwargs: dict[str, Any] = {"initial_prompt": None}
    audio = _fake_audio(30.0)  # 첫 창 하나만

    heartbeats: list[str] = []
    segments = list(
        backend._stream_windows(
            audio, kwargs, request, window_sec=60.0, on_heartbeat=heartbeats.append
        )
    )

    assert len(segments) == 1
    assert len(heartbeats) >= 1, "창이 도는 동안 하트비트가 한 번도 안 왔다"
    assert all("경과" in msg for msg in heartbeats)


def test_no_heartbeat_thread_when_callback_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """`on_heartbeat=None`이면 스레드를 만들지 않는다(불필요한 오버헤드 방지)."""
    import mlx_whisper

    monkeypatch.setattr(mlx_whisper, "transcribe", lambda chunk, **kw: _fake_result())

    backend = mlx_backend.MlxWhisperBackend(model_name="large-v3-turbo", window_sec=60.0)
    request = TranscriptionRequest(audio_path=Path("강의.m4a"))
    kwargs: dict[str, Any] = {"initial_prompt": None}
    audio = _fake_audio(30.0)

    # on_heartbeat 없이도 예외 없이 정상 동작해야 한다.
    segments = list(backend._stream_windows(audio, kwargs, request, window_sec=60.0))
    assert len(segments) == 1


def test_heartbeat_callback_exception_does_not_kill_transcription(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """FIX_GUIDE_4.md A-06: 콜백이 예외를 던져도 전사 자체는 끝까지 간다.

    이전에는 하트비트 스레드가 예외로 조용히 죽어(로그도 없이) 이후 하트비트가
    전부 멈췄다 — N-02가 고치려던 "멈춘 것처럼 보임"이 되돌아오는 회귀였다.
    """
    monkeypatch.setattr(mlx_backend, "_HEARTBEAT_INTERVAL_SEC", 0.02)

    import mlx_whisper

    def _slow_transcribe(chunk: Any, **kw: Any) -> dict[str, Any]:
        time.sleep(0.08)
        return _fake_result()

    monkeypatch.setattr(mlx_whisper, "transcribe", _slow_transcribe)

    backend = mlx_backend.MlxWhisperBackend(model_name="large-v3-turbo", window_sec=60.0)
    request = TranscriptionRequest(audio_path=Path("강의.m4a"))
    kwargs: dict[str, Any] = {"initial_prompt": None}
    audio = _fake_audio(30.0)

    def _boom(message: str) -> None:
        raise RuntimeError("콜백 실패(테스트)")

    with caplog.at_level(logging.ERROR, logger="lecture_scribe.backends.mlx"):
        segments = list(
            backend._stream_windows(
                audio, kwargs, request, window_sec=60.0, on_heartbeat=_boom
            )
        )

    assert len(segments) == 1, "하트비트 콜백이 죽어도 전사 결과는 나와야 한다"
    assert any("하트비트" in r.message for r in caplog.records), "예외가 로그에 안 남았다"


# --- FIX_GUIDE_4.md A-02: carry_window_prompt와 condition_on_previous_text 분리 ---


def test_carry_window_prompt_independent_of_condition_on_previous_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 값이 서로 다른 걸 제어해야 한다 — 하나로 묶여 있으면 안 된다.

    이전에는 `condition_on_previous_text` 하나가 ①mlx_whisper에 전달하는 내부
    서브청크 조건화와 ②우리 창 경계 캐리 프롬프트를 동시에 켰다/껐다 했다.
    `carry_window_prompt=True, condition_on_previous_text=False` 조합에서
    캐리는 여전히 일어나야 하고, mlx_whisper에는 여전히 False가 전달돼야 한다.
    """
    import mlx_whisper

    calls: list[dict[str, Any]] = []

    def _record(chunk: Any, **kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return _fake_result(text=f"세그먼트{len(calls)}")

    monkeypatch.setattr(mlx_whisper, "transcribe", _record)

    backend = mlx_backend.MlxWhisperBackend(model_name="large-v3-turbo", window_sec=60.0)
    request = TranscriptionRequest(
        audio_path=Path("강의.m4a"),
        condition_on_previous_text=False,  # 내부 서브청크 조건화는 끔
        carry_window_prompt=True,  # 창 경계 캐리는 유지
    )
    kwargs: dict[str, Any] = {
        "initial_prompt": None,
        "condition_on_previous_text": False,
    }
    audio = _fake_audio(90.0)  # 창 2개(첫 30초 + 60초)

    list(backend._stream_windows(audio, kwargs, request, window_sec=60.0))

    assert len(calls) == 2
    # mlx_whisper에는 매 창 condition_on_previous_text=False가 그대로 전달돼야 한다
    assert all(c["condition_on_previous_text"] is False for c in calls)
    # 그런데도 창 경계 캐리는 일어나야 한다 — 두 번째 호출의 initial_prompt가
    # 첫 창 결과("세그먼트1")를 반영해야 한다.
    assert calls[0]["initial_prompt"] is None
    assert calls[1]["initial_prompt"] == "세그먼트1"


def test_carry_window_prompt_false_stops_carry_even_with_condition_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """반대 조합: 캐리만 끄면 내부 조건화는 그대로, 창 경계 캐리만 멈춘다."""
    import mlx_whisper

    calls: list[dict[str, Any]] = []

    def _record(chunk: Any, **kw: Any) -> dict[str, Any]:
        calls.append(kw)
        return _fake_result(text=f"세그먼트{len(calls)}")

    monkeypatch.setattr(mlx_whisper, "transcribe", _record)

    backend = mlx_backend.MlxWhisperBackend(model_name="large-v3-turbo", window_sec=60.0)
    request = TranscriptionRequest(
        audio_path=Path("강의.m4a"),
        condition_on_previous_text=True,
        carry_window_prompt=False,  # 창 경계 캐리만 끔
    )
    kwargs: dict[str, Any] = {"initial_prompt": "고정 프롬프트", "condition_on_previous_text": True}
    audio = _fake_audio(90.0)

    list(backend._stream_windows(audio, kwargs, request, window_sec=60.0))

    assert len(calls) == 2
    # 캐리가 꺼졌으므로 두 창 모두 원래 initial_prompt를 그대로 유지해야 한다
    assert calls[0]["initial_prompt"] == "고정 프롬프트"
    assert calls[1]["initial_prompt"] == "고정 프롬프트"
