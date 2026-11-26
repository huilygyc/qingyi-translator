package com.anilingo.translator.engine

import android.util.LruCache
import com.anilingo.translator.model.AppStateBus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/**
 * Multi-channel Anime Subtitle Translator for Android:
 * 1. Optional Desktop LAN Bridge (shares PC glossary & DeepSeek/Free engine)
 * 2. Optional DeepSeek / OpenAI-compatible LLM with Anime Fansub Prompt & rolling context
 * 3. Built-in Zero-Config Multi-Source Free Translator (Google GTX + Mirror + MyMemory fallback)
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

        // Channel A: Desktop PC LAN Bridge if configured
        if (cfg.transEngine == "pc_lan" && cfg.pcLanUrl.isNotBlank()) {
            result = runCatching { translateViaPcLan(cfg.pcLanUrl, clean) }.getOrDefault("")
        }

        // Channel B: DeepSeek / OpenAI-compatible LLM
        if (result.isBlank() && cfg.transEngine == "deepseek" && cfg.llmApiKey.isNotBlank()) {
            result = runCatching { translateViaLlm(clean, glossary) }.getOrDefault("")
        }

        // Channel C: Zero-Config Multi-Source Free Channels (Default & Failover)
        if (result.isBlank()) {
            result = translateViaFreeChannels(clean, glossary)
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
        val json = JSONObject(body)
        val gObj = json.optJSONObject("glossary") ?: return@withContext 0
        val keys = gObj.keys()
        var count = 0
        while (keys.hasNext()) {
            val k = keys.next()
            val v = gObj.optString(k)
            if (k.isNotBlank() && v.isNotBlank()) count++
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
            if (orig.contains(src) && out.contains(src)) {
                out = out.replace(src, dst)
            }
        }
        return out.trim()
    }

    private fun translateViaFreeChannels(text: String, glossary: Map<String, String>): String {
        val cfg = AppStateBus.engineConfig.value
        val (prepared, placeholders) = preApplyGlossary(text, glossary)
        val sl = if (cfg.sourceLang == "auto") "auto" else cfg.sourceLang
        val tl = cfg.targetLang
        val q = URLEncoder.encode(prepared, "UTF-8")

        // 1. Google GTX Fast Endpoint
        runCatching {
            val url = URL("https://translate.googleapis.com/translate_a/single?client=gtx&sl=$sl&tl=$tl&dt=t&q=$q")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                connectTimeout = 4000
                readTimeout = 4000
                setRequestProperty("User-Agent", "Mozilla/5.0 (Linux; Android 14)")
            }
            val raw = conn.inputStream.bufferedReader().use(BufferedReader::readText)
            val arr = JSONArray(raw).optJSONArray(0)
            if (arr != null) {
                val sb = StringBuilder()
                for (i in 0 until arr.length()) {
                    val seg = arr.optJSONArray(i)?.optString(0)
                    if (!seg.isNullOrEmpty()) sb.append(seg)
                }
                if (sb.isNotBlank()) return restorePlaceholders(sb.toString().trim(), placeholders)
            }
        }

        // 2. MyMemory Fallback Endpoint
        runCatching {
            val srcGuess = if (sl == "auto") guessLang(text) else sl
            val pair = URLEncoder.encode("$srcGuess|$tl", "UTF-8")
            val url = URL("https://api.mymemory.translated.net/get?q=$q&langpair=$pair")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                connectTimeout = 4500
                readTimeout = 4500
            }
            val raw = conn.inputStream.bufferedReader().use(BufferedReader::readText)
            val t = JSONObject(raw).optJSONObject("responseData")?.optString("translatedText", "") ?: ""
            if (t.isNotBlank()) return restorePlaceholders(t.trim(), placeholders)
        }

        return restorePlaceholders(prepared, placeholders)
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
            append("你是资深二次元番剧字幕组翻译。将输入的外语台词自然地道地译为${cfg.targetLang}，贴合动漫人物口吻，只输出译文本身。")
            if (glossLines.isNotBlank()) {
                append("\n\n严格遵循以下专有名词/角色译名：\n").append(glossLines)
            }
            if (ctxLines.isNotBlank()) {
                append("\n\n前文语境参考（勿重复输出）：\n").append(ctxLines)
            }
        }

        val payload = JSONObject().apply {
            put("model", cfg.llmModel.ifBlank { "deepseek-chat" })
            put("temperature", 0.25)
            put("max_tokens", 220)
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
        val content = JSONObject(resp)
            .getJSONArray("choices")
            .getJSONObject(0)
            .getJSONObject("message")
            .getString("content")
        return content.trim().trim('「', '」', '"', '\'')
    }

    private fun translateViaPcLan(pcUrl: String, text: String): String {
        val endpoint = "${pcUrl.trim().trimEnd('/')}/api/translate"
        val conn = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 3500
            readTimeout = 4500
            setRequestProperty("Content-Type", "application/json")
        }
        val body = JSONObject().put("text", text).toString()
        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        val resp = conn.inputStream.bufferedReader().use { BufferedReader(InputStreamReader(conn.inputStream)).readText() }
        return JSONObject(resp).optString("translated", "").trim()
    }

    private fun guessLang(text: String): String {
        if (Regex("[\\u3040-\\u30FF]").containsMatchIn(text)) return "ja"
        if (Regex("[\\uAC00-\\uD7AF]").containsMatchIn(text)) return "ko"
        return "en"
    }
}
