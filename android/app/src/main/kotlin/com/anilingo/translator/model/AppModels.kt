package com.anilingo.translator.model

import android.content.Context
import android.graphics.Color
import android.graphics.RectF
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONArray
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
        key = "sakura_fansub",
        title = "樱雪番剧（无底沉浸）",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#FFD4E8"),
        origColor = Color.parseColor("#E6ECF5"),
        strokeColor = Color.parseColor("#2B1838"),
        strokeWidthDp = 3.2f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "cloud_cyan",
        title = "云音乐流光青",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#7CE8FF"),
        origColor = Color.parseColor("#D8F6FF"),
        strokeColor = Color.parseColor("#0A253B"),
        strokeWidthDp = 3.3f,
        bgAlpha = 34,
    ),
    LyricsPreset(
        key = "amber_gold",
        title = "琥珀流金（奇幻番剧）",
        colorTop = Color.parseColor("#FFFDF5"),
        colorBottom = Color.parseColor("#FFCA63"),
        origColor = Color.parseColor("#F3E5C8"),
        strokeColor = Color.parseColor("#261708"),
        strokeWidthDp = 3.4f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "fansub_classic",
        title = "经典字幕组（深海蓝边）",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#F0F6FF"),
        origColor = Color.parseColor("#DCE8FA"),
        strokeColor = Color.parseColor("#143666"),
        strokeWidthDp = 3.5f,
        bgAlpha = 0,
    ),
    LyricsPreset(
        key = "mint_neon",
        title = "薄荷霓虹（高对比清透）",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#80FFDB"),
        origColor = Color.parseColor("#D8FFF3"),
        strokeColor = Color.parseColor("#0B2E26"),
        strokeWidthDp = 3.2f,
        bgAlpha = 26,
    ),
    LyricsPreset(
        key = "soft_pill",
        title = "柔光磨砂胶囊底",
        colorTop = Color.parseColor("#FFFFFF"),
        colorBottom = Color.parseColor("#EAEFFA"),
        origColor = Color.parseColor("#C2CBE0"),
        strokeColor = Color.parseColor("#000000"),
        strokeWidthDp = 1.8f,
        bgAlpha = 155,
    ),
)

data class MobileLyricsStyle(
    val presetKey: String = "sakura_fansub",
    val baseFontSp: Float = 21f,
    val autoScaleFont: Boolean = true,
    val bilingual: Boolean = true,
    val colorTop: Int = Color.parseColor("#FFFFFF"),
    val colorBottom: Int = Color.parseColor("#FFD4E8"),
    val origColor: Int = Color.parseColor("#E6ECF5"),
    val strokeColor: Int = Color.parseColor("#2B1838"),
    val strokeWidthDp: Float = 3.2f,
    val shadowRadiusDp: Float = 4.0f,
    val bgAlpha: Int = 0,
    val lockedClickThrough: Boolean = false,
)

data class MobileEngineConfig(
    val transEngine: String = "auto_free", // "auto_free" | "deepseek" | "pc_lan"
    val sourceLang: String = "ja",         // "ja" | "en" | "ko" | "auto"
    val targetLang: String = "zh-CN",
    val llmApiBase: String = "https://api.deepseek.com/v1",
    val llmApiKey: String = "",
    val llmModel: String = "deepseek-chat",
    val pcLanUrl: String = "",             // e.g. http://192.168.1.10:18765
    val audioSource: String = "mic",       // "mic" (说话/外放) | "internal" (手机系统内录)
    val whisperCloudBase: String = "",
    val whisperCloudKey: String = "",
    val pollIntervalMs: Long = 650L,
)

data class SubtitleRecord(
    val id: Long,
    val source: String,
    val original: String,
    val translated: String,
)

/**
 * Shared reactive state bus & SharedPreferences persistence across Compose UI and WindowManager Service.
 */
object AppStateBus {
    private const val PREF_NAME = "anilingo_prefs"

    private val _overlayRunning = MutableStateFlow(false)
    val overlayRunning: StateFlow<Boolean> = _overlayRunning.asStateFlow()

    private val _liveScreenActive = MutableStateFlow(false)
    val liveScreenActive: StateFlow<Boolean> = _liveScreenActive.asStateFlow()

    private val _liveAudioActive = MutableStateFlow(false)
    val liveAudioActive: StateFlow<Boolean> = _liveAudioActive.asStateFlow()

    private val _currentOriginal = MutableStateFlow("アニメ字幕・音声リアルタイム翻訳")
    val currentOriginal: StateFlow<String> = _currentOriginal.asStateFlow()

    private val _currentTranslated = MutableStateFlow("番译姬手机端就绪 · 点悬浮字幕可框选抓词 / 截屏翻译 / 改词")
    val currentTranslated: StateFlow<String> = _currentTranslated.asStateFlow()

    private val _statusText = MutableStateFlow("就绪 · 支持全局悬浮歌词、屏幕区域翻译与手机内录/说话听译")
    val statusText: StateFlow<String> = _statusText.asStateFlow()

    private val _style = MutableStateFlow(MobileLyricsStyle())
    val style: StateFlow<MobileLyricsStyle> = _style.asStateFlow()

    private val _engineConfig = MutableStateFlow(MobileEngineConfig())
    val engineConfig: StateFlow<MobileEngineConfig> = _engineConfig.asStateFlow()

    // Normalized screen region [0..1] so portrait & landscape anime playback both map cleanly
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
            presetKey = sp.getString("presetKey", "sakura_fansub") ?: "sakura_fansub",
            baseFontSp = sp.getFloat("baseFontSp", 21f),
            autoScaleFont = sp.getBoolean("autoScaleFont", true),
            bilingual = sp.getBoolean("bilingual", true),
            colorTop = sp.getInt("colorTop", Color.parseColor("#FFFFFF")),
            colorBottom = sp.getInt("colorBottom", Color.parseColor("#FFD4E8")),
            origColor = sp.getInt("origColor", Color.parseColor("#E6ECF5")),
            strokeColor = sp.getInt("strokeColor", Color.parseColor("#2B1838")),
            strokeWidthDp = sp.getFloat("strokeWidthDp", 3.2f),
            bgAlpha = sp.getInt("bgAlpha", 0),
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
            pollIntervalMs = sp.getLong("pollIntervalMs", 650L),
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

    fun publishSubtitle(source: String, original: String, translated: String) {
        val o = original.trim()
        val t = translated.trim()
        _currentOriginal.value = o
        _currentTranslated.value = t
        val rec = SubtitleRecord(System.currentTimeMillis(), source, o, t)
        _history.value = (_history.value + rec).takeLast(120)
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
            publishSubtitle("manual", newOrig, newTrans)
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
