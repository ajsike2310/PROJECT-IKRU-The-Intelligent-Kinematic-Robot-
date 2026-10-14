"""
Offline speech-to-text for IKRU: faster-whisper (CTranslate2) on CUDA.

Loaded once and reused. There is deliberately no CPU or online fallback: if CUDA or the local
model is unavailable, WhisperSTT.load() raises SttError with an actionable message.
Validated in trial/offline_speech_recognition.
"""
import importlib.util
import os
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

SAMPLE_RATE = 16000


class SttError(RuntimeError):
    pass


@dataclass
class SttResult:
    text: str
    language: Optional[str]
    language_probability: Optional[float]
    audio_s: float
    processing_s: float


def _add_cuda_dll_dirs():
    """CTranslate2 needs cuBLAS 12 + cuDNN 9; the project's torch cu124 wheel ships both in torch/lib."""
    if os.name != "nt":
        return
    spec = importlib.util.find_spec("torch")
    for loc in (spec.submodule_search_locations or []) if spec else []:
        lib = os.path.join(loc, "lib")
        if os.path.isdir(lib):
            os.add_dll_directory(lib)
            os.environ["PATH"] = lib + os.pathsep + os.environ.get("PATH", "")


class WhisperSTT:
    def __init__(self, model_dir, model_name="small", compute_type="float16", device_index=0,
                 language=None, beam_size=5, min_audio_s=0.3):
        self.model_dir, self.model_name = str(model_dir), model_name
        self.compute_type, self.device_index = compute_type, device_index
        self.language, self.beam_size, self.min_audio_s = language, beam_size, min_audio_s
        self.model = None
        self.load_time_s = None

    def load(self):
        if not os.path.isfile(os.path.join(self.model_dir, "model.bin")):
            raise SttError(f"Whisper model not found in {self.model_dir!r}. Download it with: "
                           ".\\venv\\Scripts\\python.exe trial\\offline_speech_recognition\\run_trial.py download "
                           "and copy/point 'stt_model_dir' in config.json at the folder.")
        _add_cuda_dll_dirs()
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() < 1:
                raise SttError("CTranslate2 sees no CUDA device (check `nvidia-smi` / driver). Not falling back to CPU.")
            from faster_whisper import WhisperModel
            t0 = time.perf_counter()
            self.model = WhisperModel(self.model_dir, device="cuda", device_index=self.device_index,
                                      compute_type=self.compute_type, local_files_only=True)
            self.load_time_s = time.perf_counter() - t0
        except SttError:
            raise
        except Exception as e:
            raise SttError(f"Whisper CUDA init failed: {type(e).__name__}: {e} "
                           "(missing cublas64_12.dll/cudnn64_9.dll, old driver, or out of VRAM?)") from e
        return self

    def transcribe(self, pcm: bytes) -> Optional[SttResult]:
        """16 kHz mono int16 PCM -> SttResult, or None if the audio is empty/too short/silent."""
        if self.model is None:
            raise SttError("WhisperSTT.load() has not been called")
        if len(pcm) % 2:
            raise SttError(f"malformed int16 PCM ({len(pcm)} bytes)")
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        dur = audio.size / SAMPLE_RATE
        if dur < self.min_audio_s or float(np.abs(audio).max(initial=0.0)) < 1e-4:
            return None
        t0 = time.perf_counter()
        segments, info = self.model.transcribe(
            audio, language=self.language, task="transcribe", beam_size=self.beam_size, temperature=0.0,
            condition_on_previous_text=False, without_timestamps=True, vad_filter=False)
        text = " ".join(s.text.strip() for s in segments).strip()
        return SttResult(text, info.language, float(info.language_probability), dur, time.perf_counter() - t0)
