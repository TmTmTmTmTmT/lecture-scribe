"""전사 실행 엔진.

파이프라인: 검증 -> 프롬프트 구성 -> 모델 로드 -> 전사 -> (붕괴 시 폴백 재전사)
            -> 용어 교정 -> 반복 감지 -> 렌더링 -> 저장

- 진행률은 `세그먼트 end / 전체 duration`으로 계산한다(ffprobe duration 기준).
- 취소는 CancelToken으로 전달하고 세그먼트 경계에서 안전하게 중단한다.
- 오류는 파일 단위로 격리한다(한 파일 실패가 큐 전체를 중단시키지 않음).
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Sequence
from datetime import datetime
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Literal

from . import audio as audio_mod
from .backends.base import (
    Segment,
    TranscriptionBackend,
    TranscriptionRequest,
)
from .config import Preset, Settings
from .errors import CancelledError, LectureScribeError
from .logsetup import get_logger
from .perf import available_memory_gb, release_memory, set_thread_qos
from .postprocess import (
    CorrectionEntry,
    ForeignScriptRun,
    RepeatRun,
    apply_corrections,
    apply_fuzzy_corrections,
    build_header_notes,
    detect_collapse,
    detect_head_loss,
    find_foreign_script_runs,
    find_repeated_phrases,
    find_repeat_runs,
    foreign_script_segment_ids,
    fuzzy_available,
)
from .correction import (
    CorrectionResult,
    OllamaClient,
    annotate,
    build_sidecar as build_correction_sidecar,
    propose_corrections,
)
from .handoff import (
    HandoffContext,
    collect_low_confidence_spans,
    render_frames_only_handoff,
    render_handoff,
)
from .index import IndexEntry, append_entry
from .mirror import MirrorResult, mirror_outputs
from .prompt import PromptPlan, build_prompt_plan
from .frames import SheetRecord
from .video_stage import VideoStageResult, run_video_stage
from .writer import (
    WriteOutcome,
    dump_json,
    format_timestamp,
    low_confidence_ratio,
    render,
    render_front_matter,
    render_json,
    split_segments_by_minutes,
    write_output,
)

logger = get_logger(__name__)

FileStatus = Literal["ok", "failed", "skipped", "cancelled"]
Stage = Literal[
    "probe",
    "frames",
    "ocr",
    "model",
    "transcribe",
    "postprocess",
    "correct",
    "write",
    "done",
]


@dataclass(slots=True, frozen=True)
class ProgressEvent:
    """진행 상황 1건."""

    file: Path
    stage: Stage
    percent: float
    eta_sec: float | None = None
    message: str = ""


ProgressCallback = Callable[[ProgressEvent], None]


class CancelToken:
    """스레드 안전 취소 신호."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledError()


@dataclass(slots=True)
class FileResult:
    """파일 1건 처리 결과."""

    audio_path: Path
    status: FileStatus
    outputs: list[WriteOutcome] = field(default_factory=list)
    language: str = ""
    language_probability: float = 0.0
    duration_sec: float = 0.0
    segment_count: int = 0
    elapsed_sec: float = 0.0
    error_user: str | None = None
    error_log: str | None = None
    warnings: list[str] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    prompt_plan: PromptPlan | None = None
    corrections: list[CorrectionEntry] = field(default_factory=list)
    repeats: list[RepeatRun] = field(default_factory=list)
    foreign_runs: list[ForeignScriptRun] = field(default_factory=list)
    prompt_fallback_used: bool = False
    collapse_reason: str | None = None
    mirrors: list[MirrorResult] = field(default_factory=list)
    low_confidence_ratio: float = 0.0
    speech_duration_sec: float = 0.0
    llm_corrections: CorrectionResult | None = None
    #: 영상 입력의 화면 캡처(PLAN_VIDEO_FRAMES.md). 캡처하지 않았으면 None/0.
    frames_dir: Path | None = None
    frame_count: int = 0
    #: 오디오 트랙이 없어 화면 캡처만 처리한 경우
    frames_only: bool = False
    ocr_terms: list[str] = field(default_factory=list)
    #: 위 용어 중 실제로 전사 프롬프트에 들어간 것
    ocr_terms_applied: list[str] = field(default_factory=list)
    #: 프레임을 격자로 묶은 시트(FIX_GUIDE_13 S-01). 비어 있으면 시트를 안 만들었다.
    sheets: list[SheetRecord] = field(default_factory=list)
    #: 낱장 이미지(`NNNN_*.jpg`)를 지우지 않고 남겼는지.
    single_frames_kept: bool = True

    @property
    def avg_logprob(self) -> float:
        """유한한 값들의 평균. NaN이 하나만 섞여도 평균 전체가 nan이 된다."""
        values = [s.avg_logprob for s in self.segments if math.isfinite(s.avg_logprob)]
        if not values:
            return 0.0
        return sum(values) / len(values)

    @property
    def quality_warnings(self) -> list[str]:
        """FIX_GUIDE_6.md C-01: 산출물을 확인해야 하는 경고(반복 구간·기대 언어 밖 문자).

        GUI가 배지 개수를 셀 때 이걸 쓴다. `repeats`/`foreign_runs`는 이미 구조화된
        리스트라 `describe()`를 그대로 모아 만든다 — `warnings`의 한국어 문구를
        substring 매칭으로 재분류하지 않는다(문구가 바뀌면 조용히 깨지는 걸 피한다).
        """
        return [run.describe() for run in self.repeats] + [
            run.describe() for run in self.foreign_runs
        ]

    @property
    def info_warnings(self) -> list[str]:
        """`warnings` 중 품질 경고가 아닌 나머지(백엔드 무시 옵션, 프롬프트 안내 등)."""
        quality = set(self.quality_warnings)
        return [w for w in self.warnings if w not in quality]


#: turbo 계열 모델 이름. hotwords 효과가 없다(실측).
_TURBO_MARKERS: Final[tuple[str, ...]] = ("turbo",)


def _is_turbo(model_name: str) -> bool:
    lowered = model_name.lower()
    return any(marker in lowered for marker in _TURBO_MARKERS)


# FIX_GUIDE.md G-02: ETA를 최근 표본 몇 개로만 낸다(전체 평균 외삽 금지).
_ETA_WINDOW_SAMPLES: Final[int] = 8

#: 표본 사이 최소 벽시계 간격(초). FIX_GUIDE_2.md N-04 — 창 하나가 끝나면
#: 세그먼트가 버스트로 쏟아지는데, 그걸 전부 표본으로 찍으면 이동 구간이
#: 사실상 순간(0초)이 되어 속도·ETA가 터진다. 버스트당 표본 1개로 눌러
#: 사실상 창 경계 단위 표본이 되게 한다.
_ETA_MIN_SAMPLE_INTERVAL_SEC: Final[float] = 1.0


def _rolling_eta(recent: list[tuple[float, float]], total: float) -> float | None:
    """최근 표본 구간의 속도로 남은 시간을 추정한다.

    `recent`는 (경과 시각, 오디오 end 초) 표본을 시간순으로 담은 리스트(최근 것만
    유지, `_ETA_WINDOW_SAMPLES`개 이하). 표본이 2개 미만이거나 구간 안에서
    오디오/시각이 실질적으로 진행하지 않았으면 아직 속도를 추정할 수 없어 None.
    """
    if len(recent) < 2:
        return None
    elapsed0, audio0 = recent[0]
    elapsed1, audio1 = recent[-1]
    dt = elapsed1 - elapsed0
    daudio = audio1 - audio0
    if dt <= 0.0 or daudio <= 0.0:
        return None
    rate = daudio / dt  # 오디오 초 / 벽시계 초
    remaining_audio = max(0.0, total * 0.97 - audio1)
    return remaining_audio / rate


def build_prompt_plan_for(
    settings: Settings,
    backend: TranscriptionBackend,
    *,
    preset: Preset | None = None,
) -> PromptPlan:
    """설정(또는 지정 프리셋) + 백엔드 토크나이저로 프롬프트 계획을 만든다.

    백엔드가 hotwords를 지원하지 않으면(mlx) 용어집을 **initial_prompt로 돌린다.**
    그러지 않으면 사용자가 입력한 용어가 조용히 버려진다 — 이 앱의 핵심 기능인데
    GPU에서만 동작하지 않는 셈이 된다(실사용 보고).

    faster-whisper에서 initial_prompt를 켜면 앞부분이 잘리는 문제가 있었지만,
    mlx에서는 재현되지 않았다(실측: 프롬프트 유무 모두 0.00초에서 시작).
    """
    active = preset if preset is not None else settings.current_preset()
    language = "en" if settings.language == "en" else "ko"
    caps = backend.capabilities(TranscriptionRequest(audio_path=Path("dummy.m4a")))
    use_hotwords = settings.prompt.use_hotwords and caps.hotwords
    use_initial = settings.prompt.use_initial_prompt

    if settings.prompt.use_hotwords and _is_turbo(settings.model):
        # turbo는 용어집을 소화하지 못한다. 실측(220초 구간, 정답 용어 8개, 각 2회):
        #   large-v3  용어집 없음 2/8 -> 용어집 6/8   (효과 큼)
        #   turbo     용어집 없음 2/8 -> 용어집 2/8   (효과 없음)
        # 그런데 시간은 53초 -> 139~154초로 2.7배 늘어난다. 순손해라 아예 넣지 않는다.
        logger.info(
            "%s는 용어집 효과가 없고 hotwords를 넣으면 2.7배 느려집니다(실측). "
            "용어를 프롬프트에 넣지 않습니다 — 용어 정확도가 중요하면 large-v3를 쓰세요.",
            settings.model,
        )
        use_hotwords = False
    elif settings.prompt.use_hotwords and not caps.hotwords:
        # large-v3인데 백엔드가 hotwords를 못 쓴다(mlx). 남은 통로는 initial_prompt뿐인데,
        # 이건 사용자가 "주제 문장을 initial_prompt로 사용"을 켰을 때만 쓴다(FIX_GUIDE.md G-03).
        # 예전엔 여기서 무조건 켰다 — 사용자가 끈 옵션을 조용히 재활성화하는 셈이었고,
        # initial_prompt가 폴백 재전사(§F-03-3, detect_head_loss)까지 무장시켜서
        # 사용자가 원치 않는 전체 재전사가 걸릴 수 있었다. 실측상 효과도 없었다(2/8 -> 2/8).
        if settings.prompt.use_initial_prompt:
            logger.info(
                "%s 백엔드는 hotwords를 지원하지 않아 용어집을 initial_prompt로 전달합니다"
                "(실측상 인식 개선 효과는 확인되지 않았습니다)",
                backend.name,
            )
        else:
            logger.info(
                "%s 백엔드는 hotwords를 지원하지 않고 '주제 문장을 initial_prompt로 사용'이 "
                "꺼져 있어 이번 전사에는 용어집을 적용하지 않습니다. "
                "용어 고정이 필요하면 해당 옵션을 켜거나 CPU(faster-whisper) 백엔드를 쓰세요.",
                backend.name,
            )
    return build_prompt_plan(
        active.topic,
        active.glossary,
        backend.count_tokens,
        max_tokens=settings.prompt.max_prompt_tokens,
        use_initial_prompt=use_initial,
        use_hotwords=use_hotwords,
        repeat_glossary_in_sentence=settings.prompt.repeat_glossary_in_sentence,
        language=language,
    )


def build_request(
    audio_path: Path,
    settings: Settings,
    *,
    initial_prompt: str | None = None,
    hotwords: str | None = None,
    batched: bool = False,
) -> TranscriptionRequest:
    """설정 -> 백엔드 요청 변환."""
    decoding = settings.decoding
    prompt = settings.prompt
    language = None if settings.language == "auto" else settings.language
    # FIX_GUIDE_4.md A-02: mlx는 §5-2 게이트를 통과해 기본값이 다르다(꺼짐).
    # faster-whisper는 이 게이트와 무관하므로 원래 필드를 그대로 쓴다 — 백엔드별로
    # 기본값이 갈리는 걸 감수하고 별도 필드로 분리했다(같은 필드면 못 나눈다).
    condition_on_previous_text = (
        prompt.condition_on_previous_text_mlx
        if settings.backend == "mlx"
        else prompt.condition_on_previous_text
    )
    return TranscriptionRequest(
        audio_path=audio_path,
        language=language,
        task="transcribe",
        initial_prompt=initial_prompt if prompt.use_initial_prompt else None,
        hotwords=hotwords if prompt.use_hotwords else None,
        condition_on_previous_text=condition_on_previous_text,
        carry_window_prompt=prompt.carry_window_prompt,
        prompt_reset_on_temperature=prompt.prompt_reset_on_temperature,
        beam_size=decoding.beam_size,
        temperatures=list(decoding.temperatures),
        compression_ratio_threshold=decoding.compression_ratio_threshold,
        log_prob_threshold=decoding.log_prob_threshold,
        no_speech_threshold=decoding.no_speech_threshold,
        vad_filter=decoding.vad_filter,
        min_silence_duration_ms=decoding.min_silence_duration_ms,
        hallucination_silence_threshold=decoding.hallucination_silence_threshold,
        batched=batched,
    )


def transcribe_file(
    audio_path: Path,
    settings: Settings,
    backend: TranscriptionBackend,
    *,
    request: TranscriptionRequest | None = None,
    prompt_plan: PromptPlan | None = None,
    output_dir: Path | None = None,
    on_progress: ProgressCallback | None = None,
    cancel: CancelToken | None = None,
    write_files: bool = True,
    emit_handoff: bool = False,
    split_md_minutes: int = 0,
) -> FileResult:
    """파일 1건 전사. 예외를 FileResult로 흡수한다(큐를 계속 돌릴 수 있게)."""
    started = time.monotonic()
    cancel = cancel or CancelToken()
    result = FileResult(audio_path=audio_path, status="failed")

    def emit(
        stage: Stage, percent: float, message: str = "", eta: float | None = None
    ) -> None:
        if on_progress is not None:
            on_progress(
                ProgressEvent(
                    file=audio_path,
                    stage=stage,
                    percent=percent,
                    eta_sec=eta,
                    message=message,
                )
            )

    try:
        cancel.raise_if_cancelled()
        emit("probe", 0.0, "파일 확인 중")

        # --- 영상 입력: 화면 캡처 + OCR (PLAN_VIDEO_FRAMES.md) ---
        # 전사보다 먼저 끝내야 한다. OCR 용어가 프롬프트에 들어가기 때문이다.
        video_stage_result: VideoStageResult | None = None
        media: audio_mod.MediaInfo | None = None
        if audio_path.suffix.lower() in audio_mod.VIDEO_EXTS:
            media = audio_mod.probe_media(audio_path)
            if media.has_video and settings.video.capture_frames and write_files:
                try:
                    video_stage_result = run_video_stage(
                        audio_path,
                        media,
                        settings,
                        output_dir=output_dir,
                        on_progress=_video_progress(emit, has_audio=media.has_audio),
                        is_cancelled=lambda: cancel.cancelled,
                    )
                except CancelledError:
                    raise
                except LectureScribeError as exc:
                    if not media.has_audio:
                        raise  # 할 일이 이것뿐이므로 실패로 처리
                    warning = f"화면 캡처를 건너뛰었습니다: {exc.user_message}"
                    result.warnings.append(warning)
                    logger.warning("%s [%s] %s", warning, audio_path.name, exc.log_message)
            if video_stage_result is not None:
                result.warnings.extend(video_stage_result.warnings)
                result.frames_dir = video_stage_result.frames_dir
                result.frame_count = video_stage_result.frame_count
                result.ocr_terms = list(video_stage_result.ocr_terms)
                result.sheets = list(video_stage_result.sheets)
                result.single_frames_kept = video_stage_result.single_frames_kept

            if not media.has_audio and video_stage_result is not None:
                # 오디오가 없는 영상(화면 녹화): 프레임만 처리하고 끝낸다.
                result.duration_sec = media.duration_sec
                result.frames_only = True
                if video_stage_result.skipped:
                    result.status = "skipped"
                else:
                    if video_stage_result.frames_dir is not None:
                        result.outputs.append(
                            WriteOutcome(format="frames", path=video_stage_result.frames_dir)
                        )
                        if emit_handoff:
                            result.outputs.append(
                                _write_frames_only_handoff(
                                    audio_path, result, settings, output_dir
                                )
                            )
                    result.status = "ok"
                    result.warnings.append("오디오 트랙이 없어 화면 캡처만 처리했습니다")
                result.elapsed_sec = time.monotonic() - started
                emit("done", 100.0, "완료")
                logger.info(
                    "화면 캡처 완료 %s (%.1f초 영상, %d장, %.1f초 소요)",
                    audio_path.name,
                    result.duration_sec,
                    result.frame_count,
                    result.elapsed_sec,
                )
                return result

        info = audio_mod.probe(audio_path)
        result.duration_sec = info.duration_sec

        cancel.raise_if_cancelled()
        emit("model", 0.0, "모델 준비 중")
        backend.ensure_loaded(on_status=lambda msg: emit("model", 0.0, msg))

        plan: PromptPlan | None
        if request is None:
            plan = prompt_plan or build_prompt_plan_for(settings, backend)
            request = build_request(
                audio_path,
                settings,
                initial_prompt=plan.initial_prompt,
                hotwords=plan.hotwords,
            )
        else:
            plan = prompt_plan
        if (
            video_stage_result is not None
            and video_stage_result.ocr_terms
            and settings.video.ocr_terms_to_prompt
        ):
            plan, request = _apply_ocr_terms(
                settings, backend, video_stage_result.ocr_terms, request, result
            )
        result.prompt_plan = plan
        if plan is not None:
            for warning in plan.warnings:
                result.warnings.append(warning)
                logger.warning("%s [%s]", warning, audio_path.name)
            if plan.initial_prompt:
                logger.info(
                    "프롬프트 %d/%d 토큰, 용어 %d개 반영: %s",
                    plan.used_tokens,
                    plan.budget_tokens,
                    len(plan.included_terms),
                    plan.initial_prompt,
                )

        caps = backend.capabilities(request)
        for ignored in caps.ignored_options(request):
            warning = (
                f"{backend.name} 백엔드(batched={request.batched})에서 "
                f"무시되는 옵션: {ignored}"
            )
            result.warnings.append(warning)
            logger.warning("%s [%s]", warning, audio_path.name)

        cancel.raise_if_cancelled()
        segments = _run_transcription(
            backend, request, result, cancel, emit, base_percent=0.0
        )

        # --- 프롬프트 부작용 폴백 (§F-03-3) ---
        if settings.prompt.fallback_on_collapse and (
            request.initial_prompt or request.hotwords
        ):
            reason = detect_collapse(
                segments,
                result.duration_sec,
                initial_prompt=request.initial_prompt,
                speech_duration_sec=result.speech_duration_sec or None,
            )
            retry_request: TranscriptionRequest | None = None
            if reason is not None:
                # 전체 붕괴: 프롬프트를 모두 뺀다
                retry_request = replace(request, initial_prompt=None, hotwords=None)
                fallback_desc = "프롬프트 없이"
            elif request.initial_prompt:
                # 부분 붕괴(앞 구간 누락): initial_prompt만 빼고 hotwords는 유지해
                # 용어 고정 효과는 잃지 않는다.
                head_reason = detect_head_loss(
                    segments, audio_mod.first_speech_offset(audio_path)
                )
                if head_reason is not None:
                    reason = head_reason
                    retry_request = replace(request, initial_prompt=None)
                    fallback_desc = "initial_prompt 없이(hotwords 유지)"

            if retry_request is not None and reason is not None:
                result.collapse_reason = reason
                warning = (
                    f"프롬프트 적용 결과가 비정상({reason}). {fallback_desc} 재전사합니다."
                )
                result.warnings.append(warning)
                logger.warning("%s [%s]", warning, audio_path.name)
                cancel.raise_if_cancelled()
                segments = _run_transcription(
                    backend,
                    retry_request,
                    result,
                    cancel,
                    emit,
                    base_percent=0.0,
                    start_message=f"재전사 중({reason}, {fallback_desc})",
                )
                result.prompt_fallback_used = True

        result.segments = segments
        result.segment_count = len(segments)

        # **최종** 결과를 다시 검사한다. 폴백 재전사 후에도 비정상일 수 있고
        # (파인튜닝 모델 실측), 프롬프트와 무관한 붕괴도 알려야 한다.
        final_reason = detect_collapse(
            segments,
            result.duration_sec,
            speech_duration_sec=result.speech_duration_sec or None,
        )
        if final_reason is not None:
            result.collapse_reason = final_reason
            if result.prompt_fallback_used:
                warning = (
                    f"재전사 후에도 결과가 비정상입니다({final_reason}). "
                    "다른 모델을 시도하거나 오디오 품질을 확인하세요."
                )
            else:
                warning = (
                    f"전사 결과가 비정상으로 보입니다({final_reason}). "
                    "모델이나 오디오 품질을 확인하세요."
                )
            result.warnings.append(warning)
            logger.warning("%s [%s]", warning, audio_path.name)

        # --- 후처리: 용어 교정 + 반복 감지 (F-03-4, F-04) ---
        emit("postprocess", 98.0, "용어 교정 중")
        segments, corrections = _postprocess(segments, settings, result)
        result.segments = segments
        result.corrections = corrections
        result.repeats = find_repeat_runs(
            segments, min_count=settings.decoding.repeat_warning_count
        )
        for run in result.repeats:
            logger.warning("%s [%s]", run.describe(), audio_path.name)

        # --- 기대 언어 밖 문자 검출 (FIX_GUIDE_5.md B-02) ---
        # 언어가 ko/en이 아니면(실제로 중국어/일본어 등을 전사 중이면) 검출을
        # 끈다 — 그 경우 전 구간이 오탐이 된다(FIX_GUIDE_5.md §4-2).
        if settings.postprocess.foreign_script_detection and result.language in (
            "ko",
            "en",
        ):
            result.foreign_runs = find_foreign_script_runs(
                segments,
                ratio=settings.postprocess.foreign_script_ratio,
                min_count=settings.postprocess.foreign_script_min_count,
            )
            for foreign_run in result.foreign_runs:
                logger.warning("%s [%s]", foreign_run.describe(), audio_path.name)
                note = foreign_run.describe()
                if note not in result.warnings:
                    result.warnings.append(note)
        # 세그먼트 **안쪽** 반복 루프도 파일 상단 주석 대상이다.
        for segment in segments:
            repeated = find_repeated_phrases(segment.text)
            if repeated is None:
                continue
            word, count = repeated
            note = (
                f"[{format_timestamp(segment.start)}] 한 구간에서 '{word}'가 "
                f"{count}회 연속 반복 — 인식 실패 가능성"
            )
            if note not in result.warnings:
                result.warnings.append(note)
                logger.warning("%s [%s]", note, audio_path.name)

        # --- LLM 교정 제안 (F-09) ---
        #
        # 순서가 중요하다. 전사가 끝났으므로 **Whisper 모델을 먼저 내려**
        # 메모리를 비우고, 그 자리에 교정 모델을 올린다. 교정 모델은
        # `keep_alive=0`이라 응답 직후 스스로 내려간다(실측 4,580MB -> 51MB).
        # 둘이 동시에 상주하지 않는다.
        if settings.correction.enabled:
            cancel.raise_if_cancelled()
            emit("correct", 98.5, "교정 모델 준비 중")
            try:
                backend.unload()
            except Exception:  # noqa: BLE001 - 교정 전 정리 실패가 전사를 망치면 안 된다
                logger.exception("교정 전 전사 모델 해제 실패 %s", audio_path.name)
            release_memory()

            def _correct_progress(index: int, total: int) -> None:
                emit(
                    "correct",
                    98.5,
                    f"교정 중 {index}/{total}",
                )

            correction_result = propose_corrections(
                segments,
                settings.current_preset().topic,
                settings.current_preset().glossary,
                model=settings.correction.model,
                min_confidence=settings.correction.min_confidence,
                max_chars=settings.correction.chunk_chars,
                slide_terms=(
                    list(result.ocr_terms) if settings.correction.use_ocr_terms else []
                ),
                client=OllamaClient(
                    host=settings.correction.host,
                    timeout=settings.correction.timeout_sec,
                ),
                on_progress=_correct_progress,
                should_cancel=lambda: cancel.cancelled,
            )
            result.llm_corrections = correction_result
            if correction_result.skipped_reason:
                warning = f"교정 건너뜀: {correction_result.skipped_reason}"
                result.warnings.append(warning)
                logger.warning("%s [%s]", warning, audio_path.name)

        if write_files:
            cancel.raise_if_cancelled()
            emit("write", 99.0, "결과 저장 중")
            result.outputs = _write_outputs(
                segments,
                audio_path,
                settings,
                output_dir,
                result,
                backend.name,
                emit_handoff=emit_handoff,
                split_md_minutes=split_md_minutes,
            )
            if result.frames_dir is not None:
                # 전사 파일 뒤에 붙여 `outputs[0]`이 계속 전사문이 되게 한다.
                result.outputs.append(WriteOutcome(format="frames", path=result.frames_dir))

        result.status = "ok"
        result.elapsed_sec = time.monotonic() - started
        emit("done", 100.0, "완료")
        logger.info(
            "전사 완료 %s (%.1f초 오디오, %d세그먼트, %.1f초 소요, 교정 %d건)",
            audio_path.name,
            result.duration_sec,
            result.segment_count,
            result.elapsed_sec,
            sum(entry.count for entry in result.corrections),
        )
        return result

    except CancelledError as exc:
        result.status = "cancelled"
        result.error_user = exc.user_message
        result.elapsed_sec = time.monotonic() - started
        logger.info("취소됨: %s", audio_path.name)
        return result
    except LectureScribeError as exc:
        result.status = "failed"
        result.error_user = exc.user_message
        result.error_log = exc.log_message
        result.elapsed_sec = time.monotonic() - started
        logger.error("실패 %s: %s", audio_path.name, exc.log_message)
        return result
    except Exception as exc:  # noqa: BLE001 - 예상 못한 오류도 큐를 멈추지 않는다
        result.status = "failed"
        result.error_user = f"알 수 없는 오류가 발생했습니다: {audio_path.name}"
        result.error_log = repr(exc)
        result.elapsed_sec = time.monotonic() - started
        logger.exception("예상치 못한 오류 %s", audio_path.name)
        return result


def _video_progress(
    emit: Callable[..., None], *, has_audio: bool
) -> Callable[[str, float, str], None]:
    """영상 단계 진행률을 파일 진행률(0~100)에 맞춘다.

    오디오가 있으면 이 단계 뒤에 전사가 0%부터 다시 시작하므로 진행률은 0으로 두고
    메시지만 갱신한다(진행 막대가 뒤로 가지 않게). 화면 캡처만 처리하는 파일은 이 단계가
    전부이므로 캡처 0~60%, OCR 60~98%로 나눠 실제 진행률을 보여준다.
    """

    def report(stage: str, percent: float, message: str) -> None:
        if has_audio:
            emit("ocr" if stage == "ocr" else "frames", 0.0, message)
        elif stage == "ocr":
            emit("ocr", 60.0 + 0.38 * percent, message)
        else:
            emit("frames", 0.6 * percent, message)

    return report


def _apply_ocr_terms(
    settings: Settings,
    backend: TranscriptionBackend,
    terms: Sequence[str],
    request: TranscriptionRequest,
    result: FileResult,
) -> tuple[PromptPlan, TranscriptionRequest]:
    """OCR 용어를 **이 파일의 프롬프트에만** 덧붙인다(사용자 용어가 앞).

    프리셋·용어 통계·후처리 교정에는 넣지 않는다. 슬라이드마다 다르고 OCR 오인식이 섞일 수
    있어서, 영구 저장하거나 자동 교정에 쓰면 오염된다. 예산을 넘으면 기존 로직이 뒤쪽부터
    자르므로 OCR 용어가 먼저 빠진다.
    """
    preset = settings.current_preset()
    merged = replace(preset, glossary=[*preset.glossary, *terms])
    plan = build_prompt_plan_for(settings, backend, preset=merged)
    request = replace(
        request,
        initial_prompt=plan.initial_prompt if settings.prompt.use_initial_prompt else None,
        hotwords=plan.hotwords if settings.prompt.use_hotwords else None,
    )
    applied = [t for t in terms if t in plan.included_terms]
    result.ocr_terms_applied = applied
    if applied:
        logger.info("슬라이드 용어 %d/%d개를 프롬프트에 반영: %s", len(applied), len(terms), applied)
    else:
        logger.info(
            "슬라이드 용어 %d개는 프롬프트에 반영되지 않았습니다(백엔드/모델 설정 또는 토큰 예산)",
            len(terms),
        )
    return plan, request


def _write_frames_only_handoff(
    video_path: Path,
    result: FileResult,
    settings: Settings,
    output_dir: Path | None,
) -> WriteOutcome:
    """전사가 없는 영상의 핸드오프."""
    assert result.frames_dir is not None
    text = render_frames_only_handoff(
        video_path,
        result.frames_dir,
        result.frame_count,
        result.duration_sec,
        result.ocr_terms,
        datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    return write_output(
        text,
        video_path,
        "handoff.md",
        policy=settings.output.on_conflict,
        output_dir=output_dir,
        fallback_dir=settings.output.fallback_path,
    )


def _run_transcription(
    backend: TranscriptionBackend,
    request: TranscriptionRequest,
    result: FileResult,
    cancel: CancelToken,
    emit: Callable[..., None],
    *,
    base_percent: float,
    start_message: str = "전사 시작",
) -> list[Segment]:
    """전사 1회 실행(폴백 재전사에서 재사용).

    `start_message`: 폴백 재전사(FIX_GUIDE.md G-04)일 때 사유를 담아 넘긴다.
    그러지 않으면 진행률이 이유 없이 0%로 되돌아간 것처럼 보인다.
    """
    emit("transcribe", base_percent, start_message)

    # FIX_GUIDE_2.md N-02: mlx는 창 하나(60~120초)가 끝날 때까지 세그먼트를
    # 하나도 안 내보낸다. 그 사이 진행률·메시지가 전혀 안 움직여 "멈춘 것"처럼
    # 보인다(사용자 보고, 0.6%에서 정지). 백엔드가 창이 도는 동안 부르는
    # 하트비트로 메시지만 갱신한다 — 퍼센트/ETA는 마지막 실제 값을 그대로 쓴다.
    # 여기서 올리면(추정치) 다음 실제 emit에서 그 값이 되감기는 것처럼 보인다.
    last_percent = base_percent
    last_eta: float | None = None

    def _on_heartbeat(message: str) -> None:
        # FIX_GUIDE_4.md A-07: 취소는 창 경계에서만 확인되므로(구 N-06) 사용자가
        # 취소를 누른 뒤에도 창이 끝날 때까지 하트비트가 계속 온다. 그 사이
        # "처리 중…"을 계속 내보내면 GUI가 보여줄 "취소 중" 상태를 매번
        # 덮어써 취소가 안 먹힌 것처럼 보인다. 표시만 정직하게 바꾼다 —
        # 취소 지연 자체(창 크기)는 이 자리에서 손대지 않는다.
        if cancel.cancelled:
            emit("transcribe", last_percent, "취소 중…", last_eta)
            return
        emit("transcribe", last_percent, message, last_eta)

    stream = backend.transcribe(request, on_heartbeat=_on_heartbeat)
    result.language = stream.language
    result.language_probability = stream.language_probability
    if stream.duration_sec > 0:
        result.duration_sec = stream.duration_sec
    result.speech_duration_sec = stream.duration_after_vad_sec

    segments: list[Segment] = []
    total = result.duration_sec or 1.0
    transcribe_started = time.monotonic()
    # ETA는 "지금까지 전체 평균 속도"가 아니라 "최근 구간 속도"로 낸다(FIX_GUIDE.md G-02).
    # 전체 평균으로 내면 후반에 창 하나가 느려질 때마다 이미 지난 빠른 구간까지 같이
    # 평균에 끌려 내려가서, 남은 시간이 실제 속도 변화보다 훨씬 크게(몇 배로) 튄다.
    # 최근 표본만 보는 이동 구간 평균으로 바꿔 표시값이 최근 실제 속도를 따라가게 한다.
    #
    # FIX_GUIDE_2.md N-04(회귀 수정): mlx는 창 하나가 끝나면 세그먼트 수십 개를
    # 한꺼번에(버스트로) 내보낸다. 세그먼트마다 표본을 찍으면 이동 구간(최근 8개)이
    # 전부 같은 버스트 안에 들어가 벽시계 간격이 사실상 0이 되고, 속도가 수천 배
    # realtime으로 튀어 ETA가 0초 근처로 잘못 찍힌다. 표본은 세그먼트 단위가 아니라
    # 최소 벽시계 간격(`_ETA_MIN_SAMPLE_INTERVAL_SEC`)마다 하나씩만 찍어 사실상
    # 창 경계 단위 표본이 되게 한다.
    recent: list[tuple[float, float]] = []  # (경과 시각, 오디오 end 초) 표본
    last_sample_at = -math.inf
    try:
        for segment in stream.segments:
            if cancel.cancelled:
                raise CancelledError()
            segments.append(segment)
            percent = min(97.0, max(0.0, segment.end / total * 97.0))
            elapsed = time.monotonic() - transcribe_started
            if elapsed - last_sample_at >= _ETA_MIN_SAMPLE_INTERVAL_SEC:
                recent.append((elapsed, segment.end))
                if len(recent) > _ETA_WINDOW_SAMPLES:
                    recent.pop(0)
                last_sample_at = elapsed
            eta = _rolling_eta(recent, total)
            last_percent = percent
            last_eta = eta
            emit("transcribe", percent, segment.text.strip()[:40], eta)
    finally:
        close = getattr(stream.segments, "close", None)
        if close is not None:
            close()
    return segments


def _postprocess(
    segments: list[Segment], settings: Settings, result: FileResult
) -> tuple[list[Segment], list[CorrectionEntry]]:
    """정확 매칭 교정 + (설정 시) 유사도 교정."""
    preset = settings.current_preset()
    corrections: list[CorrectionEntry] = []

    exact = apply_corrections(segments, preset.corrections)
    segments = exact.segments
    corrections.extend(exact.log)

    if settings.postprocess.fuzzy_correction:
        if not fuzzy_available():
            warning = "rapidfuzz 미설치로 유사도 교정을 건너뜁니다(`uv sync --extra fuzzy`)."
            result.warnings.append(warning)
            logger.warning(warning)
        else:
            fuzzy = apply_fuzzy_corrections(
                segments,
                preset.glossary,
                threshold=settings.postprocess.fuzzy_threshold,
            )
            segments = fuzzy.segments
            corrections.extend(fuzzy.log)

    for entry in corrections:
        logger.info("용어 교정: %s", entry.format())
    return segments, corrections


def front_matter_meta(
    result: FileResult, settings: Settings, backend_name: str
) -> dict[str, Any]:
    """md front matter용 메타(§10.1). 에이전트가 읽을 최소·필수 항목만 담는다."""
    preset = settings.current_preset()
    cowork = settings.cowork
    return {
        "source_audio": str(result.audio_path),
        "transcribed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "duration_sec": round(result.duration_sec, 1),
        "language": result.language,
        "model": settings.model,
        "backend": backend_name,
        "topic": preset.topic,
        "glossary": list(preset.glossary),
        "segment_count": result.segment_count,
        "avg_logprob": round(result.avg_logprob, 3),
        "low_confidence_ratio": round(result.low_confidence_ratio, 4),
        "low_confidence_marker": cowork.low_confidence_marker,
        "marker_meaning": (
            "음성 인식 신뢰도가 낮거나(logprob) 기대 언어 밖 문자(한자/가나 등)가 "
            "감지된 구간. 내용을 추측으로 보완하지 말 것."
        ),
        "foreign_script_segment_count": sum(len(run.segment_ids) for run in result.foreign_runs),
    }


def build_meta(
    result: FileResult, settings: Settings, backend_name: str
) -> dict[str, Any]:
    """json 출력·사이드카·front matter가 함께 쓰는 메타데이터."""
    plan = result.prompt_plan
    return {
        "source_audio": str(result.audio_path),
        "transcribed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "duration_sec": round(result.duration_sec, 3),
        "language": result.language,
        "language_probability": round(result.language_probability, 4),
        "model": settings.model,
        "backend": backend_name,
        "compute_type": settings.compute_type,
        "topic": settings.current_preset().topic,
        "glossary": list(settings.current_preset().glossary),
        "segment_count": result.segment_count,
        "avg_logprob": round(result.avg_logprob, 4),
        "low_confidence_ratio": round(result.low_confidence_ratio, 4),
        "low_confidence_marker": settings.cowork.low_confidence_marker,
        "prompt": {
            "initial_prompt": plan.initial_prompt if plan else None,
            "hotwords": plan.hotwords if plan else None,
            "used_tokens": plan.used_tokens if plan else 0,
            "budget_tokens": plan.budget_tokens if plan else 0,
            "dropped_terms": list(plan.dropped_terms) if plan else [],
            "fallback_used": result.prompt_fallback_used,
            "collapse_reason": result.collapse_reason,
        },
        "decoding": {
            "beam_size": settings.decoding.beam_size,
            "vad_filter": settings.decoding.vad_filter,
            "temperatures": list(settings.decoding.temperatures),
            "compression_ratio_threshold": settings.decoding.compression_ratio_threshold,
            "log_prob_threshold": settings.decoding.log_prob_threshold,
            "no_speech_threshold": settings.decoding.no_speech_threshold,
        },
        "corrections": [
            {"from": entry.source, "to": entry.target, "count": entry.count,
             "fuzzy": entry.fuzzy}
            for entry in result.corrections
        ],
        "repeats": [
            {"text": run.text, "count": run.count, "start": run.start, "end": run.end}
            for run in result.repeats
        ],
        "foreign_script_runs": [
            {"text": run.text, "count": run.count, "start": run.start, "end": run.end}
            for run in result.foreign_runs
        ],
        "warnings": list(result.warnings),
        "frames": (
            {
                "dir": str(result.frames_dir),
                "count": result.frame_count,
                "ocr_terms": list(result.ocr_terms),
                "ocr_terms_applied": list(result.ocr_terms_applied),
            }
            if result.frames_dir is not None
            else None
        ),
    }


def _write_outputs(
    segments: list[Segment],
    audio_path: Path,
    settings: Settings,
    output_dir: Path | None,
    result: FileResult,
    backend_name: str = "",
    *,
    emit_handoff: bool = False,
    split_md_minutes: int = 0,
) -> list[WriteOutcome]:
    """설정된 모든 포맷으로 저장하고, Cowork 연계 산출물까지 배치한다(§10).

    순서: 본문(txt/md/srt/vtt/json) -> 분할 md -> 사이드카 -> 핸드오프 -> 미러 -> 인덱스
    """
    outputs: list[WriteOutcome] = []
    cowork = settings.cowork
    fallback = settings.output.fallback_path
    result.low_confidence_ratio = low_confidence_ratio(
        segments, cowork.low_confidence_logprob
    )
    header_notes = (
        build_header_notes(
            result.repeats, result.corrections, foreign_runs=result.foreign_runs
        )
        if settings.output.mark_repeats
        else []
    )
    force_mark_ids = foreign_script_segment_ids(result.foreign_runs)
    if settings.output.mark_repeats and result.collapse_reason:
        header_notes.insert(0, f"전사 품질 경고: {result.collapse_reason}")
    if settings.output.mark_repeats:
        # 세그먼트 안쪽 반복 주석만(진행 과정 메시지는 제외) 파일에 남긴다
        header_notes.extend(
            w
            for w in result.warnings
            if w.startswith("[") and "연속 반복" in w and w not in header_notes
        )
    if not segments:
        # 빈 파일만 남기면 오류로 오해하기 쉽다. 이유를 파일에 적어 둔다.
        note = (
            "음성이 감지되지 않았습니다(무음이거나 VAD가 모든 구간을 제거함). "
            "무음이 아닌데 비어 있다면 decoding.vad_filter 또는 no_speech_threshold를 조정하세요."
        )
        header_notes.insert(0, note)
        if note not in result.warnings:
            result.warnings.append(note)
        logger.warning("%s [%s]", note, audio_path.name)
    meta = build_meta(result, settings, backend_name)
    fm_meta = front_matter_meta(result, settings, backend_name)
    front_matter = render_front_matter(fm_meta)

    # 교정 주석은 사람이 읽는 포맷(txt/md)에만 넣는다.
    # 자막(srt/vtt)은 화면에 뜨는 글자라 주석이 방해되고, json은 사이드카가 따로 있다.
    annotated_segments = _annotate_segments(segments, result, settings)

    def write(content: str, ext: str) -> WriteOutcome:
        return write_output(
            content,
            audio_path,
            ext,
            policy=settings.output.on_conflict,
            output_dir=output_dir,
            fallback_dir=fallback,
        )

    for fmt in settings.output.formats:
        if fmt == "md" and split_md_minutes > 0:
            outputs.extend(
                _write_split_md(
                    segments,
                    audio_path,
                    settings,
                    output_dir,
                    fm_meta,
                    header_notes,
                    split_md_minutes,
                    force_mark_ids,
                )
            )
            continue
        source = (
            annotated_segments
            if fmt in {"txt", "md"} and annotated_segments is not None
            else segments
        )
        try:
            content = render(
                fmt,
                source,
                timestamps=settings.output.timestamps,
                paragraph_break_sec=settings.output.paragraph_break_sec,
                line_width=settings.output.line_width,
                section_interval_min=cowork.section_interval_min,
                header_notes=header_notes,
                title=audio_path.stem,
                front_matter=front_matter,
                meta=meta,
                low_confidence_logprob=cowork.low_confidence_logprob,
                low_confidence_marker=cowork.low_confidence_marker,
                force_mark_ids=force_mark_ids,
            )
        except ValueError as exc:
            logger.error("출력 포맷 오류: %s", exc)
            continue
        outputs.append(write(content, fmt))

    # --- 사이드카 메타데이터 (§10.2) ---
    if cowork.write_sidecar_json:
        sidecar_meta = dict(meta)
        sidecar_meta["low_confidence_ratio"] = round(result.low_confidence_ratio, 4)
        sidecar_meta["low_confidence_logprob"] = cowork.low_confidence_logprob
        sidecar_meta["foreign_script_segment_count"] = len(force_mark_ids)
        outputs.append(
            write(render_json(segments, sidecar_meta), "transcript.json")
        )

    # --- 교정 근거 JSON (F-09) ---
    correction_result = result.llm_corrections
    if (
        correction_result is not None
        and correction_result.proposals
        and settings.correction.emit_sidecar
    ):
        transcript_path = next(
            (o.path for o in outputs if o.path is not None and o.path.suffix == ".txt"),
            None,
        )
        outputs.append(
            write(
                dump_json(
                    build_correction_sidecar(
                        correction_result,
                        source_audio=audio_path,
                        transcript_path=transcript_path,
                        topic=settings.current_preset().topic,
                        glossary=settings.current_preset().glossary,
                        generated_at=str(fm_meta["transcribed_at"]),
                    ),
                    indent=1,
                )
                + "\n",
                "corrections.json",
            )
        )

    # --- 핸드오프 (§10.7) ---
    written_paths = [o.path for o in outputs if o.path is not None]
    if emit_handoff:
        context = HandoffContext(
            audio_path=audio_path,
            transcript_paths=[
                path
                for path in written_paths
                if path.suffix in {".md", ".txt"}
            ]
            or written_paths,
            title=audio_path.stem,
            topic=settings.current_preset().topic,
            glossary=list(settings.current_preset().glossary),
            language=result.language,
            model=settings.model,
            backend=backend_name,
            duration_sec=result.duration_sec,
            transcribed_at=str(fm_meta["transcribed_at"]),
            segment_count=result.segment_count,
            corrections=list(result.corrections),
            low_confidence_spans=collect_low_confidence_spans(
                segments, cowork.low_confidence_logprob
            ),
            low_confidence_marker=cowork.low_confidence_marker,
            low_confidence_ratio=result.low_confidence_ratio,
            frames_dir=result.frames_dir,
            frame_count=result.frame_count,
            ocr_terms=list(result.ocr_terms),
        )
        outputs.append(write(render_handoff(context), "handoff.md"))

    # --- 워크스페이스 미러 (§10.4) ---
    final_paths = [o.path for o in outputs if o.path is not None]
    if cowork.enable_mirror and cowork.workspace_dir:
        workspace = cowork.workspace_path
        # 출력이 이미 워크스페이스 안이면 미러하지 않는다(자기 자신 링크 방지)
        mirror_targets = [
            path
            for path in final_paths
            if workspace not in path.parents
        ]
        result.mirrors = mirror_outputs(
            mirror_targets, audio_path, workspace, cowork.mirror_mode
        )

    # --- 인덱스 (§10.3) ---
    if cowork.write_index:
        transcript = next(
            (path for path in final_paths if path.suffix == ".md"),
            next((path for path in final_paths if path.suffix == ".txt"), None),
        )
        if transcript is not None:
            append_entry(
                IndexEntry(
                    audio_path=str(audio_path),
                    transcript_path=str(transcript),
                    title=audio_path.stem,
                    topic=str(fm_meta["topic"]),
                    glossary=list(settings.current_preset().glossary),
                    language=result.language,
                    duration_sec=round(result.duration_sec, 1),
                    transcribed_at=str(fm_meta["transcribed_at"]),
                    word_count=sum(len(s.text.split()) for s in segments),
                    low_confidence_ratio=round(result.low_confidence_ratio, 4),
                    model=settings.model,
                    backend=backend_name,
                    frames_dir=str(result.frames_dir) if result.frames_dir else "",
                ),
                cowork.index_file,
            )
    return outputs


def _annotate_segments(
    segments: Sequence[Segment],
    result: FileResult,
    settings: Settings,
) -> list[Segment] | None:
    """교정 주석 `원문[→교정]`을 붙인 세그먼트 사본. 붙일 게 없으면 None.

    **원문은 한 글자도 지우지 않는다.** 교정은 덧붙이기만 한다.
    """
    correction_result = result.llm_corrections
    if (
        correction_result is None
        or not correction_result.proposals
        or not settings.correction.annotate_transcript
    ):
        return None
    annotated: list[Segment] = []
    for segment in segments:
        applicable = [
            p for p in correction_result.proposals if p.original in segment.text
        ]
        if not applicable:
            annotated.append(segment)
            continue
        annotated.append(replace(segment, text=annotate(segment.text, applicable)))
    return annotated


def _write_split_md(
    segments: list[Segment],
    audio_path: Path,
    settings: Settings,
    output_dir: Path | None,
    fm_meta: dict[str, Any],
    header_notes: list[str],
    minutes: int,
    force_mark_ids: frozenset[int] = frozenset(),
) -> list[WriteOutcome]:
    """md를 N분 단위로 분할 저장한다(§10.6).

    각 파트에 동일한 front matter와 `part`, `covers` 필드를 넣어 단독으로도
    문맥이 유지되게 한다.
    """
    from .writer import format_timestamp, render_md

    cowork = settings.cowork
    parts = split_segments_by_minutes(segments, minutes)
    outputs: list[WriteOutcome] = []
    for index, (start, end, part_segments) in enumerate(parts, start=1):
        part_meta = dict(fm_meta)
        part_meta["part"] = f"{index}/{len(parts)}"
        part_meta["covers"] = (
            f"{format_timestamp(start)}–{format_timestamp(end)}"
        )
        content = render_md(
            part_segments,
            title=f"{audio_path.stem} (part {index}/{len(parts)})",
            timestamps=settings.output.timestamps,
            paragraph_break_sec=settings.output.paragraph_break_sec,
            section_interval_min=cowork.section_interval_min,
            header_notes=header_notes if index == 1 else [],
            front_matter=render_front_matter(part_meta),
            low_confidence_logprob=cowork.low_confidence_logprob,
            low_confidence_marker=cowork.low_confidence_marker,
            force_mark_ids=force_mark_ids,
        )
        outputs.append(
            write_output(
                content,
                audio_path,
                f"part{index}.md",
                policy=settings.output.on_conflict,
                output_dir=output_dir,
                fallback_dir=settings.output.fallback_path,
            )
        )
    return outputs


# --- 큐 실행 -------------------------------------------------------------


#: 전사 1건이 실제로 쓰는 코어 수(실측: large-v3 beam3에서 약 4.4코어).
#: 이보다 촘촘히 띄우면 오버서브스크립션으로 오히려 느려진다
#: (실측 10코어에서 동시 2개 1.32배, 동시 3개 1.16배).
_CORES_PER_TRANSCRIPTION: Final[int] = 4
#: 첫 전사 1건의 **실측 메모리 최고치**(GB). large-v3 기준 파일 길이와 무관하게
#: 5.5GB 수준에서 오르내린다(90초 3.5GB / 10분 5.5GB / 45분 5.5GB).
_MEMORY_BASE_GB: Final[float] = 5.5
#: 동시 전사 1건 **추가**당 늘어나는 메모리(GB). 모델 가중치를 공유하므로
#: 2배가 아니라 증분만 든다(실측: 10분 파일 2개 동시 7.7GB = 5.5 + 2.2).
_MEMORY_PER_EXTRA_GB: Final[float] = 2.2
#: 시스템·다른 앱 몫으로 남겨 둘 여유(GB)
_MEMORY_HEADROOM_GB: Final[float] = 2.0


def limit_parallel(parallel: int, model_name: str, backend: str = "faster") -> int:
    """기기 상태에 맞게 동시 전사 수를 낮춘다(CPU 코어 + **가용** 메모리).

    실측(M1 Pro 10코어/16GB, large-v3 beam3):

    | 입력 | 순차 | 동시 2 |
    |---|---|---|
    | 90초 클립 3개 | 105초 / 3.5GB | 80초 / 4.3GB |
    | 10분 클립 2개 | 871초 / 5.5GB | **582초 / 7.7GB, 스왑 +2.2GB** |

    동시 처리가 빠르지만 메모리 여유가 없으면 스왑으로 역전된다.
    실사용 로그에서 여유 없는 상태로 긴 강의 3개를 동시에 돌렸다가
    전체 처리량이 0.63배속까지 떨어진 사례가 있었다.
    """
    if parallel <= 1:
        return parallel
    if backend == "mlx":
        # mlx-whisper는 모델을 프로세스 전역 하나로만 들고 있다(ModelHolder).
        # 동시에 돌려도 같은 GPU·같은 모델을 쓰므로 빨라지지 않고, 로드가 겹치면
        # 모델이 중복 적재돼 OOM이 난다. 항상 1건씩 처리한다.
        logger.info("mlx 백엔드는 GPU 모델을 공유하므로 동시 전사를 1개로 제한합니다")
        return 1
    cores = os.cpu_count() or 4
    by_cores = max(1, cores // _CORES_PER_TRANSCRIPTION)
    if by_cores < parallel:
        logger.info(
            "CPU %d코어 기준으로 동시 전사를 %d개로 낮춥니다(요청 %d개)",
            cores,
            by_cores,
            parallel,
        )
        parallel = by_cores

    available = available_memory_gb()
    if available > 0:
        # 첫 1건은 기본 비용, 추가 1건마다 증분 비용만 든다(모델 공유).
        budget = available - _MEMORY_HEADROOM_GB - _MEMORY_BASE_GB
        by_memory = 1 + max(0, int(budget // _MEMORY_PER_EXTRA_GB))
        if by_memory < parallel:
            logger.info(
                "가용 메모리 %.1fGB 기준으로 동시 전사를 %d개로 낮춥니다(요청 %d개). "
                "메모리가 부족한 상태에서 동시 처리하면 스왑 때문에 더 느려집니다.",
                available,
                by_memory,
                parallel,
            )
            parallel = by_memory
    return parallel


@dataclass(slots=True, frozen=True)
class QueueEvent:
    """큐 전체 진행 상황."""

    file: Path
    index: int  # 0-based
    total: int
    stage: Stage
    file_percent: float
    overall_percent: float
    eta_sec: float | None = None
    message: str = ""


QueueCallback = Callable[[QueueEvent], None]


def run_queue(
    paths: Sequence[Path],
    settings: Settings,
    backend: TranscriptionBackend,
    *,
    prompt_plan: PromptPlan | None = None,
    output_dir: Path | None = None,
    batched: bool = False,
    batch_size: int = 8,
    on_progress: QueueCallback | None = None,
    cancel: CancelToken | None = None,
    write_files: bool = True,
    emit_handoff: bool = False,
    split_md_minutes: int = 0,
) -> list[FileResult]:
    """여러 파일을 전사한다.

    전체 진행률은 파일 개수가 아니라 **오디오 총 길이** 기준으로 계산한다.
    길이를 못 구한 파일은 평균 길이로 가정한다.

    백엔드가 동시 전사를 지원하면(`capabilities().parallel_transcribe`)
    `settings.max_parallel_files`개까지 **같은 모델 인스턴스로** 병렬 처리한다.
    실측상 단일 파일은 CPU를 절반만 쓰고, 병렬 처리해도 결과는 동일하다.
    """
    cancel = cancel or CancelToken()
    durations: list[float] = []
    for path in paths:
        try:
            durations.append(audio_mod.probe_duration(path))
        except LectureScribeError:
            durations.append(0.0)  # 실패는 아래 transcribe_file에서 다시 보고된다
    known = [d for d in durations if d > 0]
    average = sum(known) / len(known) if known else 1.0
    weights = [d if d > 0 else average for d in durations]
    total_weight = sum(weights) or 1.0

    probe_request = build_request(
        paths[0] if paths else Path("dummy.m4a"), settings, batched=batched
    )
    caps = backend.capabilities(probe_request)
    parallel = min(max(1, settings.max_parallel_files), len(paths))
    if not caps.parallel_transcribe:
        parallel = 1
    parallel = limit_parallel(parallel, settings.model)

    queue_started = time.monotonic()
    lock = threading.Lock()
    done_weight = 0.0
    live: dict[int, float] = {}

    def relay(event: ProgressEvent, index: int) -> None:
        if on_progress is None:
            return
        with lock:
            live[index] = event.percent
            progressed = done_weight + sum(
                weights[i] * pct / 100.0 for i, pct in live.items()
            )
            overall_percent = min(100.0, progressed / total_weight * 100.0)
        elapsed = time.monotonic() - queue_started
        eta = (
            elapsed * (100.0 - overall_percent) / overall_percent
            if overall_percent > 0.5
            else None
        )
        on_progress(
            QueueEvent(
                file=event.file,
                index=index,
                total=len(paths),
                stage=event.stage,
                file_percent=event.percent,
                overall_percent=overall_percent,
                eta_sec=eta,
                message=event.message,
            )
        )

    def run_one(index: int, path: Path) -> FileResult:
        nonlocal done_weight
        # 워커 스레드 기본 QoS는 DEFAULT다. 사용자가 결과를 기다리는 작업이므로
        # USER_INITIATED로 올려 효율 코어로 강등되지 않게 한다.
        set_thread_qos()
        if cancel.cancelled:
            return FileResult(audio_path=path, status="cancelled")
        request = build_request(
            path,
            settings,
            initial_prompt=prompt_plan.initial_prompt if prompt_plan else None,
            hotwords=prompt_plan.hotwords if prompt_plan else None,
            batched=batched,
        )
        request.batch_size = batch_size
        result = transcribe_file(
            path,
            settings,
            backend,
            request=request,
            prompt_plan=prompt_plan,
            output_dir=output_dir,
            on_progress=lambda event: relay(event, index),
            cancel=cancel,
            write_files=write_files,
            emit_handoff=emit_handoff,
            split_md_minutes=split_md_minutes,
        )
        with lock:
            done_weight += weights[index]
            live.pop(index, None)
        # 긴 전사 뒤 힙에 남은 페이지를 OS에 돌려줘 스왑 압력을 줄인다.
        freed = release_memory()
        if freed > 64:
            logger.info("메모리 %.0fMB 반환", freed)
        return result

    if parallel <= 1:
        return [run_one(index, path) for index, path in enumerate(paths)]

    # 모델 로드는 스레드를 띄우기 전에 한 번만 한다(동시 로드 방지).
    try:
        backend.ensure_loaded()
    except LectureScribeError as exc:
        logger.error("모델 로드 실패: %s", exc.log_message)
        return [
            FileResult(
                audio_path=path,
                status="failed",
                error_user=exc.user_message,
                error_log=exc.log_message,
            )
            for path in paths
        ]

    logger.info("동시 전사 %d개로 처리합니다(파일 %d개)", parallel, len(paths))
    results: list[FileResult | None] = [None] * len(paths)
    with ThreadPoolExecutor(max_workers=parallel, thread_name_prefix="scribe") as pool:
        futures = {
            pool.submit(run_one, index, path): index
            for index, path in enumerate(paths)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 - 파일 단위 격리
                logger.exception("동시 전사 중 예외 %s", paths[index])
                results[index] = FileResult(
                    audio_path=paths[index],
                    status="failed",
                    error_user=f"알 수 없는 오류가 발생했습니다: {paths[index].name}",
                    error_log=repr(exc),
                )
    return [
        r if r is not None else FileResult(audio_path=p, status="cancelled")
        for r, p in zip(results, paths)
    ]


def summarize_segments(segments: Sequence[Segment]) -> tuple[int, float]:
    """(세그먼트 수, 평균 avg_logprob). 비유한값은 평균에서 뺀다."""
    if not segments:
        return 0, 0.0
    values = [s.avg_logprob for s in segments if math.isfinite(s.avg_logprob)]
    if not values:
        return len(segments), 0.0
    return len(segments), sum(values) / len(values)
