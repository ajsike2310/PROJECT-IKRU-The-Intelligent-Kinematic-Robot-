# 🤖 PROJECT IKRU — The Intelligent Kinematic Robot Unit

<div align="center">

![IKRU Banner](https://img.shields.io/badge/PROJECT-IKRU-blueviolet?style=for-the-badge&logo=robot&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-WROOM--32-red?style=for-the-badge&logo=espressif&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.x-blue?style=for-the-badge&logo=python&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-green?style=for-the-badge)
![WebSocket](https://img.shields.io/badge/WebSocket-Real--Time-orange?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

**IKRU** is an AI-powered two-wheeled robot that understands natural language commands. You simply talk to it — it thinks, and it moves.

</div>

---

## 📖 Table of Contents

- [Overview](#-overview)
- [System Architecture](#-system-architecture)
- [Hardware](#-hardware)
  - [Components](#components)
  - [Pin Wiring Diagram](#pin-wiring-diagram)
- [Software Stack](#-software-stack)
- [Project Structure](#-project-structure)
- [How It Works](#-how-it-works)
- [Setup & Installation](#-setup--installation)
  - [1. ESP32 Firmware](#1-esp32-firmware)
  - [2. Python Environment](#2-python-environment)
  - [3. Ollama & LLM Setup](#3-ollama--llm-setup)
  - [4. Running the Robot](#4-running-the-robot)
- [Commands & Examples](#-commands--examples)
- [Communication Protocol](#-communication-protocol)
- [Troubleshooting](#-troubleshooting)
- [Roadmap](#-roadmap)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🌐 Overview

**IKRU (Intelligent Kinematic Robot Unit)** bridges the gap between natural language and physical robotics. Using a locally-running Large Language Model (LLM) via [Ollama](https://ollama.ai/), IKRU interprets freeform human instructions and translates them into precise motor commands sent over WebSocket to an ESP32 microcontroller.

> **No cloud. No API keys. Fully offline AI at the edge.**

### Key Highlights

| Feature | Description |
|---|---|
| 🧠 **AI-Powered** | Uses a local LLM (phi3) to understand natural language |
| 📡 **Wi-Fi Control** | Commands sent via WebSocket over local network |
| ⚡ **Real-Time** | Low-latency bidirectional communication |
| 🔌 **Offline** | No internet required — LLM runs entirely on your machine |
| 🛠️ **Extensible** | Clean architecture makes adding new commands trivial |

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        YOUR COMPUTER                            │
│                                                                 │
│  ┌─────────────┐     ┌──────────────┐     ┌─────────────────┐  │
│  │  User Input │────▶│  Ollama LLM  │────▶│  chat.py        │  │
│  │  (Terminal) │     │  (phi3:3.8b) │     │  JSON Parser    │  │
│  └─────────────┘     └──────────────┘     └────────┬────────┘  │
│                                                     │           │
│                                              robot.py (Robot)   │
│                                                     │           │
└─────────────────────────────────────────────────────┼───────────┘
                                                      │
                                               Wi-Fi (WebSocket)
                                              ws://[IP]:81
                                                      │
┌─────────────────────────────────────────────────────┼───────────┐
│                        ESP32                        │           │
│                                              ┌──────▼───────┐   │
│                                              │  WebSocket   │   │
│                                              │  Server :81  │   │
│                                              └──────┬───────┘   │
│                                                     │           │
│                                              parseCommand()      │
│                                                     │           │
│                                    ┌────────────────▼────────┐  │
│                                    │   DRV8833 Motor Driver  │  │
│                                    │   EEP/IN1/IN2/IN3/IN4   │  │
│                                    └──────┬──────────┬───────┘  │
│                                           │          │           │
│                                    ┌──────▼──┐  ┌───▼──────┐   │
│                                    │ Motor L │  │ Motor R  │   │
│                                    │  (M1)   │  │  (M2)   │   │
│                                    └─────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 Hardware

### Components

| Component | Model | Quantity | Purpose |
|---|---|---|---|
| **Microcontroller** | ESP32-WROOM-32 DevKit | 1 | Body controller: Wi-Fi, WebSocket server, OLED, motors |
| **Camera Controller** | AI-Thinker ESP32-CAM | 1 | Vision eyes: Dedicated AP Wi-Fi, streams UDP JPEG frames |
| **Motor Driver** | DRV8833 Dual H-Bridge Module | 1 | High-efficiency MOSFET driver for dual DC motors |
| **DC Motors** | TT Gear Motors (3–6V) | 2 | Left and right wheel drive |
| **Display** | 0.96" SSD1306 OLED (I2C) | 1 | Face expressions and dynamic speech scrolling |
| **Chassis** | 2WD Robot Chassis | 1 | Physical robot frame |
| **Power Supply** | LiPo / 18650 Battery Pack | 1 | Powers ESP32 + motors |
| **Wheels** | Compatible wheels | 2 | Locomotion |

---

### Pin Wiring Diagram

```
ESP32 Pin     →    DRV8833 Module Pin   →    Function
──────────────────────────────────────────────────────────────────
D13  (GPIO13) →    EEP / nSLEEP (M1)   →    Enable Left  Motor (M1)
D33  (GPIO33) →    EEP / nSLEEP (M2)   →    Enable Right Motor (M2)
D26  (GPIO26) →    IN1                 →    Left  Motor Direction A
D27  (GPIO27) →    IN2                 →    Left  Motor Direction B
D14  (GPIO14) →    IN3                 →    Right Motor Direction A
D12  (GPIO12) →    IN4                 →    Right Motor Direction B
D21  (GPIO21) →    SDA                 →    SSD1306 OLED I2C Data
D22  (GPIO22) →    SCL                 →    SSD1306 OLED I2C Clock
```

> ⚠️ **Important:** GPIO34 is **input-only** on ESP32. Do **not** use it for motor enable/direction. Use GPIO33 instead.

#### DRV8833 Motor Control Truth Table

| EEP / nSLEEP | IN_A | IN_B | Motor State | Result |
|:---|:---|:---|:---|:---|
| HIGH | HIGH | LOW  | Forward Drive | Forward |
| HIGH | LOW  | HIGH | Reverse Drive | Backward |
| HIGH | LOW  | LOW  | Coast (Fast Decay) | Stop / Coast |
| HIGH | HIGH | HIGH | Brake (Slow Decay) | Active Brake |
| LOW  | X    | X    | Low-Power Sleep | Disabled |

#### Movement Logic

| Command  | Left Motor (M1) | Right Motor (M2) | Result              |
|----------|-----------------|------------------|---------------------|
| FORWARD  | Forward         | Forward          | Straight ahead      |
| BACKWARD | Backward        | Backward         | Straight back       |
| LEFT     | Backward        | Forward          | Pivot turn left     |
| RIGHT    | Forward         | Backward         | Pivot turn right    |
| STOP     | Coast           | Coast            | Coast to stop       |

---

## 💻 Software Stack

| Layer | Technology | Version |
|---|---|---|
| **Firmware** | Arduino C++ (ESP32 Arduino Core) | Latest |
| **WebSocket Server** | `WebSocketsServer` (Arduino library) | Latest |
| **OLED & Face Graphics** | `U8g2` + Custom Procedural Face Engine | Latest |
| **AI Controller** | Python | 3.8+ |
| **Conversational LLM** | Ollama + `qwen2.5:3b` | Latest |
| **Vision-Language Model** | Ollama + `qwen3-vl:4b` | Latest |
| **Python WebSocket Client** | `websocket-client` | Latest |
| **LLM Client** | `ollama` Python package | Latest |

---

## 📁 Project Structure

```
PROJECT-IKRU/
│
├── README.md                          # Master documentation & wiring guides
│
├── docs/                              # Hardware schematics & documentation assets
│   └── images/
│
├── software/                          # Python Application Package
│   └── ikru/
│       ├── __init__.py
│       ├── main.py                    # Single Main Entrypoint (Chat + Robot + Vision)
│       │
│       ├── chat/                      # Conversational LLM Subsystem
│       │   ├── __init__.py
│       │   ├── engine.py              # Ollama Qwen 2.5 3B interface
│       │   ├── prompts.py             # Persona rules & JSON formatting
│       │   └── parser.py              # [emotion] tag and tool JSON parser
│       │
│       ├── vision/                    # UDP Low-Latency Vision Pipeline
│       │   ├── __init__.py
│       │   ├── receiver.py            # Loss-tolerant AP-mode UDP stream receiver
│       │   ├── frame_buffer.py        # Thread-safe zero-queue latest buffer
│       │   └── vlm.py                 # Multimodal Qwen3-VL client
│       │
│       └── robot/                     # Robot Client Subsystem
│           ├── __init__.py
│           ├── controller.py          # WebSocket client for ESP32
│           └── protocol.py            # Protocol constants & scroll timing
│
├── firmware/                          # Microcontroller C++ Firmware
│   ├── controller/                    # ESP32 Body & OLED Firmware
│   │   ├── controller.ino             # Main robot firmware
│   │   ├── Face.h / Face.cpp          # Procedural facial state engine
│   │   ├── Eye.h / Eye.cpp            # Eye geometry and animation
│   │   └── ...                        # U8g2 graphics drivers & assets
│   │
│   └── eyes-demo/                     # Standalone Eye Animation Demo
│       ├── eyes-demo.ino
│       └── ...
│
└── tests/                             # Diagnostics & Hardware Verification
    ├── test_robot.py                  # Direct WebSocket tester
    ├── test_socket.py                 # TCP port 81 reachability tester
    └── vision/                        # Standalone Vision Diagnostics
        └── esp32_cam_ap/
            └── esp32_cam_ap.ino       # AP mode UDP camera test
```

### Module Descriptions

#### `software/ikru/robot/controller.py` — Robot Controller Client
Provides a clean Python API to communicate with the ESP32 over WebSocket (`ws://[IP]:81`) for motor movements and OLED animations.

```python
from ikru.robot import RobotController

robot = RobotController(ip="192.168.1.37")  # Connect to ESP32
robot.forward(5)                           # Move forward for 5 seconds
robot.happy()                              # Set face emotion to happy
robot.display("Hello!")                    # Scroll text on OLED speech box
robot.close()                              # Close WebSocket connection
```

#### `software/ikru/chat/engine.py` — Conversational Intelligence
Interfaces with local Ollama (`qwen2.5:3b`), maintaining multi-turn conversational context, interpreting emotion cues, and formatting movement tool calls into valid JSON.

#### `software/ikru/vision/receiver.py` — Low-Latency UDP Video Streamer
Connects to the ESP32-CAM access point (`IKRU-CAM` at `192.168.4.1`), receives 22-byte header UDP packets on port 2222, and reassembles frames with zero queue backlog for live display and on-demand VLM reasoning (`qwen3-vl:4b`).

#### `firmware/controller/controller.ino` — ESP32 Body Firmware
Runs on the ESP32-WROOM-32. Hosts a WebSocket server on **port 81**, manages 18 procedural facial expressions on the SSD1306 OLED, wraps and scrolls speech text, and controls dual DC motors via the DRV8833 driver.

---

## ⚙️ How It Works

1. **User types** a natural language command into the terminal (e.g. `"Move forward please"` or `"What shirt am I wearing?"`).
2. If visual keywords are detected and the camera is enabled, **`vlm.py`** grabs a frame snapshot from the UDP stream and queries **`qwen3-vl:4b`** for a live scene description.
3. **`chat.py`** augments the prompt with the visual observation and sends it to **Ollama** (`qwen2.5:3b`).
4. The **LLM** responds with structured JSON containing emotion tags and movement tool actions.
5. The **`RobotController`** coordinates the OLED speech box opening, scrolls text smoothly while transitioning facial expressions, and drives the **DRV8833 motor driver** pins (`IN1-IN4` / `nSLEEP`), making the robot move.
7. The ESP32 replies with `"OK"`, which is printed to the terminal.

---

## 🚀 Setup & Installation

### Prerequisites

- ESP32-WROOM-32 board + Arduino IDE (or PlatformIO)
- Python 3.8+
- [Ollama](https://ollama.ai/) installed on your machine
- Both your computer and ESP32 on the **same Wi-Fi network**

---

### 1. ESP32 Firmware

#### ESP32 #1: Body Controller
**Step 1:** Install the required Arduino library:
- Open Arduino IDE → **Sketch → Include Library → Manage Libraries**
- Search for **`WebSockets`** by Markus Sattler and install it.

**Step 2:** Update Wi-Fi credentials in `src/esp32_controller/esp32_controller.ino`:
```cpp
const char* ssid     = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
```

**Step 3:** Flash the firmware to your Body Controller ESP32:
- Select board: **ESP32 Dev Module**
- Select the correct COM port and click **Upload**.
- Note the IP address from the Serial Monitor (e.g., `192.168.1.37`).

#### ESP32 #2: ESP32-CAM (Eyes)
**Step 1:** Open `src/esp32_cam/esp32_cam.ino` in Arduino IDE.

**Step 2:** Update Wi-Fi credentials:
```cpp
const char *ssid = "YOUR_WIFI_SSID";
const char *password = "YOUR_WIFI_PASSWORD";
```

**Step 3:** Flash the firmware to your ESP32-CAM:
- Select board: **AI Thinker ESP32-CAM**
- Select the correct COM port and click **Upload**.
- Open the Serial Monitor and note the Camera IP address (e.g., `192.168.1.38`).
- Verify the stream by visiting `http://<CAMERA_IP>/` in your browser.

---

### 2. Python Environment

```bash
# Clone the repository
git clone https://github.com/ajsike2310/PROJECT-IKRU-The-Intelligent-Kinematic-Robot-.git
cd PROJECT-IKRU-The-Intelligent-Kinematic-Robot-

# Create a virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/macOS)
source .venv/bin/activate

# Install dependencies (including OpenCV for the vision pipeline)
pip install websocket-client ollama opencv-python
```

---

### 3. Ollama & LLM Setup

```bash
# Install Ollama from https://ollama.ai/
# Then pull the Qwen model used by IKRU:
ollama pull qwen2.5:3b

# Verify it is available:
ollama list
```

> 💡 The model runs entirely **locally** on your CPU/GPU. No internet connection is needed after the initial download.

---

### 4. Running the Robot

**Step 1:** Update the IP addresses in `src/chat.py` to match both of your ESP32 boards:
```python
# Set the Body Controller IP
robot = Robot(ip="192.168.1.37")

# Set the Camera IP (or set to None to run without vision)
CAM_IP = "192.168.1.38"
```

**Step 2:** Make sure Ollama is running:
```bash
ollama serve
```

**Step 3:** Launch IKRU:
```bash
cd src
python chat.py
```

You should see:
```
==================================================
🤖 Robot Assistant Started
Type 'exit' to quit
==================================================

You:
```

---

## 🗣️ Commands & Examples

IKRU understands **natural language** — you don't need to memorize exact keywords.

| You say... | IKRU does... |
|---|---|
| `Move forward` | 🔼 Drives forward |
| `Go backward` | 🔽 Drives backward |
| `Turn left` | ◀️ Pivots left |
| `Can you turn right?` | ▶️ Pivots right |
| `Stop` / `Halt` / `Freeze` | ⏹️ Stops motors |
| `What is Python?` | 💬 Answers like ChatGPT |
| `Hello` | 💬 Greets you |
| `exit` | 🚪 Closes the app |

### Example Session

```
You: Hey robot, move forward!

🔧 Executing: forward
Robot: OK

You: Now turn left

🔧 Executing: left
Robot: OK

You: Stop please

🔧 Executing: stop
Robot: OK

You: What is an LLM?
Assistant: An LLM (Large Language Model) is a type of AI model trained on vast amounts of text...

You: exit
```

---

## 📡 Communication Protocol

IKRU uses a simple text-based protocol over WebSocket:

| Direction | Message | Description |
|---|---|---|
| **PC → ESP32** | `FORWARD` | Move forward |
| **PC → ESP32** | `BACKWARD` | Move backward |
| **PC → ESP32** | `LEFT` | Pivot left |
| **PC → ESP32** | `RIGHT` | Pivot right |
| **PC → ESP32** | `STOP` | Stop motors |
| **ESP32 → PC** | `OK` | Acknowledgement |

- **Protocol:** WebSocket (`ws://`)
- **Port:** `81`
- **Message type:** Plain text (UTF-8)
- **Case insensitive** on the ESP32 side (converted to uppercase internally)

---

## 🔍 Troubleshooting

### ❌ Cannot connect to robot

- Verify the IP address in `chat.py` matches the ESP32's Serial Monitor output
- Ensure both devices are on the **same Wi-Fi network**
- Check that the ESP32 firmware is flashed and running (LED should be on)

### ❌ `ConnectionRefusedError` on WebSocket

- The ESP32 may have rebooted — check Serial Monitor for the IP again
- Try power-cycling the ESP32

### ❌ LLM not responding / slow

- Ensure `ollama serve` is running in another terminal
- The phi3 model requires ~4GB RAM. Close other applications if slow.
- Verify the model is downloaded: `ollama list`

### ❌ Motors not moving but ESP32 receives command
 
- Check EEP / nSLEEP pins — ensure GPIO13 / GPIO33 are pulled HIGH or driven HIGH by firmware
- Verify DRV8833 VM power supply (requires 2.7V–10.8V with sufficient motor current)
- Ensure common ground (GND) is connected between the ESP32 and DRV8833 power supply
- Double check wiring against the pin table above

### ❌ `Unknown Command` in Serial Monitor

- The command string may contain extra whitespace or encoding issues
- The ESP32 calls `.trim()` and `.toUpperCase()` — valid commands must match exactly: `FORWARD`, `BACKWARD`, `LEFT`, `RIGHT`, `STOP`

---

## 🗺️ Roadmap

- [x] WebSocket-based motor control
- [x] Natural language command parsing via local LLM
- [x] Bidirectional communication (ESP32 acknowledges commands)
- [ ] Speed control (PWM via EN pins)
- [ ] Ultrasonic obstacle avoidance
- [ ] Camera integration & vision-based navigation
- [ ] Voice input (microphone → speech-to-text → IKRU)
- [ ] Web dashboard for robot monitoring
- [ ] Multi-robot coordination
- [ ] ROS2 integration

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Create a feature branch**: `git checkout -b feature/your-feature`
3. **Commit your changes**: `git commit -m 'Add some feature'`
4. **Push to the branch**: `git push origin feature/your-feature`
5. **Open a Pull Request**

Please make sure your code follows the existing style and include comments where appropriate.

---

## 📄 License

This project is licensed under the **MIT License** — feel free to use, modify, and distribute it.

---

<div align="center">

Made with ❤️ by **ajsike2310**

*IKRU — Where Natural Language Meets Physical Intelligence*

</div>
