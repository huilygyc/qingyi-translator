"""Ultra-Fast Multilingual Anime Screen OCR & Frame Deduplication Engine (~45ms end-to-end)."""

from __future__ import annotations

import logging
import os
import re
import threading
from difflib import SequenceMatcher
from typing import Any, List, Optional, Tuple

import numpy as np

logging.getLogger("RapidOCR").setLevel(logging.WARNING)


class ScreenOCREngine:
    """
    Captures screen regions and extracts foreign anime subtitles using RapidOCR PP-OCRv6.
    Optimized for sub-50ms anime subtitle strips via:
    - Det.limit_type='max', Det.limit_side_len=736 (prevents 7x upscaling of wide subtitle bars)
    - Global.use_cls=False (skips unnecessary 180-degree rotation pass)
    - Optimal ONNX intra-op thread pinning (eliminates hybrid P/E-core spin contention)
    """

    def __init__(self) -> None:
        self._ocr: Any = None
        self._ocr_lock = threading.Lock()
        self._prev_thumb: Optional[np.ndarray] = None
        self._last_poll_thumb: Optional[np.ndarray] = None
        self._frame_is_stable: bool = False
        self._last_mean_score: float = 1.0
        self._prev_text: str = ""
        self._pending_candidate: str = ""
        self._empty_streak: int = 0

    def warmup(self) -> None:
        """Pre-loads ONNX OCR engine and runs a tiny dummy pass in background after UI is visible."""
        try:
            eng = self._ensure_ocr()
            with self._ocr_lock:
                eng(np.zeros((48, 192, 3), dtype=np.uint8))
        except Exception:
            pass

    def _ensure_ocr(self) -> Any:
        if self._ocr is None:
            with self._ocr_lock:
                if self._ocr is None:
                    from rapidocr import RapidOCR

                    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                    cores = os.cpu_count() or 8
                    # Keep ONNX thread count gentle so background OCR never starves video playback or desktop UI
                    intra_threads = min(4, max(2, cores // 4))
                    self._ocr = RapidOCR(
                        params={
                            "Global.use_cls": False,
                            "EngineConfig.onnxruntime.intra_op_num_threads": intra_threads,
                            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                            "Det.limit_type": "max",
                            "Det.limit_side_len": 736,
                        }
                    )
        return self._ocr

    def reset_dedup(self) -> None:
        self._prev_thumb = None
        self._last_poll_thumb = None
        self._frame_is_stable = False
        self._last_mean_score = 1.0
        self._prev_text = ""
        self._pending_candidate = ""
        self._empty_streak = 0

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
        """Ultra-fast ~1ms grayscale thumbnail comparison with inter-frame pixel-stability tracking."""
        import cv2

        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        thumb = cv2.resize(gray, (64, 20), interpolation=cv2.INTER_NEAREST).astype(np.float32)

        if self._last_poll_thumb is not None:
            inter_mad = float(np.mean(np.abs(thumb - self._last_poll_thumb)))
            self._frame_is_stable = inter_mad < 2.2
        else:
            self._frame_is_stable = False
        self._last_poll_thumb = thumb

        if self._prev_thumb is None:
            self._prev_thumb = thumb
            return True
        mad = float(np.mean(np.abs(thumb - self._prev_thumb)))
        if mad < diff_threshold:
            # If we had a pending candidate waiting for confirmation and pixels are now stable, allow 1 confirmation pass
            if self._pending_candidate and self._frame_is_stable:
                return True
            return False
        self._prev_thumb = thumb
        return True

    def recognize_image(self, bgr: np.ndarray, target_lang: str = "zh-CN", large_region: bool = False) -> str:
        if bgr is None or bgr.size == 0:
            return ""
        import cv2

        h, w = bgr.shape[:2]
        proc = bgr
        # For large / fullscreen regions, downscale early so PP-OCRv6 stays fast & lightweight
        if large_region and max(w, h) > 960:
            scale = 960.0 / float(max(w, h))
            proc = cv2.resize(bgr, (max(32, int(w * scale)), max(32, int(h * scale))), interpolation=cv2.INTER_AREA)
        elif h < 34:
            # Only upscale very tiny subtitle crops (< 34px tall) to preserve sub-50ms speed
            scale = min(1.8, 42.0 / max(1, h))
            proc = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LINEAR)

        ocr = self._ensure_ocr()
        with self._ocr_lock:
            result = ocr(proc)

        if result is None or not getattr(result, "txts", None):
            return ""

        boxes = getattr(result, "boxes", None)
        txts = list(result.txts)
        scores = list(getattr(result, "scores", [1.0] * len(txts)))

        items: List[Tuple[float, float, str]] = []
        valid_scores: List[float] = []
        min_score = 0.62 if large_region else 0.50
        for idx, txt in enumerate(txts):
            score = float(scores[idx]) if idx < len(scores) else 1.0
            clean = (txt or "").strip()
            if not clean or score < min_score:
                continue
            valid_scores.append(score)
            if boxes is not None and idx < len(boxes):
                box = boxes[idx]
                top_y = float(min(pt[1] for pt in box))
                left_x = float(min(pt[0] for pt in box))
            else:
                top_y, left_x = float(idx * 30), 0.0
            items.append((top_y, left_x, clean))

        if not items:
            self._last_mean_score = 0.0
            return ""

        self._last_mean_score = sum(valid_scores) / max(1, len(valid_scores))
        items.sort(key=lambda it: (round(it[0] / 18.0), it[1]))
        # On fullscreen regions with lots of cluttered UI/tabs/taskbar text, prefer the lower subtitle zone
        if large_region and len(items) > 8:
            proc_h = float(proc.shape[0])
            bottom_items = [it for it in items if it[0] >= proc_h * 0.52 and it[0] <= proc_h * 0.94]
            if bottom_items:
                items = bottom_items[-4:]
            else:
                items = items[-6:]

        merged = self._join_subtitle_fragments([it[2] for it in items])
        if large_region and len(merged) > 180:
            merged = merged[:180].strip()

        if not re.search(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0400-\u04ff]", merged):
            return ""

        return merged

    def check_is_new_subtitle(
        self, text: str, similarity_cutoff: float = 0.88, stabilize: bool = False
    ) -> bool:
        clean = text.strip()
        if not clean:
            self._pending_candidate = ""
            return False
        self._empty_streak = 0
        if not self._prev_text:
            self._prev_text = clean
            self._pending_candidate = ""
            return True
        if clean == self._prev_text:
            self._pending_candidate = ""
            return False
        ratio = SequenceMatcher(None, clean, self._prev_text).ratio()
        if ratio >= similarity_cutoff:
            self._pending_candidate = ""
            return False

        # Smart Pixel-Stability & Confidence Debounce:
        # Crisp, fully-rendered cuts (high confidence >= 0.90 or already pixel-stable) pass on frame 1 (saves 220ms!).
        # Blurry fade-ins / noisy flashes (< 0.90 confidence while pixels are still changing) wait for 2nd frame confirm.
        if stabilize:
            crisp_clean_cut = self._last_mean_score >= 0.90 and len(clean) >= 3
            if not crisp_clean_cut and not self._frame_is_stable:
                if not self._pending_candidate:
                    self._pending_candidate = clean
                    return False
                cand_sim = SequenceMatcher(None, clean, self._pending_candidate).ratio()
                if cand_sim < 0.72:
                    self._pending_candidate = clean
                    return False
            self._pending_candidate = ""

        self._prev_text = clean
        return True

    def record_empty_frame(self) -> int:
        self._empty_streak += 1
        self._pending_candidate = ""
        if self._empty_streak >= 3:
            self._prev_text = ""
        return self._empty_streak

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
