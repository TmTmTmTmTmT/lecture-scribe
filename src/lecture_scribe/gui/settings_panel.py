"""상단 설정 패널 (§8).

- 프리셋 드롭다운 + 저장/이름 변경/삭제
- 주제(여러 줄) / 용어(한 줄, 실시간 토큰 사용량 표시)
- 언어·모델 콤보박스
- 나머지 상세 옵션은 "고급 설정" 디스클로저 안에 접어 둔다(기본 접힘)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QSizePolicy,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..backends.base import BackendCapabilities
from ..config import (
    MODEL_NAMES,
    ConflictPolicy,
    LanguageCode,
    OutputFormat,
    Preset,
    Settings,
)
from ..correction import CORRECTION_MODELS, list_installed_gemma_models, ollama_available
from ..glossary_stats import (
    PresetGlossaryStats,
    default_stats_path,
    load_stats,
    order_glossary,
    save_stats,
    update_scores,
)
from ..ocr import ocr_available
from ..postprocess import fuzzy_available
from ..prompt import parse_glossary
from . import strings_ko as S
from .worker import TokenUsage

_LANGUAGES: list[tuple[str, str]] = [
    ("ko", S.LANGUAGE_KO),
    ("en", S.LANGUAGE_EN),
    ("auto", S.LANGUAGE_AUTO),
]
_CONFLICTS: list[tuple[str, str]] = [
    ("suffix", S.CONFLICT_SUFFIX),
    ("overwrite", S.CONFLICT_OVERWRITE),
    ("skip", S.CONFLICT_SKIP),
]
_FORMATS: tuple[str, ...] = ("txt", "md", "srt", "vtt", "json")

#: FIX_GUIDE_14 G-03: 이 아래로 점수가 떨어진 자동 추가분은 용어 칸에서도 뺀다.
#: 최소 등장 구간 수(3점)짜리가 감쇠 0.8/건으로 약 5건 연속 미등장하면 0.98로 떨어져
#: 빠진다(3 * 0.8**5 ≈ 0.98 < 1.0). 자주 나오는 용어는 매번 다시 더해져 유지된다.
GLOSSARY_EXPIRE_SCORE: Final[float] = 1.0


class SettingsPanel(QWidget):
    """설정 입력 위젯."""

    prompt_changed = Signal()  # 주제/용어/모델 변경 -> 토큰 재계산
    backend_changed = Signal()
    model_changed = Signal(str)  # 새로 추가되는 파일의 기본 모델
    advanced_toggled = Signal(bool)  # 고급 설정 펼침/접힘 -> 창 크기 조정

    def __init__(
        self,
        settings: Settings,
        parent: QWidget | None = None,
        *,
        glossary_stats_path: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._loading = False
        # FIX_GUIDE_7.md E-01: 자동 추가 용어의 등장 빈도 통계(프리셋별, 파일 영속).
        # Preset/Settings에는 넣지 않는다 — build_settings()가 Preset을 새로 만들 때
        # 알려진 필드만 옮겨 담아서 조용히 사라진다(§2-1).
        # 경로를 주입 가능하게 둔다 — 안 그러면 테스트가 실제 사용자 통계 파일을 건드린다.
        self._glossary_stats_path = glossary_stats_path or default_stats_path()
        self._glossary_stats: dict[str, PresetGlossaryStats] = load_stats(
            self._glossary_stats_path
        )
        #: 현재 프리셋에서 "이 앱이 자동으로 넣은 것"으로 취급 중인 용어(용어 칸 안).
        self._auto_glossary_terms: set[str] = set()
        self._build()
        self._load_settings()

    # --- 구성 ---

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 6)
        layout.setSpacing(6)

        # 프리셋 줄
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        preset_row.addWidget(QLabel(S.PRESET_LABEL))
        # 좁은 창에서 버튼 4개가 프리셋 콤보를 밀어내지 않게 최소 폭을 준다
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumWidth(90)
        self.preset_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        preset_row.addWidget(self.preset_combo, 1)
        self.preset_new = QPushButton(S.PRESET_NEW)
        self.preset_new.setToolTip("빈 주제·용어로 새 프리셋을 만듭니다(과목별로 하나씩).")
        self.preset_save = QPushButton(S.PRESET_SAVE)
        self.preset_save.setToolTip("지금 입력한 주제·용어를 현재 프리셋에 저장합니다.")
        self.preset_rename = QPushButton(S.PRESET_RENAME)
        self.preset_delete = QPushButton(S.PRESET_DELETE)
        for button in (
            self.preset_new,
            self.preset_save,
            self.preset_rename,
            self.preset_delete,
        ):
            button.setFixedHeight(24)
            button.setSizePolicy(
                QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed
            )
            preset_row.addWidget(button)
        layout.addLayout(preset_row)

        # 주제
        layout.addWidget(QLabel(S.TOPIC_LABEL))
        self.topic_edit = QPlainTextEdit()
        self.topic_edit.setPlaceholderText(S.TOPIC_PLACEHOLDER)
        self.topic_edit.setToolTip(S.TOPIC_TIP)
        # 고정 높이는 창이 작을 때 다른 요소를 밀어낸다. 범위로 둔다.
        self.topic_edit.setMinimumHeight(44)
        self.topic_edit.setMaximumHeight(96)
        self.topic_edit.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.topic_edit)

        # 용어 + 토큰 사용량
        layout.addWidget(QLabel(S.GLOSSARY_LABEL))
        self.glossary_edit = QLineEdit()
        self.glossary_edit.setPlaceholderText(S.GLOSSARY_PLACEHOLDER)
        self.glossary_edit.setToolTip(S.GLOSSARY_TIP)
        layout.addWidget(self.glossary_edit)
        self.token_label = QLabel("")
        self.token_label.setWordWrap(True)
        self.token_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.token_label)
        # 자동 용어 추가 등 일회성 안내
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setEnabled(False)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        # 언어 / 모델
        basic_row = QHBoxLayout()
        basic_row.setSpacing(6)
        basic_row.addWidget(QLabel(S.LANGUAGE_LABEL))
        self.language_combo = QComboBox()
        self.language_combo.setToolTip(S.LANGUAGE_TIP)
        for code, label in _LANGUAGES:
            self.language_combo.addItem(label, code)
        basic_row.addWidget(self.language_combo, 1)
        basic_row.addWidget(QLabel(S.MODEL_LABEL))
        self.model_combo = QComboBox()
        self.model_combo.setToolTip(S.MODEL_TIP)
        self.model_combo.addItems(list(MODEL_NAMES))
        basic_row.addWidget(self.model_combo, 1)
        layout.addLayout(basic_row)

        # 고급 디스클로저
        # 고급 설정은 상시 표시한다. 접어 두면 어떤 설정이 켜져 있는지 알 수 없어
        # 문제가 생겼을 때 원인 추적이 어렵다(사용자 요청).
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText(S.ADVANCED)
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(True)
        self.advanced_toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.advanced_toggle.setAutoRaise(True)
        layout.addWidget(self.advanced_toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.advanced_box = QWidget()
        self.advanced_box.setVisible(True)
        advanced_layout = QVBoxLayout(self.advanced_box)
        advanced_layout.setContentsMargins(8, 0, 0, 0)
        advanced_layout.setSpacing(4)
        intro = QLabel(S.ADVANCED_INTRO)
        intro.setWordWrap(True)
        intro.setEnabled(False)
        advanced_layout.addWidget(intro)

        # FIX_GUIDE_6.md C-03: 14행 평면 나열 대신 4구역(인식/프롬프트/출력/후처리)으로
        # 나누고 소제목 + 구분선을 붙인다. 순수 재배치 — 기본값·툴팁은 그대로.
        def add_section(title: str, *, first: bool = False) -> QFormLayout:
            if not first:
                divider = QFrame()
                divider.setFrameShape(QFrame.Shape.HLine)
                divider.setFrameShadow(QFrame.Shadow.Sunken)
                advanced_layout.addWidget(divider)
            heading = QLabel(title)
            heading.setEnabled(False)
            font = heading.font()
            font.setBold(True)
            font.setPointSize(max(1, font.pointSize() - 1))
            heading.setFont(font)
            advanced_layout.addWidget(heading)
            holder = QWidget()
            advanced_layout.addWidget(holder)
            section_form = QFormLayout(holder)
            section_form.setContentsMargins(0, 0, 0, 0)
            section_form.setSpacing(4)
            return section_form

        # FIX_GUIDE_6.md C-05: 전부가 아니라 "잘못 켜면 결과가 나빠지는" 항목과
        # "백엔드에 따라 무시되는" 항목만 툴팁 밖으로 한 줄 낸다. 나머지는 툴팁 유지.
        def note_label(text: str) -> QLabel:
            note = QLabel(text)
            note.setEnabled(False)
            note.setWordWrap(True)
            font = note.font()
            font.setPointSize(max(1, font.pointSize() - 1))
            note.setFont(font)
            return note

        # --- 인식 ---
        form = add_section(S.SECTION_RECOGNITION, first=True)

        self.backend_combo = QComboBox()
        self.backend_combo.addItem("faster-whisper (CPU)", "faster")
        self.backend_combo.addItem("mlx-whisper (GPU)", "mlx")
        self.backend_combo.setToolTip(S.BACKEND_TIP)
        form.addRow(S.BACKEND_LABEL, self.backend_combo)

        self.batched_check = QCheckBox(S.BATCHED_LABEL)
        self.batched_check.setToolTip(S.BATCHED_TIP)
        form.addRow("", self.batched_check)
        form.addRow("", note_label(S.BATCHED_NOTE))

        self.vad_check = QCheckBox(S.VAD_LABEL)
        self.vad_check.setToolTip(S.VAD_TIP)
        form.addRow("", self.vad_check)
        self.vad_note = note_label("")
        self.vad_note.setVisible(False)
        form.addRow("", self.vad_note)

        self.beam_spin = QSpinBox()
        self.beam_spin.setRange(1, 10)
        self.beam_spin.setToolTip(S.BEAM_TIP)
        form.addRow(S.BEAM_LABEL, self.beam_spin)
        self.beam_note = note_label("")
        self.beam_note.setVisible(False)
        form.addRow("", self.beam_note)

        # --- 프롬프트 ---
        form = add_section(S.SECTION_PROMPT)

        self.initial_prompt_check = QCheckBox(S.USE_INITIAL_PROMPT)
        self.initial_prompt_check.setToolTip(S.USE_INITIAL_PROMPT_TIP)
        form.addRow("", self.initial_prompt_check)
        form.addRow("", note_label(S.USE_INITIAL_PROMPT_NOTE))

        self.hotwords_check = QCheckBox(S.USE_HOTWORDS)
        self.hotwords_check.setToolTip(S.USE_HOTWORDS_TIP)
        form.addRow("", self.hotwords_check)

        self.condition_check = QCheckBox(S.CONDITION_PREV)
        self.condition_check.setToolTip(S.CONDITION_PREV_TIP)
        form.addRow("", self.condition_check)
        form.addRow("", note_label(S.CONDITION_PREV_NOTE))

        self.carry_window_check = QCheckBox(S.CARRY_WINDOW_PROMPT)
        self.carry_window_check.setToolTip(S.CARRY_WINDOW_PROMPT_TIP)
        form.addRow("", self.carry_window_check)
        form.addRow("", note_label(S.CARRY_WINDOW_PROMPT_NOTE))

        # --- 출력 ---
        form = add_section(S.SECTION_OUTPUT)

        # 레이아웃을 부모 위젯과 함께 만들어야 높이가 잡힌다
        # (부모 없이 만든 QHBoxLayout을 나중에 setLayout으로 붙이면 높이 0이 된다)
        format_holder = QWidget()
        format_holder.setToolTip(S.FORMATS_TIP)
        format_row = QHBoxLayout(format_holder)
        format_row.setContentsMargins(0, 0, 0, 0)
        format_row.setSpacing(8)
        self.format_checks: dict[str, QCheckBox] = {}
        for fmt in _FORMATS:
            check = QCheckBox(fmt)
            self.format_checks[fmt] = check
            format_row.addWidget(check)
        format_row.addStretch(1)
        form.addRow(S.FORMATS_LABEL, format_holder)

        self.timestamps_check = QCheckBox(S.TIMESTAMPS_LABEL)
        self.timestamps_check.setToolTip(S.TIMESTAMPS_TIP)
        form.addRow("", self.timestamps_check)

        self.conflict_combo = QComboBox()
        for value, label in _CONFLICTS:
            self.conflict_combo.addItem(label, value)
        self.conflict_combo.setToolTip(S.CONFLICT_TIP)
        form.addRow(S.CONFLICT_LABEL, self.conflict_combo)

        # --- 후처리 ---
        form = add_section(S.SECTION_POSTPROCESS)

        # 전사 후 교정 (F-09)
        self.correction_check = QCheckBox(S.CORRECTION_ENABLE)
        self.correction_check.setToolTip(S.CORRECTION_TIP)
        if not ollama_available():
            self.correction_check.setEnabled(False)
            self.correction_check.setToolTip(S.CORRECTION_UNAVAILABLE)
        form.addRow(S.CORRECTION_LABEL, self.correction_check)

        self.correction_model_combo = QComboBox()
        self.correction_model_refresh = QPushButton(S.CORRECTION_MODEL_REFRESH)
        self.correction_model_refresh.setToolTip(S.CORRECTION_MODEL_REFRESH_TIP)
        self._populate_correction_models()
        self.correction_model_combo.setToolTip(S.CORRECTION_MODEL_TIP)
        self.correction_model_refresh.clicked.connect(self._refresh_correction_models)
        model_row = QWidget()
        model_row_layout = QHBoxLayout(model_row)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.addWidget(self.correction_model_combo, stretch=1)
        model_row_layout.addWidget(self.correction_model_refresh)
        form.addRow(S.CORRECTION_MODEL_LABEL, model_row)

        self.correction_confidence_combo = QComboBox()
        for value, label in (("high", "high (엄격)"), ("medium", "medium (권장)"), ("low", "low (많이)")):
            self.correction_confidence_combo.addItem(label, value)
        self.correction_confidence_combo.setToolTip(S.CORRECTION_CONFIDENCE_TIP)
        form.addRow(S.CORRECTION_CONFIDENCE_LABEL, self.correction_confidence_combo)

        self.correction_annotate_check = QCheckBox(S.CORRECTION_ANNOTATE)
        self.correction_annotate_check.setToolTip(S.CORRECTION_ANNOTATE_TIP)
        form.addRow("", self.correction_annotate_check)

        self.correction_ocr_terms_check = QCheckBox(S.CORRECTION_OCR_TERMS)
        self.correction_ocr_terms_check.setToolTip(S.CORRECTION_OCR_TERMS_TIP)
        if not ocr_available():
            self.correction_ocr_terms_check.setEnabled(False)
            self.correction_ocr_terms_check.setToolTip(S.VIDEO_OCR_UNAVAILABLE)
        form.addRow("", self.correction_ocr_terms_check)

        self.fuzzy_check = QCheckBox(S.FUZZY_LABEL)
        self.fuzzy_check.setToolTip(S.FUZZY_TIP)
        if not fuzzy_available():
            self.fuzzy_check.setEnabled(False)
            self.fuzzy_check.setToolTip(S.FUZZY_UNAVAILABLE)
        form.addRow("", self.fuzzy_check)

        self.foreign_script_check = QCheckBox(S.FOREIGN_SCRIPT_LABEL)
        self.foreign_script_check.setToolTip(S.FOREIGN_SCRIPT_TIP)
        form.addRow("", self.foreign_script_check)

        # --- 영상 입력 (PLAN_VIDEO_FRAMES.md V-07) ---
        form = add_section(S.SECTION_VIDEO)

        self.video_capture_check = QCheckBox(S.VIDEO_CAPTURE_LABEL)
        self.video_capture_check.setToolTip(S.VIDEO_CAPTURE_TIP)
        form.addRow("", self.video_capture_check)

        self.video_threshold_spin = QDoubleSpinBox()
        self.video_threshold_spin.setRange(1.0, 90.0)
        self.video_threshold_spin.setDecimals(1)
        self.video_threshold_spin.setSuffix(" %")
        self.video_threshold_spin.setToolTip(S.VIDEO_THRESHOLD_TIP)
        form.addRow(S.VIDEO_THRESHOLD_LABEL, self.video_threshold_spin)

        self.video_dedupe_spin = QDoubleSpinBox()
        self.video_dedupe_spin.setRange(0.0, 20.0)
        self.video_dedupe_spin.setDecimals(1)
        self.video_dedupe_spin.setSuffix(" %")
        self.video_dedupe_spin.setToolTip(S.VIDEO_DEDUPE_TIP)
        form.addRow(S.VIDEO_DEDUPE_LABEL, self.video_dedupe_spin)

        self.video_interval_spin = QDoubleSpinBox()
        self.video_interval_spin.setRange(1.0, 600.0)
        self.video_interval_spin.setDecimals(1)
        self.video_interval_spin.setSuffix(" 초")
        self.video_interval_spin.setToolTip(S.VIDEO_INTERVAL_TIP)
        form.addRow(S.VIDEO_INTERVAL_LABEL, self.video_interval_spin)

        self.video_ocr_check = QCheckBox(S.VIDEO_OCR_LABEL)
        self.video_ocr_check.setToolTip(S.VIDEO_OCR_TIP)
        self.video_ocr_terms_check = QCheckBox(S.VIDEO_OCR_TERMS_LABEL)
        self.video_ocr_terms_check.setToolTip(S.VIDEO_OCR_TERMS_TIP)
        if not ocr_available():
            self.video_ocr_check.setEnabled(False)
            self.video_ocr_check.setToolTip(S.VIDEO_OCR_UNAVAILABLE)
            self.video_ocr_terms_check.setEnabled(False)
            self.video_ocr_terms_check.setToolTip(S.VIDEO_OCR_UNAVAILABLE)
        form.addRow("", self.video_ocr_check)
        form.addRow("", self.video_ocr_terms_check)

        self.video_sheets_check = QCheckBox(S.VIDEO_SHEETS_LABEL)
        self.video_sheets_check.setToolTip(S.VIDEO_SHEETS_TIP)
        form.addRow("", self.video_sheets_check)

        self.video_sheet_cols_spin = QSpinBox()
        self.video_sheet_cols_spin.setRange(1, 3)
        self.video_sheet_cols_spin.setToolTip(S.VIDEO_SHEET_GRID_TIP)
        form.addRow(S.VIDEO_SHEET_COLS_LABEL, self.video_sheet_cols_spin)

        self.video_sheet_rows_spin = QSpinBox()
        self.video_sheet_rows_spin.setRange(1, 3)
        self.video_sheet_rows_spin.setToolTip(S.VIDEO_SHEET_GRID_TIP)
        form.addRow(S.VIDEO_SHEET_ROWS_LABEL, self.video_sheet_rows_spin)

        self.video_keep_singles_check = QCheckBox(S.VIDEO_KEEP_SINGLES_LABEL)
        self.video_keep_singles_check.setToolTip(S.VIDEO_KEEP_SINGLES_TIP)
        form.addRow("", self.video_keep_singles_check)

        layout.addWidget(self.advanced_box)
        layout.addStretch(1)

        self._connect()

    def _connect(self) -> None:
        self.advanced_toggle.toggled.connect(self._on_advanced_toggled)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        self.preset_new.clicked.connect(self._on_preset_new)
        self.preset_save.clicked.connect(self._on_preset_save)
        self.preset_rename.clicked.connect(self._on_preset_rename)
        self.preset_delete.clicked.connect(self._on_preset_delete)
        self.topic_edit.textChanged.connect(self._emit_prompt_changed)
        self.glossary_edit.textChanged.connect(self._emit_prompt_changed)
        # FIX_GUIDE_14 G-02: 사용자가 용어 칸을 직접 고치면, 지워진 자동 추가분만
        # 추적에서 뺀다(그대로 남은 자동 추가분은 계속 자동 추가분으로 취급).
        self.glossary_edit.textChanged.connect(self._on_glossary_edited_by_user)
        self.model_combo.currentTextChanged.connect(self._emit_prompt_changed)
        self.model_combo.currentTextChanged.connect(self._emit_model_changed)
        self.language_combo.currentIndexChanged.connect(self._emit_prompt_changed)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)

    # --- 상태 반영 ---

    def _load_settings(self) -> None:
        self._loading = True
        settings = self._settings
        self.preset_combo.clear()
        for name in settings.presets:
            self.preset_combo.addItem(name)
        index = self.preset_combo.findText(settings.active_preset)
        self.preset_combo.setCurrentIndex(max(0, index))

        preset = settings.current_preset()
        self.topic_edit.setPlainText(preset.topic)
        self.glossary_edit.setText(", ".join(preset.glossary))
        self._sync_auto_terms_for_preset()

        self.language_combo.setCurrentIndex(
            max(0, self.language_combo.findData(settings.language))
        )
        model_index = self.model_combo.findText(settings.model)
        if model_index < 0:
            self.model_combo.addItem(settings.model)
            model_index = self.model_combo.count() - 1
        self.model_combo.setCurrentIndex(model_index)

        self.backend_combo.setCurrentIndex(
            max(0, self.backend_combo.findData(settings.backend))
        )
        for fmt, check in self.format_checks.items():
            check.setChecked(fmt in settings.output.formats)
        self.timestamps_check.setChecked(settings.output.timestamps)
        self.conflict_combo.setCurrentIndex(
            max(0, self.conflict_combo.findData(settings.output.on_conflict))
        )
        self.initial_prompt_check.setChecked(settings.prompt.use_initial_prompt)
        self.hotwords_check.setChecked(settings.prompt.use_hotwords)
        # FIX_GUIDE_4.md A-02: mlx는 §5-2 게이트 통과로 기본값이 다른(꺼짐)
        # 별도 필드를 쓴다. 체크박스 하나가 현재 선택된 백엔드의 값을 보여준다.
        self.condition_check.setChecked(
            settings.prompt.condition_on_previous_text_mlx
            if settings.backend == "mlx"
            else settings.prompt.condition_on_previous_text
        )
        self.carry_window_check.setChecked(settings.prompt.carry_window_prompt)
        self.vad_check.setChecked(settings.decoding.vad_filter)
        self.beam_spin.setValue(settings.decoding.beam_size)
        self.fuzzy_check.setChecked(
            settings.postprocess.fuzzy_correction and fuzzy_available()
        )
        self.foreign_script_check.setChecked(
            settings.postprocess.foreign_script_detection
        )
        correction = settings.correction
        self.correction_check.setChecked(correction.enabled and ollama_available())
        model_index = self.correction_model_combo.findData(correction.model)
        if model_index < 0:
            self.correction_model_combo.addItem(correction.model, correction.model)
            model_index = self.correction_model_combo.count() - 1
        self.correction_model_combo.setCurrentIndex(model_index)
        confidence_index = self.correction_confidence_combo.findData(
            correction.min_confidence
        )
        self.correction_confidence_combo.setCurrentIndex(max(0, confidence_index))
        self.correction_annotate_check.setChecked(correction.annotate_transcript)
        self.correction_ocr_terms_check.setChecked(
            correction.use_ocr_terms and ocr_available()
        )
        video = settings.video
        self.video_capture_check.setChecked(video.capture_frames)
        self.video_threshold_spin.setValue(video.change_threshold_pct)
        self.video_dedupe_spin.setValue(video.dedupe_threshold_pct)
        self.video_interval_spin.setValue(video.min_interval_sec)
        self.video_ocr_check.setChecked(video.ocr_enabled and ocr_available())
        self.video_ocr_terms_check.setChecked(video.ocr_terms_to_prompt and ocr_available())
        self.video_sheets_check.setChecked(video.sheets_enabled)
        self.video_sheet_cols_spin.setValue(video.sheet_cols)
        self.video_sheet_rows_spin.setValue(video.sheet_rows)
        self.video_keep_singles_check.setChecked(video.keep_single_frames)
        self._loading = False
        self._emit_prompt_changed()

    def _on_advanced_toggled(self, checked: bool) -> None:
        self.advanced_box.setVisible(checked)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow
        )
        # 펼치면 내용이 길어져 창이 작으면 잘린다. 창 쪽에서 크기를 키우게 알린다.
        self.adjustSize()
        self.advanced_toggled.emit(checked)

    def _emit_prompt_changed(self) -> None:
        if not self._loading:
            self.prompt_changed.emit()

    def _emit_model_changed(self, model: str) -> None:
        if not self._loading:
            self.model_changed.emit(model)

    def current_model(self) -> str:
        return self.model_combo.currentText()

    def _on_backend_changed(self) -> None:
        if not self._loading:
            self.backend_changed.emit()
            self.prompt_changed.emit()

    # --- 프리셋 ---

    def _on_preset_selected(self) -> None:
        if self._loading:
            return
        name = self.preset_combo.currentText()
        if not name:
            return
        self._settings.active_preset = name
        preset = self._settings.presets.get(name, Preset())
        self._loading = True
        self.topic_edit.setPlainText(preset.topic)
        self.glossary_edit.setText(", ".join(preset.glossary))
        self._loading = False
        self._sync_auto_terms_for_preset()
        self._emit_prompt_changed()

    def _on_preset_new(self) -> None:
        """빈 프리셋을 새로 만들고 바로 선택한다."""
        entered, ok = QInputDialog.getText(
            self, S.PRESET_NEW_TITLE, S.PRESET_NEW_PROMPT
        )
        name = entered.strip()
        if not ok or not name:
            return
        if name in self._settings.presets:
            QMessageBox.information(
                self, S.PRESET_NEW_TITLE, S.PRESET_DUPLICATE.format(name=name)
            )
            index = self.preset_combo.findText(name)
            if index >= 0:
                self.preset_combo.setCurrentIndex(index)
            return
        self._settings.presets[name] = Preset()
        self._settings.active_preset = name
        self._loading = True
        self.preset_combo.addItem(name)
        self.preset_combo.setCurrentIndex(self.preset_combo.count() - 1)
        self.topic_edit.clear()
        self.glossary_edit.clear()
        self._loading = False
        self._auto_glossary_terms = set()
        self.topic_edit.setFocus()
        self._emit_prompt_changed()

    def _on_preset_save(self) -> None:
        """현재 입력을 활성 프리셋에 저장한다(이름이 없으면 새로 만든다)."""
        name = self.preset_combo.currentText().strip()
        if not name:
            entered, ok = QInputDialog.getText(self, S.PRESET_SAVE, S.PRESET_NEW_NAME)
            if not ok or not entered.strip():
                return
            name = entered.strip()
            self.preset_combo.addItem(name)
            self.preset_combo.setCurrentText(name)
        existing = self._settings.presets.get(name, Preset())
        self._settings.presets[name] = Preset(
            topic=self.topic_edit.toPlainText().strip(),
            glossary=parse_glossary(self.glossary_edit.text()),
            corrections=dict(existing.corrections),
        )
        self._settings.active_preset = name

    def _on_preset_rename(self) -> None:
        old = self.preset_combo.currentText()
        if not old:
            return
        entered, ok = QInputDialog.getText(
            self, S.PRESET_RENAME_TITLE, S.PRESET_NEW_NAME, text=old
        )
        new = entered.strip()
        if not ok or not new or new == old:
            return
        self._settings.presets[new] = self._settings.presets.pop(old, Preset())
        self._settings.active_preset = new
        # FIX_GUIDE_7.md E-01: 통계도 같은 이름을 키로 쓰므로 같이 옮긴다 — 안 옮기면
        # 다음부터 새 이름으로 통계가 없는 것처럼 처음부터 다시 쌓인다.
        if old in self._glossary_stats:
            self._glossary_stats[new] = self._glossary_stats.pop(old)
        self._loading = True
        index = self.preset_combo.currentIndex()
        self.preset_combo.setItemText(index, new)
        self._loading = False

    def _on_preset_delete(self) -> None:
        name = self.preset_combo.currentText()
        if len(self._settings.presets) <= 1:
            QMessageBox.information(self, S.PRESET_DELETE, S.PRESET_LAST_ONE)
            return
        answer = QMessageBox.question(
            self, S.PRESET_DELETE, S.PRESET_DELETE_CONFIRM.format(name=name)
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._settings.presets.pop(name, None)
        self._glossary_stats.pop(name, None)
        self._loading = True
        self.preset_combo.removeItem(self.preset_combo.currentIndex())
        self._loading = False
        self._on_preset_selected()

    # --- 외부 반영 ---

    def set_token_usage(self, usage: TokenUsage | None, message: str = "") -> None:
        """토큰 사용량 표시. 초과 시 빨간색 + 잘릴 항목 안내(§8)."""
        if usage is None:
            self.token_label.setText(message)
            self.token_label.setStyleSheet("")
            return
        if usage.dropped_terms:
            self.token_label.setText(
                S.TOKEN_OVER.format(
                    used=usage.used,
                    budget=usage.budget,
                    count=len(usage.dropped_terms),
                    terms=", ".join(usage.dropped_terms),
                )
            )
            self.token_label.setStyleSheet("color: #d13438;")
        else:
            self.token_label.setText(
                S.TOKEN_USAGE.format(used=usage.used, budget=usage.budget)
            )
            self.token_label.setStyleSheet("")

    def apply_capabilities(self, caps: BackendCapabilities) -> None:
        """백엔드가 지원하지 않는 옵션을 비활성화한다(§F-03-3)."""
        self.hotwords_check.setEnabled(caps.hotwords)
        self.hotwords_check.setToolTip(
            "" if caps.hotwords else S.USE_HOTWORDS_UNSUPPORTED
        )
        self.vad_check.setEnabled(caps.vad_filter)
        self.vad_check.setToolTip("" if caps.vad_filter else S.VAD_UNSUPPORTED)
        # FIX_GUIDE_6.md C-05: 백엔드가 무시하는 항목은 툴팁만이 아니라 인라인 문구로도 보여준다.
        self.vad_note.setText(S.VAD_BACKEND_NOTE)
        self.vad_note.setVisible(not caps.vad_filter)
        self.beam_spin.setEnabled(caps.beam_search)
        self.beam_spin.setToolTip("" if caps.beam_search else S.BEAM_UNSUPPORTED)
        self.beam_note.setText(S.BEAM_BACKEND_NOTE)
        self.beam_note.setVisible(not caps.beam_search)
        self.condition_check.setEnabled(caps.condition_on_previous_text)
        self.carry_window_check.setEnabled(caps.windowed_prompt_carry)
        self.carry_window_check.setToolTip(
            S.CARRY_WINDOW_PROMPT_TIP
            if caps.windowed_prompt_carry
            else S.CARRY_WINDOW_PROMPT_UNSUPPORTED
        )

    def _populate_correction_models(self) -> None:
        """교정 모델 드롭다운을 채운다.

        Ollama 데몬이 켜져 있으면 실제로 `ollama pull`된 gemma 계열 전부를
        보여준다(사용자가 e4b/e2b 말고 다른 버전을 받아 뒀을 수 있다). 데몬이
        꺼져 있거나 Ollama가 없으면 문서화된 두 모델(`CORRECTION_MODELS`)을
        고정 목록으로 보여준다 — 화면이 비는 것보다 낫다.
        """
        previous = self.correction_model_combo.currentData()
        installed = list_installed_gemma_models()
        names = installed or list(CORRECTION_MODELS)
        self.correction_model_combo.blockSignals(True)
        self.correction_model_combo.clear()
        for name in names:
            self.correction_model_combo.addItem(name, name)
        if previous is not None:
            index = self.correction_model_combo.findData(previous)
            if index < 0:
                self.correction_model_combo.addItem(str(previous), previous)
                index = self.correction_model_combo.count() - 1
            self.correction_model_combo.setCurrentIndex(index)
        self.correction_model_combo.blockSignals(False)

    def _refresh_correction_models(self) -> None:
        """"새로고침" 버튼 — Ollama를 나중에 켰거나 모델을 새로 받았을 때 다시 훑는다."""
        self._populate_correction_models()

    def set_inputs_enabled(self, enabled: bool) -> None:
        """설정 입력 잠금.

        전사 중에도 잠그지 않는다. 작업은 큐에 넣는 시점의 설정 스냅샷을 들고 가므로
        프리셋·모델·용어를 바꿔도 이미 대기 중인 작업에는 영향이 없다.
        (이 메서드는 필요할 때만 쓰고, 기본적으로 호출하지 않는다.)
        """
        for widget in (
            self.preset_combo,
            self.preset_new,
            self.preset_save,
            self.preset_rename,
            self.preset_delete,
            self.topic_edit,
            self.glossary_edit,
            self.language_combo,
            self.model_combo,
            self.advanced_box,
        ):
            widget.setEnabled(enabled)

    # --- 값 수집 ---

    def current_topic(self) -> str:
        return self.topic_edit.toPlainText().strip()

    def current_glossary(self) -> list[str]:
        return parse_glossary(self.glossary_edit.text())

    def set_status_message(self, message: str) -> None:
        """일회성 안내 문구(자동 용어 추가 등)."""
        self.status_label.setText(message)
        self.status_label.setVisible(bool(message))

    # --- FIX_GUIDE_7.md E-01/E-02: 자동 추가 용어 빈도 관리 ---

    def _sync_auto_terms_for_preset(self) -> None:
        """활성 프리셋의 저장된 "자동 추가분" 목록을 현재 용어 칸과 맞춘다.

        칸에 없는 용어(사용자가 지웠거나 프리셋이 바뀐 것)는 추적 대상에서 뺀다 —
        화면에 없는 용어를 나중에 "삭제"할 일은 없다.
        """
        stat = self._glossary_stats.get(self._settings.active_preset)
        current = set(self.current_glossary())
        self._auto_glossary_terms = (stat.auto_added & current) if stat else set()

    def _on_glossary_edited_by_user(self) -> None:
        """사용자가 용어 칸을 직접 고치면, **없어진** 자동 추가분만 추적에서 뺀다.

        프로그램이 `_loading=True`로 감싸고 쓴 텍스트 변경(자동 추가·정리)은 걸러지고,
        사용자가 실제로 타이핑했을 때만 여기가 실행된다(기존 `_loading` 패턴 재사용).

        FIX_GUIDE_14 G-02: 예전에는(FIX_GUIDE_7.md E-01 §2-5) 편집 순간 남아 있는 자동
        추가분을 **전부** 사용자 용어로 승격했다 — 용어 칸 아무 데나 한 글자만 고쳐도
        관련 없는 자동 추가분까지 영구 고착돼, 그 뒤로는 정리(`prune_glossary_terms`)도
        만료(G-03)도 안 먹혔다. 지금은 편집 후에도 칸에 **그대로 남아 있는** 자동
        추가분은 계속 자동 추가분으로 취급하고, 사용자가 **직접 지운** 것만 추적에서
        뺀다. 새로 타이핑한 용어는 애초에 `_auto_glossary_terms`에 없으므로 자동으로
        사용자 용어 취급된다 — 별도 처리가 필요 없다.
        """
        if self._loading or not self._auto_glossary_terms:
            return
        current = set(self.current_glossary())
        remaining = self._auto_glossary_terms & current
        if remaining == self._auto_glossary_terms:
            return  # 자동 추가분은 하나도 안 지워짐 — 추적 상태 그대로 유지
        self._auto_glossary_terms = remaining
        stat = self._glossary_stats.get(self._settings.active_preset)
        if stat is not None:
            stat.auto_added = set(self._auto_glossary_terms)
            save_stats(self._glossary_stats, self._glossary_stats_path)

    def record_glossary_detections(self, detected: Sequence[tuple[str, int]]) -> list[str]:
        """전사에서 감지된 용어로 통계를 갱신하고, 새 용어를 점수 내림차순으로 반영한다.

        `detected`는 이미 용어 칸에 있는 것도 포함해서 넘겨도 된다 — 점수는 전부
        갱신하되, 실제로 칸에 추가하는 것은 새 용어뿐이다. 반환값은 새로 추가된
        용어(상태 메시지용).

        이 함수 자체는 용어 칸(화면)만 바꾸고 **설정 파일**(`settings.json`)에는
        쓰지 않는다. 다만 사용자가 "저장" 버튼을 눌러야만 반영되는 건 아니다 — 다음
        전사 시작이나 앱 종료 때 `save_settings(panel.build_settings())`가 이 칸의
        내용을 그대로 프리셋에 저장하므로, 자동 추가분은 사실상 바로 다음 저장
        시점에 영속된다(FIX_GUIDE_14 G-01 실측: 실제 설정 파일에 이런 경로로 들어간
        잡음 용어가 발견됨). 정리는 `_on_glossary_edited_by_user`(G-02)와 만료(G-03)로
        이뤄진다.
        """
        if not detected:
            return []
        name = self._settings.active_preset
        stat = self._glossary_stats.setdefault(name, PresetGlossaryStats())
        stat.scores = update_scores(stat.scores, detected)

        existing = self.current_glossary()
        lowered_existing = {t.lower() for t in existing}
        added = list(
            dict.fromkeys(
                word for word, _ in detected if word.lower() not in lowered_existing
            )
        )
        if not added:
            save_stats(self._glossary_stats, self._glossary_stats_path)
            return []

        self._auto_glossary_terms |= set(added)
        stat.auto_added = set(self._auto_glossary_terms)

        user_terms = [t for t in existing if t not in self._auto_glossary_terms]
        auto_terms = [t for t in existing if t in self._auto_glossary_terms] + added
        ordered = order_glossary(user_terms, auto_terms, stat.scores)

        self._loading = True
        self.glossary_edit.setText(", ".join(ordered))
        self._loading = False
        self._emit_prompt_changed()

        save_stats(self._glossary_stats, self._glossary_stats_path)
        return added

    def prune_glossary_terms(self, candidates: Sequence[str]) -> list[str]:
        """토큰 예산 초과로 잘린 용어 중 **자동 추가분만** 실제로 지운다.

        사용자가 직접 넣은 용어나 주제 문장은 이 교집합에 없으므로 절대 건드리지
        않는다(§2-5에서 승격된 용어도 `_auto_glossary_terms`에서 이미 빠져 있다).
        """
        to_remove = [t for t in candidates if t in self._auto_glossary_terms]
        if not to_remove:
            return []
        remove_set = set(to_remove)
        self._auto_glossary_terms -= remove_set
        remaining = [t for t in self.current_glossary() if t not in remove_set]

        self._loading = True
        self.glossary_edit.setText(", ".join(remaining))
        self._loading = False
        self._emit_prompt_changed()

        stat = self._glossary_stats.get(self._settings.active_preset)
        if stat is not None:
            stat.auto_added = set(self._auto_glossary_terms)
            save_stats(self._glossary_stats, self._glossary_stats_path)
        return to_remove

    def expire_stale_auto_terms(self) -> list[str]:
        """자동 추가분 중 점수가 오래 안 나와 낮아진 것을 용어 칸에서 뺀다.

        FIX_GUIDE_14 G-03: 예전에는 점수 감쇠(`update_scores`)가 통계 파일에서만
        항목을 지웠고, 용어 칸의 자동 추가분은 토큰 예산 초과(`prune_glossary_terms`)
        말고는 빠질 길이 없어 한 번 들어간 잡음이 다시 안 나와도 계속 남았다.
        `record_glossary_detections`가 점수를 갱신한 뒤 호출해야 한다. 사용자 용어는
        애초에 `_auto_glossary_terms`에 없으므로 절대 건드리지 않는다.
        """
        stat = self._glossary_stats.get(self._settings.active_preset)
        if stat is None or not self._auto_glossary_terms:
            return []
        expired = [
            t for t in self._auto_glossary_terms
            if stat.scores.get(t, 0.0) < GLOSSARY_EXPIRE_SCORE
        ]
        if not expired:
            return []
        expired_set = set(expired)
        self._auto_glossary_terms -= expired_set
        remaining = [t for t in self.current_glossary() if t not in expired_set]

        self._loading = True
        self.glossary_edit.setText(", ".join(remaining))
        self._loading = False
        self._emit_prompt_changed()

        stat.auto_added = set(self._auto_glossary_terms)
        save_stats(self._glossary_stats, self._glossary_stats_path)
        return expired

    def current_backend(self) -> str:
        value = self.backend_combo.currentData()
        return str(value) if value else "faster"

    def batched(self) -> bool:
        return self.batched_check.isChecked()

    def build_settings(self) -> Settings:
        """UI 상태를 Settings로 합친다(파일 저장은 호출부가 결정)."""
        settings = self._settings
        name = self.preset_combo.currentText().strip() or settings.active_preset
        existing = settings.presets.get(name, Preset())
        presets = dict(settings.presets)
        presets[name] = Preset(
            topic=self.current_topic(),
            glossary=self.current_glossary(),
            corrections=dict(existing.corrections),
        )
        formats: list[OutputFormat] = [
            fmt  # type: ignore[misc]
            for fmt in _FORMATS
            if self.format_checks[fmt].isChecked()
        ]
        conflict: ConflictPolicy = self.conflict_combo.currentData() or "suffix"
        language: LanguageCode = self.language_combo.currentData() or "ko"
        current_backend = self.current_backend()
        # FIX_GUIDE_4.md A-02: 체크박스 하나가 현재 백엔드의 필드만 쓴다.
        # 다른 백엔드의 저장된 값은 건드리지 않는다(백엔드를 오가며 토글해도
        # 서로 덮어쓰지 않게).
        condition_field = (
            "condition_on_previous_text_mlx"
            if current_backend == "mlx"
            else "condition_on_previous_text"
        )
        updated = replace(
            settings,
            language=language,
            model=self.model_combo.currentText(),
            backend=current_backend,  # type: ignore[arg-type]
            active_preset=name,
            presets=presets,
            prompt=replace(
                settings.prompt,
                use_initial_prompt=self.initial_prompt_check.isChecked(),
                use_hotwords=self.hotwords_check.isChecked(),
                carry_window_prompt=self.carry_window_check.isChecked(),
                **{condition_field: self.condition_check.isChecked()},
            ),
            decoding=replace(
                settings.decoding,
                vad_filter=self.vad_check.isChecked(),
                beam_size=self.beam_spin.value(),
            ),
            output=replace(
                settings.output,
                formats=formats or ["txt"],
                timestamps=self.timestamps_check.isChecked(),
                on_conflict=conflict,
            ),
            postprocess=replace(
                settings.postprocess,
                fuzzy_correction=self.fuzzy_check.isChecked(),
                foreign_script_detection=self.foreign_script_check.isChecked(),
            ),
            correction=replace(
                settings.correction,
                enabled=self.correction_check.isChecked(),
                model=str(self.correction_model_combo.currentData()),
                min_confidence=str(self.correction_confidence_combo.currentData()),
                annotate_transcript=self.correction_annotate_check.isChecked(),
                use_ocr_terms=(
                    self.correction_ocr_terms_check.isChecked()
                    if ocr_available()
                    else settings.correction.use_ocr_terms
                ),
            ),
            video=replace(
                settings.video,
                capture_frames=self.video_capture_check.isChecked(),
                change_threshold_pct=self.video_threshold_spin.value(),
                dedupe_threshold_pct=self.video_dedupe_spin.value(),
                min_interval_sec=self.video_interval_spin.value(),
                # OCR을 쓸 수 없어 체크박스가 잠긴 동안에는 저장된 값을 덮어쓰지 않는다.
                ocr_enabled=(
                    self.video_ocr_check.isChecked()
                    if ocr_available()
                    else settings.video.ocr_enabled
                ),
                ocr_terms_to_prompt=(
                    self.video_ocr_terms_check.isChecked()
                    if ocr_available()
                    else settings.video.ocr_terms_to_prompt
                ),
                sheets_enabled=self.video_sheets_check.isChecked(),
                sheet_cols=self.video_sheet_cols_spin.value(),
                sheet_rows=self.video_sheet_rows_spin.value(),
                keep_single_frames=self.video_keep_singles_check.isChecked(),
            ),
        )
        self._settings = updated
        return updated
