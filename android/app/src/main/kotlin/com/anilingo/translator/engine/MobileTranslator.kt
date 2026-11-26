package com.anilingo.translator.engine

import android.text.Html
import android.util.LruCache
import com.anilingo.translator.model.AppStateBus
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Low-Latency Concurrent-Racing Translator for Android:
 * - 'auto_free': Races Google dict-chrome + China-direct Youdao Mobile concurrently (first valid wins!)
 * - 'cn_direct': Mainland China zero-proxy direct (Youdao Mobile + MyMemory)
 * - 'deepseek': DeepSeek / OpenAI-compatible LLM with context & anime glossary
 * - 'pc_lan': Desktop LAN Companion Bridge
 */
object MobileTranslator {
    private val cache = LruCache<String, String>(400)
    private val recentDialogue = ArrayDeque<Pair<String, String>>()

    fun clearCache() {
        cache.evictAll()
    }

    suspend fun translate(rawText: String, forceRefresh: Boolean = false): String = withContext(Dispatchers.IO) {
        val clean = rawText.replace(Regex("\\s+"), " ").trim()
        if (clean.isEmpty()) return@withContext ""

        val cfg = AppStateBus.engineConfig.value
        val glossary = AppStateBus.glossary.value
        glossary[clean]?.let { return@withContext it }

        val cacheKey = "${cfg.transEngine}:${cfg.sourceLang}->${cfg.targetLang}:${glossary.size}::$clean"
        if (!forceRefresh) {
            cache.get(cacheKey)?.let { return@withContext it }
        }

        var result = ""
        if (cfg.transEngine == "pc_lan" && cfg.pcLanUrl.isNotBlank()) {
            result = runCatching { translateViaPcLan(cfg.pcLanUrl, clean) }.getOrDefault("")
        }
        if (result.isBlank() && cfg.transEngine == "deepseek" && cfg.llmApiKey.isNotBlank()) {
            result = runCatching { translateViaLlm(clean, glossary) }.getOrDefault("")
        }
        if (result.isBlank()) {
            result = translateViaFreeRacing(clean, glossary, cfg.transEngine)
        }

        val postFixed = postApplyGlossary(clean, result, glossary)
        if (postFixed.isNotBlank()) {
            cache.put(cacheKey, postFixed)
            synchronized(recentDialogue) {
                recentDialogue.addLast(clean to postFixed)
                while (recentDialogue.size > 4) recentDialogue.removeFirst()
            }
        }
        postFixed.ifBlank { clean }
    }

    suspend fun syncGlossaryFromPcLan(pcLanUrl: String): Int = withContext(Dispatchers.IO) {
        val base = pcLanUrl.trim().trimEnd('/')
        if (base.isEmpty()) return@withContext 0
        val conn = (URL("$base/api/glossary").openConnection() as HttpURLConnection).apply {
            connectTimeout = 3500
            readTimeout = 3500
            requestMethod = "GET"
        }
        val body = conn.inputStream.bufferedReader().use(BufferedReader::readText)
        val gObj = JSONObject(body).optJSONObject("glossary") ?: return@withContext 0
        var count = 0
        val keys = gObj.keys()
        while (keys.hasNext()) {
            val k = keys.next()
            if (k.isNotBlank() && gObj.optString(k).isNotBlank()) count++
        }
        count
    }

    private fun preApplyGlossary(text: String, glossary: Map<String, String>): Pair<String, List<Pair<String, String>>> {
        var out = text
        val placeholders = mutableListOf<Pair<String, String>>()
        glossary.entries.sortedByDescending { it.key.length }.forEach { (src, dst) ->
            if (src.isNotBlank()) {
                val idx = placeholders.size.toString()
                val token = "[#$idx#]"
                val replaced = if (src.matches(Regex("^[A-Za-z0-9_ ]+$"))) {
                    out.replace(Regex("\\b${Regex.escape(src)}\\b", RegexOption.IGNORE_CASE), token)
                } else {
                    out.replace(src, token)
                }
                if (replaced != out) {
                    out = replaced
                    placeholders.add(idx to dst)
                }
            }
        }
        return out to placeholders
    }

    private fun restorePlaceholders(translated: String, placeholders: List<Pair<String, String>>): String {
        var out = translated
        placeholders.forEach { (idx, dst) ->
            val regex = Regex("[\\[\\uFF3B【]\\s*[#\\uFF03]\\s*${Regex.escape(idx)}\\s*[#\\uFF03]\\s*[\\]\\uFF3D】]")
            out = out.replace(regex, dst)
        }
        return out
    }

    private fun postApplyGlossary(orig: String, trans: String, glossary: Map<String, String>): String {
        var out = trans
        glossary.entries.sortedByDescending { it.key.length }.forEach { (src, dst) ->
            if (orig.contains(src) && out.contains(src)) out = out.replace(src, dst)
        }
        return out.trim()
    }

    private suspend fun raceCallers(callers: List<() -> String>): String = coroutineScope {
        val winner = CompletableDeferred<String>()
        val jobs = callers.map { fn ->
            launch(Dispatchers.IO) {
                val res = runCatching { fn() }.getOrDefault("")
                if (res.isNotBlank()) winner.complete(res)
            }
        }
        val result = withTimeoutOrNull(3200L) {
            launch {
                jobs.forEach { it.join() }
                if (!winner.isCompleted) winner.complete("")
            }
            winner.await()
        } ?: ""
        jobs.forEach { it.cancel() }
        result
    }

    private suspend fun translateViaFreeRacing(text: String, glossary: Map<String, String>, mode: String): String {
        val cfg = AppStateBus.engineConfig.value
        val (prepared, placeholders) = preApplyGlossary(text, glossary)
        val sl = if (cfg.sourceLang == "auto") "auto" else cfg.sourceLang
        val tl = cfg.targetLang

        val winner = if (mode == "cn_direct") {
            raceCallers(listOf({ callYoudaoMobile(prepared, sl, tl) }, { callMyMemory(prepared, sl, tl) }))
        } else {
            val fast = raceCallers(listOf({ callGoogleChromeDict(prepared, sl, tl) }, { callYoudaoMobile(prepared, sl, tl) }))
            fast.ifBlank {
                raceCallers(listOf({ callGoogleGtx(prepared, sl, tl) }, { callMyMemory(prepared, sl, tl) }))
            }
        }
        return restorePlaceholders(winner.ifBlank { prepared }, placeholders)
    }

    private fun callGoogleChromeDict(prepared: String, sl: String, tl: String): String {
        val q = URLEncoder.encode(prepared, "UTF-8")
        val conn = (URL("https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=$sl&tl=$tl&q=$q").openConnection() as HttpURLConnection).apply {
            connectTimeout = 2200
            readTimeout = 2200
            setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14)")
        }
        val raw = conn.inputStream.bufferedReader().use(BufferedReader::readText)
        val arr = JSONArray(raw)
        if (arr.length() > 0) {
            val first = arr.get(0)
            if (first is JSONArray && first.length() > 0) return first.getString(0).trim()
            if (first is String) return first.trim()
        }
        return ""
    }

    private fun callGoogleGtx(prepared: String, sl: String, tl: String): String {
        val q = URLEncoder.encode(prepared, "UTF-8")
        val conn = (URL("https://translate.googleapis.com/translate_a/single?client=gtx&sl=$sl&tl=$tl&dt=t&q=$q").openConnection() as HttpURLConnection).apply {
            connectTimeout = 2500
            readTimeout = 2500
            setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14)")
        }
        val raw = conn.inputStream.bufferedReader().use(BufferedReader::readText)
        val arr = JSONArray(raw).optJSONArray(0) ?: return ""
        val sb = StringBuilder()
        for (i in 0 until arr.length()) {
            arr.optJSONArray(i)?.optString(0)?.let { sb.append(it) }
        }
        return sb.toString().trim()
    }

    private fun callYoudaoMobile(prepared: String, sl: String, tl: String): String {
        if (!tl.startsWith("zh")) return ""
        val guessed = if (sl == "auto") guessLang(prepared) else sl
        val ydType = when (guessed) {
            "ja" -> "JA2ZH_CN"
            "en" -> "EN2ZH_CN"
            "ko" -> "KR2ZH_CN"
            else -> "AUTO"
        }
        val form = "inputtext=${URLEncoder.encode(prepared, "UTF-8")}&type=$ydType"
        val conn = (URL("https://m.youdao.com/translate").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 2800
            readTimeout = 2800
            setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
            setRequestProperty("Referer", "https://m.youdao.com/translate")
            setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14)")
            setRequestProperty("Connection", "close")
        }
        conn.outputStream.use { it.write(form.toByteArray(Charsets.UTF_8)) }
        val page = conn.inputStream.bufferedReader().use(BufferedReader::readText)
        val m = Regex("""<ul id="translateResult">\s*<li>(.*?)</li>""", RegexOption.DOT_MATCHES_ALL).find(page)
        val rawVal = m?.groupValues?.getOrNull(1) ?: return ""
        val plain = Html.fromHtml(rawVal, Html.FROM_HTML_MODE_LEGACY).toString().trim()
        return if (plain.isNotBlank() && plain != prepared) plain else ""
    }

    private fun callMyMemory(prepared: String, sl: String, tl: String): String {
        val srcGuess = if (sl == "auto") guessLang(prepared) else sl
        val pair = URLEncoder.encode("$srcGuess|$tl", "UTF-8")
        val q = URLEncoder.encode(prepared, "UTF-8")
        val conn = (URL("https://api.mymemory.translated.net/get?q=$q&langpair=$pair").openConnection() as HttpURLConnection).apply {
            connectTimeout = 3500
            readTimeout = 3500
        }
        val raw = conn.inputStream.bufferedReader().use(BufferedReader::readText)
        return JSONObject(raw).optJSONObject("responseData")?.optString("translatedText", "")?.trim() ?: ""
    }

    private fun translateViaLlm(text: String, glossary: Map<String, String>): String {
        val cfg = AppStateBus.engineConfig.value
        val base = cfg.llmApiBase.trim().trimEnd('/')
        val endpoint = if (base.endsWith("/chat/completions")) base else "$base/chat/completions"

        val glossLines = glossary.entries.take(25).joinToString("\n") { "${it.key} -> ${it.value}" }
        val ctxLines = synchronized(recentDialogue) {
            recentDialogue.joinToString("\n") { "原文：${it.first} => 译文：${it.second}" }
        }
        val sysPrompt = buildString {
            append("你是资深字幕翻译。将外语台词自然地道地译为${cfg.targetLang}，只输出译文本身。")
            if (glossLines.isNotBlank()) append("\n\n专有名词译法：\n").append(glossLines)
            if (ctxLines.isNotBlank()) append("\n\n前文参考（勿重复输出）：\n").append(ctxLines)
        }

        val payload = JSONObject().apply {
            put("model", cfg.llmModel.ifBlank { "deepseek-chat" })
            put("temperature", 0.2)
            put("max_tokens", 200)
            put(
                "messages",
                JSONArray()
                    .put(JSONObject().put("role", "system").put("content", sysPrompt))
                    .put(JSONObject().put("role", "user").put("content", text))
            )
        }
        val conn = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 7000
            readTimeout = 7000
            setRequestProperty("Content-Type", "application/json")
            setRequestProperty("Authorization", "Bearer ${cfg.llmApiKey.trim()}")
        }
        conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
        val resp = conn.inputStream.bufferedReader().use(BufferedReader::readText)
        return JSONObject(resp)
            .getJSONArray("choices")
            .getJSONObject(0)
            .getJSONObject("message")
            .getString("content")
            .trim()
            .trim('「', '」', '"', '\'')
    }

    private fun translateViaPcLan(pcUrl: String, text: String): String {
        val endpoint = "${pcUrl.trim().trimEnd('/')}/api/translate"
        val conn = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 3000
            readTimeout = 4000
            setRequestProperty("Content-Type", "application/json")
        }
        conn.outputStream.use { it.write(JSONObject().put("text", text).toString().toByteArray(Charsets.UTF_8)) }
        val resp = conn.inputStream.bufferedReader().use(BufferedReader::readText)
        return JSONObject(resp).optString("translated", "").trim()
    }

    private fun guessLang(text: String): String {
        if (Regex("[\\u3040-\\u30FF]").containsMatchIn(text)) return "ja"
        if (Regex("[\\uAC00-\\uD7AF]").containsMatchIn(text)) return "ko"
        return "en"
    }
}
