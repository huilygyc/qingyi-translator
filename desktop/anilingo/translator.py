"""Multi-engine Translator with Zero-Config Free Channels, DeepSeek/OpenAI LLM Context, and Anime Glossary."""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import urllib.request
from collections import OrderedDict
from typing import Dict, List, Tuple

from .config import ConfigManager


class TranslationService:
    """Translates anime subtitles/speech with glossary enforcement, rolling context, and automatic failover."""

    def __init__(self, cfg_mgr: ConfigManager) -> None:
        self.cfg_mgr = cfg_mgr
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._context_window: List[Tuple[str, str]] = []
        self._lock = threading.RLock()

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    def invalidate_text(self, original: str) -> None:
        with self._lock:
            keys_to_remove = [k for k in self._cache if k.endswith(f"::{original.strip()}")]
            for k in keys_to_remove:
                self._cache.pop(k, None)

    def translate(self, text: str, force_refresh: bool = False) -> str:
        clean = self._normalize_input(text)
        if not clean:
            return ""

        cfg = self.cfg_mgr.config
        glossary = dict(self.cfg_mgr.glossary)
        glossary_sig = str( len(glossary) )
        cache_key = f"{cfg.trans_engine}:{cfg.source_lang}->{cfg.target_lang}:{glossary_sig}::{clean}"

        if not force_refresh:
            with self._lock:
                if cache_key in self._cache:
                    self._cache.move_to_end(cache_key)
                    return self._cache[cache_key]

        # Direct exact match in glossary
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
        text = re.sub(r"\s+", " ", text or "").strip()
        return text

    def _pre_replace_glossary_for_free(self, text: str, glossary: Dict[str, str]) -> Tuple[str, List[Tuple[str, str]]]:
        """Replaces matched glossary source terms with invariant placeholders [#0#] so MT never alters them."""
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
        """Ensures any untranslated source glossary token remaining in output is mapped cleanly."""
        if not translated or not glossary:
            return translated
        out = translated
        for src, dst in sorted(glossary.items(), key=lambda kv: len(kv[0]), reverse=True):
            if src in original and src in out:
                out = out.replace(src, dst)
        return out.strip()

    def _translate_via_free_channels(self, text: str, glossary: Dict[str, str]) -> str:
        cfg = self.cfg_mgr.config
        prepared, placeholders = self._pre_replace_glossary_for_free(text, glossary)
        sl = cfg.source_lang if cfg.source_lang != "auto" else "auto"
        tl = cfg.target_lang

        # Channel 1: Google GTX Fast Endpoint (Zero config, supports JP/EN/KO/Auto -> zh-CN)
        try:
            q = urllib.parse.quote(prepared)
            url = (
                f"https://translate.googleapis.com/translate_a/single"
                f"?client=gtx&sl={sl}&tl={tl}&dt=t&q={q}"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            with urllib.request.urlopen(req, timeout=4.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, list) and data and isinstance(data[0], list):
                    joined = "".join(seg[0] for seg in data[0] if seg and seg[0])
                    if joined.strip():
                        return self._restore_placeholders(joined.strip(), placeholders)
        except Exception:
            pass

        # Channel 2: Google dict-chrome-ex Mirror Endpoint
        try:
            q = urllib.parse.quote(prepared)
            url2 = (
                f"https://clients5.google.com/translate_a/t"
                f"?client=dict-chrome-ex&sl={sl}&tl={tl}&q={q}"
            )
            req2 = urllib.request.Request(
                url2,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req2, timeout=4.5) as resp2:
                data2 = json.loads(resp2.read().decode("utf-8"))
                if isinstance(data2, list) and data2:
                    first = data2[0]
                    if isinstance(first, list) and first:
                        return self._restore_placeholders(str(first[0]).strip(), placeholders)
                    if isinstance(first, str):
                        return self._restore_placeholders(first.strip(), placeholders)
        except Exception:
            pass

        # Channel 3: MyMemory Public Translation API Fallback
        try:
            src_mm = sl if sl != "auto" else self._guess_lang(text)
            langpair = urllib.parse.quote(f"{src_mm}|{tl}")
            q = urllib.parse.quote(prepared)
            url3 = f"https://api.mymemory.translated.net/get?q={q}&langpair={langpair}"
            req3 = urllib.request.Request(url3, headers={"User-Agent": "AniLingo/1.0"})
            with urllib.request.urlopen(req3, timeout=5.0) as resp3:
                data3 = json.loads(resp3.read().decode("utf-8"))
                t_text = data3.get("responseData", {}).get("translatedText", "")
                if t_text:
                    return self._restore_placeholders(str(t_text).strip(), placeholders)
        except Exception:
            pass

        return self._restore_placeholders(prepared, placeholders)

    def _translate_via_llm(self, text: str, glossary: Dict[str, str]) -> str:
        cfg = self.cfg_mgr.config
        base = cfg.llm_api_base.rstrip("/")
        if not base.endswith("/chat/completions"):
            endpoint = f"{base}/chat/completions"
        else:
            endpoint = base

        # Filter relevant glossary terms + top custom entries
        matched_terms = [f"{k} -> {v}" for k, v in glossary.items() if k.lower() in text.lower()]
        if len(matched_terms) < 20:
            for k, v in list(glossary.items())[:20]:
                pair = f"{k} -> {v}"
                if pair not in matched_terms:
                    matched_terms.append(pair)

        sys_parts = [cfg.llm_anime_prompt.strip()]
        sys_parts.append(f"目标语言：{cfg.target_lang}。")
        if matched_terms:
            sys_parts.append("必须严格遵循以下番剧专有名词/人名译法：\n" + "\n".join(matched_terms))

        with self._lock:
            recent = list(self._context_window[-4:])

        if recent:
            ctx_lines = [f"原文：{o} => 译文：{t}" for o, t in recent]
            sys_parts.append("前文台词参考（仅用于保持人称与语境连贯，不要重复输出前文）：\n" + "\n".join(ctx_lines))

        payload = {
            "model": cfg.llm_model.strip() or "deepseek-chat",
            "messages": [
                {"role": "system", "content": "\n\n".join(sys_parts)},
                {"role": "user", "content": text},
            ],
            "temperature": 0.25,
            "max_tokens": 256,
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.llm_api_key.strip()}",
                "User-Agent": "AniLingo/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            content = body["choices"][0]["message"]["content"].strip()
            content = content.strip("「」『』\"'")
            return content

    @staticmethod
    def _guess_lang(text: str) -> str:
        # Check Japanese Hiragana / Katakana
        if re.search(r"[\u3040-\u30ff]", text):
            return "ja"
        # Check Korean Hangul
        if re.search(r"[\uac00-\ud7af]", text):
            return "ko"
        # Check Cyrillic
        if re.search(r"[\u0400-\u04ff]", text):
            return "ru"
        return "en"
