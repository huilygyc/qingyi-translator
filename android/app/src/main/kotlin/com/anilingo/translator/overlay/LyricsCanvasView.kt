package com.anilingo.translator.overlay

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.text.TextPaint
import android.text.TextUtils
import android.util.TypedValue
import android.view.MotionEvent
import android.view.View
import com.anilingo.translator.model.MobileLyricsStyle
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

/**
 * Custom Canvas renderer producing NetEase / QQ Music Desktop-Lyrics style subtitles:
 * - True alpha zero-box background (or soft pill capsule when bgAlpha > 0)
 * - Auto-adaptive font sizing & balanced 2-line wrapping so long anime lines never look jarring
 * - Smooth round-join outer vector stroke + soft shadow + vertical LinearGradient fill
 */
class LyricsCanvasView(context: Context) : View(context) {

    var originalText: String = ""
        set(value) {
            field = value
            requestLayout()
            invalidate()
        }

    var translatedText: String = "轻译悬浮字幕就绪"
        set(value) {
            field = value
            requestLayout()
            invalidate()
        }

    var previousTranslatedText: String = ""
        set(value) {
            field = value
            requestLayout()
            invalidate()
        }

    var danmakuLines: List<String> = emptyList()
        set(value) {
            field = value
            requestLayout()
            invalidate()
        }

    var styleConfig: MobileLyricsStyle = MobileLyricsStyle()
        set(value) {
            field = value
            requestLayout()
            invalidate()
        }

    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val chipBorderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2f
        color = Color.argb(46, 255, 255, 255)
    }
    private val strokePaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeJoin = Paint.Join.ROUND
        strokeCap = Paint.Cap.ROUND
        typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
    }
    private val fillPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        typeface = Typeface.create(Typeface.SANS_SERIF, Typeface.BOLD)
    }
    private val bgRect = RectF()

    private fun dp(v: Float): Float =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics)

    private fun sp(v: Float): Float =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, v, resources.displayMetrics)

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) {
        val screenW = resources.displayMetrics.widthPixels
        val targetW = when (MeasureSpec.getMode(widthMeasureSpec)) {
            MeasureSpec.EXACTLY -> MeasureSpec.getSize(widthMeasureSpec)
            MeasureSpec.AT_MOST -> min(MeasureSpec.getSize(widthMeasureSpec), (screenW * 0.90f).toInt())
            else -> (screenW * 0.88f).toInt()
        }
        val availW = max(dp(140f), targetW - dp(32f))
        if (styleConfig.displayMode == "danmaku") {
            val dmPx = max(sp(13f), sp(styleConfig.baseFontSp) * 0.84f)
            val count = max(1, danmakuLines.size.coerceAtMost(3))
            val pillH = dmPx * 1.45f + dp(12f)
            val desiredH = (count * (pillH + dp(6f)) + dp(14f)).toInt().coerceAtLeast(dp(56f).toInt())
            setMeasuredDimension(targetW, desiredH)
            return
        }

        val (fontPx, lines) = computeAdaptiveFontAndLines(translatedText, availW)
        val lineH = fontPx * 1.24f
        val showOrig = styleConfig.bilingual && originalText.isNotBlank() && originalText != translatedText
        val showPrev = styleConfig.keepPrevLine && previousTranslatedText.isNotBlank() && previousTranslatedText != translatedText
        val origH = if (showOrig) fontPx * 0.60f * 1.35f + dp(4f) else 0f
        val prevH = if (showPrev) fontPx * 0.66f * 1.35f + dp(5f) else 0f
        // Keep stable minimum height for bottom anchoring so 1-line <-> 2-line transitions never jump
        val minAnchorH = if (styleConfig.anchorBottom) (fontPx * 2.55f + origH + dp(24f)).toInt() else dp(56f).toInt()
        val desiredH = (lines.size * lineH + origH + prevH + dp(24f)).toInt().coerceAtLeast(minAnchorH)
        setMeasuredDimension(targetW, desiredH)
    }

    private fun computeAdaptiveFontAndLines(text: String, availW: Float): Pair<Float, List<String>> {
        val clean = text.ifBlank { "…" }
        val basePx = sp(styleConfig.baseFontSp)
        val minPx = if (styleConfig.autoScaleFont) max(sp(13f), basePx * 0.64f) else basePx

        var px = basePx
        while (px >= minPx) {
            fillPaint.textSize = px
            val lines = wrapBalanced(clean, fillPaint, availW)
            val widest = lines.maxOfOrNull { fillPaint.measureText(it) } ?: 0f
            if (lines.size <= 2 && widest <= availW * 1.02f) {
                return px to lines
            }
            px -= dp(1.5f)
        }
        fillPaint.textSize = minPx
        return minPx to wrapBalanced(clean, fillPaint, availW)
    }

    private fun wrapBalanced(text: String, paint: TextPaint, maxW: Float): List<String> {
        if (paint.measureText(text) <= maxW) return listOf(text)
        val mid = text.length / 2
        var splitIdx = -1
        for (off in 0..min(12, mid)) {
            for (cand in listOf(mid - off, mid + off)) {
                if (cand in 1 until text.length && "，。！？、；…— ,.!?;:".contains(text[cand - 1])) {
                    splitIdx = cand
                    break
                }
            }
            if (splitIdx != -1) break
        }
        if (splitIdx != -1) {
            val l1 = text.substring(0, splitIdx).trim()
            val l2 = text.substring(splitIdx).trim()
            if (paint.measureText(l1) <= maxW * 1.06f && paint.measureText(l2) <= maxW * 1.06f) {
                return listOf(l1, l2)
            }
        }
        val out = mutableListOf<String>()
        val sb = StringBuilder()
        for (ch in text) {
            if (paint.measureText(sb.toString() + ch) > maxW && sb.isNotEmpty()) {
                out.add(sb.toString())
                sb.clear()
                sb.append(ch)
                if (out.size == 2) break
            } else {
                sb.append(ch)
            }
        }
        if (sb.isNotEmpty() && out.size < 3) out.add(sb.toString())
        return out.take(2)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val st = styleConfig
        if (st.displayMode == "danmaku") {
            drawDanmakuMode(canvas, st)
            return
        }

        val availW = max(dp(120f), width - dp(32f))
        val (mainPx, lines) = computeAdaptiveFontAndLines(translatedText, availW)
        val showOrig = st.bilingual && originalText.isNotBlank() && originalText != translatedText
        val showPrev = st.keepPrevLine && previousTranslatedText.isNotBlank() && previousTranslatedText != translatedText
        val origPx = max(sp(11f), mainPx * 0.58f)
        val prevPx = max(sp(12f), mainPx * 0.66f)

        val mainStep = mainPx * 1.22f
        val mainBlockH = lines.size * mainStep
        val origBlockH = if (showOrig) origPx * 1.30f + dp(3f) else 0f
        val prevBlockH = if (showPrev) prevPx * 1.30f + dp(5f) else 0f
        val activeH = mainBlockH + origBlockH

        // Bottom-anchored layout keeps 1-line and 2-line subtitles rock-steady on the same bottom horizon
        val activeTop = if (st.anchorBottom) {
            (height - activeH - dp(8f)).coerceAtLeast(prevBlockH + dp(4f))
        } else {
            (height - activeH) / 2f
        }

        // Compute exact widest line for snug fit-content capsule backdrop
        fillPaint.textSize = mainPx
        var maxRenderedW = lines.maxOfOrNull { fillPaint.measureText(it) } ?: 0f
        val elidedOrig = if (showOrig) {
            fillPaint.textSize = origPx
            val e = TextUtils.ellipsize(originalText, fillPaint, availW, TextUtils.TruncateAt.END).toString()
            maxRenderedW = max(maxRenderedW, fillPaint.measureText(e))
            e
        } else {
            ""
        }

        if (st.bgAlpha > 0) {
            bgPaint.color = Color.argb(st.bgAlpha.coerceIn(0, 235), 15, 23, 42)
            if (st.fitBgToText) {
                val pillW = min(width - dp(8f), maxRenderedW + dp(34f))
                val left = (width - pillW) / 2f
                bgRect.set(left, activeTop - dp(6f), left + pillW, activeTop + activeH + dp(6f))
            } else {
                bgRect.set(dp(4f), activeTop - dp(6f), width - dp(4f), activeTop + activeH + dp(6f))
            }
            canvas.drawRoundRect(bgRect, dp(16f), dp(16f), bgPaint)
        }

        // Optional faded previous line right above active subtitle
        if (showPrev) {
            fillPaint.textSize = prevPx
            val elidedPrev = TextUtils.ellipsize(previousTranslatedText, fillPaint, availW, TextUtils.TruncateAt.END).toString()
            val prevY = (activeTop - dp(6f) - prevPx * 0.20f).coerceAtLeast(prevPx + dp(2f))
            drawLyricsTextLine(
                canvas = canvas,
                text = elidedPrev,
                textPx = prevPx,
                centerX = width / 2f,
                baselineY = prevY,
                colorTop = Color.parseColor("#E2E8F0"),
                colorBottom = Color.parseColor("#CBD5E1"),
                strokeColor = st.strokeColor,
                strokeWidthPx = max(dp(1.2f), dp(st.strokeWidthDp) * 0.56f),
                alphaScale = 0.60f,
            )
        }

        var baselineY = activeTop + mainPx * 0.88f
        for (ln in lines) {
            drawLyricsTextLine(
                canvas = canvas,
                text = ln,
                textPx = mainPx,
                centerX = width / 2f,
                baselineY = baselineY,
                colorTop = st.colorTop,
                colorBottom = st.colorBottom,
                strokeColor = st.strokeColor,
                strokeWidthPx = dp(st.strokeWidthDp),
                alphaScale = 1f,
            )
            baselineY += mainStep
        }

        if (showOrig && elidedOrig.isNotBlank()) {
            val origY = activeTop + mainBlockH + origPx * 0.96f + dp(2f)
            drawLyricsTextLine(
                canvas = canvas,
                text = elidedOrig,
                textPx = origPx,
                centerX = width / 2f,
                baselineY = origY,
                colorTop = st.origColor,
                colorBottom = st.origColor,
                strokeColor = st.strokeColor,
                strokeWidthPx = max(dp(1.4f), dp(st.strokeWidthDp) * 0.62f),
                alphaScale = 1f,
            )
        }
    }

    private fun drawDanmakuMode(canvas: Canvas, st: MobileLyricsStyle) {
        val items = danmakuLines.ifEmpty { listOf(translatedText) }.takeLast(3)
        val dmPx = max(sp(13f), sp(st.baseFontSp) * 0.84f)
        val availW = max(dp(120f), width - dp(44f))
        var yBottom = height - dp(6f)
        items.reversed().forEachIndexed { idx, raw ->
            fillPaint.textSize = dmPx
            val txt = TextUtils.ellipsize(raw, fillPaint, availW, TextUtils.TruncateAt.END).toString()
            val tw = fillPaint.measureText(txt)
            val pillH = dmPx * 1.45f + dp(10f)
            val pillW = min(width - dp(12f), tw + dp(30f))
            val top = yBottom - pillH
            if (top < dp(2f)) return@forEachIndexed

            val op = when (idx) {
                0 -> 1.0f
                1 -> 0.68f
                else -> 0.42f
            }
            val left = (width - pillW) / 2f
            bgRect.set(left, top, left + pillW, yBottom)
            bgPaint.color = Color.argb((max(142, st.bgAlpha) * op).toInt().coerceIn(0, 235), 15, 23, 42)
            canvas.drawRoundRect(bgRect, pillH / 2f, pillH / 2f, bgPaint)
            canvas.drawRoundRect(bgRect, pillH / 2f, pillH / 2f, chipBorderPaint)

            val baseline = top + (pillH + dmPx * 0.72f) / 2f
            drawLyricsTextLine(
                canvas = canvas,
                text = txt,
                textPx = dmPx,
                centerX = width / 2f,
                baselineY = baseline,
                colorTop = st.colorTop,
                colorBottom = st.colorBottom,
                strokeColor = st.strokeColor,
                strokeWidthPx = min(dp(2.2f), dp(st.strokeWidthDp)),
                alphaScale = op,
            )
            yBottom = top - dp(6f)
        }
    }

    private fun drawLyricsTextLine(
        canvas: Canvas,
        text: String,
        textPx: Float,
        centerX: Float,
        baselineY: Float,
        colorTop: Int,
        colorBottom: Int,
        strokeColor: Int,
        strokeWidthPx: Float,
        alphaScale: Float = 1f,
    ) {
        val alphaInt = (255f * alphaScale.coerceIn(0f, 1f)).toInt()
        strokePaint.textSize = textPx
        fillPaint.textSize = textPx
        val tw = fillPaint.measureText(text)
        val x = centerX - tw / 2f

        // Pass 1: Soft outer shadow + smooth round-join stroke
        if (strokeWidthPx > 0.3f) {
            strokePaint.strokeWidth = strokeWidthPx * 2f
            strokePaint.color = strokeColor
            strokePaint.alpha = alphaInt
            strokePaint.setShadowLayer(dp(4.8f), dp(0.8f), dp(1.8f), Color.argb((165 * alphaScale).toInt(), 0, 0, 0))
            canvas.drawText(text, x, baselineY, strokePaint)
        }

        // Pass 2: Vertical LinearGradient fill
        fillPaint.alpha = alphaInt
        fillPaint.shader = LinearGradient(
            0f,
            baselineY - textPx * 0.88f,
            0f,
            baselineY + textPx * 0.20f,
            colorTop,
            colorBottom,
            Shader.TileMode.CLAMP
        )
        canvas.drawText(text, x, baselineY, fillPaint)
        fillPaint.shader = null
    }
}

/**
 * Full-screen interactive drag-box overlay for marking live anime subtitle region OR one-shot snip translation.
 */
class RegionPickerOverlayView(
    context: Context,
    private val mode: String, // "mark_region" | "snip"
    private val onSelected: (normRect: RectF) -> Unit,
    private val onCancel: () -> Unit,
) : View(context) {

    private var startX = 0f
    private var startY = 0f
    private var curX = 0f
    private var curY = 0f
    private var dragging = false

    private val dimPaint = Paint().apply { color = Color.argb(105, 15, 23, 42) }
    private val clearPaint = Paint().apply { xfermode = PorterDuffXfermode(PorterDuff.Mode.CLEAR) }
    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 6f
        color = Color.parseColor("#2563EB")
        pathEffect = DashPathEffect(floatArrayOf(18f, 10f), 0f)
    }
    private val bannerBgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(242, 255, 255, 255) }
    private val bannerTxtPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#1E293B")
        textSize = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, 14f, resources.displayMetrics)
        typeface = Typeface.DEFAULT_BOLD
        textAlign = Paint.Align.CENTER
    }

    init {
        setLayerType(LAYER_TYPE_SOFTWARE, null)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                startX = event.x
                startY = event.y
                curX = event.x
                curY = event.y
                dragging = true
                invalidate()
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                curX = event.x
                curY = event.y
                invalidate()
                return true
            }
            MotionEvent.ACTION_UP -> {
                dragging = false
                val l = min(startX, curX)
                val t = min(startY, curY)
                val r = max(startX, curX)
                val b = max(startY, curY)
                if (abs(r - l) < 40f || abs(b - t) < 28f) {
                    onCancel()
                } else {
                    val w = width.coerceAtLeast(1).toFloat()
                    val h = height.coerceAtLeast(1).toFloat()
                    onSelected(
                        RectF(
                            (l / w).coerceIn(0f, 0.98f),
                            (t / h).coerceIn(0f, 0.98f),
                            (r / w).coerceIn(0.02f, 1f),
                            (b / h).coerceIn(0.02f, 1f),
                        )
                    )
                }
                return true
            }
        }
        return super.onTouchEvent(event)
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.drawRect(0f, 0f, width.toFloat(), height.toFloat(), dimPaint)

        val tip = if (mode == "mark_region") {
            "手指拖拽框选【看番实时字幕区域】（轻点空白取消）"
        } else {
            "手指拖拽框选要【截屏翻译】的外语画面（轻点空白取消）"
        }
        val bw = min(width * 0.90f, 920f)
        val br = RectF((width - bw) / 2f, 90f, (width + bw) / 2f, 178f)
        canvas.drawRoundRect(br, 44f, 44f, bannerBgPaint)
        canvas.drawText(tip, width / 2f, 145f, bannerTxtPaint)

        if (dragging) {
            val sel = RectF(min(startX, curX), min(startY, curY), max(startX, curX), max(startY, curY))
            canvas.drawRect(sel, clearPaint)
            canvas.drawRect(sel, borderPaint)
        }
    }
}
