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


def is_alt_key_pressed() -> bool:
    """Checks whether Alt (VK_MENU) is currently held down for frictionless temporary overlay unlock."""
    try:
        return bool(user32.GetAsyncKeyState(0x12) & 0x8000)
    except Exception:
        return False


def set_current_thread_below_normal() -> None:
    """Lowers the calling worker thread priority so background OCR never stutters video players or games."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=False)
        kernel32.GetCurrentThread.restype = wintypes.HANDLE
        kernel32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
        kernel32.SetThreadPriority.restype = wintypes.BOOL
        THREAD_PRIORITY_BELOW_NORMAL = -1
        kernel32.SetThreadPriority(kernel32.GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL)
    except Exception:
        pass


def logical_rect_to_physical(rect: QRect) -> Tuple[int, int, int, int, float]:
    """
    Converts a Qt logical QRect to physical Win32 screen pixels + area_ratio relative to its display.
    Safe to compute cheaply on the GUI thread before passing plain ints to a background capturer.
    """
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return rect.x(), rect.y(), max(16, rect.width()), max(16, rect.height()), 0.1
    s_geo = screen.geometry()
    dpr = float(screen.devicePixelRatio() or 1.0)
    # Clamp rect within screen logical bounds
    clamped = rect.intersected(s_geo)
    if clamped.width() < 12 or clamped.height() < 12:
        clamped = rect
    rel_x = clamped.x() - s_geo.x()
    rel_y = clamped.y() - s_geo.y()
    phys_x = int(round(s_geo.x() + rel_x * dpr))
    phys_y = int(round(s_geo.y() + rel_y * dpr))
    phys_w = max(16, int(round(clamped.width() * dpr)))
    phys_h = max(16, int(round(clamped.height() * dpr)))
    screen_area = max(1.0, float(s_geo.width() * s_geo.height()))
    area_ratio = min(1.0, float(clamped.width() * clamped.height()) / screen_area)
    return phys_x, phys_y, phys_w, phys_h, area_ratio


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class FastWin32ScreenCapturer:
    """
    Zero-UI-blocking, persistent-buffer Win32 GDI capturer designed for background threads.
    - Reuses a single CreateDIBSection buffer across frames (no per-frame HBITMAP churn).
    - Hardware/GDI-side StretchBlt downscaling when capturing huge/fullscreen regions (max_side <= 1280),
      slashing 2.5K/4K VRAM->RAM transfer bandwidth by 4x~9x so fullscreen monitoring never lags Windows.
    """

    def __init__(self) -> None:
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

        self._user32.GetDC.argtypes = [wintypes.HWND]
        self._user32.GetDC.restype = wintypes.HDC
        self._user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self._user32.ReleaseDC.restype = ctypes.c_int

        self._gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self._gdi32.CreateCompatibleDC.restype = wintypes.HDC
        self._gdi32.CreateDIBSection.argtypes = [
            wintypes.HDC,
            ctypes.POINTER(_BITMAPINFO),
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_void_p),
            wintypes.HANDLE,
            wintypes.DWORD,
        ]
        self._gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._gdi32.DeleteDC.argtypes = [wintypes.HDC]
        self._gdi32.DeleteDC.restype = wintypes.BOOL
        self._gdi32.SetStretchBltMode.argtypes = [wintypes.HDC, ctypes.c_int]
        self._gdi32.SetStretchBltMode.restype = ctypes.c_int
        self._gdi32.BitBlt.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        ]
        self._gdi32.BitBlt.restype = wintypes.BOOL
        self._gdi32.StretchBlt.argtypes = [
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        ]
        self._gdi32.StretchBlt.restype = wintypes.BOOL

        self._hdc_mem: int = 0
        self._hbmp: int = 0
        self._old_obj: int = 0
        self._bits_ptr = ctypes.c_void_p()
        self._buf_w: int = 0
        self._buf_h: int = 0

    def _ensure_buffer(self, hdc_scr: int, dst_w: int, dst_h: int) -> bool:
        if self._hdc_mem and self._hbmp and self._buf_w == dst_w and self._buf_h == dst_h:
            return True
        self.close()
        hdc_mem = self._gdi32.CreateCompatibleDC(hdc_scr)
        if not hdc_mem:
            return False
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = dst_w
        bmi.bmiHeader.biHeight = -dst_h  # top-down DIB
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        bits_ptr = ctypes.c_void_p()
        hbmp = self._gdi32.CreateDIBSection(hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits_ptr), None, 0)
        if not hbmp or not bits_ptr.value:
            self._gdi32.DeleteDC(hdc_mem)
            return False
        old_obj = self._gdi32.SelectObject(hdc_mem, hbmp)
        self._gdi32.SetStretchBltMode(hdc_mem, 3)  # COLORONCOLOR fast
        self._hdc_mem = hdc_mem
        self._hbmp = hbmp
        self._old_obj = old_obj
        self._bits_ptr = bits_ptr
        self._buf_w = dst_w
        self._buf_h = dst_h
        return True

    def grab_bgr(self, x: int, y: int, w: int, h: int, max_side: int = 1280) -> np.ndarray | None:
        if w < 12 or h < 12:
            return None
        scale = 1.0
        if max_side > 0 and max(w, h) > max_side:
            scale = float(max_side) / float(max(w, h))
        dst_w = max(16, int(round(w * scale)))
        dst_h = max(16, int(round(h * scale)))

        hdc_scr = self._user32.GetDC(None)
        if not hdc_scr:
            return None
        try:
            if not self._ensure_buffer(hdc_scr, dst_w, dst_h):
                return None
            SRCCOPY = 0x00CC0020
            if dst_w == w and dst_h == h:
                ok = self._gdi32.BitBlt(self._hdc_mem, 0, 0, dst_w, dst_h, hdc_scr, x, y, SRCCOPY)
            else:
                ok = self._gdi32.StretchBlt(self._hdc_mem, 0, 0, dst_w, dst_h, hdc_scr, x, y, w, h, SRCCOPY)
            if not ok:
                return None
            nbytes = dst_w * dst_h * 4
            raw = (ctypes.c_ubyte * nbytes).from_address(self._bits_ptr.value)
            bgra = np.ctypeslib.as_array(raw).reshape((dst_h, dst_w, 4))
            # Copy only the 3 BGR channels out of the reused DIB buffer
            return bgra[:, :, :3].copy()
        except Exception:
            return None
        finally:
            self._user32.ReleaseDC(None, hdc_scr)

    def close(self) -> None:
        if self._hdc_mem:
            if self._old_obj:
                try:
                    self._gdi32.SelectObject(self._hdc_mem, self._old_obj)
                except Exception:
                    pass
                self._old_obj = 0
            if self._hbmp:
                try:
                    self._gdi32.DeleteObject(self._hbmp)
                except Exception:
                    pass
                self._hbmp = 0
            try:
                self._gdi32.DeleteDC(self._hdc_mem)
            except Exception:
                pass
            self._hdc_mem = 0
        self._buf_w = 0
        self._buf_h = 0


def grab_logical_rect_bgr(rect: QRect) -> np.ndarray | None:
    """DPI-aware one-shot screen grab (for Alt+Q snip), matching Qt logical coordinates 1:1."""
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
