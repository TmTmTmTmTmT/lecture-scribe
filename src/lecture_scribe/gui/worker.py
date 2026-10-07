"""백그라운드 작업 스레드.

전사와 토큰 계산은 모두 워커 스레드에서 돌린다. 모델 로드·다운로드도 마찬가지다.
UI 스레드에서는 어떤 무거운 작업도 하지 않는다(§8: 전사 중에도 창이 멈추지 않아야 한다).

전사 워커는 **상시 실행되는 작업 큐**다. 전사 중에도 파일을 계속 추가할 수 있고,
작업마다 그 시점의 설정(프리셋·모델·용어)을 스냅샷으로 들고 간다.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

from ..backends.base import TranscriptionBackend
from ..config import Settings
from ..engine import CancelToken, FileResult, ProgressEvent, build_prompt_plan_for, transcribe_file
from ..errors import LectureScribeError
from ..logsetup import get_logger
from ..perf import release_memory, set_thread_qos
from ..prompt import PromptPlan, build_prompt_plan, preview_token_usage

logger = get_logger(__name__)

BackendProvider = Callable[[Settings], TranscriptionBackend]
#: 실패한 백엔드를 캐시에서 내리고 메모리를 돌려주는 콜백
BackendDisposer = Callable[[Settings], None]


@dataclass(slots=True, frozen=True)
class TokenUsage:
    """토큰 사용량 미리보기 결과."""

    used: int
    budget: int
    dropped_terms: list[str]


@dataclass(slots=True)
class TranscribeJob:
    """전사 작업 1건. 설정은 **큐에 넣는 시점**의 스냅샷이다.

    덕분에 전사 중에 프리셋·모델·용어를 바꿔도 이미 대기 중인 작업에는 영향이 없고,
    새로 추가하는 파일부터 바뀐 설정이 적용된다.
    """

    path: Path
    settings: Settings
    duration_sec: float = 0.0
    emit_handoff: bool = False
    batched: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class TokenCountWorker(QThread):
    """주제/용어 입력이 바뀔 때 실제 토크나이저로 토큰 수를 센다."""

    counted = Signal(object)  # TokenUsage
    failed = Signal(str)

    def __init__(
        self,
        backend_factory: Callable[[], TranscriptionBackend],
        topic: str,
        glossary: list[str],
        max_tokens: int,
        language: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend_factory = backend_factory
        self._topic = topic
        self._glossary = glossary
        self._max_tokens = max_tokens
        self._language = language

    def run(self) -> None:  # pragma: no cover - 스레드 본문
        try:
            backend = self._backend_factory()
            used, budget = preview_token_usage(
                self._topic,
                self._glossary,
                backend.count_tokens,
                max_tokens=self._max_tokens,
                language=self._language,
            )
            plan = build_prompt_plan(
                self._topic,
                self._glossary,
                backend.count_tokens,
                max_tokens=self._max_tokens,
                language=self._language,
            )
            self.counted.emit(TokenUsage(used, budget, list(plan.dropped_terms)))
        except LectureScribeError as exc:
            self.failed.emit(exc.user_message)
        except Exception as exc:  # noqa: BLE001
            logger.exception("토큰 계산 실패")
            self.failed.emit(str(exc))


class TranscribeWorker(QThread):
    """상시 실행 전사 큐.

    `submit()`으로 언제든 작업을 추가할 수 있고, `parallel`개까지 동시에 처리한다.
    큐가 비고 실행 중인 작업이 없으면 `went_idle`을 낸다.
    """

    job_started = Signal(object)  # Path
    progressed = Signal(object)  # ProgressEvent
    job_done = Signal(object)  # FileResult
    went_idle = Signal()
    plan_ready = Signal(object, object)  # (Path, PromptPlan)
    failed = Signal(object, str)  # (Path, 메시지)

    _STOP = object()

    def __init__(
        self,
        backend_provider: BackendProvider,
        parallel: int = 1,
        parent: QObject | None = None,
        backend_disposer: BackendDisposer | None = None,
    ) -> None:
        super().__init__(parent)
        self._backend_provider = backend_provider
        self._backend_disposer = backend_disposer
        self._parallel = max(1, parallel)
        self._queue: queue.Queue[Any] = queue.Queue()
        self._cancel = CancelToken()
        self._lock = threading.Lock()
        self._active: set[Path] = set()
        self._pending_count = 0

    # --- 큐 조작 (UI 스레드에서 호출) ---

    def submit(self, job: TranscribeJob) -> None:
        with self._lock:
            self._pending_count += 1
        self._queue.put(job)

    def stop(self) -> None:
        self._queue.put(self._STOP)

    def cancel_all(self) -> None:
        """진행 중인 작업을 중단하고 대기 중인 작업을 버린다."""
        self._cancel.cancel()
        drained = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is self._STOP:
                self._queue.put(self._STOP)
                break
            drained += 1
        with self._lock:
            self._pending_count = max(0, self._pending_count - drained)

    def rearm(self) -> None:
        """취소 후 다시 쓸 수 있도록 취소 신호를 새로 만든다."""
        self._cancel = CancelToken()

    @property
    def busy(self) -> bool:
        with self._lock:
            return bool(self._active) or self._pending_count > 0

    def active_paths(self) -> set[Path]:
        with self._lock:
            return set(self._active)

    # --- 스레드 본문 ---

    def run(self) -> None:  # pragma: no cover - 스레드 본문
        with ThreadPoolExecutor(
            max_workers=self._parallel, thread_name_prefix="scribe-gui"
        ) as pool:
            running: set[Future[None]] = set()
            was_busy = False
            while True:
                try:
                    item = self._queue.get(timeout=0.2)
                except queue.Empty:
                    running = {f for f in running if not f.done()}
                    if was_busy and not running and self._queue.empty():
                        was_busy = False
                        self.went_idle.emit()
                    continue
                if item is self._STOP:
                    break
                was_busy = True
                running = {f for f in running if not f.done()}
                running.add(pool.submit(self._run_job, item))

    def _dispose_backend(self, job: TranscribeJob) -> None:
        """실패한 백엔드를 캐시에서 내린다.

        모델을 반쯤 올리다 실패한 백엔드가 캐시에 남으면 (1) 메모리를 계속 붙들고
        (2) 다음 작업이 그 망가진 인스턴스를 다시 써서 또 실패한다. 실사용에서
        전사가 실패할 때마다 메모리가 무한히 쌓이던 원인이다.
        """
        if self._backend_disposer is None:
            return
        try:
            self._backend_disposer(job.settings)
        except Exception:  # noqa: BLE001 - 정리 실패가 전사 실패를 덮으면 안 된다
            logger.exception("백엔드 정리 실패 %s", job.path.name)

    def _run_job(self, job: TranscribeJob) -> None:  # pragma: no cover - 스레드 본문
        path = job.path
        if job.settings.performance.high_priority:
            # 워커 스레드 기본 QoS는 DEFAULT다. 사용자가 기다리는 작업이므로 올린다.
            set_thread_qos()
        with self._lock:
            self._active.add(path)
            self._pending_count = max(0, self._pending_count - 1)
        try:
            if self._cancel.cancelled:
                self.job_done.emit(FileResult(audio_path=path, status="cancelled"))
                return
            self.job_started.emit(path)
            backend = self._backend_provider(job.settings)
            plan = build_prompt_plan_for(job.settings, backend)
            self.plan_ready.emit(path, plan)
            result = transcribe_file(
                path,
                job.settings,
                backend,
                prompt_plan=plan,
                on_progress=self.progressed.emit,
                cancel=self._cancel,
                emit_handoff=job.emit_handoff,
            )
            # `transcribe_file`은 예외를 삼키고 status="failed"를 돌려준다.
            # 그래서 아래 except 절은 이 경로에서 **절대 실행되지 않는다.**
            # 여기서 직접 정리하지 않으면 실패한 백엔드가 캐시에 남아 모델이
            # 메모리를 계속 붙든다(실사용에서 GPU 실패 시 점유가 안 풀리던 원인).
            if result.status == "failed":
                logger.warning(
                    "전사 실패(%s) — 백엔드를 내립니다: %s",
                    path.name,
                    result.error_log or result.error_user or "사유 미상",
                )
                self._dispose_backend(job)
                self.failed.emit(path, result.error_user or "전사에 실패했습니다.")
            self.job_done.emit(result)
        except LectureScribeError as exc:
            logger.error("전사 실패 %s: %s", path.name, exc.log_message)
            self._dispose_backend(job)
            self.failed.emit(path, exc.user_message)
            self.job_done.emit(
                FileResult(
                    audio_path=path,
                    status="failed",
                    error_user=exc.user_message,
                    error_log=exc.log_message,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("전사 워커 예외 %s", path.name)
            self._dispose_backend(job)
            self.failed.emit(path, str(exc))
            self.job_done.emit(
                FileResult(
                    audio_path=path, status="failed", error_user=str(exc)
                )
            )
        finally:
            with self._lock:
                self._active.discard(path)
            if job.settings.performance.release_memory_after_file:
                freed = release_memory()
                if freed > 64:
                    logger.info("메모리 %.0fMB 반환 (%s)", freed, path.name)


__all__ = [
    "BackendDisposer",
    "BackendProvider",
    "ProgressEvent",
    "TokenCountWorker",
    "TokenUsage",
    "TranscribeJob",
    "TranscribeWorker",
]
