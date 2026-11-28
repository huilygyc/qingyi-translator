"""Clean Light-Themed Overlays: Floating Lyrics Bar, Minimalist Floating Capsule, Inline Editor & Region Selector."""

from __future__ import annotations

import math
import re
import threading
import time
from typing import Dict, List, Optional, Tuple

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
from .win32_utils import (
    FastWin32ScreenCapturer,
    is_alt_key_pressed,
    logical_rect_to_physical,
    qt_key_event_to_hotkey_str,
    set_exclude_from_capture,
    set_window_click_through,
)


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


def _find_highlight_spans(text: str, terms: Optional[List[str]]) -> List[Tuple[int, int]]:
    """Finds non-overlapping character spans matching glossary target names for subtle accent highlighting."""
    if not text or not terms:
        return []
    uniq = sorted({t.strip() for t in terms if t and len(t.strip()) >= 2}, key=len, reverse=True)[:60]
    if not uniq:
        return []
    pattern = "|".join(re.escape(t) for t in uniq)
    return [(m.start(), m.end()) for m in re.finditer(pattern, text)]


def draw_styled_lyrics_line(
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
    opacity: float = 1.0,
    highlight_terms: Optional[List[str]] = None,
    highlight_color: Optional[QColor] = None,
) -> None:
    """Renders cinema/lyrics typography with soft shadow, round vector stroke, vertical gradient, and optional glossary highlights."""
    if not text or opacity <= 0.01:
        return
    painter.save()
    if opacity < 0.999:
        painter.setOpacity(painter.opacity() * max(0.0, min(1.0, opacity)))

    path = QPainterPath()
    path.addText(baseline, font, text)

    # Precompute vector outline path once (reused by soft shadow + stroke for 5x faster repaints!)
    outline_path = None
    if stroke_w > 0.15:
        stroker = QPainterPathStroker()
        stroker.setWidth(stroke_w * 2.0)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        outline_path = stroker.createStroke(path)

    # Soft multi-offset shadow reusing outline_path
    if shadow_alpha > 0:
        painter.setPen(Qt.PenStyle.NoPen)
        base_shadow = outline_path if outline_path is not None else path
        for dx, dy, factor in (
            (0.0, 2.2, 0.24),
            (1.6, 2.8, 0.44),
            (-0.8, 1.4, 0.20),
        ):
            a = int(min(255, max(0, shadow_alpha * factor)))
            if a <= 2:
                continue
            painter.setBrush(QColor(0, 0, 0, a))
            painter.drawPath(base_shadow.translated(dx, dy))

    # Crisp vector outer stroke
    if outline_path is not None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(stroke_col)
        painter.drawPath(outline_path)

    # Vertical linear gradient fill
    grad = QLinearGradient(0.0, baseline.y() - ascent, 0.0, baseline.y() + descent)
    grad.setColorAt(0.0, col_top)
    grad.setColorAt(1.0, col_bot)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(grad)
    painter.drawPath(path)

    # Optional subtle glossary character/term accent highlight via kerning-exact clip overfill
    spans = _find_highlight_spans(text, highlight_terms)
    if spans:
        fm = QFontMetricsF(font)
        # Pick complementary soft highlight tint (champagne gold on cool/white themes; ice-sky on warm yellow theme)
        if highlight_color is None:
            is_warm_main = col_bot.red() > 235 and col_bot.blue() < 185
            hl_col = QColor("#7DD3FC") if is_warm_main else QColor("#FDE68A")
        else:
            hl_col = highlight_color
        painter.setBrush(hl_col)
        for s_idx, e_idx in spans:
            x0 = baseline.x() + fm.horizontalAdvance(text[:s_idx])
            x1 = baseline.x() + fm.horizontalAdvance(text[:e_idx])
            clip_r = QRectF(x0 - 0.5, baseline.y() - ascent - 3.0, max(2.0, x1 - x0 + 1.0), ascent + descent + 6.0)
            painter.save()
            painter.setClipRect(clip_r)
            painter.drawPath(path)
            painter.restore()

    painter.restore()


class LyricsVectorPreviewWidget(QWidget):
    """True WYSIWYG vector subtitle preview rendered over a dark-to-bright anime-like backdrop."""

    def __init__(self, cfg_mgr: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg_mgr = cfg_mgr
        self.setFixedHeight(114)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, 12.0, 12.0)
        p.setClipPath(clip)

        # Split dark-to-bright slate backdrop so user can judge readability on both dark & bright frames
        bg = QLinearGradient(0.0, 0.0, r.width(), r.height())
        bg.setColorAt(0.0, QColor("#1E293B"))
        bg.setColorAt(0.55, QColor("#475569"))
        bg.setColorAt(1.0, QColor("#CBD5E1"))
        p.fillRect(r, bg)

        st = self.cfg_mgr.config.style
        px = min(27, max(16, int(st.base_font_size * 0.82)))
        f_main = QFont(st.font_family)
        f_main.setPixelSize(px)
        f_main.setWeight(QFont.Weight.Bold if st.font_weight >= 650 else QFont.Weight.DemiBold)
        fm_m = QFontMetricsF(f_main)
        hl_terms = list(self.cfg_mgr.glossary.values()) if st.highlight_glossary else None

        if st.display_mode == "danmaku":
            chips = [
                ("上一句：这个魔法真是太漂亮了", 0.58),
                ("当前句：我们快点出发吧，芙莉莲！", 1.0),
            ]
            f_dm = QFont(st.font_family)
            f_dm.setPixelSize(max(14, int(px * 0.82)))
            f_dm.setWeight(QFont.Weight.Bold)
            fm_d = QFontMetricsF(f_dm)
            y_bot = r.height() - 14.0
            for txt, op in reversed(chips):
                tw = fm_d.horizontalAdvance(txt)
                ch_h = fm_d.height() + 12.0
                ch_w = tw + 28.0
                pill = QRectF((r.width() - ch_w) / 2.0, y_bot - ch_h, ch_w, ch_h)
                p.save()
                p.setOpacity(op)
                bg_c = QColor(st.bg_color)
                bg_c.setAlpha(max(135, int(st.bg_opacity)))
                p.setPen(QPen(QColor(255, 255, 255, 42), 1.0))
                p.setBrush(bg_c)
                p.drawRoundedRect(pill, ch_h / 2.0, ch_h / 2.0)
                draw_styled_lyrics_line(
                    p,
                    txt,
                    f_dm,
                    QPointF(pill.center().x() - tw / 2.0, pill.top() + (ch_h - fm_d.height()) / 2.0 + fm_d.ascent()),
                    fm_d.ascent(),
                    fm_d.descent(),
                    QColor(st.color_top),
                    QColor(st.color_bottom),
                    QColor(st.stroke_color),
                    min(2.4, float(st.stroke_width)),
                    int(st.shadow_opacity * 0.7),
                    highlight_terms=hl_terms,
                )
                p.restore()
                y_bot -= ch_h + 8.0
            return

        main_txt = "芙莉莲，这个魔法真的很漂亮！"
        orig_txt = "フリーレン、この魔法は本当に綺麗だね！" if st.bilingual else ""
        prev_txt = "上一句：那我们继续向北出发吧" if st.keep_prev_line else ""

        f_orig = QFont(st.font_family)
        f_orig.setPixelSize(max(11, int(px * 0.56)))
        f_orig.setWeight(QFont.Weight.DemiBold)
        fm_o = QFontMetricsF(f_orig)

        f_prev = QFont(st.font_family)
        f_prev.setPixelSize(max(12, int(px * 0.64)))
        f_prev.setWeight(QFont.Weight.DemiBold)
        fm_p = QFontMetricsF(f_prev)

        main_w = fm_m.horizontalAdvance(main_txt)
        orig_w = fm_o.horizontalAdvance(orig_txt) if orig_txt else 0.0
        prev_w = fm_p.horizontalAdvance(prev_txt) if prev_txt else 0.0

        active_h = fm_m.height() + (fm_o.height() + 4.0 if orig_txt else 0.0)
        prev_h = (fm_p.height() + 6.0) if prev_txt else 0.0
        if st.anchor_bottom:
            active_top = r.height() - active_h - 14.0
        else:
            active_top = (r.height() - active_h) / 2.0 + (prev_h * 0.3)

        eff_bg = int(st.bg_opacity)
        if eff_bg > 0:
            bg_c = QColor(st.bg_color)
            bg_c.setAlpha(eff_bg)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg_c)
            if st.fit_bg_to_text:
                max_w = max(main_w, orig_w)
                pill = QRectF((r.width() - max_w) / 2.0 - 18.0, active_top - 6.0, max_w + 36.0, active_h + 12.0)
                p.drawRoundedRect(pill, float(st.bg_radius), float(st.bg_radius))
            else:
                p.drawRoundedRect(QRectF(14.0, active_top - 6.0, r.width() - 28.0, active_h + 12.0), float(st.bg_radius), float(st.bg_radius))

        if prev_txt:
            prev_y = active_top - prev_h - (8.0 if eff_bg > 0 else 1.0)
            draw_styled_lyrics_line(
                p,
                prev_txt,
                f_prev,
                QPointF((r.width() - prev_w) / 2.0, prev_y + fm_p.ascent()),
                fm_p.ascent(),
                fm_p.descent(),
                QColor("#E2E8F0"),
                QColor("#CBD5E1"),
                QColor(st.stroke_color),
                max(1.4, float(st.stroke_width) * 0.55),
                int(st.shadow_opacity * 0.65),
                opacity=0.62,
            )

        cur_y = active_top
        orig_first = bool(orig_txt) and st.bilingual_order == "orig_top"

        def _draw_prev_orig(y0: float) -> float:
            oc = QColor(st.orig_color)
            draw_styled_lyrics_line(
                p,
                orig_txt,
                f_orig,
                QPointF((r.width() - orig_w) / 2.0, y0 + fm_o.ascent()),
                fm_o.ascent(),
                fm_o.descent(),
                oc,
                oc,
                QColor(st.stroke_color),
                max(1.4, float(st.stroke_width) * 0.60),
                int(st.shadow_opacity * 0.80),
            )
            return y0 + fm_o.height() + 4.0

        def _draw_prev_main(y0: float) -> float:
            draw_styled_lyrics_line(
                p,
                main_txt,
                f_main,
                QPointF((r.width() - main_w) / 2.0, y0 + fm_m.ascent()),
                fm_m.ascent(),
                fm_m.descent(),
                QColor(st.color_top),
                QColor(st.color_bottom),
                QColor(st.stroke_color),
                float(st.stroke_width) * 0.85,
                int(st.shadow_opacity),
                highlight_terms=hl_terms,
            )
            return y0 + fm_m.height() + 4.0

        if orig_first:
            cur_y = _draw_prev_orig(cur_y)
            _draw_prev_main(cur_y)
        else:
            cur_y = _draw_prev_main(cur_y)
            if orig_txt:
                _draw_prev_orig(cur_y)


class LyricsStyleStudioWidget(QWidget):
    """Clean, airy light-mode subtitle style customizer with true vector WYSIWYG live preview."""

    style_changed = Signal()
    request_align_region = Signal(bool)  # False = snap above region, True = cover original hard-subs
    request_reset_center = Signal()

    def __init__(self, cfg_mgr: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cfg_mgr = cfg_mgr
        self._updating_ui = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        # True Vector Live Preview Banner
        self.preview_canvas = LyricsVectorPreviewWidget(self.cfg_mgr, self)
        root.addWidget(self.preview_canvas)

        # Settings Card
        card = QFrame()
        card.setProperty("card", True)
        grid = QGridLayout(card)
        grid.setContentsMargins(20, 14, 20, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(11)

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
        self.size_val_lbl.setFixedWidth(44)
        self.size_slider.valueChanged.connect(self._on_any_changed)
        size_box.addWidget(self.size_slider, 1)
        size_box.addWidget(self.size_val_lbl)
        grid.addLayout(size_box, 1, 1)

        grid.addWidget(QLabel("底板透明"), 1, 2)
        bg_box = QHBoxLayout()
        self.bg_slider = QSlider(Qt.Orientation.Horizontal)
        self.bg_slider.setRange(0, 235)
        self.bg_lbl = QLabel("全透明")
        self.bg_lbl.setFixedWidth(52)
        self.bg_slider.valueChanged.connect(self._on_any_changed)
        bg_box.addWidget(self.bg_slider, 1)
        bg_box.addWidget(self.bg_lbl)
        grid.addLayout(bg_box, 1, 3)

        grid.addWidget(QLabel("描边粗细"), 2, 0)
        stroke_box = QHBoxLayout()
        self.stroke_slider = QSlider(Qt.Orientation.Horizontal)
        self.stroke_slider.setRange(0, 65)
        self.stroke_val_lbl = QLabel("3.4 px")
        self.stroke_val_lbl.setFixedWidth(44)
        self.stroke_slider.valueChanged.connect(self._on_any_changed)
        stroke_box.addWidget(self.stroke_slider, 1)
        stroke_box.addWidget(self.stroke_val_lbl)
        grid.addLayout(stroke_box, 2, 1)

        grid.addWidget(QLabel("柔光阴影"), 2, 2)
        self.shadow_slider = QSlider(Qt.Orientation.Horizontal)
        self.shadow_slider.setRange(0, 230)
        self.shadow_slider.valueChanged.connect(self._on_any_changed)
        grid.addWidget(self.shadow_slider, 2, 3)

        grid.addWidget(QLabel("显示模式"), 3, 0)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("标准字幕（影院双句）", "subtitle")
        self.mode_combo.addItem("轻量弹幕流（上浮气泡）", "danmaku")
        self.mode_combo.currentIndexChanged.connect(self._on_any_changed)
        grid.addWidget(self.mode_combo, 3, 1)

        grid.addWidget(QLabel("双语顺序"), 3, 2)
        self.bi_order_combo = QComboBox()
        self.bi_order_combo.addItem("译文在上 · 原文在下", "trans_top")
        self.bi_order_combo.addItem("原文在上 · 译文在下", "orig_top")
        self.bi_order_combo.currentIndexChanged.connect(self._on_any_changed)
        grid.addWidget(self.bi_order_combo, 3, 3)

        grid.addWidget(QLabel("快捷定位"), 4, 0)
        align_row = QHBoxLayout()
        align_row.setSpacing(8)
        btn_above = QPushButton("贴合原字幕上方")
        btn_above.setToolTip("自动对齐到已框选原字幕区域的正上方")
        btn_above.clicked.connect(lambda: self.request_align_region.emit(False))
        btn_cover = QPushButton("遮盖原硬字幕")
        btn_cover.setToolTip("直接覆盖在原硬字幕上方并自动开启防重复识别底板")
        btn_cover.clicked.connect(lambda: self.request_align_region.emit(True))
        btn_center = QPushButton("复位底部居中")
        btn_center.setToolTip("重置悬浮字幕到主屏底部正中央")
        btn_center.clicked.connect(self.request_reset_center.emit)
        align_row.addWidget(btn_above)
        align_row.addWidget(btn_cover)
        align_row.addWidget(btn_center)
        align_row.addStretch()
        grid.addLayout(align_row, 4, 1, 1, 3)

        grid.addWidget(QLabel("颜色配置"), 5, 0)
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
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
        grid.addLayout(color_row, 5, 1, 1, 3)

        toggles_1 = QHBoxLayout()
        toggles_1.setSpacing(16)
        self.auto_scale_chk = QCheckBox("长句自动缩放")
        self.bilingual_chk = QCheckBox("显示双语对照")
        self.keep_prev_chk = QCheckBox("保留上一句防漏看")
        self.hl_glossary_chk = QCheckBox("词表角色名高亮")
        for chk in (self.auto_scale_chk, self.bilingual_chk, self.keep_prev_chk, self.hl_glossary_chk):
            chk.toggled.connect(self._on_any_changed)
            toggles_1.addWidget(chk)
        toggles_1.addStretch()
        grid.addLayout(toggles_1, 6, 0, 1, 4)

        toggles_2 = QHBoxLayout()
        toggles_2.setSpacing(16)
        self.fit_bg_chk = QCheckBox("底板贴合文字")
        self.anchor_bot_chk = QCheckBox("底部锚定防跳动")
        self.auto_contrast_chk = QCheckBox("亮画面自动补底板")
        self.alt_unlock_chk = QCheckBox("穿透时按住 Alt 交互")
        for chk in (self.fit_bg_chk, self.anchor_bot_chk, self.auto_contrast_chk, self.alt_unlock_chk):
            chk.toggled.connect(self._on_any_changed)
            toggles_2.addWidget(chk)
        toggles_2.addStretch()
        grid.addLayout(toggles_2, 7, 0, 1, 4)

        toggles_3 = QHBoxLayout()
        self.exclude_chk = QCheckBox("防重复识别（开启后悬浮字幕可直接盖住原外语字幕，不影响 OCR 抓词）")
        self.exclude_chk.toggled.connect(self._on_any_changed)
        toggles_3.addWidget(self.exclude_chk)
        toggles_3.addStretch()
        grid.addLayout(toggles_3, 8, 0, 1, 4)

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
        m_idx = self.mode_combo.findData(st.display_mode)
        if m_idx >= 0:
            self.mode_combo.setCurrentIndex(m_idx)
        bo_idx = self.bi_order_combo.findData(st.bilingual_order)
        if bo_idx >= 0:
            self.bi_order_combo.setCurrentIndex(bo_idx)
        self.size_slider.setValue(int(st.base_font_size))
        self.size_val_lbl.setText(f"{int(st.base_font_size)} px")
        self.auto_scale_chk.setChecked(bool(st.auto_scale_font))
        self.bilingual_chk.setChecked(bool(st.bilingual))
        self.keep_prev_chk.setChecked(bool(st.keep_prev_line))
        self.hl_glossary_chk.setChecked(bool(st.highlight_glossary))
        self.fit_bg_chk.setChecked(bool(st.fit_bg_to_text))
        self.anchor_bot_chk.setChecked(bool(st.anchor_bottom))
        self.auto_contrast_chk.setChecked(bool(st.auto_contrast_bg))
        self.alt_unlock_chk.setChecked(bool(st.alt_temp_unlock))
        self.stroke_slider.setValue(int(round(float(st.stroke_width) * 10)))
        self.stroke_val_lbl.setText(f"{float(st.stroke_width):.1f} px")
        self.shadow_slider.setValue(int(st.shadow_opacity))
        self.bg_slider.setValue(int(st.bg_opacity))
        self._update_bg_label(int(st.bg_opacity))
        self.exclude_chk.setChecked(bool(st.exclude_from_capture))
        self._refresh_color_buttons()
        self.preview_canvas.update()
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
                f"background-color: {hex_col}; color: {fg}; border: 1px solid #CBD5E1; border-radius: 7px; padding: 5px 9px; font-weight: 600;"
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
            self.preview_canvas.update()
            self.style_changed.emit()

    def _on_any_changed(self) -> None:
        if self._updating_ui:
            return
        st = self.cfg_mgr.config.style
        st.font_family = self.font_combo.currentText()
        st.display_mode = str(self.mode_combo.currentData() or "subtitle")
        st.bilingual_order = str(self.bi_order_combo.currentData() or "trans_top")
        st.base_font_size = int(self.size_slider.value())
        self.size_val_lbl.setText(f"{st.base_font_size} px")
        st.auto_scale_font = self.auto_scale_chk.isChecked()
        st.bilingual = self.bilingual_chk.isChecked()
        st.keep_prev_line = self.keep_prev_chk.isChecked()
        st.highlight_glossary = self.hl_glossary_chk.isChecked()
        st.fit_bg_to_text = self.fit_bg_chk.isChecked()
        st.anchor_bottom = self.anchor_bot_chk.isChecked()
        st.auto_contrast_bg = self.auto_contrast_chk.isChecked()
        st.alt_temp_unlock = self.alt_unlock_chk.isChecked()
        st.stroke_width = round(self.stroke_slider.value() / 10.0, 1)
        self.stroke_val_lbl.setText(f"{st.stroke_width:.1f} px")
        st.shadow_opacity = int(self.shadow_slider.value())
        st.bg_opacity = int(self.bg_slider.value())
        self._update_bg_label(st.bg_opacity)
        st.exclude_from_capture = self.exclude_chk.isChecked()
        self.cfg_mgr.save()
        self.preview_canvas.update()
        self.style_changed.emit()


class LyricsSubtitleWindow(QWidget):
    """
    Cinema/Desktop-Lyrics Floating Subtitle & Lightweight Danmaku Overlay:
    - Smooth fade-in/out + upward glide + streaming voice breathing indicator
    - Auto-contrast backdrop on bright scenes + fit-content capsule + bottom-anchored layout
    - Inline history scrubbing (‹ › & Shift+Wheel) + magnetic horizontal center snap + hold-Alt temp unlock
    - Bilingual top/bottom swap + non-truncated 2-line original wrap + glossary character highlight
    """

    request_edit = Signal()
    request_open_style = Signal()
    request_snip = Signal()
    request_mark_region = Signal()
    request_open_panel = Signal()
    lock_state_changed = Signal(bool)
    _luma_sampled = Signal(float)

    def __init__(self, cfg_mgr: ConfigManager) -> None:
        super().__init__(None)
        self.cfg_mgr = cfg_mgr
        self._original_text = "Subtitles ready"
        self._translated_text = "悬浮字幕已就绪，框选区域或截图即可开始翻译"
        self._prev_translated_text = ""
        self._prev_opacity = 0.0
        self._danmaku_items: List[Dict[str, object]] = []
        self._history_ring: List[Tuple[str, str]] = []
        self._browse_idx: int = -1  # -1 = live latest; >= 0 = scrubbing history
        self._toast_text = ""

        self._hovered = False
        self._auto_hidden = False
        self._frozen = False
        self._is_preview = False
        self._preview_phase = 0.0
        self._temp_unlocked = False
        self._snap_center_guide = False
        self._dragging = False
        self._resizing = False
        self._drag_offset = QPoint()
        self._resize_origin_pos = QPoint()
        self._resize_origin_size = self.size()

        # Smooth animation & auto-contrast state (timer stops when idle so 0% CPU)
        self._cur_opacity = 1.0
        self._target_opacity = 1.0
        self._slide_offset = 0.0
        self._prev_target_opacity = 0.0
        self._auto_bg_alpha = 0.0
        self._target_auto_bg_alpha = 0.0
        self._luma_busy = False

        self.setWindowTitle("轻译悬浮字幕")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setMinimumSize(440, 122)

        self._init_geometry()
        self._build_hover_toolbar()
        self._luma_sampled.connect(self._on_luma_sampled)

        self._hide_bar_timer = QTimer(self)
        self._hide_bar_timer.setSingleShot(True)
        self._hide_bar_timer.timeout.connect(self._check_leave_hover)

        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(self._clear_toast)

        self._auto_hide_timer = QTimer(self)
        self._auto_hide_timer.setSingleShot(True)
        self._auto_hide_timer.timeout.connect(self._on_auto_hide_timeout)

        self._prev_clear_timer = QTimer(self)
        self._prev_clear_timer.setSingleShot(True)
        self._prev_clear_timer.timeout.connect(self._fade_out_prev_line)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(25)
        self._anim_timer.timeout.connect(self._step_animation)

        # Ultra-light 850ms backdrop brightness sampler (reads <150px behind overlay via WDA-invisible capture)
        self._luma_timer = QTimer(self)
        self._luma_timer.setInterval(850)
        self._luma_timer.timeout.connect(self._schedule_luma_sample)
        self._luma_timer.start()

        # Lightweight hold-Alt temporary unlock watcher (only runs while click-through lock is active!)
        self._alt_timer = QTimer(self)
        self._alt_timer.setInterval(110)
        self._alt_timer.timeout.connect(self._poll_alt_temp_unlock)

    def _is_interaction_locked(self) -> bool:
        return bool(self.cfg_mgr.config.style.locked_click_through) and not self._temp_unlocked

    def _init_geometry(self) -> None:
        st = self.cfg_mgr.config.style
        screen = QGuiApplication.primaryScreen()
        s_geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        w = max(460, min(st.overlay_width, s_geo.width() - 60))
        h = max(136, min(st.overlay_height, 360))
        if st.overlay_x < 0 or st.overlay_y < 0:
            x = s_geo.x() + (s_geo.width() - w) // 2
            y = s_geo.y() + s_geo.height() - h - 50
        else:
            x, y = st.overlay_x, st.overlay_y
            # Multi-monitor / resolution-change off-screen guard
            union = QRect()
            for scr in QGuiApplication.screens():
                union = union.united(scr.availableGeometry())
            if not union.isNull() and not union.intersects(QRect(x + 40, y + 20, max(40, w - 80), max(40, h - 40))):
                x = s_geo.x() + (s_geo.width() - w) // 2
                y = s_geo.y() + s_geo.height() - h - 50
        self.setGeometry(x, y, w, h)

    def reset_position_center(self) -> None:
        """Resets subtitle cleanly to primary screen bottom horizontal center."""
        st = self.cfg_mgr.config.style
        screen = QGuiApplication.primaryScreen()
        s_geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        w = max(460, min(self.width(), s_geo.width() - 60))
        h = max(136, min(self.height(), 360))
        x = s_geo.x() + (s_geo.width() - w) // 2
        y = s_geo.y() + s_geo.height() - h - 50
        self.setGeometry(x, y, w, h)
        st.overlay_x, st.overlay_y, st.overlay_width, st.overlay_height = x, y, w, h
        self.cfg_mgr.save()
        self.show_toast("字幕已复位到底部居中", 1500)
        self.update()

    def _build_hover_toolbar(self) -> None:
        self.toolbar = QFrame(self)
        self.toolbar.setObjectName("lyricsHoverBar")
        self.toolbar.setStyleSheet(
            """
            QFrame#lyricsHoverBar {
                background-color: rgba(255, 255, 255, 242);
                border: 1px solid #CBD5E1;
                border-radius: 13px;
            }
            QPushButton {
                background: transparent;
                color: #334155;
                border: none;
                border-radius: 7px;
                padding: 3px 8px;
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
        bar_lay.setContentsMargins(8, 3, 8, 3)
        bar_lay.setSpacing(2)

        btn_prev_hist = QPushButton("‹")
        btn_prev_hist.setToolTip("回看上一句历史台词（也可 Shift + 滚轮）")
        btn_prev_hist.setFixedWidth(24)
        btn_prev_hist.clicked.connect(lambda: self._browse_history(-1))

        btn_next_hist = QPushButton("›")
        btn_next_hist.setToolTip("前进到下一句或恢复最新")
        btn_next_hist.setFixedWidth(24)
        btn_next_hist.clicked.connect(lambda: self._browse_history(1))

        self.btn_back_live = QPushButton("回最新")
        self.btn_back_live.setStyleSheet("background-color: #EFF6FF; color: #2563EB;")
        self.btn_back_live.clicked.connect(self._exit_history_browse)
        self.btn_back_live.hide()

        btn_copy = QPushButton("复制")
        btn_copy.setToolTip("复制当前译文（也可右键单击字幕）")
        btn_copy.clicked.connect(self.copy_current_subtitle)

        self.btn_freeze = QPushButton("冻住")
        self.btn_freeze.setToolTip("冻结当前字幕，防止下一句顶掉")
        self.btn_freeze.clicked.connect(self.toggle_frozen)

        btn_bi = QPushButton("双语")
        btn_bi.clicked.connect(self._toggle_bilingual)

        btn_preset = QPushButton("主题")
        btn_preset.clicked.connect(self._cycle_preset)

        btn_edit = QPushButton("改词")
        btn_edit.clicked.connect(self.request_edit.emit)

        btn_lock = QPushButton("穿透")
        btn_lock.setToolTip("开启鼠标穿透（锁定后按住 Alt 可临时唤醒交互）")
        btn_lock.clicked.connect(lambda: self.set_locked(True))

        btn_panel = QPushButton("面板")
        btn_panel.clicked.connect(self.request_open_panel.emit)

        btn_hide = QPushButton("隐藏")
        btn_hide.clicked.connect(self.hide)

        for b in (
            btn_prev_hist,
            btn_next_hist,
            self.btn_back_live,
            btn_copy,
            self.btn_freeze,
            btn_bi,
            btn_preset,
            btn_edit,
            btn_lock,
            btn_panel,
            btn_hide,
        ):
            bar_lay.addWidget(b)

        self.toolbar.adjustSize()
        self.toolbar.hide()

    def _browse_history(self, step: int) -> None:
        if not self._history_ring:
            self.show_toast("暂无历史台词可回看", 1100)
            return
        total = len(self._history_ring)
        if self._browse_idx < 0:
            if step > 0:
                return
            self._browse_idx = max(0, total - 2) if total >= 2 else 0
        else:
            nxt = self._browse_idx + step
            if nxt >= total:
                self._exit_history_browse()
                return
            self._browse_idx = max(0, nxt)

        orig, trans = self._history_ring[self._browse_idx]
        self._original_text = orig
        self._translated_text = trans
        self._is_preview = False
        self._auto_hidden = False
        self._cur_opacity = 1.0
        self._target_opacity = 1.0
        self._auto_hide_timer.stop()
        self.btn_back_live.setVisible(True)
        self._reposition_toolbar()
        self.show_toast(f"回看历史 {self._browse_idx + 1} / {total}", 1200)
        self.update()

    def _exit_history_browse(self) -> None:
        self._browse_idx = -1
        self.btn_back_live.setVisible(False)
        self._reposition_toolbar()
        if self._history_ring:
            orig, trans = self._history_ring[-1]
            self._original_text = orig
            self._translated_text = trans
        self._restart_auto_hide_timer()
        self.show_toast("已回到实时最新台词", 1100)
        self.update()

    def _poll_alt_temp_unlock(self) -> None:
        st = self.cfg_mgr.config.style
        if not st.locked_click_through or not st.alt_temp_unlock or not self.isVisible():
            if self._temp_unlocked:
                self._temp_unlocked = False
                set_window_click_through(int(self.winId()), bool(st.locked_click_through))
            self._alt_timer.stop()
            return

        alt_down = is_alt_key_pressed()
        cursor_near = self.geometry().adjusted(-24, -24, 24, 24).contains(QCursor.pos())
        if alt_down and cursor_near:
            if not self._temp_unlocked:
                self._temp_unlocked = True
                set_window_click_through(int(self.winId()), False)
                self._hovered = True
                self._auto_hidden = False
                self._target_opacity = 1.0
                self._ensure_anim_running()
                self._reposition_toolbar()
                self.toolbar.show()
                self.show_toast("已临时唤醒交互（松开 Alt 恢复穿透）", 1500)
                self.update()
        elif self._temp_unlocked and not alt_down and not self._dragging and not self._resizing:
            self._temp_unlocked = False
            self._hovered = False
            self.toolbar.hide()
            set_window_click_through(int(self.winId()), True)
            self._restart_auto_hide_timer()
            self.update()

    def _schedule_luma_sample(self) -> None:
        st = self.cfg_mgr.config.style
        if not st.auto_contrast_bg or not self.isVisible() or (self._auto_hidden and not self._hovered):
            if self._target_auto_bg_alpha > 0.0:
                self._target_auto_bg_alpha = 0.0
                self._ensure_anim_running()
            return
        if self._luma_busy:
            return
        # Sample only the lower subtitle strip (WDA_EXCLUDEFROMCAPTURE keeps our own overlay invisible!)
        geo = self.geometry()
        sample_rect = QRect(geo.x() + 24, geo.y() + max(36, geo.height() // 2), max(40, geo.width() - 48), max(24, geo.height() // 2 - 8))
        px, py, pw, ph, _ = logical_rect_to_physical(sample_rect)
        self._luma_busy = True

        def job() -> None:
            cap = FastWin32ScreenCapturer()
            try:
                bgr = cap.grab_bgr(px, py, pw, ph, max_side=24)
                if bgr is not None and bgr.size > 0:
                    # Fast Rec.601 average luminance (0..255) over tiny ~24x6 patch
                    luma = float(0.114 * bgr[:, :, 0].mean() + 0.587 * bgr[:, :, 1].mean() + 0.299 * bgr[:, :, 2].mean())
                    self._luma_sampled.emit(luma)
            finally:
                cap.close()
                self._luma_busy = False

        threading.Thread(target=job, daemon=True, name="SubLumaProbe").start()

    def _on_luma_sampled(self, luma: float) -> None:
        if not self.cfg_mgr.config.style.auto_contrast_bg:
            target = 0.0
        elif luma >= 152.0:
            # Bright snow / sky / white PPT scene -> smoothly bring in soft protective frosted dark pill
            target = min(162.0, 72.0 + (luma - 152.0) * 1.15)
        else:
            target = 0.0
        if abs(target - self._target_auto_bg_alpha) > 6.0:
            self._target_auto_bg_alpha = target
            self._ensure_anim_running()

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
        eff_locked = bool(st.locked_click_through) and not self._temp_unlocked
        set_window_click_through(hwnd, eff_locked)
        if st.locked_click_through and st.alt_temp_unlock:
            if not self._alt_timer.isActive():
                self._alt_timer.start()
        else:
            self._alt_timer.stop()
            self._temp_unlocked = False
        if eff_locked:
            self._hovered = False
            self.toolbar.hide()
        self.update()

    def snap_to_region(self, region_rect: QRect, cover: bool = False) -> None:
        """Smartly aligns overlay right above the marked subtitle zone OR directly masking hard-subs."""
        st = self.cfg_mgr.config.style
        screen = QGuiApplication.screenAt(region_rect.center()) or QGuiApplication.primaryScreen()
        s_geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        target_w = max(480, min(s_geo.width() - 40, max(region_rect.width() + 80, st.overlay_width)))
        target_x = max(s_geo.left() + 12, min(region_rect.center().x() - target_w // 2, s_geo.right() - target_w - 12))

        if cover:
            target_h = max(136, region_rect.height() + 48)
            target_y = max(s_geo.top() + 8, region_rect.bottom() - target_h + 10)
            st.bg_opacity = max(int(st.bg_opacity), 215)
            st.exclude_from_capture = True
            self.show_toast("已覆盖原硬字幕区（自动防重复识别）", 2000)
        else:
            target_h = max(150, self.height())
            target_y = max(s_geo.top() + 8, region_rect.top() - target_h + 4)
            self.show_toast("已贴合至原字幕正上方", 1800)

        self.setGeometry(target_x, target_y, target_w, target_h)
        st.overlay_x = self.x()
        st.overlay_y = self.y()
        st.overlay_width = self.width()
        st.overlay_height = self.height()
        self.cfg_mgr.save()
        self.apply_native_window_flags()
        self.update()

    def copy_current_subtitle(self) -> None:
        txt = self._translated_text.strip()
        if txt:
            QApplication.clipboard().setText(txt)
            self.show_toast("已复制译文", 1200)

    def toggle_frozen(self) -> None:
        self.set_frozen(not self._frozen)

    def set_frozen(self, frozen: bool) -> None:
        self._frozen = frozen
        if frozen:
            self._auto_hidden = False
            self._target_opacity = 1.0
            self._cur_opacity = 1.0
            self._auto_hide_timer.stop()
            self.btn_freeze.setText("已冻住")
            self.btn_freeze.setStyleSheet("background-color: #DBEAFE; color: #1D4ED8;")
            self.show_toast("字幕已冻住，新台词暂不覆盖", 1600)
        else:
            self.btn_freeze.setText("冻住")
            self.btn_freeze.setStyleSheet("")
            if self._browse_idx >= 0:
                self._exit_history_browse()
            else:
                self._restart_auto_hide_timer()
                self.show_toast("已恢复实时更新", 1200)
        self.update()

    def set_subtitle(self, original: str, translated: str, force: bool = False, is_preview: bool = False) -> None:
        new_orig = (original or "").strip()
        new_trans = (translated or "").strip()
        if not new_trans:
            return

        # Record final sentences into inline history ring even while user is scrubbing/frozen
        if not is_preview and not new_trans.startswith("悬浮字幕已就绪"):
            if not self._history_ring or self._history_ring[-1][1] != new_trans:
                self._history_ring.append((new_orig, new_trans))
                self._history_ring = self._history_ring[-25:]

        if (self._frozen or self._browse_idx >= 0) and not force:
            return

        if is_preview:
            # Smooth in-place streaming preview with subtle breathing indicator (no bounce, no history spam)
            self._original_text = new_orig
            self._translated_text = new_trans
            self._is_preview = True
            self._auto_hidden = False
            self._cur_opacity = 1.0
            self._target_opacity = 1.0
            self._slide_offset = 0.0
            self._ensure_anim_running()
            self._restart_auto_hide_timer()
            self.update()
            return

        old_trans = self._translated_text
        was_preview = self._is_preview
        self._is_preview = False
        is_placeholder = old_trans.startswith("悬浮字幕已就绪")
        if (
            new_trans != old_trans
            and old_trans
            and not is_placeholder
            and not was_preview
            and self.cfg_mgr.config.style.keep_prev_line
        ):
            self._prev_translated_text = old_trans
            self._prev_opacity = 0.62
            self._prev_target_opacity = 0.62
            self._prev_clear_timer.start(3200)

        self._original_text = new_orig
        self._translated_text = new_trans
        self._auto_hidden = False

        # Append to lightweight danmaku stream buffer
        now = time.monotonic()
        if not self._danmaku_items or self._danmaku_items[-1]["text"] != new_trans:
            self._danmaku_items.append({"text": new_trans, "orig": new_orig, "born": now})
            self._danmaku_items = self._danmaku_items[-3:]

        # Smooth 150ms fade-in + subtle upward glide (skip bounce when seamlessly finalizing a live preview)
        if was_preview:
            self._cur_opacity = 1.0
            self._slide_offset = 0.0
        else:
            self._cur_opacity = max(0.20, self._cur_opacity * 0.45) if self._cur_opacity > 0.1 else 0.05
            self._slide_offset = 7.0
        self._target_opacity = 1.0
        self._ensure_anim_running()
        self._restart_auto_hide_timer()
        self.update()

    def clear_for_empty_scene(self) -> None:
        if not self._hovered and not self._dragging and not self._frozen and self._browse_idx < 0 and self.cfg_mgr.config.auto_hide_seconds > 0:
            self._auto_hidden = True
            self._is_preview = False
            self._target_opacity = 0.0
            self._prev_target_opacity = 0.0
            self._ensure_anim_running()

    def _fade_out_prev_line(self) -> None:
        self._prev_target_opacity = 0.0
        self._ensure_anim_running()

    def _ensure_anim_running(self) -> None:
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _step_animation(self) -> None:
        changed = False
        if abs(self._cur_opacity - self._target_opacity) > 0.015:
            step = 0.16 if self._target_opacity > self._cur_opacity else 0.085
            if self._target_opacity > self._cur_opacity:
                self._cur_opacity = min(self._target_opacity, self._cur_opacity + step)
            else:
                self._cur_opacity = max(self._target_opacity, self._cur_opacity - step)
            changed = True
        else:
            self._cur_opacity = self._target_opacity

        if self._slide_offset > 0.25:
            self._slide_offset *= 0.62
            changed = True
        else:
            self._slide_offset = 0.0

        if abs(self._prev_opacity - self._prev_target_opacity) > 0.015:
            if self._prev_target_opacity < self._prev_opacity:
                self._prev_opacity = max(0.0, self._prev_opacity - 0.055)
            else:
                self._prev_opacity = min(self._prev_target_opacity, self._prev_opacity + 0.08)
            if self._prev_opacity <= 0.01:
                self._prev_translated_text = ""
            changed = True
        else:
            self._prev_opacity = self._prev_target_opacity

        # Smooth auto-contrast backdrop easing
        if abs(self._auto_bg_alpha - self._target_auto_bg_alpha) > 1.5:
            diff = self._target_auto_bg_alpha - self._auto_bg_alpha
            self._auto_bg_alpha += diff * 0.22
            changed = True
        else:
            self._auto_bg_alpha = self._target_auto_bg_alpha

        # Gentle breathing pulse while streaming voice preview is active
        if self._is_preview and self._cur_opacity > 0.05:
            self._preview_phase = (self._preview_phase + 0.16) % (math.pi * 2.0)
            changed = True

        self.update()
        if not changed:
            self._anim_timer.stop()

    def _restart_auto_hide_timer(self) -> None:
        sec = int(self.cfg_mgr.config.auto_hide_seconds)
        if sec > 0 and self._translated_text and not self._frozen and self._browse_idx < 0:
            self._auto_hide_timer.start(sec * 1000)
        else:
            self._auto_hide_timer.stop()

    def _on_auto_hide_timeout(self) -> None:
        if not self._hovered and not self._dragging and not self._frozen and self._browse_idx < 0 and self.cfg_mgr.config.auto_hide_seconds > 0:
            self._auto_hidden = True
            self._is_preview = False
            self._target_opacity = 0.0
            self._prev_target_opacity = 0.0
            self._ensure_anim_running()

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
            tip = "已开启鼠标穿透（按住 Alt 移到字幕上可临时交互）" if self.cfg_mgr.config.style.alt_temp_unlock else "已开启鼠标穿透，可在迷你悬浮条或主面板解锁"
            self.show_toast(tip, 2400)
        else:
            self._temp_unlocked = False
            self.show_toast("字幕已解锁（滚轮调字号 · Shift+滚轮翻历史）", 1800)
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

    def wheelEvent(self, event) -> None:
        if not self._is_interaction_locked():
            delta = event.angleDelta().y()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Shift + Mouse Wheel scrubs recent subtitle history inline!
                if delta > 0:
                    self._browse_history(-1)
                elif delta < 0:
                    self._browse_history(1)
            else:
                if delta > 0:
                    self._step_font(2)
                elif delta < 0:
                    self._step_font(-2)
            event.accept()
            return
        super().wheelEvent(event)

    def enterEvent(self, event) -> None:
        if not self._is_interaction_locked():
            self._hovered = True
            self._auto_hidden = False
            self._target_opacity = 1.0
            self._ensure_anim_running()
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
            self._restart_auto_hide_timer()
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and not self._is_interaction_locked():
            self.request_edit.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event) -> None:
        if self._is_interaction_locked():
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.copy_current_subtitle()
            event.accept()
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
        if self._is_interaction_locked():
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
            raw_pt = event.globalPosition().toPoint() - self._drag_offset
            nx, ny = raw_pt.x(), raw_pt.y()
            # Magnetic horizontal center snap (±18 px)
            scr = QGuiApplication.screenAt(event.globalPosition().toPoint()) or QGuiApplication.primaryScreen()
            if scr is not None:
                s_geo = scr.availableGeometry()
                center_x = s_geo.x() + (s_geo.width() - self.width()) // 2
                if abs(nx - center_x) <= 18:
                    nx = center_x
                    self._snap_center_guide = True
                else:
                    self._snap_center_guide = False
            self.move(nx, ny)
            self.update()
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
            self._snap_center_guide = False
            st = self.cfg_mgr.config.style
            st.overlay_x = self.x()
            st.overlay_y = self.y()
            st.overlay_width = self.width()
            st.overlay_height = self.height()
            self.cfg_mgr.save()
            self.update()
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
        top_pad = 36.0
        content_rect = QRectF(14.0, top_pad, max(80.0, self.width() - 28.0), max(54.0, self.height() - top_pad - 8.0))

        if self._hovered and not self._is_interaction_locked():
            hover_pen = QPen(QColor(59, 130, 246, 135), 1.2, Qt.PenStyle.DashLine)
            painter.setPen(hover_pen)
            painter.setBrush(QColor(255, 255, 255, 22))
            painter.drawRoundedRect(content_rect, float(st.bg_radius), float(st.bg_radius))
            grip_pen = QPen(QColor(59, 130, 246, 180), 1.6)
            painter.setPen(grip_pen)
            w, h = self.width(), self.height()
            painter.drawLine(w - 16, h - 6, w - 6, h - 16)
            painter.drawLine(w - 11, h - 6, w - 6, h - 11)

        # Tactile blue dashed vertical center snap guideline while dragging to screen center
        if self._snap_center_guide and self._dragging:
            cx = self.width() / 2.0
            painter.setPen(QPen(QColor(59, 130, 246, 200), 1.6, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(cx, top_pad), QPointF(cx, self.height() - 6.0))

        if self._cur_opacity > 0.01 or self._hovered:
            draw_op = 1.0 if self._hovered else self._cur_opacity
            if st.display_mode == "danmaku":
                self._paint_danmaku_mode(painter, content_rect, draw_op)
            else:
                self._paint_subtitle_mode(painter, content_rect, draw_op)

        if self._toast_text:
            t_font = QFont(st.font_family, 10, QFont.Weight.DemiBold)
            fm_t = QFontMetricsF(t_font)
            tw = fm_t.horizontalAdvance(self._toast_text) + 24.0
            th = fm_t.height() + 10.0
            t_rect = QRectF((self.width() - tw) / 2.0, self.height() - th - 4.0, tw, th)
            painter.setPen(QPen(QColor("#CBD5E1"), 1.0))
            painter.setBrush(QColor(255, 255, 255, 242))
            painter.drawRoundedRect(t_rect, 10.0, 10.0)
            painter.setFont(t_font)
            painter.setPen(QColor("#1E293B"))
            painter.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, self._toast_text)

    def _paint_danmaku_mode(self, painter: QPainter, content_rect: QRectF, draw_op: float) -> None:
        st = self.cfg_mgr.config.style
        items = list(self._danmaku_items)
        if not items and self._translated_text:
            items = [{"text": self._translated_text, "orig": self._original_text, "born": time.monotonic()}]
        if not items:
            return

        avail_w = max(140.0, content_rect.width() - 44.0)
        dm_px = max(16, int(st.base_font_size * 0.84))
        dm_font = QFont(st.font_family)
        dm_font.setPixelSize(dm_px)
        dm_font.setWeight(QFont.Weight.Bold if st.font_weight >= 650 else QFont.Weight.DemiBold)
        fm = QFontMetricsF(dm_font)
        hl_terms = list(self.cfg_mgr.glossary.values()) if st.highlight_glossary else None

        y_bottom = content_rect.bottom() - 4.0 + self._slide_offset
        for idx, item in enumerate(reversed(items)):
            txt = str(item["text"])
            elided = fm.elidedText(txt, Qt.TextElideMode.ElideRight, avail_w)
            tw = fm.horizontalAdvance(elided)
            pill_h = fm.height() + 14.0
            pill_w = min(content_rect.width() - 12.0, tw + 34.0)
            pill_top = y_bottom - pill_h
            if pill_top < content_rect.top() - 4.0:
                break

            tier_op = (1.0 if idx == 0 else (0.68 if idx == 1 else 0.42)) * draw_op
            pill_rect = QRectF(content_rect.center().x() - pill_w / 2.0, pill_top, pill_w, pill_h)

            painter.save()
            painter.setOpacity(tier_op)
            bg_c = QColor(st.bg_color)
            bg_c.setAlpha(max(138, int(st.bg_opacity), int(round(self._auto_bg_alpha)) if st.auto_contrast_bg else 0))
            painter.setPen(QPen(QColor(255, 255, 255, 45), 1.0))
            painter.setBrush(bg_c)
            painter.drawRoundedRect(pill_rect, pill_h / 2.0, pill_h / 2.0)

            tx = pill_rect.center().x() - tw / 2.0
            ty = pill_rect.top() + (pill_h - fm.height()) / 2.0 + fm.ascent()
            draw_styled_lyrics_line(
                painter,
                elided,
                dm_font,
                QPointF(tx, ty),
                fm.ascent(),
                fm.descent(),
                QColor(st.color_top),
                QColor(st.color_bottom),
                QColor(st.stroke_color),
                min(2.4, float(st.stroke_width)),
                int(st.shadow_opacity * 0.72),
                highlight_terms=hl_terms,
            )
            painter.restore()
            y_bottom = pill_top - 8.0

    def _paint_subtitle_mode(self, painter: QPainter, content_rect: QRectF, draw_op: float) -> None:
        st = self.cfg_mgr.config.style
        trans_txt = self._translated_text
        if not trans_txt:
            return
        orig_txt = self._original_text if (st.bilingual and self._original_text and self._original_text != trans_txt) else ""
        show_prev = (
            st.keep_prev_line
            and self._browse_idx < 0
            and bool(self._prev_translated_text)
            and self._prev_opacity > 0.02
            and self._prev_translated_text != trans_txt
        )

        avail_w = max(120.0, content_rect.width() - 40.0)
        orig_px = max(13, int(round(st.base_font_size * st.orig_font_scale)))
        orig_font = QFont(st.font_family)
        orig_font.setPixelSize(orig_px)
        orig_font.setWeight(QFont.Weight.DemiBold)
        fm_orig = QFontMetricsF(orig_font)

        # Non-truncated balanced 2-line wrap for bilingual original text!
        orig_lines = self._wrap_balanced_lines(orig_txt, orig_font, avail_w)[:2] if orig_txt else []
        orig_line_step = fm_orig.height() * 1.12
        orig_reserve_h = (len(orig_lines) * orig_line_step + 5.0) if orig_lines else 0.0

        prev_reserve_h = (max(13, int(st.base_font_size * 0.66)) * 1.35) if show_prev else 0.0
        main_avail_h = max(36.0, content_rect.height() - orig_reserve_h - prev_reserve_h - 14.0)

        main_font, main_lines = self._compute_adaptive_font_and_lines(trans_txt, avail_w, main_avail_h)
        fm_main = QFontMetricsF(main_font)
        line_step = fm_main.height() * 1.12

        # Re-sync orig font scale if main font auto-shrunk for a very long sentence
        scaled_orig_px = min(orig_px, max(12, int(main_font.pixelSize() * 0.64)))
        if scaled_orig_px != orig_px:
            orig_font.setPixelSize(scaled_orig_px)
            fm_orig = QFontMetricsF(orig_font)
            orig_lines = self._wrap_balanced_lines(orig_txt, orig_font, avail_w)[:2] if orig_txt else []
            orig_line_step = fm_orig.height() * 1.12

        prev_font = QFont(st.font_family)
        prev_font.setPixelSize(max(13, int(main_font.pixelSize() * 0.66)))
        prev_font.setWeight(QFont.Weight.DemiBold)
        fm_prev = QFontMetricsF(prev_font)
        elided_prev = fm_prev.elidedText(self._prev_translated_text, Qt.TextElideMode.ElideRight, avail_w) if show_prev else ""

        main_block_h = len(main_lines) * line_step
        orig_block_h = (len(orig_lines) * orig_line_step + 4.0) if orig_lines else 0.0
        prev_block_h = (fm_prev.height() + 6.0) if elided_prev else 0.0
        active_block_h = main_block_h + orig_block_h

        if st.anchor_bottom:
            active_top = content_rect.bottom() - active_block_h - 10.0 + self._slide_offset
        else:
            active_top = content_rect.top() + max(4.0, (content_rect.height() - active_block_h) / 2.0) + self._slide_offset

        eff_bg_alpha = max(int(st.bg_opacity), int(round(self._auto_bg_alpha)) if st.auto_contrast_bg else 0)
        prev_gap = 12.0 if eff_bg_alpha > 0 else 2.0
        prev_top = active_top - prev_block_h - prev_gap

        widest_active = max((fm_main.horizontalAdvance(ln) for ln in main_lines), default=0.0)
        for oln in orig_lines:
            widest_active = max(widest_active, fm_orig.horizontalAdvance(oln))

        if eff_bg_alpha > 0:
            painter.save()
            painter.setOpacity(draw_op)
            bg_c = QColor(st.bg_color)
            bg_c.setAlpha(min(245, eff_bg_alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg_c)
            if st.fit_bg_to_text:
                pill_w = min(content_rect.width(), widest_active + 46.0)
                pill_rect = QRectF(
                    content_rect.center().x() - pill_w / 2.0,
                    active_top - 8.0,
                    pill_w,
                    active_block_h + 16.0,
                )
                painter.drawRoundedRect(pill_rect, float(st.bg_radius), float(st.bg_radius))
            else:
                bar_rect = QRectF(content_rect.left(), active_top - 8.0, content_rect.width(), active_block_h + 16.0)
                painter.drawRoundedRect(bar_rect, float(st.bg_radius), float(st.bg_radius))
            painter.restore()

        if elided_prev and prev_top >= content_rect.top() - 4.0:
            pw = fm_prev.horizontalAdvance(elided_prev)
            px = content_rect.center().x() - pw / 2.0
            py = prev_top + fm_prev.ascent()
            draw_styled_lyrics_line(
                painter,
                elided_prev,
                prev_font,
                QPointF(px, py),
                fm_prev.ascent(),
                fm_prev.descent(),
                QColor("#E2E8F0"),
                QColor("#CBD5E1"),
                QColor(st.stroke_color),
                max(1.4, float(st.stroke_width) * 0.56),
                int(st.shadow_opacity * 0.65),
                opacity=self._prev_opacity * draw_op,
            )

        hl_terms = list(self.cfg_mgr.glossary.values()) if st.highlight_glossary else None
        # Streaming preview renders at subtle 0.88 opacity + gentle pulsing dot; final brightens cleanly to 1.0
        active_text_op = draw_op * (0.88 if self._is_preview else 1.0)
        orig_first = bool(orig_lines) and st.bilingual_order == "orig_top"

        def _paint_orig_block(y_start: float) -> float:
            oc = QColor(st.orig_color)
            y_cur = y_start + fm_orig.ascent()
            for oln in orig_lines:
                ow = fm_orig.horizontalAdvance(oln)
                ox = content_rect.center().x() - ow / 2.0
                draw_styled_lyrics_line(
                    painter,
                    oln,
                    orig_font,
                    QPointF(ox, y_cur),
                    fm_orig.ascent(),
                    fm_orig.descent(),
                    oc,
                    oc,
                    QColor(st.stroke_color),
                    max(1.5, float(st.stroke_width) * 0.62),
                    int(st.shadow_opacity * 0.80),
                    opacity=active_text_op,
                )
                y_cur += orig_line_step
            return y_start + orig_block_h

        def _paint_main_block(y_start: float) -> float:
            y_cur = y_start + fm_main.ascent()
            last_end_x = content_rect.center().x()
            last_mid_y = y_cur
            for ln in main_lines:
                ln_w = fm_main.horizontalAdvance(ln)
                x = content_rect.center().x() - ln_w / 2.0
                draw_styled_lyrics_line(
                    painter,
                    ln,
                    main_font,
                    QPointF(x, y_cur),
                    fm_main.ascent(),
                    fm_main.descent(),
                    QColor(st.color_top),
                    QColor(st.color_bottom),
                    QColor(st.stroke_color),
                    float(st.stroke_width),
                    int(st.shadow_opacity),
                    opacity=active_text_op,
                    highlight_terms=hl_terms,
                )
                last_end_x = x + ln_w
                last_mid_y = y_cur - fm_main.ascent() * 0.32
                y_cur += line_step

            # Subtle pulsing breathing dot while voice streaming preview is still speaking
            if self._is_preview:
                pulse = 0.45 + 0.50 * (0.5 + 0.5 * math.sin(self._preview_phase))
                painter.save()
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(96, 165, 250, int(235 * pulse * draw_op)))
                painter.drawEllipse(QPointF(last_end_x + 9.0, last_mid_y), 3.6, 3.6)
                painter.restore()
            return y_start + main_block_h + 3.0

        if orig_first:
            next_y = _paint_orig_block(active_top)
            _paint_main_block(next_y)
        else:
            next_y = _paint_main_block(active_top)
            if orig_lines:
                _paint_orig_block(next_y)


class _CornerBracketWidget(QWidget):
    """Tiny 24x24 click-through corner marker so even fullscreen selection uses 0 full-screen DWM overlay."""

    def __init__(self, corner: str) -> None:
        super().__init__(None)
        self._corner = corner  # "tl" | "tr" | "bl" | "br"
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(24, 24)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        hwnd = int(self.winId())
        set_exclude_from_capture(hwnd, True)
        set_window_click_through(hwnd, True)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(37, 99, 235, 200), 2.4))
        w, h, m, L = self.width(), self.height(), 2, 16
        if self._corner == "tl":
            p.drawLine(m, m, m + L, m)
            p.drawLine(m, m, m, m + L)
        elif self._corner == "tr":
            p.drawLine(w - m, m, w - m - L, m)
            p.drawLine(w - m, m, w - m, m + L)
        elif self._corner == "bl":
            p.drawLine(m, h - m, m + L, h - m)
            p.drawLine(m, h - m, m, h - m - L)
        else:
            p.drawLine(w - m, h - m, w - m - L, h - m)
            p.drawLine(w - m, h - m, w - m, h - m - L)


class LiveRegionIndicator:
    """
    Zero-DWM-overhead region indicator made of 4 tiny 24x24 corner brackets.
    Eliminates full-screen transparent layered window GPU compositing lag when user selects large/fullscreen zones.
    """

    def __init__(self) -> None:
        self._corners = {
            "tl": _CornerBracketWidget("tl"),
            "tr": _CornerBracketWidget("tr"),
            "bl": _CornerBracketWidget("bl"),
            "br": _CornerBracketWidget("br"),
        }

    def set_target_rect(self, rect: QRect) -> None:
        r = rect.adjusted(-3, -3, 3, 3)
        sz = 24
        self._corners["tl"].move(r.left(), r.top())
        self._corners["tr"].move(r.right() - sz + 1, r.top())
        self._corners["bl"].move(r.left(), r.bottom() - sz + 1)
        self._corners["br"].move(r.right() - sz + 1, r.bottom() - sz + 1)

    def show(self) -> None:
        for w in self._corners.values():
            w.show()

    def hide(self) -> None:
        for w in self._corners.values():
            w.hide()

    def close(self) -> None:
        for w in self._corners.values():
            w.close()


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
