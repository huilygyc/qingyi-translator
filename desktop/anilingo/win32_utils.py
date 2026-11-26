"""Windows Native Helpers: Global Hotkeys, Mouse Click-Through (WS_EX_TRANSPARENT), and Screen Capture Exclusion."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Dict, Tuple

import numpy as np
from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QRect, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QKeyEvent

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Windows 10 2004+ / Windows 11 invisible-to-capture flag
WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_MAP: Dict[str, int] = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): ord(str(d)) for d in range(0, 10)},
    **{f"F{i}": 0x70 + (i - 1) for i in range(1, 13)},
    **{f"NUM{d}": 0x60 + d for d in range(0, 10)},
    "SPACE": 0x20,
    "TAB": 0x09,
    "ESC": 0x1B,
    "TILDE": 0xC0,
    "`": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "HOME": 0x24,
    "END": 0x23,
    "PGUP": 0x21,
    "PGDN": 0x22,
    "INS": 0x2D,
    "DEL": 0x2E,
    "PAUSE": 0x13,
}

QT_KEY_TO_NAME: Dict[int, str] = {
    **{getattr(Qt.Key, f"Key_{chr(c)}"): chr(c) for c in range(ord("A"), ord("Z") + 1)},
    **{getattr(Qt.Key, f"Key_{d}"): str(d) for d in range(0, 10)},
    **{getattr(Qt.Key, f"Key_F{i}"): f"F{i}" for i in range(1, 13)},
    Qt.Key.Key_Space: "SPACE",
    Qt.Key.Key_Tab: "TAB",
    Qt.Key.Key_QuoteLeft: "`",
    Qt.Key.Key_AsciiTilde: "`",
    Qt.Key.Key_Minus: "-",
    Qt.Key.Key_Equal: "=",
    Qt.Key.Key_BracketLeft: "[",
    Qt.Key.Key_BracketRight: "]",
    Qt.Key.Key_Backslash: "\\",
    Qt.Key.Key_Semicolon: ";",
    Qt.Key.Key_Apostrophe: "'",
    Qt.Key.Key_Comma: ",",
    Qt.Key.Key_Period: ".",
    Qt.Key.Key_Slash: "/",
    Qt.Key.Key_Up: "UP",
    Qt.Key.Key_Down: "DOWN",
    Qt.Key.Key_Left: "LEFT",
    Qt.Key.Key_Right: "RIGHT",
    Qt.Key.Key_Home: "HOME",
    Qt.Key.Key_End: "END",
    Qt.Key.Key_PageUp: "PGUP",
    Qt.Key.Key_PageDown: "PGDN",
    Qt.Key.Key_Insert: "INS",
    Qt.Key.Key_Delete: "DEL",
    Qt.Key.Key_Pause: "PAUSE",
}


def qt_key_event_to_hotkey_str(event: QKeyEvent) -> str | None:
    """Converts a live Qt key press event into a canonical hotkey string like 'Ctrl+Shift+X' or 'F8'."""
    key = int(event.key())
    if key in (
        int(Qt.Key.Key_Control),
        int(Qt.Key.Key_Shift),
        int(Qt.Key.Key_Alt),
        int(Qt.Key.Key_Meta),
        int(Qt.Key.Key_unknown),
    ):
        return None
    key_name = QT_KEY_TO_NAME.get(Qt.Key(key)) or QT_KEY_TO_NAME.get(key)
    if not key_name:
        return None
    mods = event.modifiers()
    parts = []
    if mods & Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if mods & Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")
    if mods & Qt.KeyboardModifier.ShiftModifier:
        parts.append("Shift")
    if mods & Qt.KeyboardModifier.MetaModifier:
        parts.append("Win")
    # Require at least one modifier for normal letters/numbers so typing isn't hijacked; F1-F12 can stand alone
    if not parts and not key_name.startswith("F") and key_name not in ("PAUSE", "INS"):
        parts.append("Alt")
    parts.append(key_name)
    return "+".join(parts)


def set_exclude_from_capture(hwnd: int, enable: bool) -> bool:
    """Marks a floating window invisible to screen capture so OCR sees the clean video underneath it."""
    try:
        flag = WDA_EXCLUDEFROMCAPTURE if enable else WDA_NONE
        res = user32.SetWindowDisplayAffinity(wintypes.HWND(int(hwnd)), wintypes.DWORD(flag))
        return bool(res)
    except Exception:
        return False


def set_window_click_through(hwnd: int, enable: bool) -> None:
    """Enables/disables mouse click-through so clicks pass straight to the anime player underneath."""
    try:
        get_long = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
        set_long = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
        style = get_long(wintypes.HWND(int(hwnd)), GWL_EXSTYLE)
        if enable:
            new_style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
        else:
            new_style = style & ~WS_EX_TRANSPARENT
        set_long(wintypes.HWND(int(hwnd)), GWL_EXSTYLE, new_style)
    except Exception:
        pass


def parse_hotkey_string(hotkey_str: str) -> Tuple[int, int] | None:
    parts = [p.strip().upper() for p in (hotkey_str or "").split("+") if p.strip()]
    if not parts:
        return None
    mods = MOD_NOREPEAT
    vk = 0
    for p in parts:
        if p in ("ALT",):
            mods |= MOD_ALT
        elif p in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif p in ("SHIFT",):
            mods |= MOD_SHIFT
        elif p in ("WIN", "META", "SUPER"):
            mods |= MOD_WIN
        elif p in VK_MAP:
            vk = VK_MAP[p]
    if vk == 0:
        return None
    return mods, vk


class GlobalHotkeyManager(QObject, QAbstractNativeEventFilter):
    """System-wide Win32 RegisterHotKey dispatcher integrated cleanly into the Qt6 event loop."""

    triggered = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self._id_to_action: Dict[int, str] = {}
        self._next_id = 9100

    def unregister_all(self) -> None:
        for hk_id in list(self._id_to_action.keys()):
            try:
                user32.UnregisterHotKey(None, hk_id)
            except Exception:
                pass
        self._id_to_action.clear()

    def register_action(self, action_name: str, hotkey_str: str) -> bool:
        parsed = parse_hotkey_string(hotkey_str)
        if not parsed:
            return False
        mods, vk = parsed
        hk_id = self._next_id
        self._next_id += 1
        ok = bool(user32.RegisterHotKey(None, hk_id, mods, vk))
        if ok:
            self._id_to_action[hk_id] = action_name
        return ok

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    hk_id = int(msg.wParam)
                    action = self._id_to_action.get(hk_id)
                    if action:
                        self.triggered.emit(action)
                        return True, 0
            except Exception:
                pass
        return False, 0


def force_foreground_window(hwnd: int) -> None:
    """Brings the window immediately to the front when the user clicks the EXE."""
    try:
        SW_RESTORE = 9
        user32.ShowWindow(wintypes.HWND(int(hwnd)), SW_RESTORE)
        user32.SetForegroundWindow(wintypes.HWND(int(hwnd)))
    except Exception:
        pass


def grab_logical_rect_bgr(rect: QRect) -> np.ndarray | None:
    """DPI-aware screen grab matching Qt logical coordinates 1:1 across 100%~200% Windows scaling."""
    if rect.width() < 10 or rect.height() < 10:
        return None
    import cv2

    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return None
    s_geo = screen.geometry()
    rel_x = rect.x() - s_geo.x()
    rel_y = rect.y() - s_geo.y()
    pix = screen.grabWindow(0, rel_x, rel_y, rect.width(), rect.height())
    if pix.isNull():
        return None
    qimg = pix.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    bpl = qimg.bytesPerLine()
    ptr = qimg.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl // 4, 4))[:, :w, :]
    return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
