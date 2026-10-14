import queue
import threading
import time

import os

import pyaudio

from .stt import WhisperSTT
from .vad import SAMPLE_RATE, FRAME_SAMPLES, SpeechSegmenter, load_vad


_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class MicController:
    """
    Handles microphone capture, Voice Activity Detection (Silero VAD) and
    offline speech-to-text (faster-whisper on CUDA, auto language detection).

    Capture and transcription run on separate threads, so the mic keeps
    listening while a previous sentence is being transcribed.
    """
    def __init__(self, vad="silero", vad_threshold=0.5, silence_ms=500,
                 max_utterance_s=12.0, device_index=None, preroll_ms=400,
                 stt_model="small", stt_model_dir="data/models/faster-whisper-small",
                 stt_compute_type="float16", stt_language=None, **_ignored):
        self.device_index = device_index
        self.last_language = None   # language detected for the most recent utterance
        self._segmenter_args = dict(
            threshold=vad_threshold,
            silence_ms=silence_ms,
            max_utterance_s=max_utterance_s,
            preroll_ms=preroll_ms,
        )

        print("[Audio] Initializing Microphone...")
        self.vad_name, self.vad_prob = load_vad(vad)
        if not os.path.isabs(stt_model_dir):
            stt_model_dir = os.path.join(_REPO_ROOT, stt_model_dir)
        print(f"[Audio] Loading Whisper '{stt_model}' on CUDA...")
        self.stt = WhisperSTT(stt_model_dir, stt_model, stt_compute_type, language=stt_language).load()
        print(f"[Audio] Whisper ready in {self.stt.load_time_s:.1f}s.")
        self._pa = pyaudio.PyAudio()
        self._stream = None
        self._running = False
        print(f"[Audio] Microphone ready (VAD: {self.vad_name}, end-of-speech after {silence_ms} ms silence).")

    def _open_stream(self):
        if self._stream is None:
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=FRAME_SAMPLES,
                input_device_index=self.device_index,
            )
        return self._stream

    def _read_frame(self):
        return self._open_stream().read(FRAME_SAMPLES, exception_on_overflow=False)

    def _transcribe(self, pcm: bytes) -> str:
        r = self.stt.transcribe(pcm)
        if r is None:
            return ""
        self.last_language = r.language
        print(f"  [STT] {r.language} ({r.language_probability:.2f}) {r.processing_s * 1000:.0f}ms")
        return r.text

    def listen(self) -> str:
        """
        Blocks until one utterance has been spoken and returns the recognized text.
        Returns an empty string if the speech couldn't be recognized.
        """
        print("\n[Mic] Listening... (Say 'exit' to quit)")
        segmenter = SpeechSegmenter(**self._segmenter_args)
        while True:
            frame = self._read_frame()
            for kind, pcm in segmenter.process(frame, self.vad_prob(frame)):
                if kind != "end":
                    continue
                print("  [Processing audio...]")
                try:
                    return self._transcribe(pcm)
                except Exception as e:
                    print(f"  [STT Error: {e}]")
                    return ""

    def start_background_listening(self, on_text, on_speech_start=None):
        """
        Starts capture + transcription threads.
        `on_text(text, t_speech_end)` is called for every recognized utterance.
        `on_speech_start()` (optional) fires as soon as the VAD hears a voice.
        Returns a stop function (accepts wait_for_stop for compatibility).
        """
        utterances = queue.Queue()
        self._running = True

        def capture_loop():
            segmenter = SpeechSegmenter(**self._segmenter_args)
            while self._running:
                try:
                    frame = self._read_frame()
                except Exception as e:
                    print(f"[Mic] Capture error: {e}")
                    time.sleep(0.5)
                    continue
                for kind, pcm in segmenter.process(frame, self.vad_prob(frame)):
                    if kind == "start" and on_speech_start:
                        try:
                            on_speech_start()
                        except Exception:
                            pass
                    elif kind == "end":
                        utterances.put((pcm, time.time()))

        def stt_loop():
            while self._running:
                try:
                    pcm, t_end = utterances.get(timeout=0.5)
                except queue.Empty:
                    continue
                speech_s = len(pcm) / (SAMPLE_RATE * 2)
                t0 = time.time()
                try:
                    text = self._transcribe(pcm)
                except Exception as e:
                    print(f"  [STT Error: {e}]")
                    continue
                print(f"\n[Mic] speech {speech_s:.1f}s | STT {int((time.time() - t0) * 1000)}ms")
                if text:
                    try:
                        on_text(text, t_end)
                    except Exception as e:
                        print(f"[Mic] Callback error: {e}")

        threads = [
            threading.Thread(target=capture_loop, daemon=True, name="mic-capture"),
            threading.Thread(target=stt_loop, daemon=True, name="mic-stt"),
        ]
        for t in threads:
            t.start()

        def stop(wait_for_stop=False):
            self._running = False
            if wait_for_stop:
                for t in threads:
                    t.join(timeout=2.0)

        return stop
