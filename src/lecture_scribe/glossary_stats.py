"""FIX_GUIDE_7.md E-01/E-02: 자동 추가 용어의 등장 빈도 누적·감쇠·정렬.

GUI/백엔드 비의존 순수 함수 + 파일 I/O만 담당한다(CLAUDE.md 코딩 규칙 §코어 로직).
프리셋별로 "용어 -> 점수"와 "이 앱이 자동으로 넣은 용어" 목록을
`~/Library/Application Support/LectureScribe/glossary_stats.json`에 저장한다.

`config.py`의 `Settings`/`Preset`과는 **별도 파일**이다. `settings_panel.build_settings()`가
매번 `Preset`을 새로 만들며 알려진 필드만 옮겨 담기 때문에, 여기 넣으면 저장할 때마다
조용히 사라진다(FIX_GUIDE_7.md §2-1 참고). 통계는 이 파일 하나로 독립적으로 관리한다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

logger = logging.getLogger(__name__)


def default_stats_path() -> Path:
    """기본 저장 경로. **호출 시점에** `Path.home()`을 읽는다.

    `Final` 상수로 모듈 임포트 시점에 굳혀 두면, 테스트가 나중에 `Path.home`을
    패치해도 이미 계산된 값은 바뀌지 않아 실제 사용자 파일을 건드리게 된다
    (`config.py`의 `settings_path()`도 같은 함정에 빠져 있었다 — 이후 같은 패턴으로
    고쳤다. `default_app_support_dir()`/`default_log_dir()` 참고).
    호출부(`SettingsPanel`)는 매번 이 함수를 불러 경로를 얻는다.
    """
    return (
        Path.home() / "Library" / "Application Support" / "LectureScribe" / "glossary_stats.json"
    )


#: 참고/문서화용 기본값. 모듈 임포트 시점에 고정되므로 **런타임 기본값으로 쓰지 않는다**
#: — `load_stats`/`save_stats`의 함수 시그니처 기본값에도 `default_stats_path()`를 쓴다.
STATS_PATH: Final[Path] = default_stats_path()

#: 전사 1건마다 기존 점수에 곱하는 감쇠 계수. "최근 많이 나온 용어"를 만들기 위함 —
#: 시간이 아니라 전사 건수 단위로 감쇠한다(시계에 의존하지 않아 테스트가 쉽다).
DECAY: Final[float] = 0.8
#: 이 아래로 내려간 용어는 통계 파일에서 지운다(무한 증식 방지).
FLOOR: Final[float] = 0.1
#: 통계 파일 자체의 스키마 버전. `config.SCHEMA_VERSION`과는 무관하다 — 설정 스키마는
#: 건드리지 않는다.
_STATS_SCHEMA_VERSION: Final[int] = 1


@dataclass(slots=True)
class PresetGlossaryStats:
    """프리셋 1개의 자동 용어 통계."""

    #: 용어 -> 누적(감쇠 반영) 점수.
    scores: dict[str, float] = field(default_factory=dict)
    #: 현재 이 앱이 "자동으로 넣은 것"으로 취급하는 용어. 삭제 대상은 이 목록에
    #: 있는 것뿐이다 — 사용자가 직접 넣은 용어는 여기 없다.
    auto_added: set[str] = field(default_factory=set)


def load_stats(path: Path | None = None) -> dict[str, PresetGlossaryStats]:
    """통계 파일을 읽는다. 없거나 깨졌으면 빈 통계로 시작한다.

    통계는 편의 기능이지 산출물이 아니므로 여기서 예외를 던져 전사를 실패시키지 않는다.
    `path`를 생략하면 **호출 시점에** `default_stats_path()`를 계산한다(테스트 격리).
    """
    path = path or default_stats_path()
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("용어 통계 파일을 읽지 못해 빈 상태로 시작합니다: %s", exc)
        return {}
    try:
        raw: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.warning("용어 통계 파일이 손상되어 빈 상태로 시작합니다: %s", exc)
        return {}

    presets_raw = raw.get("presets", {})
    if not isinstance(presets_raw, dict):
        return {}
    result: dict[str, PresetGlossaryStats] = {}
    for name, data in presets_raw.items():
        if not isinstance(data, dict):
            continue
        scores_raw = data.get("scores", {})
        auto_raw = data.get("auto_added", [])
        if not isinstance(scores_raw, dict):
            continue
        try:
            scores = {str(word): float(score) for word, score in scores_raw.items()}
            auto_added = (
                {str(term) for term in auto_raw} if isinstance(auto_raw, list) else set()
            )
        except (TypeError, ValueError):
            continue
        result[str(name)] = PresetGlossaryStats(scores=scores, auto_added=auto_added)
    return result


def save_stats(stats: dict[str, PresetGlossaryStats], path: Path | None = None) -> None:
    """통계를 저장한다. 실패해도 예외를 올리지 않고 경고만 남긴다.

    `path`를 생략하면 **호출 시점에** `default_stats_path()`를 계산한다(테스트 격리).
    """
    path = path or default_stats_path()
    payload = {
        "version": _STATS_SCHEMA_VERSION,
        "presets": {
            name: {
                "scores": stat.scores,
                "auto_added": sorted(stat.auto_added),
            }
            for name, stat in stats.items()
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("용어 통계 파일 저장 실패: %s", exc)


def update_scores(
    existing: dict[str, float],
    detected: Sequence[tuple[str, int]],
    *,
    decay: float = DECAY,
    floor: float = FLOOR,
) -> dict[str, float]:
    """전사 1건이 끝날 때 점수를 감쇠하고 새 등장을 더한다.

    1. 기존 점수 전체에 `decay`를 곱한다(과거로 갈수록 가중치가 준다).
    2. 이번에 감지된 `(용어, 등장 구간 수)`를 더한다.
    3. `floor` 아래로 내려간 항목은 없앤다(파일 무한 증식 방지).
    """
    merged: dict[str, float] = {word: score * decay for word, score in existing.items()}
    for word, count in detected:
        merged[word] = merged.get(word, 0.0) + count
    return {word: score for word, score in merged.items() if score >= floor}


def order_glossary(
    user_terms: Sequence[str],
    auto_terms: Sequence[str],
    scores: dict[str, float],
) -> list[str]:
    """[사용자 용어 — 원래 순서] + [자동 추가분 — 점수 내림차순]으로 합친다.

    사용자가 친 용어의 순서는 절대 바꾸지 않는다. 자동 추가분만 재정렬한다.
    동점이면 원래 순서를 유지한다(`sorted`는 안정 정렬).
    """
    ranked_auto = sorted(auto_terms, key=lambda term: scores.get(term, 0.0), reverse=True)
    return list(user_terms) + ranked_auto
