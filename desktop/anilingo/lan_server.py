"""Lightweight LAN Companion HTTP Bridge so the Android App can sync Glossary, Styles, or Offload Translation."""

from __future__ import annotations

import base64
import json
import socket
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

import numpy as np

from .config import ConfigManager
from .ocr_engine import ScreenOCREngine
from .translator import TranslationService


def get_local_lan_ip() -> str:
    """Prefers physical Wi-Fi/Ethernet LAN IPv4 (192.168.x.x / 10.x.x.x / 172.16-31.x.x) over TUN/virtual IPs."""
    try:
        candidates = []
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ip.startswith("192.168."):
                return ip
            if ip.startswith("10.") or (
                ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31
            ):
                candidates.append(ip)
        if candidates:
            return candidates[0]
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class LanBridgeServer:
    """Exposes /api/ping, /api/glossary, /api/translate, /api/ocr_translate, /api/latest for Android companion."""

    def __init__(
        self,
        cfg_mgr: ConfigManager,
        translator: TranslationService,
        ocr_engine: ScreenOCREngine,
        get_latest_sub: Callable[[], dict],
        audio_transcriber: Optional[Callable[[np.ndarray, Optional[str]], str]] = None,
    ) -> None:
        self.cfg_mgr = cfg_mgr
        self.translator = translator
        self.ocr_engine = ocr_engine
        self.get_latest_sub = get_latest_sub
        self.audio_transcriber = audio_transcriber
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._httpd is not None:
            return
        port = int(self.cfg_mgr.config.lan_server_port)
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args) -> None:
                pass

            def _send_json(self, code: int, payload: dict) -> None:
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if self.path.startswith("/api/ping"):
                    self._send_json(200, {"ok": True, "app": "AniLingo-Desktop", "ip": get_local_lan_ip()})
                elif self.path.startswith("/api/glossary"):
                    self._send_json(200, {"ok": True, "glossary": parent.cfg_mgr.glossary})
                elif self.path.startswith("/api/latest"):
                    self._send_json(200, {"ok": True, "subtitle": parent.get_latest_sub(), "style": asdict(parent.cfg_mgr.config.style)})
                else:
                    self._send_json(404, {"ok": False, "error": "not_found"})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8")) if length > 0 else {}
                if self.path.startswith("/api/translate"):
                    txt = str(body.get("text", "")).strip()
                    trans = parent.translator.translate(txt) if txt else ""
                    self._send_json(200, {"ok": True, "original": txt, "translated": trans})
                elif self.path.startswith("/api/ocr_translate"):
                    import cv2

                    b64 = str(body.get("image_base64", ""))
                    raw_img = base64.b64decode(b64)
                    arr = np.frombuffer(raw_img, dtype=np.uint8)
                    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                    orig = parent.ocr_engine.recognize_image(bgr, parent.cfg_mgr.config.target_lang)
                    trans = parent.translator.translate(orig) if orig else ""
                    self._send_json(200, {"ok": True, "original": orig, "translated": trans})
                elif self.path.startswith("/api/audio_transcribe") and parent.audio_transcriber is not None:
                    b64_pcm = str(body.get("pcm16_base64", ""))
                    lang = body.get("lang") or None
                    if lang == "auto":
                        lang = None
                    raw_pcm = base64.b64decode(b64_pcm)
                    audio_f32 = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0
                    orig = parent.audio_transcriber(audio_f32, lang)
                    self._send_json(200, {"ok": True, "text": orig})
                elif self.path.startswith("/api/glossary"):
                    terms = body.get("glossary", {})
                    if isinstance(terms, dict):
                        for k, v in terms.items():
                            parent.cfg_mgr.set_glossary_term(str(k), str(v))
                    self._send_json(200, {"ok": True, "glossary": parent.cfg_mgr.glossary})
                else:
                    self._send_json(404, {"ok": False, "error": "not_found"})

        try:
            self._httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
            self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="LanBridge")
            self._thread.start()
        except Exception:
            self._httpd = None

    def stop(self) -> None:
        if self._httpd is not None:
            try:
                self._httpd.shutdown()
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None
