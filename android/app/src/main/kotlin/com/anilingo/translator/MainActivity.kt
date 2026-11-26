package com.anilingo.translator

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.core.content.ContextCompat
import com.anilingo.translator.model.AppStateBus
import com.anilingo.translator.overlay.FloatingTranslatorService
import com.anilingo.translator.ui.main.AniLingoMainScreen
import com.anilingo.translator.ui.theme.AniLingoTheme

class MainActivity : ComponentActivity() {

    private var pendingFollowUpAction: String = "live_screen"

    private val overlayPermLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        if (Settings.canDrawOverlays(this)) {
            startFloatingService(FloatingTranslatorService.ACTION_START_OVERLAY)
        } else {
            Toast.makeText(this, "需要授予悬浮窗权限才能显示桌面歌词字幕", Toast.LENGTH_LONG).show()
        }
    }

    private val mediaProjectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val svcIntent = Intent(this, FloatingTranslatorService::class.java).apply {
                action = FloatingTranslatorService.ACTION_GRANT_PROJECTION
                putExtra(FloatingTranslatorService.EXTRA_RESULT_CODE, result.resultCode)
                putExtra(FloatingTranslatorService.EXTRA_RESULT_DATA, result.data)
                putExtra(FloatingTranslatorService.EXTRA_AFTER_PROJECTION, pendingFollowUpAction)
            }
            ContextCompat.startForegroundService(this, svcIntent)
            moveTaskToBack(true)
        } else {
            Toast.makeText(this, "未授予屏幕捕获权限", Toast.LENGTH_SHORT).show()
        }
    }

    private val audioPermLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { grantedMap ->
        if (grantedMap[Manifest.permission.RECORD_AUDIO] == true) {
            if (AppStateBus.engineConfig.value.audioSource == "internal") {
                requestScreenProjection("internal_audio")
            } else {
                ensureOverlayThenSend(FloatingTranslatorService.ACTION_TOGGLE_AUDIO)
            }
        } else {
            Toast.makeText(this, "需要麦克风/录音权限才能进行声音实时翻译", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        AppStateBus.init(this)
        enableEdgeToEdge()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 101)
            }
        }

        handleIncomingProjectionIntent(intent)

        setContent {
            AniLingoTheme {
                AniLingoMainScreen(
                    onToggleOverlay = {
                        if (AppStateBus.overlayRunning.value) {
                            startService(
                                Intent(this, FloatingTranslatorService::class.java).apply {
                                    action = FloatingTranslatorService.ACTION_STOP_OVERLAY
                                }
                            )
                        } else {
                            ensureOverlayPermissionAndStart()
                        }
                    },
                    onPickRegion = {
                        ensureOverlayThenSend(FloatingTranslatorService.ACTION_START_REGION_PICKER)
                    },
                    onToggleLiveScreen = {
                        if (AppStateBus.liveScreenActive.value) {
                            ensureOverlayThenSend(FloatingTranslatorService.ACTION_TOGGLE_LIVE_SCREEN)
                        } else {
                            requestScreenProjection("live_screen")
                        }
                    },
                    onStartSnip = {
                        requestScreenProjection("snip")
                    },
                    onToggleAudio = {
                        if (AppStateBus.liveAudioActive.value) {
                            ensureOverlayThenSend(FloatingTranslatorService.ACTION_TOGGLE_AUDIO)
                        } else {
                            checkAudioPermAndStart()
                        }
                    }
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIncomingProjectionIntent(intent)
    }

    private fun handleIncomingProjectionIntent(intent: Intent?) {
        val req = intent?.getStringExtra("request_projection")
        if (!req.isNullOrBlank()) {
            intent.removeExtra("request_projection")
            requestScreenProjection(req)
        }
    }

    private fun ensureOverlayPermissionAndStart(): Boolean {
        if (!Settings.canDrawOverlays(this)) {
            val uri = Uri.parse("package:$packageName")
            overlayPermLauncher.launch(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, uri))
            return false
        }
        startFloatingService(FloatingTranslatorService.ACTION_START_OVERLAY)
        return true
    }

    private fun ensureOverlayThenSend(svcAction: String) {
        if (!Settings.canDrawOverlays(this)) {
            ensureOverlayPermissionAndStart()
            return
        }
        startFloatingService(svcAction)
    }

    private fun startFloatingService(svcAction: String) {
        val intent = Intent(this, FloatingTranslatorService::class.java).apply {
            action = svcAction
        }
        ContextCompat.startForegroundService(this, intent)
    }

    private fun requestScreenProjection(followUp: String) {
        if (!Settings.canDrawOverlays(this)) {
            ensureOverlayPermissionAndStart()
            return
        }
        if (followUp == "internal_audio" &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED
        ) {
            audioPermLauncher.launch(arrayOf(Manifest.permission.RECORD_AUDIO))
            return
        }
        pendingFollowUpAction = followUp
        if (!AppStateBus.overlayRunning.value) {
            startFloatingService(FloatingTranslatorService.ACTION_START_OVERLAY)
        }
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjectionLauncher.launch(mpm.createScreenCaptureIntent())
    }

    private fun checkAudioPermAndStart() {
        if (!Settings.canDrawOverlays(this)) {
            ensureOverlayPermissionAndStart()
            return
        }
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED
        ) {
            if (AppStateBus.engineConfig.value.audioSource == "internal") {
                requestScreenProjection("internal_audio")
            } else {
                ensureOverlayThenSend(FloatingTranslatorService.ACTION_TOGGLE_AUDIO)
            }
        } else {
            audioPermLauncher.launch(arrayOf(Manifest.permission.RECORD_AUDIO))
        }
    }
}
