"""Configuration, Lyrics Style Presets, Anime Glossary, and Subtitle History Management."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = DATA_DIR / "config.json"
GLOSSARY_PATH = DATA_DIR / "glossary.json"
HISTORY_PATH = DATA_DIR / "history.json"


# Clean, refined music-lyrics & cinema subtitle presets (no garish colors)
LYRICS_STYLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "sakura_fansub": {
        "name": "纯净电影白（默认无底色）",
        "font_family": "Microsoft YaHei UI",
        "font_weight": 700,
        "base_font_size": 30,
        "orig_font_scale": 0.56,
        "auto_scale_font": True,
        "bilingual": True,
        "color_top": "#FFFFFF",
        "color_bottom": "#F1F5F9",
        "orig_color": "#E2E8F0",
        "stroke_color": "#1E293B",
        "stroke_width": 3.4,
        "shadow_opacity": 155,
        "bg_color": "#0F172A",
        "bg_opacity": 0,
        "bg_radius": 16,
    },
    "cloud_music_cyan": {
        "name": "晴空冰蓝（桌面歌词风）",
        "font_family": "Microsoft YaHei UI",
        "font_weight": 700,
        "base_font_size": 30,
        "orig_font_scale": 0.55,
        "auto_scale_font": True,
        "bilingual": True,
        "color_top": "#FFFFFF",
        "color_bottom": "#BAE6FD",
        "orig_color": "#E0F2FE",
        "stroke_color": "#0F2942",
        "stroke_width": 3.4,
        "shadow_opacity": 160,
        "bg_color": "#0F172A",
        "bg_opacity": 0,
        "bg_radius": 16,
    },
    "amber_fantasy": {
        "name": "暖调柔和黄（经典影视风）",
        "font_family": "Microsoft YaHei UI",
        "font_weight": 700,
        "base_font_size": 30,
        "orig_font_scale": 0.55,
        "auto_scale_font": True,
        "bilingual": True,
        "color_top": "#FFFBEB",
        "color_bottom": "#FDE68A",
        "orig_color": "#F3F4F6",
        "stroke_color": "#1F242D",
        "stroke_width": 3.4,
        "shadow_opacity": 165,
        "bg_color": "#18181B",
        "bg_opacity": 0,
        "bg_radius": 16,
    },
    "fansub_classic": {
        "name": "字幕组深蓝描边",
        "font_family": "Microsoft YaHei UI",
        "font_weight": 700,
        "base_font_size": 29,
        "orig_font_scale": 0.56,
        "auto_scale_font": True,
        "bilingual": True,
        "color_top": "#FFFFFF",
        "color_bottom": "#F8FAFC",
        "orig_color": "#E2E8F0",
        "stroke_color": "#1E3A5F",
        "stroke_width": 3.6,
        "shadow_opacity": 170,
        "bg_color": "#0F172A",
        "bg_opacity": 0,
        "bg_radius": 16,
    },
    "mint_neon": {
        "name": "清爽薄荷青",
        "font_family": "Microsoft YaHei UI",
        "font_weight": 700,
        "base_font_size": 30,
        "orig_font_scale": 0.55,
        "auto_scale_font": True,
        "bilingual": True,
        "color_top": "#FFFFFF",
        "color_bottom": "#A7F3D0",
        "orig_color": "#ECFDF5",
        "stroke_color": "#132A24",
        "stroke_width": 3.3,
        "shadow_opacity": 160,
        "bg_color": "#0F1F1C",
        "bg_opacity": 0,
        "bg_radius": 16,
    },
    "soft_glass_pill": {
        "name": "半透浅灰黑底条（防杂乱背景）",
        "font_family": "Microsoft YaHei UI",
        "font_weight": 600,
        "base_font_size": 28,
        "orig_font_scale": 0.56,
        "auto_scale_font": True,
        "bilingual": True,
        "color_top": "#FFFFFF",
        "color_bottom": "#F8FAFC",
        "orig_color": "#CBD5E1",
        "stroke_color": "#0F172A",
        "stroke_width": 1.8,
        "shadow_opacity": 110,
        "bg_color": "#1E293B",
        "bg_opacity": 145,
        "bg_radius": 18,
    },
}


@dataclass
class SubtitleStyleConfig:
    preset_key: str = "sakura_fansub"
    font_family: str = "Microsoft YaHei UI"
    font_weight: int = 700
    base_font_size: int = 30
    orig_font_scale: float = 0.56
    auto_scale_font: bool = True
    bilingual: bool = True
    color_top: str = "#FFFFFF"
    color_bottom: str = "#F1F5F9"
    orig_color: str = "#E2E8F0"
    stroke_color: str = "#1E293B"
    stroke_width: float = 3.4
    shadow_opacity: int = 155
    bg_color: str = "#0F172A"
    bg_opacity: int = 0
    bg_radius: int = 16
    fit_bg_to_text: bool = True
    anchor_bottom: bool = True
    keep_prev_line: bool = True
    display_mode: str = "subtitle"  # "subtitle" | "danmaku"
    overlay_x: int = -1
    overlay_y: int = -1
    overlay_width: int = 920
    overlay_height: int = 195
    locked_click_through: bool = False
    exclude_from_capture: bool = True


@dataclass
class AppConfig:
    # Translation settings
    trans_engine: str = "auto_free"  # "auto_free" | "deepseek" | "openai_compat"
    source_lang: str = "auto"        # "auto" | "ja" | "en" | "ko" | "ru" | "fr"
    target_lang: str = "zh-CN"       # "zh-CN" | "zh-TW" | "en" | "ja"
    llm_api_base: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_anime_prompt: str = (
        "你是一位资深的二次元番剧字幕组精校翻译。请将外语台词自然、信达雅地翻译为简体中文，"
        "贴合日本动漫/影视的口语语境、语气词与人物性格，绝不生硬机翻。只输出译文本身，不要任何解释或引号。"
    )

    # Screen region capture settings
    capture_region: List[int] = field(default_factory=lambda: [360, 780, 1200, 180])  # [x, y, w, h]
    region_interval_ms: int = 220
    show_region_border: bool = True
    ocr_stabilize: bool = True

    # Subtitle auto-hide & tray behavior
    auto_hide_seconds: int = 6      # 0 = never hide; otherwise fade out after N seconds of no new lines
    minimize_to_tray_on_close: bool = True

    # Audio capture & ASR settings
    audio_source: str = "loopback"  # "loopback" (电脑声音) | "mic" (说话麦克风)
    audio_device_index: int = -1    # -1 = auto default
    whisper_model: str = "tiny"     # "sensevoice" | "tiny" | "base" | "small"
    vad_energy_threshold: float = 0.012
    asr_cloud_api_base: str = ""
    asr_cloud_api_key: str = ""
    asr_cloud_model: str = "whisper-1"

    # Global Hotkeys
    hotkey_snip_translate: str = "Alt+Q"
    hotkey_select_region: str = "Alt+R"
    hotkey_toggle_live: str = "Alt+S"
    hotkey_toggle_audio: str = "Alt+A"
    hotkey_lock_subtitle: str = "Alt+L"

    # Floating Quick Control Panel
    show_quick_panel: bool = True

    # LAN Server for Mobile Companion
    lan_server_enabled: bool = True
    lan_server_port: int = 18765

    # Subtitle visual style
    style: SubtitleStyleConfig = field(default_factory=SubtitleStyleConfig)


@dataclass
class SubtitleEntry:
    id: str
    timestamp: float
    source: str  # "screen" | "snip" | "audio_pc" | "audio_mic" | "manual"
    original: str
    translated: str
    edited: bool = False

    def format_srt_time(self, ts_offset: float) -> str:
        secs = max(0.0, ts_offset)
        h = int(secs // 3600)
        m = int((secs % 3600) // 60)
        s = int(secs % 60)
        ms = int((secs - int(secs)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class ConfigManager:
    """Thread-safe manager for app configuration, anime glossary, and subtitle timeline."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.config = AppConfig()
        self.glossary: Dict[str, str] = {
            "フリーレン": "芙莉莲",
            "Frieren": "芙莉莲",
            "ヒンメル": "辛美尔",
            "Himmel": "辛美尔",
            "フェルン": "菲伦",
            "Fern": "菲伦",
            "シュタルク": "休塔尔克",
            "Stark": "休塔尔克",
        }
        self.history: List[SubtitleEntry] = []
        self.load()

    def load(self) -> None:
        with self._lock:
            if CONFIG_PATH.exists():
                try:
                    raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                    style_raw = raw.pop("style", {})
                    for k, v in raw.items():
                        if hasattr(self.config, k):
                            setattr(self.config, k, v)
                    for sk, sv in style_raw.items():
                        if hasattr(self.config.style, sk):
                            setattr(self.config.style, sk, sv)
                except Exception:
                    pass

            if GLOSSARY_PATH.exists():
                try:
                    g = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
                    if isinstance(g, dict):
                        self.glossary = {str(k): str(v) for k, v in g.items() if str(k).strip()}
                except Exception:
                    pass
            else:
                self.save_glossary()

            if HISTORY_PATH.exists():
                try:
                    h_list = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
                    if isinstance(h_list, list):
                        self.history = [SubtitleEntry(**item) for item in h_list[-300:]]
                except Exception:
                    pass

    def save(self) -> None:
        with self._lock:
            data = asdict(self.config)
            CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def save_glossary(self) -> None:
        with self._lock:
            GLOSSARY_PATH.write_text(
                json.dumps(self.glossary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def save_history(self) -> None:
        with self._lock:
            trimmed = self.history[-300:]
            HISTORY_PATH.write_text(
                json.dumps([asdict(x) for x in trimmed], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def apply_preset(self, preset_key: str) -> None:
        with self._lock:
            preset = LYRICS_STYLE_PRESETS.get(preset_key)
            if not preset:
                return
            self.config.style.preset_key = preset_key
            for k, v in preset.items():
                if k != "name" and hasattr(self.config.style, k):
                    setattr(self.config.style, k, v)
            self.save()

    def set_glossary_term(self, src_term: str, dst_term: str) -> None:
        src_clean = src_term.strip()
        dst_clean = dst_term.strip()
        if not src_clean or not dst_clean:
            return
        with self._lock:
            self.glossary[src_clean] = dst_clean
            self.save_glossary()

    def remove_glossary_term(self, src_term: str) -> None:
        with self._lock:
            if src_term in self.glossary:
                del self.glossary[src_term]
                self.save_glossary()

    def add_history(self, source: str, original: str, translated: str) -> SubtitleEntry:
        with self._lock:
            entry = SubtitleEntry(
                id=f"{int(time.time() * 1000)}_{len(self.history)}",
                timestamp=time.time(),
                source=source,
                original=original.strip(),
                translated=translated.strip(),
                edited=False,
            )
            self.history.append(entry)
            if len(self.history) > 300:
                self.history = self.history[-300:]
            self.save_history()
            return entry

    def update_history_entry(self, entry_id: str, new_original: str, new_translated: str) -> SubtitleEntry | None:
        with self._lock:
            for item in reversed(self.history):
                if item.id == entry_id:
                    item.original = new_original.strip()
                    item.translated = new_translated.strip()
                    item.edited = True
                    self.save_history()
                    return item
        return None

    def export_srt(self, out_path: str | Path, bilingual: bool = True) -> int:
        with self._lock:
            items = list(self.history)
        if not items:
            Path(out_path).write_text("", encoding="utf-8")
            return 0
        t0 = items[0].timestamp
        lines: List[str] = []
        for idx, item in enumerate(items, start=1):
            start_rel = item.timestamp - t0
            if idx < len(items):
                end_rel = min(start_rel + 4.0, max(start_rel + 1.2, items[idx].timestamp - t0 - 0.1))
            else:
                end_rel = start_rel + 3.5
            s_str = item.format_srt_time(start_rel)
            e_str = item.format_srt_time(end_rel)
            body = f"{item.translated}\n{item.original}" if (bilingual and item.original) else item.translated
            lines.append(f"{idx}\n{s_str} --> {e_str}\n{body}\n")
        Path(out_path).write_text("\n".join(lines), encoding="utf-8")
        return len(items)
