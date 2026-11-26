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

    var translatedText: String = "番译姬悬浮歌词就绪"
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
        val availW = max(dp(140f), targetW - dp(28f))
        val (fontPx, lines) = computeAdaptiveFontAndLines(translatedText, availW)
        val lineH = fontPx * 1.24f
        val showOrig = styleConfig.bilingual && originalText.isNotBlank() && originalText != translatedText
        val origH = if (showOrig) fontPx * 0.62f * 1.35f + dp(4f) else 0f
        val desiredH = (lines.size * lineH + origH + dp(20f)).toInt().coerceAtLeast(dp(52f).toInt())
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
        bgRect.set(dp(4f), dp(2f), width - dp(4f), height - dp(2f))

        if (st.bgAlpha > 0) {
            bgPaint.color = Color.argb(st.bgAlpha.coerceIn(0, 235), 16, 19, 30)
            canvas.drawRoundRect(bgRect, dp(16f), dp(16f), bgPaint)
        }

        val availW = max(dp(120f), width - dp(28f))
        val (mainPx, lines) = computeAdaptiveFontAndLines(translatedText, availW)
        val showOrig = st.bilingual && originalText.isNotBlank() && originalText != translatedText
        val origPx = max(sp(11f), mainPx * 0.58f)

        val mainStep = mainPx * 1.22f
        val totalH = lines.size * mainStep + (if (showOrig) origPx * 1.3f + dp(3f) else 0f)
        var baselineY = (height - totalH) / 2f + mainPx * 0.86f

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
            )
            baselineY += mainStep
        }

        if (showOrig) {
            fillPaint.textSize = origPx
            val elided = TextUtils.ellipsize(originalText, fillPaint, availW, TextUtils.TruncateAt.END).toString()
            val origY = baselineY - mainStep + origPx * 1.18f + dp(3f)
            drawLyricsTextLine(
                canvas = canvas,
                text = elided,
                textPx = origPx,
                centerX = width / 2f,
                baselineY = origY,
                colorTop = st.origColor,
                colorBottom = st.origColor,
                strokeColor = st.strokeColor,
                strokeWidthPx = max(dp(1.4f), dp(st.strokeWidthDp) * 0.65f),
            )
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
    ) {
        strokePaint.textSize = textPx
        fillPaint.textSize = textPx
        val tw = fillPaint.measureText(text)
        val x = centerX - tw / 2f

        // Pass 1: Smooth outer stroke + soft shadow
        if (strokeWidthPx > 0.3f) {
            strokePaint.strokeWidth = strokeWidthPx * 2f
            strokePaint.color = strokeColor
            strokePaint.setShadowLayer(dp(3.5f), dp(1f), dp(1.6f), Color.argb(175, 0, 0, 0))
            canvas.drawText(text, x, baselineY, strokePaint)
        }

        // Pass 2: Vertical LinearGradient fill (desktop music lyrics look)
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

    private val dimPaint = Paint().apply { color = Color.argb(115, 10, 14, 24) }
    private val clearPaint = Paint().apply { xfermode = PorterDuffXfermode(PorterDuff.Mode.CLEAR) }
    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 6f
        color = if (mode == "mark_region") Color.parseColor("#7CE8FF") else Color.parseColor("#FF80BF")
        pathEffect = DashPathEffect(floatArrayOf(18f, 10f), 0f)
    }
    private val bannerBgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.argb(225, 20, 24, 38) }
    private val bannerTxtPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.parseColor("#FFD4EA")
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
