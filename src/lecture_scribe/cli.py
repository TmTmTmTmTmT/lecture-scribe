"""명령줄 진입점 (Quick Action / 자동화 / 에이전트 호출용).

스트림 분리 원칙:
- stdout: `--json` / `--stdout` 결과 전용
- stderr: 진행률·로그·경고 전부
- stdin 입력이나 확인 질문은 어떤 경로에서도 요구하지 않는다.

종료 코드: 0 전체 성공 / 1 일부 실패 / 2 전체 실패 / 130 사용자 취소
"""

from __future__ import annotations

import argparse
import io
import json
import re
import logging
import signal
import sys
from dataclasses import asdict, replace
from pathlib import Path
from collections.abc import Callable
from types import FrameType
from typing import Any, TextIO

from . import __version__
from .audio import collect_inputs, probe_duration
from .backends.base import TranscriptionBackend
from .config import MODEL_NAMES, Preset, Settings, VideoSettings, load_settings
from .engine import (
    CancelToken,
    FileResult,
    QueueEvent,
    build_meta,
    build_prompt_plan_for,
    run_queue,
)
from .notify import notify_completion, notify_start
from .perf import (
    QOS_CLASS_USER_INITIATED,
    QOS_CLASS_UTILITY,
    check_memory_headroom,
    hide_from_dock,
    set_thread_qos,
)
from .errors import LectureScribeError
from .prompt import parse_glossary
from .writer import render_txt
from .logsetup import get_logger, setup_logging
from .provenance import log_startup

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_ALL_FAILED = 2
EXIT_CANCELLED = 130

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lecture-scribe",
        description="강의 녹음 로컬 전사 (LectureScribe)",
    )
    parser.add_argument("files", nargs="+", type=Path, help="오디오/영상 파일 또는 폴더")
    parser.add_argument("--topic", default=None, help="전사 주제 문장")
    parser.add_argument(
        "--preset", default=None, help="저장된 프리셋 이름 (--topic보다 우선순위 낮음)"
    )
    parser.add_argument("--glossary", default=None, help="용어 목록, 쉼표 구분")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="주제/용어 프롬프트를 쓰지 않고 전사(붕괴 의심 시 비교용)",
    )
    parser.add_argument(
        "--initial-prompt",
        action="store_true",
        help=(
            "주제 문장을 initial_prompt로 사용(기본 꺼짐). "
            "앞 구간이 누락되는 사례가 있어 기본값은 hotwords 단독이다."
        ),
    )
    parser.add_argument(
        "--no-initial-prompt",
        action="store_true",
        help="initial_prompt를 명시적으로 끈다(기본값과 동일)",
    )
    parser.add_argument(
        "--no-hotwords", action="store_true", help="hotwords만 끄고 initial_prompt는 유지"
    )
    parser.add_argument(
        "--no-prompt-fallback",
        action="store_true",
        help="프롬프트 부작용이 감지돼도 재전사하지 않는다(A/B 비교용)",
    )
    parser.add_argument(
        "--no-repeat-glossary",
        action="store_true",
        help="용어를 initial_prompt 문장에 중복해서 넣지 않는다(프롬프트를 짧게 유지)",
    )
    parser.add_argument(
        "--fuzzy", action="store_true", help="rapidfuzz 유사도 용어 교정 사용"
    )
    parser.add_argument("--fuzzy-threshold", type=int, default=None)
    parser.add_argument("--language", choices=["ko", "en", "auto"], default=None)
    parser.add_argument("--model", default=None, help=f"모델 이름 {MODEL_NAMES}")
    parser.add_argument("--backend", choices=["faster", "mlx"], default=None)
    parser.add_argument("--compute-type", default=None, help="int8 / int8_float32 / float32 등")
    parser.add_argument("--output-dir", type=Path, default=None, help="기본: 원본과 동일 위치")
    parser.add_argument(
        "--on-conflict", choices=["overwrite", "suffix", "skip"], default=None
    )
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=["txt", "md", "srt", "vtt", "json"],
        help="출력 포맷(반복 지정 가능). 기본: 설정값",
    )
    parser.add_argument(
        "--progress-json",
        action="store_true",
        help="진행 상황을 JSON Lines로 stderr에 출력",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="최종 결과를 단일 JSON 객체로 stdout에 출력(에이전트 호출용)",
    )
    parser.add_argument(
        "--stdout",
        dest="text_stdout",
        action="store_true",
        help="파일을 쓰지 않고 전사 텍스트만 stdout에 출력",
    )
    parser.add_argument(
        "--notify", action="store_true", help="완료 시 macOS 알림 표시"
    )
    parser.add_argument("--timestamps", dest="timestamps", action="store_true", default=None)
    parser.add_argument("--no-timestamps", dest="timestamps", action="store_false")
    parser.add_argument(
        "--batched",
        action="store_true",
        help=(
            "BatchedInferencePipeline 사용(빠름). 단, 설치본 실측상 "
            "condition_on_previous_text / hallucination_silence_threshold / "
            "temperature 폴백 체인이 무시된다."
        ),
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--beam-size",
        type=int,
        default=None,
        help="빔 크기(기본 설정값 5). 3으로 낮추면 실측 27%% 빨라지고 품질 차이는 근소하다",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=None,
        metavar="N",
        help="동시에 전사할 파일 수(기본 2). 모델을 공유하므로 메모리는 약 10%%만 는다. 1이면 순차",
    )
    parser.add_argument(
        "--low-priority",
        action="store_true",
        help="다른 작업에 양보한다(기본은 사용자 대기 작업 우선순위)",
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=None,
        help="0=자동(권장). 실측상 효율 코어까지 쓰면 오히려 느려진다",
    )
    parser.add_argument("--recursive", action="store_true", help="폴더 입력 시 하위 폴더까지 탐색")
    parser.add_argument(
        "--emit-handoff",
        action="store_true",
        help="후속 작업용 컨텍스트 파일(<basename>.handoff.md) 생성",
    )
    parser.add_argument(
        "--split-md",
        type=int,
        default=0,
        metavar="MIN",
        help="md 출력을 MIN분 단위 파일로 분할(기본 비활성)",
    )
    parser.add_argument(
        "--open-gui",
        action="store_true",
        help="전사하지 않고 GUI를 띄워 파일을 큐에 적재한다(Quick Action용)",
    )
    parser.add_argument(
        "--correct",
        action="store_true",
        help=(
            "전사 후 로컬 LLM(Ollama gemma4)으로 오인식 교정을 제안한다. "
            "전사문은 고치지 않고 `원문[→교정]` 주석과 <basename>.corrections.json을 낸다"
        ),
    )
    parser.add_argument(
        "--no-correct",
        action="store_true",
        help="설정에서 켜져 있어도 이번 실행에서는 교정을 건너뛴다",
    )
    parser.add_argument(
        "--correct-model",
        default=None,
        metavar="NAME",
        help=(
            "교정 모델(기본 gemma4:e4b). 실측 정확도 e4b 89% / e2b 71%, "
            "속도는 e2b가 약 1.7배 빠르다"
        ),
    )
    parser.add_argument(
        "--correct-confidence",
        choices=("low", "medium", "high"),
        default=None,
        help="채택할 최소 신뢰도(기본 medium)",
    )
    parser.add_argument(
        "--correct-ocr-terms",
        dest="correct_ocr_terms",
        action="store_true",
        default=None,
        help="영상 슬라이드에서 뽑은 용어를 이 파일의 교정 프롬프트에 참고로 추가(기본 꺼짐)",
    )
    parser.add_argument(
        "--no-correct-ocr-terms",
        dest="correct_ocr_terms",
        action="store_false",
        help="위 기능을 끈다",
    )
    video = parser.add_argument_group("영상 입력(화면 캡처)")
    video.add_argument(
        "--no-frames", action="store_true", help="영상의 화면 캡처를 끈다(오디오만 전사)"
    )
    video.add_argument(
        "--frame-threshold",
        type=float,
        default=None,
        metavar="PCT",
        help="화면 변화 기준 %%(기본 10, 1~90)",
    )
    video.add_argument(
        "--frame-dedupe",
        type=float,
        default=None,
        metavar="PCT",
        help="이미 저장한 프레임과 이 %% 미만으로 다르면 저장 안 함(기본 3, 0이면 끔)",
    )
    video.add_argument(
        "--frame-interval",
        type=float,
        default=None,
        metavar="SEC",
        help="최소 캡처 간격 초(기본 5)",
    )
    video.add_argument("--no-ocr", action="store_true", help="슬라이드 글자 인식(OCR)을 끈다")
    video.add_argument(
        "--ocr-terms",
        dest="ocr_terms",
        action="store_true",
        default=None,
        help="슬라이드에서 뽑은 용어를 이 파일의 전사 프롬프트에 추가(기본 꺼짐)",
    )
    video.add_argument(
        "--no-ocr-terms", dest="ocr_terms", action="store_false", help="위 기능을 끈다"
    )
    video.add_argument(
        "--sheet-grid",
        type=_parse_sheet_grid,
        default=None,
        metavar="COLSxROWS",
        help="프레임을 격자로 묶은 시트 크기(기본 1x2, 각 1~3). '1x1'은 시트를 끈다",
    )
    video.add_argument(
        "--no-sheets", dest="sheets", action="store_false", default=None,
        help="시트를 만들지 않는다(낱장 그대로 둔다)",
    )
    video.add_argument(
        "--keep-frames",
        dest="keep_frames",
        action="store_true",
        default=None,
        help="시트를 만든 뒤에도 낱장 이미지를 지우지 않는다",
    )
    parser.add_argument("--dry-run", action="store_true", help="전사 없이 처리 계획만 출력")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("--version", action="version", version=f"lecture-scribe {__version__}")
    return parser


def _parse_sheet_grid(raw: str) -> tuple[int, int]:
    """'2x2' -> (2, 2). argparse가 실패 메시지를 붙이도록 ArgumentTypeError를 던진다."""
    match = re.fullmatch(r"(\d+)\s*[xX]\s*(\d+)", raw.strip())
    if match is None:
        raise argparse.ArgumentTypeError(f"'COLSxROWS' 형식이어야 합니다(예: 2x2): {raw!r}")
    return int(match.group(1)), int(match.group(2))


def apply_overrides(settings: Settings, args: argparse.Namespace) -> Settings:
    """CLI 플래그를 설정에 덮어쓴다(설정 파일은 변경하지 않음)."""
    output = settings.output
    if args.on_conflict is not None:
        output = replace(output, on_conflict=args.on_conflict)
    if args.timestamps is not None:
        output = replace(output, timestamps=args.timestamps)
    if args.formats:
        seen: list[str] = []
        for fmt in args.formats:
            if fmt not in seen:
                seen.append(fmt)
        output = replace(output, formats=seen)  # type: ignore[arg-type]

    decoding = settings.decoding
    if args.beam_size is not None:
        decoding = replace(decoding, beam_size=args.beam_size)

    prompt_settings = settings.prompt
    if args.no_prompt:
        prompt_settings = replace(
            prompt_settings, use_initial_prompt=False, use_hotwords=False
        )
    if args.initial_prompt:
        prompt_settings = replace(prompt_settings, use_initial_prompt=True)
    if args.no_initial_prompt:
        prompt_settings = replace(prompt_settings, use_initial_prompt=False)
    if args.no_hotwords:
        prompt_settings = replace(prompt_settings, use_hotwords=False)
    if args.no_repeat_glossary:
        prompt_settings = replace(prompt_settings, repeat_glossary_in_sentence=False)
    if args.no_prompt_fallback:
        prompt_settings = replace(prompt_settings, fallback_on_collapse=False)

    postprocess = settings.postprocess
    if args.fuzzy:
        postprocess = replace(postprocess, fuzzy_correction=True)
    if args.fuzzy_threshold is not None:
        postprocess = replace(postprocess, fuzzy_threshold=args.fuzzy_threshold)

    correction = settings.correction
    if args.correct:
        correction = replace(correction, enabled=True)
    if args.no_correct:
        correction = replace(correction, enabled=False)
    if args.correct_model is not None:
        correction = replace(correction, model=args.correct_model)
    if args.correct_confidence is not None:
        correction = replace(correction, min_confidence=args.correct_confidence)
    if args.correct_ocr_terms is not None:
        correction = replace(correction, use_ocr_terms=args.correct_ocr_terms)

    video_overrides: dict[str, Any] = {}
    if args.no_frames:
        video_overrides["capture_frames"] = False
    if args.frame_threshold is not None:
        video_overrides["change_threshold_pct"] = args.frame_threshold
    if args.frame_dedupe is not None:
        video_overrides["dedupe_threshold_pct"] = args.frame_dedupe
    if args.frame_interval is not None:
        video_overrides["min_interval_sec"] = args.frame_interval
    if args.no_ocr:
        video_overrides["ocr_enabled"] = False
    if args.ocr_terms is not None:
        video_overrides["ocr_terms_to_prompt"] = args.ocr_terms
    if args.sheet_grid is not None:
        video_overrides["sheet_cols"], video_overrides["sheet_rows"] = args.sheet_grid
    if args.sheets is not None:
        video_overrides["sheets_enabled"] = args.sheets
    if args.keep_frames is not None:
        video_overrides["keep_single_frames"] = args.keep_frames
    # 범위 보정은 설정 로더와 같은 코드를 쓴다.
    video_settings = (
        VideoSettings.from_dict({**asdict(settings.video), **video_overrides})
        if video_overrides
        else settings.video
    )

    presets = dict(settings.presets)
    active = settings.active_preset
    if args.preset is not None:
        if args.preset not in presets:
            raise LectureScribeError(
                f"프리셋을 찾을 수 없습니다: {args.preset} "
                f"(사용 가능: {', '.join(presets) or '없음'})"
            )
        active = args.preset
    if args.topic is not None or args.glossary is not None:
        # --topic/--glossary는 프리셋 위에 덮어쓴다(프리셋 파일은 수정하지 않음).
        base_preset = presets.get(active, Preset())
        presets[active] = Preset(
            topic=args.topic if args.topic is not None else base_preset.topic,
            glossary=(
                parse_glossary(args.glossary)
                if args.glossary is not None
                else list(base_preset.glossary)
            ),
            corrections=dict(base_preset.corrections),
        )

    return replace(
        settings,
        language=args.language or settings.language,
        model=args.model or settings.model,
        backend=args.backend or settings.backend,
        compute_type=args.compute_type or settings.compute_type,
        cpu_threads=(
            args.cpu_threads if args.cpu_threads is not None else settings.cpu_threads
        ),
        max_parallel_files=(
            max(1, args.parallel)
            if args.parallel is not None
            else settings.max_parallel_files
        ),
        active_preset=active,
        presets=presets,
        prompt=prompt_settings,
        decoding=decoding,
        postprocess=postprocess,
        correction=correction,
        output=output,
        video=video_settings,
    )


def make_backend(settings: Settings) -> TranscriptionBackend:
    if settings.backend == "mlx":
        from .backends.mlx import MlxWhisperBackend, is_available

        if is_available():
            return MlxWhisperBackend(model_name=settings.model)
        # 배포 번들에는 mlx가 없다. 설정만 남아 있으면 기본 백엔드로 되돌린다.
        logger.warning(
            "mlx 백엔드를 쓸 수 없어 faster-whisper로 전환합니다"
            "(설치하려면 `uv sync --extra mlx`)."
        )
    from .backends.faster import FasterWhisperBackend, default_download_root

    return FasterWhisperBackend(
        model_name=settings.model,
        compute_type=settings.compute_type,
        cpu_threads=settings.cpu_threads,
        num_workers=max(1, settings.max_parallel_files),
        download_root=default_download_root(),
    )


def _progress_printer(quiet: bool, json_mode: bool) -> "Callable[[QueueEvent], None]":
    """진행 상황 출력기. **항상 stderr로만** 쓴다(stdout은 결과 전용)."""
    last = {"percent": -1.0}

    def printer(event: QueueEvent) -> None:
        if quiet:
            return
        if json_mode:
            payload = {
                "event": "progress",
                "file": str(event.file),
                "percent": round(event.file_percent, 1),
                "overall_percent": round(event.overall_percent, 1),
                "eta_sec": int(event.eta_sec) if event.eta_sec else None,
                "stage": event.stage,
                "index": event.index,
                "total": event.total,
            }
            emit_event(payload)
            return
        if event.stage == "transcribe" and event.overall_percent - last["percent"] < 1.0:
            return
        last["percent"] = event.overall_percent
        eta = f" ETA {int(event.eta_sec)}초" if event.eta_sec else ""
        prefix = f"({event.index + 1}/{event.total}) " if event.total > 1 else ""
        print(
            f"\r[{event.overall_percent:5.1f}%] {prefix}{event.file.name} — "
            f"{event.message}{eta}",
            end="",
            file=sys.stderr,
            flush=True,
        )
        if event.stage == "done":
            print(file=sys.stderr, flush=True)

    return printer


def emit_event(payload: dict[str, Any]) -> None:
    """진행/로그 이벤트를 stderr에 JSON 한 줄로 출력."""
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


class JsonLineStderr(io.TextIOBase):
    """`--progress-json` 모드에서 stderr 한 줄 한 줄이 유효한 JSON이 되게 감싼다.

    서드파티(huggingface_hub 등)가 평문을 stderr로 직접 찍어도 소비자가
    JSON Lines로 파싱할 수 있어야 한다. 이미 JSON인 줄은 그대로 통과시키고,
    평문은 `{"event":"log", ...}`로 감싼다.
    """

    def __init__(self, stream: "TextIO") -> None:
        super().__init__()
        self._stream = stream
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._write_line(line)
        return len(text)

    def _write_line(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        if stripped.startswith("{"):
            try:
                json.loads(stripped)
                self._stream.write(stripped + "\n")
                self._stream.flush()
                return
            except json.JSONDecodeError:
                pass
        self._stream.write(
            json.dumps(
                {"event": "log", "level": "info", "message": stripped},
                ensure_ascii=False,
            )
            + "\n"
        )
        self._stream.flush()

    def flush(self) -> None:
        if self._buffer.strip():
            self._write_line(self._buffer)
            self._buffer = ""
        self._stream.flush()


class JsonLogHandler(logging.Handler):
    """`--progress-json` 모드에서 로그도 JSON Lines로 내보낸다.

    stderr가 진행률과 로그를 함께 실어 나르므로(§6 스트림 분리 원칙),
    한 줄 한 줄이 모두 유효한 JSON이어야 소비자가 파싱하기 쉽다.
    """

    def emit(self, record: logging.LogRecord) -> None:
        try:
            emit_event(
                {
                    "event": "log",
                    "level": record.levelname.lower(),
                    "message": record.getMessage(),
                }
            )
        except Exception:  # noqa: BLE001 - 로깅이 프로그램을 멈추면 안 된다
            self.handleError(record)


def result_to_dict(result: FileResult, settings: Settings, backend_name: str) -> dict[str, Any]:
    """`--json` 출력용 파일 1건 결과."""
    payload: dict[str, Any] = {
        "audio_path": str(result.audio_path),
        "status": result.status,
        "language": result.language,
        "duration_sec": round(result.duration_sec, 3),
        "segment_count": result.segment_count,
        "elapsed_sec": round(result.elapsed_sec, 2),
        "avg_logprob": round(result.avg_logprob, 4),
        "outputs": [
            {
                "format": outcome.format,
                "path": str(outcome.path) if outcome.path else None,
                "skipped": outcome.skipped,
                "fallback_used": outcome.fallback_used,
                "overwritten": outcome.overwritten,
            }
            for outcome in result.outputs
        ],
        "warnings": list(result.warnings),
        "corrections": [
            {"from": e.source, "to": e.target, "count": e.count, "fuzzy": e.fuzzy}
            for e in result.corrections
        ],
        "repeats": [
            {"text": r.text, "count": r.count, "start": r.start, "end": r.end}
            for r in result.repeats
        ],
        "prompt_fallback_used": result.prompt_fallback_used,
        "collapse_reason": result.collapse_reason,
        "frames_only": result.frames_only,
        "frames": (
            {
                "dir": str(result.frames_dir),
                "count": result.frame_count,
                "ocr_terms": list(result.ocr_terms),
                "ocr_terms_applied": list(result.ocr_terms_applied),
                "sheet_count": len(result.sheets),
                "single_frames_kept": result.single_frames_kept,
            }
            if result.frames_dir is not None
            else None
        ),
    }
    if result.error_user:
        payload["error"] = result.error_user
    if result.status == "ok":
        payload["meta"] = build_meta(result, settings, backend_name)
        payload["meta"].pop("segments", None)
    return payload


def exit_code_for(results: list[FileResult]) -> int:
    ok = [r for r in results if r.status == "ok"]
    failed = [r for r in results if r.status == "failed"]
    cancelled = [r for r in results if r.status == "cancelled"]
    if cancelled:
        return EXIT_CANCELLED
    if failed and ok:
        return EXIT_PARTIAL
    if failed:
        return EXIT_ALL_FAILED
    return EXIT_OK


def summarize(results: list[FileResult], quiet: bool) -> int:
    """사람이 읽는 요약을 stderr로 출력하고 종료 코드를 정한다."""
    ok = [r for r in results if r.status == "ok"]
    failed = [r for r in results if r.status == "failed"]

    if not quiet:
        for result in ok:
            for outcome in result.outputs:
                if outcome.path is None:
                    print(f"건너뜀(이미 존재): {result.audio_path.name}", file=sys.stderr)
                    continue
                note = " [대체 폴더]" if outcome.fallback_used else ""
                print(f"저장: {outcome.path}{note}", file=sys.stderr)
    if failed:
        print(f"\n실패 {len(failed)}건:", file=sys.stderr)
        for result in failed:
            print(f"  - {result.audio_path}: {result.error_user}", file=sys.stderr)
    return exit_code_for(results)


def emit_json_result(
    results: list[FileResult], settings: Settings, backend_name: str, code: int
) -> None:
    """최종 결과를 stdout에 단일 JSON 객체로 출력한다(다른 출력과 섞이면 안 된다)."""
    payload = {
        "version": 1,
        "exit_code": code,
        "summary": {
            "total": len(results),
            "ok": sum(1 for r in results if r.status == "ok"),
            "failed": sum(1 for r in results if r.status == "failed"),
            "cancelled": sum(1 for r in results if r.status == "cancelled"),
        },
        "settings": {
            "model": settings.model,
            "backend": backend_name,
            "language": settings.language,
            "formats": list(settings.output.formats),
            "preset": settings.active_preset,
        },
        "results": [result_to_dict(r, settings, backend_name) for r in results],
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def build_reindex_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lecture-scribe reindex",
        description="기존 전사물의 front matter만 읽어 인덱스를 재구축한다(전사 재수행 없음)",
    )
    parser.add_argument("directory", type=Path)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--index-path", type=Path, default=None)
    parser.add_argument("--json", dest="json_output", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser


def build_list_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lecture-scribe list", description="전사 인덱스를 조회한다"
    )
    parser.add_argument("--topic", default=None, help="주제/제목/용어 부분일치")
    parser.add_argument("--since", default=None, help="ISO 날짜(YYYY-MM-DD) 이후")
    parser.add_argument("--index-path", type=Path, default=None)
    parser.add_argument("--json", dest="json_output", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("-v", "--verbose", action="count", default=0)
    return parser


def run_reindex(argv: list[str]) -> int:
    from .index import rebuild

    args = build_reindex_parser().parse_args(argv)
    setup_logging(verbosity=args.verbose, quiet=args.quiet or args.json_output)
    log_startup("CLI")
    settings = load_settings()
    index_path = args.index_path or settings.cowork.index_file
    directory = args.directory.expanduser()
    if not directory.is_dir():
        print(f"오류: 폴더가 아닙니다: {directory}", file=sys.stderr)
        return EXIT_ALL_FAILED
    entries = rebuild(directory, index_path, recursive=args.recursive)
    if args.json_output:
        json.dump(
            {
                "index_path": str(index_path),
                "count": len(entries),
                "entries": [asdict(entry) for entry in entries],
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
    elif not args.quiet:
        print(f"인덱스 재구축: {len(entries)}건 -> {index_path}", file=sys.stderr)
    return EXIT_OK


def run_list(argv: list[str]) -> int:
    from .index import query, read_entries

    args = build_list_parser().parse_args(argv)
    setup_logging(verbosity=args.verbose, quiet=args.quiet or args.json_output)
    settings = load_settings()
    index_path = args.index_path or settings.cowork.index_file
    entries = query(read_entries(index_path), topic=args.topic, since=args.since)
    if args.json_output:
        json.dump(
            {
                "index_path": str(index_path),
                "count": len(entries),
                "entries": [asdict(entry) for entry in entries],
            },
            sys.stdout,
            ensure_ascii=False,
            indent=2,
        )
        sys.stdout.write("\n")
        return EXIT_OK
    if not entries:
        print("인덱스에 해당 항목이 없습니다.", file=sys.stderr)
        return EXIT_OK
    for entry in entries:
        minutes = int(entry.duration_sec // 60)
        print(
            f"{entry.transcribed_at[:16]}  {minutes:>4}분  "
            f"저신뢰 {entry.low_confidence_ratio:>6.1%}  {entry.title}"
        )
        print(f"      {entry.transcript_path}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == "reindex":
        return run_reindex(raw[1:])
    if raw and raw[0] == "list":
        return run_list(raw[1:])

    args = build_parser().parse_args(raw)
    # --json / --stdout일 때는 사람이 읽는 진행 표시를 끈다(stdout 오염 방지가 아니라
    # stderr 소음 감소 목적. 진행률은 --progress-json으로 받는다).
    quiet = args.quiet or (args.json_output and not args.progress_json)
    logger = setup_logging(verbosity=args.verbose, quiet=quiet)
    if args.progress_json:
        # stderr 전체를 JSON Lines로 감싼다(서드파티 평문 출력 포함).
        sys.stderr = JsonLineStderr(sys.stderr)
        # 사람이 읽는 콘솔 핸들러를 JSON 핸들러로 교체하고,
        # 서드파티(huggingface_hub 등)의 평문 경고는 낮춰 stderr를 JSON으로 유지한다.
        for handler in list(logger.handlers):
            if isinstance(handler, logging.StreamHandler) and not isinstance(
                handler, logging.FileHandler
            ):
                logger.removeHandler(handler)
        json_handler = JsonLogHandler()
        json_handler.setLevel(logging.INFO if args.verbose else logging.WARNING)
        logger.addHandler(json_handler)
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

    try:
        settings = apply_overrides(load_settings(), args)
    except LectureScribeError as exc:
        print(f"오류: {exc.user_message}", file=sys.stderr)
        return EXIT_ALL_FAILED

    if args.open_gui:
        from .gui.app import main as gui_main

        return gui_main([str(path) for path in args.files])

    # 창 없는 전사 프로세스가 Dock에 뜨지 않게 한다(.app 번들에서 실행될 때).
    hide_from_dock()

    inputs, rejected = collect_inputs(list(args.files), recursive=args.recursive)
    for path, reason in rejected:
        print(f"제외: {path} — {reason}", file=sys.stderr)
    if not inputs:
        print("처리할 파일이 없습니다.", file=sys.stderr)
        if args.json_output:
            emit_json_result([], settings, settings.backend, EXIT_ALL_FAILED)
        return EXIT_ALL_FAILED

    if args.dry_run:
        for path in inputs:
            for fmt in settings.output.formats:
                target = (args.output_dir or path.parent) / f"{path.stem}.{fmt}"
                print(f"{path} -> {target}", file=sys.stderr)
        return EXIT_OK

    cancel = CancelToken()

    def handle_sigint(signum: int, frame: FrameType | None) -> None:
        print("\n취소 요청됨. 현재 세그먼트까지 정리 후 종료합니다.", file=sys.stderr)
        cancel.cancel()

    signal.signal(signal.SIGINT, handle_sigint)

    backend = make_backend(settings)
    on_progress = _progress_printer(quiet, args.progress_json)

    try:
        plan = build_prompt_plan_for(settings, backend)
    except LectureScribeError as exc:
        print(f"오류: {exc.user_message}", file=sys.stderr)
        return EXIT_ALL_FAILED

    if args.progress_json:
        emit_event(
            {
                "event": "prompt",
                "initial_prompt": plan.initial_prompt,
                "hotwords": plan.hotwords,
                "used_tokens": plan.used_tokens,
                "budget_tokens": plan.budget_tokens,
                "included_terms": plan.included_terms,
                "dropped_terms": plan.dropped_terms,
                "warnings": plan.warnings,
            }
        )
    elif not quiet:
        if plan.initial_prompt:
            print(
                f"프롬프트 {plan.used_tokens}/{plan.budget_tokens} 토큰, "
                f"용어 {len(plan.included_terms)}개 반영",
                file=sys.stderr,
            )
            print(f"  → {plan.initial_prompt}", file=sys.stderr)
        elif plan.hotwords:
            print(
                f"용어 고정(hotwords) {plan.used_tokens}/{plan.budget_tokens} 토큰, "
                f"{len(plan.included_terms)}개",
                file=sys.stderr,
            )
        for warning in plan.warnings:
            print(f"경고: {warning}", file=sys.stderr)

    if settings.performance.warn_low_memory:
        memory_warning = check_memory_headroom(settings.model)
        if memory_warning and not quiet:
            print(f"경고: {memory_warning}", file=sys.stderr)

    # 전사는 사용자가 결과를 기다리는 작업이다. 메인 스레드 QoS를 명시한다.
    set_thread_qos(
        QOS_CLASS_UTILITY if args.low_priority else QOS_CLASS_USER_INITIATED
    )

    if args.notify:
        # Quick Action은 진행률을 못 보여준다. 시작 시점에 예상 시간을 알려
        # "멈춘 것 같다"는 오해를 줄인다.
        total_audio = 0.0
        for path in inputs:
            try:
                total_audio += probe_duration(path)
            except LectureScribeError:
                continue
        if total_audio > 0:
            notify_start(len(inputs), total_audio, settings.model)

    results = run_queue(
        inputs,
        settings,
        backend,
        prompt_plan=plan,
        output_dir=args.output_dir,
        batched=args.batched,
        batch_size=args.batch_size,
        on_progress=on_progress,
        cancel=cancel,
        write_files=not args.text_stdout,
        emit_handoff=args.emit_handoff,
        split_md_minutes=args.split_md,
    )

    code = exit_code_for(results)

    if args.text_stdout:
        # 파일을 쓰지 않고 전사 텍스트만 stdout으로
        for result in results:
            if result.status != "ok":
                continue
            if len(results) > 1:
                print(f"# {result.audio_path.name}")
            print(render_txt(
                result.segments,
                timestamps=settings.output.timestamps,
                paragraph_break_sec=settings.output.paragraph_break_sec,
                line_width=settings.output.line_width,
            ))

    if args.progress_json:
        for result in results:
            emit_event(
                {
                    "event": "file_done",
                    "file": str(result.audio_path),
                    "status": result.status,
                    "outputs": [
                        str(o.path) for o in result.outputs if o.path is not None
                    ],
                    "skipped_outputs": [o.format for o in result.outputs if o.skipped],
                    "error": result.error_user,
                    "warnings": result.warnings,
                }
            )
        emit_event(
            {
                "event": "queue_done",
                "exit_code": code,
                "ok": sum(1 for r in results if r.status == "ok"),
                "failed": sum(1 for r in results if r.status == "failed"),
                "cancelled": sum(1 for r in results if r.status == "cancelled"),
            }
        )

    if args.json_output:
        emit_json_result(results, settings, backend.name, code)
    elif args.progress_json:
        pass  # 위에서 file_done / queue_done 이벤트로 이미 보고했다
    elif not args.text_stdout:
        summarize(results, quiet)
    else:
        summarize(results, quiet=True)

    if isinstance(sys.stderr, JsonLineStderr):
        sys.stderr.flush()

    if args.notify:
        first_output = next(
            (
                outcome.path
                for result in results
                for outcome in result.outputs
                if outcome.path is not None
            ),
            None,
        )
        notify_completion(
            ok_count=sum(1 for r in results if r.status == "ok"),
            failed_count=sum(1 for r in results if r.status == "failed"),
            first_output=first_output,
        )

    return code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
