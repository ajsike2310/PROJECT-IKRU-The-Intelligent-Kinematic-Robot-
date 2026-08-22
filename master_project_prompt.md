# Master Context Prompt for PROJECT IKRU (Intelligent Kinematic Robot Unit)

Copy and paste the section below into a new AI chat along with your brainstorming notes to give the AI complete knowledge of your codebase and architecture.

***

```markdown
You are an expert systems engineer and software developer. I am building a physical two-wheeled robotic desk companion called **IKRU (Intelligent Kinematic Robot Unit)**. 

Below is the complete blueprint, codebase, and architectural details of the project. Please ingest this information so you have a full understanding of how the files interact, the hardware pin layout, the C++ firmware, the Python controller client, the WebSocket protocol, and the local LLM reasoning flow.

Once you have processed this context, wait for my brainstorming ideas to help me expand, debug, or refactor this codebase.

---

## 1. Project Overview & Architecture
IKRU is a desk companion robot that reads natural language commands, processes them locally using an offline Large Language Model (via Ollama), maps commands to movement tools or animated eye expressions, and sends them via WebSocket to an ESP32 microcontroller. The ESP32 drives two DC motors via an L293D motor driver and renders expressions/scrolling text on an SSD1306 128x64 OLED display.

### System Architecture Flow
1. **User Input:** The user types a natural language prompt in the PC terminal.
2. **Local LLM (Ollama):** The Python client sends the conversation history to Ollama running `qwen2.5:3b` with a custom system prompt.
3. **Structured Response:** The LLM returns a structured JSON object containing:
   - `tools`: A list of movement actions (e.g. `forward`, `backward`, `left`, `right`, `stop`, `dance`, `sing`) and their durations.
   - `response`: Text to be displayed on the OLED screen with inline `[emotion]` tags (e.g., `"[happy]Hello! [worried]Is something wrong?"`).
4. **Python Parser (chat.py):** Parses the JSON, splits the text into (emotion, text) segments, and invokes the WebSocket client.
5. **WebSocket Transmission:** The Python client connects to the ESP32 WebSocket Server (`ws://<ESP32_IP>:81`) and sends plain text instructions sequentially.
6. **Microcontroller execution (ESP32):**
   - **Display:** Animates the OLED screen. It draws eyes in IDLE mode, or opens a speech box and scrolls text in SPEAKING mode.
   - **Motors:** Controls the L293D motor driver GPIO pins to drive DC gear motors.
   - **Acknowledgement:** Replies with `"OK"` to acknowledge receipt of each instruction.

---

## 2. Directory Structure
```text
PROJECT-IKRU/
├── README.md                          # Technical overview and hardware wiring
├── src/                               # Main Python application
│   ├── __init__.py                    # Package initializer
│   ├── robot.py                       # Robot WebSocket client class
│   ├── chat.py                        # AI chat loop & LLM integration
│   ├── test_robot.py                  # Direct websocket testing script
│   ├── test_socket.py                 # TCP port connectivity test
│   │
│   └── esp32_controller/              # ESP32 Arduino firmware
│       ├── esp32_controller.ino       # Core WebSocket server & hardware control
│       ├── Animations.h               # Keyframe animations for eye movements
│       ├── AsyncTimer.h/AsyncTimer.cpp # Helper for async timing / non-blocking blinks
│       ├── Common.h                   # Globals and OLED references
│       ├── Eye.h/Eye.cpp              # Eye dimensions, pupil/cornea scaling
│       ├── EyeDrawer.h                # Low-level eye rendering code
│       ├── EyePresets.h               # Coordinates and values for expressions
│       ├── Face.h/Face.cpp            # Facial animation state coordinator
│       ├── FaceEmotions.hpp           # Enum defining the 18 active expressions
│       ├── FaceExpression.h/FaceExpression.cpp # Emotion transition logic
│       ├── LookAssistant.h/LookAssistant.cpp # Helper for random gaze movements
│       └── EyeBlink.h/EyeBlink.cpp / EyeVariation.h/EyeVariation.cpp / etc.
```

---

## 3. Hardware Pin Mapping & Truth Table
### Pin Wiring
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

## 4. Communication Protocol (PC ↔ ESP32)
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

### B. LLM Main Controller Loop (`src/chat.py`)
This file is the core intelligence loop. It uses `ollama` to run queries against `qwen2.5:3b` in JSON mode. The system prompt instructs the LLM to format its response with a `tools` array (for physical movement tasks) and a `response` string (for speaking). 

The LLM inserts inline `[emotion]` tags into the speech response. `chat.py` extracts these segments, updates the eye expressions on the fly, handles the scrolling duration pauses, and runs the movement tools:

```python
import json
import math
import re
import time
import ollama
from robot import Robot

# Initialize connection
robot = Robot(ip="192.168.1.37")

movement_functions = {
    "forward":  robot.forward,
    "backward": robot.backward,
    "left":     robot.left,
    "right":    robot.right,
    "stop":     robot.stop,
    "dance":    robot.dance,
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
    # Extracts "[happy]Hello [sad]World" into [("happy", "Hello"), ("sad", "World")]
    matches = re.findall(r'\[([a-z]+)\]([^\[]*)', text)
    return [(emotion, chunk.strip()) for emotion, chunk in matches if chunk.strip()]

SYSTEM_PROMPT = """You are Ikru, a desk companion robot.
Return a valid JSON object:
{"tools": [{"action": "movement_name", "duration": seconds}], "response": "[emotion]text [emotion]more text"}

Available movement actions: forward, backward, left, right, stop, dance, sing
Available lowercase emotions: normal, happy, glee, sad, worried, focused, annoyed, surprised, skeptic, frustrated, unimpressed, sleepy, suspicious, squint, angry, furious, scared, awe

Rules:
1. Always start your response string with an [emotion] tag.
2. Each segment must contain real phrases/sentences (at least 5 words). Do not repeat the emotion name.
3. Use a maximum of 3 emotion changes per response.
4. Keep segments short (1-2 sentences) so they fit on the OLED screen.
"""

messages = [{"role": "system", "content": SYSTEM_PROMPT}]

while True:
    user = input("\nYou: ")
    if user.lower() == "exit":
        break

    messages.append({"role": "user", "content": user})
    robot.focused()  # Look focused while LLM is generating

    # Call LLM in structured JSON mode
    response = ollama.chat(model="qwen2.5:3b", messages=messages, format="json")
    assistant_raw = response["message"]["content"].strip()

    try:
        data = json.loads(assistant_raw)
        tools = data.get("tools", [])
        response_text = data.get("response", "").strip()
    except json.JSONDecodeError:
        # Fallback
        tools, response_text = [], assistant_raw

    segments = parse_segments(response_text) or [("normal", response_text)]

    # 1. Open the OLED Speech Box once
    robot.display_open()
    time.sleep(0.35)

    full_response_text = ""

    # 2. Render each segment with its specific emotion
    for emotion, text in segments:
        # Change OLED eye expression
        emotion_functions.get(emotion, robot.normal)()
        
        if text:
            # Send text to OLED
            robot.display(text)
            print(f"Emotion: {emotion} | OLED: {text}")

            # Calculate exact scrolling delay matching ESP32 timings
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

    # 4. Execute physical movements if requested
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

robot.close()
```

---

## 6. ESP32 Arduino Firmware Core (`src/esp32_controller/esp32_controller.ino`)
Runs a multi-state machine for OLED rendering:
* `OLED_IDLE`: Full screen eye animations. Eyes blink randomly, and react to emotion commands.
* `OLED_SPEAKING`: Opens a speech box of width `84px` on the left side of the screen (`X` coordinate `0` to `84`). Shrinks the eyes down to scale `0.45` and pushes them to the bottom right corner (`X=106`, `Y=48`) so the eyes remain visible while text scrolls.
* `OLED_WAITING`: Speech box remains open, waiting for the next segment to avoid screen flicker.

### Key Logic in C++
1. **Text Formatting (`prepareMessage`)**:
   Splits long text blocks into words and packs them into lines that do not exceed the `75px` boundary of the speech box. If a single word is wider than `75px`, it splits it and appends a hyphen `-`.
2. **Text Scrolling (`updateSpeechScroll`)**:
   Once the speech box slides open (width reaches `84`), it pauses for `600ms`. It then scrolls the text up pixel-by-pixel every `30ms`. When the text scrolls off screen, it pauses for `400ms` before closing the box or transitioning to the next block.
3. **Smooth Eye Interpolation (`loop`)**:
   In the main loop, target eye positions and scales are smoothly interpolated (Lerped) using `dt` (delta time) to prevent jarring visual jumps:
   ```cpp
   float lerpFactor = 10.0 * dt;
   currentEyeScale += (targetEyeScale - currentEyeScale) * lerpFactor;
   currentEyeX += (targetEyeX - currentEyeX) * lerpFactor;
   currentEyeY += (targetEyeY - currentEyeY) * lerpFactor;
   ```
4. **WebSocket Commands Parser (`parseCommand`)**:
   Converts movements to direct `digitalWrite()` calls. It maps the motor pins as:
   - `FORWARD` / `BACKWARD` / `LEFT` / `RIGHT` / `STOP`
   - Maps the 18 text emotions to internal `face->Expression.GoTo_<Emotion>()` methods.
   - Parses display messages (e.g. `DISPLAY_OPEN` calls `oledOpen()`, `DISPLAY:<text>` calls `oledMessage()`, `DISPLAY_CLOSE` calls `oledClose()`).

***

This concludes the master specification. Use this knowledge to help write modifications, new movement functions, or UI enhancements!
```
