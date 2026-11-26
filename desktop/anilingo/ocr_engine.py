"""High-Speed Multilingual Anime Screen OCR & Frame Deduplication Engine (Lazy-loaded for instant EXE startup)."""

from __future__ import annotations

import logging
import re
import threading
from difflib import SequenceMatcher
from typing import Any, List, Optional, Tuple

import numpy as np

logging.getLogger("RapidOCR").setLevel(logging.WARNING)


class ScreenOCREngine:
    """Captures screen regions and extracts foreign anime subtitles using RapidOCR PP-OCRv6."""

    def __init__(self) -> None:
        self._ocr: Any = None
        self._ocr_lock = threading.Lock()
        self._prev_thumb: Optional[np.ndarray] = None
        self._prev_text: str = ""

    def warmup(self) -> None:
        """Pre-loads ONNX OCR engine in a background daemon thread after UI is visible."""
        try:
            self._ensure_ocr()
        except Exception:
            pass

    def _ensure_ocr(self) -> Any:
        if self._ocr is None:
            with self._ocr_lock:
                if self._ocr is None:
                    from rapidocr import RapidOCR

                    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                    self._ocr = RapidOCR()
        return self._ocr

    def reset_dedup(self) -> None:
        self._prev_thumb = None
        self._prev_text = ""

    @staticmethod
    def grab_region_bgr(x: int, y: int, w: int, h: int) -> Optional[np.ndarray]:
        if w < 12 or h < 12:
            return None
        import cv2
        import mss

        with mss.mss() as sct:
            monitor = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
            shot = sct.grab(monitor)
            arr = np.array(shot, dtype=np.uint8)
            return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)

    def has_frame_changed(self, bgr: np.ndarray, diff_threshold: float = 3.2) -> bool:
        """Fast 64x20 grayscale thumbnail comparison so idle scenes cost ~0% CPU."""
        import cv2

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        thumb = cv2.resize(gray, (64, 20), interpolation=cv2.INTER_AREA).astype(np.float32)
        if self._prev_thumb is None:
            self._prev_thumb = thumb
            return True
        mad = float(np.mean(np.abs(thumb - self._prev_thumb)))
        if mad < diff_threshold:
            return False
        self._prev_thumb = thumb
        return True

    def recognize_image(self, bgr: np.ndarray, target_lang: str = "zh-CN") -> str:
        if bgr is None or bgr.size == 0:
            return ""
        import cv2

        h, w = bgr.shape[:2]
        proc = bgr
        if h < 64:
            scale = min(2.0, 72.0 / max(1, h))
            proc = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC)

        ocr = self._ensure_ocr()
        with self._ocr_lock:
            result = ocr(proc)

        if result is None or not getattr(result, "txts", None):
            return ""

        boxes = getattr(result, "boxes", None)
        txts = list(result.txts)
        scores = list(getattr(result, "scores", [1.0] * len(txts)))

        items: List[Tuple[float, float, str]] = []
        for idx, txt in enumerate(txts):
            score = float(scores[idx]) if idx < len(scores) else 1.0
            clean = (txt or "").strip()
            if not clean or score < 0.50:
                continue
            if boxes is not None and idx < len(boxes):
                box = boxes[idx]
                top_y = float(min(pt[1] for pt in box))
                left_x = float(min(pt[0] for pt in box))
            else:
                top_y, left_x = float(idx * 30), 0.0
            items.append((top_y, left_x, clean))

        if not items:
            return ""

        items.sort(key=lambda it: (round(it[0] / 18.0), it[1]))
        merged = self._join_subtitle_fragments([it[2] for it in items])

        if not re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0400-\u04ff]", merged):
            return ""

        return merged

    def check_is_new_subtitle(self, text: str, similarity_cutoff: float = 0.88) -> bool:
        clean = text.strip()
        if not clean:
            return False
        if not self._prev_text:
            self._prev_text = clean
            return True
        if clean == self._prev_text:
            return False
        ratio = SequenceMatcher(None, clean, self._prev_text).ratio()
        if ratio >= similarity_cutoff:
            return False
        self._prev_text = clean
        return True

    @staticmethod
    def _join_subtitle_fragments(parts: List[str]) -> str:
        if not parts:
            return ""
        out = parts[0]
        for p in parts[1:]:
            if re.search(r"[A-Za-z0-9]$", out) and re.search(r"^[A-Za-z0-9]", p):
                out += " " + p
            else:
                out += " " + p if len(p) > 6 and re.search(r"[A-Za-z]", p) else p
        return out.strip()
