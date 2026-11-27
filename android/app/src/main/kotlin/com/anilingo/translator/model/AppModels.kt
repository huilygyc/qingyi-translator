package com.anilingo.translator.model

import android.content.Context
import android.graphics.Color
import android.graphics.RectF
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject

data class LyricsPreset(
    val key: String,
    val title: String,
    val colorTop: Int,
    val colorBottom: Int,
    val origColor: Int,
    val strokeColor: Int,
    val strokeWidthDp: Float,
    val bgAlpha: Int,
)

val MOBILE_LYRICS_PRESETS: List<LyricsPreset> = listOf(
    LyricsPreset(
        key = "clean_cinema",
        title = "纯净电影白（默认）",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#F1F5F9"),
        origColor = Color.parseColor("#E2E8F0"),
        strokeColor = Color.parseColor("#1E293B"),
        strokeWidthDp = 3.2f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "cloud_cyan",
        title = "晴空冰蓝",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#BAE6FD"),
        origColor = Color.parseColor("#E0F2FE"),
        strokeColor = Color.parseColor("#0F2942"),
        strokeWidthDp = 3.3f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "amber_gold",
        title = "暖调柔和黄",
        colorTop = Color.parseColor("#FFFBEB"),
        colorBottom = Color.parseColor("#FDE68A"),
        origColor = Color.parseColor("#F3F4F6"),
        strokeColor = Color.parseColor("#1F242D"),
        strokeWidthDp = 3.3f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "fansub_classic",
        title = "字幕组深蓝边",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#F8FAFC"),
        origColor = Color.parseColor("#E2E8F0"),
        strokeColor = Color.parseColor("#1E3A5F"),
        strokeWidthDp = 3.5f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "mint_neon",
        title = "清爽薄荷青",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#A7F3D0"),
        origColor = Color.parseColor("#ECFDF5"),
        strokeColor = Color.parseColor("#132A24"),
        strokeWidthDp = 3.2f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "soft_pill",
        title = "半透灰底条",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#F8FAFC"),
        origColor = Color.parseColor("#CBD5E1"),
        strokeColor = Color.parseColor("#0F172A"),
        strokeWidthDp = 1.8f,
        bgAlpha = 148,
    ),
)

data class MobileLyricsStyle(
    val presetKey: String = "clean_cinema",
    val baseFontSp: Float = 20f,
    val autoScaleFont: Boolean = true,
    val bilingual: Boolean = true,
    val colorTop: Int = Color.parseColor("#FFFFFF"),
    val colorBottom: Int = Color.parseColor("#F1F5F9"),
    val origColor: Int = Color.parseColor("#E2E8F0"),
    val strokeColor: Int = Color.parseColor("#1E293B"),
    val strokeWidthDp: Float = 3.2f,
    val shadowRadiusDp: Float = 3.8f,
    val bgAlpha: Int = 0,
    val fitBgToText: Boolean = true,
    val anchorBottom: Boolean = true,
    val keepPrevLine: Boolean = true,
    val displayMode: String = "subtitle", // "subtitle" | "danmaku"
    val autoHideSeconds: Int = 6,
    val lockedClickThrough: Boolean = false,
)

data class MobileEngineConfig(
    val transEngine: String = "auto_free", // "auto_free" | "cn_direct" | "deepseek" | "pc_lan"
    val sourceLang: String = "ja",         // "ja" | "en" | "ko" | "auto"
    val targetLang: String = "zh-CN",
    val llmApiBase: String = "https://api.deepseek.com/v1",
    val llmApiKey: String = "",
    val llmModel: String = "deepseek-chat",
    val pcLanUrl: String = "",
    val audioSource: String = "mic",       // "mic" | "internal"
    val whisperCloudBase: String = "",
    val whisperCloudKey: String = "",
    val pollIntervalMs: Long = 350L,
)

data class SubtitleRecord(
    val id: Long,
    val source: String,
    val original: String,
    val translated: String,
)

object AppStateBus {
    private const val PREF_NAME = "qingyi_prefs_v2"

    private val _overlayRunning = MutableStateFlow(false)
    val overlayRunning: StateFlow<Boolean> = _overlayRunning.asStateFlow()

    private val _liveScreenActive = MutableStateFlow(false)
    val liveScreenActive: StateFlow<Boolean> = _liveScreenActive.asStateFlow()

    private val _liveAudioActive = MutableStateFlow(false)
    val liveAudioActive: StateFlow<Boolean> = _liveAudioActive.asStateFlow()

    private val _currentOriginal = MutableStateFlow("Subtitles ready")
    val currentOriginal: StateFlow<String> = _currentOriginal.asStateFlow()

    private val _currentTranslated = MutableStateFlow("悬浮字幕已就绪，轻触可展开控制条")
    val currentTranslated: StateFlow<String> = _currentTranslated.asStateFlow()

    private val _previousTranslated = MutableStateFlow("")
    val previousTranslated: StateFlow<String> = _previousTranslated.asStateFlow()

    private val _recentLines = MutableStateFlow<List<String>>(emptyList())
    val recentLines: StateFlow<List<String>> = _recentLines.asStateFlow()

    private val _subtitleFrozen = MutableStateFlow(false)
    val subtitleFrozen: StateFlow<Boolean> = _subtitleFrozen.asStateFlow()

    private val _statusText = MutableStateFlow("就绪")
    val statusText: StateFlow<String> = _statusText.asStateFlow()

    private val _style = MutableStateFlow(MobileLyricsStyle())
    val style: StateFlow<MobileLyricsStyle> = _style.asStateFlow()

    private val _engineConfig = MutableStateFlow(MobileEngineConfig())
    val engineConfig: StateFlow<MobileEngineConfig> = _engineConfig.asStateFlow()

    private val _captureRegionNorm = MutableStateFlow(RectF(0.08f, 0.72f, 0.92f, 0.91f))
    val captureRegionNorm: StateFlow<RectF> = _captureRegionNorm.asStateFlow()

    private val _glossary = MutableStateFlow(
        linkedMapOf(
            "フリーレン" to "芙莉莲",
            "Frieren" to "芙莉莲",
            "ヒンメル" to "辛美尔",
            "Himmel" to "辛美尔",
            "フェルン" to "菲伦",
            "Fern" to "菲伦",
            "シュタルク" to "休塔尔克",
            "Stark" to "休塔尔克",
        )
    )
    val glossary: StateFlow<Map<String, String>> = _glossary.asStateFlow()

    private val _history = MutableStateFlow<List<SubtitleRecord>>(emptyList())
    val history: StateFlow<List<SubtitleRecord>> = _history.asStateFlow()

    private var initialized = false

    fun init(context: Context) {
        if (initialized) return
        initialized = true
        val sp = context.applicationContext.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        _style.value = MobileLyricsStyle(
            presetKey = sp.getString("presetKey", "clean_cinema") ?: "clean_cinema",
            baseFontSp = sp.getFloat("baseFontSp", 20f),
            autoScaleFont = sp.getBoolean("autoScaleFont", true),
            bilingual = sp.getBoolean("bilingual", true),
            colorTop = sp.getInt("colorTop", Color.parseColor("#FFFFFF")),
            colorBottom = sp.getInt("colorBottom", Color.parseColor("#F1F5F9")),
            origColor = sp.getInt("origColor", Color.parseColor("#E2E8F0")),
            strokeColor = sp.getInt("strokeColor", Color.parseColor("#1E293B")),
            strokeWidthDp = sp.getFloat("strokeWidthDp", 3.2f),
            bgAlpha = sp.getInt("bgAlpha", 0),
            fitBgToText = sp.getBoolean("fitBgToText", true),
            anchorBottom = sp.getBoolean("anchorBottom", true),
            keepPrevLine = sp.getBoolean("keepPrevLine", true),
            displayMode = sp.getString("displayMode", "subtitle") ?: "subtitle",
            autoHideSeconds = sp.getInt("autoHideSeconds", 6),
            lockedClickThrough = false,
        )
        _engineConfig.value = MobileEngineConfig(
            transEngine = sp.getString("transEngine", "auto_free") ?: "auto_free",
            sourceLang = sp.getString("sourceLang", "ja") ?: "ja",
            targetLang = sp.getString("targetLang", "zh-CN") ?: "zh-CN",
            llmApiBase = sp.getString("llmApiBase", "https://api.deepseek.com/v1") ?: "https://api.deepseek.com/v1",
            llmApiKey = sp.getString("llmApiKey", "") ?: "",
            llmModel = sp.getString("llmModel", "deepseek-chat") ?: "deepseek-chat",
            pcLanUrl = sp.getString("pcLanUrl", "") ?: "",
            audioSource = sp.getString("audioSource", "mic") ?: "mic",
            whisperCloudBase = sp.getString("whisperCloudBase", "") ?: "",
            whisperCloudKey = sp.getString("whisperCloudKey", "") ?: "",
            pollIntervalMs = sp.getLong("pollIntervalMs", 350L),
        )
        _captureRegionNorm.value = RectF(
            sp.getFloat("regL", 0.08f),
            sp.getFloat("regT", 0.72f),
            sp.getFloat("regR", 0.92f),
            sp.getFloat("regB", 0.91f),
        )
        val glossJson = sp.getString("glossaryJson", null)
        if (!glossJson.isNullOrBlank()) {
            runCatching {
                val obj = JSONObject(glossJson)
                val map = linkedMapOf<String, String>()
                val keys = obj.keys()
                while (keys.hasNext()) {
                    val k = keys.next()
                    map[k] = obj.getString(k)
                }
                if (map.isNotEmpty()) _glossary.value = map
            }
        }
    }

    fun saveAll(context: Context) {
        val sp = context.applicationContext.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)
        val st = _style.value
        val ec = _engineConfig.value
        val reg = _captureRegionNorm.value
        val gObj = JSONObject()
        _glossary.value.forEach { (k, v) -> gObj.put(k, v) }

        sp.edit()
            .putString("presetKey", st.presetKey)
            .putFloat("baseFontSp", st.baseFontSp)
            .putBoolean("autoScaleFont", st.autoScaleFont)
            .putBoolean("bilingual", st.bilingual)
            .putInt("colorTop", st.colorTop)
            .putInt("colorBottom", st.colorBottom)
            .putInt("origColor", st.origColor)
            .putInt("strokeColor", st.strokeColor)
            .putFloat("strokeWidthDp", st.strokeWidthDp)
            .putInt("bgAlpha", st.bgAlpha)
            .putBoolean("fitBgToText", st.fitBgToText)
            .putBoolean("anchorBottom", st.anchorBottom)
            .putBoolean("keepPrevLine", st.keepPrevLine)
            .putString("displayMode", st.displayMode)
            .putInt("autoHideSeconds", st.autoHideSeconds)
            .putString("transEngine", ec.transEngine)
            .putString("sourceLang", ec.sourceLang)
            .putString("targetLang", ec.targetLang)
            .putString("llmApiBase", ec.llmApiBase)
            .putString("llmApiKey", ec.llmApiKey)
            .putString("llmModel", ec.llmModel)
            .putString("pcLanUrl", ec.pcLanUrl)
            .putString("audioSource", ec.audioSource)
            .putString("whisperCloudBase", ec.whisperCloudBase)
            .putString("whisperCloudKey", ec.whisperCloudKey)
            .putLong("pollIntervalMs", ec.pollIntervalMs)
            .putFloat("regL", reg.left)
            .putFloat("regT", reg.top)
            .putFloat("regR", reg.right)
            .putFloat("regB", reg.bottom)
            .putString("glossaryJson", gObj.toString())
            .apply()
    }

    fun updateStyle(context: Context, transform: (MobileLyricsStyle) -> MobileLyricsStyle) {
        _style.value = transform(_style.value)
        saveAll(context)
    }

    fun applyPreset(context: Context, preset: LyricsPreset) {
        _style.value = _style.value.copy(
            presetKey = preset.key,
            colorTop = preset.colorTop,
            colorBottom = preset.colorBottom,
            origColor = preset.origColor,
            strokeColor = preset.strokeColor,
            strokeWidthDp = preset.strokeWidthDp,
            bgAlpha = preset.bgAlpha,
        )
        saveAll(context)
    }

    fun cycleNextPreset(context: Context): LyricsPreset {
        val curIdx = MOBILE_LYRICS_PRESETS.indexOfFirst { it.key == _style.value.presetKey }
        val next = MOBILE_LYRICS_PRESETS[(curIdx + 1) % MOBILE_LYRICS_PRESETS.size]
        applyPreset(context, next)
        return next
    }

    fun updateEngineConfig(context: Context, transform: (MobileEngineConfig) -> MobileEngineConfig) {
        _engineConfig.value = transform(_engineConfig.value)
        saveAll(context)
    }

    fun updateCaptureRegion(context: Context, normRect: RectF) {
        _captureRegionNorm.value = normRect
        saveAll(context)
    }

    fun setOverlayRunning(running: Boolean) {
        _overlayRunning.value = running
    }

    fun setLiveScreenActive(active: Boolean) {
        _liveScreenActive.value = active
    }

    fun setLiveAudioActive(active: Boolean) {
        _liveAudioActive.value = active
    }

    fun setStatus(msg: String) {
        _statusText.value = msg
    }

    fun setSubtitleFrozen(frozen: Boolean) {
        _subtitleFrozen.value = frozen
    }

    fun clearPreviousTranslated() {
        _previousTranslated.value = ""
    }

    fun publishSubtitle(source: String, original: String, translated: String) {
        val o = original.trim()
        val t = translated.trim()
        if (t.isEmpty()) return
        val rec = SubtitleRecord(System.currentTimeMillis(), source, o, t)
        _history.value = (_history.value + rec).takeLast(120)
        if (_subtitleFrozen.value) return

        val oldT = _currentTranslated.value
        if (oldT.isNotBlank() && oldT != t && !oldT.startsWith("悬浮字幕已就绪") && _style.value.keepPrevLine) {
            _previousTranslated.value = oldT
        }
        _currentOriginal.value = o
        _currentTranslated.value = t
        val nextRecent = (_recentLines.value.filterNot { it == t } + t).takeLast(3)
        _recentLines.value = nextRecent
    }

    fun mergeGlossary(context: Context, incoming: Map<String, String>): Int {
        if (incoming.isEmpty()) return 0
        val next = LinkedHashMap(_glossary.value)
        var added = 0
        incoming.forEach { (k, v) ->
            val ks = k.trim()
            val vs = v.trim()
            if (ks.isNotEmpty() && vs.isNotEmpty()) {
                if (next[ks] != vs) added++
                next[ks] = vs
            }
        }
        _glossary.value = next
        saveAll(context)
        return added
    }

    fun editCurrentSubtitle(newOrig: String, newTrans: String) {
        _currentOriginal.value = newOrig.trim()
        _currentTranslated.value = newTrans.trim()
        val curList = _history.value.toMutableList()
        if (curList.isNotEmpty()) {
            val last = curList.last()
            curList[curList.lastIndex] = last.copy(original = newOrig.trim(), translated = newTrans.trim())
            _history.value = curList
        } else {
            publishSubtitle("手动", newOrig, newTrans)
        }
    }

    fun putGlossaryTerm(context: Context, src: String, dst: String) {
        val s = src.trim()
        val d = dst.trim()
        if (s.isEmpty() || d.isEmpty()) return
        val next = LinkedHashMap(_glossary.value)
        next[s] = d
        _glossary.value = next
        saveAll(context)
    }

    fun removeGlossaryTerm(context: Context, src: String) {
        val next = LinkedHashMap(_glossary.value)
        next.remove(src)
        _glossary.value = next
        saveAll(context)
    }
}
