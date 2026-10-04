"""
===============================================================================
PROJECT IKRU — ESP32-CAM DIAGNOSTIC TEST
===============================================================================
Connects to the ESP32-CAM over the IKRU UDP protocol (discovery on 2223,
video on 2222) using the production VisionReceiver, then checks:

  1. Connection   — does a first frame arrive within the timeout?
  2. Stream health — FPS, completed vs. discarded frames, packet throughput
  3. Image quality — resolution, brightness, sharpness (blur), frozen frames

A live window shows the feed with stats. Keys:
  s       save a snapshot
  q / ESC stop early

Usage:
  python tests/vision/test_camera.py
  python tests/vision/test_camera.py --ip 192.168.1.50 --duration 20
  python tests/vision/test_camera.py --no-window
===============================================================================
"""

import os
import sys
import time
import argparse

import cv2
import numpy as np

# Ensure 'software' directory is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
software_dir = os.path.join(project_root, "software")
if software_dir not in sys.path:
    sys.path.insert(0, software_dir)

from ikru import config
from ikru.vision.receiver import VisionReceiver

# Pass/warn thresholds
MIN_FPS = 5.0
MAX_DISCARD_RATIO = 0.25
MIN_BRIGHTNESS = 40.0     # mean gray level (0-255); below = too dark / lens covered
MAX_BRIGHTNESS = 220.0    # above = overexposed
MIN_SHARPNESS = 50.0      # Laplacian variance; below = blurry / out of focus
FROZEN_DIFF = 0.5         # mean abs diff between frames treated as "identical"
FROZEN_SECONDS = 3.0      # identical frames for this long = stream frozen

WINDOW_NAME = "IKRU Camera Test"


def grid_mask(h, w, margin=2):
    """Mask that excludes the 5x5 grid VisionReceiver draws onto every frame,
    so the grid's hard edges don't inflate brightness/sharpness readings."""
    mask = np.ones((h, w), dtype=bool)
    for i in range(1, 5):
        x, y = i * w // 5, i * h // 5
        mask[:, max(0, x - margin):x + margin + 1] = False
        mask[max(0, y - margin):y + margin + 1, :] = False
    return mask


def analyze_frame(frame):
    """Returns (brightness, sharpness, gray) for a BGR frame."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mask = grid_mask(*gray.shape)
    brightness = float(gray[mask].mean())
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F)[mask].var())
    return brightness, sharpness, gray


def wait_for_first_frame(receiver, timeout_s):
    start = time.perf_counter()
    while time.perf_counter() - start < timeout_s:
        if receiver.buffer.has_frame():
            return time.perf_counter() - start
        print(f"\r[*] Waiting for frames... {time.perf_counter() - start:4.1f}s "
              f"(packets: {receiver.packets_received})", end="", flush=True)
        time.sleep(0.1)
    print()
    return None


def save_snapshot(frame, snapshot_dir):
    os.makedirs(snapshot_dir, exist_ok=True)
    path = os.path.join(snapshot_dir, f"ikru_cam_{time.strftime('%Y%m%d_%H%M%S')}.jpg")
    cv2.imwrite(path, frame)
    print(f"\n[+] Snapshot saved: {path}")
    return path


def print_check(label, ok, detail, warn_only=False):
    tag = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    print(f"  [{tag}] {label:<16} {detail}")
    return ok or warn_only


def test_camera(cam_ip, video_port, discovery_port, duration_s, connect_timeout_s,
                show_window, snapshot_dir):
    print("=" * 70)
    print("  IKRU: ESP32-CAM Diagnostic Test")
    print("=" * 70)
    print(f"[*] Camera     : {cam_ip} (discovery UDP {discovery_port})")
    print(f"[*] Listening  : UDP 0.0.0.0:{video_port}")

    receiver = VisionReceiver(
        cam_ip=cam_ip,
        video_port=video_port,
        discovery_port=discovery_port,
        show_window=False,
    )
    receiver.start()
    time.sleep(0.2)
    if not receiver.running:
        print(f"[-] Could not bind UDP port {video_port}. Is IKRU (main.py) or another "
              f"vision test already running?")
        return False

    # ── Phase 1: connection ─────────────────────────────────
    first_frame_s = wait_for_first_frame(receiver, connect_timeout_s)
    if first_frame_s is None:
        print(f"[-] No frames received within {connect_timeout_s:.0f}s.")
        print(f"    Packets received: {receiver.packets_received}")
        print("    Troubleshooting:")
        print("     - Is the PC connected to the camera's Wi-Fi / same network?")
        print(f"     - Is the camera IP correct? (try --ip, or set IKRU_CAM_IP)")
        print(f"     - Windows Firewall may be blocking inbound UDP {video_port} for python.exe")
        print("     - Power-cycle the ESP32-CAM (brownouts are common on weak supplies)")
        receiver.stop()
        return False
    print(f"\r[+] First frame after {first_frame_s * 1000:.0f} ms" + " " * 30)

    # ── Phase 2: stream + image quality ─────────────────────
    print(f"[*] Measuring stream for {duration_s:.0f}s"
          + (" (s = snapshot, q/ESC = stop)" if show_window else "") + "...\n")

    completed_start = receiver.frames_completed
    discarded_start = receiver.frames_discarded
    packets_start = receiver.packets_received

    resolution = None
    resolution_changes = 0
    brightness_samples = []
    sharpness_samples = []
    fps_samples = []
    prev_gray = None
    frozen_since = None
    longest_frozen_s = 0.0
    longest_gap_s = 0.0
    last_new_frame_t = time.perf_counter()
    last_frame = None
    snapshots = []

    start = time.perf_counter()
    last_print = 0.0
    try:
        while time.perf_counter() - start < duration_s:
            now = time.perf_counter()
            frame = receiver.buffer.get_frame()

            if frame is not None and (last_frame is None or frame.shape != last_frame.shape
                                      or not np.array_equal(frame, last_frame)):
                longest_gap_s = max(longest_gap_s, now - last_new_frame_t)
                last_new_frame_t = now
                last_frame = frame

                h, w = frame.shape[:2]
                if resolution is None:
                    resolution = (w, h)
                elif resolution != (w, h):
                    resolution_changes += 1
                    resolution = (w, h)

                brightness, sharpness, gray = analyze_frame(frame)
                brightness_samples.append(brightness)
                sharpness_samples.append(sharpness)

                # Frozen-scene detection: new frame objects but pixel-identical content
                if prev_gray is not None and prev_gray.shape == gray.shape:
                    diff = float(cv2.absdiff(gray, prev_gray).mean())
                    if diff < FROZEN_DIFF:
                        frozen_since = frozen_since or now
                        longest_frozen_s = max(longest_frozen_s, now - frozen_since)
                    else:
                        frozen_since = None
                prev_gray = gray
            else:
                longest_gap_s = max(longest_gap_s, now - last_new_frame_t)

            if receiver.fps > 0:
                fps_samples.append(receiver.fps)

            if now - last_print >= 0.5:
                last_print = now
                b = brightness_samples[-1] if brightness_samples else 0
                s = sharpness_samples[-1] if sharpness_samples else 0
                print(f"\r  FPS {receiver.fps:5.1f} | done {receiver.frames_completed - completed_start:5d} "
                      f"| dropped {receiver.frames_discarded - discarded_start:4d} "
                      f"| bright {b:5.1f} | sharp {s:7.1f} "
                      f"| {duration_s - (now - start):4.1f}s left", end="", flush=True)

            if show_window:
                display = last_frame.copy() if last_frame is not None else np.zeros((240, 320, 3), np.uint8)
                lines = [
                    f"FPS: {receiver.fps:.1f}",
                    f"Res: {resolution[0]}x{resolution[1]}" if resolution else "Res: -",
                    f"Bright: {brightness_samples[-1]:.0f}" if brightness_samples else "Bright: -",
                    f"Sharp: {sharpness_samples[-1]:.0f}" if sharpness_samples else "Sharp: -",
                ]
                for i, text in enumerate(lines):
                    cv2.putText(display, text, (5, 18 + i * 18), cv2.FONT_HERSHEY_SIMPLEX,
                                0.5, (0, 255, 0), 1)
                cv2.imshow(WINDOW_NAME, display)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    print("\n[*] Stopped early by user.")
                    break
                if key == ord("s") and last_frame is not None:
                    snapshots.append(save_snapshot(last_frame, snapshot_dir))
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n[*] Interrupted.")

    elapsed = time.perf_counter() - start
    completed = receiver.frames_completed - completed_start
    discarded = receiver.frames_discarded - discarded_start
    packets = receiver.packets_received - packets_start

    # Always keep one snapshot for reference
    if not snapshots and last_frame is not None:
        snapshots.append(save_snapshot(last_frame, snapshot_dir))

    receiver.stop()
    if show_window:
        cv2.destroyAllWindows()

    # ── Report ──────────────────────────────────────────────
    avg_fps = completed / elapsed if elapsed > 0 else 0.0
    total_frames = completed + discarded
    discard_ratio = discarded / total_frames if total_frames else 1.0
    avg_brightness = float(np.mean(brightness_samples)) if brightness_samples else 0.0
    avg_sharpness = float(np.median(sharpness_samples)) if sharpness_samples else 0.0

    print("\n")
    print("=" * 70)
    print("  RESULTS")
    print("=" * 70)
    print(f"  Duration          : {elapsed:.1f}s")
    print(f"  Packets received  : {packets} ({packets / elapsed:.0f}/s)" if elapsed > 0 else "")
    print(f"  Frames completed  : {completed}")
    print(f"  Frames discarded  : {discarded}")
    print(f"  Avg frame size    : {receiver.avg_frame_size_kb:.1f} KB")
    if fps_samples:
        print(f"  FPS min/avg/max   : {min(fps_samples):.1f} / {avg_fps:.1f} / {max(fps_samples):.1f}")
    print(f"  Longest gap       : {longest_gap_s * 1000:.0f} ms")
    print(f"  Snapshots         : {', '.join(snapshots) if snapshots else 'none'}")
    print("-" * 70)

    passed = True
    passed &= print_check("Connection", True, f"first frame in {first_frame_s * 1000:.0f} ms")
    passed &= print_check("Frame rate", avg_fps >= MIN_FPS,
                          f"{avg_fps:.1f} FPS (min {MIN_FPS:.0f})")
    passed &= print_check("Frame loss", discard_ratio <= MAX_DISCARD_RATIO,
                          f"{discard_ratio * 100:.1f}% discarded (max {MAX_DISCARD_RATIO * 100:.0f}%)")
    passed &= print_check("Resolution", resolution is not None and resolution_changes == 0,
                          (f"{resolution[0]}x{resolution[1]}" if resolution else "unknown")
                          + (f" (changed {resolution_changes}x)" if resolution_changes else ""),
                          warn_only=True)
    passed &= print_check("Brightness", MIN_BRIGHTNESS <= avg_brightness <= MAX_BRIGHTNESS,
                          f"{avg_brightness:.0f}/255 (ok {MIN_BRIGHTNESS:.0f}-{MAX_BRIGHTNESS:.0f}; "
                          f"lens covered or bad lighting?)" if not MIN_BRIGHTNESS <= avg_brightness <= MAX_BRIGHTNESS
                          else f"{avg_brightness:.0f}/255", warn_only=True)
    passed &= print_check("Sharpness", avg_sharpness >= MIN_SHARPNESS,
                          f"{avg_sharpness:.0f} (min {MIN_SHARPNESS:.0f}; "
                          f"blank scene or lens out of focus?)" if avg_sharpness < MIN_SHARPNESS
                          else f"{avg_sharpness:.0f}", warn_only=True)
    passed &= print_check("Frozen feed", longest_frozen_s < FROZEN_SECONDS,
                          f"longest identical run {longest_frozen_s:.1f}s (max {FROZEN_SECONDS:.0f}s)")
    print("=" * 70)
    print(f"  OVERALL: {'PASS' if passed else 'FAIL'}")
    print("=" * 70)
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IKRU ESP32-CAM Diagnostic")
    parser.add_argument("--ip", default=config.DEFAULT_CAM_IP, help="ESP32-CAM IP")
    parser.add_argument("--port", type=int, default=config.CAM_VIDEO_PORT, help="UDP video port")
    parser.add_argument("--discovery-port", type=int, default=config.CAM_DISCOVERY_PORT,
                        help="UDP discovery port")
    parser.add_argument("--duration", type=float, default=10.0, help="Measurement time in seconds")
    parser.add_argument("--connect-timeout", type=float, default=8.0,
                        help="Seconds to wait for the first frame")
    parser.add_argument("--no-window", action="store_true", help="Run headless (no preview window)")
    parser.add_argument("--snapshot-dir", default=os.path.join(project_root, "tests", "vision", "output"),
                        help="Where snapshots are saved")
    args = parser.parse_args()

    ok = test_camera(
        cam_ip=args.ip,
        video_port=args.port,
        discovery_port=args.discovery_port,
        duration_s=args.duration,
        connect_timeout_s=args.connect_timeout,
        show_window=not args.no_window,
        snapshot_dir=args.snapshot_dir,
    )
    sys.exit(0 if ok else 1)
