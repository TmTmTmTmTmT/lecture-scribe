"""config.py 스키마·마이그레이션·프리셋 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lecture_scribe.config import (
    SCHEMA_VERSION,
    CorrectionSettings,
    Preset,
    Settings,
    default_app_support_dir,
    load_settings,
    migrate,
    save_settings,
    settings_path,
)
from lecture_scribe.errors import ConfigError


def test_settings_path_follows_patched_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """회귀 테스트: `settings_path()`가 실제 사용자 파일을 절대 건드리지 않아야 한다.

    `Path.home()`을 실행 중에 다시 패치해도(예: `conftest.isolated_home`이 이미
    한 번 걸어 둔 것과 별개로) `settings_path()`가 그 값을 즉시 따라가는지 확인한다.
    이전엔 `SETTINGS_PATH`가 모듈 임포트 시점에 `Final` 상수로 굳어 있어, 나중에
    `Path.home()`을 패치해도 `load_settings()`/`save_settings()`가 여전히 실제
    `~/Library/Application Support/LectureScribe/settings.json`을 가리켰다
    (실측 확인됨 — 이 테스트가 그 회귀를 잡는다).
    """
    fake_home = Path("/private/tmp/lecture-scribe-settings-path-probe")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("LECTURE_SCRIBE_SETTINGS", raising=False)
    resolved = settings_path()
    assert resolved == fake_home / "Library" / "Application Support" / "LectureScribe" / "settings.json"
    assert resolved == default_app_support_dir() / "settings.json"


def test_load_and_save_settings_bare_call_does_not_touch_real_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """경로 없이 `load_settings()`/`save_settings()`를 불러도 (이미 패치된) 임시
    HOME 안에만 쓴다 — 실제 사용자 설정 파일이 존재하는지와 무관하게 통과해야 한다.
    """
    settings = Settings()
    save_settings(settings)  # path 생략 — 내부적으로 settings_path()를 쓴다
    resolved = settings_path()
    assert resolved.is_relative_to(Path.home())
    assert resolved.exists()
    loaded = load_settings()
    assert loaded.version == settings.version


def test_defaults_match_spec() -> None:
    settings = Settings()
    assert settings.version == SCHEMA_VERSION
    assert settings.backend == "faster"
    assert settings.model == "large-v3"
    assert settings.compute_type == "int8"
    assert settings.language == "ko"
    assert settings.output.formats == ["txt"]
    assert settings.output.on_conflict == "suffix"
    assert settings.prompt.max_prompt_tokens == 224
    assert settings.decoding.temperatures == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert settings.decoding.beam_size == 3  # 실측 기반 기본값(5 대비 27% 빠름)
    assert settings.cowork.low_confidence_marker == "⟨?⟩"
    # FIX_GUIDE_4.md A-02: 기본값은 기존 동작과 동일(둘 다 켬) — 구조만 분리했다.
    assert settings.prompt.condition_on_previous_text is True
    assert settings.prompt.carry_window_prompt is True
    # FIX_GUIDE_5.md B-01: 0.5 시도했으나 §5-1 게이트 실패(글자수 -1.82%, 반복 0->2) -> 0.6 유지
    assert settings.decoding.no_speech_threshold == 0.6
    # FIX_GUIDE_5.md B-02: 기본 켬 — 원문을 지우지 않고 표시만 하므로 켜서 손해가 없다.
    assert settings.postprocess.foreign_script_detection is True
    assert settings.postprocess.foreign_script_ratio == 0.3
    assert settings.postprocess.foreign_script_min_count == 2


def test_postprocess_foreign_script_settings_roundtrip(tmp_path: Path) -> None:
    """FIX_GUIDE_5.md B-02: 저장·복원에서 값이 유지돼야 한다."""
    path = tmp_path / "settings.json"
    settings = Settings.from_dict(
        {
            "postprocess": {
                "foreign_script_detection": False,
                "foreign_script_ratio": 0.5,
                "foreign_script_min_count": 3,
            }
        }
    )
    save_settings(settings, path)
    restored = load_settings(path)
    assert restored.postprocess.foreign_script_detection is False
    assert restored.postprocess.foreign_script_ratio == 0.5
    assert restored.postprocess.foreign_script_min_count == 3


def test_carry_window_prompt_roundtrips_independently_of_condition(
    tmp_path: Path,
) -> None:
    """FIX_GUIDE_4.md A-02: 두 값이 서로 다르게 저장·복원돼야 한다(묶여 있으면 안 됨)."""
    path = tmp_path / "settings.json"
    settings = Settings.from_dict(
        {
            "version": SCHEMA_VERSION,
            "prompt": {
                "condition_on_previous_text": False,
                "carry_window_prompt": True,
            },
        }
    )
    assert settings.prompt.condition_on_previous_text is False
    assert settings.prompt.carry_window_prompt is True
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.prompt.condition_on_previous_text is False
    assert loaded.prompt.carry_window_prompt is True


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.presets["마이크로파공학"] = Preset(
        topic="OO대학교 전기공학과 마이크로파공학 강의",
        glossary=["임피던스 정합", "스미스 차트"],
        corrections={"스미스차트": "스미스 차트"},
    )
    settings.active_preset = "마이크로파공학"
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.active_preset == "마이크로파공학"
    assert loaded.current_preset().glossary == ["임피던스 정합", "스미스 차트"]
    assert loaded.current_preset().corrections["스미스차트"] == "스미스 차트"


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "없음.json") == Settings()


def test_load_corrupt_file_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{이건 JSON이 아님", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(path)


def test_migrate_from_version_zero() -> None:
    migrated = migrate({"backend": "faster"})
    assert migrated["version"] == SCHEMA_VERSION


def test_migrate_v1_to_v2_disables_initial_prompt() -> None:
    """v1에서 켜져 있던 use_initial_prompt를 v2에서 끈다(실측 근거)."""
    migrated = migrate({"version": 1, "prompt": {"use_initial_prompt": True}})
    assert migrated["version"] == SCHEMA_VERSION
    assert migrated["prompt"]["use_initial_prompt"] is False


def test_migrate_v2_keeps_initial_prompt_choice() -> None:
    """v2 이후로는 사용자가 명시적으로 켠 값을 건드리지 않는다."""
    data = {"version": 2, "prompt": {"use_initial_prompt": True}}
    assert migrate(data)["prompt"]["use_initial_prompt"] is True


def test_migrate_v2_to_v3_adds_correction_section() -> None:
    """v3에서 correction 섹션이 생기되 **꺼진 채로** 내려가야 한다.

    Ollama가 없는 환경이 정상이므로 기존 사용자에게 켜진 채 배포되면 안 된다.
    """
    migrated = migrate({"version": 2, "prompt": {}})
    assert migrated["version"] == 3
    assert "correction" in migrated
    assert Settings.from_dict(migrated).correction.enabled is False


def test_load_v1_file_migrates(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"version": 1, "prompt": {"use_initial_prompt": True}}),
        encoding="utf-8",
    )
    settings = load_settings(path)
    assert settings.version == SCHEMA_VERSION
    assert settings.prompt.use_initial_prompt is False


def test_unknown_enum_values_fall_back() -> None:
    settings = Settings.from_dict(
        {
            "version": 1,
            "backend": "그런거없음",
            "language": "fr",
            "output": {"on_conflict": "explode", "formats": ["txt", "부적절"]},
        }
    )
    assert settings.backend == "faster"
    assert settings.language == "ko"
    assert settings.output.on_conflict == "suffix"
    assert settings.output.formats == ["txt"]


def test_active_preset_falls_back_to_existing() -> None:
    settings = Settings.from_dict(
        {"version": 1, "active_preset": "없는프리셋", "presets": {"A": {"topic": "t"}}}
    )
    assert settings.active_preset == "A"


def test_current_preset_never_raises() -> None:
    settings = Settings(active_preset="없음", presets={})
    assert settings.current_preset() == Preset()


def test_saved_json_is_utf8_and_readable(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.presets["한글이름"] = Preset(topic="주제")
    save_settings(settings, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert "한글이름" in raw["presets"]
    assert "\\u" not in path.read_text(encoding="utf-8")


def test_paths_expand_user() -> None:
    settings = Settings()
    assert settings.output.fallback_path.is_absolute()
    assert settings.cowork.workspace_path.is_absolute()
    assert settings.cowork.index_file.name == "index.jsonl"


def test_initial_prompt_disabled_by_default() -> None:
    """실측 근거: initial_prompt는 오디오 앞 구간 누락을 유발한다.

    hotwords만으로 용어 인식 효과는 유지되므로 기본값을 hotwords 단독으로 둔다.
    """
    settings = Settings()
    assert settings.prompt.use_initial_prompt is False
    assert settings.prompt.use_hotwords is True
    assert settings.prompt.fallback_on_collapse is True


def test_initial_prompt_can_be_re_enabled() -> None:
    """v2 이후 사용자가 명시적으로 켠 값은 유지된다(v1 값만 일괄 내림)."""
    settings = Settings.from_dict(
        {"version": SCHEMA_VERSION, "prompt": {"use_initial_prompt": True}}
    )
    assert settings.prompt.use_initial_prompt is True


# --- FIX_GUIDE_4.md A-01: 교정 host 검증 (전 과정 로컬 원칙) ---


@pytest.mark.parametrize(
    "host",
    [
        "http://localhost:11434",
        "http://127.0.0.1:11434",
        "http://127.0.0.1:9999",
        "http://[::1]:11434",
        "https://localhost:11434",
    ],
)
def test_correction_host_allows_local_addresses(host: str) -> None:
    settings = CorrectionSettings.from_dict({"host": host})
    assert settings.host == host


@pytest.mark.parametrize(
    "host",
    [
        "http://192.168.0.5:11434",
        "https://example.com",
        "http://evil.example.com:11434",
        "not a url at all",
    ],
)
def test_correction_host_rejects_remote_and_falls_back(
    host: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """전 과정 로컬 원칙(CLAUDE.md §목적) — 원격 host는 기본값으로 되돌리고 경고를 남긴다.

    검증 없이 통과시키면 config.json 한 줄로 전사문 전체가 조용히 외부로
    나갈 수 있다(correction.py propose()가 이 host로 POST한다).
    """
    monkeypatch.delenv("LECTURE_SCRIBE_ALLOW_REMOTE_CORRECTION", raising=False)
    with caplog.at_level("WARNING", logger="lecture_scribe.config"):
        settings = CorrectionSettings.from_dict({"host": host})
    assert settings.host == CorrectionSettings().host
    assert any("host" in r.message for r in caplog.records)


def test_correction_host_remote_allowed_with_env_escape_hatch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """탈출구: 사람이 직접 환경변수를 켰을 때만 원격 host를 허용하되 매번 경고한다."""
    monkeypatch.setenv("LECTURE_SCRIBE_ALLOW_REMOTE_CORRECTION", "1")
    with caplog.at_level("WARNING", logger="lecture_scribe.config"):
        settings = CorrectionSettings.from_dict({"host": "https://example.com"})
    assert settings.host == "https://example.com"
    assert any("전사문이" in r.message for r in caplog.records)


def test_video_settings_defaults_and_clamping() -> None:
    from lecture_scribe.config import VideoSettings

    base = Settings.from_dict({})
    assert base.video.change_threshold_pct == 10.0
    assert base.video.dedupe_threshold_pct == 3.0
    assert base.video.min_interval_sec == 5.0
    assert base.video.ocr_terms_to_prompt is False  # 효과 게이트(V-08) 통과 전까지 꺼 둠

    weird = VideoSettings.from_dict(
        {"change_threshold_pct": 500, "min_interval_sec": "abc", "max_frames": -3,
         "dedupe_threshold_pct": float("nan"), "jpeg_quality": 1000}
    )
    assert weird.change_threshold_pct == 90.0
    assert weird.min_interval_sec == 5.0
    assert weird.max_frames == 1
    assert weird.dedupe_threshold_pct == 3.0
    assert weird.jpeg_quality == 95


def test_video_settings_roundtrip(tmp_path: Path) -> None:
    settings = Settings.from_dict({"video": {"change_threshold_pct": 20, "capture_frames": False}})
    path = tmp_path / "s.json"
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.video.change_threshold_pct == 20.0
    assert loaded.video.capture_frames is False


def test_video_sheet_settings_defaults_clamping_and_roundtrip(tmp_path: Path) -> None:
    from lecture_scribe.config import VideoSettings

    base = Settings.from_dict({})
    assert base.video.sheets_enabled is True
    assert base.video.sheet_cols == 1 and base.video.sheet_rows == 2
    assert base.video.keep_single_frames is False

    weird = VideoSettings.from_dict({"sheet_cols": 0, "sheet_rows": 99})
    assert weird.sheet_cols == 1 and weird.sheet_rows == 3

    settings = Settings.from_dict(
        {"video": {"sheet_cols": 3, "sheet_rows": 1, "keep_single_frames": True}}
    )
    path = tmp_path / "s.json"
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.video.sheet_cols == 3 and loaded.video.sheet_rows == 1
    assert loaded.video.keep_single_frames is True


def test_correction_use_ocr_terms_defaults_off_and_roundtrips() -> None:
    from lecture_scribe.config import CorrectionSettings

    assert CorrectionSettings().use_ocr_terms is False
    assert CorrectionSettings.from_dict({}).use_ocr_terms is False
    assert CorrectionSettings.from_dict({"use_ocr_terms": True}).use_ocr_terms is True
