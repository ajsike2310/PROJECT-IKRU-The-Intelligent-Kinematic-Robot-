"""
===============================================================================
PROJECT IKRU — R2-D2 NATURAL SENTENCE-TO-DROID INTERACTIVE HARNESS
===============================================================================

Type any sentence in natural language or choose a shortcut.
The system analyzes the sentence (sentiment, punctuation, questions, syllables, contour)
and replicates it into an authentic R2-D2 droid vocalization with continuous chirps,
glissando sweeps, and whistles.
===============================================================================
"""

import os
import sys
import time
from pathlib import Path

# Ensure project software directory is in sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(root_dir, "software"))

from ikru.audio import SonicEmotionEngine, DroidStep

# Optional winsound on Windows for instant speaker playback
try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False

# Optional websocket-client for live ESP32 testing
try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False


def render_ascii_pattern(emotion: str, intensity: float, steps: list, sentence: str = None) -> str:
    """Renders a visual ASCII representation of frequency sweeps, chirps, and word lengths."""
    title = f"R2-D2 Vocalization: [{emotion.upper()}] (Intensity: {intensity:.2f})"
    if sentence:
        title += f"\n  Sentence: \"{sentence}\""

    lines = [
        "=" * 75,
        f"  {title}",
        "-" * 75,
    ]

    min_freq = 150
    max_freq = 4500

    for idx, s in enumerate(steps):
        avg_f = (s.start_freq + s.end_freq) / 2.0
        norm = max(0.0, min(1.0, (avg_f - min_freq) / (max_freq - min_freq)))
        bar_len = int(norm * 18)

        if s.start_freq < s.end_freq:
            arrow = "↗ [UP CHIRP]"
        elif s.start_freq > s.end_freq:
            arrow = "↘ [DOWN SLIDE]"
        else:
            arrow = "→ [TONE]"

        marker = " " * bar_len + "●"
        word_info = f"[{s.word_label}]" if getattr(s, "word_label", "") else ""
        desc = f"{s.start_freq:4d}Hz -> {s.end_freq:4d}Hz ({s.duration_ms:3d}ms)"
        lines.append(f"  Step {idx + 1:02d}: {word_info:<16} {marker:<20} {desc:<24} {arrow}")

    total_time = sum(s.duration_ms + s.pause_ms for s in steps)
    lines.append("-" * 75)
    lines.append(f"  Total Words/Steps: {len(steps)} | Total Duration: {total_time} ms")
    lines.append("=" * 75)
    return "\n".join(lines)


import threading


def play_local_audio(engine: SonicEmotionEngine, steps: list, temp_dir: Path, volume: float = 0.20):
    """Plays the generated pattern locally through PC audio with adjustable volume."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    wav_path = temp_dir / "temp_preview.wav"

    try:
        wav_io = engine.synthesize_wav(steps, sample_rate=22050, volume=volume)
        wav_path.write_bytes(wav_io.getvalue())

        if HAS_WINSOUND:
            # Play in background thread so the whole sound completes without getting cut off
            t = threading.Thread(
                target=winsound.PlaySound,
                args=(str(wav_path), winsound.SND_FILENAME),
                daemon=True
            )
            t.start()
            print("  [AUDIO] Playing on PC speakers...")
        else:
            print(f"  [AUDIO] WAV saved to {wav_path}")
    except Exception as e:
        print(f"  [AUDIO] Local playback warning: {e}")


import socket


def send_to_esp32(engine: SonicEmotionEngine, emotion: str, intensity: float, steps: list, ip: str, tcp_port: int = 5000, ws_port: int = 81):
    """Sends the sound command to ESP32 via ultra-fast TCP (port 5000) or WebSocket (port 81)."""
    # Build payload string
    if steps and len(steps) > 0:
        tone_strs = [f"{int(s.start_freq)},{int(s.end_freq)},{int(s.duration_ms)},{int(s.pause_ms)}" for s in steps]
        cmd_str = f"TONES:{';'.join(tone_strs)}"
    else:
        cmd_str = f"SOUND:{emotion.upper()}:{intensity:.2f}"

    # 1. Try ultra-fast TCP socket (port 5000)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.5)
        sock.connect((ip, tcp_port))
        sock.sendall((cmd_str + "\n").encode("utf-8"))
        sock.recv(64)
        sock.close()
        print(f"  [ESP32] Transmitted to {ip}:{tcp_port} (TCP)")
        return
    except Exception:
        pass

    # 2. Fallback to WebSocket (port 81)
    if HAS_WEBSOCKET:
        try:
            ws = websocket.create_connection(
                f"ws://{ip}:{ws_port}",
                timeout=2.5,
                http_proxy_host=None,
                http_proxy_port=None
            )
            ws.send(cmd_str)
            ws.close()
            print(f"  [ESP32] Transmitted to ws://{ip}:{ws_port}")
            return
        except Exception as e:
            print(f"  [ESP32] Connection note: {ip} not reachable ({e})")
    else:
        print(f"  [ESP32] Connection note: {ip}:{tcp_port} not reachable")


# Alias for backward compatibility
send_to_esp32_ws = send_to_esp32


def main():
    engine = SonicEmotionEngine()
    current_intensity = 0.5
    current_volume = 0.20
    esp32_ip = "192.168.4.1"
    temp_dir = Path(__file__).parent / "scratch"

    SHORTCUTS = {
        "1": ("happy", "Happy (Joyful rising whistle & chirp trill)", None),
        "2": ("excited", "Excited (Fast ascending sparkle & high flutter)", None),
        "3": ("sad", "Sad (Long downward sliding whistle 'whooo-oo-op')", None),
        "4": ("angry", "Angry (Harsh low abrasive buzz & screech tantrum)", None),
        "5": ("confused", "Confused (Inquisitive droid chatter 'boop-weep?')", None),
        "6": ("surprised", "Surprised (Explosive rocket sweep & startled yip)", None),
        "7": ("thinking", "Thinking (Conversational computing chatter)", None),
        "8": ("success", "Success (Triumphant 4-stage ascending fanfare)", None),
        "9": ("error", "Error (Harsh descending rasp/buzz 'BZZT-BZZT')", None),
        "0": ("neutral", "Neutral (Classic 2-chirp droid greeting)", None),
        "w": ("warning", "Warning (Rapid urgent alternating siren trills)", None),
        "p": ("processing", "Processing (Fast rhythmic radar clicks)", None),
        "c": ("cannot_perform", "Cannot Perform (Sad descending double boop)", None),
        "s": ("sleepy", "Sleepy (Powering-down whistle trailing into silence)", None),
        "a": ("affection", "Affection (Loving melodic droid whistle)", None),
    }

    print("\n" + "=" * 70)
    print("   PROJECT IKRU — R2-D2 DROID HARNESS (STANDALONE AP MODE)")
    print("=" * 70)
    print("  ESP32 Access Point: 'IKRU-AUDIO' (Pass: 'ikru@potato')")
    print("  Target Endpoint    : 192.168.4.1:5000 (TCP) / ws://192.168.4.1:81")
    print(f"  Current Volume     : {int(current_volume * 100)}%")
    print("-" * 70)
    print("  How to use:")
    print("   * Type ANY natural language sentence! (e.g. 'I found your mug!')")
    print("   * Or use key shortcuts: [1-9, 0, w, p, c, s, a]")
    print("   * [v <0.0-1.0>] : Set PC volume (e.g. 'v 0.1' for quiet, 'v 0.3' for soft)")
    print("   * [i <0.0-1.0>] : Set emotion intensity override (e.g. 'i 0.8')")
    print("   * [demo]        : Play automated showcase of all emotions")
    print("   * [q / exit]    : Quit")
    print("=" * 70)

    while True:
        try:
            prompt_str = f"\n[IKRU R2-D2] Type sentence or command > "
            user_input = input(prompt_str).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue

        cmd_lower = user_input.lower().strip()

        if cmd_lower in ["q", "exit", "quit"]:
            print("Goodbye!")
            break

        # Change Volume command: e.g. "v 0.15" or "vol 0.3"
        if cmd_lower.startswith(("v ", "vol ", "volume ", "/v ")):
            parts = cmd_lower.split()
            if len(parts) >= 2:
                try:
                    val = float(parts[1])
                    current_volume = max(0.0, min(1.0, val))
                    print(f"  -> PC Volume set to: {int(current_volume * 100)}% ({current_volume:.2f})")
                    continue
                except ValueError:
                    print("  [Error] Invalid volume number. Use range 0.0 to 1.0 (e.g. 'v 0.15')")
                    continue
                val = float(parts[1])
                current_intensity = engine.clamp_intensity(val)
                print(f"  -> Intensity set to: {current_intensity:.2f}")
                continue
                """except ValueError:
                # Not an intensity command, it's a sentence like "I found..."!
                    pass"""

        # Set ESP32 IP
        if cmd_lower.startswith(("esp ", "set_esp ", "/esp ")):
            parts = cmd_lower.split()
            if len(parts) == 2:
                target = parts[1].strip()
                if target.lower() in ["ap", "ap_mode", "softap"]:
                    esp32_ip = "192.168.4.1"
                else:
                    esp32_ip = target
                print(f"  -> ESP32 IP set to: {esp32_ip}")
                continue

        # Full Demo Sweep
        if cmd_lower == "demo":
            print("\n  >>> RUNNING FULL R2-D2 DROID DEMO TOUR <<<")
            sample_phrases = [
                "Hey there, great to see you!",
                "I am so excited and happy today!",
                "Oh no, I am very sorry that happened...",
                "Why are you doing that?",
                "I successfully finished your task!",
                "Watch out! Warning obstacle ahead!",
                "I am feeling so sleepy, goodnight...",
                "You are my best friend!"
            ]
            for phrase in sample_phrases:
                print(f"\nPhrase: \"{phrase}\"")
                emo, eff_int, steps = engine.sentence_to_droid_pattern(phrase)
                print(render_ascii_pattern(emo, eff_int, steps, sentence=phrase))
                play_local_audio(engine, steps, temp_dir, volume=current_volume)
                send_to_esp32_ws(engine, emo, eff_int, steps, esp32_ip)
                time.sleep(max(0.7, sum(s.duration_ms + s.pause_ms for s in steps) / 1000.0 + 0.4))
            print("\n  >>> DEMO COMPLETE <<<")
            continue

        # Single key shortcuts
        if cmd_lower in SHORTCUTS:
            emo, desc, intent = SHORTCUTS[cmd_lower]
            steps = engine.generate_pattern(emo, current_intensity, intent)
            print(render_ascii_pattern(emo, current_intensity, steps))
            play_local_audio(engine, steps, temp_dir, volume=current_volume)
            send_to_esp32_ws(engine, emo, current_intensity, steps, esp32_ip)
            continue

        # NATURAL SENTENCE INPUT! (Sentence -> R2-D2 Droid Vocalization)
        emo, eff_int, steps = engine.sentence_to_droid_pattern(user_input, intensity=None)
        print(render_ascii_pattern(emo, eff_int, steps, sentence=user_input))
        play_local_audio(engine, steps, temp_dir, volume=current_volume)
        send_to_esp32_ws(engine, emo, eff_int, steps, esp32_ip)


if __name__ == "__main__":
    main()
