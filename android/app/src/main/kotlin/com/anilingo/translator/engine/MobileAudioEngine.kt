package com.anilingo.translator.engine

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.projection.MediaProjection
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import com.anilingo.translator.model.AppStateBus
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sqrt

/**
 * Dual-Mode Android Real-Time Audio Translator:
 * 1. Microphone Voice Mode ("mic"): Continuous Android SpeechRecognizer streaming (supports ja-JP, en-US, ko-KR).
 * 2. Internal Device Playback Mode ("internal", Android 10+): AudioPlaybackCaptureConfiguration captures anime/video sound,
 *    segments speech via Energy VAD, and transcribes via Cloud Whisper API or Desktop PC LAN Bridge.
 */
class MobileAudioEngine(
    private val context: Context,
    private val scope: CoroutineScope,
    private val onRecognized: (sourceTag: String, originalText: String) -> Unit,
) {
    private val mainHandler = Handler(Looper.getMainLooper())
    private var speechRecognizer: SpeechRecognizer? = null
    private var micActive = false
    private var playbackJob: Job? = null

    fun startMicrophoneRecognition() {
        stopAll()
        micActive = true
        mainHandler.post {
            if (!SpeechRecognizer.isRecognitionAvailable(context)) {
                AppStateBus.setStatus("⚠️ 当前系统未安装语音识别服务，可在设置配置云端/电脑局域网语音接口")
                return@post
            }
            speechRecognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) {
                        AppStateBus.setStatus("🎙️ 正在聆听麦克风外语语音...")
                    }

                    override fun onBeginningOfSpeech() {}
                    override fun onRmsChanged(rmsdB: Float) {}
                    override fun onBufferReceived(buffer: ByteArray?) {}
                    override fun onEndOfSpeech() {}

                    override fun onError(error: Int) {
                        if (micActive) {
                            mainHandler.postDelayed({ restartMicListening() }, 450L)
                        }
                    }

                    override fun onResults(results: Bundle?) {
                        val matches = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        val best = matches?.firstOrNull()?.trim().orEmpty()
                        if (best.isNotEmpty()) {
                            onRecognized("audio_mic", best)
                        }
                        if (micActive) {
                            mainHandler.postDelayed({ restartMicListening() }, 180L)
                        }
                    }

                    override fun onPartialResults(partialResults: Bundle?) {}
                    override fun onEvent(eventType: Int, params: Bundle?) {}
                })
            }
            restartMicListening()
        }
    }

    private fun restartMicListening() {
        if (!micActive) return
        val langTag = when (AppStateBus.engineConfig.value.sourceLang) {
            "ja" -> "ja-JP"
            "en" -> "en-US"
            "ko" -> "ko-KR"
            else -> "ja-JP"
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, langTag)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        }
        runCatching { speechRecognizer?.startListening(intent) }
    }

    @SuppressLint("MissingPermission")
    fun startInternalAudioCapture(projection: MediaProjection?) {
        stopAll()
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q || projection == null) {
            AppStateBus.setStatus("⚠️ 手机内部声音捕获需要先授予屏幕/内录捕获权限（Android 10+）")
            return
        }

        playbackJob = scope.launch(Dispatchers.IO) {
            val sampleRate = 16000
            val minBuf = AudioRecord.getMinBufferSize(
                sampleRate,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            ).coerceAtLeast(4096)

            val captureConfig = AudioPlaybackCaptureConfiguration.Builder(projection)
                .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                .addMatchingUsage(AudioAttributes.USAGE_GAME)
                .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
                .build()

            val record = runCatching {
                AudioRecord.Builder()
                    .setAudioFormat(
                        AudioFormat.Builder()
                            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                            .setSampleRate(sampleRate)
                            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                            .build()
                    )
                    .setBufferSizeInBytes(minBuf * 2)
                    .setAudioPlaybackCaptureConfig(captureConfig)
                    .build()
            }.getOrNull()

            if (record == null || record.state != AudioRecord.STATE_INITIALIZED) {
                AppStateBus.setStatus("⚠️ 初始化手机内录失败，请确认目标播放器允许音频捕获")
                return@launch
            }

            AppStateBus.setStatus("🔊 正在捕获手机内部播放声音（生肉听译中）...")
            record.startRecording()

            val chunkSamples = 1600 // 100ms at 16kHz
            val shortBuf = ShortArray(chunkSamples)
            val speechStream = ByteArrayOutputStream()
            var speaking = false
            var silenceMs = 0
            var speechMs = 0

            try {
                while (isActive) {
                    val read = record.read(shortBuf, 0, chunkSamples)
                    if (read <= 0) continue

                    var sumSq = 0.0
                    for (i in 0 until read) {
                        val norm = shortBuf[i] / 32768.0
                        sumSq += norm * norm
                    }
                    val rms = sqrt(sumSq / read)

                    if (rms >= 0.012) {
                        speaking = true
                        silenceMs = 0
                        speechMs += 100
                        writeShortsLe(speechStream, shortBuf, read)
                    } else if (speaking) {
                        silenceMs += 100
                        speechMs += 100
                        writeShortsLe(speechStream, shortBuf, read)
                        if (silenceMs >= 450) {
                            flushInternalPcm(speechStream.toByteArray(), speechMs)
                            speechStream.reset()
                            speaking = false
                            silenceMs = 0
                            speechMs = 0
                        }
                    }

                    if (speaking && speechMs >= 5000) {
                        flushInternalPcm(speechStream.toByteArray(), speechMs)
                        speechStream.reset()
                        speaking = false
                        silenceMs = 0
                        speechMs = 0
                    }
                }
            } finally {
                runCatching {
                    record.stop()
                    record.release()
                }
            }
        }
    }

    private fun writeShortsLe(out: ByteArrayOutputStream, shorts: ShortArray, count: Int) {
        val bb = ByteBuffer.allocate(count * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (i in 0 until count) bb.putShort(shorts[i])
        out.write(bb.array())
    }

    private fun flushInternalPcm(pcmBytes: ByteArray, durationMs: Int) {
        if (durationMs < 400 || pcmBytes.isEmpty()) return
        val cfg = AppStateBus.engineConfig.value

        // Priority 1: Free Local Faster-Whisper via Desktop PC LAN Bridge if connected
        if (cfg.pcLanUrl.isNotBlank()) {
            val lanTxt = runCatching {
                val endpoint = "${cfg.pcLanUrl.trim().trimEnd('/')}/api/audio_transcribe"
                val conn = (URL(endpoint).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    doOutput = true
                    connectTimeout = 4000
                    readTimeout = 8000
                    setRequestProperty("Content-Type", "application/json")
                }
                val b64 = android.util.Base64.encodeToString(pcmBytes, android.util.Base64.NO_WRAP)
                val payload = JSONObject().put("pcm16_base64", b64).put("lang", cfg.sourceLang).toString()
                conn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }
                val resp = conn.inputStream.bufferedReader().use { it.readText() }
                JSONObject(resp).optString("text", "").trim()
            }.getOrDefault("")
            if (lanTxt.isNotBlank()) {
                onRecognized("audio_internal", lanTxt)
                return
            }
        }

        // Priority 2: Cloud Whisper API if configured
        val wavBytes = wrapPcmAsWav(pcmBytes, 16000, 1, 16)
        if (cfg.whisperCloudBase.isNotBlank() && cfg.whisperCloudKey.isNotBlank()) {
            val txt = runCatching {
                transcribeCloudWhisper(wavBytes, cfg.whisperCloudBase, cfg.whisperCloudKey, cfg.sourceLang)
            }.getOrDefault("")
            if (txt.isNotBlank()) {
                onRecognized("audio_internal", txt)
            }
        } else {
            AppStateBus.setStatus("💡 手机内录已就绪：在同一 Wi-Fi 填写电脑端局域网地址即可免 Key 用电脑显卡听译，或切换麦克风流式听译")
        }
    }

    private fun wrapPcmAsWav(pcm: ByteArray, sampleRate: Int, channels: Int, bitsPerSample: Int): ByteArray {
        val byteRate = sampleRate * channels * bitsPerSample / 8
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
            put("RIFF".toByteArray())
            putInt(36 + pcm.size)
            put("WAVE".toByteArray())
            put("fmt ".toByteArray())
            putInt(16)
            putShort(1)
            putShort(channels.toShort())
            putInt(sampleRate)
            putInt(byteRate)
            putShort((channels * bitsPerSample / 8).toShort())
            putShort(bitsPerSample.toShort())
            put("data".toByteArray())
            putInt(pcm.size)
        }.array()
        return header + pcm
    }

    private fun transcribeCloudWhisper(wav: ByteArray, apiBase: String, apiKey: String, lang: String): String {
        val boundary = "----AniLingoMob${System.currentTimeMillis()}"
        val endpoint = apiBase.trim().trimEnd('/').let {
            if (it.endsWith("/audio/transcriptions")) it else "$it/audio/transcriptions"
        }
        val bos = ByteArrayOutputStream()
        fun writeField(k: String, v: String) {
            bos.write("--$boundary\r\nContent-Disposition: form-data; name=\"$k\"\r\n\r\n$v\r\n".toByteArray())
        }
        writeField("model", "whisper-1")
        if (lang != "auto") writeField("language", lang)
        bos.write(
            ("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"sub.wav\"\r\n" +
                "Content-Type: audio/wav\r\n\r\n").toByteArray()
        )
        bos.write(wav)
        bos.write("\r\n--$boundary--\r\n".toByteArray())

        val conn = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            doOutput = true
            connectTimeout = 8000
            readTimeout = 8000
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            setRequestProperty("Authorization", "Bearer ${apiKey.trim()}")
        }
        conn.outputStream.use { it.write(bos.toByteArray()) }
        val resp = conn.inputStream.bufferedReader().use { it.readText() }
        return JSONObject(resp).optString("text", "").trim()
    }

    fun stopAll() {
        micActive = false
        playbackJob?.cancel()
        playbackJob = null
        mainHandler.post {
            runCatching {
                speechRecognizer?.stopListening()
                speechRecognizer?.cancel()
                speechRecognizer?.destroy()
            }
            speechRecognizer = null
        }
    }
}
