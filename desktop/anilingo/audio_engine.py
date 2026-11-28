"""Real-Time Low-Latency Streaming Audio Capture (WASAPI Loopback + Mic) & Speech-to-Text Engine."""

from __future__ import annotations

import ctypes
import io
import json
import os
import queue
import re
import tarfile
import threading
import time
import urllib.request
import wave
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .config import DATA_DIR, ConfigManager
from .win32_utils import set_current_thread_below_normal

SENSEVOICE_DIR_NAME = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
SENSEVOICE_URLS = [
    "https://ghfast.top/https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
]


def _has_cuda_cublas_runtime() -> bool:
    """0.3ms pre-check preventing the 2-second lazy CUDA load + crash penalty when CUDA toolkit isn't installed."""
    for dll in ("cublas64_12.dll", "cublas64_11.dll"):
        try:
            ctypes.WinDLL(dll)
            return True
        except OSError:
            pass
    return False


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
        on_transcript: Callable[..., None],
        on_level: Optional[Callable[[float], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cfg_mgr = cfg_mgr
        self.on_transcript = on_transcript  # (source_tag, recognized_text, is_final)
        self.on_level = on_level
        self.on_status = on_status

        self._running = False
        self._capture_thread: Optional[threading.Thread] = None
        self._asr_thread: Optional[threading.Thread] = None
        # Tiny zero-backlog queue: (audio_16k, is_final) — stale audio is always dropped so live speech never snowballs!
        self._segment_queue: "queue.Queue[Tuple[np.ndarray, bool]]" = queue.Queue(maxsize=2)

        self._whisper_model: Any = None
        self._whisper_loaded_name: str = ""
        self._whisper_device: str = "cpu"
        self._cuda_checked: bool = False
        self._cuda_available: bool = False
        self._sensevoice_rec: Any = None
        self._model_lock = threading.Lock()
        self._last_preview_text: str = ""

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
        self._last_preview_text = ""
        while not self._segment_queue.empty():
            try:
                self._segment_queue.get_nowait()
            except queue.Empty:
                break

        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True, name="AudioCapture")
        self._asr_thread = threading.Thread(target=self._asr_loop, daemon=True, name="AudioASR")
        self._capture_thread.start()
        self._asr_thread.start()
        # Immediately pre-warm ASR model on start so sentence #1 has zero model-loading delay!
        threading.Thread(target=self._warmup_asr_bg, daemon=True, name="AudioWarmup").start()

    def _warmup_asr_bg(self) -> None:
        set_current_thread_below_normal()
        try:
            if self.cfg_mgr.config.whisper_model.strip() == "sensevoice":
                self._ensure_sensevoice()
            else:
                self._ensure_whisper(force_cpu=False)
        except Exception:
            pass

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
                self._emit_status("未检测到可用的音频输入或内录设备")
                self._running = False
                return

            dev_idx = int(dev["index"])
            sr = int(float(dev.get("defaultSampleRate", 48000)))
            channels = max(1, min(2, int(dev.get("maxInputChannels", 2))))
            chunk_frames = max(256, int(sr * 0.04))  # 40ms ultra-responsive chunks

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
            rms_history: deque[float] = deque(maxlen=55)  # ~2.2s rolling window for adaptive BGM noise floor
            speaking = False
            silence_sec = 0.0
            speech_sec = 0.0
            since_preview_sec = 0.0

            while self._running:
                try:
                    raw = stream.read(chunk_frames, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.02)
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

                # Adaptive noise floor: prevents continuous anime BGM / ambient mic noise from pinning VAD open for 3.8s!
                rms_history.append(rms)
                if len(rms_history) >= 12:
                    sorted_rms = sorted(rms_history)
                    noise_floor = sorted_rms[len(sorted_rms) // 5]  # 20th percentile background floor
                else:
                    noise_floor = 0.004

                base_thresh = max(0.004, float(self.cfg_mgr.config.vad_energy_threshold))
                # Dynamic threshold adapts gracefully to BGM while staying sensitive on quiet mics
                enter_thresh = max(base_thresh, noise_floor * 1.95 + 0.006)
                keep_thresh = max(base_thresh * 0.85, noise_floor * 1.45 + 0.004)
                chunk_dur = len(samples_16k) / float(target_sr)

                is_voiced = rms >= (keep_thresh if speaking else enter_thresh)
                if is_voiced:
                    if not speaking:
                        speaking = True
                        speech_chunks = list(preroll_chunks)
                        speech_sec = sum(len(c) for c in speech_chunks) / float(target_sr)
                        since_preview_sec = 0.0
                    speech_chunks.append(samples_16k)
                    speech_sec += chunk_dur
                    since_preview_sec += chunk_dur
                    silence_sec = 0.0

                    # Live streaming interim preview every ~0.85s while speaker is still talking!
                    if speech_sec >= 0.90 and since_preview_sec >= 0.85 and self._segment_queue.empty():
                        self._flush_segment(speech_chunks, speech_sec, is_final=False)
                        since_preview_sec = 0.0
                else:
                    if speaking:
                        speech_chunks.append(samples_16k)
                        speech_sec += chunk_dur
                        silence_sec += chunk_dur
                        # Crisp 0.24s pause finalizes sentence immediately
                        if silence_sec >= 0.24:
                            self._flush_segment(speech_chunks, speech_sec, is_final=True)
                            speech_chunks = []
                            speaking = False
                            silence_sec = 0.0
                            speech_sec = 0.0
                            since_preview_sec = 0.0
                    else:
                        preroll_chunks.append(samples_16k)
                        if len(preroll_chunks) > 5:  # ~200ms pre-roll
                            preroll_chunks.pop(0)

                # Tight 2.4s hard cap (carrying 0.2s overlap tail) so nonstop rapid anime dialogue stays super responsive
                if speaking and speech_sec >= 2.4:
                    self._flush_segment(speech_chunks, speech_sec, is_final=True)
                    overlap_tail = speech_chunks[-5:] if len(speech_chunks) > 5 else []
                    speech_chunks = list(overlap_tail)
                    speech_sec = sum(len(c) for c in speech_chunks) / float(target_sr)
                    silence_sec = 0.0
                    since_preview_sec = 0.0

        except Exception as exc:
            self._emit_status(f"音频捕获异常: {exc}")
            self._running = False
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            p.terminate()

    def _flush_segment(self, chunks: List[np.ndarray], dur_sec: float, is_final: bool = True) -> None:
        if dur_sec < 0.30 or not chunks:
            return
        seg = np.concatenate(chunks).astype(np.float32)
        if not is_final and not self._segment_queue.empty():
            # Never queue an interim preview behind pending work
            return
        if self._segment_queue.full():
            try:
                self._segment_queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self._segment_queue.put_nowait((seg, is_final))
        except queue.Full:
            pass

    def _ensure_whisper(self, force_cpu: bool = False) -> Any:
        from faster_whisper import WhisperModel

        raw_name = self.cfg_mgr.config.whisper_model.strip() or "tiny"
        model_name = "tiny" if raw_name == "sensevoice" else raw_name
        with self._model_lock:
            if (
                self._whisper_model is not None
                and self._whisper_loaded_name == model_name
                and not (force_cpu and self._whisper_device != "cpu")
            ):
                return self._whisper_model

            if not self._cuda_checked:
                self._cuda_available = _has_cuda_cublas_runtime()
                self._cuda_checked = True

            self._emit_status(f"正在加载语音模型 ({model_name})...")
            if not force_cpu and self._cuda_available:
                try:
                    self._whisper_model = WhisperModel(model_name, device="cuda", compute_type="float16")
                    self._whisper_loaded_name = model_name
                    self._whisper_device = "cuda"
                    self._emit_status(f"语音引擎已就绪 (GPU · {model_name})")
                    return self._whisper_model
                except Exception:
                    self._cuda_available = False

            cores = os.cpu_count() or 8
            cpu_threads = min(6, max(4, cores // 2))
            self._whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=cpu_threads)
            self._whisper_loaded_name = model_name
            self._whisper_device = "cpu"
            self._emit_status(f"语音引擎已就绪 ({model_name})")
            return self._whisper_model

    def _asr_loop(self) -> None:
        set_current_thread_below_normal()
        while self._running:
            try:
                audio_16k, is_final = self._segment_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            # Zero-backlog drain: if a newer segment already arrived, jump straight to it (never lag seconds behind!)
            while True:
                try:
                    newer_audio, newer_final = self._segment_queue.get_nowait()
                    if is_final and not newer_final:
                        # Don't let a speculative preview discard an already-completed final sentence
                        continue
                    audio_16k, is_final = newer_audio, newer_final
                except queue.Empty:
                    break

            cfg = self.cfg_mgr.config
            source_tag = "audio_pc" if cfg.audio_source == "loopback" else "audio_mic"
            lang_hint = None if cfg.source_lang == "auto" else cfg.source_lang

            text = ""
            if is_final and cfg.asr_cloud_api_base.strip() and cfg.asr_cloud_api_key.strip():
                try:
                    text = self._transcribe_cloud(audio_16k, lang_hint)
                except Exception:
                    text = ""

            if not text:
                text = self._transcribe_local(audio_16k, lang_hint)

            clean = (text or "").strip()
            if clean and not self._is_hallucination(clean):
                if not is_final and clean == self._last_preview_text:
                    continue
                self._last_preview_text = "" if is_final else clean
                self.on_transcript(source_tag, clean, is_final)

    def _ensure_sensevoice(self) -> Any:
        """Loads SenseVoiceSmall (int8 ONNX via sherpa-onnx), auto-downloading once if absent."""
        with self._model_lock:
            if self._sensevoice_rec is not None:
                return self._sensevoice_rec
            import sherpa_onnx

            model_root = DATA_DIR / "models" / SENSEVOICE_DIR_NAME
            model_file = model_root / "model.int8.onnx"
            tokens_file = model_root / "tokens.txt"

            if not (model_file.exists() and tokens_file.exists()):
                models_dir = DATA_DIR / "models"
                models_dir.mkdir(parents=True, exist_ok=True)
                archive_path = models_dir / f"{SENSEVOICE_DIR_NAME}.tar.bz2"
                downloaded = False
                for url in SENSEVOICE_URLS:
                    try:
                        self._emit_status("首次使用 SenseVoice，正在下载动漫多语种语音模型 (~150MB)...")
                        req = urllib.request.Request(url, headers={"User-Agent": "QingYi/1.2"})
                        with urllib.request.urlopen(req, timeout=30) as resp, open(archive_path, "wb") as out_f:
                            while True:
                                chunk = resp.read(262144)
                                if not chunk:
                                    break
                                out_f.write(chunk)
                        self._emit_status("正在解压 SenseVoice 模型...")
                        with tarfile.open(archive_path, "r:bz2") as tf:
                            tf.extractall(models_dir)
                        archive_path.unlink(missing_ok=True)
                        downloaded = model_file.exists() and tokens_file.exists()
                        if downloaded:
                            break
                    except Exception:
                        archive_path.unlink(missing_ok=True)
                if not downloaded:
                    raise RuntimeError("SenseVoice 模型下载失败，自动切换为 Whisper 引擎")

            cores = os.cpu_count() or 8
            self._sensevoice_rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model_file),
                tokens=str(tokens_file),
                num_threads=min(4, max(2, cores // 4)),
                use_itn=True,
                debug=False,
            )
            self._emit_status("SenseVoice 动漫高准语音引擎已就绪")
            return self._sensevoice_rec

    def _transcribe_sensevoice(self, audio_16k: np.ndarray) -> str:
        rec = self._ensure_sensevoice()
        stream = rec.create_stream()
        stream.accept_waveform(16000, audio_16k)
        rec.decode_stream(stream)
        raw = str(stream.result.text or "").strip()
        # Strip SenseVoice meta tags like <|ja|><|NEUTRAL|><|Speech|><|woitn|>
        clean = re.sub(r"<\|[^|]+\|>", "", raw).strip()
        return clean

    def _transcribe_local(self, audio_16k: np.ndarray, lang_hint: Optional[str]) -> str:
        if self.cfg_mgr.config.whisper_model.strip() == "sensevoice":
            try:
                return self._transcribe_sensevoice(audio_16k)
            except Exception as exc:
                self._emit_status(f"{exc}")

        whisper_kwargs = dict(
            language=lang_hint,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            without_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 200, "speech_pad_ms": 100},
            condition_on_previous_text=False,
        )
        try:
            model = self._ensure_whisper(force_cpu=False)
            segments, _ = model.transcribe(audio_16k, **whisper_kwargs)
            return " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
        except Exception:
            # Automatic fallback to CPU int8 if CUDA fails at inference time
            self._cuda_available = False
            try:
                model = self._ensure_whisper(force_cpu=True)
                segments, _ = model.transcribe(audio_16k, **whisper_kwargs)
                return " ".join(s.text.strip() for s in segments if s.text.strip()).strip()
            except Exception as exc:
                self._emit_status(f"语音识别错误: {exc}")
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
