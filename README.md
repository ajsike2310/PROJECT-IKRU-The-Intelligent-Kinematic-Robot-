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
│                                    │    L293D Motor Driver   │  │
│                                    │   EN1/EN2/C1A/C1B/...   │  │
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
| **Microcontroller** | ESP32-WROOM-32 DevKit | 1 | Main controller, Wi-Fi, WebSocket server |
| **Motor Driver** | L293D Module | 1 | Drives both DC motors |
| **DC Motors** | TT Gear Motors (3–6V) | 2 | Left and right wheel drive |
| **Chassis** | 2WD Robot Chassis | 1 | Physical robot frame |
| **Power Supply** | LiPo / 18650 Battery Pack | 1 | Powers ESP32 + motors |
| **Wheels** | Compatible wheels | 2 | Locomotion |

---

### Pin Wiring Diagram

```
ESP32 Pin     →    L293D Module Pin    →    Function
──────────────────────────────────────────────────────
D13  (GPIO13) →    EN1                 →    Enable Left  Motor (M1)
D33  (GPIO33) →    EN2                 →    Enable Right Motor (M2)
D26  (GPIO26) →    C1-A                →    Left  Motor Direction A
D27  (GPIO27) →    C1-B                →    Left  Motor Direction B
D14  (GPIO14) →    C2-A                →    Right Motor Direction A
D12  (GPIO12) →    C2-B                →    Right Motor Direction B
```

> ⚠️ **Important:** GPIO34 is **input-only** on ESP32. Do **not** use it for EN2. Use GPIO33 instead.

#### L293D Motor Control Truth Table

| EN  | C_-A | C_-B | Result     |
|-----|------|------|------------|
| HIGH | HIGH | LOW  | Forward    |
| HIGH | LOW  | HIGH | Backward   |
| LOW  | X    | X    | Stop/Coast |

#### Movement Logic

| Command  | Left Motor (M1) | Right Motor (M2) | Result              |
|----------|-----------------|------------------|---------------------|
| FORWARD  | Forward         | Forward          | Straight ahead      |
| BACKWARD | Backward        | Backward         | Straight back       |
| LEFT     | Backward        | Forward          | Pivot turn left     |
| RIGHT    | Forward         | Backward         | Pivot turn right    |
| STOP     | Disabled        | Disabled         | Coast to stop       |

---

## 💻 Software Stack

| Layer | Technology | Version |
|---|---|---|
| **Firmware** | Arduino C++ (ESP32 Arduino Core) | Latest |
| **WebSocket Server** | `WebSocketsServer` (Arduino library) | Latest |
| **AI Controller** | Python | 3.8+ |
| **Local LLM** | Ollama + `phi3:3.8b-mini-4k-instruct-q4_K_M` | Latest |
| **Python WebSocket Client** | `websocket-client` | Latest |
| **LLM Client** | `ollama` Python package | Latest |

---

## 📁 Project Structure

```
PROJECT-IKRU/
│
├── README.md                          # You are here
├── ESP32.jpeg                         # ESP32 hardware reference image
├── L293Dmotordriver.jpeg              # L293D module reference image
│
└── src/                                # Main Python application
    ├── __init__.py                    # Package initializer
    ├── robot.py                       # Robot WebSocket client class
    ├── chat.py                        # AI chat loop & LLM integration
    │
    └── esp32_controller/              # Arduino firmware
        └── esp32_controller.ino       # ESP32 WebSocket server + motor control
```

### File Descriptions

#### `src/robot.py` — Robot Controller Class
Provides a clean Python API to communicate with the ESP32 over WebSocket.

```python
from robot import Robot

robot = Robot(ip="192.168.1.44")  # Connect to ESP32
robot.forward()                   # Send FORWARD command
robot.left()                      # Send LEFT command
robot.stop()                      # Send STOP command
robot.close()                     # Close WebSocket connection
```

#### `src/chat.py` — AI Chat Loop
The main entry point. Accepts natural language input, queries the local LLM, parses the JSON tool call, and dispatches the correct robot function.

#### `src/esp32_controller/esp32_controller.ino` — ESP32 Firmware
Runs on the ESP32. Connects to Wi-Fi, starts a WebSocket server on **port 81**, and interprets incoming text commands (`FORWARD`, `BACKWARD`, `LEFT`, `RIGHT`, `STOP`) to control the motors via the L293D driver.

---

## ⚙️ How It Works

1. **User types** a natural language command into the terminal (e.g. `"Move forward please"` or `"Turn left"`).
2. **`chat.py`** appends it to a conversation history and sends it to the **Ollama LLM** (phi3 model).
3. The **LLM** responds with either:
   - A **JSON tool call** like `{"tool": "forward"}` → for robot movement requests
   - A **plain text answer** → for non-movement questions (acts like ChatGPT)
4. **`chat.py`** attempts to parse the response as JSON. If successful and the `"tool"` key is present, it calls the corresponding method on the `Robot` instance.
5. The **`Robot` class** sends the command string (e.g. `"FORWARD"`) to the ESP32 over a **WebSocket connection** (`ws://[IP]:81`).
6. The **ESP32** receives the string, parses it, and activates the appropriate GPIO pins on the **L293D motor driver**, making the robot move.
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

**Step 1:** Install the required Arduino library:
- Open Arduino IDE → **Sketch → Include Library → Manage Libraries**
- Search for **`WebSockets`** by Markus Sattler and install it

**Step 2:** Update Wi-Fi credentials in `esp32_controller.ino`:
```cpp
const char* ssid     = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";
```

**Step 3:** Flash the firmware:
- Select board: **ESP32 Dev Module**
- Select correct COM port
- Click **Upload**

**Step 4:** Open Serial Monitor at `115200` baud. Note the IP address printed:
```
Connected!
IP Address: 192.168.1.44
WebSocket Server Started
```

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

# Install dependencies
pip install websocket-client ollama
```

---

### 3. Ollama & LLM Setup

```bash
# Install Ollama from https://ollama.ai/
# Then pull the phi3 model used by IKRU:
ollama pull phi3:3.8b-mini-4k-instruct-q4_K_M

# Verify it is available:
ollama list
```

> 💡 The model runs entirely **locally** on your CPU/GPU. No internet connection is needed after the initial download.

---

### 4. Running the Robot

**Step 1:** Update the IP address in `src/chat.py` to match your ESP32's IP:
```python
robot = Robot(ip="192.168.1.44")  # Change this to your ESP32's IP
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

- Check EN1/EN2 pins — ensure GPIO33 is used for EN2 (NOT GPIO34, which is input-only)
- Verify L293D module power supply (needs sufficient current for motors)
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
