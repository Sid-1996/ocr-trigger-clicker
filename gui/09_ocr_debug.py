import logging
import threading
import time
import unicodedata
from dataclasses import dataclass, field, replace
from difflib import SequenceMatcher
from enum import Enum

import numpy as np
from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from _loader import load_sibling
from i18n import T

_screenshot = load_sibling("screenshot", "core/01_screenshot.py")
_ocr = load_sibling("ocr_engine", "core/02_ocr_engine.py")
_bg_input = load_sibling("bg_input", "core/16_bg_input.py")
_hybrid = load_sibling("hybrid_input", "core/19_hybrid_input.py")
_pynput_input = load_sibling("pynput_input", "core/03_pynput_input.py")
_capture_pipeline = load_sibling("capture_pipeline", "core/17_capture_pipeline.py")
capture_frame = _capture_pipeline.capture_frame
_pw_mod = load_sibling("print_window", "core/15_print_window.py")
is_black_capture = _pw_mod.is_black_capture
is_admin = _pw_mod.is_admin

_rule_mod = load_sibling("rule_engine", "core/04_rule_engine.py")
_get_interaction_mode = _rule_mod.get_config_interaction_mode

activate_window = _screenshot.activate_window
capture_window_content = getattr(_screenshot, "capture_window_content", lambda title: None)
recognize = _ocr.recognize
recognize_detailed = _ocr.recognize_detailed
OcrCallOutcome = _ocr.OcrCallOutcome
OcrResult = _ocr.OcrResult


def _find_text_after_click(block_results: list, target: str) -> bool:
    """True if the same target text is still detected (case-insensitive, fuzzy)."""
    try:
        return bool(_ocr.find_text(block_results, target, "fuzzy", 0.8))
    except Exception:
        return False


_KEY_TEST_DEFAULT = "space"  # 16_bg_input / 03_pynput_input 兩邊都相容的按鍵名
_ERR_MODE_SWITCHED = "mode changed to pynput"  # key verify 的假失敗（非注入問題）
_ERR_RUN_ACTIVE = "main loop running"  # 主循環執行中 → 驗證 worker 自我中止（非注入問題）
_KEY_TEST_OPTIONS = (
    "space",
    "enter",
    "escape",
    "tab",
    "1",
    "2",
    "3",
    "up",
    "down",
    "f5",
)
_KEY_TEST_WAIT_SEC = 0.6
_KEY_PIXEL_TOLERANCE = 12
_KEY_SIMILAR_THRESHOLD = 0.90
_VISUAL_PADDING_RATIO = 0.25
_VISUAL_PIXEL_TOLERANCE = 12


class BackendStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NOT_EXECUTED = "not_executed"


class ObservationStatus(str, Enum):
    NOT_RUN = "not_run"
    CHANGED = "changed"
    NO_CHANGE = "no_change"
    TEXT_PRESENT = "text_present"
    TEXT_MISSING = "text_missing"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class _OcrTarget:
    text: str
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class VisualAnalysis:
    status: ObservationStatus = ObservationStatus.NOT_RUN
    scope: str = ""
    roi: tuple[int, int, int, int] | None = None
    diff_pixels: int = 0
    diff_ratio: float = 0.0
    tolerance: int = _VISUAL_PIXEL_TOLERANCE
    before: np.ndarray | None = None
    after: np.ndarray | None = None
    heatmap: np.ndarray | None = None
    reason: str = ""


@dataclass(frozen=True)
class TextDiffAnalysis:
    status: ObservationStatus = ObservationStatus.NOT_RUN
    scope: str = ""
    added: tuple[str, ...] = ()
    disappeared: tuple[str, ...] = ()
    changed: tuple[tuple[str, str], ...] = ()
    moved: tuple[str, ...] = ()
    before_ocr_status: str = ""
    after_ocr_status: str = ""
    reason: str = ""
    before_results: tuple[OcrResult, ...] = ()
    after_results: tuple[OcrResult, ...] = ()


@dataclass(frozen=True)
class BackendTestRequest:
    generation: int
    kind: str
    mode: str
    window_title: str
    hwnd: int
    key: str = ""
    target: _OcrTarget | None = None
    capture_source_gdi: bool = False
    window_rect: tuple[int, int, int, int] | None = None
    frame_size: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class BackendTestResult:
    test_id: int
    kind: str
    mode: str
    hwnd: int
    key: str
    coordinates: tuple[int, int] | None
    backend_status: BackendStatus
    elapsed_ms: float
    error: str = ""
    cancelled: bool = False
    visual_status: ObservationStatus = ObservationStatus.NOT_RUN
    ocr_status: ObservationStatus = ObservationStatus.NOT_RUN
    observation: str = ""
    visual: VisualAnalysis = field(default_factory=VisualAnalysis)
    text_diff: TextDiffAnalysis = field(default_factory=TextDiffAnalysis)


def _text_unavailable(
    reason: str, *, scope: str = "", before_status: str = "", after_status: str = ""
) -> TextDiffAnalysis:
    return TextDiffAnalysis(
        status=ObservationStatus.UNAVAILABLE,
        scope=scope,
        before_ocr_status=before_status,
        after_ocr_status=after_status,
        reason=reason,
    )


def _normalize_ocr_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def _text_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _center_distance(a, b) -> float:
    ax, ay = a.x + a.w / 2, a.y + a.h / 2
    bx, by = b.x + b.w / 2, b.y + b.h / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def _box_iou(a, b) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter <= 0:
        return 0.0
    union = a.w * a.h + b.w * b.h - inter
    return inter / union if union > 0 else 0.0


def _compare_ocr_texts(
    before: list[OcrResult] | tuple[OcrResult, ...],
    after: list[OcrResult] | tuple[OcrResult, ...],
    *,
    scope: str,
    roi: tuple[int, int, int, int] | None = None,
) -> TextDiffAnalysis:
    before_items = list(before)
    after_items = list(after)
    roi_w = roi[2] if roi else 0
    roi_h = roi[3] if roi else 0
    base = max(
        min(roi_w, roi_h),
        max(before_items[0].w if before_items else 0, after_items[0].w if after_items else 0, 1),
    )
    move_tol = max(12.0, base * 0.35)
    candidates: list[tuple[float, int, int, int, float, float]] = []
    for bi, bitem in enumerate(before_items):
        btext = _normalize_ocr_text(bitem.text)
        for ai, aitem in enumerate(after_items):
            atext = _normalize_ocr_text(aitem.text)
            sim = _text_similarity(btext, atext)
            iou = _box_iou(bitem, aitem)
            dist = _center_distance(bitem, aitem)
            if sim < 0.3 and dist > move_tol and iou <= 0:
                continue
            conf = 0.02 * ((bitem.confidence or 0.0) + (aitem.confidence or 0.0)) / 2
            score = 0.8 * sim + 0.2 * iou + conf
            candidates.append((score, bi, ai, sim, iou, dist))
    candidates.sort(reverse=True)
    used_b: set[int] = set()
    used_a: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for _, bi, ai, _, _, _ in candidates:
        if bi not in used_b and ai not in used_a:
            used_b.add(bi)
            used_a.add(ai)
            pairs.append((bi, ai))

    unchanged = 0
    changed_pairs: list[tuple[str, str]] = []
    moved: list[str] = []
    for bi, ai in pairs:
        bitem, aitem = before_items[bi], after_items[ai]
        btext, atext = _normalize_ocr_text(bitem.text), _normalize_ocr_text(aitem.text)
        sim = _text_similarity(btext, atext)
        dist = _center_distance(bitem, aitem)
        if btext == atext and dist <= move_tol:
            unchanged += 1
        elif btext == atext:
            moved.append(bitem.text)
        elif sim >= 0.8:
            if dist <= move_tol:
                changed_pairs.append((bitem.text, aitem.text))
            else:
                moved.append(bitem.text)
        else:
            changed_pairs.append((bitem.text, aitem.text))

    disappeared = tuple(b.text for i, b in enumerate(before_items) if i not in used_b)
    added = tuple(a.text for i, a in enumerate(after_items) if i not in used_a)
    if added or disappeared or changed_pairs or moved:
        status = ObservationStatus.CHANGED
    else:
        status = ObservationStatus.NO_CHANGE
    return TextDiffAnalysis(
        status=status,
        scope=scope,
        added=added,
        disappeared=disappeared,
        changed=tuple(changed_pairs),
        moved=tuple(moved),
        before_ocr_status="ok",
        after_ocr_status="ok",
        before_results=tuple(before_items),
        after_results=tuple(after_items),
    )


def _visual_unavailable(reason: str, *, scope: str = "") -> VisualAnalysis:
    return VisualAnalysis(status=ObservationStatus.UNAVAILABLE, scope=scope, reason=reason)


def _roi_bounds(
    target: _OcrTarget | None,
    shape: tuple[int, ...],
    *,
    pad_ratio: float = _VISUAL_PADDING_RATIO,
    fallback_full: bool = False,
) -> tuple[int, int, int, int] | None:
    """Return a clamped (x, y, w, h) ROI inside the frame, or None if empty."""
    if len(shape) < 2:
        return None
    h, w = int(shape[0]), int(shape[1])
    if h < 1 or w < 1:
        return None
    if target is None:
        return (0, 0, w, h) if fallback_full else None
    pad = max(4, int(max(target.w, target.h) * pad_ratio))
    x0 = max(0, int(target.x) - pad)
    y0 = max(0, int(target.y) - pad)
    x1 = min(w, int(target.x) + int(target.w) + pad)
    y1 = min(h, int(target.y) + int(target.h) + pad)
    if x1 <= x0 or y1 <= y0:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def _select_visual_roi(
    request: BackendTestRequest, shape: tuple[int, ...]
) -> tuple[tuple[int, int, int, int] | None, str]:
    if request.target is not None:
        return _roi_bounds(request.target, shape), "roi"
    if request.kind == "key":
        return _roi_bounds(None, shape, fallback_full=True), "frame"
    return None, "roi"


def _compare_visual(
    before: np.ndarray | None,
    after: np.ndarray | None,
    roi: tuple[int, int, int, int] | None,
    *,
    scope: str,
    tolerance: int = _VISUAL_PIXEL_TOLERANCE,
) -> VisualAnalysis:
    """Compare two BGR frames on a clamped ROI using only NumPy."""
    if before is None or after is None:
        return _visual_unavailable("capture_unavailable", scope=scope)
    if before.shape != after.shape:
        return _visual_unavailable("frame_size_changed", scope=scope)
    if roi is None:
        return _visual_unavailable("roi_unavailable", scope=scope)
    x, y, w, h = roi
    if w < 1 or h < 1:
        return _visual_unavailable("roi_unavailable", scope=scope)
    bh, bw = int(before.shape[0]), int(before.shape[1])
    if x < 0 or y < 0 or x + w > bw or y + h > bh:
        return _visual_unavailable("roi_out_of_bounds", scope=scope)
    a = before[y : y + h, x : x + w]
    b = after[y : y + h, x : x + w]
    if a.size == 0 or b.size == 0:
        return _visual_unavailable("roi_unavailable", scope=scope)
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    changed = (diff > tolerance).any(axis=2) if diff.ndim == 3 else diff > tolerance
    diff_pixels = int(changed.sum())
    total = int(changed.size)
    ratio = diff_pixels / total if total else 0.0
    heatmap = np.zeros(changed.shape, dtype=np.uint8)
    heatmap[changed] = 255
    return VisualAnalysis(
        status=ObservationStatus.CHANGED if diff_pixels else ObservationStatus.NO_CHANGE,
        scope=scope,
        roi=roi,
        diff_pixels=diff_pixels,
        diff_ratio=ratio,
        tolerance=tolerance,
        before=a.copy(),
        after=b.copy(),
        heatmap=heatmap,
    )


def _error_for_backend_failure(previous: str, current: str) -> str:
    """Only use last_error when this call can be distinguished from its prior value."""
    return current if current and current != previous else ""


# ── Verify 狀態 → i18n key 對照 ────────────────────────────────────────────
# 狀態名不等於 i18n key（key_test 的成功文案是 ok 不是 success），而且長文與
# 短文分屬不同命名空間，所以對應關係集中在這裡，避免程式端直接拼 key 拼錯
# 而讓使用者看到原始 key 字串。
# 欄位：state → (色碼, 長文命名空間, 長文 key, 短文命名空間, 短文 key)
_KEY_VERIFY_STATES = {
    "success": ("#1e8e3e", "key_test", "ok", "key_test", "ok"),
    "no_change": ("#b45309", "key_test", "no_change", "key_test", "no_change"),
    "fail": ("#c62828", "click_verify", "inject_fail", "click_verify", "inject_fail"),
    "black": ("#b45309", "key_test", "black", "click_verify", "black"),
    "window_changed": (
        "#666",
        "key_test",
        "window_changed",
        "click_verify",
        "window_changed",
    ),
}

# Click Verify：state → (色碼, i18n key 後綴)，長文與短文共用同一個後綴。
_CLICK_VERIFY_STATES = {
    "success": ("#1e8e3e", "success"),
    "no_response": ("#b45309", "no_response"),
    "inject_fail": ("#c62828", "inject_fail"),
    "black": ("#b45309", "black"),
    "window_changed": ("#666", "window_changed"),
    "skipped": ("#666", "skipped"),
}


def _frame_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """回傳 0~1 的相似度：像素差 > 12 的像素比例反算。"""
    if a.shape != b.shape:
        return 0.0
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    changed = (diff > _KEY_PIXEL_TOLERANCE).any(axis=2)
    return float(1.0 - changed.mean())


class _ClickBanner(QLabel):
    """單行結論列：點擊開啟完整結果對話框。"""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(T("ocr_debug.verify.detail_hint"))
        self.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _ImageLabel(QLabel):
    clicked = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setScaledContents(False)
        self.setStyleSheet("background-color: #1e1e1e; color: #888; font-size: 14px;")
        self.setMinimumSize(400, 300)

    def mousePressEvent(self, event):
        self.clicked.emit(int(event.position().x()), int(event.position().y()))
        super().mousePressEvent(event)


class _OcrSignals(QObject):
    ocr_done = pyqtSignal(list, float, int)
    ocr_failed = pyqtSignal(str, int)  # (錯誤訊息, request_id)
    ocr_status = pyqtSignal(str, int)  # (訊息, request_id)
    click_verify_done = pyqtSignal(dict)
    key_verify_done = pyqtSignal(dict)
    backend_test_done = pyqtSignal(object)


class OcrDebugPanel(QWidget):
    rule_requested = pyqtSignal(dict)
    step_requested = pyqtSignal(dict)
    template_requested = pyqtSignal(dict)
    template_step_requested = pyqtSignal(dict)
    # 後台測試失敗（注入失敗／遊戲無反應／截圖全黑）→ 請求主視窗開「診斷＋行動」對話框
    bg_inject_fail = pyqtSignal()

    _OCR_MODES = {
        "full_test": {"preprocess": False, "max_side_len": 0, "min_confidence": 0.25},
    }

    def __init__(self, window_title: str, parent=None):
        super().__init__(parent)
        self._window_title = window_title
        self._ocr_results: list = []
        self._latest_raw: np.ndarray | None = None
        self._annotated_pixmap: QPixmap | None = None
        self._crop_pixmap: QPixmap | None = None
        self._capture_source = ""
        self._black_warn_text = ""
        self._selected_index = -1
        # 顯示偏好：是否在截圖上繪製 OCR 框/標籤。clear_results 不得重置此偏好。
        self._show_boxes = False
        # 三種背景任務各自的 generation id。
        # 遞增只代表「禁止舊結果回填」，不代表取消 Worker（Worker 仍會跑完）。
        self._ocr_request_id = 0
        self._click_verify_request_id = 0
        self._key_verify_request_id = 0
        self._test_cancel_events: dict[str, threading.Event] = {}
        self._diagnostic_result: BackendTestResult | None = None
        self._has_active_rule = False
        self._verif_in_progress = False
        self._key_verif_in_progress = False
        # 輸入測試按鈕（點擊／按鍵）的可用性由兩個條件決定：
        # 1) 面板自身狀態：_click_test_available / _key_test_available
        #    （有選取結果、驗證進行中…由面板自己維護）
        # 2) 主循環是否執行中：_run_active
        #    測試鈕會直接操作後台輸入（frida 模式），與執行中的主循環共用同一組
        #    後端狀態 → 循環執行期間一律停用，避免兩邊同時送輸入互相干擾。
        #    用 threading.Event：驗證 worker 在背景執行緒讀取這個狀態，
        #    Event 的讀寫是原子的，跨執行緒的閘語意明確。
        self._run_active = threading.Event()
        self._click_test_available = False
        self._key_test_available = True
        self._last_verify_guidance = ""
        self._last_verify_dev = ""
        self._signals = _OcrSignals()
        self._signals.ocr_done.connect(self._on_ocr_done)
        self._signals.ocr_failed.connect(self._on_ocr_failed)
        self._signals.ocr_status.connect(self._on_ocr_status)
        self._signals.click_verify_done.connect(self._on_click_verify_done)
        self._signals.key_verify_done.connect(self._on_key_verify_done)
        self._signals.backend_test_done.connect(self._on_backend_test_done)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._capture_btn = QPushButton(T("ocr_debug.capture"))
        self._capture_btn.setMinimumWidth(80)
        self._capture_btn.setToolTip(T("ocr_debug.capture.tooltip"))
        toolbar.addWidget(self._capture_btn)
        self._show_boxes_check = QCheckBox(T("ocr_debug.show_boxes"))
        self._show_boxes_check.setChecked(False)
        self._show_boxes_check.toggled.connect(self._on_show_boxes_toggled)
        toolbar.addWidget(self._show_boxes_check)
        self._click_test_btn = QPushButton(T("ocr_debug.click_test"))
        self._click_test_btn.setMinimumWidth(80)
        self._click_test_btn.setToolTip(T("ocr_debug.click_test.tooltip"))
        self._click_test_btn.clicked.connect(self._on_click_test)
        toolbar.addWidget(self._click_test_btn)
        self._key_test_combo = QComboBox()
        for name in _KEY_TEST_OPTIONS:
            self._key_test_combo.addItem(name.capitalize(), name)
        self._key_test_combo.setCurrentIndex(_KEY_TEST_OPTIONS.index(_KEY_TEST_DEFAULT))
        self._key_test_combo.setToolTip(T("ocr_debug.key_test.key_choose.tooltip"))
        toolbar.addWidget(self._key_test_combo)
        self._key_test_btn = QPushButton(T("ocr_debug.key_test"))
        self._key_test_btn.setMinimumWidth(80)
        self._key_test_btn.setToolTip(T("ocr_debug.key_test.tooltip"))
        self._key_test_btn.clicked.connect(self._on_key_test)
        toolbar.addWidget(self._key_test_btn)
        # 測試按鈕的初始可用性一律走 _sync_test_buttons（面板狀態 × 非循環執行中）
        self._sync_test_buttons()
        toolbar.addStretch()
        self._info_label = QLabel("")
        toolbar.addWidget(self._info_label)
        layout.addLayout(toolbar)

        self._click_error_label = _ClickBanner()
        self._click_error_label.setObjectName("clickErrorLabel")
        self._click_error_label.setStyleSheet("color: #c62828;")
        self._click_error_label.clicked.connect(self._open_click_detail)
        layout.addWidget(self._click_error_label)

        self._diagnostic_label = QLabel()
        self._diagnostic_label.setWordWrap(True)
        self._diagnostic_label.setStyleSheet(
            "QLabel { background:#f6f7f9; color:#222; border:1px solid #d9dde3; "
            "border-radius:6px; padding:6px; font-size:11px; }"
        )
        self._diagnostic_label.hide()
        layout.addWidget(self._diagnostic_label)

        self._diagnostic_detail_label = QLabel()
        self._diagnostic_detail_label.setWordWrap(True)
        self._diagnostic_detail_label.setStyleSheet(
            "QLabel { background:#f6f7f9; color:#555; border:1px solid #d9dde3; "
            "border-radius:6px; padding:6px; font-size:11px; }"
        )
        self._diagnostic_detail_label.hide()
        layout.addWidget(self._diagnostic_detail_label)

        self._diagnostic_detail_btn = QPushButton(T("ocr_debug.diagnostic.detail"))
        self._diagnostic_detail_btn.setCheckable(True)
        self._diagnostic_detail_btn.setChecked(False)
        self._diagnostic_detail_btn.toggled.connect(self._on_diagnostic_detail_toggled)
        self._diagnostic_detail_btn.hide()
        layout.addWidget(self._diagnostic_detail_btn)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._image_label = _ImageLabel()
        self._image_label.setText(T("ocr_debug.no_capture"))
        self._image_label.clicked.connect(self._on_image_clicked)
        self._image_label.installEventFilter(self)
        splitter.addWidget(self._image_label)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        self._summary_label = QLabel(T("ocr_debug.summary"))
        self._summary_label.setWordWrap(True)
        self._summary_label.setMinimumHeight(96)
        self._style_card(self._summary_label, dark=False)
        right_layout.addWidget(self._summary_label)

        self._result_table = QTableWidget()
        self._result_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._result_table.setFont(QFont("Consolas", 9))
        self._result_table.setColumnCount(3)
        self._result_table.setHorizontalHeaderLabels(
            [T("ocr_debug.col_index"), T("ocr_debug.col_text"), T("ocr_debug.col_confidence")]
        )
        self._result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._result_table.setColumnWidth(0, 40)
        self._result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._result_table.setColumnWidth(2, 70)
        self._result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._result_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._result_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        right_layout.addWidget(self._result_table)

        crop_title = QLabel(T("ocr_debug.crop_preview_title"))
        crop_title.setStyleSheet("font-weight: 600; color: #666;")
        right_layout.addWidget(crop_title)
        self._crop_title = crop_title

        self._crop_label = QLabel(T("ocr_debug.crop_hint"))
        self._crop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._crop_label.setMinimumHeight(150)
        self._crop_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._crop_label.setStyleSheet(
            "QLabel {"
            "  background: #111;"
            "  color: #a8a8a8;"
            "  border: 1px solid #2a2d33;"
            "  border-radius: 8px;"
            "  padding: 6px;"
            "}"
        )
        right_layout.addWidget(self._crop_label)

        self._selected_detail = QLabel(T("ocr_debug.selected_none"))
        self._selected_detail.setWordWrap(True)
        self._selected_detail.setMinimumHeight(110)
        self._style_card(self._selected_detail, dark=True)
        right_layout.addWidget(self._selected_detail)
        self._sync_selection_widgets()

        self._template_btn = QPushButton(T("ocr_debug.create_template_rule"))
        self._template_btn.setEnabled(False)
        self._template_btn.setToolTip(T("ocr_debug.create_template_rule.tooltip"))
        self._template_btn.clicked.connect(self._on_add_template)
        right_layout.addWidget(self._template_btn)

        self._add_template_step_btn = QPushButton(T("ocr_debug.add_template_step"))
        self._add_template_step_btn.setEnabled(False)
        self._add_template_step_btn.setToolTip(T("ocr_debug.add_template_step.tooltip"))
        self._add_template_step_btn.clicked.connect(self._on_add_template_step)
        right_layout.addWidget(self._add_template_step_btn)

        self._add_rule_btn = QPushButton(T("ocr_debug.create_text_rule"))
        self._add_rule_btn.setEnabled(False)
        self._add_rule_btn.setToolTip(T("ocr_debug.create_text_rule.tooltip"))
        self._add_rule_btn.clicked.connect(self._on_add_rule)
        right_layout.addWidget(self._add_rule_btn)

        self._set_sub_target_btn = QPushButton(T("ocr_debug.add_text_step"))
        self._set_sub_target_btn.setEnabled(False)
        self._set_sub_target_btn.setToolTip(T("ocr_debug.add_text_step.tooltip"))
        self._set_sub_target_btn.clicked.connect(self._on_set_sub_target)
        right_layout.addWidget(self._set_sub_target_btn)

        # keep a single list for enable/disable iteration
        self._add_buttons = [
            self._template_btn,
            self._add_template_step_btn,
            self._add_rule_btn,
            self._set_sub_target_btn,
        ]

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_scroll.setWidget(right_panel)

        splitter.addWidget(right_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([580, 408])
        layout.addWidget(splitter, 1)

        self._status_bar = QStatusBar(self)
        self._status_bar.showMessage(T("ocr_debug.ready"))
        layout.addWidget(self._status_bar)

        self._capture_btn.clicked.connect(self._take_snapshot)

    def _style_card(self, widget: QLabel, *, dark: bool = False):
        if dark:
            widget.setStyleSheet(
                "QLabel {"
                "  background: #101215;"
                "  color: #d8d8d8;"
                "  border: 1px solid #2a2d33;"
                "  border-radius: 8px;"
                "  padding: 8px;"
                "}"
            )
        else:
            widget.setStyleSheet(
                "QLabel {"
                "  background: #f6f7f9;"
                "  color: #222;"
                "  border: 1px solid #d9dde3;"
                "  border-radius: 8px;"
                "  padding: 8px;"
                "}"
            )

    def _ocr_options(self) -> dict:
        return self._OCR_MODES["full_test"]

    def _minimize_and_capture(self):
        mode = _get_interaction_mode()
        title = self._window_title
        hwnd = _screenshot.get_window_hwnd(title)

        if mode != "pynput":
            img = capture_frame(mode, title, hwnd=hwnd)
            if img is not None:
                logging.debug("ocr_dbg: bg mode=%s %dx%d", mode, img.shape[1], img.shape[0])
                return img[:, :, ::-1].copy(), T("ocr_debug.source_screen")
            return None, ""

        # 前景模式：縮小主視窗 → 啟動目標視窗 → mss 截圖（避免閃爍優先）
        try:
            parent = self.parent() if self.parent() else None
            self_was_maxed = self.isMaximized()
            parent_was_maxed = parent.isMaximized() if parent else False
            self.showMinimized()
            if parent:
                parent.showMinimized()
            QApplication.processEvents()
            time.sleep(0.08)

            activate_window(title)
            QApplication.processEvents()
            time.sleep(0.12)

            img = capture_frame(mode, title, hwnd=hwnd)
            source = T("ocr_debug.source_screen")
            if img is not None:
                logging.debug("ocr_dbg: fg mss %dx%d", img.shape[1], img.shape[0])
                img = img[:, :, ::-1].copy()

            if img is None:
                img = capture_window_content(title)
                source = T("ocr_debug.source_gdi")
                if img is not None:
                    wr = _screenshot.get_window_rect(title)
                    if wr:
                        chrome = _screenshot.get_window_client_offset(title) or (0, 0)
                        full_h, full_w = wr["h"], wr["w"]
                        if img.shape[0] != full_h or img.shape[1] != full_w:
                            padded = np.zeros((full_h, full_w, img.shape[2]), dtype=img.dtype)
                            cx, cy = chrome
                            padded[cy : cy + img.shape[0], cx : cx + img.shape[1]] = img
                            img = padded

            return img, source
        except Exception:
            return None, ""
        finally:
            parent = self.parent() if self.parent() else None
            if parent and parent.isMinimized():
                if parent_was_maxed:
                    parent.showMaximized()
                else:
                    parent.showNormal()
                parent.activateWindow()
            if self.isMinimized():
                if self_was_maxed:
                    self.showMaximized()
                else:
                    self.showNormal()

    def _take_snapshot(self):
        self._ocr_request_id += 1
        request_id = self._ocr_request_id
        self._capture_btn.setEnabled(False)
        self._capture_btn.setText(T("ocr_debug.recognizing"))
        self._info_label.setText("")
        self._click_error_label.hide()
        self._black_warn_text = ""
        self._selected_index = -1
        # 清掉上一次擷取的結果：舊視窗的 OCR 座標配上新視窗 rect 會點錯位置。
        self._ocr_results = []
        self._result_table.blockSignals(True)
        self._result_table.setRowCount(0)
        self._result_table.clearSelection()
        self._result_table.blockSignals(False)
        self._add_rule_btn.setEnabled(False)
        self._template_btn.setEnabled(False)
        self._click_test_available = False
        self._sync_test_buttons()
        self._update_step_btn_state()

        raw, src = self._minimize_and_capture()
        self._capture_source = src

        if raw is None:
            logging.warning("capture failed for '%s'", self._window_title)
            self._status_bar.showMessage(T("ocr_debug.capture_failed", title=self._window_title))
            self._restore_capture_btn()
            return

        # 後台截圖全黑 + 非系統管理員 → 暫存提示，待 OCR 完成後與耗時訊息合併顯示
        if _get_interaction_mode() != "pynput" and is_black_capture(raw) and not is_admin():
            self._black_warn_text = T("bg_capture.black_admin_warn")

        self._latest_raw = raw
        try:
            threading.Thread(
                target=self._do_ocr, args=(raw.copy(), request_id), daemon=True
            ).start()
        except Exception as e:
            # Worker 啟動失敗：必須自行復原按鈕，否則擷取按鈕會永久停用
            logging.exception("ocr worker start failed")
            self._restore_capture_btn()
            self._status_bar.showMessage(T("ocr_debug.ocr_failed", err=str(e) or type(e).__name__))

    def _do_ocr(self, img: np.ndarray, request_id: int):
        # Worker 執行緒：不得直接操作任何 QWidget，成功與失敗都經 signal 回 GUI thread。
        try:
            self._signals.ocr_status.emit(T("ocr_debug.ocr_loading"), request_id)
            t0 = time.monotonic()
            opts = self._ocr_options()
            results = recognize(img, **opts)
            elapsed = (time.monotonic() - t0) * 1000
            logging.debug("ocr_dbg: %.0fms %d blocks", elapsed, len(results))
            self._signals.ocr_done.emit(results, elapsed, request_id)
        except Exception as e:
            logging.exception("_do_ocr failed")
            self._signals.ocr_failed.emit(str(e) or type(e).__name__, request_id)

    def _on_ocr_status(self, msg: str, request_id: int):
        if request_id != self._ocr_request_id:
            return
        self._status_bar.showMessage(msg)

    def _on_ocr_failed(self, message: str, request_id: int):
        try:
            if request_id != self._ocr_request_id:
                return
            self._restore_capture_btn()
            # 只顯示簡短錯誤訊息；完整 traceback 留在日誌
            self._status_bar.showMessage(T("ocr_debug.ocr_failed", err=message))
        except Exception:
            logging.exception("_on_ocr_failed failed")

    def _restore_capture_btn(self):
        self._capture_btn.setText(T("ocr_debug.capture"))
        self._capture_btn.setEnabled(True)

    def _on_ocr_done(self, results: list, elapsed_ms: float, request_id: int):
        try:
            if request_id != self._ocr_request_id:
                return
            self._ocr_results = results
            self._restore_capture_btn()
            self._populate_table()
            self._rebuild_annotated()
            self._update_display()
            if self._latest_raw is None:
                return
            h, w = self._latest_raw.shape[:2]
            info_text = T("ocr_debug.info_label", ms=round(elapsed_ms), n=len(results))
            if self._black_warn_text:
                info_text = f"{info_text}  {self._black_warn_text}"
            self._info_label.setText(info_text)
            self._summary_label.setText(
                T(
                    "ocr_debug.summary_text",
                    title=self._window_title,
                    source=self._capture_source or T("ocr_debug.source_screen"),
                    w=w,
                    h=h,
                    n=len(results),
                    ms=round(elapsed_ms),
                )
            )
            self._status_bar.showMessage(
                T(
                    "ocr_debug.status_bar",
                    source=self._capture_source,
                    w=w,
                    h=h,
                    n=len(results),
                    ms=round(elapsed_ms),
                )
            )
        except Exception:
            logging.exception("_on_ocr_done failed")

    def _populate_table(self):
        self._result_table.blockSignals(True)
        self._result_table.setRowCount(len(self._ocr_results))
        for i, r in enumerate(self._ocr_results):
            self._result_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self._result_table.setItem(i, 1, QTableWidgetItem(r.text))
            item = QTableWidgetItem(f"{int(r.confidence * 100)}%")
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r.confidence >= 0.8:
                bg = QColor(220, 255, 220)
            elif r.confidence >= 0.5:
                bg = QColor(255, 250, 200)
            else:
                bg = QColor(255, 220, 220)
            item.setBackground(bg)
            item.setForeground(QColor(30, 30, 30))
            self._result_table.setItem(i, 2, item)
        self._result_table.blockSignals(False)

    def _on_table_selection_changed(self):
        try:
            rows = self._result_table.selectedIndexes()
            if rows:
                self._selected_index = rows[0].row()
                self._add_rule_btn.setEnabled(True)
                self._template_btn.setEnabled(True)
                # 驗證進行中不得提前解鎖，否則使用者可重複點擊測試
                if not self._verif_in_progress:
                    self._click_test_available = True
            else:
                self._selected_index = -1
                self._add_rule_btn.setEnabled(False)
                self._template_btn.setEnabled(False)
                self._click_test_available = False
            self._sync_test_buttons()
            self._update_step_btn_state()
            self._sync_selection_widgets()
            self._rebuild_annotated()
            self._update_display()
        except Exception:
            logging.exception("_on_table_selection_changed failed")

    def _on_show_boxes_toggled(self, checked: bool):
        self._show_boxes = bool(checked)
        self._rebuild_annotated()
        self._update_display()

    def _sync_selection_widgets(self):
        has_selection = 0 <= self._selected_index < len(self._ocr_results)
        self._crop_title.setVisible(has_selection)
        self._crop_label.setVisible(has_selection)
        self._selected_detail.setVisible(has_selection)

    def _on_image_clicked(self, label_x: int, label_y: int):
        if self._latest_raw is None or not self._ocr_results:
            return
        h, w = self._latest_raw.shape[:2]
        if h < 1 or w < 1:
            return
        pixmap = self._image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return

        scaled_w = pixmap.width()
        scaled_h = pixmap.height()
        offset_x = max(0, (self._image_label.width() - scaled_w) // 2)
        offset_y = max(0, (self._image_label.height() - scaled_h) // 2)

        img_x = label_x - offset_x
        img_y = label_y - offset_y
        if img_x < 0 or img_y < 0 or img_x >= scaled_w or img_y >= scaled_h:
            return

        orig_w = w
        orig_h = h
        orig_x = int(img_x / scaled_w * orig_w)
        orig_y = int(img_y / scaled_h * orig_h)

        for i, r in enumerate(self._ocr_results):
            if r.x <= orig_x <= r.x + r.w and r.y <= orig_y <= r.y + r.h:
                self._selected_index = i
                self._result_table.blockSignals(True)
                self._result_table.selectRow(i)
                self._result_table.blockSignals(False)
                self._add_rule_btn.setEnabled(True)
                self._template_btn.setEnabled(True)
                self._click_test_available = True
                self._sync_test_buttons()
                self._update_step_btn_state()
                self._sync_selection_widgets()
                try:
                    self._rebuild_annotated()
                    self._update_display()
                except Exception:
                    pass
                return

    def set_has_active_rule(self, active: bool):
        self._has_active_rule = active
        self._update_step_btn_state()

    def set_run_active(self, active: bool) -> None:
        """主循環執行期間停用輸入測試按鈕，並作廢在途的驗證工作。

        輸入測試會直接操作後台輸入（frida 模式），與執行中的主循環共用同一組
        後端狀態 → 循環執行期間必須停用，避免兩邊同時送輸入互相干擾。
        循環停止後依面板原本狀態還原（不覆蓋面板自己的啟用／停用邏輯）。

        「停用按鈕」只擋住新的測試；先前已啟動的驗證 worker 仍在背景執行緒，
        因此主循環啟動時必須另外作廢它們（見 _abort_running_verifications）。
        """
        active = bool(active)
        was_active = self._run_active.is_set()
        if active:
            for cancel_event in self._test_cancel_events.values():
                cancel_event.set()
            # 先關閘再作廢：worker 讀的是 _run_active，先 set 才能讓正在
            # 邊界上檢查的 worker 立刻看到「主循環執行中」。
            self._run_active.set()
            if not was_active:
                self._abort_running_verifications()
        else:
            self._run_active.clear()
        self._sync_test_buttons()

    def _abort_running_verifications(self) -> None:
        """作廢在途的 click／key 驗證工作（主循環啟動時呼叫）。

        以既有的 generation id 機制作廢：worker 回來的結果 request id 已過期
        → _on_click_verify_done／_on_key_verify_done 安全忽略，不覆蓋面板狀態。
        同時歸零 in-progress 旗標並還原按鈕文字／可用性，否則按鈕會永久卡在
        「驗證中」（與 clear_results 的既有做法一致）。

        已送出 DOWN 的部分不受影響：放開（UP）由後端層必定送出，不阻擋。
        """
        self._click_verify_request_id += 1
        self._key_verify_request_id += 1
        self._verif_in_progress = False
        self._key_verif_in_progress = False
        try:
            # 選取結果仍在 → 點擊測試維持可用；按鍵測試本來就可用。
            self._click_test_available = self._selected_index >= 0
            self._key_test_available = True
            self._click_test_btn.setText(T("ocr_debug.click_test"))
            self._key_test_btn.setText(T("ocr_debug.key_test"))
            self._sync_test_buttons()
        except RuntimeError:
            logging.debug("ocr debug panel closed: skip verify abort UI restore")

    def _verify_input_blocked(self) -> bool:
        """True 代表主循環執行中，驗證 worker 不得再送出輸入或繼續擷取。

        worker 在背景執行緒執行，主循環啟動後必須讓它停下來，避免與主循環
        重疊操作後台輸入（已送出的 DOWN 不受影響：UP 由後端層必定送出）。
        """
        return self._run_active.is_set()

    def _sync_test_buttons(self) -> None:
        """套用輸入測試按鈕的可用性：面板自身狀態 AND 非主循環執行中。

        面板自己的意圖（是否有選取結果、驗證是否進行中）決定「測試鈕本來該
        不該用」；主循環執行中則一律停用。視窗已關閉（C++ 物件已刪除）時
        安全忽略，不讓狀態更新拖垮 GUI。
        """
        run_active = self._run_active.is_set()
        try:
            self._click_test_btn.setEnabled(self._click_test_available and not run_active)
            self._key_test_btn.setEnabled(self._key_test_available and not run_active)
        except RuntimeError:
            logging.debug("ocr debug panel closed: skip test button state")

    def _update_step_btn_state(self):
        enabled = self._selected_index >= 0 and self._has_active_rule
        self._set_sub_target_btn.setEnabled(enabled)
        self._add_template_step_btn.setEnabled(enabled)

    def _compute_roi(self):
        if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
            return None
        r = self._ocr_results[self._selected_index]
        img_h, img_w = self._latest_raw.shape[:2] if self._latest_raw is not None else (0, 0)
        if img_w < 1 or img_h < 1:
            return None
        pad = 20
        px_x = max(0, r.x - pad)
        px_y = max(0, r.y - pad)
        px_w = min(img_w - px_x, r.w + pad * 2)
        px_h = min(img_h - px_y, r.h + pad * 2)

        client_rect = _screenshot.get_client_rect_for_image(self._window_title, img_w, img_h)
        is_gdi = self._capture_source == T("ocr_debug.source_gdi")
        if is_gdi or client_rect is None:
            roi = {
                "x": px_x / img_w,
                "y": px_y / img_h,
                "w": px_w / img_w,
                "h": px_h / img_h,
                "roi_coord": "client",
            }
        else:
            cx, cy, client_w, client_h = client_rect
            roi = {
                "x": max(0.0, (px_x - cx) / client_w) if client_w > 0 else 0.0,
                "y": max(0.0, (px_y - cy) / client_h) if client_h > 0 else 0.0,
                "w": min(1.0, px_w / client_w) if client_w > 0 else 0.0,
                "h": min(1.0, px_h / client_h) if client_h > 0 else 0.0,
                "roi_coord": "client",
            }
        return roi, px_x, px_y, px_w, px_h

    def _source_capture_size(self):
        """本次畫面（模板來源）的客戶區尺寸，與 _compute_roi 的座標基準一致。"""
        img_h, img_w = self._latest_raw.shape[:2] if self._latest_raw is not None else (0, 0)
        if img_w < 1 or img_h < 1:
            return None
        client_rect = _screenshot.get_client_rect_for_image(self._window_title, img_w, img_h)
        is_gdi = self._capture_source == T("ocr_debug.source_gdi")
        if is_gdi or client_rect is None:
            return [img_w, img_h]
        return [client_rect[2], client_rect[3]]

    def _on_add_rule(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, px_x, px_y, px_w, px_h = result
        r = self._ocr_results[self._selected_index]

        self.rule_requested.emit(
            {
                "target_text": r.text,
                "roi": roi,
                "fuzzy": True,
                "click_position": "text_center",
            }
        )

        self._status_bar.showMessage(
            T("ocr_debug.rule_created", text=r.text, x=px_x, y=px_y, w=px_w, h=px_h)
        )

    def _on_add_template(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, _px_x, _px_y, _px_w, _px_h = result
        r = self._ocr_results[self._selected_index]

        import cv2 as _cv2

        from _loader import load_sibling

        _tmpl = load_sibling("template_matching", "core/11_template_matching.py")

        img_h, img_w = self._latest_raw.shape[:2]
        t_x = max(0, r.x)
        t_y = max(0, r.y)
        t_w = min(img_w - t_x, r.w)
        t_h = min(img_h - t_y, r.h)
        if t_w < 1 or t_h < 1:
            return
        crop = self._latest_raw[t_y : t_y + t_h, t_x : t_x + t_w].copy()
        crop_bgr = _cv2.cvtColor(crop, _cv2.COLOR_RGB2BGR)
        template_b64 = _tmpl.img_to_b64(crop_bgr)

        logging.debug(
            "ocr_dbg: template rule src=%s px=(%d,%d) %dx%d roi=%s",
            self._capture_source,
            t_x,
            t_y,
            t_w,
            t_h,
            {k: round(v, 3) if isinstance(v, (int, float)) else v for k, v in roi.items()},
        )

        self.template_requested.emit(
            {
                "template_data": template_b64,
                "roi": roi,
                "name": r.text,
                "capture_size": self._source_capture_size(),
            }
        )

        self._status_bar.showMessage(
            T("ocr_debug.template_rule_created", text=r.text, tw=t_w, th=t_h, rw=_px_w, rh=_px_h)
        )

    def _on_set_sub_target(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, px_x, px_y, px_w, px_h = result
        r = self._ocr_results[self._selected_index]

        self.step_requested.emit(
            {
                "target_text": r.text,
                "roi": roi,
            }
        )

        self._status_bar.showMessage(
            T("ocr_debug.step_added", text=r.text, x=px_x, y=px_y, w=px_w, h=px_h)
        )

    def _on_add_template_step(self):
        result = self._compute_roi()
        if result is None:
            return
        roi, _px_x, _px_y, _px_w, _px_h = result
        r = self._ocr_results[self._selected_index]

        import cv2 as _cv2

        from _loader import load_sibling

        _tmpl = load_sibling("template_matching", "core/11_template_matching.py")

        img_h, img_w = self._latest_raw.shape[:2]
        t_x = max(0, r.x)
        t_y = max(0, r.y)
        t_w = min(img_w - t_x, r.w)
        t_h = min(img_h - t_y, r.h)
        if t_w < 1 or t_h < 1:
            return
        crop = self._latest_raw[t_y : t_y + t_h, t_x : t_x + t_w].copy()
        crop_bgr = _cv2.cvtColor(crop, _cv2.COLOR_RGB2BGR)
        template_b64 = _tmpl.img_to_b64(crop_bgr)

        self.template_step_requested.emit(
            {
                "template_data": template_b64,
                "roi": roi,
                "name": r.text,
                "capture_size": self._source_capture_size(),
            }
        )

        logging.debug(
            "ocr_dbg: template step src=%s px=(%d,%d) %dx%d roi=%s",
            self._capture_source,
            t_x,
            t_y,
            t_w,
            t_h,
            {k: round(v, 3) if isinstance(v, (int, float)) else v for k, v in roi.items()},
        )

        self._status_bar.showMessage(
            T("ocr_debug.template_step_added", text=r.text, tw=t_w, th=t_h)
        )

    def _click_verify_worker(
        self,
        r,
        sx: int,
        sy: int,
        frame_w: int,
        frame_h: int,
        request_id: int,
        request: BackendTestRequest | None = None,
        cancel: threading.Event | None = None,
        before: np.ndarray | None = None,
        visual_error: str = "",
        backend_ok: bool = True,
    ):
        def emit(
            state: str,
            still: str,
            ms: float,
            err: str = "",
            visual: VisualAnalysis | None = None,
            text_diff: TextDiffAnalysis | None = None,
        ):
            self._signals.click_verify_done.emit(
                {
                    "state": state,
                    "text": r.text,
                    "sx": sx,
                    "sy": sy,
                    "ms": ms,
                    "still": still,
                    "last_error": err,
                    "request_id": request_id,
                    "visual": visual or _visual_unavailable(visual_error or "capture_unavailable"),
                    "text_diff": text_diff
                    or _text_unavailable(visual_error or "capture_unavailable"),
                }
            )

        try:
            # 等 ~0.6s 過場，再重拍目標區塊確認點擊是否有實際反應
            time.sleep(0.6)
            # 主循環若已啟動 → 不得繼續驗證：主循環會改變畫面，繼續比對只會
            # 得出「沒有反應」的假結論。此時結果會因 generation id 作廢而被忽略。
            if self._verify_input_blocked() or (cancel is not None and cancel.is_set()):
                reason = "main_loop_running" if self._run_active.is_set() else "cancelled"
                emit("skipped", "?", 0.0, _ERR_RUN_ACTIVE, _visual_unavailable(reason))
                return
            mode = request.mode if request else _get_interaction_mode()
            title = request.window_title if request else self._window_title
            hwnd = request.hwnd if request else _screenshot.get_window_hwnd(title)
            t0 = time.monotonic()
            can_ocr = backend_ok and mode != "pynput" and bool(hwnd)
            if request is None and (mode == "pynput" or not hwnd):
                # 目標視窗消失或互動模式改變 → 必須回報完成，
                # 否則 in-progress 永遠卡住，點擊測試按鈕會永久停用。
                emit(
                    "skipped",
                    "?",
                    0.0,
                    _ERR_MODE_SWITCHED if mode == "pynput" else "",
                    _visual_unavailable("capture_unavailable"),
                )
                return
            if before is None and not can_ocr:
                emit(
                    "skipped",
                    "?",
                    0.0,
                    "",
                    _visual_unavailable(visual_error or "capture_unavailable"),
                    _text_unavailable(visual_error or "capture_unavailable"),
                )
                return
            img = capture_frame(mode, title, hwnd=hwnd or None)
            if cancel is not None and cancel.is_set():
                emit(
                    "skipped",
                    "?",
                    0.0,
                    "",
                    _visual_unavailable("cancelled"),
                    _text_unavailable("cancelled"),
                )
                return
            if self._run_active.is_set():
                emit(
                    "skipped",
                    "?",
                    0.0,
                    "",
                    _visual_unavailable("main_loop_running"),
                    _text_unavailable("main_loop_running"),
                )
                return
            if img is None or is_black_capture(img):
                emit(
                    "black",
                    "?",
                    (time.monotonic() - t0) * 1000,
                    "",
                    _visual_unavailable("black_capture"),
                    _text_unavailable("black_capture"),
                )
                return
            visual = self._analyze_visual(request, before, img, visual_error) if request else None
            roi, scope = _select_visual_roi(request, img.shape) if request else (None, "")
            text_diff = self._analyze_text_diff(
                request, before, img, visual, roi, scope, visual_error, cancel
            )
            if not can_ocr:
                emit("skipped", "?", (time.monotonic() - t0) * 1000, "", visual, text_diff)
                return
            img_rgb = img[:, :, ::-1].copy()
            h, w = img_rgb.shape[:2]
            if (w, h) != (frame_w, frame_h):
                emit(
                    "window_changed",
                    "?",
                    (time.monotonic() - t0) * 1000,
                    "",
                    _visual_unavailable("frame_size_changed"),
                    _text_unavailable("frame_size_changed"),
                )
                return
            matched = _find_text_after_click(list(text_diff.after_results), r.text)
            emit(
                "no_response" if matched else "success",
                "yes" if matched else "no",
                (time.monotonic() - t0) * 1000,
                visual=visual,
                text_diff=text_diff,
            )
        except Exception as e:
            logging.exception("click verify failed")
            emit("black", "?", 0.0, str(e))

    def _roi_patch(self, img: np.ndarray, r) -> np.ndarray:
        h, w = img.shape[:2]
        pad = max(4, int(max(r.w, r.h) * 0.25))
        x0 = max(0, r.x - pad)
        y0 = max(0, r.y - pad)
        x1 = min(w, r.x + r.w + pad)
        y1 = min(h, r.y + r.h + pad)
        return img[y0:y1, x0:x1]

    def _show_click_verify(
        self,
        state: str,
        *,
        text: str = "",
        api_ok: bool,
        sx: int,
        sy: int,
        last_error: str = "",
        ms: float = 0.0,
        still: str = "?",
    ):
        key = state if state in _CLICK_VERIFY_STATES else "black"
        color, suffix = _CLICK_VERIFY_STATES[key]
        guidance = T(f"ocr_debug.click_verify.{suffix}", text=text)
        dev = T(
            "ocr_debug.click_verify.dev_info",
            mode=_get_interaction_mode(),
            source=self._capture_source or "?",
            text=text,
            sx=sx,
            sy=sy,
            hwnd=_screenshot.get_window_hwnd(self._window_title) or "?",
            api=T("ocr_debug.click_success") if api_ok else T("ocr_debug.click_failed"),
            last_error=last_error or "無",
            ms=round(ms),
            still_visible=still,
        )
        self._last_verify_guidance = guidance
        self._last_verify_dev = dev
        self._click_error_label.setStyleSheet(f"color: {color};")
        self._click_error_label.setText(T(f"ocr_debug.click_verify.short.{suffix}", text=text))
        self._click_error_label.show()
        QTimer.singleShot(15000, self._click_error_label.hide)
        if key in ("inject_fail", "no_response", "black"):
            # Legacy OCR observation is independent of the Backend result.
            logging.info("ocr_dbg click observation=%s text=%s", key, text)

    def _key_verify_worker(self, hwnd: int, key: str, request_id: int):
        def emit(state: str, **kw):
            self._signals.key_verify_done.emit(
                {
                    "state": state,
                    "similar": "?",
                    "err": "",
                    "ms": 0.0,
                    "key": key,
                    "request_id": request_id,
                    **kw,
                }
            )

        try:
            # 主循環已啟動 → 立即中止（尚未送出任何輸入）
            if self._verify_input_blocked():
                emit("fail", err=_ERR_RUN_ACTIVE)
                return
            mode = _get_interaction_mode()
            if mode == "pynput":
                emit("fail", err=_ERR_MODE_SWITCHED)
                return
            t0 = time.monotonic()
            before = capture_frame(mode, self._window_title, hwnd=hwnd)
            if before is None or is_black_capture(before):
                emit("black")
                return
            # 送出輸入前再確認一次：主循環可能在擷取期間啟動。
            # 已送出的 DOWN 不受這道閘影響（放開由後端層必定送出）。
            if self._verify_input_blocked():
                emit("fail", err=_ERR_RUN_ACTIVE)
                return
            if mode == "hybrid":
                with _hybrid.focus_guard(self._window_title, activate_window):
                    sent = _pynput_input.send_key(key)
            else:
                _bg_input.set_method(mode)
                sent = _bg_input.send_key(hwnd, key)
            ms = (time.monotonic() - t0) * 1000
            if not sent:
                emit("fail", err=_bg_input.last_error() or "", ms=ms)
                return
            time.sleep(_KEY_TEST_WAIT_SEC)
            after = capture_frame(mode, self._window_title, hwnd=hwnd)
            if after is None or is_black_capture(after):
                emit("black", ms=(time.monotonic() - t0) * 1000)
                return
            ms = (time.monotonic() - t0) * 1000
            if before.shape != after.shape:
                emit("window_changed", ms=ms)
                return
            sim = _frame_similarity(before, after)
            emit(
                "success" if sim < _KEY_SIMILAR_THRESHOLD else "no_change",
                similar=round(sim * 100, 1),
                ms=ms,
            )
        except Exception as e:
            logging.exception("key verify failed")
            emit("fail", err=str(e))

    def _show_key_verify(self, out: dict):
        state = out.get("state", "black")
        key = state if state in _KEY_VERIFY_STATES else "black"
        color, g_ns, g_key, s_ns, s_key = _KEY_VERIFY_STATES[key]
        test_key = out.get("key", _KEY_TEST_DEFAULT)
        sim = out.get("similar", "?")
        # 長文與短文可能來自不同命名空間，兩個命名空間的文案可用的 placeholder 皆一併帶上
        guidance = T(f"ocr_debug.{g_ns}.{g_key}", text="", sim=sim, key=test_key)
        dev = T(
            "ocr_debug.key_test.dev_info",
            mode=_get_interaction_mode(),
            source=self._capture_source or "?",
            key=test_key,
            sim=sim,
            hwnd=_screenshot.get_window_hwnd(self._window_title) or "?",
            api="send_key",
            err=out.get("err", "") or "無",
            ms=round(out.get("ms", 0.0)),
        )
        self._last_verify_guidance = guidance
        self._last_verify_dev = dev
        self._last_verify_title = T("ocr_debug.key_test.dialog_title")
        self._click_error_label.setStyleSheet(f"color: {color};")
        self._click_error_label.setText(T(f"ocr_debug.{s_ns}.short.{s_key}"))
        self._click_error_label.show()
        QTimer.singleShot(15000, self._click_error_label.hide)
        if key in ("no_change", "fail", "black"):
            # Legacy pixel observation cannot overwrite Backend or imply receipt.
            logging.info("ocr_dbg key observation=%s key=%s", key, test_key)

    # Phase 1 worker path. These definitions intentionally replace the legacy
    # callbacks above; all user initiated input now enters through this path.
    def _on_click_test(self):
        if self._verif_in_progress or self._run_active.is_set():
            return
        if not 0 <= self._selected_index < len(self._ocr_results):
            return
        selected = self._ocr_results[self._selected_index]
        target = _OcrTarget(
            selected.text, int(selected.x), int(selected.y), int(selected.w), int(selected.h)
        )
        rect = _screenshot.get_window_rect(self._window_title)
        request_id = self._click_verify_request_id + 1
        request = BackendTestRequest(
            generation=request_id,
            kind="click",
            mode=_get_interaction_mode(),
            window_title=str(self._window_title),
            hwnd=int(_screenshot.get_window_hwnd(self._window_title) or 0),
            target=target,
            capture_source_gdi=self._capture_source == T("ocr_debug.source_gdi"),
            window_rect=(
                (int(rect["x"]), int(rect["y"]), int(rect["w"]), int(rect["h"])) if rect else None
            ),
            frame_size=(
                (int(self._latest_raw.shape[1]), int(self._latest_raw.shape[0]))
                if self._latest_raw is not None
                else (0, 0)
            ),
        )
        self._click_verify_request_id = request_id
        self._verif_in_progress = True
        self._click_test_available = False
        self._click_error_label.hide()
        self._diagnostic_label.hide()
        self._diagnostic_detail_label.clear()
        self._diagnostic_detail_label.hide()
        self._diagnostic_detail_btn.setChecked(False)
        self._diagnostic_detail_btn.hide()
        self._click_test_btn.setText(T("ocr_debug.verifying"))
        self._sync_test_buttons()
        self._start_backend_test(request)

    def _on_key_test(self):
        if self._key_verif_in_progress or self._run_active.is_set():
            return
        request_id = self._key_verify_request_id + 1
        request = BackendTestRequest(
            generation=request_id,
            kind="key",
            mode=_get_interaction_mode(),
            window_title=str(self._window_title),
            hwnd=int(_screenshot.get_window_hwnd(self._window_title) or 0),
            key=str(self._key_test_combo.currentData() or _KEY_TEST_DEFAULT),
        )
        self._key_verify_request_id = request_id
        self._key_verif_in_progress = True
        self._key_test_available = False
        self._click_error_label.hide()
        self._diagnostic_label.hide()
        self._diagnostic_detail_label.clear()
        self._diagnostic_detail_label.hide()
        self._diagnostic_detail_btn.setChecked(False)
        self._diagnostic_detail_btn.hide()
        self._key_test_btn.setText(T("ocr_debug.key_test.verifying"))
        self._sync_test_buttons()
        self._start_backend_test(request)

    def _start_key_verify(self, hwnd: int, key: str):
        """Compatibility entry point; the backend operation still runs in a worker."""
        if self._key_verif_in_progress or self._run_active.is_set():
            return
        request_id = self._key_verify_request_id + 1
        self._key_verify_request_id = request_id
        request = BackendTestRequest(
            generation=request_id,
            kind="key",
            mode=_get_interaction_mode(),
            window_title=str(self._window_title),
            hwnd=int(hwnd or 0),
            key=str(key),
        )
        self._key_verif_in_progress = True
        self._key_test_available = False
        self._sync_test_buttons()
        self._start_backend_test(request)

    def _start_backend_test(self, request: BackendTestRequest):
        cancel = threading.Event()
        self._test_cancel_events[request.kind] = cancel
        try:
            threading.Thread(
                target=self._run_backend_test, args=(request, cancel), daemon=False
            ).start()
        except Exception as exc:
            logging.exception("OCR Debug worker start failed")
            result = BackendTestResult(
                request.generation,
                request.kind,
                request.mode,
                request.hwnd,
                request.key,
                None,
                BackendStatus.FAILED,
                0.0,
                error=str(exc) or type(exc).__name__,
            )
            self._signals.backend_test_done.emit(result)

    def _analyze_text_diff(
        self,
        request: BackendTestRequest,
        before: np.ndarray | None,
        after: np.ndarray | None,
        visual: VisualAnalysis,
        roi,
        scope: str,
        visual_error: str = "",
        cancel: threading.Event | None = None,
    ) -> TextDiffAnalysis:
        if visual is not None and visual.status == ObservationStatus.UNAVAILABLE:
            return _text_unavailable(visual.reason or "visual_unavailable")
        if before is None:
            return _text_unavailable(visual_error or "capture_unavailable", scope=scope)
        if after is None:
            return _text_unavailable("capture_unavailable", scope=scope)
        if roi is None:
            return _text_unavailable("roi_unavailable", scope=scope)
        if cancel is not None and cancel.is_set():
            return _text_unavailable("cancelled")
        if self._run_active.is_set():
            return _text_unavailable("main_loop_running")
        try:
            x, y, w, h = roi
            bx, by = x + (w or 0), y + (h or 0)
            opts = self._ocr_options()
            before_img = before[y:by, x:bx]
            after_img = after[y:by, x:bx]
            before_outcome = recognize_detailed(before_img, **opts)
            if cancel is not None and cancel.is_set():
                return _text_unavailable("cancelled", before_status=before_outcome.status)
            if self._run_active.is_set():
                return _text_unavailable("main_loop_running", before_status=before_outcome.status)
            after_outcome = recognize_detailed(after_img, **opts)
            if before_outcome.status != "ok" or after_outcome.status != "ok":
                reason = (
                    before_outcome.reason if before_outcome.status != "ok" else after_outcome.reason
                )
                reason = reason or before_outcome.status or after_outcome.status
                return TextDiffAnalysis(
                    status=ObservationStatus.UNAVAILABLE,
                    scope=scope,
                    before_ocr_status=before_outcome.status,
                    after_ocr_status=after_outcome.status,
                    reason=reason,
                    before_results=tuple(before_outcome.results),
                    after_results=tuple(after_outcome.results),
                )
            return _compare_ocr_texts(
                before_outcome.results, after_outcome.results, scope=scope, roi=roi
            )
        except Exception:
            logging.exception("text diff failed")
            return TextDiffAnalysis(
                status=ObservationStatus.UNAVAILABLE,
                scope=scope,
                reason="worker_error",
            )

    def _capture_visual_before(
        self, request: BackendTestRequest, cancel: threading.Event
    ) -> tuple[np.ndarray | None, str]:
        """Capture the pre-input frame in the worker thread (never on GUI thread)."""
        try:
            if request.mode == "pynput":
                activate_window(request.window_title)
                if cancel.wait(0.15):
                    return None, "cancelled"
            hwnd = request.hwnd or None
            before = capture_frame(request.mode, request.window_title, hwnd=hwnd)
            if before is None:
                return None, "capture_unavailable"
            if is_black_capture(before):
                return None, "black_capture"
            return before, ""
        except Exception:
            logging.exception("visual baseline capture failed")
            return None, "capture_unavailable"

    def _analyze_visual(
        self,
        request: BackendTestRequest,
        before: np.ndarray | None,
        after: np.ndarray | None,
        visual_error: str = "",
    ) -> VisualAnalysis:
        if before is None:
            return _visual_unavailable(visual_error or "capture_unavailable")
        if after is None:
            return _visual_unavailable("capture_unavailable")
        try:
            if _get_interaction_mode() != request.mode:
                return _visual_unavailable("source_changed")
            if request.hwnd:
                current = _screenshot.get_window_hwnd(request.window_title)
                if not current or int(current) != int(request.hwnd):
                    return _visual_unavailable("window_changed")
            roi, scope = _select_visual_roi(request, after.shape)
            if roi is None:
                return _visual_unavailable("roi_unavailable", scope=scope)
            return _compare_visual(before, after, roi, scope=scope)
        except Exception:
            logging.exception("visual comparison failed")
            return _visual_unavailable("worker_error")

    def _run_backend_test(self, request: BackendTestRequest, cancel: threading.Event):
        before, visual_error = None, ""
        if request.kind in ("click", "key"):
            before, visual_error = self._capture_visual_before(request, cancel)

        result, coords = self._dispatch_backend_test(request, cancel)
        try:
            self._signals.backend_test_done.emit(result)
        except RuntimeError:
            logging.debug("OCR Debug panel closed before backend result delivery")
            return
        if result.backend_status not in (BackendStatus.SUCCESS, BackendStatus.FAILED):
            return
        backend_ok = result.backend_status == BackendStatus.SUCCESS
        if request.kind == "click" and request.target is not None:
            self._click_verify_worker(
                request.target,
                *(coords or (0, 0)),
                request.frame_size[0],
                request.frame_size[1],
                request.generation,
                request=request,
                cancel=cancel,
                before=before,
                visual_error=visual_error,
                backend_ok=backend_ok,
            )
        elif request.kind == "key":
            self._key_observation_worker(request, before, visual_error, cancel)

    def _dispatch_backend_test(self, request: BackendTestRequest, cancel: threading.Event):
        started = time.monotonic()
        coords = None
        api_called = False
        previous_error = ""
        ok = False

        def result(status, error="", cancelled=False):
            return BackendTestResult(
                test_id=request.generation,
                kind=request.kind,
                mode=request.mode,
                hwnd=request.hwnd,
                key=request.key,
                coordinates=coords,
                backend_status=status,
                elapsed_ms=(time.monotonic() - started) * 1000 if api_called else 0.0,
                error=error,
                cancelled=cancelled,
            )

        if cancel.is_set():
            return result(BackendStatus.CANCELLED, cancelled=True), coords
        if self._run_active.is_set():
            return result(BackendStatus.NOT_EXECUTED, "main_loop_running"), coords

        try:
            if request.kind == "click":
                target = request.target
                if target is None:
                    return result(BackendStatus.NOT_EXECUTED, "target_unavailable"), coords
                ox, oy = target.x + target.w // 2, target.y + target.h // 2
                if request.mode == "frida":
                    if not request.hwnd:
                        return result(BackendStatus.NOT_EXECUTED, "window_unavailable"), coords
                    if request.capture_source_gdi:
                        x, y = ox, oy
                    else:
                        chrome = _screenshot.get_window_client_offset(request.window_title) or (
                            0,
                            0,
                        )
                        x, y = ox - int(chrome[0]), oy - int(chrome[1])
                    coords = (x, y)
                    _bg_input.set_method(request.mode)
                    previous_error = _bg_input.last_error()
                    if cancel.is_set() or self._run_active.is_set():
                        return result(
                            BackendStatus.CANCELLED
                            if cancel.is_set()
                            else BackendStatus.NOT_EXECUTED,
                            cancelled=cancel.is_set(),
                        ), coords
                    api_called = True
                    ok = bool(_bg_input.click(request.hwnd, x, y, cancel=cancel))
                elif request.mode in ("hybrid", "pynput"):
                    import ctypes
                    from ctypes import wintypes

                    if request.mode == "hybrid" or request.capture_source_gdi:
                        if not request.hwnd:
                            return result(BackendStatus.NOT_EXECUTED, "window_unavailable"), coords
                        point = wintypes.POINT(0, 0)
                        if not ctypes.windll.user32.ClientToScreen(
                            request.hwnd, ctypes.byref(point)
                        ):
                            return result(
                                BackendStatus.NOT_EXECUTED, "coordinates_unavailable"
                            ), coords
                        coords = (int(point.x) + ox, int(point.y) + oy)
                    elif request.window_rect:
                        coords = (request.window_rect[0] + ox, request.window_rect[1] + oy)
                    else:
                        return result(BackendStatus.NOT_EXECUTED, "coordinates_unavailable"), coords
                    if request.mode == "hybrid":
                        with _hybrid.focus_guard(
                            request.window_title, activate_window, request.hwnd
                        ) as focus_ok:
                            if cancel.is_set() or self._run_active.is_set():
                                return result(
                                    BackendStatus.CANCELLED
                                    if cancel.is_set()
                                    else BackendStatus.NOT_EXECUTED,
                                    cancelled=cancel.is_set(),
                                ), coords
                            if not focus_ok:
                                return result(
                                    BackendStatus.NOT_EXECUTED, "focus_unavailable"
                                ), coords
                            api_called = True
                            ok = bool(_pynput_input.send_click(*coords, cancel=cancel))
                    else:
                        activate_window(request.window_title)
                        if cancel.wait(0.15):
                            return result(BackendStatus.CANCELLED, cancelled=True), coords
                        if self._run_active.is_set():
                            return result(BackendStatus.NOT_EXECUTED, "main_loop_running"), coords
                        api_called = True
                        ok = bool(_pynput_input.send_click(*coords, cancel=cancel))
                else:
                    return result(BackendStatus.NOT_EXECUTED, "mode_unavailable"), coords
            elif request.kind == "key":
                if request.mode == "pynput":
                    activate_window(request.window_title)
                    if cancel.wait(0.15):
                        return result(BackendStatus.CANCELLED, cancelled=True), coords
                    if self._run_active.is_set():
                        return result(BackendStatus.NOT_EXECUTED, "main_loop_running"), coords
                    api_called = True
                    ok = bool(_pynput_input.send_key(request.key, cancel=cancel))
                elif request.mode == "hybrid":
                    if not request.hwnd:
                        return result(BackendStatus.NOT_EXECUTED, "window_unavailable"), coords
                    with _hybrid.focus_guard(request.window_title, activate_window) as focus_ok:
                        if cancel.is_set() or self._run_active.is_set():
                            return result(
                                BackendStatus.CANCELLED
                                if cancel.is_set()
                                else BackendStatus.NOT_EXECUTED,
                                cancelled=cancel.is_set(),
                            ), coords
                        if not focus_ok:
                            return result(BackendStatus.NOT_EXECUTED, "focus_unavailable"), coords
                        api_called = True
                        ok = bool(_pynput_input.send_key(request.key, cancel=cancel))
                elif request.mode == "frida":
                    if not request.hwnd:
                        return result(BackendStatus.NOT_EXECUTED, "window_unavailable"), coords
                    _bg_input.set_method(request.mode)
                    previous_error = _bg_input.last_error()
                    if cancel.is_set() or self._run_active.is_set():
                        return result(
                            BackendStatus.CANCELLED
                            if cancel.is_set()
                            else BackendStatus.NOT_EXECUTED,
                            cancelled=cancel.is_set(),
                        ), coords
                    api_called = True
                    ok = bool(_bg_input.send_key(request.hwnd, request.key, cancel=cancel))
                else:
                    return result(BackendStatus.NOT_EXECUTED, "mode_unavailable"), coords
            else:
                return result(BackendStatus.NOT_EXECUTED, "test_unavailable"), coords
        except Exception as exc:
            logging.exception("OCR Debug backend test failed")
            return result(BackendStatus.FAILED, str(exc) or type(exc).__name__), coords

        if cancel.is_set() or self._run_active.is_set():
            return result(BackendStatus.CANCELLED, cancelled=True), coords
        if ok:
            return result(BackendStatus.SUCCESS), coords
        error = ""
        if request.mode == "frida":
            try:
                error = _error_for_backend_failure(previous_error, _bg_input.last_error())
            except Exception:
                pass
        return result(BackendStatus.FAILED, error or "error_unavailable"), coords

    def _on_backend_test_done(self, result: BackendTestResult):
        current_id = (
            self._click_verify_request_id if result.kind == "click" else self._key_verify_request_id
        )
        if result.test_id != current_id:
            return
        self._diagnostic_result = result
        self._render_diagnostic_result(result)
        if result.backend_status == BackendStatus.FAILED and result.mode == "frida":
            self.bg_inject_fail.emit()
        if result.backend_status != BackendStatus.SUCCESS or result.mode == "pynput":
            self._finish_test_ui(result.kind)

    def _render_diagnostic_result(self, result: BackendTestResult):
        kind = T(f"ocr_debug.diagnostic.kind.{result.kind}")
        target = (
            f"{result.coordinates[0]}, {result.coordinates[1]}"
            if result.coordinates
            else result.key
        )
        backend = T(f"ocr_debug.diagnostic.backend.{result.backend_status.value}")
        visual_status = result.visual_status
        if result.visual.status != ObservationStatus.NOT_RUN:
            visual_status = result.visual.status
        visual = T(f"ocr_debug.diagnostic.observation.{visual_status.value}")
        ocr = T(f"ocr_debug.diagnostic.observation.{result.ocr_status.value}")
        # 主摘要：只有三項核心狀態。Backend FAILED 的錯誤原因留在主層。
        main_lines = [
            T(
                "ocr_debug.diagnostic.identity",
                kind=kind,
                mode=result.mode,
                hwnd=result.hwnd,
                target=target,
            ),
            T("ocr_debug.diagnostic.backend_line", status=backend, ms=round(result.elapsed_ms)),
            T("ocr_debug.diagnostic.observation_line", visual=visual, ocr=ocr),
        ]
        if result.error:
            error = (
                T("ocr_debug.diagnostic.error_unavailable")
                if result.error == "error_unavailable"
                else T(f"ocr_debug.diagnostic.reason.{result.error}", default=result.error)
            )
            main_lines.append(T("ocr_debug.diagnostic.error_line", error=error))
        # 詳細資訊：耗時起的全部細節（ms 已在主層顯示，此處保留完整行供查閱）。
        detail_lines: list[str] = []
        if result.visual.status != ObservationStatus.NOT_RUN:
            scope = (
                T(f"ocr_debug.diagnostic.scope.{result.visual.scope}")
                if result.visual.scope in ("roi", "frame")
                else T("ocr_debug.diagnostic.scope.none")
            )
            roi_text = (
                f"{result.visual.roi[0]},{result.visual.roi[1]},{result.visual.roi[2]},{result.visual.roi[3]}"
                if result.visual.roi
                else T("ocr_debug.diagnostic.scope.none")
            )
            detail_lines.append(
                T(
                    "ocr_debug.diagnostic.visual_line",
                    status=visual,
                    ratio=round(result.visual.diff_ratio * 100, 2),
                    pixels=result.visual.diff_pixels,
                    scope=scope,
                    roi=roi_text,
                )
            )
            if result.visual.reason:
                reason = T(
                    f"ocr_debug.diagnostic.visual_reason.{result.visual.reason}",
                    default=result.visual.reason,
                )
                detail_lines.append(T("ocr_debug.diagnostic.visual_reason_line", reason=reason))
            # Visual 僅供內部判斷：結果存於 BackendTestResult.visual，不產生任何圖片預覽
        if result.text_diff.status != ObservationStatus.NOT_RUN:
            td_scope = (
                T(f"ocr_debug.diagnostic.text_scope.{result.text_diff.scope}")
                if result.text_diff.scope in ("roi", "frame")
                else T("ocr_debug.diagnostic.scope.none")
            )
            if result.text_diff.status == ObservationStatus.UNAVAILABLE:
                detail_lines.append(
                    T(
                        "ocr_debug.diagnostic.text_unavailable_line",
                        reason=T(
                            f"ocr_debug.diagnostic.text_reason.{result.text_diff.reason}",
                            default=result.text_diff.reason,
                        ),
                    )
                )
            else:
                parts = []
                if result.text_diff.added:
                    parts.append(
                        T(
                            "ocr_debug.diagnostic.text_added",
                            texts="、".join(result.text_diff.added),
                        )
                    )
                if result.text_diff.disappeared:
                    parts.append(
                        T(
                            "ocr_debug.diagnostic.text_disappeared",
                            texts="、".join(result.text_diff.disappeared),
                        )
                    )
                if result.text_diff.changed:
                    parts.append(
                        T(
                            "ocr_debug.diagnostic.text_changed",
                            texts="、".join(f"{b}→{a}" for b, a in result.text_diff.changed),
                        )
                    )
                if result.text_diff.moved:
                    parts.append(
                        T(
                            "ocr_debug.diagnostic.text_moved",
                            texts="、".join(result.text_diff.moved),
                        )
                    )
                summary = "｜".join(parts) if parts else T("ocr_debug.diagnostic.text_no_change")
                detail_lines.append(
                    T("ocr_debug.diagnostic.text_line", summary=summary, scope=td_scope)
                )
        self._diagnostic_label.setText("\n".join(main_lines))
        self._diagnostic_label.show()
        self._diagnostic_detail_label.setText("\n".join(detail_lines))
        self._diagnostic_detail_btn.show()
        self._refresh_diagnostic_detail_visibility()

    def _on_diagnostic_detail_toggled(self, _checked: bool):
        self._refresh_diagnostic_detail_visibility()

    def _refresh_diagnostic_detail_visibility(self):
        expanded = self._diagnostic_detail_btn.isChecked()
        self._diagnostic_detail_label.setVisible(
            expanded and not self._diagnostic_detail_label.text() == ""
        )
        self._diagnostic_detail_btn.setText(
            T("ocr_debug.diagnostic.detail_hide") if expanded else T("ocr_debug.diagnostic.detail")
        )

    def _finish_test_ui(self, kind: str):
        self._test_cancel_events.pop(kind, None)
        if kind == "click":
            self._verif_in_progress = False
            self._click_test_available = self._selected_index >= 0
            self._click_test_btn.setText(T("ocr_debug.click_test"))
        else:
            self._key_verif_in_progress = False
            self._key_test_available = True
            self._key_test_btn.setText(T("ocr_debug.key_test"))
        self._sync_test_buttons()

    def cancel_active_tests(self):
        """Cancel pending tests during application shutdown; backends still release sent input."""
        for cancel_event in self._test_cancel_events.values():
            cancel_event.set()
        self._click_verify_request_id += 1
        self._key_verify_request_id += 1
        self._verif_in_progress = False
        self._key_verif_in_progress = False

    def _key_observation_worker(self, request, before, visual_error, cancel):
        def emit(state, visual=None, text_diff=None, **kw):
            if visual is None:
                visual = _visual_unavailable(visual_error or "capture_unavailable")
            if text_diff is None:
                text_diff = _text_unavailable(visual_error or "capture_unavailable")
            self._signals.key_verify_done.emit(
                {
                    "state": state,
                    "similar": "?",
                    "err": "",
                    "ms": 0.0,
                    "key": request.key,
                    "mode": request.mode,
                    "request_id": request.generation,
                    "visual": visual,
                    "text_diff": text_diff,
                    **kw,
                }
            )

        try:
            if cancel.is_set() or self._run_active.is_set():
                reason = "main_loop_running" if self._run_active.is_set() else "cancelled"
                emit(
                    "fail",
                    _visual_unavailable(reason),
                    _text_unavailable(reason),
                    err=_ERR_RUN_ACTIVE,
                )
                return
            if before is None:
                emit(
                    "black",
                    text_diff=_text_unavailable(visual_error or "capture_unavailable"),
                    err=visual_error or "capture_unavailable",
                )
                return
            time.sleep(_KEY_TEST_WAIT_SEC)
            if cancel.is_set() or self._run_active.is_set():
                reason = "main_loop_running" if self._run_active.is_set() else "cancelled"
                emit(
                    "fail",
                    _visual_unavailable(reason),
                    _text_unavailable(reason),
                    err=_ERR_RUN_ACTIVE,
                )
                return
            after = capture_frame(request.mode, request.window_title, hwnd=request.hwnd or None)
            if cancel.is_set():
                emit(
                    "fail",
                    _visual_unavailable("cancelled"),
                    _text_unavailable("cancelled"),
                    err=_ERR_RUN_ACTIVE,
                )
                return
            if self._run_active.is_set():
                emit(
                    "fail",
                    _visual_unavailable("main_loop_running"),
                    _text_unavailable("main_loop_running"),
                    err=_ERR_RUN_ACTIVE,
                )
                return
            if after is None:
                emit(
                    "black",
                    _visual_unavailable("capture_unavailable"),
                    _text_unavailable("capture_unavailable"),
                )
            elif is_black_capture(after):
                emit(
                    "black",
                    _visual_unavailable("black_capture"),
                    _text_unavailable("black_capture"),
                )
            elif before.shape != after.shape:
                emit(
                    "window_changed",
                    _visual_unavailable("frame_size_changed"),
                    _text_unavailable("frame_size_changed"),
                )
            else:
                visual = self._analyze_visual(request, before, after, visual_error)
                roi, scope = _select_visual_roi(request, after.shape)
                text_diff = self._analyze_text_diff(
                    request, before, after, visual, roi, scope, visual_error, cancel
                )
                sim = _frame_similarity(before, after)
                if visual.status == ObservationStatus.CHANGED:
                    state = "success"
                elif visual.status == ObservationStatus.NO_CHANGE:
                    state = "no_change"
                else:
                    state = "fail"
                emit(
                    state,
                    visual,
                    text_diff,
                    similar=round(sim * 100, 1),
                )
        except Exception as exc:
            logging.exception("key observation failed")
            emit("fail", _visual_unavailable("worker_error"), err=str(exc) or type(exc).__name__)

    def _on_click_verify_done(self, out: dict):
        if out.get("request_id") != self._click_verify_request_id:
            return
        old = self._diagnostic_result
        if old and old.test_id == out["request_id"]:
            status = (
                ObservationStatus.TEXT_PRESENT
                if out.get("still") == "yes"
                else ObservationStatus.TEXT_MISSING
            )
            if out.get("state") in ("black", "window_changed", "skipped"):
                status = ObservationStatus.UNAVAILABLE
            visual = out.get("visual")
            text_diff = out.get("text_diff")
            if isinstance(visual, VisualAnalysis) or isinstance(text_diff, TextDiffAnalysis):
                changes = {
                    "visual_status": visual.status
                    if isinstance(visual, VisualAnalysis)
                    else old.visual_status,
                    "observation": out.get("state", ""),
                }
                if isinstance(visual, VisualAnalysis):
                    changes["visual"] = visual
                if isinstance(text_diff, TextDiffAnalysis):
                    changes["text_diff"] = text_diff
                self._diagnostic_result = replace(old, **changes)
            else:
                self._diagnostic_result = replace(
                    old, ocr_status=status, observation=out.get("state", "")
                )
            self._render_diagnostic_result(self._diagnostic_result)
        self._finish_test_ui("click")
        self._show_click_verify(
            out["state"],
            text=out.get("text", ""),
            api_ok=bool(old and old.backend_status == BackendStatus.SUCCESS),
            sx=out.get("sx", 0),
            sy=out.get("sy", 0),
            last_error=out.get("last_error", ""),
            ms=out.get("ms", 0.0),
            still=out.get("still", "?"),
        )

    def _on_key_verify_done(self, out: dict):
        if out.get("request_id") != self._key_verify_request_id:
            return
        old = self._diagnostic_result
        if old and old.test_id == out["request_id"]:
            visual = out.get("visual")
            text_diff = out.get("text_diff")
            if isinstance(visual, VisualAnalysis) or isinstance(text_diff, TextDiffAnalysis):
                changes = {
                    "visual_status": visual.status
                    if isinstance(visual, VisualAnalysis)
                    else old.visual_status,
                    "observation": out.get("state", ""),
                }
                if isinstance(visual, VisualAnalysis):
                    changes["visual"] = visual
                if isinstance(text_diff, TextDiffAnalysis):
                    changes["text_diff"] = text_diff
                self._diagnostic_result = replace(old, **changes)
            else:
                legacy_visual = {
                    "success": ObservationStatus.CHANGED,
                    "no_change": ObservationStatus.NO_CHANGE,
                    "black": ObservationStatus.UNAVAILABLE,
                    "window_changed": ObservationStatus.UNAVAILABLE,
                    "fail": ObservationStatus.UNAVAILABLE,
                }.get(out.get("state"), ObservationStatus.UNAVAILABLE)
                self._diagnostic_result = replace(
                    old, visual_status=legacy_visual, observation=out.get("state", "")
                )
            self._render_diagnostic_result(self._diagnostic_result)
        self._finish_test_ui("key")
        self._show_key_verify(out)

    def _open_click_detail(self):
        guidance = getattr(self, "_last_verify_guidance", "")
        dev = getattr(self, "_last_verify_dev", "")
        if not guidance and not dev:
            return
        title = getattr(self, "_last_verify_title", "") or T("ocr_debug.verify.dialog_title")
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        v = QVBoxLayout(dlg)
        guide_label = QLabel(guidance)
        guide_label.setWordWrap(True)
        v.addWidget(guide_label)
        dev_view = QTextEdit(dev)
        dev_view.setReadOnly(True)
        dev_view.setFont(QFont("Consolas", 9))
        dev_view.setFixedHeight(150)
        v.addWidget(dev_view)
        row = QHBoxLayout()
        copy_btn = QPushButton(T("ocr_debug.verify.copy"))
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(dev))
        row.addWidget(copy_btn)
        row.addStretch()
        close_btn = QPushButton(T("ocr_debug.verify.close"))
        close_btn.clicked.connect(dlg.accept)
        row.addWidget(close_btn)
        v.addLayout(row)
        dlg.resize(560, 420)
        dlg.exec()

    def _rebuild_annotated(self):
        try:
            if self._latest_raw is None:
                self._annotated_pixmap = None
                self._crop_pixmap = None
                return
            h, w = self._latest_raw.shape[:2]
            if h < 1 or w < 1:
                self._annotated_pixmap = None
                self._crop_pixmap = None
                return
            img = np.ascontiguousarray(self._latest_raw)
            h, w, ch = img.shape
            q_img = QImage(img.tobytes(), w, h, ch * w, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            if pixmap.isNull():
                self._annotated_pixmap = None
                self._crop_pixmap = None
                return

            if not self._show_boxes:
                # 預設乾淨原圖：不繪製任何 OCR 框/標籤（選取高亮一併隱藏）。
                self._annotated_pixmap = pixmap
                self._update_crop_preview()
                return

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            font = QFont("Consolas", 9)
            painter.setFont(font)
            fm = painter.fontMetrics()
            th = fm.height()

            for i, r in enumerate(self._ocr_results):
                if i == self._selected_index:
                    painter.setPen(QPen(QColor(255, 220, 0), 5))
                elif r.confidence >= 0.5:
                    painter.setPen(QPen(QColor(0, 220, 255), 3))
                else:
                    painter.setPen(QPen(QColor(255, 80, 80), 3))
                painter.drawRect(r.x, r.y, r.w, r.h)

                label = f"{i + 1}  {r.text}  {int(r.confidence * 100)}%"
                tw = fm.horizontalAdvance(label)

                label_x = r.x
                label_y = r.y - 4
                bg_y = label_y - th - 2
                if bg_y < 0:
                    label_y = r.y + th + 4
                    bg_y = r.y

                painter.fillRect(label_x - 2, bg_y - 2, tw + 8, th + 6, QColor(0, 0, 0, 180))
                text_color = QColor(255, 255, 255) if r.confidence >= 0.5 else QColor(255, 180, 180)
                painter.setPen(text_color)
                painter.drawText(label_x + 2, label_y, label)

            painter.end()
            self._annotated_pixmap = pixmap
            self._update_crop_preview()
        except Exception:
            logging.exception("_rebuild_annotated failed")
            self._annotated_pixmap = None
            self._crop_pixmap = None

    def _update_crop_preview(self):
        try:
            self._crop_pixmap = None
            if self._latest_raw is None:
                self._selected_detail.setText(T("ocr_debug.selected_none"))
                self._crop_label.setText(T("ocr_debug.no_preview"))
                self._crop_label.setPixmap(QPixmap())
                return

            if self._selected_index < 0 or self._selected_index >= len(self._ocr_results):
                self._selected_detail.setText(T("ocr_debug.selected_none"))
                self._crop_label.setText(T("ocr_debug.crop_hint"))
                self._crop_label.setPixmap(QPixmap())
                return

            r = self._ocr_results[self._selected_index]
            pad = 24
            x0 = max(0, r.x - pad)
            y0 = max(0, r.y - pad)
            x1 = min(self._latest_raw.shape[1], r.x + r.w + pad)
            y1 = min(self._latest_raw.shape[0], r.y + r.h + pad)
            if x1 <= x0 or y1 <= y0:
                self._crop_label.setText(T("ocr_debug.crop_gen_failed"))
                self._crop_label.setPixmap(QPixmap())
                return

            crop = np.ascontiguousarray(self._latest_raw[y0:y1, x0:x1])
            ch = crop.shape[2]
            q_img = QImage(
                crop.tobytes(),
                crop.shape[1],
                crop.shape[0],
                ch * crop.shape[1],
                QImage.Format.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(q_img)
            self._crop_pixmap = pixmap
            self._crop_label.setPixmap(
                pixmap.scaled(
                    self._crop_label.width(),
                    self._crop_label.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._selected_detail.setText(
                T(
                    "ocr_debug.detail_text",
                    n=self._selected_index + 1,
                    text=r.text,
                    x=r.x,
                    y=r.y,
                    w=r.w,
                    h=r.h,
                    conf=int(r.confidence * 100),
                )
            )
        except Exception:
            logging.exception("_update_crop_preview failed")

    def _update_display(self):
        if self._annotated_pixmap is None:
            return
        target = self._image_label.contentsRect().size()
        if target.width() < 10 or target.height() < 10:
            target = self._image_label.size()
        scaled = self._annotated_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def clear_results(self):
        for cancel_event in self._test_cancel_events.values():
            cancel_event.set()
        # 遞增三種背景任務各自的 generation id，讓在途結果全部失效。
        # 注意：這「不代表取消 Worker」——Worker 仍會跑完，只是結果不得回填新畫面。
        self._ocr_request_id += 1
        self._click_verify_request_id += 1
        self._key_verify_request_id += 1
        self._ocr_results = []
        self._latest_raw = None
        self._annotated_pixmap = None
        self._crop_pixmap = None
        self._capture_source = ""
        self._black_warn_text = ""
        self._selected_index = -1
        # 表格一併清空，舊視窗的列不得再被選取
        self._result_table.blockSignals(True)
        self._result_table.setRowCount(0)
        self._result_table.clearSelection()
        self._result_table.blockSignals(False)
        self._info_label.setText("")
        self._summary_label.setText(T("ocr_debug.summary"))
        self._last_verify_guidance = ""
        self._last_verify_dev = ""
        self._click_error_label.hide()
        self._add_rule_btn.setEnabled(False)
        self._template_btn.setEnabled(False)
        self._click_test_available = False
        self._sync_test_buttons()
        self._click_test_btn.setText(T("ocr_debug.click_test"))
        # 在途的驗證工作已被 generation id 作廢，旗標一併歸零，
        # 否則過期 slot 被忽略後沒人能解鎖，按鈕會永久卡在「驗證中」。
        self._verif_in_progress = False
        self._key_verif_in_progress = False
        self._key_test_available = True
        self._sync_test_buttons()
        self._key_test_btn.setText(T("ocr_debug.key_test"))
        self._diagnostic_result = None
        self._diagnostic_label.clear()
        self._diagnostic_label.hide()
        self._diagnostic_detail_label.clear()
        self._diagnostic_detail_label.hide()
        self._diagnostic_detail_btn.setChecked(False)
        self._diagnostic_detail_btn.hide()
        self._update_step_btn_state()
        self._image_label.setText(T("ocr_debug.switch_window"))
        self._image_label.setPixmap(QPixmap())
        self._crop_label.setText("")
        self._crop_label.setPixmap(QPixmap())
        self._selected_detail.setText(T("ocr_debug.selected_none"))
        self._sync_selection_widgets()
        # 在途 OCR 結果已作廢，擷取按鈕必須恢復可用，否則會永久卡在「辨識中」
        self._restore_capture_btn()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display()
        self._update_crop_preview()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            if obj is self._image_label:
                QTimer.singleShot(0, self._update_display)

        return super().eventFilter(obj, event)
