import socket
import struct
import time

import cv2
import numpy as np


# ============================================================
# IKRU ESP32-CAM + MobileNet-SSD TEST
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
# MODEL
# ============================================================

MODEL_PROTO = (
    "tests/vision/models/"
    "MobileNetSSD_deploy.prototxt"
)

MODEL_WEIGHTS = (
    "tests/vision/models/"
    "MobileNetSSD_deploy.caffemodel"
)


print("[MODEL] Loading MobileNet-SSD...")

net = cv2.dnn.readNetFromCaffe(
    MODEL_PROTO,
    MODEL_WEIGHTS
)

# ------------------------------------------------------------
# Use CPU.
#
# If later you want to benchmark CUDA, we can change this.
# ------------------------------------------------------------

net.setPreferableBackend(
    cv2.dnn.DNN_BACKEND_OPENCV
)

net.setPreferableTarget(
    cv2.dnn.DNN_TARGET_CPU
)

print("[MODEL] MobileNet-SSD loaded")


# ============================================================
# COCO / VOC CLASSES
# ============================================================

CLASSES = [
    "background",
    "aeroplane",
    "bicycle",
    "bird",
    "boat",
    "bottle",
    "bus",
    "car",
    "cat",
    "chair",
    "cow",
    "diningtable",
    "dog",
    "horse",
    "motorbike",
    "person",
    "pottedplant",
    "sheep",
    "sofa",
    "train",
    "tvmonitor",
]


# ============================================================
# CONFIG
# ============================================================

CONFIDENCE_THRESHOLD = 0.40

INPUT_WIDTH = 300
INPUT_HEIGHT = 300


# ============================================================
# UDP SOCKET
# ============================================================

sock = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)

sock.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

sock.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_RCVBUF,
    4 * 1024 * 1024
)

sock.bind(
    ("0.0.0.0", VIDEO_PORT)
)

sock.settimeout(0.5)


print()
print("==========================================")
print("       IKRU ESP32-CAM + MOBILE SSD")
print("==========================================")

print(
    f"[UDP] Listening on port {VIDEO_PORT}"
)


# ============================================================
# DISCOVERY
# ============================================================

discovery = socket.socket(
    socket.AF_INET,
    socket.SOCK_DGRAM
)

discovery.sendto(
    b"IKRU_DISCOVER",
    (ESP32_CAM_IP, DISCOVERY_PORT)
)

discovery.close()

print("[DISCOVERY] Request sent")
print("[UDP] Waiting for camera...")
print()


# ============================================================
# FRAME STORAGE
# ============================================================

frames = {}

highest_frame_id = -1


# ============================================================
# STATISTICS
# ============================================================

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


# ============================================================
# CLEANUP
# ============================================================

def cleanup_frames():

    global frames_discarded

    now = time.perf_counter()

    expired = []

    for frame_id, frame in frames.items():

        if (
            now - frame["received_at"]
            > FRAME_TIMEOUT
        ):

            expired.append(frame_id)

    for frame_id in expired:

        del frames[frame_id]

        frames_discarded += 1


# ============================================================
# JPEG DECODER
# ============================================================

def decode_jpeg(data):

    if len(data) < 4:

        return None

    if data[:2] != b"\xff\xd8":

        return None

    if data[-2:] != b"\xff\xd9":

        return None

    array = np.frombuffer(
        data,
        dtype=np.uint8
    )

    return cv2.imdecode(
        array,
        cv2.IMREAD_COLOR
    )


# ============================================================
# MOBILE SSD DETECTION
# ============================================================

def detect_objects(image):

    global inference_count
    global inference_time
    global detected_objects

    height, width = image.shape[:2]

    blob = cv2.dnn.blobFromImage(
        cv2.resize(
            image,
            (INPUT_WIDTH, INPUT_HEIGHT)
        ),
        scalefactor=0.007843,
        size=(
            INPUT_WIDTH,
            INPUT_HEIGHT
        ),
        mean=127.5
    )

    net.setInput(blob)

    start = time.perf_counter()

    detections = net.forward()

    elapsed = (
        time.perf_counter()
        - start
    )

    inference_count += 1
    inference_time += elapsed

    objects_this_frame = 0

    for i in range(
        detections.shape[2]
    ):

        confidence = float(
            detections[0, 0, i, 2]
        )

        if confidence < CONFIDENCE_THRESHOLD:

            continue

        class_id = int(
            detections[0, 0, i, 1]
        )

        if (
            class_id < 0
            or class_id >= len(CLASSES)
        ):

            continue

        label = CLASSES[class_id]

        box = detections[
            0,
            0,
            i,
            3:7
        ] * np.array(
            [width, height, width, height]
        )

        x1, y1, x2, y2 = box.astype(
            int
        )

        # Clamp coordinates.

        x1 = max(0, min(x1, width - 1))
        y1 = max(0, min(y1, height - 1))
        x2 = max(0, min(x2, width - 1))
        y2 = max(0, min(y2, height - 1))

        objects_this_frame += 1
        detected_objects += 1

        # ----------------------------------------------------
        # Bounding box
        # ----------------------------------------------------

        cv2.rectangle(
            image,
            (x1, y1),
            (x2, y2),
            (0, 255, 0),
            2
        )

        # ----------------------------------------------------
        # Label
        # ----------------------------------------------------

        text = (
            f"{label} "
            f"{confidence * 100:.1f}%"
        )

        text_y = max(
            y1 - 8,
            20
        )

        cv2.putText(
            image,
            text,
            (x1, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2
        )

    return objects_this_frame


# ============================================================
# MAIN LOOP
# ============================================================

try:

    while True:

        cleanup_frames()

        try:

            packet, address = sock.recvfrom(
                65535
            )

        except socket.timeout:

            continue

        # ----------------------------------------------------
        # Discovery response
        # ----------------------------------------------------

        if packet == b"IKRU_CAMERA":

            print(
                "[DISCOVERY] ESP32-CAM connected"
            )

            continue

        packets_received += 1
        bytes_received += len(packet)

        # ----------------------------------------------------
        # Validate packet size
        # ----------------------------------------------------

        if len(packet) < HEADER_SIZE:

            continue

        # ----------------------------------------------------
        # Read header
        # ----------------------------------------------------

        (
            magic,
            version,
            packet_type,
            frame_id,
            chunk_id,
            total_chunks,
            frame_length,
            chunk_length,
            timestamp
        ) = struct.unpack(
            HEADER_FORMAT,
            packet[:HEADER_SIZE]
        )

        # ----------------------------------------------------
        # Validate header
        # ----------------------------------------------------

        if magic != MAGIC:
            continue

        if version != VERSION:
            continue

        if packet_type != PACKET_VIDEO:
            continue

        payload = packet[
            HEADER_SIZE:
        ]

        if len(payload) != chunk_length:

            continue

        # ----------------------------------------------------
        # Ignore stale frames
        # ----------------------------------------------------

        if frame_id < highest_frame_id:

            continue

        if frame_id > highest_frame_id:

            highest_frame_id = frame_id

            old_frames = [
                fid
                for fid in frames
                if fid < frame_id
            ]

            for fid in old_frames:

                del frames[fid]

                frames_discarded += 1

        # ----------------------------------------------------
        # Create frame
        # ----------------------------------------------------

        if frame_id not in frames:

            frames[frame_id] = {

                "total_chunks":
                    total_chunks,

                "frame_length":
                    frame_length,

                "chunks": {},

                "received_at":
                    time.perf_counter()
            }

            frames_started += 1

        frame = frames[frame_id]

        # ----------------------------------------------------
        # Store chunk
        # ----------------------------------------------------

        if chunk_id < total_chunks:

            frame["chunks"][
                chunk_id
            ] = payload

        # ----------------------------------------------------
        # Check completion
        # ----------------------------------------------------

        if (
            len(frame["chunks"])
            != total_chunks
        ):

            continue

        # ----------------------------------------------------
        # Reconstruct JPEG
        # ----------------------------------------------------

        chunks = []

        valid = True

        for i in range(total_chunks):

            chunk = frame["chunks"].get(i)

            if chunk is None:

                valid = False

                break

            chunks.append(chunk)

        del frames[frame_id]

        if not valid:

            frames_discarded += 1

            continue

        jpeg = b"".join(chunks)

        if len(jpeg) != frame_length:

            frames_discarded += 1

            continue

        frames_completed += 1

        # ----------------------------------------------------
        # Decode
        # ----------------------------------------------------

        image = decode_jpeg(jpeg)

        if image is None:

            continue

        decoded_frames += 1

        # ====================================================
        # OBJECT DETECTION
        # ====================================================

        objects = detect_objects(
            image
        )

        # ====================================================
        # PERFORMANCE
        # ====================================================

        elapsed = (
            time.perf_counter()
            - start_time
        )

        display_fps = (
            decoded_frames / elapsed
            if elapsed > 0
            else 0
        )

        detector_fps = (
            inference_count
            / max(
                time.perf_counter()
                - start_time,
                0.001
            )
        )

        avg_inference_ms = (
            inference_time
            / inference_count
            * 1000
            if inference_count > 0
            else 0
        )

        # ====================================================
        # OVERLAY
        # ====================================================

        cv2.putText(
            image,
            f"Display FPS: {display_fps:.1f}",
            (10, 22),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2
        )

        cv2.putText(
            image,
            f"Detector FPS: {detector_fps:.1f}",
            (10, 45),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2
        )

        cv2.putText(
            image,
            f"Inference: {avg_inference_ms:.1f} ms",
            (10, 68),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2
        )

        cv2.putText(
            image,
            f"Objects: {objects}",
            (10, 91),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2
        )

        # ====================================================
        # DISPLAY
        # ====================================================

        cv2.imshow(
            "IKRU - ESP32-CAM + MobileNet-SSD",
            image
        )

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q") or key == 27:

            break


except KeyboardInterrupt:

    print("\n[VISION] Stopped.")


finally:

    sock.close()

    cv2.destroyAllWindows()

    elapsed = (
        time.perf_counter()
        - start_time
    )

    display_fps = (
        decoded_frames / elapsed
        if elapsed > 0
        else 0
    )

    detector_fps = (
        inference_count / elapsed
        if elapsed > 0
        else 0
    )

    avg_inference = (
        inference_time
        / inference_count
        * 1000
        if inference_count > 0
        else 0
    )

    print()
    print("==========================================")
    print("             FINAL RESULTS")
    print("==========================================")
    print(
        f"Packets received : {packets_received}"
    )
    print(
        f"Data received    : "
        f"{bytes_received / 1024 / 1024:.2f} MB"
    )
    print(
        f"Frames completed : {frames_completed}"
    )
    print(
        f"Frames discarded : {frames_discarded}"
    )
    print(
        f"Decoded frames   : {decoded_frames}"
    )
    print(
        f"Objects detected : {detected_objects}"
    )
    print(
        f"Display FPS      : {display_fps:.2f}"
    )
    print(
        f"Detector FPS     : {detector_fps:.2f}"
    )
    print(
        f"Avg inference    : {avg_inference:.2f} ms"
    )
    print("==========================================")