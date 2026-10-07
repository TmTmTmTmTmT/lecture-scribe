"""시작 시 외부 의존성(ffmpeg/Ollama/gemma) 점검 — GUI 비의존 순수 함수.

`gui/startup_dialog.py`가 이 결과로 대화상자를 그린다. 여기서는 판정만 하고
Qt를 쓰지 않는다(코딩 규칙 §"GUI/백엔드 비의존" 취지 — 이 모듈은 로직만).

무엇을 확인하는가(전부 로컬, 네트워크 호출 없음 — Ollama 데몬 확인만 localhost):
1. ffmpeg / ffprobe — 없으면 전사 자체가 안 된다(가장 흔한 최초 실행 실패, TROUBLESHOOTING.md).
2. Ollama 실행 파일 — 없으면 교정 기능 자체를 못 켠다.
3. Ollama 데몬 — 켜져 있는지(꺼져 있으면 `ensure_running()`으로 띄울 수 있음).
4. gemma 교정 모델(`CORRECTION_MODELS`) — 받아져 있는지.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from .. import audio
from ..correction import CORRECTION_MODELS, OllamaClient, _model_stem, find_ollama
from ..errors import FFmpegNotFoundError

#: 점검 결과에 붙는 후속 동작. 대화상자가 이 값으로 버튼을 고른다.
#: - "show_command": 설치 명령을 보여주고 복사만 시킨다(직접 실행 안 함 — 이 앱이
#:   사용자 승인 없이 brew/설치 프로그램을 돌리지 않는다는 원칙).
#: - "start_ollama": 이미 설치된 실행 파일을 그냥 띄운다(다운로드 없음, 안전).
#: - "pull_model": `ollama pull <model>`을 실행한다(다운로드 있음 — 버튼 클릭 자체가
#:   사용자 승인이다).
Action = Literal["show_command", "start_ollama", "pull_model", None]


@dataclass(slots=True, frozen=True)
class DependencyItem:
    """점검 결과 1건."""

    key: str
    label: str
    ok: bool
    detail: str
    action: Action = None
    #: `action`이 "show_command"일 때 보여줄 셸 명령. 그 외엔 무의미.
    command: str = ""
    #: `action`이 "pull_model"일 때 받을 모델 이름.
    model: str = ""


#: 데몬 응답 대기 타임아웃(초). 로컬호스트라 느릴 이유가 없어 짧게 잡는다.
_ALIVE_TIMEOUT_SEC: Final[float] = 1.5


def _check_ffmpeg_family(name: str, brew_hint: str) -> DependencyItem:
    try:
        path = audio.find_binary(name)
    except FFmpegNotFoundError:
        return DependencyItem(
            key=name,
            label=name,
            ok=False,
            detail=f"{name}을(를) 찾지 못했습니다.",
            action="show_command",
            command=brew_hint,
        )
    return DependencyItem(key=name, label=name, ok=True, detail=str(path))


def check_dependencies() -> list[DependencyItem]:
    """전부 점검해 결과 목록을 돌려준다. 실패해도 예외를 던지지 않는다.

    호출부(스플래시 대화상자)가 "문제 없음"이면 아예 안 띄울 수 있게, 항목마다
    `ok`를 명시한다.
    """
    items: list[DependencyItem] = [
        _check_ffmpeg_family("ffmpeg", "brew install ffmpeg"),
        _check_ffmpeg_family("ffprobe", "brew install ffmpeg"),
    ]

    ollama_path = find_ollama()
    if ollama_path is None:
        items.append(
            DependencyItem(
                key="ollama",
                label="Ollama",
                ok=False,
                detail="교정(오인식 제안) 기능에 필요합니다. 없어도 전사는 정상 동작합니다.",
                action="show_command",
                command="brew install ollama",
            )
        )
        # 실행 파일이 없으면 데몬·모델 점검은 의미가 없다.
        return items

    items.append(
        DependencyItem(key="ollama", label="Ollama", ok=True, detail=str(ollama_path))
    )

    client = OllamaClient()
    daemon_alive = client.alive(_ALIVE_TIMEOUT_SEC)
    items.append(
        DependencyItem(
            key="ollama_daemon",
            label="Ollama 데몬",
            ok=daemon_alive,
            detail="실행 중" if daemon_alive else "꺼져 있습니다.",
            action=None if daemon_alive else "start_ollama",
        )
    )
    if not daemon_alive:
        # 데몬이 꺼져 있으면 모델 목록 자체를 못 읽는다 — 모델 항목은 "확인 불가"로 둔다.
        for model in CORRECTION_MODELS:
            items.append(
                DependencyItem(
                    key=f"model:{model}",
                    label=f"교정 모델 {model}",
                    ok=False,
                    detail="Ollama 데몬을 먼저 실행해야 확인할 수 있습니다.",
                )
            )
        return items

    try:
        installed = set(client.models())
    except Exception:  # noqa: BLE001 - 점검 실패로 앱을 못 열게 하면 안 된다
        installed = set()

    installed_stems = {_model_stem(name) for name in installed}

    def _has(model: str) -> bool:
        return _model_stem(model) in installed_stems

    for model in CORRECTION_MODELS:
        present = _has(model)
        items.append(
            DependencyItem(
                key=f"model:{model}",
                label=f"교정 모델 {model}",
                ok=present,
                detail="받아져 있습니다." if present else "아직 안 받았습니다.",
                action=None if present else "pull_model",
                model=model,
            )
        )
    return items


def has_any_problem(items: list[DependencyItem]) -> bool:
    return any(not item.ok for item in items)


__all__ = ["DependencyItem", "check_dependencies", "has_any_problem"]
