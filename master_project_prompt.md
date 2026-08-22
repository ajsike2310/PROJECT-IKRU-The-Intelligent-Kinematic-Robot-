# Master Context Prompt for PROJECT IKRU (Intelligent Kinematic Robot Unit)

Copy and paste the section below into a new AI chat along with your brainstorming notes to give the AI complete knowledge of your codebase and architecture.

***

```markdown
You are an expert systems engineer and software developer. I am building a physical two-wheeled robotic desk companion called **IKRU (Intelligent Kinematic Robot Unit)**. 

Below is the complete blueprint, codebase, and architectural details of the project. Please ingest this information so you have a full understanding of how the files interact, the hardware pin layout, the C++ firmware, the Python controller client, the WebSocket protocol, and the local LLM reasoning flow.

Once you have processed this context, wait for my brainstorming ideas to help me expand, debug, or refactor this codebase.

---

## 1. Project Overview & Architecture
IKRU is a desk companion robot that reads natural language commands, processes them locally using an offline Large Language Model (via Ollama), maps commands to movement tools or animated eye expressions, and sends them via WebSocket to an ESP32 microcontroller. 

### Dual Microcontroller Setup
To balance low-latency visual capture and real-time motor control, IKRU utilizes two independent ESP32 microcontrollers coordinated by a central PC "brain":
1. **ESP32 #1 — BODY CONTROLLER:** Runs a WebSocket server to control physical locomotion (two DC motors driven by an L293D motor driver) and displays animated eyes and scrolling text on an SSD1306 128x64 OLED display.
2. **ESP32 #2 — EYES (ESP32-CAM):** Runs an HTTP server to capture live JPEG frames from an OV2640 camera sensor and streams them as an MJPEG feed over the local network to the PC.

### System Architecture Flow
1. **User Input:** The user types a natural language prompt in the PC terminal.
2. **Video Capture & Vision (PC):** The PC runs `vision.py` in a background thread to decode the ESP32-CAM MJPEG stream. It performs face detection (OpenCV Haar Cascade) and object detection (MobileNet-SSD via OpenCV DNN module) in real time.
3. **Local LLM (Ollama):** The Python client (`chat.py`) dynamically injects what IKRU currently sees (faces and objects) into a temporary system context message. It sends the conversation history + visual context to Ollama running `qwen2.5:3b` in JSON mode.
4. **Structured Response:** The LLM returns a structured JSON object containing:
   - `tools`: A list of movement actions (e.g. `forward`, `backward`, `left`, `right`, `stop`, `dance`, `sing`) and their durations.
   - `response`: Text to be displayed on the OLED screen with inline `[emotion]` tags (e.g., `"[happy]Hello! [worried]Is something wrong?"`).
5. **Python Parser (chat.py):** Parses the JSON, splits the text into (emotion, text) segments, updates the eye expressions on the body OLED, and triggers movement commands.
6. **Body Execution (ESP32-Body):** Receives text commands via WebSocket (`ws://<BODY_IP>:81`), adjusts GPIO pins for motor control, and animates/scrolls the OLED display.

```
                                 HUMAN
                                   │
                              Text / Voice
                                   │
                                   ▼
                ┌──────────────────────────────────┐
                │          YOUR COMPUTER           │
                │             RTX 4060             │
                │                                  │
                │    Ollama (qwen2.5:3b)           │
                │    chat.py (Controller Loop)     │
                │    vision.py (Vision System)     │
                └───────┬──────────────────┬───────┘
                        │                  ▲
               Wi-Fi    │                  │   Wi-Fi
            (WebSocket) │                  │ (HTTP/MJPEG)
               Port 81  │                  │   Port 80
                        ▼                  │
         ┌─────────────────────────┐       │
         │   ESP32 #1 — BODY       │       │
         │                         │       │
         │   WebSocket Server      │       │
         │   parseCommand()        │       │
         │   L293D Motor Driver    │       │
         │   SSD1306 OLED (Eyes)   │       │
         └─────┬─────────────┬─────┘       │
               │             │             │
               ▼             ▼             │
          ┌─────────┐   ┌─────────┐        │
          │ Motor L │   │ Motor R │        │
          └─────────┘   └─────────┘        │
                                           │
         ┌─────────────────────────────────┴┐
         │   ESP32 #2 — EYES (ESP32-CAM)    │
         │                                  │
         │   OV2640 Sensor                  │
         │   HTTP Stream Server             │
         └──────────────────────────────────┘
```

---

## 2. Directory Structure
```text
PROJECT-IKRU/
├── README.md                          # Technical overview and installation instructions
├── master_project_prompt.md           # You are here (complete master context)
├── src/                               # Main Python application
│   ├── __init__.py                    # Package initializer
│   ├── robot.py                       # Robot WebSocket client class
│   ├── chat.py                        # AI chat loop & LLM integration (Ollama + Vision)
│   ├── vision.py                      # PC-side vision pipeline (Haar Face + MobileNet SSD)
│   ├── test_robot.py                  # Direct websocket testing script
│   ├── test_socket.py                 # TCP port connectivity test
│   │
│   ├── esp32_controller/              # Body Arduino firmware
│   │   ├── esp32_controller.ino       # Body WebSocket server + motor/OLED control
│   │   ├── Animations.h               # Keyframe animations for eye movements
│   │   ├── AsyncTimer.h/AsyncTimer.cpp # Helper for async timing / non-blocking blinks
│   │   ├── Common.h                   # Globals and OLED references
│   │   ├── Eye.h/Eye.cpp              # Eye dimensions, pupil/cornea scaling
│   │   ├── EyeDrawer.h                # Low-level eye rendering code
│   │   ├── EyePresets.h               # Coordinates and values for expressions
│   │   ├── Face.h/Face.cpp            # Facial animation state coordinator
│   │   ├── FaceEmotions.hpp           # Enum defining the 18 active expressions
│   │   ├── FaceExpression.h/FaceExpression.cpp # Emotion transition logic
│   │   └── LookAssistant.h/LookAssistant.cpp # Helper for random gaze movements
│   │
│   └── esp32_cam/                     # Camera Arduino firmware
│       └── esp32_cam.ino              # Low-latency MJPEG video server
```

---

## 3. Hardware Pin Mapping & Truth Table
### Body Controller Pin Wiring
* **EN1** (GPIO 13) → Enable Left Motor (M1)
* **EN2** (GPIO 33) → Enable Right Motor (M2) *(Note: GPIO 34 is input-only, do not use it for EN)*
* **C1A** (GPIO 26) → Left Motor Direction Pin A
* **C1B** (GPIO 27) → Left Motor Direction Pin B
* **C2A** (GPIO 14) → Right Motor Direction Pin A
* **C2B** (GPIO 12) → Right Motor Direction Pin B
* **SDA** (GPIO 21) → I2C Data for SSD1306 OLED
* **SCL** (GPIO 22) → I2C Clock for SSD1306 OLED

### Motor Driver Logic (L293D Module)
* `EN = HIGH`, `CxA = HIGH`, `CxB = LOW`  → Motor moves **Forward**
* `EN = HIGH`, `CxA = LOW`, `CxB = HIGH`  → Motor moves **Backward**
* `EN = LOW`                              → Motor **Stops** (coasts)

---

## 4. Communication Protocol (PC ↔ ESP32-Body)
Communication occurs over a raw WebSocket on port 81. All commands sent to the ESP32 are plain text. The ESP32 is case-insensitive (converts incoming text to uppercase) and trims whitespace. The ESP32 replies with `"OK"` after executing each command.

| Command | Action |
|---|---|
| `FORWARD` | Both motors forward |
| `BACKWARD` | Both motors backward |
| `LEFT` | Left motor backward, Right motor forward (pivot spin left) |
| `RIGHT` | Left motor forward, Right motor backward (pivot spin right) |
| `STOP` | Disable both motors (coast) |
| `DISPLAY_OPEN` | Opens the speech box on the OLED, shrinks eyes, and positions them in the bottom-right corner. |
| `DISPLAY_CLOSE` | Closes the speech box and expands eyes back to full screen. |
| `DISPLAY:<text>` | Draws and scrolls text on the left side of the OLED (width <= 75px). |
| `NORMAL`, `HAPPY`, `GLEE`, `SAD`, `WORRIED`, `FOCUSED`, `ANNOYED`, `SURPRISED`, `SKEPTIC`, `FRUSTRATED`, `UNIMPRESSED`, `SLEEPY`, `SUSPICIOUS`, `SQUINT`, `ANGRY`, `FURIOUS`, `SCARED`, `AWE` | Changes the eye expression on the OLED display. |

---

## 5. Python Codebase

### A. Robot API Client (`src/robot.py`)
Provides methods to connect, send commands, trigger expressions, perform complex macros (`dance`, `sing`), and write to the display:

```python
import websocket
import time

class Robot:
    def __init__(self, ip):
        # Connects to ESP32 WebSocket server on Port 81
        self.ws = websocket.create_connection(f"ws://{ip}:81")

    def send(self, cmd):
        self.ws.send(cmd)
        print(self.ws.recv())  # Print "OK" acknowledgement

    # Movement Methods
    def forward(self, duration=0):
        self.send("FORWARD")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def backward(self, duration=0):
        self.send("BACKWARD")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def left(self, duration=0):
        self.send("LEFT")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def right(self, duration=0):
        self.send("RIGHT")
        if duration > 0:
            time.sleep(duration)
            self.stop()

    def stop(self, duration=0):
        self.send("STOP")
        if duration > 0:
            time.sleep(duration)

    # OLED Speech Box Controls
    def display(self, text):
        self.send("DISPLAY:" + text)

    def display_open(self):
        self.send("DISPLAY_OPEN")

    def display_close(self):
        self.send("DISPLAY_CLOSE")

    # Expressions
    def normal(self): self.send("NORMAL")
    def happy(self): self.send("HAPPY")
    def glee(self): self.send("GLEE")
    def sad(self): self.send("SAD")
    def worried(self): self.send("WORRIED")
    def focused(self): self.send("FOCUSED")
    def annoyed(self): self.send("ANNOYED")
    def surprised(self): self.send("SURPRISED")
    def skeptic(self): self.send("SKEPTIC")
    def frustrated(self): self.send("FRUSTRATED")
    def unimpressed(self): self.send("UNIMPRESSED")
    def sleepy(self): self.send("SLEEPY")
    def suspicious(self): self.send("SUSPICIOUS")
    def squint(self): self.send("SQUINT")
    def angry(self): self.send("ANGRY")
    def furious(self): self.send("FURIOUS")
    def scared(self): self.send("SCARED")
    def awe(self): self.send("AWE")

    # Macro/Combo Sequences
    def dance(self):
        moves = [
            ("LEFT", "GLEE", 0.4),
            ("RIGHT", "HAPPY", 0.4),
            ("LEFT", "SURPRISED", 0.4),
            ("RIGHT", "GLEE", 0.4),
            ("FORWARD", "HAPPY", 0.4),
            ("BACKWARD", "GLEE", 0.4),
        ]
        for move, emotion, duration in moves:
            self.send(move)
            self.send(emotion)
            time.sleep(duration)
            self.send("STOP")
        self.send("NORMAL")

    def sing(self):
        notes = ["♪", "♫", "♪♪", "♬"]
        self.display_open()
        time.sleep(0.3)
        for i in range(4):
            self.send("HAPPY" if i % 2 == 0 else "GLEE")
            self.send("LEFT" if i % 2 == 0 else "RIGHT")
            self.display(f"   {notes[i]}   ")
            time.sleep(1.2)
            self.send("STOP")
        self.display_close()
        time.sleep(0.3)
        self.send("NORMAL")

    def close(self):
        self.ws.close()
```

### B. PC Vision Pipeline (`src/vision.py`)
This script decodes the HTTP MJPEG stream from the ESP32-CAM using a raw byte reader to bypass caching latencies. It applies Haar Cascade face detection and MobileNet-SSD object detection (via OpenCV DNN) in a thread-safe background process:

```python
import os
import sys
import time
import threading
import urllib.request
import numpy as np
import cv2

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
PROTOTXT_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.prototxt")
MODEL_PATH = os.path.join(MODEL_DIR, "MobileNetSSD_deploy.caffemodel")

PROTOTXT_URL = "https://raw.githubusercontent.com/chuanqi305/MobileNet-SSD/master/MobileNetSSD_deploy.prototxt"
MODEL_URL = "https://github.com/chuanqi305/MobileNet-SSD/raw/master/MobileNetSSD_deploy.caffemodel"

CLASSES = ["background", "aeroplane", "bicycle", "bird", "boat",
           "bottle", "bus", "car", "cat", "chair", "cow", "diningtable",
           "dog", "horse", "motorbike", "person", "pottedplant", "sheep",
           "sofa", "train", "tvmonitor"]

COLORS = np.random.uniform(100, 255, size=(len(CLASSES), 3))

def download_models_if_needed():
    try:
        if not os.path.exists(MODEL_DIR):
            os.makedirs(MODEL_DIR)
        if not os.path.exists(PROTOTXT_PATH):
            print("[Vision] Downloading MobileNet-SSD prototxt...")
            urllib.request.urlretrieve(PROTOTXT_URL, PROTOTXT_PATH)
        if not os.path.exists(MODEL_PATH):
            print("[Vision] Downloading MobileNet-SSD weights...")
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            urllib.request.install_opener(opener)
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        return True
    except Exception as e:
        print(f"[Vision] Could not download models: {e}. Face-only mode active.")
        return False

class VisionSystem:
    def __init__(self, cam_ip, show_window=True):
        self.ip = cam_ip
        self.stream_url = f"http://{cam_ip}/stream"
        self.show_window = show_window
        self.running = False
        self.thread = None
        self.latest_frame = None
        self.faces_count = 0
        self.detected_objects = []
        self.lock = threading.Lock()
        
        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
        )
        
        self.dnn_active = False
        if download_models_if_needed():
            try:
                self.net = cv2.dnn.readNetFromCaffe(PROTOTXT_PATH, MODEL_PATH)
                self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
                self.dnn_active = True
            except Exception as e:
                print(f"[Vision] Failed to load network: {e}")
        
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run_stream, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        cv2.destroyAllWindows()

    def get_latest_detections(self):
        with self.lock:
            return self.faces_count, list(self.detected_objects)

    def _run_stream(self):
        while self.running:
            try:
                req = urllib.request.Request(self.stream_url)
                stream = urllib.request.urlopen(req, timeout=5)
                bytes_buffer = bytes()
                while self.running:
                    chunk = stream.read(2048)
                    if not chunk:
                        break
                    bytes_buffer += chunk
                    a = bytes_buffer.find(b'\xff\xd8')
                    b = bytes_buffer.find(b'\xff\xd9')
                    if a != -1 and b != -1:
                        jpg_bytes = bytes_buffer[a:b+2]
                        bytes_buffer = bytes_buffer[b+2:]
                        frame = cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if frame is not None:
                            self._process_frame(frame)
            except Exception as e:
                print(f"[Vision] Stream error: {e}")
                if self.running:
                    time.sleep(2)

    def _process_frame(self, frame):
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.1, 4, minSize=(30, 30))
        
        objects = []
        if self.dnn_active:
            blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
            self.net.setInput(blob)
            detections = self.net.forward()
            for i in range(detections.shape[2]):
                confidence = detections[0, 0, i, 2]
                if confidence > 0.5:
                    class_idx = int(detections[0, 0, i, 1])
                    class_label = CLASSES[class_idx]
                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    (startX, startY, endX, endY) = box.astype("int")
                    objects.append(class_label)
                    color = COLORS[class_idx]
                    cv2.rectangle(frame, (startX, startY), (endX, endY), color, 2)
                    cv2.putText(frame, class_label, (startX, startY - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        for (x, y, fw, fh) in faces:
            cv2.rectangle(frame, (x, y), (x + fw, y + fh), (255, 0, 255), 2)
            cv2.putText(frame, "Face", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)

        with self.lock:
            self.faces_count = len(faces)
            self.detected_objects = list(set(objects))
            
        if self.show_window:
            cv2.imshow("IKRU Eyes - Live Stream", frame)
            cv2.waitKey(1)
        self.latest_frame = frame
```

### C. LLM Controller Loop (`src/chat.py`)
Connects to the body controller, optional camera vision thread, and queries the local Ollama LLM. It maps system messages containing active camera feeds (faces, objects) directly to the prompt context dynamically:

```python
import json
import math
import re
import time
import ollama
from robot import Robot
from vision import VisionSystem

# Initialize connections
robot = Robot(ip="192.168.1.37")

# Change this to your ESP32-CAM IP to activate live vision, or None to run without camera
CAM_IP = None  

vision = None
if CAM_IP is not None:
    try:
        vision = VisionSystem(cam_ip=CAM_IP, show_window=True)
        vision.start()
        print("[Vision] Camera system successfully loaded!")
    except Exception as e:
        print(f"[Vision] Could not start camera system: {e}")

movement_functions = {
    "forward":  robot.forward, "backward": robot.backward, "left": robot.left,
    "right":    robot.right,   "stop":     robot.stop,     "dance":   robot.dance,
    "sing":     robot.sing,
}

emotion_functions = {
    "normal": robot.normal, "happy": robot.happy, "glee": robot.glee,
    "sad": robot.sad, "worried": robot.worried, "focused": robot.focused,
    "annoyed": robot.annoyed, "surprised": robot.surprised, "skeptic": robot.skeptic,
    "frustrated": robot.frustrated, "unimpressed": robot.unimpressed, "sleepy": robot.sleepy,
    "suspicious": robot.suspicious, "squint": robot.squint, "angry": robot.angry,
    "furious": robot.furious, "scared": robot.scared, "awe": robot.awe
}

def parse_segments(text):
    matches = re.findall(r'\[([a-z]+)\]([^\[]*)', text)
    return [(emotion, chunk.strip()) for emotion, chunk in matches if chunk.strip()]

SYSTEM_PROMPT = """You are Ikru, a desk companion robot.
Return a valid JSON object:
{"tools": [{"action": "movement_name", "duration": seconds}], "response": "[emotion]text [emotion]more text"}

Available actions: forward, backward, left, right, stop, dance, sing
Available lowercase emotions: normal, happy, glee, sad, worried, focused, annoyed, surprised, skeptic, frustrated, unimpressed, sleepy, suspicious, squint, angry, furious, scared, awe

Rules:
1. Always start your response string with an [emotion] tag.
2. Each segment must contain real phrases/sentences (at least 5 words). Do not repeat the emotion name.
3. Use a maximum of 3 emotion changes per response.
4. Keep segments short (1-2 sentences) so they fit on the OLED screen.
5. See your environment using your camera (you will be told what objects/faces are present).
"""

messages = [{"role": "system", "content": SYSTEM_PROMPT}]

while True:
    user = input("\nYou: ")
    if user.lower() == "exit":
        break

    messages.append({"role": "user", "content": user})
    robot.focused()  # Set eyes to focused thinking expression

    # Dynamic camera integration
    if vision:
        faces, objs = vision.get_latest_detections()
        detected_items = []
        if faces > 0:
            detected_items.append(f"{faces} human face(s)")
        if objs:
            detected_items.append(", ".join(objs))
        
        if detected_items:
            vision_context = f"What you currently see in front of you: {', '.join(detected_items)}."
        else:
            vision_context = "What you currently see: Nothing in particular."
        
        # Inject context temporarily right before the user prompt
        temp_system_msg = {"role": "system", "content": vision_context}
        ollama_messages = messages[:-1] + [temp_system_msg] + [messages[-1]]
    else:
        ollama_messages = messages

    response = ollama.chat(model="qwen2.5:3b", messages=ollama_messages, format="json")
    assistant_raw = response["message"]["content"].strip()

    try:
        data = json.loads(assistant_raw)
        tools = data.get("tools", [])
        response_text = data.get("response", "").strip()
    except json.JSONDecodeError:
        tools, response_text = [], assistant_raw

    segments = parse_segments(response_text) or [("normal", response_text)]

    # 1. Open the OLED Speech Box once
    robot.display_open()
    time.sleep(0.35)

    full_response_text = ""

    # 2. Render each segment with its specific emotion
    for emotion, text in segments:
        emotion_functions.get(emotion, robot.normal)()
        
        if text:
            robot.display(text)
            print(f"Emotion: {emotion} | OLED: {text}")

            # Scrolling delay timings
            CHARS_PER_LINE = 8
            SCROLL_MS_PER_PX = 0.030
            START_PAUSE_S = 0.600
            END_PAUSE_S = 0.400

            num_lines = max(1, math.ceil(len(text) / CHARS_PER_LINE))
            scroll_pixels = 64 + num_lines * 18
            scroll_time = scroll_pixels * SCROLL_MS_PER_PX
            wait = START_PAUSE_S + scroll_time + END_PAUSE_S
            time.sleep(wait)
        full_response_text += text + " "

    # 3. Close the OLED Speech Box
    robot.display_close()
    time.sleep(0.35)

    # 4. Execute physical movements
    for t in tools:
        action = t.get("action", "").lower()
        duration = float(t.get("duration", 0))
        if action in movement_functions:
            print(f"Executing movement: {action} ({duration}s)")
            if action in ["forward", "backward", "left", "right", "stop"]:
                movement_functions[action](duration)
            else:
                movement_functions[action]()

    print(f"\nAssistant: {full_response_text.strip()}")
    messages.append({
        "role": "assistant",
        "content": json.dumps({"tools": tools, "response": response_text})
    })

# Cleanup on exit
if vision:
    vision.stop()
robot.close()
```

---

## 6. ESP32 Arduino Firmware Core

### A. Body Controller Firmware (`src/esp32_controller/esp32_controller.ino`)
Runs a multi-state machine for OLED rendering:
* `OLED_IDLE`: Full screen eye animations. Eyes blink randomly, and react to emotion commands.
* `OLED_SPEAKING`: Opens a speech box of width `84px` on the left side of the screen. Shrinks the eyes down to scale `0.45` and pushes them to the bottom right corner (`X=106`, `Y=48`) so the eyes remain visible while text scrolls.
* `OLED_WAITING`: Speech box remains open, waiting for the next segment to avoid screen flicker.

### B. ESP32-CAM Firmware (`src/esp32_cam/esp32_cam.ino`)
Connects to Wi-Fi, configures the OV2640 camera, and starts an HTTP Web Server on port 80.
* Serves a live MJPEG stream on `http://<CAM_IP>/stream` with low-latency optimizations (Wi-Fi power saving disabled, `CAMERA_GRAB_LATEST` enabled).
* Serves raw JPEG snapshots at `http://<CAM_IP>/capture` for high-quality framing or VLM inputs.

***

This concludes the master specification. Use this knowledge to help write modifications, new movement functions, or UI enhancements!
```
