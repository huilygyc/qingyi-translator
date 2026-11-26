package com.anilingo.translator.engine

import android.graphics.Bitmap
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * On-Device Offline Anime Subtitle OCR powered by Google ML Kit (Japanese Kana/Kanji + English/Latin + Korean).
 * Includes fast 32x12 luma thumbnail diffing & normalized edit-distance deduplication.
 */
class MobileOcrEngine {
    private val jpRecognizer by lazy {
        TextRecognition.getClient(JapaneseTextRecognizerOptions.Builder().build())
    }
    private val koRecognizer by lazy {
        TextRecognition.getClient(KoreanTextRecognizerOptions.Builder().build())
    }
    private val latinRecognizer by lazy {
        TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    }

    private var prevLumaThumb: IntArray? = null
    private var prevSubtitleText: String = ""

    fun resetDedup() {
        prevLumaThumb = null
        prevSubtitleText = ""
    }

    fun hasFrameChanged(bmp: Bitmap, threshold: Float = 4.0f): Boolean {
        val scaled = Bitmap.createScaledBitmap(bmp, 32, 12, true)
        val pixels = IntArray(32 * 12)
        scaled.getPixels(pixels, 0, 32, 0, 0, 32, 12)
        if (scaled !== bmp) scaled.recycle()

        val luma = IntArray(pixels.size) { idx ->
            val c = pixels[idx]
            val r = (c shr 16) and 0xFF
            val g = (c shr 8) and 0xFF
            val b = c and 0xFF
            (r * 3 + g * 4 + b) shr 3
        }

        val prev = prevLumaThumb
        if (prev == null) {
            prevLumaThumb = luma
            return true
        }
        var diffSum = 0
        for (i in luma.indices) {
            diffSum += abs(luma[i] - prev[i])
        }
        val mad = diffSum.toFloat() / luma.size
        if (mad < threshold) return false
        prevLumaThumb = luma
        return true
    }

    suspend fun recognizeBitmap(bitmap: Bitmap, langCode: String): String =
        suspendCancellableCoroutine { cont ->
            val recognizer = when (langCode) {
                "ko" -> koRecognizer
                "en" -> latinRecognizer
                else -> jpRecognizer // Japanese recognizer natively recognizes BOTH Japanese + English/Latin!
            }
            val image = InputImage.fromBitmap(bitmap, 0)
            recognizer.process(image)
                .addOnSuccessListener { visionText ->
                    val lines = visionText.textBlocks
                        .sortedBy { it.boundingBox?.top ?: 0 }
                        .flatMap { it.lines }
                        .map { it.text.trim() }
                        .filter { it.isNotEmpty() }
                    val merged = lines.joinToString(" ").trim()
                    if (cont.isActive) cont.resume(merged)
                }
                .addOnFailureListener {
                    if (cont.isActive) cont.resume("")
                }
        }

    fun isDistinctNewSubtitle(text: String, currentDisplayedTranslation: String): Boolean {
        val clean = text.trim()
        if (clean.isEmpty()) return false
        // Guard against accidental self-capture if translated Chinese text overlaps
        if (currentDisplayedTranslation.isNotBlank() && clean.contains(currentDisplayedTranslation.take(6))) {
            return false
        }
        if (prevSubtitleText.isEmpty()) {
            prevSubtitleText = clean
            return true
        }
        if (clean == prevSubtitleText) return false
        val sim = similarity(clean, prevSubtitleText)
        if (sim >= 0.86f) return false
        prevSubtitleText = clean
        return true
    }

    private fun similarity(a: String, b: String): Float {
        val maxLen = max(a.length, b.length)
        if (maxLen == 0) return 1.0f
        val dp = IntArray(b.length + 1) { it }
        for (i in 1..a.length) {
            var prevDiag = dp[0]
            dp[0] = i
            for (j in 1..b.length) {
                val temp = dp[j]
                val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                dp[j] = min(min(dp[j] + 1, dp[j - 1] + 1), prevDiag + cost)
                prevDiag = temp
            }
        }
        return 1.0f - dp[b.length].toFloat() / maxLen.toFloat()
    }
}
