"""Low-Latency Concurrent-Racing Translator (China Direct + Google Keep-Alive + DeepSeek LLM + Glossary)."""

from __future__ import annotations

import concurrent.futures
import html as html_mod
import http.client
import json
import re
import threading
import time
import urllib.parse
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

from .config import ConfigManager


class _KeepAliveClient:
    """Thread-safe persistent HTTP/HTTPS connection reusing TLS sockets across lines."""

    def __init__(self, host: str, use_https: bool = True, port: Optional[int] = None, timeout: float = 2.6) -> None:
        self.host = host
        self.use_https = use_https
        self.port = port
        self.timeout = timeout
        self._lock = threading.Lock()
        self._conn: Optional[http.client.HTTPConnection] = None

    def _get_conn(self) -> http.client.HTTPConnection:
        if self._conn is None:
            if self.use_https:
                self._conn = http.client.HTTPSConnection(self.host, port=self.port, timeout=self.timeout)
            else:
                self._conn = http.client.HTTPConnection(self.host, port=self.port, timeout=self.timeout)
        return self._conn

    def _reset(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def request(
        self,
        method: str,
        path: str,
        body: Optional[bytes] = None,
        headers: Optional[Dict[str, str]] = None,
        keep_alive: bool = True,
    ) -> bytes:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Connection": "keep-alive" if keep_alive else "close",
        }
        if headers:
            req_headers.update(headers)

        with self._lock:
            for attempt in range(2):
                try:
                    conn = self._get_conn()
                    conn.request(method, path, body=body, headers=req_headers)
                    resp = conn.getresponse()
                    data = resp.read()
                    if not keep_alive or getattr(resp, "will_close", False):
                        self._reset()
                    if resp.status >= 400:
                        raise RuntimeError(f"HTTP {resp.status}")
                    return data
                except Exception:
                    self._reset()
                    if attempt == 1:
                        raise
        return b""


class TranslationService:
    """
    Translates anime subtitles/speech with:
    - 'auto_free': Concurrent parallel racing between Google Keep-Alive & China-direct Youdao/MyMemory (first valid wins!)
    - 'cn_direct': Mainland China direct zero-proxy channels (Youdao Mobile + MyMemory)
    - 'google_first': Google Keep-Alive preferred with domestic fallback
    - 'deepseek' / 'openai_compat': LLM context-aware anime fansub translation
    """

    def __init__(self, cfg_mgr: ConfigManager) -> None:
        self.cfg_mgr = cfg_mgr
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._context_window: List[Tuple[str, str]] = []
        self._lock = threading.RLock()
        self._race_pool = concurrent.futures.ThreadPoolExecutor(max_workers=6, thread_name_prefix="TransRace")

        self._clients: Dict[str, _KeepAliveClient] = {
            "chrome_dict": _KeepAliveClient("clients5.google.com", True, timeout=2.0),
            "google_gtx": _KeepAliveClient("translate.googleapis.com", True, timeout=2.0),
            "youdao_m": _KeepAliveClient("m.youdao.com", True, timeout=2.5),
            "mymemory": _KeepAliveClient("api.mymemory.translated.net", True, timeout=2.8),
        }
        self._llm_clients: Dict[str, _KeepAliveClient] = {}
        self._cooldown_until: Dict[str, float] = {}

    def warmup_connections(self) -> None:
        """Pre-establishes primary & backup sockets in parallel so even sentence #1 avoids TLS cold start."""
        mode = self.cfg_mgr.config.trans_engine
        targets = ["youdao_m", "mymemory"] if mode == "cn_direct" else ["chrome_dict", "youdao_m", "google_gtx"]
        futs = [self._race_pool.submit(self._call_free_channel, ch, "hello", "en", "zh-CN") for ch in targets]
        concurrent.futures.wait(futs, timeout=2.2)

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def invalidate_text(self, original: str) -> None:
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.endswith(f"::{original.strip()}")]
            for k in keys_to_remove:
                self._cache.pop(k, None)

    def _is_cooling_down(self, ch: str) -> bool:
        return time.monotonic() < self._cooldown_until.get(ch, 0.0)

    def _mark_cooldown(self, ch: str, seconds: float = 90.0) -> None:
        self._cooldown_until[ch] = time.monotonic() + seconds

    def translate(self, text: str, force_refresh: bool = False) -> str:
        clean = self._normalize_input(text)
        if not clean:
            return ""

        cfg = self.cfg_mgr.config
        glossary = dict(self.cfg_mgr.glossary)
        glossary_sig = str(len(glossary))
        cache_key = f"{cfg.trans_engine}:{cfg.source_lang}->{cfg.target_lang}:{glossary_sig}::{clean}"

        if not force_refresh:
            with self._lock:
                if cache_key in self._cache:
                    self._cache.move_to_end(cache_key)
                    return self._cache[cache_key]

        if clean in glossary:
            return glossary[clean]

        result = ""
        use_llm = cfg.trans_engine in ("deepseek", "openai_compat") and bool(cfg.llm_api_key.strip())

        if use_llm:
            try:
                result = self._translate_via_llm(clean, glossary)
            except Exception:
                result = ""

        if not result:
            result = self._translate_via_free_channels(clean, glossary)

        result = self._post_apply_glossary(clean, result, glossary)

        if result:
            with self._lock:
                self._cache[cache_key] = result
                if len(self._cache) > 1000:
                    self._cache.popitem(last=False)
                self._context_window.append((clean, result))
                if len(self._context_window) > 6:
                    self._context_window = self._context_window[-6:]

        return result or clean

    @staticmethod
    def _normalize_input(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _pre_replace_glossary_for_free(self, text: str, glossary: Dict[str, str]) -> Tuple[str, List[Tuple[str, str]]]:
        if not glossary:
            return text, []
        out = text
        placeholders: List[Tuple[str, str]] = []
        for src, dst in sorted(glossary.items(), key=lambda kv: len(kv[0]), reverse=True):
            if not src:
                continue
            idx = len(placeholders)
            token = f"[#{idx}#]"
            if re.match(r"^[A-Za-z0-9_ ]+$", src):
                new_out, n = re.subn(rf"\b{re.escape(src)}\b", token, out, flags=re.IGNORECASE)
            else:
                n = out.count(src)
                new_out = out.replace(src, token) if n > 0 else out
            if n > 0:
                out = new_out
                placeholders.append((str(idx), dst))
        return out, placeholders

    @staticmethod
    def _restore_placeholders(translated: str, placeholders: List[Tuple[str, str]]) -> str:
        if not translated or not placeholders:
            return translated
        out = translated
        for idx_str, dst in placeholders:
            pattern = rf"[\[\uff3b【]\s*[#\uff03]\s*{re.escape(idx_str)}\s*[#\uff03]\s*[\]\uff3d】]"
            out = re.sub(pattern, dst, out)
        return out

    @staticmethod
    def _post_apply_glossary(original: str, translated: str, glossary: Dict[str, str]) -> str:
        if not translated or not glossary:
            return translated
        out = translated
        for src, dst in sorted(glossary.items(), key=lambda kv: len(kv[0]), reverse=True):
            if src in original and src in out:
                out = out.replace(src, dst)
        return out.strip()

    def _call_free_channel(self, channel: str, prepared: str, sl: str, tl: str) -> str:
        q = urllib.parse.quote(prepared)
        if channel == "chrome_dict":
            raw = self._clients["chrome_dict"].request(
                "GET", f"/translate_a/t?client=dict-chrome-ex&sl={sl}&tl={tl}&q={q}"
            )
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, list) and data:
                first = data[0]
                if isinstance(first, list) and first:
                    return str(first[0]).strip()
                if isinstance(first, str):
                    return first.strip()
        elif channel == "google_gtx":
            raw = self._clients["google_gtx"].request(
                "GET", f"/translate_a/single?client=gtx&sl={sl}&tl={tl}&dt=t&q={q}"
            )
            data = json.loads(raw.decode("utf-8"))
            if isinstance(data, list) and data and isinstance(data[0], list):
                joined = "".join(seg[0] for seg in data[0] if seg and seg[0])
                if joined.strip():
                    return joined.strip()
        elif channel == "youdao_m":
            if not tl.startswith("zh"):
                return ""
            guessed = sl if sl != "auto" else self._guess_lang(prepared)
            yd_type_map = {
                "ja": "JA2ZH_CN",
                "en": "EN2ZH_CN",
                "ko": "KR2ZH_CN",
                "fr": "FR2ZH_CN",
                "ru": "RU2ZH_CN",
            }
            yd_type = yd_type_map.get(guessed, "AUTO")
            body = urllib.parse.urlencode({"inputtext": prepared, "type": yd_type}).encode("utf-8")
            raw = self._clients["youdao_m"].request(
                "POST",
                "/translate",
                body=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://m.youdao.com/translate",
                    "User-Agent": "Mozilla/5.0 (Linux; Android 14)",
                },
                keep_alive=True,
            )
            page = raw.decode("utf-8", errors="ignore")
            m = re.search(r'<ul id="translateResult">\s*<li>(.*?)</li>', page, re.S)
            if m:
                val = html_mod.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
                if val and val != prepared:
                    return val
        elif channel == "mymemory":
            src_mm = sl if sl != "auto" else self._guess_lang(prepared)
            langpair = urllib.parse.quote(f"{src_mm}|{tl}")
            raw = self._clients["mymemory"].request("GET", f"/get?q={q}&langpair={langpair}")
            data = json.loads(raw.decode("utf-8"))
            t_text = data.get("responseData", {}).get("translatedText", "")
            if t_text:
                return str(t_text).strip()
        return ""

    def _race_staggered(
        self,
        primary: List[str],
        hedge: List[str],
        prepared: str,
        sl: str,
        tl: str,
        hedge_delay_sec: float = 0.40,
        total_timeout_sec: float = 3.0,
    ) -> str:
        """
        Staggered Hedge Racing:
        Starts primary fast channels immediately; if no valid answer arrives within 400ms,
        automatically launches hedge backup channels into the same live race to crush 800ms tail spikes.
        """
        start_t = time.monotonic()
        active_primary = [ch for ch in primary if not self._is_cooling_down(ch)] or list(primary)
        active_hedge = [ch for ch in hedge if ch not in active_primary and not self._is_cooling_down(ch)]

        pending: Dict[concurrent.futures.Future, str] = {
            self._race_pool.submit(self._call_free_channel, ch, prepared, sl, tl): ch
            for ch in active_primary
        }
        hedged = not active_hedge

        while pending:
            elapsed = time.monotonic() - start_t
            remaining = total_timeout_sec - elapsed
            if remaining <= 0:
                break

            wait_slice = min(remaining, max(0.02, hedge_delay_sec - elapsed)) if not hedged else remaining
            done, _ = concurrent.futures.wait(
                list(pending.keys()),
                timeout=wait_slice,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )

            for fut in done:
                ch = pending.pop(fut, "")
                try:
                    res = fut.result()
                    if res:
                        self._cooldown_until.pop(ch, None)
                        return res
                except Exception:
                    self._mark_cooldown(ch, 75.0)

            # Launch hedge channels once 400ms elapses (or if all primary channels already failed fast)
            if not hedged and ((time.monotonic() - start_t) >= hedge_delay_sec or not pending):
                hedged = True
                for ch in active_hedge:
                    pending[self._race_pool.submit(self._call_free_channel, ch, prepared, sl, tl)] = ch

        return ""

    def _translate_via_free_channels(self, text: str, glossary: Dict[str, str]) -> str:
        cfg = self.cfg_mgr.config
        prepared, placeholders = self._pre_replace_glossary_for_free(text, glossary)
        sl = cfg.source_lang if cfg.source_lang != "auto" else "auto"
        tl = cfg.target_lang

        if cfg.trans_engine == "cn_direct":
            res = self._race_staggered(["youdao_m"], ["mymemory"], prepared, sl, tl, hedge_delay_sec=0.38)
            if res:
                return self._restore_placeholders(res, placeholders)
        elif cfg.trans_engine == "google_first":
            res = self._race_staggered(["chrome_dict", "google_gtx"], ["youdao_m", "mymemory"], prepared, sl, tl, hedge_delay_sec=0.40)
            if res:
                return self._restore_placeholders(res, placeholders)
        else:
            # Default 'auto_free': race Google Keep-Alive + Youdao immediately, hedge google_gtx + MyMemory at 400ms
            res = self._race_staggered(["chrome_dict", "youdao_m"], ["google_gtx", "mymemory"], prepared, sl, tl, hedge_delay_sec=0.40)
            if res:
                return self._restore_placeholders(res, placeholders)

        return self._restore_placeholders(prepared, placeholders)

    def _translate_via_llm(self, text: str, glossary: Dict[str, str]) -> str:
        cfg = self.cfg_mgr.config
        base = cfg.llm_api_base.rstrip("/")
        endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.hostname or "api.deepseek.com"
        use_https = parsed.scheme != "http"
        port = parsed.port
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

        client_key = f"{parsed.scheme}://{host}:{port}"
        with self._lock:
            client = self._llm_clients.get(client_key)
            if client is None:
                client = _KeepAliveClient(host, use_https=use_https, port=port, timeout=7.5)
                self._llm_clients[client_key] = client
            recent = list(self._context_window[-4:])

        matched_terms = [f"{k} -> {v}" for k, v in glossary.items() if k.lower() in text.lower()]
        if len(matched_terms) < 20:
            for k, v in list(glossary.items())[:20]:
                pair = f"{k} -> {v}"
                if pair not in matched_terms:
                    matched_terms.append(pair)

        sys_parts = [cfg.llm_anime_prompt.strip(), f"目标语言：{cfg.target_lang}。"]
        if matched_terms:
            sys_parts.append("必须严格遵循以下专有名词/人名译法：\n" + "\n".join(matched_terms))
        if recent:
            ctx_lines = [f"原文：{o} => 译文：{t}" for o, t in recent]
            sys_parts.append("前文台词参考（仅保持人称与语境连贯，不要重复输出）：\n" + "\n".join(ctx_lines))

        payload = {
            "model": cfg.llm_model.strip() or "deepseek-chat",
            "messages": [
                {"role": "system", "content": "\n\n".join(sys_parts)},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "max_tokens": 200,
        }

        raw = client.request(
            "POST",
            path,
            body=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.llm_api_key.strip()}",
            },
        )
        body = json.loads(raw.decode("utf-8"))
        content = body["choices"][0]["message"]["content"].strip()
        return content.strip("「」『』\"'")

    @staticmethod
    def _guess_lang(text: str) -> str:
        if re.search(r"[\u3040-\u30ff]", text):
            return "ja"
        if re.search(r"[\uac00-\ud7af]", text):
            return "ko"
        if re.search(r"[\u0400-\u04ff]", text):
            return "ru"
        return "en"
