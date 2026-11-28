"""Clean, Spacious Light-Mode Desktop Control Panel (Zero Emojis, Calm Typography, Left Navigation Rail)."""

from __future__ import annotations

import concurrent.futures
import json
import threading
import time
import urllib.request
import webbrowser
from typing import Optional

from PySide6.QtCore import QObject, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import GITHUB_REPO, __version__
from .audio_engine import RealtimeAudioEngine
from .config import ConfigManager, SubtitleEntry
from .lan_server import LanBridgeServer, get_local_lan_ip
from .ocr_engine import ScreenOCREngine
from .translator import TranslationService
from .ui_overlays import (
    FloatingQuickPanel,
    HotkeyRecorderEdit,
    InlineSubtitleEditDialog,
    LiveRegionIndicator,
    LyricsStyleStudioWidget,
    LyricsSubtitleWindow,
    RegionSelectorOverlay,
    SnipResultCard,
)
from .win32_utils import (
    FastWin32ScreenCapturer,
    GlobalHotkeyManager,
    force_foreground_window,
    grab_logical_rect_bgr,
    logical_rect_to_physical,
    set_current_thread_below_normal,
)


def create_app_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(4, 4, 60, 60)
    grad.setColorAt(0.0, QColor("#3B82F6"))
    grad.setColorAt(1.0, QColor("#2563EB"))
    p.setBrush(grad)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 15, 15)
    p.setPen(QColor("#FFFFFF"))
    f = p.font()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "译")
    p.end()
    return QIcon(pix)


class WorkerBridge(QObject):
    subtitle_ready = Signal(str, str, str)
    audio_preview_ready = Signal(str, str)
    snip_ready = Signal(QRect, str, str)
    snip_retranslated = Signal(str)
    audio_level = Signal(float)
    status_message = Signal(str)
    devices_loaded = Signal(object)
    empty_screen = Signal()
    update_checked = Signal(str, str)  # (latest_tag, release_url)


class MainWindow(QMainWindow):
    """Minimalist Light-Themed Control Panel."""

    def __init__(self) -> None:
        super().__init__()
        self.cfg_mgr = ConfigManager()
        self.translator = TranslationService(self.cfg_mgr)
        self.ocr_engine = ScreenOCREngine()
        self.bridge = WorkerBridge(self)

        self._live_screen_running = False
        self._screen_stop_event = threading.Event()
        self._screen_thread: Optional[threading.Thread] = None
        self._capture_box_lock = threading.Lock()
        self._capture_phys_box = (0, 0, 400, 120, 0.1)
        self._audio_trans_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="AudioTrans")
        self._audio_seq_lock = threading.Lock()
        self._audio_seq = 0
        self._force_quit = False
        self._tray_notified = False
        self._current_entry_id: str = ""
        self._active_selector: Optional[RegionSelectorOverlay] = None
        self._active_snip_card: Optional[SnipResultCard] = None
        self._cached_audio_devs: dict = {"loopback": [], "mic": []}

        self.setWindowTitle("轻译 — 实时屏幕与声音字幕翻译")
        self.setWindowIcon(create_app_icon())
        self.resize(880, 580)
        self.setMinimumSize(780, 520)
        self._apply_clean_light_theme()

        # Floating Lyrics Overlay
        self.lyrics_win = LyricsSubtitleWindow(self.cfg_mgr)
        self.lyrics_win.request_edit.connect(self.open_inline_subtitle_editor)
        self.lyrics_win.request_open_style.connect(lambda: self._switch_nav(1))
        self.lyrics_win.request_snip.connect(lambda: self.start_region_selection("snip"))
        self.lyrics_win.request_mark_region.connect(lambda: self.start_region_selection("mark_region"))
        self.lyrics_win.request_open_panel.connect(lambda: self._open_main_at_tab(0))
        self.lyrics_win.lock_state_changed.connect(self._sync_lock_ui)
        self.lyrics_win.show()

        # Minimalist Horizontal Floating Capsule
        self.quick_panel = FloatingQuickPanel(self.cfg_mgr)
        self.quick_panel.act_snip.connect(lambda: self.start_region_selection("snip"))
        self.quick_panel.act_mark_region.connect(lambda: self.start_region_selection("mark_region"))
        self.quick_panel.act_toggle_live_screen.connect(self.toggle_live_screen_translation)
        self.quick_panel.act_toggle_audio.connect(self.toggle_audio_translation)
        self.quick_panel.act_switch_audio_src.connect(self._quick_switch_audio_src)
        self.quick_panel.act_toggle_lock.connect(self._toggle_lock_overlay)
        self.quick_panel.act_edit_sub.connect(self.open_inline_subtitle_editor)
        self.quick_panel.act_cycle_skin.connect(self.lyrics_win._cycle_preset)
        self.quick_panel.act_open_main.connect(self._open_main_at_tab)
        if self.cfg_mgr.config.show_quick_panel:
            self.quick_panel.show()

        self.region_indicator = LiveRegionIndicator()

        # Audio Engine
        self.audio_engine = RealtimeAudioEngine(
            self.cfg_mgr,
            on_transcript=self._on_audio_transcript_bg,
            on_level=lambda lv: self.bridge.audio_level.emit(lv),
            on_status=lambda msg: self.bridge.status_message.emit(msg),
        )

        # LAN Bridge
        self.lan_server = LanBridgeServer(
            self.cfg_mgr,
            self.translator,
            self.ocr_engine,
            get_latest_sub=self._get_latest_sub_dict,
            audio_transcriber=self.audio_engine._transcribe_local,
        )

        self.bridge.subtitle_ready.connect(self._on_subtitle_ready)
        self.bridge.audio_preview_ready.connect(self._on_audio_preview_ready)
        self.bridge.snip_ready.connect(self._on_snip_ready)
        self.bridge.snip_retranslated.connect(self._on_snip_retranslated)
        self.bridge.audio_level.connect(self._update_audio_meter)
        self.bridge.status_message.connect(self._set_status)
        self.bridge.devices_loaded.connect(self._apply_loaded_audio_devices)
        self.bridge.empty_screen.connect(self.lyrics_win.clear_for_empty_scene)
        self.bridge.update_checked.connect(self._on_update_checked)

        self.hotkeys = GlobalHotkeyManager(self)
        QApplication.instance().installNativeEventFilter(self.hotkeys)
        self.hotkeys.triggered.connect(self._on_hotkey_triggered)

        self._build_ui()
        self._setup_tray()
        self._register_configured_hotkeys()
        QTimer.singleShot(120, self._post_show_warmup)

    def _post_show_warmup(self) -> None:
        def bg_init() -> None:
            if self.cfg_mgr.config.lan_server_enabled:
                self.lan_server.start()
            try:
                devs = RealtimeAudioEngine.list_devices()
                self.bridge.devices_loaded.emit(devs)
            except Exception:
                pass
            threading.Thread(target=self.translator.warmup_connections, daemon=True, name="NetWarmup").start()
            self.ocr_engine.warmup()

        threading.Thread(target=bg_init, daemon=True, name="PostShowWarmup").start()

    def bring_panel_to_front(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        force_foreground_window(int(self.winId()))
        if self.cfg_mgr.config.show_quick_panel and not self.quick_panel.isVisible():
            self.quick_panel.show()

    def _apply_clean_light_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QStackedWidget {
                background-color: #F5F7FA;
            }
            QWidget {
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
                font-size: 13px;
                color: #1E293B;
            }
            QFrame#sidebar {
                background-color: #FFFFFF;
                border-right: 1px solid #E5E9F0;
            }
            QPushButton[nav="true"] {
                background: transparent;
                color: #475569;
                border: none;
                border-radius: 9px;
                padding: 10px 14px;
                text-align: left;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton[nav="true"]:hover {
                background-color: #F1F5F9;
                color: #0F172A;
            }
            QPushButton[nav="true"]:checked {
                background-color: #EFF6FF;
                color: #2563EB;
                font-weight: 700;
            }
            QFrame[card="true"] {
                background-color: #FFFFFF;
                border: 1px solid #E5E9F0;
                border-radius: 13px;
            }
            QLabel[role="cardTitle"] {
                color: #0F172A;
                font-size: 15px;
                font-weight: 700;
                background: transparent;
            }
            QLabel[role="caption"] {
                color: #64748B;
                font-size: 12px;
                background: transparent;
            }
            QLabel[role="pageTitle"] {
                color: #0F172A;
                font-size: 19px;
                font-weight: 700;
                background: transparent;
            }
            QPushButton {
                background-color: #F1F5F9;
                color: #334155;
                border: 1px solid #DCE2EC;
                border-radius: 8px;
                padding: 7px 15px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #E2E8F0;
                color: #0F172A;
            }
            QPushButton#primaryBtn {
                background-color: #2563EB;
                color: #FFFFFF;
                border: 1px solid #2563EB;
                border-radius: 8px;
                padding: 7px 18px;
                font-weight: 600;
            }
            QPushButton#primaryBtn:hover {
                background-color: #1D4ED8;
                border: 1px solid #1D4ED8;
            }
            QPushButton#activeStopBtn {
                background-color: #FEE2E2;
                color: #DC2626;
                border: 1px solid #FECACA;
            }
            QPushButton#activeStopBtn:hover {
                background-color: #FECACA;
            }
            QPushButton[seg="true"] {
                background-color: #F1F5F9;
                color: #64748B;
                border: 1px solid #E2E8F0;
                border-radius: 7px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton[seg="true"]:checked {
                background-color: #FFFFFF;
                color: #2563EB;
                border: 1px solid #93C5FD;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                background-color: #F8FAFC;
                color: #0F172A;
                border: 1px solid #CBD5E1;
                border-radius: 8px;
                padding: 6px 10px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
                background-color: #FFFFFF;
                border: 1px solid #2563EB;
            }
            QComboBox::drop-down {
                border: none;
                width: 22px;
            }
            QTableWidget {
                background-color: #FFFFFF;
                border: 1px solid #E5E9F0;
                border-radius: 10px;
                gridline-color: #F1F5F9;
                selection-background-color: #EFF6FF;
                selection-color: #1E293B;
            }
            QHeaderView::section {
                background-color: #F8FAFC;
                color: #475569;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #E5E9F0;
                font-weight: 600;
            }
            QProgressBar {
                background-color: #F1F5F9;
                border: none;
                border-radius: 3px;
                max-height: 6px;
            }
            QProgressBar::chunk {
                background-color: #3B82F6;
                border-radius: 3px;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            """
        )

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root_lay = QHBoxLayout(central)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # 1. Left Minimalist Sidebar
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(182)
        s_lay = QVBoxLayout(sidebar)
        s_lay.setContentsMargins(16, 24, 16, 18)
        s_lay.setSpacing(6)

        brand_row = QHBoxLayout()
        logo_badge = QLabel("译")
        logo_badge.setFixedSize(30, 30)
        logo_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_badge.setStyleSheet(
            "background-color: #2563EB; color: #FFFFFF; border-radius: 8px; font-weight: 700; font-size: 15px;"
        )
        brand_lbl = QLabel("轻译")
        brand_lbl.setStyleSheet("font-size: 18px; font-weight: 700; color: #0F172A; background: transparent;")
        brand_row.addWidget(logo_badge)
        brand_row.addSpacing(8)
        brand_row.addWidget(brand_lbl)
        brand_row.addStretch()
        s_lay.addLayout(brand_row)
        s_lay.addSpacing(18)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        nav_items = ["实时翻译", "字幕外观", "快捷键", "词表与记录", "偏好设置"]
        for idx, text in enumerate(nav_items):
            btn = QPushButton(text)
            btn.setProperty("nav", True)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if idx == 0:
                btn.setChecked(True)
            btn.clicked.connect(lambda _c, i=idx: self._switch_nav(i))
            self.nav_group.addButton(btn, idx)
            s_lay.addWidget(btn)

        s_lay.addStretch()

        # Clean sidebar bottom switches
        self.chk_sub_vis = QCheckBox("显示悬浮字幕")
        self.chk_sub_vis.setChecked(True)
        self.chk_sub_vis.toggled.connect(self.lyrics_win.setVisible)
        s_lay.addWidget(self.chk_sub_vis)

        self.chk_bar_vis = QCheckBox("显示悬浮工具条")
        self.chk_bar_vis.setChecked(self.cfg_mgr.config.show_quick_panel)
        self.chk_bar_vis.toggled.connect(self._set_quick_panel_visible)
        s_lay.addWidget(self.chk_bar_vis)

        s_lay.addSpacing(6)
        self.status_lbl = QLabel("就绪")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setStyleSheet("color: #64748B; font-size: 11.5px; padding-top: 6px; border-top: 1px solid #F1F5F9;")
        s_lay.addWidget(self.status_lbl)

        root_lay.addWidget(sidebar)

        # 2. Right Spacious Content Area
        self.pages = QStackedWidget()
        root_lay.addWidget(self.pages, 1)

        self._build_page_home()
        self._build_page_style()
        self._build_page_hotkeys()
        self._build_page_glossary_history()
        self._build_page_settings()

    def _switch_nav(self, idx: int) -> None:
        btn = self.nav_group.button(idx)
        if btn:
            btn.setChecked(True)
        self.pages.setCurrentIndex(idx)

    # --- Page 0: Spacious Home ---
    def _build_page_home(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 26, 32, 24)
        lay.setSpacing(16)

        # Header + Compact Language Selectors
        top_row = QHBoxLayout()
        title = QLabel("实时翻译")
        title.setProperty("role", "pageTitle")
        top_row.addWidget(title)
        top_row.addStretch()

        self.src_lang_combo = QComboBox()
        for label, code in [
            ("自动识别语言", "auto"),
            ("日语", "ja"),
            ("英语", "en"),
            ("韩语", "ko"),
            ("俄语", "ru"),
            ("法语", "fr"),
        ]:
            self.src_lang_combo.addItem(label, code)
        idx_s = self.src_lang_combo.findData(self.cfg_mgr.config.source_lang)
        if idx_s >= 0:
            self.src_lang_combo.setCurrentIndex(idx_s)
        self.src_lang_combo.currentIndexChanged.connect(self._save_quick_lang)

        arrow_lbl = QLabel("→")
        arrow_lbl.setStyleSheet("color: #94A3B8; padding: 0 4px;")

        self.dst_lang_combo = QComboBox()
        for label, code in [
            ("简体中文", "zh-CN"),
            ("繁體中文", "zh-TW"),
            ("英语", "en"),
            ("日语", "ja"),
        ]:
            self.dst_lang_combo.addItem(label, code)
        idx_t = self.dst_lang_combo.findData(self.cfg_mgr.config.target_lang)
        if idx_t >= 0:
            self.dst_lang_combo.setCurrentIndex(idx_t)
        self.dst_lang_combo.currentIndexChanged.connect(self._save_quick_lang)

        top_row.addWidget(self.src_lang_combo)
        top_row.addWidget(arrow_lbl)
        top_row.addWidget(self.dst_lang_combo)
        lay.addLayout(top_row)

        # Card 1: Screen Region Live Translation
        c_screen = QFrame()
        c_screen.setProperty("card", True)
        cs_lay = QHBoxLayout(c_screen)
        cs_lay.setContentsMargins(22, 18, 22, 18)

        cs_left = QVBoxLayout()
        cs_left.setSpacing(4)
        t1 = QLabel("屏幕区域翻译")
        t1.setProperty("role", "cardTitle")
        d1 = QLabel("框选固定字幕区域，台词变化时自动更新译文")
        d1.setProperty("role", "caption")
        cs_left.addWidget(t1)
        cs_left.addWidget(d1)
        cs_lay.addLayout(cs_left, 1)

        self.btn_quick_bottom = QPushButton("底部字幕区")
        self.btn_quick_bottom.setToolTip("一键锁定屏幕下方黄金字幕带（不占资源、延迟最低）")
        self.btn_quick_bottom.clicked.connect(self._select_bottom_subtitle_band)
        self.btn_mark_region = QPushButton("框选区域")
        self.btn_mark_region.clicked.connect(lambda: self.start_region_selection("mark_region"))
        self.btn_toggle_live_screen = QPushButton("开始翻译")
        self.btn_toggle_live_screen.setObjectName("primaryBtn")
        self.btn_toggle_live_screen.clicked.connect(self.toggle_live_screen_translation)
        cs_lay.addWidget(self.btn_quick_bottom)
        cs_lay.addSpacing(6)
        cs_lay.addWidget(self.btn_mark_region)
        cs_lay.addSpacing(8)
        cs_lay.addWidget(self.btn_toggle_live_screen)
        lay.addWidget(c_screen)

        # Card 2: Screenshot Translation
        c_snip = QFrame()
        c_snip.setProperty("card", True)
        sn_lay = QHBoxLayout(c_snip)
        sn_lay.setContentsMargins(22, 18, 22, 18)

        sn_left = QVBoxLayout()
        sn_left.setSpacing(4)
        t2 = QLabel("截图翻译")
        t2.setProperty("role", "cardTitle")
        self.lbl_snip_desc = QLabel("鼠标框选屏幕任意区域进行单次识别翻译")
        self.lbl_snip_desc.setProperty("role", "caption")
        sn_left.addWidget(t2)
        sn_left.addWidget(self.lbl_snip_desc)
        sn_lay.addLayout(sn_left, 1)

        self.btn_snip_now = QPushButton("框选截图")
        self.btn_snip_now.clicked.connect(lambda: self.start_region_selection("snip"))
        sn_lay.addWidget(self.btn_snip_now)
        lay.addWidget(c_snip)

        # Card 3: Audio Real-time Translation
        c_audio = QFrame()
        c_audio.setProperty("card", True)
        au_outer = QVBoxLayout(c_audio)
        au_outer.setContentsMargins(22, 18, 22, 16)
        au_outer.setSpacing(12)

        au_top = QHBoxLayout()
        au_left = QVBoxLayout()
        au_left.setSpacing(4)
        t3 = QLabel("声音实时翻译")
        t3.setProperty("role", "cardTitle")
        d3 = QLabel("直接识别电脑播放声音或麦克风说话声")
        d3.setProperty("role", "caption")
        au_left.addWidget(t3)
        au_left.addWidget(d3)
        au_top.addLayout(au_left, 1)

        self.seg_pc = QPushButton("电脑声音")
        self.seg_pc.setProperty("seg", True)
        self.seg_pc.setCheckable(True)
        self.seg_mic = QPushButton("麦克风")
        self.seg_mic.setProperty("seg", True)
        self.seg_mic.setCheckable(True)
        is_lb = self.cfg_mgr.config.audio_source == "loopback"
        self.seg_pc.setChecked(is_lb)
        self.seg_mic.setChecked(not is_lb)
        self.seg_pc.clicked.connect(lambda: self._quick_switch_audio_src("loopback"))
        self.seg_mic.clicked.connect(lambda: self._quick_switch_audio_src("mic"))

        self.btn_toggle_audio = QPushButton("开始听译")
        self.btn_toggle_audio.setObjectName("primaryBtn")
        self.btn_toggle_audio.clicked.connect(self.toggle_audio_translation)

        au_top.addWidget(self.seg_pc)
        au_top.addWidget(self.seg_mic)
        au_top.addSpacing(8)
        au_top.addWidget(self.btn_toggle_audio)
        au_outer.addLayout(au_top)

        self.audio_meter = QProgressBar()
        self.audio_meter.setRange(0, 100)
        self.audio_meter.setValue(0)
        self.audio_meter.setTextVisible(False)
        au_outer.addWidget(self.audio_meter)
        lay.addWidget(c_audio)

        # Card 4: Clean Subtitle Quick Action Strip
        c_sub = QFrame()
        c_sub.setProperty("card", True)
        sb_lay = QHBoxLayout(c_sub)
        sb_lay.setContentsMargins(22, 14, 22, 14)
        sb_lbl = QLabel("当前悬浮字幕")
        sb_lbl.setStyleSheet("font-weight: 600; color: #334155; background: transparent;")
        sb_lay.addWidget(sb_lbl)
        sb_lay.addStretch()

        btn_align_cur = QPushButton("贴合字幕区")
        btn_align_cur.clicked.connect(lambda: self._align_subtitle_to_region(False))
        btn_edit_cur = QPushButton("修改译文")
        btn_edit_cur.clicked.connect(self.open_inline_subtitle_editor)
        btn_style_go = QPushButton("调整样式")
        btn_style_go.clicked.connect(lambda: self._switch_nav(1))
        self.btn_lock_overlay = QPushButton("锁定穿透")
        self.btn_lock_overlay.clicked.connect(self._toggle_lock_overlay)

        sb_lay.addWidget(btn_align_cur)
        sb_lay.addSpacing(6)
        sb_lay.addWidget(btn_edit_cur)
        sb_lay.addSpacing(6)
        sb_lay.addWidget(btn_style_go)
        sb_lay.addSpacing(6)
        sb_lay.addWidget(self.btn_lock_overlay)
        lay.addWidget(c_sub)

        lay.addStretch()
        self.pages.addWidget(page)

    # --- Page 1: Subtitle Appearance ---
    def _build_page_style(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 22, 32, 22)
        lay.setSpacing(14)

        title = QLabel("字幕外观")
        title.setProperty("role", "pageTitle")
        lay.addWidget(title)

        self.style_studio = LyricsStyleStudioWidget(self.cfg_mgr, self)
        self.style_studio.style_changed.connect(self._on_style_updated)
        self.style_studio.request_align_region.connect(self._align_subtitle_to_region)
        lay.addWidget(self.style_studio)
        lay.addStretch()

        scroll.setWidget(page)
        self.pages.addWidget(scroll)

    # --- Page 2: Dedicated Clean Hotkeys Page ---
    def _build_page_hotkeys(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 26, 32, 24)
        lay.setSpacing(16)

        hdr = QHBoxLayout()
        title = QLabel("快捷键")
        title.setProperty("role", "pageTitle")
        hdr.addWidget(title)
        hdr.addStretch()
        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_default_hotkeys)
        hdr.addWidget(btn_reset)
        lay.addLayout(hdr)

        sub = QLabel("点击右侧按键框后直接按下键盘组合键即可修改，按 Backspace 清空")
        sub.setProperty("role", "caption")
        lay.addWidget(sub)

        card = QFrame()
        card.setProperty("card", True)
        grid = QGridLayout(card)
        grid.setContentsMargins(24, 20, 24, 20)
        grid.setVerticalSpacing(16)

        self.ed_hk_snip = HotkeyRecorderEdit(self.cfg_mgr.config.hotkey_snip_translate)
        self.ed_hk_reg = HotkeyRecorderEdit(self.cfg_mgr.config.hotkey_select_region)
        self.ed_hk_live = HotkeyRecorderEdit(self.cfg_mgr.config.hotkey_toggle_live)
        self.ed_hk_audio = HotkeyRecorderEdit(self.cfg_mgr.config.hotkey_toggle_audio)
        self.ed_hk_lock = HotkeyRecorderEdit(self.cfg_mgr.config.hotkey_lock_subtitle)

        self.ed_hk_snip.hotkey_recorded.connect(lambda v: self._update_single_hotkey("hotkey_snip_translate", v))
        self.ed_hk_reg.hotkey_recorded.connect(lambda v: self._update_single_hotkey("hotkey_select_region", v))
        self.ed_hk_live.hotkey_recorded.connect(lambda v: self._update_single_hotkey("hotkey_toggle_live", v))
        self.ed_hk_audio.hotkey_recorded.connect(lambda v: self._update_single_hotkey("hotkey_toggle_audio", v))
        self.ed_hk_lock.hotkey_recorded.connect(lambda v: self._update_single_hotkey("hotkey_lock_subtitle", v))

        rows = [
            ("框选截图翻译", "随时冻结屏幕框选任意位置进行翻译", self.ed_hk_snip),
            ("框选监控区域", "重新指定视频外语字幕所在区域", self.ed_hk_reg),
            ("开始 / 停止区域翻译", "快速切换屏幕区域实时翻译状态", self.ed_hk_live),
            ("开始 / 停止声音翻译", "快速切换电脑原声或麦克风听译", self.ed_hk_audio),
            ("锁定 / 解锁字幕穿透", "开启后鼠标点击可穿透悬浮字幕直达播放器", self.ed_hk_lock),
        ]
        for idx, (name, hint, widget) in enumerate(rows):
            txt_col = QVBoxLayout()
            txt_col.setSpacing(2)
            n_lbl = QLabel(name)
            n_lbl.setStyleSheet("font-weight: 600; color: #1E293B; background: transparent;")
            h_lbl = QLabel(hint)
            h_lbl.setProperty("role", "caption")
            txt_col.addWidget(n_lbl)
            txt_col.addWidget(h_lbl)
            grid.addLayout(txt_col, idx, 0)
            grid.addWidget(widget, idx, 1, alignment=Qt.AlignmentFlag.AlignRight)

        lay.addWidget(card)
        lay.addStretch()
        self.pages.addWidget(page)

    # --- Page 3: Glossary & History (Segmented, Clean) ---
    def _build_page_glossary_history(self) -> None:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 26, 32, 24)
        lay.setSpacing(14)

        top = QHBoxLayout()
        title = QLabel("词表与记录")
        title.setProperty("role", "pageTitle")
        top.addWidget(title)
        top.addStretch()

        self.seg_gloss = QPushButton("专有名词词表")
        self.seg_gloss.setProperty("seg", True)
        self.seg_gloss.setCheckable(True)
        self.seg_gloss.setChecked(True)
        self.seg_hist = QPushButton("翻译历史记录")
        self.seg_hist.setProperty("seg", True)
        self.seg_hist.setCheckable(True)
        sub_grp = QButtonGroup(self)
        sub_grp.setExclusive(True)
        sub_grp.addButton(self.seg_gloss, 0)
        sub_grp.addButton(self.seg_hist, 1)
        top.addWidget(self.seg_gloss)
        top.addWidget(self.seg_hist)
        lay.addLayout(top)

        sub_stack = QStackedWidget()
        self.seg_gloss.clicked.connect(lambda: sub_stack.setCurrentIndex(0))
        self.seg_hist.clicked.connect(lambda: sub_stack.setCurrentIndex(1))

        # Subpage 0: Glossary
        g_page = QWidget()
        g_lay = QVBoxLayout(g_page)
        g_lay.setContentsMargins(0, 0, 0, 0)
        g_lay.setSpacing(10)
        self.gloss_table = QTableWidget(0, 2)
        self.gloss_table.setHorizontalHeaderLabels(["外语原词", "固定译名"])
        self.gloss_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.gloss_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.gloss_table.verticalHeader().setVisible(False)
        g_lay.addWidget(self.gloss_table, 1)

        add_row = QHBoxLayout()
        self.in_g_src = QLineEdit()
        self.in_g_src.setPlaceholderText("输入外语原词（例如角色名）")
        self.in_g_dst = QLineEdit()
        self.in_g_dst.setPlaceholderText("输入指定中文译名")
        btn_g_add = QPushButton("添加词条")
        btn_g_add.setObjectName("primaryBtn")
        btn_g_add.clicked.connect(self._add_glossary_from_tab)
        btn_g_del = QPushButton("删除选中")
        btn_g_del.clicked.connect(self._del_selected_glossary)
        add_row.addWidget(self.in_g_src, 1)
        add_row.addWidget(self.in_g_dst, 1)
        add_row.addWidget(btn_g_add)
        add_row.addWidget(btn_g_del)
        g_lay.addLayout(add_row)
        sub_stack.addWidget(g_page)

        # Subpage 1: History
        h_page = QWidget()
        h_lay = QVBoxLayout(h_page)
        h_lay.setContentsMargins(0, 0, 0, 0)
        h_lay.setSpacing(10)
        self.hist_table = QTableWidget(0, 3)
        self.hist_table.setHorizontalHeaderLabels(["来源", "原文", "译文（双击可修改）"])
        self.hist_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.hist_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.hist_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.hist_table.verticalHeader().setVisible(False)
        self.hist_table.cellDoubleClicked.connect(self._on_history_row_dblclick)
        h_lay.addWidget(self.hist_table, 1)

        h_btns = QHBoxLayout()
        btn_export = QPushButton("导出 SRT 字幕")
        btn_export.clicked.connect(self._export_srt_dialog)
        btn_clear = QPushButton("清空记录")
        btn_clear.clicked.connect(self._clear_history)
        h_btns.addWidget(btn_export)
        h_btns.addStretch()
        h_btns.addWidget(btn_clear)
        h_lay.addLayout(h_btns)
        sub_stack.addWidget(h_page)

        lay.addWidget(sub_stack, 1)
        self._reload_glossary_table()
        self._reload_history_table()
        self.pages.addWidget(page)

    # --- Page 4: Clean Preferences & Engine Settings ---
    def _build_page_settings(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 26, 32, 24)
        lay.setSpacing(16)

        title = QLabel("偏好设置")
        title.setProperty("role", "pageTitle")
        lay.addWidget(title)

        card_eng = QFrame()
        card_eng.setProperty("card", True)
        g1 = QGridLayout(card_eng)
        g1.setContentsMargins(22, 20, 22, 20)
        g1.setHorizontalSpacing(16)
        g1.setVerticalSpacing(14)

        g1.addWidget(QLabel("翻译引擎"), 0, 0)
        self.engine_quick_combo = QComboBox()
        self.engine_quick_combo.addItem("自动极速竞速（推荐·免配置）", "auto_free")
        self.engine_quick_combo.addItem("国内直连免代理（有道 + MyMemory）", "cn_direct")
        self.engine_quick_combo.addItem("Google 极速优先", "google_first")
        self.engine_quick_combo.addItem("DeepSeek / 大模型接口", "deepseek")
        idx_e = self.engine_quick_combo.findData(self.cfg_mgr.config.trans_engine)
        if idx_e >= 0:
            self.engine_quick_combo.setCurrentIndex(idx_e)
        g1.addWidget(self.engine_quick_combo, 0, 1)

        g1.addWidget(QLabel("接口地址"), 1, 0)
        self.ed_api_base = QLineEdit(self.cfg_mgr.config.llm_api_base)
        g1.addWidget(self.ed_api_base, 1, 1)

        g1.addWidget(QLabel("API Key"), 2, 0)
        self.ed_api_key = QLineEdit(self.cfg_mgr.config.llm_api_key)
        self.ed_api_key.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        self.ed_api_key.setPlaceholderText("选填，留空时默认使用内置免费引擎")
        g1.addWidget(self.ed_api_key, 2, 1)

        g1.addWidget(QLabel("模型名称"), 3, 0)
        self.ed_llm_model = QLineEdit(self.cfg_mgr.config.llm_model)
        g1.addWidget(self.ed_llm_model, 3, 1)
        lay.addWidget(card_eng)

        card_hw = QFrame()
        card_hw.setProperty("card", True)
        g2 = QGridLayout(card_hw)
        g2.setContentsMargins(22, 20, 22, 20)
        g2.setHorizontalSpacing(16)
        g2.setVerticalSpacing(14)

        g2.addWidget(QLabel("音频设备"), 0, 0)
        self.audio_dev_combo = QComboBox()
        self.audio_dev_combo.addItem("系统默认设备", -1)
        g2.addWidget(self.audio_dev_combo, 0, 1)

        g2.addWidget(QLabel("语音模型"), 1, 0)
        self.combo_whisper = QComboBox()
        for label, m in [
            ("SenseVoiceSmall（动漫日/英/韩高准·首次自动下载）", "sensevoice"),
            ("Whisper 轻量极速 (tiny)", "tiny"),
            ("Whisper 均衡标准 (base)", "base"),
            ("Whisper 高准确度 (small)", "small"),
        ]:
            self.combo_whisper.addItem(label, m)
        w_idx = self.combo_whisper.findData(self.cfg_mgr.config.whisper_model)
        if w_idx >= 0:
            self.combo_whisper.setCurrentIndex(w_idx)
        g2.addWidget(self.combo_whisper, 1, 1)

        g2.addWidget(QLabel("识别频率"), 2, 0)
        sp_row = QHBoxLayout()
        self.combo_interval = QComboBox()
        for lbl_i, ms_val in [
            ("0.22 秒（极速低延迟·推荐）", 220),
            ("0.4 秒（标准）", 400),
            ("0.8 秒（均衡省电）", 800),
            ("1.2 秒（低功耗）", 1200),
        ]:
            self.combo_interval.addItem(lbl_i, ms_val)
        cur_ms = self.cfg_mgr.config.region_interval_ms
        best_idx = 0
        for i in range(self.combo_interval.count()):
            if abs(int(self.combo_interval.itemData(i)) - cur_ms) <= 100:
                best_idx = i
                break
        self.combo_interval.setCurrentIndex(best_idx)
        self.combo_interval.currentIndexChanged.connect(
            lambda: self._on_interval_changed(int(self.combo_interval.currentData() or 220))
        )
        self.chk_show_border = QCheckBox("显示区域四角辅助标")
        self.chk_show_border.setChecked(self.cfg_mgr.config.show_region_border)
        self.chk_show_border.toggled.connect(self._on_region_border_toggled)
        self.chk_stabilize = QCheckBox("智能防抖")
        self.chk_stabilize.setToolTip("清晰切换时首帧直接放行，仅在淡入残影时等待确认")
        self.chk_stabilize.setChecked(self.cfg_mgr.config.ocr_stabilize)
        sp_row.addWidget(self.combo_interval)
        sp_row.addSpacing(12)
        sp_row.addWidget(self.chk_show_border)
        sp_row.addSpacing(10)
        sp_row.addWidget(self.chk_stabilize)
        sp_row.addStretch()
        g2.addLayout(sp_row, 2, 1)

        g2.addWidget(QLabel("看番体验"), 3, 0)
        ux_row = QHBoxLayout()
        self.combo_autohide = QComboBox()
        for lbl_h, sec_v in [
            ("6 秒无台词自动隐身（推荐）", 6),
            ("4 秒无台词自动隐身", 4),
            ("10 秒无台词自动隐身", 10),
            ("不自动隐藏字幕", 0),
        ]:
            self.combo_autohide.addItem(lbl_h, sec_v)
        ah_idx = self.combo_autohide.findData(int(self.cfg_mgr.config.auto_hide_seconds))
        if ah_idx >= 0:
            self.combo_autohide.setCurrentIndex(ah_idx)
        self.chk_tray_close = QCheckBox("点关闭按钮时最小化到托盘")
        self.chk_tray_close.setChecked(self.cfg_mgr.config.minimize_to_tray_on_close)
        ux_row.addWidget(self.combo_autohide)
        ux_row.addSpacing(12)
        ux_row.addWidget(self.chk_tray_close)
        ux_row.addStretch()
        g2.addLayout(ux_row, 3, 1)

        lan_ip = get_local_lan_ip()
        port = self.cfg_mgr.config.lan_server_port
        g2.addWidget(QLabel("手机联动"), 4, 0)
        lan_lbl = QLabel(f"局域网地址  http://{lan_ip}:{port}")
        lan_lbl.setProperty("role", "caption")
        g2.addWidget(lan_lbl, 4, 1)

        g2.addWidget(QLabel("软件版本"), 5, 0)
        ver_row = QHBoxLayout()
        ver_lbl = QLabel(f"轻译 v{__version__}")
        ver_lbl.setProperty("role", "caption")
        self.btn_check_upd = QPushButton("检查新版本")
        self.btn_check_upd.clicked.connect(self._check_github_update)
        ver_row.addWidget(ver_lbl)
        ver_row.addSpacing(12)
        ver_row.addWidget(self.btn_check_upd)
        ver_row.addStretch()
        g2.addLayout(ver_row, 5, 1)
        lay.addWidget(card_hw)

        btn_save = QPushButton("保存设置")
        btn_save.setObjectName("primaryBtn")
        btn_save.clicked.connect(self._save_advanced_settings)
        lay.addWidget(btn_save, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addStretch()

        scroll.setWidget(page)
        self.pages.addWidget(scroll)

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(create_app_icon(), self)
        menu = QMenu()
        act_show = QAction("打开主面板", self)
        act_show.triggered.connect(self.bring_panel_to_front)
        act_snip = QAction("框选截图翻译", self)
        act_snip.triggered.connect(lambda: self.start_region_selection("snip"))
        act_unlock = QAction("锁定 / 解锁字幕穿透", self)
        act_unlock.triggered.connect(self._toggle_lock_overlay)
        act_quit = QAction("退出轻译", self)
        act_quit.triggered.connect(self.quit_application)
        for a in (act_show, act_snip, act_unlock, act_quit):
            menu.addAction(a)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.bring_panel_to_front()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick
            else None
        )
        self.tray.show()

    # --- Hotkey & State Sync ---
    def _register_configured_hotkeys(self) -> list[str]:
        self.hotkeys.unregister_all()
        cfg = self.cfg_mgr.config
        conflicts: list[str] = []
        for act, hk in [
            ("snip", cfg.hotkey_snip_translate),
            ("mark_region", cfg.hotkey_select_region),
            ("toggle_live", cfg.hotkey_toggle_live),
            ("toggle_audio", cfg.hotkey_toggle_audio),
            ("toggle_lock", cfg.hotkey_lock_subtitle),
        ]:
            if hk and not self.hotkeys.register_action(act, hk):
                conflicts.append(hk)
        self._refresh_action_states()
        return conflicts

    def _update_single_hotkey(self, attr_name: str, new_hk: str) -> None:
        setattr(self.cfg_mgr.config, attr_name, new_hk.strip())
        self.cfg_mgr.save()
        self._sync_hotkey_recorders()
        conflicts = self._register_configured_hotkeys()
        if conflicts:
            self._set_status(f"快捷键 {', '.join(conflicts)} 已被其他程序占用，请更换")
        else:
            self._set_status(f"已更新快捷键：{new_hk or '未设置'}")

    def _reset_default_hotkeys(self) -> None:
        cfg = self.cfg_mgr.config
        cfg.hotkey_snip_translate = "Alt+Q"
        cfg.hotkey_select_region = "Alt+R"
        cfg.hotkey_toggle_live = "Alt+S"
        cfg.hotkey_toggle_audio = "Alt+A"
        cfg.hotkey_lock_subtitle = "Alt+L"
        self.cfg_mgr.save()
        self._sync_hotkey_recorders()
        self._register_configured_hotkeys()
        self._set_status("已恢复默认快捷键")

    def _sync_hotkey_recorders(self) -> None:
        cfg = self.cfg_mgr.config
        self.ed_hk_snip.set_hotkey(cfg.hotkey_snip_translate)
        self.ed_hk_reg.set_hotkey(cfg.hotkey_select_region)
        self.ed_hk_live.set_hotkey(cfg.hotkey_toggle_live)
        self.ed_hk_audio.set_hotkey(cfg.hotkey_toggle_audio)
        self.ed_hk_lock.set_hotkey(cfg.hotkey_lock_subtitle)

    def _refresh_action_states(self) -> None:
        cfg = self.cfg_mgr.config
        hk_snip = f"（快捷键 {cfg.hotkey_snip_translate}）" if cfg.hotkey_snip_translate else ""
        self.lbl_snip_desc.setText(f"鼠标框选屏幕任意区域进行单次识别翻译{hk_snip}")

        if self._live_screen_running:
            self.btn_toggle_live_screen.setText("停止翻译")
            self.btn_toggle_live_screen.setObjectName("activeStopBtn")
        else:
            self.btn_toggle_live_screen.setText("开始翻译")
            self.btn_toggle_live_screen.setObjectName("primaryBtn")
        self.btn_toggle_live_screen.style().unpolish(self.btn_toggle_live_screen)
        self.btn_toggle_live_screen.style().polish(self.btn_toggle_live_screen)

        if self.audio_engine.is_running:
            self.btn_toggle_audio.setText("停止听译")
            self.btn_toggle_audio.setObjectName("activeStopBtn")
        else:
            self.btn_toggle_audio.setText("开始听译")
            self.btn_toggle_audio.setObjectName("primaryBtn")
        self.btn_toggle_audio.style().unpolish(self.btn_toggle_audio)
        self.btn_toggle_audio.style().polish(self.btn_toggle_audio)

        self._sync_lock_ui(cfg.style.locked_click_through)
        self._sync_quick_panel()

    def _sync_quick_panel(self) -> None:
        self.quick_panel.sync_state(
            self._live_screen_running,
            self.audio_engine.is_running,
            self.cfg_mgr.config.style.locked_click_through,
        )

    def _set_quick_panel_visible(self, vis: bool) -> None:
        self.quick_panel.setVisible(vis)
        self.cfg_mgr.config.show_quick_panel = vis
        self.cfg_mgr.save()

    def _open_main_at_tab(self, tab_idx: int = 0) -> None:
        self.bring_panel_to_front()
        self._switch_nav(tab_idx)

    def _quick_switch_audio_src(self, mode: str) -> None:
        was_running = self.audio_engine.is_running
        if was_running:
            self.audio_engine.stop()
        self.cfg_mgr.config.audio_source = mode
        self.cfg_mgr.config.audio_device_index = -1
        self.cfg_mgr.save()
        self.seg_pc.setChecked(mode == "loopback")
        self.seg_mic.setChecked(mode != "loopback")
        self._apply_loaded_audio_devices(self._cached_audio_devs)
        if was_running:
            self.audio_engine.start()
        self._sync_quick_panel()

    def _on_hotkey_triggered(self, action: str) -> None:
        if action == "snip":
            self.start_region_selection("snip")
        elif action == "mark_region":
            self.start_region_selection("mark_region")
        elif action == "toggle_live":
            self.toggle_live_screen_translation()
        elif action == "toggle_audio":
            self.toggle_audio_translation()
        elif action == "toggle_lock":
            self._toggle_lock_overlay()

    # --- Screen Region & Snip ---
    def start_region_selection(self, mode: str) -> None:
        if self._active_selector is not None:
            self._active_selector.close()
        self._active_selector = RegionSelectorOverlay(mode=mode)
        self._active_selector.region_selected.connect(self._on_region_selected)
        self._active_selector.show()
        self._active_selector.raise_()
        self._active_selector.activateWindow()

    def _refresh_capture_phys_box(self) -> float:
        r = self.cfg_mgr.config.capture_region
        rect = QRect(int(r[0]), int(r[1]), max(16, int(r[2])), max(16, int(r[3])))
        phys_box = logical_rect_to_physical(rect)
        with self._capture_box_lock:
            self._capture_phys_box = phys_box
        return phys_box[4]

    def _select_bottom_subtitle_band(self) -> None:
        scr = QGuiApplication.primaryScreen()
        geo = scr.availableGeometry() if scr else QRect(0, 0, 1920, 1080)
        bw = int(geo.width() * 0.76)
        bh = int(geo.height() * 0.16)
        bx = geo.x() + (geo.width() - bw) // 2
        by = geo.y() + int(geo.height() * 0.79)
        rect = QRect(bx, by, bw, bh)
        self._on_region_selected(rect, "mark_region")
        self._set_status("已一键锁定底部字幕带")

    def _on_region_selected(self, rect: QRect, mode: str) -> None:
        if mode == "mark_region":
            self.cfg_mgr.config.capture_region = [rect.x(), rect.y(), rect.width(), rect.height()]
            self.cfg_mgr.save()
            self.ocr_engine.reset_dedup()
            area_ratio = self._refresh_capture_phys_box()
            if self.cfg_mgr.config.show_region_border:
                self.region_indicator.set_target_rect(rect)
                self.region_indicator.show()
            if not self._live_screen_running:
                self.toggle_live_screen_translation()
            elif area_ratio > 0.40:
                self._set_status("区域较大，已启用防卡限流（建议点「底部字幕区」更快更省电）")
            else:
                self._set_status(f"已更新区域 ({rect.width()}×{rect.height()})")
        else:
            self._set_status("正在识别截图...")
            bgr = grab_logical_rect_bgr(rect)
            if bgr is None:
                self._set_status("截图失败")
                return
            threading.Thread(target=self._run_snip_ocr_bg, args=(rect, bgr), daemon=True).start()

    def _run_snip_ocr_bg(self, rect: QRect, bgr) -> None:
        orig = self.ocr_engine.recognize_image(bgr, self.cfg_mgr.config.target_lang)
        if not orig:
            self.bridge.status_message.emit("选区内未识别到文字")
            return
        trans = self.translator.translate(orig)
        self.bridge.snip_ready.emit(rect, orig, trans)

    def _on_snip_ready(self, rect: QRect, orig: str, trans: str) -> None:
        self._on_subtitle_ready("截图", orig, trans)
        if self._active_snip_card is not None:
            self._active_snip_card.close()
        card = SnipResultCard(rect, orig, trans, self)
        card.apply_to_lyrics.connect(lambda o, t: self._apply_manual_edit(o, t))
        card.retranslate_requested.connect(self._retranslate_for_snip_card)
        card.show()
        self._active_snip_card = card

    def _retranslate_for_snip_card(self, edited_orig: str) -> None:
        if not edited_orig:
            return
        threading.Thread(
            target=lambda: self.bridge.snip_retranslated.emit(
                self.translator.translate(edited_orig, force_refresh=True)
            ),
            daemon=True,
        ).start()

    def _on_snip_retranslated(self, trans: str) -> None:
        if self._active_snip_card is not None:
            self._active_snip_card.update_translation(trans)

    def toggle_live_screen_translation(self) -> None:
        self._live_screen_running = not self._live_screen_running
        if self._live_screen_running:
            self.ocr_engine.reset_dedup()
            r = self.cfg_mgr.config.capture_region
            qrect = QRect(r[0], r[1], r[2], r[3])
            area_ratio = self._refresh_capture_phys_box()
            if self.cfg_mgr.config.show_region_border:
                self.region_indicator.set_target_rect(qrect)
                self.region_indicator.show()
            if not self.lyrics_win.isVisible():
                self.lyrics_win.show()
                self.chk_sub_vis.setChecked(True)
            self._screen_stop_event.clear()
            self._screen_thread = threading.Thread(
                target=self._live_screen_worker_loop, daemon=True, name="LiveScreenWorker"
            )
            self._screen_thread.start()
            if area_ratio > 0.40:
                self._set_status("全屏监控已启用防卡限流（建议点「底部字幕区」更快更省电）")
                self.lyrics_win.show_toast("大区域防卡模式已开启，建议框选底部字幕区提速", 2400)
            else:
                self._set_status("区域实时翻译运行中")
        else:
            self._screen_stop_event.set()
            self.region_indicator.hide()
            self._set_status("区域翻译已停止")
        self._refresh_action_states()

    def _live_screen_worker_loop(self) -> None:
        """
        Dedicated low-priority background capture + OCR + translation loop:
        - Never blocks the Qt GUI thread or DWM desktop compositor.
        - Reuses a persistent DIBSection buffer and hardware-downscales fullscreen regions.
        - Enforces adaptive polling + post-OCR breathing cooldown on large/fullscreen selections.
        """
        set_current_thread_below_normal()
        capturer = FastWin32ScreenCapturer()
        try:
            while not self._screen_stop_event.is_set() and self._live_screen_running:
                loop_start = time.monotonic()
                with self._capture_box_lock:
                    px, py, pw, ph, area_ratio = self._capture_phys_box

                is_fullscreen = area_ratio > 0.45
                is_large = area_ratio > 0.30
                base_sec = max(0.12, float(self.cfg_mgr.config.region_interval_ms) / 1000.0)
                eff_interval = max(base_sec, 0.85) if is_fullscreen else (max(base_sec, 0.55) if is_large else base_sec)
                diff_thresh = 6.0 if is_fullscreen else (4.2 if is_large else 3.2)
                max_grab_side = 1024 if is_fullscreen else (1280 if is_large else 0)

                bgr = capturer.grab_bgr(px, py, pw, ph, max_side=max_grab_side)
                ran_ocr = False
                if bgr is not None and self.ocr_engine.has_frame_changed(bgr, diff_threshold=diff_thresh):
                    ran_ocr = True
                    orig = self.ocr_engine.recognize_image(
                        bgr, self.cfg_mgr.config.target_lang, large_region=is_large
                    )
                    if not orig:
                        empty_cnt = self.ocr_engine.record_empty_frame()
                        if empty_cnt == 3:
                            self.bridge.empty_screen.emit()
                    elif self.ocr_engine.check_is_new_subtitle(orig, stabilize=self.cfg_mgr.config.ocr_stabilize):
                        trans = self.translator.translate(orig)
                        self.bridge.subtitle_ready.emit("屏幕", orig, trans)

                elapsed = time.monotonic() - loop_start
                min_cooldown = (0.40 if is_fullscreen else (0.20 if is_large else 0.03)) if ran_ocr else 0.03
                wait_sec = max(min_cooldown, eff_interval - elapsed)
                self._screen_stop_event.wait(wait_sec)
        finally:
            capturer.close()

    # --- Audio ---
    def _apply_loaded_audio_devices(self, devs: dict) -> None:
        self._cached_audio_devs = devs or {"loopback": [], "mic": []}
        self.audio_dev_combo.clear()
        self.audio_dev_combo.addItem("系统默认设备", -1)
        mode = self.cfg_mgr.config.audio_source
        for d in self._cached_audio_devs.get(mode, []):
            self.audio_dev_combo.addItem(f"{d.name}", d.index)

    def toggle_audio_translation(self) -> None:
        if self.audio_engine.is_running:
            self.audio_engine.stop()
            self._set_status("声音翻译已停止")
        else:
            self.cfg_mgr.config.audio_device_index = int(self.audio_dev_combo.currentData() or -1)
            self.cfg_mgr.save()
            if not self.lyrics_win.isVisible():
                self.lyrics_win.show()
                self.chk_sub_vis.setChecked(True)
            self.audio_engine.start()
        self._refresh_action_states()

    def _on_audio_transcript_bg(self, source_tag: str, recognized_text: str, is_final: bool = True) -> None:
        """Runs translation concurrently in a worker pool so _asr_loop NEVER stalls waiting on HTTP translation."""
        with self._audio_seq_lock:
            self._audio_seq += 1
            my_seq = self._audio_seq

        def translate_task() -> None:
            trans = self.translator.translate(recognized_text)
            if not trans:
                return
            with self._audio_seq_lock:
                stale = my_seq < self._audio_seq
            if is_final:
                label = "电脑原声" if source_tag == "audio_pc" else "麦克风"
                self.bridge.subtitle_ready.emit(label, recognized_text, trans)
            elif not stale:
                self.bridge.audio_preview_ready.emit(recognized_text, trans)

        self._audio_trans_pool.submit(translate_task)

    def _on_audio_preview_ready(self, orig: str, trans: str) -> None:
        self.lyrics_win.set_subtitle(orig, trans, is_preview=True)
        self._set_status(f"实时听译中：{trans[:22]}")

    def _update_audio_meter(self, level: float) -> None:
        self.audio_meter.setValue(int(min(100, max(0, round(level * 100)))))

    # --- Subtitle Editing & Glossary ---
    def _on_subtitle_ready(self, source: str, orig: str, trans: str) -> None:
        entry = self.cfg_mgr.add_history(source, orig, trans)
        self._current_entry_id = entry.id
        self.lyrics_win.set_subtitle(orig, trans)
        self._append_history_row(entry)
        self._set_status(f"已翻译：{trans[:24]}")

    def open_inline_subtitle_editor(self) -> None:
        orig, trans = self.lyrics_win.current_subtitle()
        dlg = InlineSubtitleEditDialog(orig, trans, self)
        dlg.saved.connect(self._apply_manual_edit)
        dlg.retranslate.connect(self._retranslate_current_subtitle)
        dlg.glossary_added.connect(self._on_inline_glossary_added)
        dlg.exec()

    def _align_subtitle_to_region(self, cover: bool = False) -> None:
        r = self.cfg_mgr.config.capture_region
        rect = QRect(int(r[0]), int(r[1]), max(100, int(r[2])), max(32, int(r[3])))
        if not self.lyrics_win.isVisible():
            self.lyrics_win.show()
            self.chk_sub_vis.setChecked(True)
        self.lyrics_win.snap_to_region(rect, cover=cover)
        self.style_studio.sync_from_config()
        self._set_status("悬浮字幕已覆盖原硬字幕区" if cover else "悬浮字幕已贴合原字幕上方")

    def _apply_manual_edit(self, new_orig: str, new_trans: str) -> None:
        self.lyrics_win.set_subtitle(new_orig, new_trans, force=True)
        if self._current_entry_id:
            self.cfg_mgr.update_history_entry(self._current_entry_id, new_orig, new_trans)
        else:
            e = self.cfg_mgr.add_history("手动", new_orig, new_trans)
            self._current_entry_id = e.id
        self._reload_history_table()
        self.lyrics_win.show_toast("字幕已更新", 1400)

    def _retranslate_current_subtitle(self, edited_orig: str) -> None:
        def job() -> None:
            t = self.translator.translate(edited_orig, force_refresh=True)
            self.bridge.subtitle_ready.emit("重译", edited_orig, t)

        threading.Thread(target=job, daemon=True).start()

    def _on_inline_glossary_added(self, src_term: str, dst_term: str) -> None:
        self.cfg_mgr.set_glossary_term(src_term, dst_term)
        self.translator.clear_cache()
        self._reload_glossary_table()

    def _save_quick_lang(self) -> None:
        self.cfg_mgr.config.source_lang = str(self.src_lang_combo.currentData())
        self.cfg_mgr.config.target_lang = str(self.dst_lang_combo.currentData())
        self.cfg_mgr.save()
        self.translator.clear_cache()

    def _on_region_border_toggled(self, checked: bool) -> None:
        self.cfg_mgr.config.show_region_border = checked
        self.cfg_mgr.save()
        if checked and self._live_screen_running:
            r = self.cfg_mgr.config.capture_region
            self.region_indicator.set_target_rect(QRect(r[0], r[1], r[2], r[3]))
            self.region_indicator.show()
        else:
            self.region_indicator.hide()

    def _on_interval_changed(self, val: int) -> None:
        self.cfg_mgr.config.region_interval_ms = val
        self.cfg_mgr.save()

    def _toggle_lock_overlay(self) -> None:
        cur = self.cfg_mgr.config.style.locked_click_through
        self.lyrics_win.set_locked(not cur)

    def _sync_lock_ui(self, locked: bool) -> None:
        if locked:
            self.btn_lock_overlay.setText("解锁穿透")
            self.btn_lock_overlay.setStyleSheet("background-color: #FEF3C7; color: #B45309; border: 1px solid #FDE68A;")
        else:
            self.btn_lock_overlay.setText("锁定穿透")
            self.btn_lock_overlay.setStyleSheet("")
        self._sync_quick_panel()

    def _on_style_updated(self) -> None:
        self.lyrics_win.apply_native_window_flags()
        self.lyrics_win.update()

    def _reload_history_table(self) -> None:
        self.hist_table.setRowCount(0)
        for entry in self.cfg_mgr.history[-120:]:
            self._append_history_row(entry)

    def _append_history_row(self, entry: SubtitleEntry) -> None:
        r = self.hist_table.rowCount()
        self.hist_table.insertRow(r)
        it_src = QTableWidgetItem(entry.source)
        it_src.setData(Qt.ItemDataRole.UserRole, entry.id)
        self.hist_table.setItem(r, 0, it_src)
        self.hist_table.setItem(r, 1, QTableWidgetItem(entry.original))
        self.hist_table.setItem(r, 2, QTableWidgetItem(entry.translated))
        self.hist_table.scrollToBottom()

    def _on_history_row_dblclick(self, row: int, _col: int) -> None:
        id_item = self.hist_table.item(row, 0)
        orig_item = self.hist_table.item(row, 1)
        trans_item = self.hist_table.item(row, 2)
        if not id_item or not orig_item or not trans_item:
            return
        self._current_entry_id = str(id_item.data(Qt.ItemDataRole.UserRole))
        self.lyrics_win.set_subtitle(orig_item.text(), trans_item.text())
        self.open_inline_subtitle_editor()

    def _export_srt_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "导出 SRT 字幕", "subtitles.srt", "SRT Subtitle (*.srt)")
        if path:
            cnt = self.cfg_mgr.export_srt(path, bilingual=True)
            QMessageBox.information(self, "导出完成", f"已导出 {cnt} 条字幕至：\n{path}")

    def _clear_history(self) -> None:
        self.cfg_mgr.history.clear()
        self.cfg_mgr.save_history()
        self.hist_table.setRowCount(0)

    def _reload_glossary_table(self) -> None:
        self.gloss_table.setRowCount(0)
        for src, dst in self.cfg_mgr.glossary.items():
            r = self.gloss_table.rowCount()
            self.gloss_table.insertRow(r)
            self.gloss_table.setItem(r, 0, QTableWidgetItem(src))
            self.gloss_table.setItem(r, 1, QTableWidgetItem(dst))

    def _add_glossary_from_tab(self) -> None:
        s = self.in_g_src.text().strip()
        d = self.in_g_dst.text().strip()
        if s and d:
            self.cfg_mgr.set_glossary_term(s, d)
            self.translator.clear_cache()
            self.in_g_src.clear()
            self.in_g_dst.clear()
            self._reload_glossary_table()

    def _del_selected_glossary(self) -> None:
        row = self.gloss_table.currentRow()
        if row >= 0:
            item = self.gloss_table.item(row, 0)
            if item:
                self.cfg_mgr.remove_glossary_term(item.text())
                self.translator.clear_cache()
                self._reload_glossary_table()

    def _save_advanced_settings(self) -> None:
        cfg = self.cfg_mgr.config
        cfg.trans_engine = str(self.engine_quick_combo.currentData())
        cfg.llm_api_base = self.ed_api_base.text().strip() or "https://api.deepseek.com/v1"
        cfg.llm_api_key = self.ed_api_key.text().strip()
        cfg.llm_model = self.ed_llm_model.text().strip() or "deepseek-chat"
        cfg.whisper_model = str(self.combo_whisper.currentData() or "tiny")
        cfg.ocr_stabilize = self.chk_stabilize.isChecked()
        cfg.auto_hide_seconds = int(self.combo_autohide.currentData() or 0)
        cfg.minimize_to_tray_on_close = self.chk_tray_close.isChecked()
        if cfg.llm_api_key and cfg.trans_engine == "auto_free":
            cfg.trans_engine = "deepseek"
            idx_ds = self.engine_quick_combo.findData("deepseek")
            if idx_ds >= 0:
                self.engine_quick_combo.setCurrentIndex(idx_ds)
        self.cfg_mgr.save()
        self.translator.clear_cache()
        self._set_status("偏好设置已保存")

    def _check_github_update(self) -> None:
        self.btn_check_upd.setEnabled(False)
        self.btn_check_upd.setText("检查中...")

        def fetch() -> None:
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                req = urllib.request.Request(url, headers={"User-Agent": f"QingYi/{__version__}"})
                data = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))
                tag = str(data.get("tag_name", "")).strip()
                html_url = str(data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases"))
                self.bridge.update_checked.emit(tag, html_url)
            except Exception:
                self.bridge.update_checked.emit("ERROR", "")

        threading.Thread(target=fetch, daemon=True).start()

    def _on_update_checked(self, latest_tag: str, html_url: str) -> None:
        self.btn_check_upd.setEnabled(True)
        self.btn_check_upd.setText("检查新版本")
        if latest_tag == "ERROR" or not latest_tag:
            QMessageBox.information(self, "检查更新", "连接 GitHub 失败，请稍后重试。")
            return
        cur_v = f"v{__version__}"
        if latest_tag != cur_v and latest_tag > cur_v:
            reply = QMessageBox.question(
                self,
                "发现新版本",
                f"当前版本：{cur_v}\n最新版本：{latest_tag}\n\n是否立即前往 GitHub 下载更新？",
            )
            if reply == QMessageBox.StandardButton.Yes and html_url:
                webbrowser.open(html_url)
        else:
            QMessageBox.information(self, "检查更新", f"当前已是最新版本（{cur_v}）。")

    def _get_latest_sub_dict(self) -> dict:
        o, t = self.lyrics_win.current_subtitle()
        return {"original": o, "translated": t, "timestamp": time.time()}

    def _set_status(self, text: str) -> None:
        clean = (text or "").lstrip("🎧📺✂️✨✅⚠️⏳⏹️⏸️💡 ").strip()
        self.status_lbl.setText(clean)

    def quit_application(self) -> None:
        self._force_quit = True
        self.close()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:
        if not self._force_quit and self.cfg_mgr.config.minimize_to_tray_on_close and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_notified:
                self._tray_notified = True
                self.tray.showMessage(
                    "轻译仍在后台运行",
                    "悬浮字幕与工具条已保留，双击右下角托盘图标可重新打开主面板。",
                    QSystemTrayIcon.MessageIcon.Information,
                    2600,
                )
            return

        self._live_screen_running = False
        self._screen_stop_event.set()
        self.audio_engine.stop()
        self.lan_server.stop()
        self.cfg_mgr.flush_pending_writes()
        self.hotkeys.unregister_all()
        self.region_indicator.close()
        self.quick_panel.close()
        self.lyrics_win.close()
        self.tray.hide()
        super().closeEvent(event)
