"""비유한값(NaN/Inf) 방어.

mlx-whisper는 일부 세그먼트에 `NaN`을 돌려준다(실측: 46분 녹음 1,422개 중 22개).
그대로 두면 세 가지가 **조용히** 망가진다.

1. 평균이 통째로 `nan`이 된다(하나만 섞여도).
2. `nan < threshold`는 항상 False라 저신뢰 마커가 붙지 않는다.
3. 기록된 JSON에 맨 `NaN`이 들어가 RFC 8259 위반이 되고, 엄격한 파서는
   사이드카를 아예 읽지 못한다.
"""

from __future__ import annotations

import json
import math

import pytest

from conftest import make_segment
from lecture_scribe.writer import (
    dump_json,
    is_low_confidence,
    low_confidence_ratio,
    render_json,
)


def _strict_loads(raw: str) -> object:
    """엄격한 파서 흉내. NaN/Infinity를 허용하지 않는다."""

    def reject(constant: str) -> object:
        raise ValueError(f"허용되지 않는 상수: {constant}")

    return json.loads(raw, parse_constant=reject)


# --- 1) 평균 오염 -------------------------------------------------------------


def test_one_nan_does_not_poison_average() -> None:
    from lecture_scribe.engine import summarize_segments

    segments = [
        make_segment(0, 0.0, 3.0, "정상", avg_logprob=-0.3),
        make_segment(1, 3.0, 6.0, "NaN", avg_logprob=math.nan),
        make_segment(2, 6.0, 9.0, "정상", avg_logprob=-0.5),
    ]
    count, mean = summarize_segments(segments)
    assert count == 3
    assert math.isfinite(mean), "NaN 하나에 평균 전체가 오염됐다"
    assert mean == pytest.approx(-0.4)


def test_file_result_average_ignores_nan() -> None:
    from pathlib import Path

    from lecture_scribe.engine import FileResult

    result = FileResult(audio_path=Path("/tmp/a.m4a"), status="ok")
    result.segments = [
        make_segment(0, 0.0, 3.0, "a", avg_logprob=-0.2),
        make_segment(1, 3.0, 6.0, "b", avg_logprob=math.nan),
    ]
    assert result.avg_logprob == pytest.approx(-0.2)


def test_all_nan_gives_zero_not_nan() -> None:
    from lecture_scribe.engine import summarize_segments

    segments = [make_segment(i, 0.0, 1.0, "x", avg_logprob=math.nan) for i in range(3)]
    _, mean = summarize_segments(segments)
    assert mean == 0.0


# --- 2) 저신뢰 마커 누락 --------------------------------------------------------


def test_nan_counts_as_low_confidence() -> None:
    """신뢰도를 모르는 구간을 멀쩡한 것처럼 표시하면 안 된다."""
    segment = make_segment(0, 0.0, 3.0, "모름", avg_logprob=math.nan)
    assert is_low_confidence(segment, -0.8), "NaN이 고신뢰로 통과했다"


def test_nan_included_in_low_confidence_ratio() -> None:
    segments = [
        make_segment(0, 0.0, 3.0, "정상", avg_logprob=-0.2),
        make_segment(1, 3.0, 6.0, "모름", avg_logprob=math.nan),
    ]
    assert low_confidence_ratio(segments, -0.8) == pytest.approx(0.5)


# --- 3) 무효한 JSON -----------------------------------------------------------


def test_render_json_never_emits_nan() -> None:
    segments = [
        make_segment(0, 0.0, 3.0, "정상", avg_logprob=-0.3),
        make_segment(1, 3.0, 6.0, "모름", avg_logprob=math.nan),
    ]
    raw = render_json(segments, {"avg_logprob": math.nan, "model": "large-v3"})
    assert "NaN" not in raw
    parsed = _strict_loads(raw)  # 엄격한 파서로도 읽혀야 한다
    assert isinstance(parsed, dict)
    assert parsed["avg_logprob"] is None
    assert parsed["segments"][1]["avg_logprob"] is None


def test_dump_json_rejects_infinity_too() -> None:
    raw = dump_json({"a": math.inf, "b": -math.inf, "c": [math.nan, 1.0]})
    assert "Infinity" not in raw and "NaN" not in raw
    parsed = _strict_loads(raw)
    assert parsed == {"a": None, "b": None, "c": [None, 1.0]}


def test_dump_json_keeps_normal_values() -> None:
    payload = {"n": -0.3391, "s": "글자", "l": [1, 2], "d": {"k": True}, "z": None}
    assert _strict_loads(dump_json(payload)) == payload


# --- 백엔드 경계에서의 정화 -------------------------------------------------------


def test_mlx_convert_coerces_nan_to_low_confidence() -> None:
    from pathlib import Path

    from lecture_scribe.backends.mlx import _UNKNOWN_LOGPROB, _convert

    raw = [
        {"id": 0, "start": 0.0, "end": 3.0, "text": "정상", "avg_logprob": -0.3},
        {"id": 1, "start": 3.0, "end": 6.0, "text": "NaN", "avg_logprob": float("nan")},
        {"id": 2, "start": 6.0, "end": 9.0, "text": "Inf", "avg_logprob": float("inf")},
    ]
    segments = list(_convert(raw, Path("/tmp/a.m4a")))
    assert all(math.isfinite(s.avg_logprob) for s in segments)
    assert segments[1].avg_logprob == _UNKNOWN_LOGPROB
    assert segments[2].avg_logprob == _UNKNOWN_LOGPROB
    # 모르는 것은 저신뢰로 표시되어야 한다
    assert is_low_confidence(segments[1], -0.8)


def test_mlx_convert_sanitises_every_numeric_field() -> None:
    from pathlib import Path

    from lecture_scribe.backends.mlx import _convert

    raw = [
        {
            "id": 0,
            "start": float("nan"),
            "end": float("inf"),
            "text": "x",
            "avg_logprob": float("nan"),
            "no_speech_prob": float("nan"),
            "compression_ratio": float("nan"),
            "temperature": float("nan"),
        }
    ]
    segment = list(_convert(raw, Path("/tmp/a.m4a")))[0]
    for field in (
        segment.start,
        segment.end,
        segment.avg_logprob,
        segment.no_speech_prob,
        segment.compression_ratio,
        segment.temperature,
    ):
        assert math.isfinite(field)
