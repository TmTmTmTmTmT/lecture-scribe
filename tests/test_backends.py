"""백엔드 능력(capabilities) 노출 검증.

전사 정확도가 아니라 **어떤 옵션이 실제로 먹히는지**를 검증한다.
설치본 실측으로 확인한 사실을 코드가 그대로 반영하는지 보는 회귀 테스트다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lecture_scribe.backends.base import TranscriptionRequest
from lecture_scribe.backends.faster import FasterWhisperBackend


def make_request(**kwargs: object) -> TranscriptionRequest:
    base: dict[str, object] = {
        "audio_path": Path("강의.m4a"),
        "initial_prompt": "이번 시간에는 임피던스 정합을 다룹니다.",
        "hotwords": "임피던스 정합, 스미스 차트",
    }
    base.update(kwargs)
    return TranscriptionRequest(**base)  # type: ignore[arg-type]


# --- faster-whisper -----------------------------------------------------


def test_faster_sequential_supports_everything() -> None:
    backend = FasterWhisperBackend()
    caps = backend.capabilities(make_request())
    assert caps.hotwords
    assert caps.condition_on_previous_text
    assert caps.temperature_fallback
    assert caps.hallucination_silence_threshold
    assert caps.vad_filter
    assert caps.beam_search
    assert caps.ignored_options(make_request()) == []
    # FIX_GUIDE_4.md A-02: 창 단위로 나누지 않는 백엔드라 이 개념이 없다.
    assert caps.windowed_prompt_carry is False


def test_faster_batched_drops_anti_hallucination_options() -> None:
    """BatchedInferencePipeline이 내부에서 하드코딩으로 무시하는 항목들(실측)."""
    backend = FasterWhisperBackend()
    request = make_request(batched=True)
    caps = backend.capabilities(request)
    assert caps.hotwords is True
    assert caps.condition_on_previous_text is False
    assert caps.temperature_fallback is False
    assert caps.hallucination_silence_threshold is False
    ignored = caps.ignored_options(request)
    assert "condition_on_previous_text" in ignored
    assert "hallucination_silence_threshold" in ignored
    assert any("폴백 체인" in item for item in ignored)


def test_faster_ignored_options_is_never_silent() -> None:
    """무시되는 옵션이 있으면 반드시 목록으로 노출되어야 한다(§15-6)."""
    backend = FasterWhisperBackend()
    request = make_request(batched=True)
    assert backend.capabilities(request).ignored_options(request)


def test_faster_model_repo_mapping() -> None:
    from lecture_scribe.backends.faster import _model_repo

    assert _model_repo("large-v3") == "Systran/faster-whisper-large-v3"
    assert _model_repo("large-v3-turbo").endswith("faster-whisper-large-v3-turbo")


# --- mlx-whisper --------------------------------------------------------


def test_mlx_capabilities_reflect_missing_features() -> None:
    """mlx-whisper 0.4.3 실측: hotwords / VAD / 빔서치 / prompt_reset 없음."""
    from lecture_scribe.backends.mlx import MlxWhisperBackend

    backend = MlxWhisperBackend()
    request = make_request()
    caps = backend.capabilities(request)
    assert caps.hotwords is False
    assert caps.vad_filter is False
    assert caps.beam_search is False
    assert caps.prompt_reset_on_temperature is False
    assert caps.initial_prompt is True
    assert caps.condition_on_previous_text is True
    # FIX_GUIDE_4.md A-02: 창(120초) 단위로 나누는 유일한 백엔드.
    assert caps.windowed_prompt_carry is True

    ignored = caps.ignored_options(request)
    assert "hotwords" in ignored
    assert "vad_filter" in ignored
    assert any("빔 서치" in item for item in ignored)


def test_mlx_model_repo_mapping() -> None:
    from lecture_scribe.backends.mlx import model_repo

    assert model_repo("large-v3") == "mlx-community/whisper-large-v3-mlx"
    assert model_repo("large-v3-turbo") == "mlx-community/whisper-large-v3-turbo"
    assert model_repo("org/custom-model") == "org/custom-model"


def test_mlx_unknown_model_raises() -> None:
    from lecture_scribe.backends.mlx import model_repo
    from lecture_scribe.errors import ModelLoadError

    with pytest.raises(ModelLoadError):
        model_repo("없는모델")


# --- mlx: 외부 ffmpeg 의존 제거 -------------------------------------------------


def test_mlx_does_not_shell_out_to_ffmpeg() -> None:
    """`mlx_whisper.audio.load_audio`는 맨 이름 `ffmpeg`를 실행한다.

    `.app` 번들과 Quick Action은 PATH에 `/usr/bin:/bin:/usr/sbin:/sbin`만
    상속받아 ffmpeg를 찾지 못한다(실측: GPU 백엔드만 즉시 실패했다).
    경로 대신 PyAV로 디코드한 배열을 넘겨야 한다.
    """
    import inspect

    from lecture_scribe.backends import mlx as mlx_backend

    source = inspect.getsource(mlx_backend.MlxWhisperBackend.transcribe)
    streaming = inspect.getsource(mlx_backend.MlxWhisperBackend._stream_windows)
    assert "self._decode_audio(request.audio_path)" in source
    assert "mlx_whisper.transcribe(chunk" in streaming
    # 경로를 그대로 넘기면 안 된다
    assert "media_arg" not in source and "media_arg" not in streaming


def test_mlx_decode_uses_file_handle_not_path(tmp_path: Path) -> None:
    """콜론이 든 파일명(`9:4 캡스톤디자인.m4a`)도 안전해야 한다.

    경로 문자열을 디코더에 넘기면 `9:`을 프로토콜로 해석하는 문제가 재발한다.
    """
    import inspect

    from lecture_scribe.backends import mlx as mlx_backend

    source = inspect.getsource(mlx_backend.MlxWhisperBackend._decode_audio)
    assert 'audio_path.open("rb")' in source
    assert "decode_audio(handle" in source


def test_mlx_decode_reports_unreadable_file(tmp_path: Path) -> None:
    """읽을 수 없는 파일은 도메인 예외로 감싸 사용자 메시지를 준다."""
    from lecture_scribe.backends.mlx import MlxWhisperBackend
    from lecture_scribe.errors import TranscriptionFailedError

    broken = tmp_path / "깨진 파일.m4a"
    broken.write_bytes(b"not audio at all")
    backend = MlxWhisperBackend(model_name="large-v3-turbo")
    with pytest.raises(TranscriptionFailedError) as exc:
        backend._decode_audio(broken)
    assert "깨진 파일.m4a" in exc.value.user_message


# --- mlx: 창 단위 스트리밍 (진행률·취소) ------------------------------------------


def test_mlx_streams_in_windows_not_all_at_once() -> None:
    """`mlx_whisper.transcribe()`는 파일 전체를 다 돌린 뒤에야 반환한다.

    실측: 46분 파일에 400.7초. 그대로 쓰면 그 시간 내내 진행률이 0%에 멈춰 있고
    취소도 안 된다(실사용 보고). 창 단위로 잘라 여러 번 호출해야 한다.
    """
    import inspect

    from lecture_scribe.backends import mlx as mlx_backend

    source = inspect.getsource(mlx_backend.MlxWhisperBackend._stream_windows)
    assert "while offset < total" in source, "창 단위로 돌지 않는다"
    assert "yield" in source, "세그먼트를 지연 생성하지 않는다"
    assert "GeneratorExit" in source, "취소 경로에서 GPU 메모리를 안 돌려준다"


def test_mlx_first_window_is_shorter() -> None:
    """첫 결과가 빨리 나와야 사용자가 멈춘 게 아님을 안다(실측 33.5초 -> 5.3초)."""
    from lecture_scribe.backends.mlx import _FIRST_WINDOW_SEC

    from lecture_scribe.backends.mlx import MlxWhisperBackend

    backend = MlxWhisperBackend(model_name="large-v3-turbo")
    assert _FIRST_WINDOW_SEC < backend._window_sec


def test_mlx_window_offsets_are_applied() -> None:
    """창마다 타임스탬프를 창 시작 시각만큼 밀어야 한다."""
    import inspect

    from lecture_scribe.backends import mlx as mlx_backend

    source = inspect.getsource(mlx_backend.MlxWhisperBackend._stream_windows)
    assert "start=segment.start + start_sec" in source
    assert "end=segment.end + start_sec" in source


def test_mlx_segment_ids_are_continuous_across_windows() -> None:
    """창이 바뀌어도 세그먼트 id가 0부터 다시 시작하면 안 된다."""
    from pathlib import Path

    from lecture_scribe.backends.mlx import _convert

    first = list(_convert([{"text": "가"}, {"text": "나"}], Path("/tmp/a.m4a"), start_id=0))
    second = list(_convert([{"text": "다"}], Path("/tmp/a.m4a"), start_id=len(first)))
    assert [s.id for s in first + second] == [0, 1, 2]


# --- 용어집이 GPU에서도 전달되는가 -------------------------------------------------


class _NoHotwords:
    name = "mlx"

    def capabilities(self, request: object) -> object:
        from lecture_scribe.backends.base import BackendCapabilities

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

    def count_tokens(self, text: str) -> int:
        return len(text) // 2


def test_glossary_dropped_when_hotwords_unsupported_and_initial_prompt_off() -> None:
    """FIX_GUIDE.md G-03: mlx + hotwords 미지원 + initial_prompt 꺼짐(기본값) ->
    사용자가 끈 옵션을 조용히 재활성화하지 않는다. 용어집은 이번 전사에 적용 안 됨."""
    from lecture_scribe.config import Preset, Settings

    from lecture_scribe.engine import build_prompt_plan_for

    settings = Settings()
    settings.presets["기본"] = Preset(topic="통신 강의", glossary=["AWGN", "열잡음"])
    settings.active_preset = "기본"
    assert settings.prompt.use_initial_prompt is False  # 기본값 전제

    plan = build_prompt_plan_for(settings, _NoHotwords())  # type: ignore[arg-type]
    assert plan.hotwords is None
    assert not plan.initial_prompt, "사용자가 끈 옵션을 조용히 켜면 안 된다"


def test_glossary_routed_to_initial_prompt_when_user_opts_in() -> None:
    """같은 조건이라도 사용자가 'initial_prompt로 사용'을 직접 켜면 용어집이 전달된다."""
    from dataclasses import replace as dc_replace

    from lecture_scribe.config import Preset, Settings
    from lecture_scribe.engine import build_prompt_plan_for

    settings = Settings()
    settings.presets["기본"] = Preset(topic="통신 강의", glossary=["AWGN", "열잡음"])
    settings.active_preset = "기본"
    settings = dc_replace(
        settings, prompt=dc_replace(settings.prompt, use_initial_prompt=True)
    )

    plan = build_prompt_plan_for(settings, _NoHotwords())  # type: ignore[arg-type]
    assert plan.hotwords is None
    assert plan.initial_prompt, "동의했는데도 용어가 전달될 통로가 없다"
    assert "AWGN" in plan.initial_prompt
