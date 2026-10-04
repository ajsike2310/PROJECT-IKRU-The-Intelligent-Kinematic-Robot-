"""
===============================================================================
IKRU ESP32-CAM + YOLOv8 Real-Time UDP Receiver & Object Detector
===============================================================================
Receives UDP stream from ESP32-CAM on port 2222 (discovery on port 2223)
and performs real-time YOLO object detection.

Usage:
  python tests/vision/test_udp_receiver_yolo.py
  python tests/vision/test_udp_receiver_yolo.py --model yolov8n.pt --conf 0.45
===============================================================================
"""

import os
import sys
import time
import socket
import struct
import argparse
import cv2
import numpy as np

# Try importing ultralytics YOLO
try:
    from ultralytics import YOLO
    HAS_ULTRALYTICS = True
except ImportError:
    HAS_ULTRALYTICS = False

# ============================================================
# DEFAULTS & CONFIG
# ============================================================

ESP32_CAM_IP = "192.168.4.1"
DISCOVERY_PORT = 2223
VIDEO_PORT = 2222

MAGIC = 0x494B
VERSION = 1
PACKET_VIDEO = 0

HEADER_FORMAT = "<HBBIHHIHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
FRAME_TIMEOUT = 0.15


# ============================================================
# MAIN FUNCTION
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="IKRU ESP32-CAM UDP YOLO Receiver")
    parser.add_argument("--ip", default=ESP32_CAM_IP, help="ESP32-CAM IP address")
    parser.add_argument("--port", type=int, default=VIDEO_PORT, help="UDP video port")
    parser.add_argument("--discovery-port", type=int, default=DISCOVERY_PORT, help="UDP discovery port")
    parser.add_argument("--model", default="yolov8n.pt", help="YOLO model path or name (default: yolov8n.pt)")
    parser.add_argument("--conf", type=float, default=0.40, help="Confidence threshold (default: 0.40)")
    parser.add_argument("--imgsz", type=int, default=320, help="Inference image size (default: 320 for speed)")
    parser.add_argument("--device", default="cpu", help="Device for YOLO inference (default: 'cpu' to avoid torchvision CUDA NMS mismatch)")
    args = parser.parse_args()

    if not HAS_ULTRALYTICS:
        print("[!] Warning: 'ultralytics' library is not installed in the active environment.")
        print("    Install it via: pip install ultralytics")
        sys.exit(1)

    print(f"[MODEL] Loading YOLO model: {args.model}...")
    try:
        yolo_model = YOLO(args.model)
        print(f"[MODEL] YOLO model '{args.model}' loaded successfully.")
    except Exception as e:
        print(f"[-] Failed to load YOLO model: {e}")
        sys.exit(1)

    # ------------------------------------------------------------
    # UDP Socket Initialization
    # ------------------------------------------------------------
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    try:
        sock.bind(("0.0.0.0", args.port))
    except Exception as e:
        print(f"[-] Failed to bind UDP port {args.port}: {e}")
        sys.exit(1)

    sock.settimeout(0.5)

    print()
    print("==========================================================")
    print("       IKRU ESP32-CAM + YOLO REAL-TIME TEST")
    print("==========================================================")
    print(f"[UDP] Listening on port {args.port}")

    # ------------------------------------------------------------
    # Send Discovery Handshake
    # ------------------------------------------------------------
    discovery = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        discovery.sendto(b"IKRU_DISCOVER", (args.ip, args.discovery_port))
        print(f"[DISCOVERY] Request sent to {args.ip}:{args.discovery_port}")
    except Exception as e:
        print(f"[DISCOVERY] Warning: Could not send discovery: {e}")
    finally:
        discovery.close()

    print("[UDP] Waiting for camera stream...")
    print("Press 'q' or ESC in the window, or Ctrl+C in terminal to stop.")
    print()

    # Frame reassembly storage
    frames = {}
    highest_frame_id = -1

    # Metrics
    packets_received = 0
    bytes_received = 0
    frames_started = 0
    frames_completed = 0
    frames_discarded = 0
    decoded_frames = 0
    detected_objects = 0
    inference_count = 0
    inference_time = 0.0

    start_time = time.perf_counter()

    def cleanup_frames():
        nonlocal frames_discarded
        now = time.perf_counter()
        expired = [fid for fid, f in frames.items() if now - f["received_at"] > FRAME_TIMEOUT]
        for fid in expired:
            del frames[fid]
            frames_discarded += 1

    def decode_jpeg(data):
        if len(data) < 4 or data[:2] != b"\xff\xd8" or data[-2:] != b"\xff\xd9":
            return None
        array = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(array, cv2.IMREAD_COLOR)

    # ------------------------------------------------------------
    # Main Streaming & Detection Loop
    # ------------------------------------------------------------
    try:
        while True:
            cleanup_frames()

            try:
                packet, address = sock.recvfrom(65535)
            except socket.timeout:
                continue

            if packet == b"IKRU_CAMERA":
                print(f"[DISCOVERY] ESP32-CAM connected from {address[0]}")
                continue

            packets_received += 1
            bytes_received += len(packet)

            if len(packet) < HEADER_SIZE:
                continue

            (
                magic,
                version,
                packet_type,
                frame_id,
                chunk_id,
                total_chunks,
                frame_length,
                chunk_length,
                timestamp,
            ) = struct.unpack(HEADER_FORMAT, packet[:HEADER_SIZE])

            if magic != MAGIC or version != VERSION or packet_type != PACKET_VIDEO:
                continue

            payload = packet[HEADER_SIZE:]
            if len(payload) != chunk_length:
                continue

            if frame_id < highest_frame_id:
                continue

            if frame_id > highest_frame_id:
                highest_frame_id = frame_id
                old_frames = [fid for fid in frames if fid < frame_id]
                for fid in old_frames:
                    del frames[fid]
                    frames_discarded += 1

            if frame_id not in frames:
                frames[frame_id] = {
                    "total_chunks": total_chunks,
                    "frame_length": frame_length,
                    "chunks": {},
                    "received_at": time.perf_counter(),
                }
                frames_started += 1

            frame = frames[frame_id]
            if chunk_id < total_chunks:
                frame["chunks"][chunk_id] = payload

            if len(frame["chunks"]) != total_chunks:
                continue

            chunks = [frame["chunks"].get(i) for i in range(total_chunks)]
            del frames[frame_id]

            if None in chunks:
                frames_discarded += 1
                continue

            jpeg = b"".join(chunks)
            if len(jpeg) != frame_length:
                frames_discarded += 1
                continue

            frames_completed += 1
            image = decode_jpeg(jpeg)
            if image is None:
                continue

            decoded_frames += 1

            # ------------------------------------------------------------
            # YOLO Object Detection
            # ------------------------------------------------------------
            inf_start = time.perf_counter()
            results = yolo_model(image, conf=args.conf, imgsz=args.imgsz, device=args.device, verbose=False)
            inf_elapsed = time.perf_counter() - inf_start

            inference_count += 1
            inference_time += inf_elapsed

            objects_in_frame = 0
            if len(results) > 0 and results[0].boxes is not None:
                boxes = results[0].boxes
                objects_in_frame = len(boxes)
                detected_objects += objects_in_frame

                # Draw YOLO detections on image
                image = results[0].plot()

            # ------------------------------------------------------------
            # Overlay Statistics
            # ------------------------------------------------------------
            now_t = time.perf_counter()
            elapsed_tot = max(now_t - start_time, 0.001)
            display_fps = decoded_frames / elapsed_tot
            detector_fps = inference_count / elapsed_tot
            avg_inf_ms = (inference_time / inference_count * 1000) if inference_count > 0 else 0.0

            cv2.putText(image, f"Display FPS: {display_fps:.1f}", (10, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.putText(image, f"YOLO FPS: {detector_fps:.1f}", (10, 45),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.putText(image, f"Inference: {avg_inf_ms:.1f} ms", (10, 68),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            cv2.putText(image, f"Objects: {objects_in_frame}", (10, 91),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # ------------------------------------------------------------
            # Display Window
            # ------------------------------------------------------------
            cv2.imshow("IKRU - ESP32-CAM + YOLO Detection", image)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break

    except KeyboardInterrupt:
        print("\n[VISION] Interrupted by user.")
    finally:
        sock.close()
        cv2.destroyAllWindows()

        tot_elapsed = max(time.perf_counter() - start_time, 0.001)
        print()
        print("==========================================================")
        print("                   FINAL YOLO RESULTS")
        print("==========================================================")
        print(f"Packets received : {packets_received}")
        print(f"Data received    : {bytes_received / 1024 / 1024:.2f} MB")
        print(f"Frames completed : {frames_completed}")
        print(f"Frames discarded : {frames_discarded}")
        print(f"Decoded frames   : {decoded_frames}")
        print(f"Total Detections : {detected_objects}")
        print(f"Display FPS      : {decoded_frames / tot_elapsed:.2f}")
        print(f"Detector FPS     : {inference_count / tot_elapsed:.2f}")
        print(f"Avg inference    : {(inference_time / inference_count * 1000) if inference_count > 0 else 0:.2f} ms")
        print("==========================================================")


if __name__ == "__main__":
    main()
