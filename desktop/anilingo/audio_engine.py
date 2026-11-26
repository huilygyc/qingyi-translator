"""Real-Time Audio Capture (WASAPI Computer Loopback + Microphone) & Speech-to-Text Engine."""

from __future__ import annotations

import io
import json
import queue
import threading
import time
import urllib.request
import wave
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from .config import ConfigManager


class AudioDeviceInfo:
    def __init__(self, index: int, name: str, is_loopback: bool, sample_rate: int, channels: int) -> None:
        self.index = index
        self.name = name
        self.is_loopback = is_loopback
        self.sample_rate = sample_rate
        self.channels = channels


class RealtimeAudioEngine:
    """Captures PC internal audio (WASAPI Loopback) or Microphone voice, segments speech via VAD, and transcribes."""

    def __init__(
        self,
        cfg_mgr: ConfigManager,
        on_transcript: Callable[[str, str], None],
        on_level: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cfg_mgr = cfg_mgr
        self.on_transcript = on_transcript  # (source_tag, recognized_text)
        self.on_level = on_level
        self.on_status = on_status

        self._running = False
        self._capture_thread: Optional[threading.Thread] = None
        self._asr_thread: Optional[threading.Thread] = None
        self._segment_queue: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=12)

        self._whisper_model: Any = None
        self._whisper_loaded_name: str = ""
        self._whisper_device: str = "cpu"
        self._model_lock = threading.Lock()

    @staticmethod
    def list_devices() -> Dict[str, List[AudioDeviceInfo]]:
        import pyaudiowpatch as pyaudio

        loopbacks: List[AudioDeviceInfo] = []
        mics: List[AudioDeviceInfo] = []
        p = pyaudio.PyAudio()
        try:
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                max_in = int(info.get("maxInputChannels", 0))
                if max_in <= 0:
                    continue
                is_lb = bool(info.get("isLoopbackDevice", False))
                name = str(info.get("name", f"Device {i}"))
                sr = int(float(info.get("defaultSampleRate", 48000)))
                item = AudioDeviceInfo(i, name, is_lb, sr, max_in)
                if is_lb:
                    loopbacks.append(item)
                else:
                    mics.append(item)
        finally:
            p.terminate()
        return {"loopback": loopbacks, "mic": mics}

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        while not self._segment_queue.empty():
            try:
                self._segment_queue.get_nowait()
            except queue.Empty:
                break

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True, name="AudioCapture")
        self._asr_thread = threading.Thread(target=self._asr_loop, daemon=True, name="AudioASR")
        self._capture_thread.start()
        self._asr_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=1.5)
        if self._asr_thread and self._asr_thread.is_alive():
            self._asr_thread.join(timeout=1.5)
        if self.on_level:
            self.on_level(0.0)

    @property
    def is_running(self) -> bool:
        return self._running

    def _emit_status(self, msg: str) -> None:
        if self.on_status:
            self.on_status(msg)

    def _resolve_target_device(self, p: Any) -> Optional[dict]:
        cfg = self.cfg_mgr.config
        want_loopback = cfg.audio_source == "loopback"

        if cfg.audio_device_index >= 0:
            try:
                d = p.get_device_info_by_index(cfg.audio_device_index)
                if int(d.get("maxInputChannels", 0)) > 0 and bool(d.get("isLoopbackDevice", False)) == want_loopback:
                    return d
            except Exception:
                pass

        if want_loopback:
            try:
                return p.get_default_wasapi_loopback()
            except Exception:
                for i in range(p.get_device_count()):
                    d = p.get_device_info_by_index(i)
                    if d.get("isLoopbackDevice"):
                        return d
        else:
            try:
                return p.get_default_input_device_info()
            except Exception:
                for i in range(p.get_device_count()):
                    d = p.get_device_info_by_index(i)
                    if int(d.get("maxInputChannels", 0)) > 0 and not d.get("isLoopbackDevice"):
                        return d
        return None

    def _capture_loop(self) -> None:
        import pyaudiowpatch as pyaudio

        p = pyaudio.PyAudio()
        stream = None
        try:
            dev = self._resolve_target_device(p)
            if not dev:
                self._emit_status("⚠️ 未检测到可用的音频输入/内录设备")
                self._running = False
                return

            dev_idx = int(dev["index"])
            dev_name = str(dev.get("name", "Audio"))
            sr = int(float(dev.get("defaultSampleRate", 48000)))
            channels = max(1, min(2, int(dev.get("maxInputChannels", 2))))
            chunk_frames = max(512, int(sr * 0.08))  # 80ms chunks

            mode_label = "电脑系统原声" if self.cfg_mgr.config.audio_source == "loopback" else "麦克风语音"
            self._emit_status(f"正在听译{mode_label}")

            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=sr,
                input=True,
                input_device_index=dev_idx,
                frames_per_buffer=chunk_frames,
            )

            target_sr = 16000
            preroll_chunks: List[np.ndarray] = []
            speech_chunks: List[np.ndarray] = []
            speaking = False
            silence_sec = 0.0
            speech_sec = 0.0

            while self._running:
                try:
                    raw = stream.read(chunk_frames, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.03)
                    continue

                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                if channels > 1:
                    samples = samples.reshape(-1, channels).mean(axis=1)

                # Resample to 16kHz mono cleanly
                if sr != target_sr and len(samples) > 1:
                    new_len = int(round(len(samples) * target_sr / sr))
                    x_old = np.linspace(0.0, 1.0, num=len(samples), endpoint=False)
                    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
                    samples_16k = np.interp(x_new, x_old, samples).astype(np.float32)
                else:
                    samples_16k = samples

                rms = float(np.sqrt(np.mean(samples_16k * samples_16k) + 1e-12))
                if self.on_level:
                    self.on_level(min(1.0, rms * 14.0))

                thresh = max(0.004, float(self.cfg_mgr.config.vad_energy_threshold))
                chunk_dur = len(samples_16k) / float(target_sr)

                if rms >= thresh:
                    if not speaking:
                        speaking = True
                        speech_chunks = list(preroll_chunks)
                        speech_sec = sum(len(c) for c in speech_chunks) / float(target_sr)
                    speech_chunks.append(samples_16k)
                    speech_sec += chunk_dur
                    silence_sec = 0.0
                else:
                    if speaking:
                        speech_chunks.append(samples_16k)
                        speech_sec += chunk_dur
                        silence_sec += chunk_dur
                        if silence_sec >= 0.32:
                            self._flush_segment(speech_chunks, speech_sec)
                            speech_chunks = []
                            speaking = False
                            silence_sec = 0.0
                            speech_sec = 0.0
                    else:
                        preroll_chunks.append(samples_16k)
                        if len(preroll_chunks) > 4:
                            preroll_chunks.pop(0)

                # Cap continuous rapid anime dialogue at 3.8s so subtitles appear promptly
                if speaking and speech_sec >= 3.8:
                    self._flush_segment(speech_chunks, speech_sec)
                    speech_chunks = []
                    speaking = False
                    silence_sec = 0.0
                    speech_sec = 0.0

        except Exception as exc:
            self._emit_status(f"⚠️ 音频捕获异常: {exc}")
            self._running = False
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            p.terminate()

    def _flush_segment(self, chunks: List[np.ndarray], dur_sec: float) -> None:
        if dur_sec < 0.35 or not chunks:
            return
        seg = np.concatenate(chunks).astype(np.float32)
        if self._segment_queue.full():
            try:
                self._segment_queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self._segment_queue.put_nowait(seg)
        except queue.Full:
            pass

    def _ensure_whisper(self, force_cpu: bool = False) -> Any:
        from faster_whisper import WhisperModel

        model_name = self.cfg_mgr.config.whisper_model.strip() or "tiny"
        with self._model_lock:
            if (
                self._whisper_model is not None
                and self._whisper_loaded_name == model_name
                and not (force_cpu and self._whisper_device != "cpu")
            ):
                return self._whisper_model

            self._emit_status(f"正在加载语音模型 ({model_name})...")
            if not force_cpu:
                try:
                    self._whisper_model = WhisperModel(model_name, device="cuda", compute_type="float16")
                    self._whisper_loaded_name = model_name
                    self._whisper_device = "cuda"
                    self._emit_status(f"语音引擎已就绪 (GPU · {model_name})")
                    return self._whisper_model
                except Exception:
                    pass

            self._whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=4)
            self._whisper_loaded_name = model_name
            self._whisper_device = "cpu"
            self._emit_status(f"语音引擎已就绪 ({model_name})")
            return self._whisper_model

    def _asr_loop(self) -> None:
        while self._running:
            try:
                audio_16k = self._segment_queue.get(timeout=0.3)
            except queue.Empty:
                continue

            cfg = self.cfg_mgr.config
            source_tag = "audio_pc" if cfg.audio_source == "loopback" else "audio_mic"
            lang_hint = None if cfg.source_lang == "auto" else cfg.source_lang

            text = ""
            if cfg.asr_cloud_api_base.strip() and cfg.asr_cloud_api_key.strip():
                try:
                    text = self._transcribe_cloud(audio_16k, lang_hint)
                except Exception:
                    text = ""

            if not text:
                text = self._transcribe_local(audio_16k, lang_hint)

            clean = (text or "").strip()
            if clean and not self._is_hallucination(clean):
                self.on_transcript(source_tag, clean)

    def _transcribe_local(self, audio_16k: np.ndarray, lang_hint: Optional[str]) -> str:
        try:
            model = self._ensure_whisper(force_cpu=False)
            segments, _ = model.transcribe(
                audio_16k,
                language=lang_hint,
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
        except Exception:
            # Automatic fallback to CPU int8 if CUDA DLLs (e.g. cublas64_12.dll) fail lazily at inference time
            try:
                model = self._ensure_whisper(force_cpu=True)
                segments, _ = model.transcribe(
                    audio_16k,
                    language=lang_hint,
                    beam_size=1,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                return " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
            except Exception as exc:
                self._emit_status(f"⚠️ 语音识别错误: {exc}")
                return ""

    def _transcribe_cloud(self, audio_16k: np.ndarray, lang_hint: Optional[str]) -> str:
        """Optional OpenAI-compatible /v1/audio/transcriptions endpoint."""
        cfg = self.cfg_mgr.config
        wav_buf = io.BytesIO()
        with wave.open(wav_buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            pcm16 = np.clip(audio_16k * 32767.0, -32768, 32767).astype(np.int16)
            wf.writeframes(pcm16.tobytes())
        wav_bytes = wav_buf.getvalue()

        boundary = f"----AniLingoBoundary{int(time.time() * 1000)}"
        parts: List[bytes] = []

        def add_field(name: str, val: str) -> None:
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{val}\r\n".encode())

        add_field("model", cfg.asr_cloud_model.strip() or "whisper-1")
        if lang_hint:
            add_field("language", lang_hint)
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n".encode() + wav_bytes + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)

        base = cfg.asr_cloud_api_base.rstrip("/")
        url = base if base.endswith("/audio/transcriptions") else f"{base}/audio/transcriptions"
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Authorization": f"Bearer {cfg.asr_cloud_api_key.strip()}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            return str(res.get("text", "")).strip()

    @staticmethod
    def _is_hallucination(text: str) -> bool:
        hallucinations = {
            "ご視聴ありがとうございました",
            "チャンネル登録お願いします",
            "字幕視聴ありがとうございました",
            "Thank you for watching.",
            "Thanks for watching!",
            "Subtitles by the Amara.org community",
        }
        return text.strip() in hallucinations or len(text.strip()) <= 1
