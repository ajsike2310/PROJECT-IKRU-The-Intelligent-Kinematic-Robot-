import os
import sys
import time
import threading
import urllib.request
import numpy as np
import cv2

# ============================================================
# IKRU PC VISION SYSTEM
# ============================================================
# Connects to the ESP32-CAM stream, decodes MJPEG frames at low latency,
# and runs face + object detection.
# ============================================================

# Model paths and download URLs
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
PROTOTXT_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
MODEL_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")

PROTOTXT_URL = "https://raw.githubusercontent.com/PINTO0309/MobileNet-SSD-RealSense/master/caffemodel/MobileNetSSD/MobileNetSSD_deploy.prototxt"
# GitHub mirror for reliable download
MODEL_URL = "https://github.com/PINTO0309/MobileNet-SSD-RealSense/raw/master/caffemodel/MobileNetSSD/MobileNetSSD_deploy.caffemodel"

# MobileNet-SSD labels
CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat",
           "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
           "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
           "sofa", "train", "tvmonitor"]

# Color palette for classes (dynamic borders)
COLORS = np.random.uniform(100, 255, size=(len(CLASSES), 3))

def download_models_if_needed():
    """Attempts to download MobileNet-SSD files to allow object detection."""
    try:
        if not os.path.exists(MODEL_DIR):
            os.makedirs(MODEL_DIR)
        
        if not os.path.exists(PROTOTXT_PATH):
            print("[Vision] Downloading MobileNet-SSD prototxt model...")
            urllib.request.urlretrieve(PROTOTXT_URL, PROTOTXT_PATH)
            print("[Vision] Downloaded prototxt successfully.")
            
        if not os.path.exists(MODEL_PATH):
            print("[Vision] Downloading MobileNet-SSD weights (23MB). Please wait...")
            # Use a custom user agent to avoid HTTP 403 on github download links
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            urllib.request.install_opener(opener)
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
            print("[Vision] Downloaded weights successfully.")
        return True
    except Exception as e:
        print(f"[Vision] WARNING: Could not download object detection models: {e}")
        print("[Vision] Falling back to Face Detection only.")
        return False

class VisionSystem:
    def __init__(self, cam_ip, show_window=True):
        self.ip = cam_ip
        self.stream_url = f"http://{cam_ip}/stream"
        self.show_window = show_window
        
        self.running = False
        self.thread = None
        self.latest_frame = None
        
        # Thread-safe detection variables
        self.faces_count = 0
        self.detected_objects = []
        self.lock = threading.Lock()
        
        # Initialize Haar Cascade for Face Detection
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        # Initialize DNN for Object Detection
        self.dnn_active = False
        if download_models_if_needed():
            try:
                self.net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, MODEL_PATH)
                # If CUDA is compiled in OpenCV and available, use RTX 4060
                # OpenCV default built-ins usually fall back to CPU silently
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self.dnn_active = True
                print("[Vision] MobileNet-SSD Object Detector initialized successfully.")
            except Exception as e:
                print(f"[Vision] Could not load Caffe model: {e}")
        
    def start(self):
        """Starts the background thread to fetch and process camera frames."""
        self.running = True
        self.thread = threading.Thread(target=self._run_stream, daemon=True)
        self.thread.start()
        print(f"[Vision] Stream listener thread started at {self.stream_url}")

    def stop(self):
        """Stops the streaming thread and closes OpenCV windows."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        cv2.destroyAllWindows()
        print("[Vision] Vision system stopped.")

    def get_latest_detections(self):
        """Thread-safe getter for current active detections."""
        with self.lock:
            return self.faces_count, list(self.detected_objects)

    def _run_stream(self):
        """Continuous MJPEG HTTP decoding loop."""
        while self.running:
            try:
                print(f"[Vision] Connecting to camera stream at {self.stream_url}...")
                req = urllib.request.Request(self.stream_url)
                stream = urllib.request.urlopen(req, timeout=5)
                bytes_buffer = bytes()
                
                print("[Vision] Stream connected! Analyzing frames...")
                while self.running:
                    # Read chunks of the HTTP multipart stream
                    chunk = stream.read(2048)
                    if not chunk:
                        break
                    
                    bytes_buffer += chunk
                    
                    # Search for JPEG Start Of Image (SOI) and End Of Image (EOI) markers
                    a = bytes_buffer.find(b'\xff\xd8')
                    b = bytes_buffer.find(b'\xff\xd9')
                    
                    if a != -1 and b != -1:
                        # Extract raw JPEG bytes
                        jpg_bytes = bytes_buffer[a:b+2]
                        # Discard read frame from buffer
                        bytes_buffer = bytes_buffer[b+2:]
                        
                        # Decode JPEG bytes to numpy image
                        frame = cv2.imdecode(
                            np.frombuffer(jpg_bytes, dtype=np.uint8), 
                            cv2.IMREAD_COLOR
                        )
                        
                        if frame is not None:
                            self._process_frame(frame)
                            
            except Exception as e:
                print(f"[Vision] Stream error: {e}")
                if self.running:
                    print("[Vision] Reconnecting in 2 seconds...")
                    time.sleep(2)

    def _process_frame(self, frame):
        """Applies face detection, object detection, draws bounding boxes, and displays frame."""
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # 1. Face Detection (Haar Cascade)
        faces = self.face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
        
        # 2. Object Detection (MobileNet-SSD)
        objects = []
        if self.dnn_active:
            # Preprocess frame for Caffe model (resize to 300x300 and mean subtraction)
            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)), 
                0.007843, 
                (300, 300), 
                127.5
            )
            self.net.setInput(blob)
            detections = self.net.forward()
            
            # Loop over detections
            for i in range(detections.shape[2]):
                confidence = detections[0, 0, i, 2]
                if confidence > 0.5:  # Confidence threshold
                    class_idx = int(detections[0, 0, i, 1])
                    class_label = CLASSES[class_idx]
                    
                    # Compute box coordinates
                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    (startX, startY, endX, endY) = box.astype("int")
                    
                    # Limit coordinates to frame dimensions
                    startX, startY = max(0, startX), max(0, startY)
                    endX, endY = min(w, endX), min(h, endY)
                    
                    # Track object label
                    objects.append(class_label)
                    
                    # Draw bounding box and label
                    color = COLORS[class_idx]
                    cv2.rectangle(frame, (startX, startY), (endX, endY), color, 2)
                    label = f"{class_label}: {confidence*100:.1f}%"
                    cv2.putText(
                        frame, label, (startX, startY - 10 if startY > 20 else startY + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2
                    )

        # Draw Face bounding boxes (separate color to differentiate from DNN objects)
        for (x, y, fw, fh) in faces:
            cv2.rectangle(frame, (x, y), (x + fw, y + fh), (255, 0, 255), 2)
            cv2.putText(
                frame, "Face", (x, y - 10 if y > 20 else y + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2
            )

        # Thread-safe updates
        with self.lock:
            self.faces_count = len(faces)
            self.detected_objects = list(set(objects)) # Unique objects
            
        # Display the live window
        if self.show_window:
            cv2.imshow("IKRU Eyes - Live Stream", frame)
            # Must call waitKey to refresh OpenCV window frame
            cv2.waitKey(1)
            
        self.latest_frame = frame


# Standalone testing mode
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python vision.py <ESP32_CAM_IP>")
        sys.exit(1)
        
    cam_ip = sys.argv[1]
    vision = VisionSystem(cam_ip, show_window=True)
    vision.start()
    
    try:
        while True:
            faces, objs = vision.get_latest_detections()
            print(f"[Main] Current Detections — Faces: {faces} | Objects: {objs}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping vision system...")
        vision.stop()
        print("Stopped.")
