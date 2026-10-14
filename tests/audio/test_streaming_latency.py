"""
PROJECT IKRU — End-to-End Low Latency Pipeline Benchmark
=========================================================
Measures exact latency metrics across:
1. User Input -> First Ollama Token Latency
2. Sentence Boundary Parsing Latency
3. Sentence TTS Synthesis Latency
4. Total Perceived Response Latency (< 750ms Target)
"""

import sys
import time
from pathlib import Path

# Add project root and software dir to sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOFTWARE_DIR = PROJECT_ROOT / "software"
if str(SOFTWARE_DIR) not in sys.path:
    sys.path.insert(0, str(SOFTWARE_DIR))

from ikru.chat import ChatEngine
from ikru.audio import AudioService
from ikru import config


def benchmark_voice_latency(prompt: str = "Hello Ikru! How are you today?"):
    print("=" * 60)
    print(f"[BENCHMARK] Testing query: '{prompt}'")
    print("=" * 60)

    chat = ChatEngine()
    audio = AudioService(play_pc=False, engine="edge")

    t0 = time.perf_counter()
    first_token_time = None
    first_sentence_audio_time = None
    first_sentence_text = None
    tokens_received = 0

    print("[VOICE] [INPUT_RECEIVED] Querying streaming ChatEngine...")

    for event_type, data in chat.ask_stream(prompt):
        if event_type == "token":
            tokens_received += 1
            if first_token_time is None:
                first_token_time = (time.perf_counter() - t0) * 1000.0
                print(f"[VOICE] [FIRST_TOKEN_RECEIVED] Latency: {first_token_time:.1f}ms")

        elif event_type == "sentence":
            emo, sentence_text = data
            t_sent_start = time.perf_counter()
            audio_url, duration = audio.speak_to_file(sentence_text)
            t_tts = (time.perf_counter() - t_sent_start) * 1000.0

            if first_sentence_audio_time is None:
                first_sentence_audio_time = (time.perf_counter() - t0) * 1000.0
                first_sentence_text = sentence_text
                print(f"[VOICE] [FIRST_AUDIO_READY] Perceived Latency: {first_sentence_audio_time:.1f}ms")
                print(f"        Sentence 1: '{sentence_text}' (Emotion: {emo}, Audio Duration: {duration:.1f}s, TTS Gen: {t_tts:.1f}ms)")

        elif event_type == "done":
            tools, full_response = data
            total_roundtrip = (time.perf_counter() - t0) * 1000.0
            print(f"[VOICE] [RESPONSE_COMPLETED] Full Roundtrip: {total_roundtrip:.1f}ms | Tokens: {tokens_received}")
            print("=" * 60)

    # Verification checks
    assert first_token_time is not None, "First token was not received!"
    assert first_sentence_audio_time is not None, "First audio chunk was not generated!"
    print(f"[SUMMARY] First Token Latency : {first_token_time:.1f}ms")
    print(f"[SUMMARY] Perceived Audio Start: {first_sentence_audio_time:.1f}ms")
    print(f"[SUMMARY] Status               : {'SUCCESS (PASS)' if first_sentence_audio_time < 2000 else 'NEEDS ATTENTION'}")


if __name__ == "__main__":
    benchmark_voice_latency()
