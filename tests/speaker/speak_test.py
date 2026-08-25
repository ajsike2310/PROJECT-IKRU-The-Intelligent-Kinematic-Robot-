import io
import socket
import sys
import time
import wave
from pathlib import Path
import numpy as np

# ============================================================
# IKRU AUDIO CONVERTER & SENDER (ALL-IN-ONE)
#
# Automatically converts any WAV (Stereo/Mono, any sample rate)
# to 16kHz Mono 16-bit PCM in-memory and streams it to ESP32-CAM.
# ============================================================

ESP32_IP = "192.168.4.1"
PORT = 5000
TARGET_SAMPLE_RATE = 16000
CHUNK_SIZE = 4096


def convert_wav_to_16k_mono_pcm(file_path):
    """
    Reads any 16-bit/8-bit WAV file, converts stereo to mono,
    and resamples to 16000 Hz 16-bit PCM.
    Returns: in-memory BytesIO WAV buffer, duration in seconds.
    """
    with wave.open(str(file_path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    print(f"\n[INPUT WAV] Channels: {channels}, Bits: {sample_width * 8}, Rate: {sample_rate} Hz, Frames: {frame_count}")

    # Parse raw bytes into numpy array
    if sample_width == 2:
        audio = np.frombuffer(raw, dtype=np.int16)
    elif sample_width == 1:
        # Convert 8-bit unsigned (0..255) to 16-bit signed (-32768..32767)
        audio = (np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128) * 256
    else:
        raise ValueError(f"Unsupported sample width: {sample_width} bytes ({sample_width * 8}-bit). Only 8/16-bit supported.")

    # 1. Convert Stereo -> Mono
    if channels == 2:
        audio = audio[:len(audio) - (len(audio) % 2)]
        audio = audio.reshape(-1, 2)
        audio = (audio[:, 0].astype(np.int32) + audio[:, 1].astype(np.int32)) // 2
        audio = audio.astype(np.int16)
        print("  -> Converted stereo to mono")
    elif channels != 1:
        raise ValueError("Only mono or stereo audio is supported.")

    # 2. Resample to Target Sample Rate (e.g. 16000 Hz)
    if sample_rate != TARGET_SAMPLE_RATE:
        print(f"  -> Resampling {sample_rate} Hz -> {TARGET_SAMPLE_RATE} Hz")
        old_length = len(audio)
        new_length = int(old_length * TARGET_SAMPLE_RATE / sample_rate)
        old_positions = np.linspace(0, old_length - 1, old_length)
        new_positions = np.linspace(0, old_length - 1, new_length)
        audio = np.interp(new_positions, old_positions, audio).astype(np.int16)

    # 3. Create In-Memory Converted WAV
    wav_bytes_io = io.BytesIO()
    with wave.open(wav_bytes_io, "wb") as out_wav:
        out_wav.setnchannels(1)
        out_wav.setsampwidth(2)
        out_wav.setframerate(TARGET_SAMPLE_RATE)
        out_wav.writeframes(audio.tobytes())

    duration = len(audio) / TARGET_SAMPLE_RATE
    wav_bytes_io.seek(0)
    return wav_bytes_io, duration


def send_wav_to_esp32(wav_io, duration, ip=ESP32_IP, port=PORT):
    """
    Connects to ESP32-CAM TCP server and streams the WAV data.
    """
    total_size = len(wav_io.getbuffer())
    print(f"\n[NETWORK] Connecting to ESP32-CAM at {ip}:{port}...")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)

    try:
        sock.connect((ip, port))
    except OSError as e:
        print(f"[ERROR] Could not connect to ESP32-CAM: {e}")
        print("  -> Make sure your PC is connected to the 'esp_audio' or 'IKRU-CAM' Wi-Fi AP.")
        sock.close()
        return False

    print("[NETWORK] Connected!")
    print(f"[AUDIO] Streaming {total_size / 1024:.1f} KB ({duration:.2f}s) to ESP32-CAM...")

    total_sent = 0
    start_time = time.perf_counter()

    try:
        while True:
            chunk = wav_io.read(CHUNK_SIZE)
            if not chunk:
                break

            sock.sendall(chunk)
            total_sent += len(chunk)
            progress = (total_sent / total_size) * 100
            print(f"\r[AUDIO] Progress: {progress:6.1f}% [{total_sent}/{total_size} bytes]", end="", flush=True)

    except OSError as e:
        print(f"\n[ERROR] Audio transfer failed: {e}")
        sock.close()
        return False

    elapsed = time.perf_counter() - start_time
    print(f"\n[AUDIO] Transfer complete in {elapsed:.2f}s!")

    try:
        sock.shutdown(socket.SHUT_WR)
        sock.close()
    except Exception:
        pass

    print("[NETWORK] Playback started on ESP32-CAM speaker.")
    return True


def main():
    if len(sys.argv) < 2:
        print("=" * 50)
        print("  IKRU ALL-IN-ONE AUDIO CONVERTER & SENDER")
        print("=" * 50)
        print("Usage:")
        print('  python tests/speaker/speak_test.py "path/to/audio.wav"')
        print('  python tests/speaker/speak_test.py "audio.wav" --save "converted.wav"')
        print("=" * 50)
        return 1

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"[ERROR] File not found: {input_path}")
        return 1

    print("=" * 50)
    print(f"  Processing Audio: {input_path.name}")
    print("=" * 50)

    try:
        # Convert and resample audio on-the-fly
        converted_io, duration = convert_wav_to_16k_mono_pcm(input_path)

        # Optional: Save converted file if requested
        if "--save" in sys.argv:
            save_idx = sys.argv.index("--save") + 1
            if save_idx < len(sys.argv):
                save_path = Path(sys.argv[save_idx])
                save_path.write_bytes(converted_io.getvalue())
                print(f"[SAVED] Exported converted WAV to: {save_path}")

        # Stream directly to ESP32-CAM
        success = send_wav_to_esp32(converted_io, duration)
        return 0 if success else 1

    except Exception as e:
        print(f"\n[ERROR] {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())