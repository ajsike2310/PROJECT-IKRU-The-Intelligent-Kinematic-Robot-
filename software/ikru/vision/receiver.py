import os
import time
import socket
import struct
import threading
import cv2
import numpy as np

from .frame_buffer import FrameBuffer

IKRU_MAGIC = 0x494B  # "IK" in Little-Endian
HEADER_FORMAT = "<HBBIHHIHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 22 bytes


class VisionReceiver:
    """
    High-performance, loss-tolerant UDP video stream receiver for IKRU ESP32-CAM (AP & Station Modes).
    Handles discovery handshake (port 2223) and 22-byte packet reassembly (port 2222).
    """

    def __init__(
        self,
        cam_ip="192.168.4.1",
        video_port=2222,
        discovery_port=2223,
        show_window=True,
        frame_timeout_s=0.15
    ):
        self.cam_ip = self._clean_ip(cam_ip) if cam_ip else "192.168.4.1"
        self.video_port = video_port
        self.discovery_port = discovery_port
        self.show_window = show_window
        self.frame_timeout_s = frame_timeout_s

        self.buffer = FrameBuffer()
        self.running = False
        self.connected = False

        self._thread = None
        self._socket = None

        # Statistics
        self.fps = 0.0
        self.avg_frame_size_kb = 0.0
        self.packets_received = 0
        self.frames_completed = 0
        self.frames_discarded = 0
        self._fps_counter = 0
        self._fps_start = time.perf_counter()

    @staticmethod
    def _clean_ip(ip):
        if not ip:
            return None
        ip = str(ip).strip()
        if ip.startswith("http://"):
            ip = ip[7:]
        if ip.startswith("https://"):
            ip = ip[8:]
        return ip.rstrip("/").split(":")[0]

    def start(self):
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="VisionReceiverThread"
        )
        self._thread.start()

    def stop(self):
        self.running = False
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1.0)
        cv2.destroyAllWindows()

    def _send_discovery(self):
        """Sends discovery packet to notify ESP32-CAM of PC's IP."""
        try:
            disc_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            disc_sock.sendto(b"IKRU_DISCOVER", (self.cam_ip, self.discovery_port))
            disc_sock.close()
        except Exception:
            pass

    def _worker(self):
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            self._socket.bind(("0.0.0.0", self.video_port))
            self._socket.settimeout(0.5)
        except Exception as e:
            print(f"[Vision] Bind error on port {self.video_port}: {e}")
            self.running = False
            return

        # Send initial discovery
        self._send_discovery()

        active_frame_id = None
        active_total_chunks = 0
        active_frame_length = 0
        active_chunks = {}
        active_start_time = 0.0
        highest_frame_id = 0
        last_disc_time = time.perf_counter()

        while self.running:
            now = time.perf_counter()

            # Keep-alive discovery pulse every 2 seconds if not connected or to maintain state
            if now - last_disc_time > 2.0:
                self._send_discovery()
                last_disc_time = now

            # Discard incomplete frames on timeout
            if active_frame_id is not None and (now - active_start_time > self.frame_timeout_s):
                self.frames_discarded += 1
                active_frame_id = None
                active_chunks.clear()

            try:
                data, addr = self._socket.recvfrom(2048)
                if not data or len(data) < HEADER_SIZE:
                    # Could be discovery reply ("IKRU_CAMERA")
                    if data == b"IKRU_CAMERA":
                        self.connected = True
                    continue

                (
                    magic,
                    version,
                    pkt_type,
                    frame_id,
                    chunk_id,
                    total_chunks,
                    frame_length,
                    chunk_length,
                    ts_ms
                ) = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])

                if magic != IKRU_MAGIC or version != 1:
                    continue

                payload = data[HEADER_SIZE:HEADER_SIZE + chunk_length]
                if len(payload) != chunk_length:
                    continue

                self.packets_received += 1

                # Drop stale frames
                if frame_id < highest_frame_id and (highest_frame_id - frame_id < 100000):
                    continue

                if frame_id != active_frame_id:
                    if active_frame_id is not None:
                        self.frames_discarded += 1
                    active_frame_id = frame_id
                    highest_frame_id = max(highest_frame_id, frame_id)
                    active_total_chunks = total_chunks
                    active_frame_length = frame_length
                    active_start_time = now
                    active_chunks = {}

                active_chunks[chunk_id] = payload

                # Reassemble when all chunks arrive
                if len(active_chunks) == active_total_chunks:
                    self.frames_completed += 1
                    frame_bytes = bytearray()
                    for idx in range(active_total_chunks):
                        frame_bytes.extend(active_chunks[idx])

                    if (
                        len(frame_bytes) == active_frame_length
                        and frame_bytes.startswith(b"\xff\xd8")
                        and (b"\xff\xd9" in frame_bytes[-32:])
                    ):
                        decoded = cv2.imdecode(
                            np.frombuffer(frame_bytes, dtype=np.uint8),
                            cv2.IMREAD_COLOR
                        )
                        if decoded is not None:
                            # --- Draw 5x5 Grid onto the raw frame so VLM can see it ---
                            dh, dw = decoded.shape[:2]
                            dgrid_color = (255, 255, 255)  # White lines
                            for i in range(1, 5):
                                cv2.line(decoded, (i * dw // 5, 0), (i * dw // 5, dh), dgrid_color, 1)
                                cv2.line(decoded, (0, i * dh // 5), (dw, i * dh // 5), dgrid_color, 1)
                            # ------------------------------------------------------------
                            
                            self.buffer.set_frame(decoded)
                            self.connected = True
                            self._update_fps(len(frame_bytes))

                    active_frame_id = None
                    active_chunks.clear()

            except socket.timeout:
                self.connected = False
                continue
            except Exception:
                time.sleep(0.01)

        try:
            self._socket.close()
        except Exception:
            pass

    def _update_fps(self, frame_size):
        self._fps_counter += 1
        now = time.perf_counter()
        elapsed = now - self._fps_start
        if elapsed >= 1.0:
            self.fps = self._fps_counter / elapsed
            self._fps_counter = 0
            self._fps_start = now
            self.avg_frame_size_kb = frame_size / 1024.0

    def update_display(self):
        """Pumps the OpenCV window display loop."""
        if not self.show_window:
            return

        frame = self.buffer.get_frame()
        if frame is not None:
            display = frame.copy()
            cv2.putText(
                display,
                f"AP UDP FPS: {self.fps:.1f}",
                (5, 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 0),
                1
            )
        else:
            display = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.putText(
                display,
                "Connecting to IKRU-CAM...",
                (20, 110),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (200, 200, 200),
                2
            )
            cv2.putText(
                display,
                f"Target: {self.cam_ip}:{self.video_port}",
                (20, 145),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (100, 200, 100),
                1
            )

        cv2.imshow("IKRU EYES (UDP)", display)
        key = cv2.waitKey(1)
        if key == 27:
            self.stop()
