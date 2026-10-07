"""워크스페이스 미러 (§10.4).

원본 저장 규칙(F-05: 오디오와 같은 위치)은 그대로 두고, 전사물을 작업 폴더에도
배치한다. Cowork 세션은 특정 폴더 기준으로 동작하므로 iCloud·외장 볼륨·수업별
폴더에 흩어진 결과를 한 곳에 모아야 접근이 편하다.

- 기본 `hardlink`. 볼륨이 달라 하드링크가 불가하면 **자동으로 copy로 강등**하고 로그를 남긴다.
- 미러 폴더 안에서는 파일명 충돌이 잦다(여러 수업의 `week01.md`).
  `<상위폴더명>__<basename>.md` 형태로 접두어를 붙여 피한다.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import MirrorMode
from .logsetup import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class MirrorResult:
    """미러 1건 결과."""

    source: Path
    target: Path
    mode: MirrorMode
    downgraded_from: MirrorMode | None = None


def mirror_filename(source: Path, audio_path: Path) -> str:
    """`<상위폴더명>__<basename>.<ext>`. 상위 폴더가 없으면 basename만."""
    parent = audio_path.parent.name
    if not parent or parent in {"/", "."}:
        return source.name
    safe_parent = parent.replace("/", "_").strip()
    return f"{safe_parent}__{source.name}"


def _place(source: Path, target: Path, mode: MirrorMode) -> MirrorMode:
    """실제 배치. 하드링크 실패 시 copy로 강등하고 사용한 모드를 돌려준다."""
    if target.exists() or target.is_symlink():
        target.unlink()
    if mode == "hardlink":
        try:
            target.hardlink_to(source)
            return "hardlink"
        except OSError as exc:
            logger.warning(
                "하드링크 불가(볼륨이 다르거나 파일시스템 미지원) %s -> %s: %s. copy로 진행합니다.",
                source,
                target,
                exc,
            )
            shutil.copy2(source, target)
            return "copy"
    if mode == "symlink":
        try:
            target.symlink_to(source)
            return "symlink"
        except OSError as exc:
            logger.warning("심볼릭 링크 실패 %s: %s. copy로 진행합니다.", target, exc)
            shutil.copy2(source, target)
            return "copy"
    shutil.copy2(source, target)
    return "copy"


def mirror_outputs(
    outputs: list[Path],
    audio_path: Path,
    workspace_dir: Path,
    mode: MirrorMode = "hardlink",
) -> list[MirrorResult]:
    """전사물들을 워크스페이스로 미러링한다. 실패는 로그만 남기고 넘어간다."""
    results: list[MirrorResult] = []
    if not outputs:
        return results
    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("워크스페이스 폴더를 만들 수 없습니다 %s: %s", workspace_dir, exc)
        return results

    for source in outputs:
        if not source.exists():
            continue
        target = workspace_dir / mirror_filename(source, audio_path)
        try:
            used = _place(source, target, mode)
        except OSError as exc:
            logger.warning("미러 실패 %s -> %s: %s", source, target, exc)
            continue
        results.append(
            MirrorResult(
                source=source,
                target=target,
                mode=used,
                downgraded_from=mode if used != mode else None,
            )
        )
        logger.info("미러: %s -> %s (%s)", source.name, target, used)
    return results
