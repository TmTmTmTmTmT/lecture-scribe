"""정방형 메인 창 (§8).

- 위(설정 약 40%) / 아래(드롭존 약 60%) 2분할. 탭·사이드바·메뉴바 없음.
- 리사이즈 시 가로세로 1:1을 강제한다(짧은 변 기준).
- 최소 480×480, 기본 640×640. 크기·위치는 종료 시 저장.
- 무거운 작업(모델 로드·전사·토큰 계산)은 전부 워커 스레드에서 돈다.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import threading

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QKeySequence,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..audio import collect_inputs, probe_duration
from ..backends.base import BackendCapabilities, TranscriptionBackend, TranscriptionRequest
from ..config import Settings, load_settings, save_settings
from ..engine import FileResult, ProgressEvent, limit_parallel
from ..errors import LectureScribeError
from ..logsetup import get_logger
from ..notify import completion_message, notify_completion
from ..perf import (
    show_in_dock,
    available_memory_gb,
    check_memory_headroom,
    model_memory_gb,
    process_rss_mb,
    release_memory,
)
from ..postprocess import suggest_glossary_terms
from ..provenance import stale_sources, stale_warning
from ..prompt import PromptPlan
from . import strings_ko as S
from .dropzone import DropZone
from .notifier import AppNotifier
from .settings_panel import SettingsPanel
from .splitter import GripSplitter
from .watchdog import UiWatchdog
from .worker import TokenCountWorker, TokenUsage, TranscribeJob, TranscribeWorker

logger = get_logger(__name__)

MIN_SIDE = 480
#: 분할선 두께(px). 기본값은 너무 얇아 끌기 어렵다.
_SPLITTER_HANDLE = 12


DEFAULT_SIDE = 640
_TOKEN_DEBOUNCE_MS = 400


def make_backend(settings: Settings) -> TranscriptionBackend:
    """설정에 맞는 백엔드 인스턴스를 만든다(워커 스레드에서 호출)."""
    if settings.backend == "mlx":
        from ..backends.mlx import MlxWhisperBackend, is_available

        if is_available():
            return MlxWhisperBackend(model_name=settings.model)
        logger.warning(
            "mlx 백엔드를 쓸 수 없어 faster-whisper로 전환합니다"
            "(설치하려면 `uv sync --extra mlx`)."
        )
    from ..backends.faster import FasterWhisperBackend, default_download_root

    return FasterWhisperBackend(
        model_name=settings.model,
        compute_type=settings.compute_type,
        cpu_threads=settings.cpu_threads,
        num_workers=max(1, settings.max_parallel_files),
        download_root=default_download_root(),
    )


class MainWindow(QWidget):
    """LectureScribe 메인 창."""

    def __init__(self, initial_files: list[Path] | None = None) -> None:
        super().__init__()
        self._settings = load_settings()
        self._worker: TranscribeWorker | None = None
        self._token_worker: TokenCountWorker | None = None
        self._token_pending = False
        self._results: dict[Path, FileResult] = {}
        self._backend_lock = threading.Lock()
        self._low_memory_warned = False
        self._height_before_advanced: int | None = None
        self._split_applied = False
        self._stale_warned = False
        # FIX_GUIDE_7.md E-02: 자동 추가 직후 1회만 토큰 정리를 적용하기 위한 게이트.
        self._glossary_prune_pending = False
        self._glossary_last_added: list[str] = []
        # 백엔드(=토크나이저·모델 보유) 인스턴스를 재사용한다. 매번 새로 만들면
        # 토크나이저 로드에 수백 ms가 걸려 UI가 멈춘다.
        self._backend_cache: dict[tuple[str, str, str], TranscriptionBackend] = {}

        self.setWindowTitle(S.APP_TITLE)
        self.setMinimumSize(MIN_SIDE, MIN_SIDE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.panel = SettingsPanel(self._settings)
        # 창이 작거나 고급 설정을 펼치면 내용이 잘리므로 스크롤 영역에 넣는다.
        self.panel_scroll = QScrollArea()
        self.panel_scroll.setWidget(self.panel)
        self.panel_scroll.setWidgetResizable(True)
        self.panel_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.panel_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.panel_scroll.setMinimumHeight(110)
        # 스크롤 영역이 내용 전체 높이를 요구하면 분할선 위치가 그 값에 끌려간다.
        # 세로 sizeHint를 무시시켜야 사용자가 정한 비율이 그대로 유지된다.
        self.panel_scroll.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Ignored
        )

        self.dropzone = DropZone()
        self.dropzone.setMinimumHeight(140)

        # 사용자가 위·아래 비율을 직접 조절할 수 있게 한다(기본 40:60).
        self.splitter = GripSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.panel_scroll)
        self.splitter.addWidget(self.dropzone)
        self.splitter.setStretchFactor(0, 40)
        self.splitter.setStretchFactor(1, 60)
        # macOS 기본 분할선은 몇 px라 잡히지도, 보이지도 않는다. 끌 수 있다는 걸
        # 알아볼 수 있게 넓히고 손잡이를 그린다.
        self.splitter.setHandleWidth(_SPLITTER_HANDLE)

        self.splitter.setToolTip(S.SPLITTER_TIP)
        layout.addWidget(self.splitter)

        # 전사 중 창이 멈춘다는 보고가 있었으나 재현되지 않았다. 다음에 발생하면
        # 원인을 알 수 있도록 메인 스레드 정지를 로그에 남긴다.
        self._watchdog = UiWatchdog(self)
        self._watchdog.start()

        # osascript 알림은 Script Editor 소유라 눌러도 그게 열린다(실사용 보고).
        # 앱 이름으로 내고 클릭하면 이 창이 올라오게 한다. 아이콘은 넘기지
        # 않는다 — AppNotifier가 트레이 전용 템플릿 실루엣을 알아서 쓴다
        # (FIX_GUIDE_4.md A-05; 컬러 앱 아이콘을 넘기면 다크 메뉴 막대에서
        # 거의 안 보인다).
        self._notifier = AppNotifier(self._raise_window, parent=self)

        self._install_shortcuts()
        self._restore_geometry()
        self._connect()
        self._refresh_capabilities()
        self._schedule_token_count()

        if initial_files:
            self.add_files(initial_files)

    def _raise_window(self) -> None:
        """알림이나 메뉴 막대 아이콘을 눌렀을 때 창을 앞으로 가져온다."""
        show_in_dock()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _install_shortcuts(self) -> None:
        """⌘Q / ⌘W 로 종료.

        메뉴 막대가 없는 창이라 기본 단축키가 붙지 않는다. 끄기 어려우면 앱을
        켜 둔 채로 두게 되고, 그러면 코드를 고쳐도 옛 코드가 계속 돈다
        (실제로 이것 때문에 고친 버그가 재현되는 것처럼 보였다).
        """
        # `StandardKey`는 쓰지 않는다. 실측하니 `Quit`은 빈 시퀀스가 되고
        # `Close`는 ⌘W가 아니라 ⌘F4로 잡혔다. macOS에서 Qt는 Ctrl을 ⌘로 매핑하므로
        # "Ctrl+Q"/"Ctrl+W"라고 쓰면 실제로는 ⌘Q/⌘W가 된다.
        for keys in ("Ctrl+Q", "Ctrl+W"):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self.close)

    @staticmethod
    def _backend_key(settings: Settings) -> tuple[str, str, str]:
        return (settings.backend, settings.model, settings.compute_type)

    def _backend_for(self, settings: Settings) -> TranscriptionBackend:
        """설정별 백엔드 인스턴스를 캐시해서 돌려준다.

        여러 워커 스레드가 동시에 호출하므로 락으로 보호한다.
        같은 (백엔드, 모델, compute_type)이면 인스턴스를 공유해 메모리를 아낀다.

        생성은 **락 밖에서** 한다. 락을 쥔 채로 만들면 그동안 UI 스레드의
        `_refresh_capabilities()`가 같은 락에서 막혀 창이 멈춘다.
        """
        key = self._backend_key(settings)
        with self._backend_lock:
            backend = self._backend_cache.get(key)
            if backend is not None:
                return backend
        created = make_backend(settings)
        with self._backend_lock:
            # 그 사이 다른 스레드가 먼저 넣었으면 그쪽을 쓴다(중복 로드 방지).
            existing = self._backend_cache.get(key)
            if existing is not None:
                return existing
            self._backend_cache[key] = created
            return created

    def _dispose_backend(self, settings: Settings) -> None:
        """실패한 백엔드를 캐시에서 빼고 메모리를 돌려준다(워커 스레드에서 호출).

        캐시에 남겨 두면 반쯤 로드된 모델이 메모리를 계속 붙들고, 다음 작업이
        같은 인스턴스를 다시 써서 또 실패한다.
        """
        key = self._backend_key(settings)
        with self._backend_lock:
            backend = self._backend_cache.pop(key, None)
        if backend is None:
            return
        try:
            backend.unload()
        except Exception:  # noqa: BLE001 - 정리 중 예외는 삼키되 기록은 남긴다
            logger.exception("백엔드 해제 실패 %s", key)
        freed = release_memory()
        logger.info("실패한 백엔드 %s 해제 (%.0fMB 반환)", key, freed)

    # --- 배선 ---

    def _connect(self) -> None:
        # 유휴 시 모델 해제 타이머 (실측: large-v3 해제 시 약 1.6GB 반환)
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._unload_models)

        self._token_timer = QTimer(self)
        self._token_timer.setSingleShot(True)
        self._token_timer.setInterval(_TOKEN_DEBOUNCE_MS)
        self._token_timer.timeout.connect(self._start_token_count)

        self.panel.prompt_changed.connect(self._schedule_token_count)
        self.panel.backend_changed.connect(self._refresh_capabilities)
        self.panel.advanced_toggled.connect(self._on_advanced_toggled)
        self.dropzone.files_added.connect(self.add_files)
        self.dropzone.start_requested.connect(self._start_transcription)
        self.dropzone.cancel_requested.connect(self._cancel_transcription)
        self.dropzone.remove_requested.connect(self._on_remove_row)
        self.dropzone.retry_requested.connect(self._on_retry_row)
        self.panel.model_changed.connect(self.dropzone.set_default_model)
        self.dropzone.set_default_model(self.panel.current_model())

    def _on_advanced_toggled(self, expanded: bool) -> None:
        """고급 설정을 펼치면 잘리지 않게 창을 키운다.

        FIX_GUIDE_6.md C-04: 정방형 강제를 풀었으므로 **높이만** 늘린다(폭은 그대로).
        접을 때는 사용자가 조정했을 수 있으니 임의로 줄이지 않고, 펼치기 직전
        높이로만 되돌린다.
        """
        if not expanded:
            if self._height_before_advanced is not None:
                height = max(MIN_SIDE, self._height_before_advanced)
                self._height_before_advanced = None
                self._apply_height(height)
            return
        self._height_before_advanced = self.height()
        # 패널이 필요로 하는 높이 + 드롭존 최소 높이 + 여백
        needed = (
            self.panel.sizeHint().height()
            + self.dropzone.minimumHeight()
            + self.splitter.handleWidth()
            + 24
        )
        height = max(self.height(), min(needed, self._max_height()))
        if height > self.height():
            self._apply_height(height)
        # 펼친 내용이 다 보이도록 위쪽을 늘리되, 사용자가 이미 더 넓게 끌어 놨다면
        # 그 선택을 존중한다(임의로 줄이지 않는다).
        wanted = min(
            self.panel.sizeHint().height(), height - self.dropzone.minimumHeight()
        )
        current = self.splitter.sizes()[0] if self.splitter.sizes() else 0
        panel_height = max(current, wanted)
        self.splitter.setSizes([panel_height, max(1, height - panel_height)])

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """첫 표시 때 저장된 분할 비율을 다시 적용한다.

        생성자에서 `setSizes()`로 넣은 값은 창이 처음 그려질 때 레이아웃 재배치에
        덮인다(실측: 0.40으로 넣어도 0.78이 됐다). 표시 직후 한 번 더 적용한다.
        """
        super().showEvent(event)
        if not self._split_applied:
            self._split_applied = True
            # 레이아웃이 자리를 잡은 뒤에 적용해야 정확하다(높이가 아직 확정 전이다).
            QTimer.singleShot(
                0, lambda: self._apply_split_ratio(self._settings.window.split_ratio)
            )

    def _apply_split_ratio(self, ratio: float) -> None:
        total = max(1, self.splitter.height())
        top = int(total * min(0.85, max(0.15, ratio)))
        self.splitter.setSizes([top, max(1, total - top)])

    def split_ratio(self) -> float:
        """위(설정) 영역이 차지하는 비율. 사용자가 끌어 놓은 위치를 그대로 기억한다."""
        sizes = self.splitter.sizes()
        total = sum(sizes)
        if total <= 0 or len(sizes) < 2:
            return self._settings.window.split_ratio
        return min(0.85, max(0.15, sizes[0] / total))

    def _max_height(self) -> int:
        """화면 밖으로 나가지 않을 최대 높이."""
        screen = self.screen()
        if screen is None:
            return DEFAULT_SIDE * 2
        area = screen.availableGeometry()
        return max(MIN_SIDE, area.height() - 40)

    def _apply_height(self, height: int) -> None:
        self.resize(self.width(), height)

    # FIX_GUIDE_6.md C-04: 정방형 강제 제거. 최소 크기(480×480)만 유지하고
    # 폭·높이를 독립적으로 조절할 수 있게 한다(고급 설정이 상시 펼침이라
    # 세로로만 늘릴 수 없으면 항상 스크롤 상태가 된다 — 실사용 문제).

    def _restore_geometry(self) -> None:
        state = self._settings.window
        width = max(MIN_SIDE, state.width or DEFAULT_SIDE)
        height = max(MIN_SIDE, state.height or DEFAULT_SIDE)
        self.resize(width, height)
        if state.x is not None and state.y is not None:
            self.move(state.x, state.y)
        ratio = state.split_ratio
        self.splitter.setSizes([int(height * ratio), int(height * (1.0 - ratio))])

    # --- 토큰 계산 ---

    def _schedule_token_count(self) -> None:
        self.panel.set_token_usage(None, S.TOKEN_COUNTING)
        self._token_timer.start()

    def _start_token_count(self) -> None:
        if self._token_worker is not None and self._token_worker.isRunning():
            self._token_pending = True
            return
        settings = self.panel.build_settings()
        worker = TokenCountWorker(
            backend_factory=lambda: self._backend_for(settings),
            topic=self.panel.current_topic(),
            glossary=self.panel.current_glossary(),
            max_tokens=settings.prompt.max_prompt_tokens,
            language="en" if settings.language == "en" else "ko",
        )
        worker.counted.connect(self._on_token_counted)
        worker.failed.connect(self._on_token_failed)
        worker.finished.connect(self._on_token_worker_done)
        self._token_worker = worker
        worker.start()

    def _on_token_counted(self, usage: TokenUsage) -> None:
        self.panel.set_token_usage(usage)
        self._maybe_prune_glossary(usage)

    def _maybe_prune_glossary(self, usage: TokenUsage) -> None:
        """FIX_GUIDE_7.md E-02: 자동 추가 직후 예산을 넘겼으면 자동 추가분만 뺀다.

        플래그는 여기서 한 번 쓰고 바로 내린다 — 사용자가 그 뒤에 타이핑해서 도는
        토큰 계산에는 적용되지 않는다(§3-1·§3-4).
        """
        if not self._glossary_prune_pending:
            return
        self._glossary_prune_pending = False
        added = self._glossary_last_added
        self._glossary_last_added = []
        if not usage.dropped_terms:
            return
        removed = self.panel.prune_glossary_terms(usage.dropped_terms)
        if not removed:
            return
        logger.info("토큰 한도 초과로 자동 용어 제거: %s", ", ".join(removed))
        if added:
            self.panel.set_status_message(
                S.GLOSSARY_AUTO_ADDED_AND_PRUNED.format(
                    added_count=len(added),
                    removed_count=len(removed),
                    removed_terms=", ".join(removed),
                )
            )
        else:
            self.panel.set_status_message(
                S.GLOSSARY_AUTO_PRUNED.format(
                    count=len(removed), terms=", ".join(removed)
                )
            )

    def _on_token_failed(self, message: str) -> None:
        self.panel.set_token_usage(None, f"{S.TOKEN_ERROR} — {message}")

    def _on_token_worker_done(self) -> None:
        if self._token_pending:
            self._token_pending = False
            self._start_token_count()

    # --- 백엔드 능력 ---

    def _refresh_capabilities(self) -> None:
        settings = self.panel.build_settings()
        try:
            backend = self._backend_for(settings)
            caps: BackendCapabilities = backend.capabilities(
                TranscriptionRequest(
                    audio_path=Path("dummy.m4a"), batched=self.panel.batched()
                )
            )
        except LectureScribeError as exc:
            logger.warning("백엔드 능력 조회 실패: %s", exc.log_message)
            return
        self.panel.apply_capabilities(caps)

    # --- 큐 ---

    def _ensure_worker(self) -> TranscribeWorker:
        """상시 실행 전사 워커. 한 번 만들면 앱이 닫힐 때까지 유지한다."""
        if self._worker is None:
            # 가용 메모리·코어·백엔드에 맞춰 동시 전사 수를 정한다. 메모리가 빠듯하면
            # 동시 처리가 오히려 느려지고(스왑), mlx는 모델을 공유해서 1개만 가능하다.
            parallel = limit_parallel(
                max(1, self._settings.max_parallel_files),
                self._settings.model,
                self._settings.backend,
            )
            logger.info(
                "전사 워커 시작(동시 %d개, 백엔드 %s)", parallel, self._settings.backend
            )
            worker = TranscribeWorker(
                backend_provider=self._backend_for,
                parallel=parallel,
                backend_disposer=self._dispose_backend,
            )
            worker.job_started.connect(self._on_job_started)
            worker.progressed.connect(self._on_progress)
            worker.job_done.connect(self._on_job_done)
            worker.plan_ready.connect(self._on_plan_ready)
            worker.failed.connect(self._on_job_failed)
            worker.went_idle.connect(self._on_idle)
            worker.start()
            self._worker = worker
        return self._worker

    def add_files(self, paths: list[Path]) -> None:
        """파일을 큐에 **덧붙인다.** 전사 중에도 언제든 호출할 수 있다."""
        accepted, rejected = collect_inputs(
            paths, recursive=self._settings.recursive_folder_drop
        )
        if rejected:
            names = ", ".join(path.name for path, _ in rejected[:5])
            QMessageBox.information(
                self,
                S.APP_TITLE,
                S.UNSUPPORTED_FILES.format(count=len(rejected), names=names),
            )
        if not accepted:
            return
        durations: dict[Path, float] = {}
        for path in accepted:
            try:
                durations[path] = probe_duration(path)
            except LectureScribeError:
                durations[path] = 0.0
        self.dropzone.add_paths(accepted, durations)

    def _on_remove_row(self, path: Path) -> None:
        self.dropzone.remove_row(path)

    def _on_retry_row(self, path: Path) -> None:
        """실패한 파일 하나를 다시 큐에 넣는다.

        행을 대기 상태로 되돌린 뒤 `_start_transcription()`을 그대로 태운다.
        모델을 바꿔서 재시도하는 경우가 많으므로, 그 시점의 행 선택을 따른다.
        """
        self.dropzone.reset_row(path)
        self._start_transcription()

    def _unload_models(self) -> None:
        """유휴 상태가 이어지면 모델을 내려 메모리를 돌려준다."""
        if self._worker is not None and self._worker.busy:
            return
        with self._backend_lock:
            if not self._backend_cache:
                return
            before = process_rss_mb()
            for backend in self._backend_cache.values():
                backend.unload()
            self._backend_cache.clear()
        logger.info(
            "유휴 상태라 모델을 내렸습니다 (%.0fMB -> %.0fMB)", before, process_rss_mb()
        )

    def _schedule_idle_unload(self) -> None:
        minutes = self._settings.performance.unload_model_after_idle_min
        if minutes > 0:
            self._idle_timer.start(minutes * 60 * 1000)

    def _start_transcription(self) -> None:
        """대기 중인 행을 큐에 넣는다. 전사 중에도 누를 수 있다."""
        pending = self.dropzone.pending_paths()
        if not pending:
            QMessageBox.information(self, S.APP_TITLE, S.QUEUE_NOTHING_PENDING)
            return
        self._idle_timer.stop()
        settings = self.panel.build_settings()
        if not self._ensure_memory_for(settings):
            return
        try:
            save_settings(settings)
        except LectureScribeError as exc:
            logger.warning("설정 저장 실패: %s", exc.log_message)
        self._settings = settings

        worker = self._ensure_worker()
        worker.rearm()
        for path in pending:
            # 파일별 모델 + 지금 시점의 프리셋/용어를 스냅샷으로 고정
            job_settings = replace(settings, model=self.dropzone.model_for(path))
            self.dropzone.set_row_state(path, "waiting")
            worker.submit(
                TranscribeJob(
                    path=path,
                    settings=job_settings,
                    batched=self.panel.batched(),
                )
            )
        self.dropzone.set_running(True)

    def _ensure_memory_for(self, settings: Settings) -> bool:
        """전사를 시작해도 되는지 확인한다. 진행 가능하면 True.

        메모리가 빠듯하면 **먼저 안 쓰는 모델을 내려 회수한 뒤** 다시 잰다.
        그래도 부족하면 시작하지 않고 무엇을 하면 되는지 알려 준다. 그냥 밀어붙이면
        Metal 안쪽에서 죽어 원인을 알 수 없는 실패가 나기 때문이다(실측).
        """
        needed = model_memory_gb(settings.model) + 2.0
        available = available_memory_gb()
        if available <= 0 or available >= needed:
            return True

        # 1차: 캐시된 모델을 내려 회수한다.
        if not (self._worker is not None and self._worker.busy):
            self._unload_models()
            available = available_memory_gb()
            if available >= needed:
                logger.info("모델을 내려 메모리를 확보했습니다(%.1fGB)", available)
                return True

        lighter = (
            "large-v3-turbo"
            if not settings.model.startswith("large-v3-turbo")
            else "medium"
        )
        if settings.backend == "mlx":
            # GPU는 여유가 없으면 시작 자체가 실패한다. 막고 대안을 제시한다.
            QMessageBox.warning(
                self,
                S.APP_TITLE,
                f"GPU(Metal) 전사를 시작할 메모리가 부족합니다.\n\n"
                f"필요: 약 {needed:.1f}GB / 지금 가용: {available:.1f}GB\n\n"
                f"다음 중 하나를 해보세요.\n"
                f"  · 다른 앱을 닫는다\n"
                f"  · 더 가벼운 모델({lighter})을 고른다\n"
                f"  · 백엔드를 CPU(faster-whisper)로 바꾼다",
            )
            return False

        if settings.performance.warn_low_memory and not self._low_memory_warned:
            warning = check_memory_headroom(settings.model)
            if warning:
                self._low_memory_warned = True
                QMessageBox.information(self, S.APP_TITLE, warning)
        return True

    def _cancel_transcription(self) -> None:
        if self._worker is not None:
            self._worker.cancel_all()
            for path in self.dropzone.pending_paths():
                self.dropzone.set_row_state(path, "cancelled")

    # --- 워커 시그널 ---

    def _on_job_started(self, path: Path) -> None:
        self.dropzone.set_row_state(path, "running")
        self.dropzone.set_running(True)

    def _on_progress(self, event: ProgressEvent) -> None:
        # FIX_GUIDE.md G-05: 메시지가 빈 문자열이어도 "모델 준비 중…"은 실제로
        # 모델을 (다시) 로드하는 stage에서만 쓴다. mlx는 VAD가 없어 무음/공백
        # 세그먼트가 흔한데, 그럴 때 전사 중인 것을 모델 재로드처럼 잘못 표시하면
        # 사용자가 멈춘 걸로 오해한다(실사용 보고).
        if event.message:
            message = event.message
        elif event.stage == "model":
            message = S.MODEL_PREPARING
        else:
            message = S.PROCESSING_GENERIC
        self.dropzone.set_row_progress(
            event.file, event.percent, message, event.eta_sec
        )

    def _on_job_done(self, result: FileResult) -> None:
        state = {
            "ok": "done",
            "failed": "failed",
            "cancelled": "cancelled",
            "skipped": "skipped",
        }.get(result.status, "failed")
        self._results[result.audio_path] = result
        if result.status == "ok":
            self._auto_suggest_glossary(result)
        self.dropzone.set_row_result(result.audio_path, result)
        self.dropzone.set_row_state(result.audio_path, state)  # type: ignore[arg-type]
        # FIX_GUIDE_14 T-01: 워커 스레드의 release_memory()는 Qt 크래시를 피하려고
        # gc.collect()를 건너뛴다. 이 슬롯은 메인 스레드에서 도니(Qt 시그널) 여기서
        # 한 번 더 돌려 건너뛴 회수량을 보전한다.
        if self._settings.performance.release_memory_after_file:
            freed = release_memory()
            if freed > 64:
                logger.info(
                    "메모리 %.0fMB 반환(메인 스레드 보전) %s", freed, result.audio_path.name
                )

    def _auto_suggest_glossary(self, result: FileResult) -> None:
        """전사에 자주 나온 전문어를 용어 칸에 채워 넣는다.

        신뢰도 높은 구간에서만 뽑는다. 잘못 인식된 단어를 용어집에 넣으면 다음
        전사에서 오류가 고착되기 때문이다(실측 확인).

        FIX_GUIDE_7.md E-01: 등장 횟수를 프리셋별로 누적·감쇠해 두고, 자동 추가분을
        점수 내림차순으로 정렬한다. E-02: 이어서 토큰 예산을 넘기면(다음
        `_on_token_counted` 호출에서) 점수 낮은 자동 추가분부터 실제로 뺀다.
        FIX_GUIDE_14 G-03: 점수 갱신(감쇠) 뒤에는 오래 안 나온 자동 추가분을 칸에서도
        뺀다 — 안 그러면 한 번 들어간 잡음이 다시 안 나와도 영원히 남는다.
        """
        settings = self._settings
        if not settings.postprocess.auto_suggest_glossary or not result.segments:
            return
        suggestions = suggest_glossary_terms(
            result.segments,
            self.panel.current_glossary(),
            limit=settings.postprocess.auto_suggest_limit,
        )
        if not suggestions:
            return
        added = self.panel.record_glossary_detections(suggestions)
        # 감쇠는 record_glossary_detections 안에서 이미 끝났다 — 새 용어가 없어도
        # (added가 비어도) 기존 자동 추가분의 점수는 갱신됐으니 만료를 확인한다.
        expired = self.panel.expire_stale_auto_terms()
        if expired:
            logger.info("자동 추가 용어 만료(%s): %s", result.audio_path.name, ", ".join(expired))
        if not added and not expired:
            return
        if added:
            logger.info("용어 자동 추가(%s): %s", result.audio_path.name, ", ".join(added))
        messages = []
        if added:
            messages.append(S.GLOSSARY_AUTO_ADDED.format(count=len(added), terms=", ".join(added)))
        if expired:
            messages.append(S.GLOSSARY_AUTO_EXPIRED.format(count=len(expired), terms=", ".join(expired)))
        self.panel.set_status_message(" / ".join(messages))
        if not added:
            return
        # 다음 토큰 계산 결과에서만(자동 추가 직후 1회) 정리 여부를 판단한다 —
        # 사용자가 타이핑하는 중의 토큰 계산에는 절대 적용하지 않는다(§3-1 게이트).
        self._glossary_prune_pending = True
        self._glossary_last_added = added

    def _on_job_failed(self, path: Path, message: str) -> None:
        logger.warning("작업 실패 %s: %s", path.name, message)
        # 켜 둔 사이에 코드가 바뀌었다면, 지금 도는 것은 옛 코드다. 이미 고친 버그가
        # 그대로 재현되는 것처럼 보이므로 반드시 알려 준다(실제로 오진된 적 있다).
        warning = stale_warning()
        if warning and not self._stale_warned:
            self._stale_warned = True
            logger.warning("낡은 코드로 실행 중: %s", ", ".join(stale_sources()))
            QMessageBox.warning(self, S.APP_TITLE, warning)

    def _on_idle(self) -> None:
        """큐가 비었다. 알림을 띄우고 취소 버튼을 끈 뒤 유휴 해제 타이머를 건다."""
        self.dropzone.set_running(False)
        self._low_memory_warned = False
        self._schedule_idle_unload()
        results = list(self._results.values())
        self._results.clear()
        if not results:
            return
        first_output = next(
            (
                outcome.path
                for result in results
                for outcome in result.outputs
                if outcome.path is not None
            ),
            None,
        )
        ok_count = sum(1 for r in results if r.status == "ok")
        failed_count = sum(1 for r in results if r.status == "failed")
        if not self._notifier.notify(S.APP_TITLE, completion_message(
            ok_count, failed_count, first_output
        )):
            # FIX_GUIDE_3.md I-04: 트레이를 못 쓰는 환경에서만 여기로 온다.
            # osascript 알림은 스크립트 편집기 소유로 뜬다(실사용 보고) — 왜
            # 이게 뜨는지 사용자가 알 길이 없었으므로 사유를 로그로 남긴다.
            logger.info(
                "트레이 알림을 쓸 수 없어 osascript로 대체합니다 "
                "(알림을 누르면 스크립트 편집기가 열립니다)"
            )
            notify_completion(
                ok_count=ok_count, failed_count=failed_count, first_output=first_output
            )

    def _on_plan_ready(self, path: Path, plan: PromptPlan) -> None:
        """워커가 만든 프롬프트 계획의 경고(용어 잘림 등)를 표시한다."""
        if plan.dropped_terms:
            self.panel.set_token_usage(
                TokenUsage(plan.used_tokens, plan.budget_tokens, list(plan.dropped_terms))
            )
        for warning in plan.warnings:
            logger.warning("%s [%s]", warning, path.name)

    # --- 종료 ---

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._watchdog.stop()
        self._notifier.hide()
        if self._worker is not None:
            self._worker.cancel_all()
            self._worker.stop()
            self._worker.wait(5000)
        if self._token_worker is not None and self._token_worker.isRunning():
            self._token_worker.wait(2000)
        settings = self.panel.build_settings()
        settings.window.width = self.width()
        settings.window.height = self.height()
        settings.window.x = self.x()
        settings.window.y = self.y()
        settings.window.split_ratio = self.split_ratio()
        try:
            save_settings(settings)
        except LectureScribeError as exc:
            logger.warning("설정 저장 실패: %s", exc.log_message)
        logger.info(
            "종료 — 창 %dx%d, 분할 비율 %.2f 저장",
            settings.window.width,
            settings.window.height,
            settings.window.split_ratio,
        )
        super().closeEvent(event)
        # 창이 유일한 최상위 위젯이므로 닫히면 앱도 끝나야 한다. 남아 있으면
        # 다음에 코드를 고쳐도 옛 프로세스가 계속 돈다.
        app = QApplication.instance()
        if app is not None:
            app.quit()
