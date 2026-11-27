package com.anilingo.translator.overlay

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.RectF
import android.graphics.drawable.GradientDrawable
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.IBinder
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import com.anilingo.translator.MainActivity
import com.anilingo.translator.engine.MobileAudioEngine
import com.anilingo.translator.engine.MobileOcrEngine
import com.anilingo.translator.engine.MobileTranslator
import com.anilingo.translator.model.AppStateBus
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.abs

/**
 * System-wide Floating Lyrics & Screen/Audio Real-time Translator Service.
 * Floats cleanly above Bilibili, MX Player, VLC, YouTube, Netflix, browsers, or games.
 */
class FloatingTranslatorService : Service() {

    companion object {
        const val ACTION_START_OVERLAY = "com.anilingo.action.START_OVERLAY"
        const val ACTION_STOP_OVERLAY = "com.anilingo.action.STOP_OVERLAY"
        const val ACTION_GRANT_PROJECTION = "com.anilingo.action.GRANT_PROJECTION"
        const val ACTION_START_REGION_PICKER = "com.anilingo.action.START_REGION_PICKER"
        const val ACTION_START_SNIP = "com.anilingo.action.START_SNIP"
        const val ACTION_TOGGLE_LIVE_SCREEN = "com.anilingo.action.TOGGLE_LIVE_SCREEN"
        const val ACTION_TOGGLE_AUDIO = "com.anilingo.action.TOGGLE_AUDIO"
        const val ACTION_UNLOCK_TOUCH = "com.anilingo.action.UNLOCK_TOUCH"

        const val EXTRA_RESULT_CODE = "extra_result_code"
        const val EXTRA_RESULT_DATA = "extra_result_data"
        const val EXTRA_AFTER_PROJECTION = "extra_after_projection"

        private const val NOTIF_CHANNEL_ID = "anilingo_floating_channel"
        private const val NOTIF_ID = 2026
    }

    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private lateinit var windowManager: WindowManager
    private val ocrEngine = MobileOcrEngine()
    private lateinit var audioEngine: MobileAudioEngine

    private var rootContainer: LinearLayout? = null
    private var toolbarScroll: HorizontalScrollView? = null
    private var lyricsView: LyricsCanvasView? = null
    private var overlayParams: WindowManager.LayoutParams? = null

    private var unlockBadgeView: TextView? = null
    private var unlockBadgeParams: WindowManager.LayoutParams? = null

    private var pickerView: RegionPickerOverlayView? = null
    private var editCardView: View? = null

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private var screenLoopJob: Job? = null
    private var autoHideJob: Job? = null
    private var prevClearJob: Job? = null
    private var freezeChipView: TextView? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        AppStateBus.init(this)
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        audioEngine = MobileAudioEngine(this, serviceScope) { src, orig ->
            serviceScope.launch {
                val trans = MobileTranslator.translate(orig)
                AppStateBus.publishSubtitle(src, orig, trans)
            }
        }
        createNotificationChannel()
        startSafeForeground(includeMediaProjection = false, includeMicrophone = false)
        setupFloatingLyricsOverlay()
        observeReactiveState()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP_OVERLAY -> {
                stopSelf()
                return START_NOT_STICKY
            }
            ACTION_GRANT_PROJECTION -> {
                val code = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
                val data: Intent? = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(EXTRA_RESULT_DATA, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(EXTRA_RESULT_DATA)
                }
                val followUp = intent.getStringExtra(EXTRA_AFTER_PROJECTION) ?: "live_screen"
                if (code == Activity.RESULT_OK && data != null) {
                    initMediaProjection(code, data, followUp)
                }
            }
            ACTION_START_REGION_PICKER -> showRegionPicker("mark_region")
            ACTION_START_SNIP -> {
                if (mediaProjection == null) {
                    requestProjectionViaActivity("snip")
                } else {
                    showRegionPicker("snip")
                }
            }
            ACTION_TOGGLE_LIVE_SCREEN -> toggleLiveScreen()
            ACTION_TOGGLE_AUDIO -> toggleAudio()
            ACTION_UNLOCK_TOUCH -> setClickThroughLock(false)
        }
        return START_STICKY
    }

    private fun startSafeForeground(includeMediaProjection: Boolean, includeMicrophone: Boolean) {
        val notif = buildNotification()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            var fgType = ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            if (includeMediaProjection) fgType = fgType or ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            if (includeMicrophone) fgType = fgType or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
            startForeground(NOTIF_ID, notif, fgType)
        } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val fgType = if (includeMediaProjection) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
            } else {
                0
            }
            if (fgType != 0) startForeground(NOTIF_ID, notif, fgType) else startForeground(NOTIF_ID, notif)
        } else {
            startForeground(NOTIF_ID, notif)
        }
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val chan = NotificationChannel(
                NOTIF_CHANNEL_ID,
                "轻译悬浮字幕服务",
                NotificationManager.IMPORTANCE_LOW
            )
            val nm = getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(chan)
        }
    }

    private fun buildNotification(): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val unlockIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, FloatingTranslatorService::class.java).apply { action = ACTION_UNLOCK_TOUCH },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val builder = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            Notification.Builder(this, NOTIF_CHANNEL_ID)
        } else {
            @Suppress("DEPRECATION")
            Notification.Builder(this)
        }
        return builder
            .setSmallIcon(android.R.drawable.ic_menu_sort_alphabetically)
            .setContentTitle("轻译 正在运行")
            .setContentText("点击返回控制面板 · 若开启穿透锁定可点下方解锁")
            .setContentIntent(openIntent)
            .addAction(
                Notification.Action.Builder(null, "解锁悬浮窗穿透", unlockIntent).build()
            )
            .setOngoing(true)
            .build()
    }

    private fun dp(v: Float): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics).toInt()

    private fun setupFloatingLyricsOverlay() {
        if (!Settings.canDrawOverlays(this)) {
            AppStateBus.setStatus("请先授予全局悬浮窗权限")
            stopSelf()
            return
        }

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
        }

        val barScroll = HorizontalScrollView(this).apply {
            isHorizontalScrollBarEnabled = false
            visibility = View.GONE
            background = GradientDrawable().apply {
                setColor(Color.argb(242, 255, 255, 255))
                cornerRadius = dp(16f).toFloat()
                setStroke(dp(1f), Color.parseColor("#CBD5E1"))
            }
            setPadding(dp(8f), dp(3f), dp(8f), dp(3f))
        }

        val barRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        fun makeActionChip(label: String, onClick: () -> Unit): TextView {
            return TextView(this).apply {
                text = label
                setTextColor(Color.parseColor("#1E293B"))
                textSize = 12f
                setPadding(dp(8f), dp(5f), dp(8f), dp(5f))
                setOnClickListener { onClick() }
            }
        }

        barRow.addView(makeActionChip("框选") { showRegionPicker("mark_region") })
        barRow.addView(makeActionChip("盯屏") { toggleLiveScreen() })
        barRow.addView(makeActionChip("截屏") {
            if (mediaProjection == null) requestProjectionViaActivity("snip") else showRegionPicker("snip")
        })
        barRow.addView(makeActionChip("听译") { toggleAudio() })
        barRow.addView(makeActionChip("复制") {
            val txt = AppStateBus.currentTranslated.value
            if (txt.isNotBlank()) {
                val cm = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                cm.setPrimaryClip(ClipData.newPlainText("QingYiSubtitle", txt))
                Toast.makeText(this, "已复制译文", Toast.LENGTH_SHORT).show()
            }
        })
        val fChip = makeActionChip("冻住") {
            val next = !AppStateBus.subtitleFrozen.value
            AppStateBus.setSubtitleFrozen(next)
            Toast.makeText(this, if (next) "字幕已冻住" else "已恢复实时更新", Toast.LENGTH_SHORT).show()
        }
        freezeChipView = fChip
        barRow.addView(fChip)
        barRow.addView(makeActionChip("主题") {
            val preset = AppStateBus.cycleNextPreset(this)
            Toast.makeText(this, "主题：${preset.title}", Toast.LENGTH_SHORT).show()
        })
        barRow.addView(makeActionChip("改词") { showFloatingEditDialog() })
        barRow.addView(makeActionChip("穿透") { setClickThroughLock(true) })
        barRow.addView(makeActionChip("关闭") { stopSelf() })
        barScroll.addView(barRow)

        val lView = LyricsCanvasView(this).apply {
            originalText = AppStateBus.currentOriginal.value
            translatedText = AppStateBus.currentTranslated.value
            styleConfig = AppStateBus.style.value
        }

        container.addView(
            barScroll,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                bottomMargin = dp(4f)
            }
        )
        container.addView(
            lView,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
        )

        val dm = resources.displayMetrics
        val params = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = (dm.widthPixels * 0.06f).toInt()
            y = (dm.heightPixels * 0.72f).toInt()
        }

        // Drag to move + tap to toggle mini-toolbar
        var downRawX = 0f
        var downRawY = 0f
        var startWinX = 0
        var startWinY = 0
        var moved = false

        lView.setOnTouchListener { _, ev ->
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downRawX = ev.rawX
                    downRawY = ev.rawY
                    startWinX = params.x
                    startWinY = params.y
                    moved = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = (ev.rawX - downRawX).toInt()
                    val dy = (ev.rawY - downRawY).toInt()
                    if (abs(dx) > dp(5f) || abs(dy) > dp(5f)) moved = true
                    if (moved) {
                        params.x = startWinX + dx
                        params.y = startWinY + dy
                        runCatching { windowManager.updateViewLayout(container, params) }
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (!moved) {
                        barScroll.visibility = if (barScroll.visibility == View.VISIBLE) View.GONE else View.VISIBLE
                    }
                    true
                }
                else -> false
            }
        }

        windowManager.addView(container, params)
        rootContainer = container
        toolbarScroll = barScroll
        lyricsView = lView
        overlayParams = params
        AppStateBus.setOverlayRunning(true)
    }

    private fun observeReactiveState() {
        serviceScope.launch {
            AppStateBus.currentOriginal.collectLatest { orig ->
                lyricsView?.originalText = orig
            }
        }
        serviceScope.launch {
            AppStateBus.currentTranslated.collectLatest { trans ->
                lyricsView?.let { lv ->
                    lv.translatedText = trans
                    lv.animate().cancel()
                    lv.alpha = 0.25f
                    lv.translationY = dp(6f).toFloat()
                    lv.animate().alpha(1f).translationY(0f).setDuration(160L).start()
                }
                autoHideJob?.cancel()
                val sec = AppStateBus.style.value.autoHideSeconds
                if (sec > 0 && trans.isNotBlank() && !AppStateBus.subtitleFrozen.value) {
                    autoHideJob = serviceScope.launch {
                        delay(sec * 1000L)
                        if (toolbarScroll?.visibility != View.VISIBLE && !AppStateBus.subtitleFrozen.value) {
                            lyricsView?.animate()?.alpha(0f)?.setDuration(300L)?.start()
                        }
                    }
                }
            }
        }
        serviceScope.launch {
            AppStateBus.previousTranslated.collectLatest { prev ->
                lyricsView?.previousTranslatedText = prev
                prevClearJob?.cancel()
                if (prev.isNotBlank()) {
                    prevClearJob = serviceScope.launch {
                        delay(3200L)
                        AppStateBus.clearPreviousTranslated()
                    }
                }
            }
        }
        serviceScope.launch {
            AppStateBus.recentLines.collectLatest { list ->
                lyricsView?.danmakuLines = list
            }
        }
        serviceScope.launch {
            AppStateBus.subtitleFrozen.collectLatest { frozen ->
                freezeChipView?.text = if (frozen) "已冻住" else "冻住"
                freezeChipView?.setTextColor(Color.parseColor(if (frozen) "#2563EB" else "#1E293B"))
                if (frozen) {
                    autoHideJob?.cancel()
                    lyricsView?.animate()?.alpha(1f)?.setDuration(120L)?.start()
                }
            }
        }
        serviceScope.launch {
            AppStateBus.style.collectLatest { st ->
                lyricsView?.styleConfig = st
            }
        }
    }

    private fun setClickThroughLock(locked: Boolean) {
        val container = rootContainer ?: return
        val params = overlayParams ?: return
        AppStateBus.updateStyle(this) { it.copy(lockedClickThrough = locked) }

        if (locked) {
            toolbarScroll?.visibility = View.GONE
            params.flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
            runCatching { windowManager.updateViewLayout(container, params) }
            showEdgeUnlockBadge()
            Toast.makeText(this, "已开启穿透锁定，点击右侧「解锁」按钮即可恢复", Toast.LENGTH_SHORT).show()
        } else {
            params.flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN
            runCatching { windowManager.updateViewLayout(container, params) }
            removeEdgeUnlockBadge()
            Toast.makeText(this, "悬浮字幕已解锁", Toast.LENGTH_SHORT).show()
        }
    }

    private fun showEdgeUnlockBadge() {
        if (unlockBadgeView != null) return
        val badge = TextView(this).apply {
            text = "解锁"
            textSize = 11.5f
            setTextColor(Color.parseColor("#2563EB"))
            setPadding(dp(10f), dp(6f), dp(10f), dp(6f))
            background = GradientDrawable().apply {
                setColor(Color.argb(235, 255, 255, 255))
                cornerRadius = dp(14f).toFloat()
                setStroke(dp(1f), Color.parseColor("#93C5FD"))
            }
            setOnClickListener { setClickThroughLock(false) }
        }
        val bParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = dp(4f)
            y = (resources.displayMetrics.heightPixels * 0.45f).toInt()
        }
        runCatching {
            windowManager.addView(badge, bParams)
            unlockBadgeView = badge
            unlockBadgeParams = bParams
        }
    }

    private fun removeEdgeUnlockBadge() {
        unlockBadgeView?.let { runCatching { windowManager.removeView(it) } }
        unlockBadgeView = null
    }

    // --- MediaProjection Screen Capture & Snip OCR ---
    private fun requestProjectionViaActivity(followUp: String) {
        val actIntent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
            putExtra("request_projection", followUp)
        }
        startActivity(actIntent)
    }

    private fun initMediaProjection(resultCode: Int, data: Intent, followUp: String) {
        startSafeForeground(includeMediaProjection = true, includeMicrophone = false)
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjection?.stop()
        val proj = mpm.getMediaProjection(resultCode, data) ?: return
        proj.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                stopLiveScreenCapture()
                mediaProjection = null
            }
        }, null)
        mediaProjection = proj
        ensureVirtualDisplay()

        when (followUp) {
            "snip" -> showRegionPicker("snip")
            "internal_audio" -> startAudioInternalMode()
            else -> startLiveScreenLoop()
        }
    }

    private fun ensureVirtualDisplay() {
        val proj = mediaProjection ?: return
        virtualDisplay?.release()
        imageReader?.close()

        val dm = resources.displayMetrics
        val w = dm.widthPixels
        val h = dm.heightPixels
        val reader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
        val vd = proj.createVirtualDisplay(
            "AniLingoScreenCap",
            w,
            h,
            dm.densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface,
            null,
            null
        )
        imageReader = reader
        virtualDisplay = vd
    }

    private fun grabCroppedScreenBitmap(normRect: RectF): Bitmap? {
        val reader = imageReader ?: return null
        val image = reader.acquireLatestImage() ?: return null
        return try {
            val plane = image.planes[0]
            val buffer = plane.buffer
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - pixelStride * image.width

            val fullBmp = Bitmap.createBitmap(
                image.width + rowPadding / pixelStride,
                image.height,
                Bitmap.Config.ARGB_8888
            )
            fullBmp.copyPixelsFromBuffer(buffer)

            val left = (normRect.left * image.width).toInt().coerceIn(0, image.width - 20)
            val top = (normRect.top * image.height).toInt().coerceIn(0, image.height - 20)
            val right = (normRect.right * image.width).toInt().coerceIn(left + 16, image.width)
            val bottom = (normRect.bottom * image.height).toInt().coerceIn(top + 16, image.height)

            val cropped = Bitmap.createBitmap(fullBmp, left, top, right - left, bottom - top)
            fullBmp.recycle()
            cropped
        } catch (_: Throwable) {
            null
        } finally {
            image.close()
        }
    }

    private fun toggleLiveScreen() {
        if (AppStateBus.liveScreenActive.value) {
            stopLiveScreenCapture()
        } else {
            if (mediaProjection == null) {
                requestProjectionViaActivity("live_screen")
            } else {
                startLiveScreenLoop()
            }
        }
    }

    private fun startLiveScreenLoop() {
        screenLoopJob?.cancel()
        ocrEngine.resetDedup()
        ensureVirtualDisplay()
        AppStateBus.setLiveScreenActive(true)
        AppStateBus.setStatus("正在实时监控屏幕字幕区域")
        toolbarScroll?.visibility = View.GONE

        screenLoopJob = serviceScope.launch {
            while (isActive && AppStateBus.liveScreenActive.value) {
                val interval = AppStateBus.engineConfig.value.pollIntervalMs.coerceIn(350L, 2500L)
                val norm = AppStateBus.captureRegionNorm.value
                val crop = withContext(Dispatchers.Default) { grabCroppedScreenBitmap(norm) }
                if (crop != null) {
                    val changed = ocrEngine.hasFrameChanged(crop)
                    if (changed) {
                        val lang = AppStateBus.engineConfig.value.sourceLang
                        val raw = ocrEngine.recognizeBitmap(crop, lang)
                        if (raw.isNotBlank() && ocrEngine.isDistinctNewSubtitle(raw, AppStateBus.currentTranslated.value)) {
                            val trans = MobileTranslator.translate(raw)
                            AppStateBus.publishSubtitle("screen", raw, trans)
                        }
                    }
                    crop.recycle()
                }
                delay(interval)
            }
        }
    }

    private fun stopLiveScreenCapture() {
        screenLoopJob?.cancel()
        screenLoopJob = null
        AppStateBus.setLiveScreenActive(false)
        AppStateBus.setStatus("已停止屏幕实时盯屏")
    }

    private fun showRegionPicker(mode: String) {
        if (pickerView != null) return
        toolbarScroll?.visibility = View.GONE
        val pView = RegionPickerOverlayView(
            context = this,
            mode = mode,
            onSelected = { normRect ->
                removeRegionPicker()
                if (mode == "mark_region") {
                    AppStateBus.updateCaptureRegion(this, normRect)
                    Toast.makeText(this, "已保存实时字幕区域", Toast.LENGTH_SHORT).show()
                    if (mediaProjection != null && !AppStateBus.liveScreenActive.value) {
                        startLiveScreenLoop()
                    }
                } else {
                    performOneShotSnipTranslate(normRect)
                }
            },
            onCancel = { removeRegionPicker() }
        )
        val pParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        )
        windowManager.addView(pView, pParams)
        pickerView = pView
    }

    private fun removeRegionPicker() {
        pickerView?.let { runCatching { windowManager.removeView(it) } }
        pickerView = null
    }

    private fun performOneShotSnipTranslate(normRect: RectF) {
        serviceScope.launch {
            // Briefly hide floating lyrics for 90ms so single-shot snip captures pure underlying anime frame
            rootContainer?.alpha = 0f
            delay(100L)
            ensureVirtualDisplay()
            delay(80L)
            val crop = withContext(Dispatchers.Default) { grabCroppedScreenBitmap(normRect) }
            rootContainer?.alpha = 1f

            if (crop == null) {
                Toast.makeText(this@FloatingTranslatorService, "截屏读取失败，请重试", Toast.LENGTH_SHORT).show()
                return@launch
            }
            val orig = ocrEngine.recognizeBitmap(crop, AppStateBus.engineConfig.value.sourceLang)
            crop.recycle()
            if (orig.isBlank()) {
                Toast.makeText(this@FloatingTranslatorService, "选区内未检测到外语文字", Toast.LENGTH_SHORT).show()
                return@launch
            }
            val trans = MobileTranslator.translate(orig, forceRefresh = true)
            AppStateBus.publishSubtitle("snip", orig, trans)
        }
    }

    // --- Audio Real-time Translation (Mic + Internal Device Playback) ---
    private fun toggleAudio() {
        if (AppStateBus.liveAudioActive.value) {
            audioEngine.stopAll()
            AppStateBus.setLiveAudioActive(false)
            AppStateBus.setStatus("已停止声音实时听译")
        } else {
            val mode = AppStateBus.engineConfig.value.audioSource
            if (mode == "internal") {
                if (mediaProjection == null) {
                    requestProjectionViaActivity("internal_audio")
                } else {
                    startAudioInternalMode()
                }
            } else {
                startSafeForeground(includeMediaProjection = mediaProjection != null, includeMicrophone = true)
                AppStateBus.setLiveAudioActive(true)
                audioEngine.startMicrophoneRecognition()
            }
        }
    }

    private fun startAudioInternalMode() {
        startSafeForeground(includeMediaProjection = true, includeMicrophone = true)
        AppStateBus.setLiveAudioActive(true)
        audioEngine.startInternalAudioCapture(mediaProjection)
    }

    // --- Floating Inline Subtitle Editor & Glossary Quick-Add right over Anime Player ---
    private fun showFloatingEditDialog() {
        if (editCardView != null) return
        toolbarScroll?.visibility = View.GONE

        val card = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18f), dp(16f), dp(18f), dp(16f))
            background = GradientDrawable().apply {
                setColor(Color.WHITE)
                cornerRadius = dp(16f).toFloat()
                setStroke(dp(1f), Color.parseColor("#CBD5E1"))
            }
        }

        val title = TextView(this).apply {
            text = "修改当前字幕"
            textSize = 15f
            setTextColor(Color.parseColor("#0F172A"))
        }
        card.addView(title)

        val transInput = EditText(this).apply {
            setText(AppStateBus.currentTranslated.value)
            setTextColor(Color.parseColor("#0F172A"))
            hint = "修改中文译文"
            setHintTextColor(Color.parseColor("#94A3B8"))
        }
        card.addView(transInput)

        val glossRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val srcInput = EditText(this).apply {
            hint = "外语原词"
            setTextColor(Color.parseColor("#0F172A"))
            setHintTextColor(Color.parseColor("#94A3B8"))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val dstInput = EditText(this).apply {
            hint = "固定译名"
            setTextColor(Color.parseColor("#0F172A"))
            setHintTextColor(Color.parseColor("#94A3B8"))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        glossRow.addView(srcInput)
        glossRow.addView(dstInput)
        card.addView(glossRow)

        val btnRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.END
        }
        val btnCancel = TextView(this).apply {
            text = "取消"
            setTextColor(Color.parseColor("#64748B"))
            setPadding(dp(14f), dp(8f), dp(14f), dp(8f))
            setOnClickListener { closeFloatingEditDialog() }
        }
        val btnSave = TextView(this).apply {
            text = "保存修改"
            setTextColor(Color.WHITE)
            setPadding(dp(16f), dp(8f), dp(16f), dp(8f))
            background = GradientDrawable().apply {
                setColor(Color.parseColor("#2563EB"))
                cornerRadius = dp(9f).toFloat()
            }
            setOnClickListener {
                val gs = srcInput.text.toString().trim()
                val gd = dstInput.text.toString().trim()
                var updatedTrans = transInput.text.toString().trim()
                if (gs.isNotEmpty() && gd.isNotEmpty()) {
                    AppStateBus.putGlossaryTerm(this@FloatingTranslatorService, gs, gd)
                    MobileTranslator.clearCache()
                    updatedTrans = updatedTrans.replace(gs, gd)
                }
                AppStateBus.editCurrentSubtitle(AppStateBus.currentOriginal.value, updatedTrans)
                closeFloatingEditDialog()
            }
        }
        btnRow.addView(btnCancel)
        btnRow.addView(btnSave)
        card.addView(btnRow)

        val eParams = WindowManager.LayoutParams(
            (resources.displayMetrics.widthPixels * 0.88f).toInt(),
            WindowManager.LayoutParams.WRAP_CONTENT,
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
            } else {
                @Suppress("DEPRECATION")
                WindowManager.LayoutParams.TYPE_PHONE
            },
            WindowManager.LayoutParams.FLAG_DIM_BEHIND,
            PixelFormat.TRANSLUCENT
        ).apply {
            dimAmount = 0.45f
            gravity = Gravity.CENTER
            softInputMode = WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
        }

        windowManager.addView(card, eParams)
        editCardView = card
    }

    private fun closeFloatingEditDialog() {
        editCardView?.let { runCatching { windowManager.removeView(it) } }
        editCardView = null
    }

    override fun onDestroy() {
        stopLiveScreenCapture()
        audioEngine.stopAll()
        removeRegionPicker()
        closeFloatingEditDialog()
        removeEdgeUnlockBadge()
        rootContainer?.let { runCatching { windowManager.removeView(it) } }
        virtualDisplay?.release()
        imageReader?.close()
        mediaProjection?.stop()
        AppStateBus.setOverlayRunning(false)
        AppStateBus.setLiveAudioActive(false)
        serviceScope.cancel()
        super.onDestroy()
    }
}
