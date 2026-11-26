"""Clean Light-Themed Overlays: Floating Lyrics Bar, Minimalist Floating Capsule, Inline Editor & Region Selector."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from .config import LYRICS_STYLE_PRESETS, ConfigManager
from .win32_utils import qt_key_event_to_hotkey_str, set_exclude_from_capture, set_window_click_through


class HotkeyRecorderEdit(QLineEdit):
    """Click and press any key combo directly to set a shortcut."""

    hotkey_recorded = Signal(str)

    def __init__(self, initial_hotkey: str = "", parent: QWidget | None = None) -> None:
        super().__init__(initial_hotkey, parent)
        self._saved_hotkey = initial_hotkey
        self.setReadOnly(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(150)
        self.setFixedHeight(34)
        self.setPlaceholderText("点击设置")
        self.setToolTip("点击后直接按下新快捷键，Backspace 清空，ESC 取消")

    def set_hotkey(self, hk: str) -> None:
        self._saved_hotkey = hk
        self.setText(hk or "未设置")

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.setText("请按键...")
        self.setStyleSheet(
            "background-color: #EFF6FF; border: 1.5px solid #2563EB; color: #1D4ED8; font-weight: 600; border-radius: 8px;"
        )

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.setText(self._saved_hotkey or "未设置")
        self.setStyleSheet("")

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.clearFocus()
            return
        if key == Qt.Key.Key_Backspace:
            self._saved_hotkey = ""
            self.setText("未设置")
            self.hotkey_recorded.emit("")
            self.clearFocus()
            return
        combo = qt_key_event_to_hotkey_str(event)
        if combo:
            self._saved_hotkey = combo
            self.setText(combo)
            self.hotkey_recorded.emit(combo)
            self.clearFocus()


class InlineSubtitleEditDialog(QDialog):
    """Clean light-mode popover to edit current subtitle text & save character names."""

    saved = Signal(str, str)
    retranslate = Signal(str)
    glossary_added = Signal(str, str)

    def __init__(self, original: str, translated: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改字幕")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(480, 310)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        card = QFrame()
        card.setObjectName("lightEditCard")
        card.setStyleSheet(
            """
            QFrame#lightEditCard {
                background-color: #FFFFFF;
                border: 1px solid #DCE1EA;
                border-radius: 14px;
            }
            QLabel { color: #334155; font-size: 13px; }
            QLineEdit, QPlainTextEdit {
                background-color: #F8FAFC;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                padding: 7px 10px;
                font-size: 13px;
            }
            QLineEdit:focus, QPlainTextEdit:focus {
                border: 1px solid #2563EB;
                background-color: #FFFFFF;
            }
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #E2E8F0; }
            QPushButton#primaryBtn {
                background-color: #2563EB;
                border: 1px solid #2563EB;
                color: #FFFFFF;
                font-weight: 600;
            }
            QPushButton#primaryBtn:hover { background-color: #1D4ED8; border: 1px solid #1D4ED8; }
            """
        )
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        hdr = QHBoxLayout()
        title = QLabel("修改当前字幕")
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #0F172A;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.reject)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self.trans_edit = QPlainTextEdit(translated)
        self.trans_edit.setPlaceholderText("输入修改后的译文")
        self.trans_edit.setFixedHeight(68)
        lay.addWidget(self.trans_edit)

        orig_row = QHBoxLayout()
        self.orig_edit = QLineEdit(original)
        self.orig_edit.setPlaceholderText("识别原文")
        re_btn = QPushButton("重新翻译")
        re_btn.clicked.connect(self._on_retranslate)
        orig_row.addWidget(self.orig_edit, 1)
        orig_row.addWidget(re_btn)
        lay.addLayout(orig_row)

        gloss_row = QHBoxLayout()
        self.src_term = QLineEdit()
        self.src_term.setPlaceholderText("原词（如角色名）")
        self.dst_term = QLineEdit()
        self.dst_term.setPlaceholderText("固定译名")
        add_g_btn = QPushButton("存入词表")
        add_g_btn.clicked.connect(self._on_add_glossary)
        gloss_row.addWidget(self.src_term, 1)
        gloss_row.addWidget(self.dst_term, 1)
        gloss_row.addWidget(add_g_btn)
        lay.addLayout(gloss_row)

        self.tip_lbl = QLabel("")
        self.tip_lbl.setStyleSheet("color: #64748B; font-size: 12px;")
        lay.addWidget(self.tip_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("保存修改")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)
        lay.addLayout(btn_row)

    def _on_retranslate(self) -> None:
        txt = self.orig_edit.text().strip()
        if txt:
            self.retranslate.emit(txt)
            self.accept()

    def _on_add_glossary(self) -> None:
        s = self.src_term.text().strip()
        d = self.dst_term.text().strip()
        if s and d:
            self.glossary_added.emit(s, d)
            cur = self.trans_edit.toPlainText()
            if s in cur:
                self.trans_edit.setPlainText(cur.replace(s, d))
            self.tip_lbl.setText(f"已记住固定译名：{s} -> {d}")
            self.tip_lbl.setStyleSheet("color: #2563EB; font-size: 12px;")
            self.src_term.clear()
            self.dst_term.clear()

    def _on_save(self) -> None:
        self.saved.emit(self.orig_edit.text().strip(), self.trans_edit.toPlainText().strip())
        self.accept()


class LyricsStyleStudioWidget(QWidget):
    """Clean, airy light-mode subtitle style customizer with live preview banner."""

    style_changed = Signal()

    def __init__(self, cfg_mgr: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg_mgr = cfg_mgr
        self._updating_ui = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # Live Preview Banner (soft slate backdrop simulating a video frame)
        self.preview_frame = QFrame()
        self.preview_frame.setFixedHeight(104)
        self.preview_frame.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #334155, stop:1 #475569); border-radius: 12px;"
        )
        p_lay = QVBoxLayout(self.preview_frame)
        p_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_main_lbl = QLabel("字幕效果实时预览")
        self.preview_main_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_sub_lbl = QLabel("Subtitle live style preview")
        self.preview_sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p_lay.addWidget(self.preview_main_lbl)
        p_lay.addWidget(self.preview_sub_lbl)
        root.addWidget(self.preview_frame)

        # Settings Card
        card = QFrame()
        card.setProperty("card", True)
        grid = QGridLayout(card)
        grid.setContentsMargins(22, 20, 22, 20)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(16)

        grid.addWidget(QLabel("预设主题"), 0, 0)
        self.preset_combo = QComboBox()
        for key, info in LYRICS_STYLE_PRESETS.items():
            self.preset_combo.addItem(info["name"], key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_selected)
        grid.addWidget(self.preset_combo, 0, 1)

        grid.addWidget(QLabel("字幕字体"), 0, 2)
        self.font_combo = QComboBox()
        preferred_fonts = [
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "SimHei",
            "KaiTi",
            "YouYuan",
            "DengXian",
            "Segoe UI",
        ]
        avail = set(QFontDatabase.families())
        for f in preferred_fonts:
            if f in avail:
                self.font_combo.addItem(f)
        if self.font_combo.count() == 0:
            self.font_combo.addItems(list(avail)[:15])
        self.font_combo.currentTextChanged.connect(self._on_any_changed)
        grid.addWidget(self.font_combo, 0, 3)

        grid.addWidget(QLabel("文字大小"), 1, 0)
        size_box = QHBoxLayout()
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(18, 56)
        self.size_val_lbl = QLabel("30 px")
        self.size_val_lbl.setFixedWidth(46)
        self.size_slider.valueChanged.connect(self._on_any_changed)
        size_box.addWidget(self.size_slider, 1)
        size_box.addWidget(self.size_val_lbl)
        grid.addLayout(size_box, 1, 1)

        grid.addWidget(QLabel("底板透明"), 1, 2)
        bg_box = QHBoxLayout()
        self.bg_slider = QSlider(Qt.Orientation.Horizontal)
        self.bg_slider.setRange(0, 200)
        self.bg_lbl = QLabel("全透明")
        self.bg_lbl.setFixedWidth(64)
        self.bg_slider.valueChanged.connect(self._on_any_changed)
        bg_box.addWidget(self.bg_slider, 1)
        bg_box.addWidget(self.bg_lbl)
        grid.addLayout(bg_box, 1, 3)

        grid.addWidget(QLabel("描边粗细"), 2, 0)
        stroke_box = QHBoxLayout()
        self.stroke_slider = QSlider(Qt.Orientation.Horizontal)
        self.stroke_slider.setRange(0, 65)
        self.stroke_val_lbl = QLabel("3.4 px")
        self.stroke_val_lbl.setFixedWidth(46)
        self.stroke_slider.valueChanged.connect(self._on_any_changed)
        stroke_box.addWidget(self.stroke_slider, 1)
        stroke_box.addWidget(self.stroke_val_lbl)
        grid.addLayout(stroke_box, 2, 1)

        grid.addWidget(QLabel("阴影强度"), 2, 2)
        self.shadow_slider = QSlider(Qt.Orientation.Horizontal)
        self.shadow_slider.setRange(0, 230)
        self.shadow_slider.valueChanged.connect(self._on_any_changed)
        grid.addWidget(self.shadow_slider, 2, 3)

        grid.addWidget(QLabel("颜色配置"), 3, 0)
        color_row = QHBoxLayout()
        color_row.setSpacing(10)
        self.btn_col_top = QPushButton("主字色")
        self.btn_col_bot = QPushButton("渐变色")
        self.btn_col_stroke = QPushButton("描边色")
        self.btn_col_orig = QPushButton("原文色")
        self.btn_col_top.clicked.connect(lambda: self._pick_color("color_top"))
        self.btn_col_bot.clicked.connect(lambda: self._pick_color("color_bottom"))
        self.btn_col_stroke.clicked.connect(lambda: self._pick_color("stroke_color"))
        self.btn_col_orig.clicked.connect(lambda: self._pick_color("orig_color"))
        for b in (self.btn_col_top, self.btn_col_bot, self.btn_col_stroke, self.btn_col_orig):
            color_row.addWidget(b)
        grid.addLayout(color_row, 3, 1, 1, 3)

        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(24)
        self.auto_scale_chk = QCheckBox("长句自动缩放字号")
        self.bilingual_chk = QCheckBox("显示双语对照")
        self.exclude_chk = QCheckBox("防重复识别（可直接覆盖在原字幕上方）")
        for chk in (self.auto_scale_chk, self.bilingual_chk, self.exclude_chk):
            chk.toggled.connect(self._on_any_changed)
            toggles_row.addWidget(chk)
        toggles_row.addStretch()
        grid.addLayout(toggles_row, 4, 0, 1, 4)

        root.addWidget(card)
        self.sync_from_config()

    def sync_from_config(self) -> None:
        self._updating_ui = True
        st = self.cfg_mgr.config.style
        idx = self.preset_combo.findData(st.preset_key)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        f_idx = self.font_combo.findText(st.font_family)
        if f_idx >= 0:
            self.font_combo.setCurrentIndex(f_idx)
        self.size_slider.setValue(int(st.base_font_size))
        self.size_val_lbl.setText(f"{int(st.base_font_size)} px")
        self.auto_scale_chk.setChecked(bool(st.auto_scale_font))
        self.bilingual_chk.setChecked(bool(st.bilingual))
        self.stroke_slider.setValue(int(round(float(st.stroke_width) * 10)))
        self.stroke_val_lbl.setText(f"{float(st.stroke_width):.1f} px")
        self.shadow_slider.setValue(int(st.shadow_opacity))
        self.bg_slider.setValue(int(st.bg_opacity))
        self._update_bg_label(int(st.bg_opacity))
        self.exclude_chk.setChecked(bool(st.exclude_from_capture))
        self._refresh_color_buttons()
        self._update_preview_banner()
        self._updating_ui = False

    def _refresh_color_buttons(self) -> None:
        st = self.cfg_mgr.config.style
        for btn, hex_col, title in (
            (self.btn_col_top, st.color_top, "主字色"),
            (self.btn_col_bot, st.color_bottom, "渐变色"),
            (self.btn_col_stroke, st.stroke_color, "描边色"),
            (self.btn_col_orig, st.orig_color, "原文色"),
        ):
            c = QColor(hex_col)
            lum = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
            fg = "#1E293B" if lum > 165 else "#FFFFFF"
            btn.setText(f"{title}  {hex_col}")
            btn.setStyleSheet(
                f"background-color: {hex_col}; color: {fg}; border: 1px solid #CBD5E1; border-radius: 7px; padding: 6px 10px; font-weight: 600;"
            )

    def _update_preview_banner(self) -> None:
        st = self.cfg_mgr.config.style
        px = min(32, max(16, int(st.base_font_size * 0.85)))
        self.preview_main_lbl.setStyleSheet(
            f"background: transparent; color: {st.color_bottom}; font-family: '{st.font_family}'; font-size: {px}px; font-weight: 700;"
        )
        self.preview_sub_lbl.setVisible(bool(st.bilingual))
        self.preview_sub_lbl.setStyleSheet(
            f"background: transparent; color: {st.orig_color}; font-family: '{st.font_family}'; font-size: {max(12, int(px * 0.58))}px;"
        )

    def _update_bg_label(self, val: int) -> None:
        pct = int(round(val / 255.0 * 100))
        self.bg_lbl.setText("全透明" if val == 0 else f"{pct}%")

    def _on_preset_selected(self) -> None:
        if self._updating_ui:
            return
        key = self.preset_combo.currentData()
        if key:
            self.cfg_mgr.apply_preset(str(key))
            self.sync_from_config()
            self.style_changed.emit()

    def _pick_color(self, attr: str) -> None:
        st = self.cfg_mgr.config.style
        cur = QColor(getattr(st, attr))
        picked = QColorDialog.getColor(cur, self, "选择颜色")
        if picked.isValid():
            setattr(st, attr, picked.name().upper())
            self.cfg_mgr.save()
            self._refresh_color_buttons()
            self._update_preview_banner()
            self.style_changed.emit()

    def _on_any_changed(self) -> None:
        if self._updating_ui:
            return
        st = self.cfg_mgr.config.style
        st.font_family = self.font_combo.currentText()
        st.base_font_size = int(self.size_slider.value())
        self.size_val_lbl.setText(f"{st.base_font_size} px")
        st.auto_scale_font = self.auto_scale_chk.isChecked()
        st.bilingual = self.bilingual_chk.isChecked()
        st.stroke_width = round(self.stroke_slider.value() / 10.0, 1)
        self.stroke_val_lbl.setText(f"{st.stroke_width:.1f} px")
        st.shadow_opacity = int(self.shadow_slider.value())
        st.bg_opacity = int(self.bg_slider.value())
        self._update_bg_label(st.bg_opacity)
        st.exclude_from_capture = self.exclude_chk.isChecked()
        self.cfg_mgr.save()
        self._update_preview_banner()
        self.style_changed.emit()


class LyricsSubtitleWindow(QWidget):
    """Desktop-Lyrics Floating Subtitle Overlay with clean light hover capsule."""

    request_edit = Signal()
    request_open_style = Signal()
    request_snip = Signal()
    request_mark_region = Signal()
    request_open_panel = Signal()
    lock_state_changed = Signal(bool)

    def __init__(self, cfg_mgr: ConfigManager) -> None:
        super().__init__(None)
        self.cfg_mgr = cfg_mgr
        self._original_text = "Subtitles ready"
        self._translated_text = "悬浮字幕已就绪，框选区域或截图即可开始翻译"
        self._toast_text = ""

        self._hovered = False
        self._dragging = False
        self._resizing = False
        self._drag_offset = QPoint()
        self._resize_origin_pos = QPoint()
        self._resize_origin_size = self.size()

        self.setWindowTitle("轻译悬浮字幕")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setMinimumSize(420, 96)

        self._init_geometry()
        self._build_hover_toolbar()

        self._hide_bar_timer = QTimer(self)
        self._hide_bar_timer.setSingleShot(True)
        self._hide_bar_timer.timeout.connect(self._check_leave_hover)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._clear_toast)

    def _init_geometry(self) -> None:
        st = self.cfg_mgr.config.style
        screen = QGuiApplication.primaryScreen()
        s_geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        w = max(460, min(st.overlay_width, s_geo.width() - 60))
        h = max(110, min(st.overlay_height, 340))
        if st.overlay_x < 0 or st.overlay_y < 0:
            x = s_geo.x() + (s_geo.width() - w) // 2
            y = s_geo.y() + s_geo.height() - h - 55
        else:
            x, y = st.overlay_x, st.overlay_y
        self.setGeometry(x, y, w, h)

    def _build_hover_toolbar(self) -> None:
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("lyricsHoverBar")
        self.toolbar.setStyleSheet(
            """
            QFrame#lyricsHoverBar {
                background-color: rgba(255, 255, 255, 238);
                border: 1px solid #CBD5E1;
                border-radius: 13px;
            }
            QPushButton {
                background: transparent;
                color: #334155;
                border: none;
                border-radius: 7px;
                padding: 3px 9px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #EFF6FF;
                color: #2563EB;
            }
            """
        )
        bar_lay = QHBoxLayout(self.toolbar)
        bar_lay.setContentsMargins(10, 3, 10, 3)
        bar_lay.setSpacing(3)

        btn_snip = QPushButton("截图")
        btn_snip.clicked.connect(self.request_snip.emit)

        btn_reg = QPushButton("框选")
        btn_reg.clicked.connect(self.request_mark_region.emit)

        btn_bi = QPushButton("双语")
        btn_bi.clicked.connect(self._toggle_bilingual)

        btn_sm = QPushButton("A-")
        btn_sm.clicked.connect(lambda: self._step_font(-2))

        btn_lg = QPushButton("A+")
        btn_lg.clicked.connect(lambda: self._step_font(2))

        btn_preset = QPushButton("主题")
        btn_preset.clicked.connect(self._cycle_preset)

        btn_edit = QPushButton("改词")
        btn_edit.clicked.connect(self.request_edit.emit)

        btn_lock = QPushButton("锁定穿透")
        btn_lock.clicked.connect(lambda: self.set_locked(True))

        btn_panel = QPushButton("主面板")
        btn_panel.clicked.connect(self.request_open_panel.emit)

        btn_hide = QPushButton("隐藏")
        btn_hide.clicked.connect(self.hide)

        for b in (btn_snip, btn_reg, btn_bi, btn_sm, btn_lg, btn_preset, btn_edit, btn_lock, btn_panel, btn_hide):
            bar_lay.addWidget(b)

        self.toolbar.adjustSize()
        self.toolbar.hide()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.apply_native_window_flags()
        self._reposition_toolbar()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._reposition_toolbar()

    def _reposition_toolbar(self) -> None:
        self.toolbar.adjustSize()
        x = max(6, (self.width() - self.toolbar.width()) // 2)
        self.toolbar.move(x, 4)

    def apply_native_window_flags(self) -> None:
        hwnd = int(self.winId())
        st = self.cfg_mgr.config.style
        set_exclude_from_capture(hwnd, bool(st.exclude_from_capture))
        set_window_click_through(hwnd, bool(st.locked_click_through))
        if st.locked_click_through:
            self._hovered = False
            self.toolbar.hide()
        self.update()

    def set_subtitle(self, original: str, translated: str) -> None:
        self._original_text = (original or "").strip()
        self._translated_text = (translated or "").strip()
        self.update()

    def current_subtitle(self) -> tuple[str, str]:
        return self._original_text, self._translated_text

    def show_toast(self, msg: str, duration_ms: int = 2000) -> None:
        self._toast_text = msg
        self.update()
        self._toast_timer.start(duration_ms)

    def _clear_toast(self) -> None:
        self._toast_text = ""
        self.update()

    def set_locked(self, locked: bool) -> None:
        self.cfg_mgr.config.style.locked_click_through = locked
        self.cfg_mgr.save()
        if locked:
            self.show_toast("已开启鼠标穿透，可在迷你悬浮条或主面板解锁", 2200)
        else:
            self.show_toast("字幕已解锁", 1400)
        self.apply_native_window_flags()
        self.lock_state_changed.emit(locked)

    def _toggle_bilingual(self) -> None:
        st = self.cfg_mgr.config.style
        st.bilingual = not st.bilingual
        self.cfg_mgr.save()
        self.update()

    def _step_font(self, delta: int) -> None:
        st = self.cfg_mgr.config.style
        st.base_font_size = max(16, min(58, int(st.base_font_size) + delta))
        self.cfg_mgr.save()
        self.show_toast(f"字号 {st.base_font_size} px", 900)
        self.update()

    def _cycle_preset(self) -> None:
        keys = list(LYRICS_STYLE_PRESETS.keys())
        cur = self.cfg_mgr.config.style.preset_key
        nxt = keys[(keys.index(cur) + 1) % len(keys)] if cur in keys else keys[0]
        self.cfg_mgr.apply_preset(nxt)
        self.apply_native_window_flags()
        self.show_toast(LYRICS_STYLE_PRESETS[nxt]["name"], 1300)
        self.update()

    def enterEvent(self, event) -> None:
        if not self.cfg_mgr.config.style.locked_click_through:
            self._hovered = True
            self._reposition_toolbar()
            self.toolbar.show()
            self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hide_bar_timer.start(400)
        super().leaveEvent(event)

    def _check_leave_hover(self) -> None:
        if not self.rect().contains(self.mapFromGlobal(QCursor.pos())) and not self._dragging and not self._resizing:
            self._hovered = False
            self.toolbar.hide()
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self.cfg_mgr.config.style.locked_click_through:
            self.request_edit.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if self.cfg_mgr.config.style.locked_click_through:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            if pos.x() >= self.width() - 24 and pos.y() >= self.height() - 24:
                self._resizing = True
                self._resize_origin_pos = event.globalPosition().toPoint()
                self._resize_origin_size = self.size()
            else:
                self._dragging = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self.cfg_mgr.config.style.locked_click_through:
            return
        pos = event.position().toPoint()
        if self._resizing:
            delta = event.globalPosition().toPoint() - self._resize_origin_pos
            nw = max(self.minimumWidth(), self._resize_origin_size.width() + delta.x())
            nh = max(self.minimumHeight(), self._resize_origin_size.height() + delta.y())
            self.resize(nw, nh)
            event.accept()
            return
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        if pos.x() >= self.width() - 24 and pos.y() >= self.height() - 24:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._dragging or self._resizing:
            self._dragging = False
            self._resizing = False
            st = self.cfg_mgr.config.style
            st.overlay_x = self.x()
            st.overlay_y = self.y()
            st.overlay_width = self.width()
            st.overlay_height = self.height()
            self.cfg_mgr.save()
        super().mouseReleaseEvent(event)

    @staticmethod
    def _wrap_balanced_lines(text: str, font: QFont, max_w: float) -> List[str]:
        fm = QFontMetricsF(font)
        if fm.horizontalAdvance(text) <= max_w:
            return [text]

        mid = len(text) // 2
        best_idx = -1
        for offset in range(0, min(14, mid)):
            for cand in (mid - offset, mid + offset):
                if 1 <= cand < len(text) and text[cand - 1] in "，。！？、；…— ,.!?;:":
                    best_idx = cand
                    break
            if best_idx != -1:
                break

        if best_idx != -1:
            l1, l2 = text[:best_idx].strip(), text[best_idx:].strip()
            if fm.horizontalAdvance(l1) <= max_w * 1.06 and fm.horizontalAdvance(l2) <= max_w * 1.06:
                return [l1, l2]

        lines: List[str] = []
        cur = ""
        for ch in text:
            if fm.horizontalAdvance(cur + ch) > max_w and cur:
                lines.append(cur.strip())
                cur = ch
                if len(lines) == 2:
                    break
            else:
                cur += ch
        if cur:
            rem_start = sum(len(x) for x in lines)
            rest = text[rem_start:].strip() if len(lines) == 2 else cur.strip()
            if rest:
                lines.append(rest)
        return lines[:3]

    def _compute_adaptive_font_and_lines(self, text: str, avail_w: float, avail_h: float) -> tuple[QFont, List[str]]:
        st = self.cfg_mgr.config.style
        base_px = int(st.base_font_size)
        min_px = max(15, int(base_px * 0.60)) if st.auto_scale_font else base_px

        chosen_px = base_px
        for px in range(base_px, min_px - 1, -2):
            f = QFont(st.font_family)
            f.setPixelSize(px)
            f.setWeight(QFont.Weight.Bold if st.font_weight >= 650 else QFont.Weight.DemiBold)
            lines = self._wrap_balanced_lines(text, f, avail_w)
            fm = QFontMetricsF(f)
            total_h = len(lines) * fm.height() * 1.12
            widest = max((fm.horizontalAdvance(ln) for ln in lines), default=0.0)
            if len(lines) <= 2 and widest <= avail_w and total_h <= avail_h:
                return f, lines
            chosen_px = px

        f_final = QFont(st.font_family)
        f_final.setPixelSize(chosen_px)
        f_final.setWeight(QFont.Weight.Bold)
        return f_final, self._wrap_balanced_lines(text, f_final, avail_w)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        st = self.cfg_mgr.config.style
        top_pad = 36.0 if self._hovered else 10.0
        content_rect = QRectF(14.0, top_pad, max(80.0, self.width() - 28.0), max(48.0, self.height() - top_pad - 10.0))

        if st.bg_opacity > 0:
            bg_c = QColor(st.bg_color)
            bg_c.setAlpha(int(st.bg_opacity))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg_c)
            painter.drawRoundedRect(content_rect, float(st.bg_radius), float(st.bg_radius))

        if self._hovered and not st.locked_click_through:
            hover_pen = QPen(QColor(59, 130, 246, 135), 1.2, Qt.PenStyle.DashLine)
            painter.setPen(hover_pen)
            painter.setBrush(QColor(255, 255, 255, 28) if st.bg_opacity == 0 else Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(content_rect, float(st.bg_radius), float(st.bg_radius))
            grip_pen = QPen(QColor(59, 130, 246, 180), 1.6)
            painter.setPen(grip_pen)
            w, h = self.width(), self.height()
            painter.drawLine(w - 16, h - 6, w - 6, h - 16)
            painter.drawLine(w - 11, h - 6, w - 6, h - 11)

        trans_txt = self._translated_text
        orig_txt = self._original_text if (st.bilingual and self._original_text and self._original_text != trans_txt) else ""

        avail_w = max(120.0, content_rect.width() - 28.0)
        orig_px = max(13, int(round(st.base_font_size * st.orig_font_scale)))
        orig_reserve_h = (orig_px * 1.55) if orig_txt else 0.0
        main_avail_h = max(36.0, content_rect.height() - orig_reserve_h - 8.0)

        if trans_txt:
            main_font, main_lines = self._compute_adaptive_font_and_lines(trans_txt, avail_w, main_avail_h)
            fm_main = QFontMetricsF(main_font)
            line_step = fm_main.height() * 1.12

            orig_font = QFont(st.font_family)
            orig_font.setPixelSize(min(orig_px, max(12, int(main_font.pixelSize() * 0.65))))
            orig_font.setWeight(QFont.Weight.DemiBold)
            fm_orig = QFontMetricsF(orig_font)

            total_block_h = len(main_lines) * line_step + (fm_orig.height() + 4.0 if orig_txt else 0.0)
            cur_y = content_rect.top() + max(4.0, (content_rect.height() - total_block_h) / 2.0) + fm_main.ascent()

            for ln in main_lines:
                ln_w = fm_main.horizontalAdvance(ln)
                x = content_rect.center().x() - ln_w / 2.0
                self._draw_lyrics_line(
                    painter,
                    ln,
                    main_font,
                    QPointF(x, cur_y),
                    fm_main.ascent(),
                    fm_main.descent(),
                    QColor(st.color_top),
                    QColor(st.color_bottom),
                    QColor(st.stroke_color),
                    float(st.stroke_width),
                    int(st.shadow_opacity),
                )
                cur_y += line_step

            if orig_txt:
                elided_orig = fm_orig.elidedText(orig_txt, Qt.TextElideMode.ElideRight, avail_w)
                ow = fm_orig.horizontalAdvance(elided_orig)
                ox = content_rect.center().x() - ow / 2.0
                oy = cur_y - line_step + fm_main.descent() + 5.0 + fm_orig.ascent()
                orig_c = QColor(st.orig_color)
                self._draw_lyrics_line(
                    painter,
                    elided_orig,
                    orig_font,
                    QPointF(ox, oy),
                    fm_orig.ascent(),
                    fm_orig.descent(),
                    orig_c,
                    orig_c,
                    QColor(st.stroke_color),
                    max(1.6, float(st.stroke_width) * 0.68),
                    int(st.shadow_opacity * 0.85),
                )

        if self._toast_text:
            t_font = QFont(st.font_family, 10, QFont.Weight.DemiBold)
            fm_t = QFontMetricsF(t_font)
            tw = fm_t.horizontalAdvance(self._toast_text) + 24.0
            th = fm_t.height() + 10.0
            t_rect = QRectF((self.width() - tw) / 2.0, self.height() - th - 4.0, tw, th)
            painter.setPen(QPen(QColor("#CBD5E1"), 1.0))
            painter.setBrush(QColor(255, 255, 255, 240))
            painter.drawRoundedRect(t_rect, 10.0, 10.0)
            painter.setFont(t_font)
            painter.setPen(QColor("#1E293B"))
            painter.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, self._toast_text)

    @staticmethod
    def _draw_lyrics_line(
        painter: QPainter,
        text: str,
        font: QFont,
        baseline: QPointF,
        ascent: float,
        descent: float,
        col_top: QColor,
        col_bot: QColor,
        stroke_col: QColor,
        stroke_w: float,
        shadow_alpha: int,
    ) -> None:
        path = QPainterPath()
        path.addText(baseline, font, text)

        if shadow_alpha > 0:
            shadow_path = path.translated(1.8, 2.4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, min(255, shadow_alpha)))
            painter.drawPath(shadow_path)

        if stroke_w > 0.15:
            stroker = QPainterPathStroker()
            stroker.setWidth(stroke_w * 2.0)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            outline_path = stroker.createStroke(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(stroke_col)
            painter.drawPath(outline_path)

        grad = QLinearGradient(0.0, baseline.y() - ascent, 0.0, baseline.y() + descent)
        grad.setColorAt(0.0, col_top)
        grad.setColorAt(1.0, col_bot)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(grad)
        painter.drawPath(path)


class LiveRegionIndicator(QWidget):
    """Subtle clean blue corner brackets showing the marked subtitle region."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        hwnd = int(self.winId())
        set_exclude_from_capture(hwnd, True)
        set_window_click_through(hwnd, True)

    def set_target_rect(self, rect: QRect) -> None:
        self.setGeometry(rect.adjusted(-4, -4, 4, 4))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(37, 99, 235, 190), 2.2)
        p.setPen(pen)
        r = self.rect().adjusted(2, 2, -2, -2)
        L = min(20, r.width() // 5, r.height() // 2)
        p.drawLine(r.topLeft(), r.topLeft() + QPoint(L, 0))
        p.drawLine(r.topLeft(), r.topLeft() + QPoint(0, L))
        p.drawLine(r.topRight(), r.topRight() + QPoint(-L, 0))
        p.drawLine(r.topRight(), r.topRight() + QPoint(0, L))
        p.drawLine(r.bottomLeft(), r.bottomLeft() + QPoint(L, 0))
        p.drawLine(r.bottomLeft(), r.bottomLeft() + QPoint(0, -L))
        p.drawLine(r.bottomRight(), r.bottomRight() + QPoint(-L, 0))
        p.drawLine(r.bottomRight(), r.bottomRight() + QPoint(0, -L))


class RegionSelectorOverlay(QWidget):
    """Interactive screen rubber-band selector."""

    region_selected = Signal(QRect, str)

    def __init__(self, mode: str = "snip") -> None:
        super().__init__(None)
        self.mode = mode
        self._start_pos: Optional[QPoint] = None
        self._cur_pos: Optional[QPoint] = None

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        union = QRect()
        for scr in QGuiApplication.screens():
            union = union.united(scr.geometry())
        self.setGeometry(union)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.close()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_pos = event.globalPosition().toPoint()
            self._cur_pos = self._start_pos
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._start_pos is not None:
            self._cur_pos = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._start_pos and self._cur_pos:
            sel = QRect(self._start_pos, self._cur_pos).normalized()
            self.close()
            if sel.width() >= 16 and sel.height() >= 14:
                QTimer.singleShot(45, lambda: self.region_selected.emit(sel, self.mode))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(15, 23, 42, 95))

        tip = "拖动鼠标框选字幕监控区域  ·  右键或 ESC 取消" if self.mode == "mark_region" else "拖动鼠标框选需要翻译的画面  ·  右键或 ESC 取消"
        banner = QRectF((self.width() - 380) / 2.0, 36.0, 380.0, 38.0)
        p.setPen(QPen(QColor("#E2E8F0"), 1.0))
        p.setBrush(QColor(255, 255, 255, 242))
        p.drawRoundedRect(banner, 19.0, 19.0)
        p.setPen(QColor("#1E293B"))
        p.setFont(QFont("Microsoft YaHei UI", 10, QFont.Weight.DemiBold))
        p.drawText(banner, Qt.AlignmentFlag.AlignCenter, tip)

        if self._start_pos and self._cur_pos:
            local_start = self.mapFromGlobal(self._start_pos)
            local_cur = self.mapFromGlobal(self._cur_pos)
            sel = QRectF(local_start, local_cur).normalized()

            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            p.fillRect(sel, Qt.GlobalColor.transparent)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

            accent = QColor("#2563EB")
            p.setPen(QPen(accent, 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel)

            dim_txt = f"{int(sel.width())} × {int(sel.height())}"
            tag_r = QRectF(sel.left(), max(4.0, sel.top() - 26.0), 96.0, 22.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 235))
            p.drawRoundedRect(tag_r, 6.0, 6.0)
            p.setPen(accent)
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(tag_r, Qt.AlignmentFlag.AlignCenter, dim_txt)


class SnipResultCard(QDialog):
    """Clean light-mode floating card next to screenshot translation."""

    apply_to_lyrics = Signal(str, str)
    retranslate_requested = Signal(str)

    def __init__(self, anchor_rect: QRect, original: str, translated: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(400, 225)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        card = QFrame()
        card.setObjectName("snipLightCard")
        card.setStyleSheet(
            """
            QFrame#snipLightCard {
                background-color: #FFFFFF;
                border: 1px solid #DCE1EA;
                border-radius: 14px;
            }
            QLabel { color: #334155; font-size: 12px; }
            QPlainTextEdit, QLineEdit {
                background-color: #F8FAFC;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                padding: 6px 9px;
                font-size: 13px;
            }
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #E2E8F0;
                border-radius: 7px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #E2E8F0; }
            """
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(9)

        top = QHBoxLayout()
        hdr = QLabel("截图翻译")
        hdr.setStyleSheet("color: #0F172A; font-weight: 700; font-size: 14px;")
        top.addWidget(hdr)
        top.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.close)
        top.addWidget(btn_close)
        lay.addLayout(top)

        self.orig_box = QLineEdit(original)
        lay.addWidget(self.orig_box)

        self.trans_box = QPlainTextEdit(translated)
        self.trans_box.setFixedHeight(72)
        lay.addWidget(self.trans_box)

        actions = QHBoxLayout()
        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.trans_box.toPlainText().strip()))
        btn_re = QPushButton("重译")
        btn_re.clicked.connect(lambda: self.retranslate_requested.emit(self.orig_box.text().strip()))
        btn_sync = QPushButton("显示到字幕")
        btn_sync.setStyleSheet(
            "background-color: #2563EB; color: #FFFFFF; border: 1px solid #2563EB; border-radius: 7px; font-weight: 600;"
        )
        btn_sync.clicked.connect(self._sync_lyrics)
        actions.addWidget(btn_copy)
        actions.addWidget(btn_re)
        actions.addStretch()
        actions.addWidget(btn_sync)
        lay.addLayout(actions)

        scr = QGuiApplication.screenAt(anchor_rect.center()) or QGuiApplication.primaryScreen()
        s_geo = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
        x = min(max(s_geo.left() + 10, anchor_rect.left()), s_geo.right() - self.width() - 10)
        y = anchor_rect.bottom() + 10
        if y + self.height() > s_geo.bottom():
            y = max(s_geo.top() + 10, anchor_rect.top() - self.height() - 10)
        self.move(x, y)

    def update_translation(self, translated: str) -> None:
        self.trans_box.setPlainText(translated)

    def _sync_lyrics(self) -> None:
        self.apply_to_lyrics.emit(self.orig_box.text().strip(), self.trans_box.toPlainText().strip())
        self.close()


class FloatingQuickPanel(QWidget):
    """
    Minimalist Light Horizontal Floating Capsule Bar:
    Clean warm-white pill bar with crisp 2-word buttons and 1-click collapse to a tiny '轻译' pill.
    """

    act_snip = Signal()
    act_mark_region = Signal()
    act_toggle_live_screen = Signal()
    act_toggle_audio = Signal()
    act_switch_audio_src = Signal(str)
    act_toggle_lock = Signal()
    act_edit_sub = Signal()
    act_cycle_skin = Signal()
    act_open_main = Signal(int)

    def __init__(self, cfg_mgr: ConfigManager) -> None:
        super().__init__(None)
        self.cfg_mgr = cfg_mgr
        self._collapsed = False
        self._dragging = False
        self._drag_offset = QPoint()

        self.setWindowTitle("轻译悬浮工具条")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._root_lay = QHBoxLayout(self)
        self._root_lay.setContentsMargins(4, 4, 4, 4)

        # Collapsed minimal white pill
        self.ball_btn = QPushButton("轻译")
        self.ball_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ball_btn.setToolTip("点击展开悬浮控制条")
        self.ball_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 242);
                color: #2563EB;
                border: 1px solid #CBD5E1;
                border-radius: 15px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #EFF6FF; }
            """
        )
        self.ball_btn.clicked.connect(lambda: self.set_collapsed(False))
        self.ball_btn.hide()
        self._root_lay.addWidget(self.ball_btn)

        # Expanded sleek single-line capsule
        self.card = QFrame()
        self.card.setObjectName("lightCapsule")
        self.card.setStyleSheet(
            """
            QFrame#lightCapsule {
                background-color: rgba(255, 255, 255, 245);
                border: 1px solid #DCE1EA;
                border-radius: 19px;
            }
            QPushButton {
                background: transparent;
                color: #334155;
                border: none;
                border-radius: 13px;
                padding: 5px 11px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #F1F5F9;
                color: #0F172A;
            }
            """
        )
        c_lay = QHBoxLayout(self.card)
        c_lay.setContentsMargins(10, 4, 10, 4)
        c_lay.setSpacing(3)

        grip = QLabel("⋮⋮")
        grip.setStyleSheet("color: #94A3B8; font-size: 12px; padding: 0 3px;")
        c_lay.addWidget(grip)

        self.btn_snip = QPushButton("截图")
        self.btn_snip.clicked.connect(self.act_snip.emit)

        self.btn_region = QPushButton("框选")
        self.btn_region.clicked.connect(self.act_mark_region.emit)

        self.btn_live_screen = QPushButton("区域翻译")
        self.btn_live_screen.clicked.connect(self.act_toggle_live_screen.emit)

        self.btn_live_audio = QPushButton("声音翻译")
        self.btn_live_audio.clicked.connect(self.act_toggle_audio.emit)

        self.btn_lock = QPushButton("穿透")
        self.btn_lock.clicked.connect(self.act_toggle_lock.emit)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #E2E8F0;")

        btn_main = QPushButton("面板")
        btn_main.clicked.connect(lambda: self.act_open_main.emit(0))

        btn_min = QPushButton("收起")
        btn_min.setStyleSheet("color: #64748B;")
        btn_min.clicked.connect(lambda: self.set_collapsed(True))

        for w in (self.btn_snip, self.btn_region, self.btn_live_screen, self.btn_live_audio, self.btn_lock, sep, btn_main, btn_min):
            c_lay.addWidget(w)

        self._root_lay.addWidget(self.card)
        self.adjustSize()

        scr = QGuiApplication.primaryScreen()
        s_geo = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
        self.move(s_geo.right() - self.width() - 32, s_geo.top() + 28)
        self.sync_state(False, False, self.cfg_mgr.config.style.locked_click_through)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        set_exclude_from_capture(int(self.winId()), True)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self.card.setVisible(not collapsed)
        self.ball_btn.setVisible(collapsed)
        self.adjustSize()

    def sync_state(self, screen_running: bool, audio_running: bool, sub_locked: bool) -> None:
        active_pill = "background-color: #DBEAFE; color: #1D4ED8;"
        warn_pill = "background-color: #FEF3C7; color: #B45309;"

        self.btn_live_screen.setText("停止盯屏" if screen_running else "区域翻译")
        self.btn_live_screen.setStyleSheet(active_pill if screen_running else "")

        self.btn_live_audio.setText("停止听译" if audio_running else "声音翻译")
        self.btn_live_audio.setStyleSheet(active_pill if audio_running else "")

        self.btn_lock.setText("解锁字幕" if sub_locked else "穿透")
        self.btn_lock.setStyleSheet(warn_pill if sub_locked else "")
        self.adjustSize()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)
