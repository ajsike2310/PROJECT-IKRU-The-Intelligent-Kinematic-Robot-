<div align="center">

# 🤖 PROJECT IKRU
### The Intelligent Kinematic Robot Unit

**A low-cost desktop companion robot that hears, sees, remembers and moves — powered by local AI, with no cloud service required.**

[![CI](https://github.com/ajsike2310/PROJECT-IKRU-The-Intelligent-Kinematic-Robot-/actions/workflows/ci.yml/badge.svg)](https://github.com/ajsike2310/PROJECT-IKRU-The-Intelligent-Kinematic-Robot-/actions/workflows/ci.yml)

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)
![ESP32](https://img.shields.io/badge/ESP32-Firmware-E7352C?style=for-the-badge&logo=espressif&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-Local%20LLM-111111?style=for-the-badge)
![Whisper](https://img.shields.io/badge/faster--whisper-Offline%20STT-2E8B57?style=for-the-badge)
![CUDA](https://img.shields.io/badge/NVIDIA-CUDA%2012-76B900?style=for-the-badge&logo=nvidia&logoColor=white)
![Tests](https://img.shields.io/badge/tests-102%20passing-brightgreen?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)

*Mar Baselios College of Engineering and Technology · Department of Computer Science and Engineering*

</div>

---

## Table of Contents

1. [Overview](#1-overview)
2. [Features](#2-features)
3. [System Architecture](#3-system-architecture)
4. [Hardware](#4-hardware)
5. [Quick Start](#5-quick-start)
6. [Command Reference](#6-command-reference)
7. [Talking to IKRU](#7-talking-to-ikru)
8. [Configuration](#8-configuration)
9. [How the Smart Parts Work](#9-how-the-smart-parts-work)
10. [Testing](#10-testing)
11. [Communication Protocol](#11-communication-protocol)
12. [Project Structure](#12-project-structure)
13. [Troubleshooting](#13-troubleshooting)
14. [Known Limitations and Roadmap](#14-known-limitations-and-roadmap)
15. [Documentation](#15-documentation)
16. [Contributors and Acknowledgements](#16-contributors-and-acknowledgements)
17. [License](#17-license)

---

## 1. Overview

**IKRU** is a two-wheeled desktop robot built from inexpensive off-the-shelf parts: two ESP32 boards, a small OLED face, an ultrasonic sensor, a motor driver and a speaker. All the heavy thinking runs on an ordinary PC that the user already owns.

You talk to IKRU. It listens, decides what you mean, answers out loud with an expressive animated face, and — when you ask — moves. When nobody is talking to it, it lives its own small life on the desk: it looks around, remembers what it sees, wanders within a safe radius and says things that are grounded in what is actually happening around it.

> **Local-first by design.** The language model, vision model, speech recogniser, voice-activity detector, decision model and memory all run on your own machine. No API keys, no subscriptions, and no internet needed once the models are downloaded.

![IKRU terminal start-up screen](image.png)

---

## 2. Features

| Area | What IKRU does |
|---|---|
| 🗣️ **Offline speech recognition** | Silero VAD + `faster-whisper` (Whisper-small) on the GPU, with automatic language identification. No internet at run time. |
| 🧠 **Local language model** | Chat through [Ollama](https://ollama.com) (`qwen2.5:3b` by default) returning structured JSON: a spoken reply with emotion tags plus physical *tools*. |
| ⚡ **Fast action routing** | The *Laya* decision model chooses the physical action in parallel with the LLM, so "stop" never waits for a full reply. |
| 👁️ **Vision** | The ESP32-CAM streams UDP video; a vision-language model (`qwen3-vl:4b`) describes scenes and names objects. |
| 🧭 **Autonomous roaming** | Dead-reckoned world model, ultrasonic occupancy grid, leash around home, startle and obstacle reflexes. |
| 🔎 **Object search** | "Find my mug" — IKRU roams, inspects obstacles with the camera and reports back. |
| 💭 **Grounded spontaneous thoughts** | Idle remarks are built from the live camera view, time of day, the user and IKRU's own state — not from canned lines — with repeat control. |
| 🗂️ **Visual memory** | Remembers *where* and *when* it last saw objects (persisting across restarts). "Where is my mug?" is answered from memory. |
| 😀 **Expressive face** | 18 procedural eye expressions on an SSD1306 OLED, speech-bubble text scrolling, droid sounds. |
| 🧰 **Long-term memory** | SQLite history and user facts plus Qdrant semantic recall, so IKRU remembers *you*. |
| 🛡️ **Layered safety** | Firmware brake, proximity reflexes, roaming stop, link watchdog and instant yielding when you speak. |
| 🖥️ **Terminal UI** | Start-up banner with mascot and laptop specs, coloured status output. |

---

## 3. System Architecture

Three computing nodes cooperate over a private Wi-Fi network created by the camera head.

```
 ┌────────────────────────────── PC (Python) ───────────────────────────────┐
 │  Mic ─► Silero VAD ─► faster-whisper (GPU) ─► text                        │
 │                                   │                                       │
 │            ┌──────────────────────┴──────────────────────┐                │
 │            ▼                                             ▼                │
 │   Laya router (action)                      Chat LLM via Ollama (reply)   │
 │            └──────────────────────┬──────────────────────┘                │
 │                                   ▼                                       │
 │             merge ─► speak + face ─► tools ─► RobotController             │
 │                                                                           │
 │   Vision (UDP + VLM) · Memory (SQLite + Qdrant) · Autonomous brain        │
 └───────────────▲───────────────────────────────────────┬──────────────────┘
        UDP :2222 │ JPEG frames                           │ WebSocket :81
 ┌───────────────┴───────────┐               ┌───────────▼──────────────────┐
 │ ESP32-CAM  (head)         │               │ ESP32-WROOM-32  (body)       │
 │ Wi-Fi access point        │               │ motors · OLED face · sonar   │
 │ "IKRU-CAM", 192.168.4.1   │               │ speaker · safety brake       │
 └───────────────────────────┘               │ fixed IP 192.168.4.200       │
                                             └──────────────────────────────┘
```

Interactive UML and data-flow diagrams are in [`docs/diagrams/`](docs/diagrams/). The full developer handbook is [`docs/HOW_IKRU_WORKS.md`](docs/HOW_IKRU_WORKS.md).

### Network at a glance

| Device | Address |
|---|---|
| Camera head (access point `IKRU-CAM`) | `192.168.4.1` |
| Robot body | `192.168.4.200` (fixed) |
| PC | DHCP on `192.168.4.0/24` |

> Guest and campus Wi-Fi usually isolate devices from each other, so use the `IKRU-CAM` network. Power the **head first**, then the body.

---

## 4. Hardware

| Component | Model | Qty | Purpose |
|---|---|:-:|---|
| Body controller | ESP32-WROOM-32 DevKit | 1 | WebSocket server, motors, OLED, sonar, speaker |
| Head controller | AI-Thinker ESP32-CAM (OV2640) | 1 | Access point and UDP JPEG video |
| Motor driver | DRV8833 | 1 | Dual H-bridge |
| Drive motors | TT / N20 gear motors | 2 | Left and right wheel |
| Display | 0.96″ SSD1306 OLED (I²C) | 1 | Animated eyes and speech box |
| Distance sensor | HC-SR04(P) ultrasonic | 1 | Obstacle sensing and emergency brake |
| Speaker | SmartElex digital speaker module | 1 | Droid sounds and audio |
| Power | Battery pack + buck-boost converters | — | Logic and motor supply (common ground!) |
| Chassis | 3D-printed two-wheel body | 1 | Frame |

**Pin map (body firmware, `firmware/controller/controller.ino`)**

| Signal | GPIO | Notes |
|---|:-:|---|
| Left motor `IN1` / `IN2` | 26 / 27 | PWM |
| Right motor `IN3` / `IN4` | 14 / 12 | PWM |
| Driver enable `EEP` (nSLEEP) | 13 | Driven HIGH (33 also kept HIGH for older wiring) |
| OLED `SDA` / `SCL` | 21 / 22 | I²C address `0x3C` |
| Ultrasonic `TRIG` / `ECHO` | 18 / 19 | Echo may need a level shifter |
| Speaker audio | 25 | PWM tones |

> ⚠️ GPIO 34–39 are **input-only** on the ESP32 — never use them for motor outputs.

A parts list with approximate costs is in the project report.

---

## 5. Quick Start

### 5.1 Requirements

| Requirement | Notes |
|---|---|
| **OS** | Windows 10/11 (Wi-Fi control uses Windows network commands) |
| **Python** | 3.10+ (developed and tested on **3.13**) |
| **GPU** | NVIDIA GPU with CUDA 12 — required for offline speech recognition. 6 GB is enough for Whisper-small |
| **Ollama** | https://ollama.com |
| **Wi-Fi** | Ideally two adapters (one for internet, one for `IKRU-CAM`) |
| **Arduino IDE 2.x** | With the Espressif ESP32 core 3.x, for flashing firmware |

### 5.2 Clone and create the environment

```powershell
git clone https://github.com/ajsike2310/PROJECT-IKRU-The-Intelligent-Kinematic-Robot-.git
cd PROJECT-IKRU-The-Intelligent-Kinematic-Robot-

python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

### 5.3 Install PyTorch with CUDA, then the project

The CUDA 12 / cuDNN 9 libraries that the speech recogniser needs ship inside the PyTorch CUDA wheel, so install that first (the project was developed with `torch 2.6.0+cu124`).

```powershell
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
pip install faster-whisper silero-vad          # also listed in requirements.txt
```

### 5.4 Pull the Ollama models

```powershell
ollama pull qwen2.5:3b        # chat model (set in config.json -> "llm_model")
ollama pull qwen3-vl:4b       # vision model (config.json -> "vlm_model")
ollama list
```

### 5.5 Download the speech model (one time, needs internet)

```powershell
.\venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download as s; s('Systran/faster-whisper-small', local_dir='data/models/faster-whisper-small')"
```

After this, speech recognition loads from `data/models/faster-whisper-small` and never touches the network. (`data/models/` is git-ignored.)

> If the download crawls, retry with `$env:HF_HUB_DISABLE_XET = "1"` first.

### 5.6 Flash the firmware

1. Open `firmware/controller/controller.ino` → board **ESP32 Dev Module** → install the **WebSockets** (Markus Sattler) and **U8g2** libraries → Upload.
2. Open `firmware/head/head.ino` → board **AI Thinker ESP32-CAM** → Upload.
3. Keep Wi-Fi credentials out of Git: they live in the git-ignored `config.local.json`.

### 5.7 Run IKRU

```powershell
ollama serve                                   # if Ollama is not already running
.\venv\Scripts\python.exe run.py
```

On start-up IKRU shows the banner, then a **bring-up** sequence: PC network → robot power-on → join `IKRU-CAM` → body link. Answer the prompts, wait for *ready*, and start talking. Say **"exit"** (or type it) to quit; `Ctrl+C` also works.

---

## 6. Command Reference

### 6.1 Launching

```powershell
.\venv\Scripts\python.exe run.py [options]
```

| Option | Purpose |
|---|---|
| `--ip IP` | Robot body IP or hostname (default from `config.json`) |
| `--cam-ip IP` | ESP32-CAM IP address |
| `--volume N` | Speaker volume 0–100 |
| `--pc-audio` | Also play audio through the PC speakers |
| `--voice-mode {r2d2,tts}` | `r2d2` = instant droid chirps on the robot speaker (default); `tts` = neural speech |
| `--tts-engine {chatterbox,chatterbox_mtl,edge}` | Text-to-speech engine for `tts` mode |
| `--voice NAME` | Edge-TTS voice preset (`guy`, `jenny`, `ana`, `ryan`, …) |
| `--voice-prompt WAV` | Reference WAV for Chatterbox voice cloning |
| `--lang CODE` | Language for multilingual Chatterbox (`fr`, `zh`, `es`, …) |
| `--no-mic` | Disable the microphone; type instead |
| `--no-ui` | Plain output (no banner or mascot) |
| `--no-vision` | Disable the camera feed |
| `--no-wizard` | Skip the connection menu when the robot isn't found |
| `--provision-wifi` | Send new Wi-Fi credentials to the robot |

Common combinations:

```powershell
.\venv\Scripts\python.exe run.py --no-mic                 # keyboard only
.\venv\Scripts\python.exe run.py --no-vision --no-mic     # lightest possible
.\venv\Scripts\python.exe run.py --voice-mode tts --tts-engine edge
.\venv\Scripts\python.exe run.py --ip 192.168.4.200 --cam-ip 192.168.4.1
```

If the robot can't be found, a menu offers `[r]etry`, `[m]anual IP`, `[u]sb serial` or `[c]ontinue offline`.

### 6.2 Offline speech-recognition trial (isolated, no robot needed)

A standalone test bench lives in [`trial/offline_speech_recognition/`](trial/offline_speech_recognition/README.md).

```powershell
$T = ".\venv\Scripts\python.exe trial\offline_speech_recognition\run_trial.py"

Invoke-Expression "$T gpu-check"                  # nvidia-smi, CUDA, model init on the GPU
Invoke-Expression "$T file path\to\audio.wav"     # transcribe a WAV (16 kHz mono)
Invoke-Expression "$T mic-test --seconds 5 --save my_clip.wav"
Invoke-Expression "$T live"                       # mic -> Silero VAD -> Whisper
Invoke-Expression "$T --language ml file clip.wav"   # force a language (default: auto)
Invoke-Expression "$T offline-verify clip.wav"    # blocks the network, then transcribes
Invoke-Expression "$T bench trial\offline_speech_recognition\samples"   # latency + WER
```

### 6.3 Handy utilities

```powershell
ollama ps                                         # models currently loaded in VRAM
nvidia-smi -l 1                                   # watch GPU memory/utilisation live
Test-NetConnection 192.168.4.200 -Port 81        # is the robot's WebSocket port reachable?
```

---

## 7. Talking to IKRU

IKRU understands natural language — there are no exact keywords to memorise.

| You say… | IKRU does |
|---|---|
| "Move forward for two seconds" | Drives forward 2 s (durations are parsed from your words) |
| "Turn left" / "go backward" | Pivots / reverses |
| "Stop!" | Stops immediately — handled before the LLM finishes |
| "Dance" / "celebrate" / "act confused" | Plays a choreographed sequence |
| "Find my coffee mug" | Roams the desk and inspects obstacles with the camera |
| "Where is my coffee mug?" | Answers from visual memory: *where* and *how long ago* it last saw it |
| "What did you see earlier?" | Summarises its recent camera views |
| "What am I wearing?" | Grabs a frame and asks the vision model |
| "My name is Alex" | Remembers it across sessions |
| "Stop searching" | Cancels the search |
| "Exit" | Plays a sleepy animation and shuts down |

Built-in choreographies: `celebrate`, `victory_twirl`, `happy_dance`, `confused_wiggle`, `scared_retreat`, `curious_scan`, `disapproval_shake`. Add your own as JSON in `data/sequences/`.

Facial expressions (18): `normal happy glee sad worried focused annoyed surprised skeptic frustrated unimpressed sleepy suspicious squint angry furious scared awe`.

---

## 8. Configuration

Settings live in `config.json`; machine-specific overrides (Wi-Fi, last robot IP) go in the git-ignored `config.local.json`, which is merged on top.

| Section | Key examples |
|---|---|
| top level | `robot_ip`, `cam_ip`, `llm_model`, `vlm_model`, `llm_keep_alive`, `enable_mic`, `enable_vision`, `tts_engine`, `volume` |
| `mic` | `vad_threshold`, `silence_ms` (700), `preroll_ms` (400), `max_utterance_s` (15), `stt_model`, `stt_model_dir`, `stt_compute_type`, `stt_language` (`null` = auto-detect) |
| `memory` | `sqlite_path`, `qdrant_path`, `recall_top_k`, `recall_threshold` |
| `autonomous` | `enabled`, `roam_enabled`, `leash_cm`, `idle_before_roam_s`, `vision_min_gap_s` (30), `glance_s` (60), `search_timeout_s` |
| `tool_router` | `engine`, `mode` (`parallel`/`sequential`), `laya_model`, `device`, `min_confidence` |
| `ui` | `status_bar` (off by default) |

> **Tip — slow replies after the camera looks around?** The vision and chat models share GPU memory. Raise `autonomous.vision_min_gap_s` or set `autonomous.glance_s` to `0`.

---

## 9. How the Smart Parts Work

<details>
<summary><b>🎙️ Offline speech recognition</b></summary>

Microphone audio (16 kHz mono) is cut into 32 ms frames and scored by **Silero VAD**: an utterance opens after two speech frames, keeps 400 ms of pre-roll so the first word isn't clipped, and closes after 700 ms of silence (forced cut at 15 s). Each utterance is transcribed on the GPU by **Whisper-small** through `faster-whisper` (float16), with automatic language identification. The model loads once at start-up and is reused. There is deliberately **no CPU or online fallback** — if CUDA or the model is missing, start-up fails with a clear message and IKRU falls back to typed input.

Preliminary results on an RTX 4050 laptop GPU (synthetic English speech): 3–12 s of audio transcribed in 0.4–1.0 s, ~0.7 GB VRAM.
</details>

<details>
<summary><b>💭 Grounded spontaneous thoughts</b></summary>

When idle, IKRU builds each thought from live context: the current camera description, the time of day, how long since you last interacted, its own energy, what it knows about you, related memories, sonar and the world model. A short "focus" line only picks *which* of those to talk about (sight, atmosphere, human, self) and rotates so topics don't repeat. Each thought is compared with the last ten; a near-duplicate is regenerated once and otherwise dropped. The prompt forbids inventing things that aren't in the context and lets IKRU stay silent when there is nothing to say.
</details>

<details>
<summary><b>🗂️ Visual memory</b></summary>

Every camera look files the named objects and a scene description into the world model: when each object was last seen, what it was next to and a short description of the view, plus a rolling log of the latest 12 views — all persisted in `data/memory/world_model.json`. IKRU glances at the desk about once a minute while resting and at most stops while roaming (rate-limited by `vision_min_gap_s`). "Where is X?" is answered from this memory; a physical search starts only if X was never seen or you say "go find…". Positions are stored in words ("near the laptop"), not coordinates, because the dead-reckoned pose resets each session.
</details>

<details>
<summary><b>🛡️ Safety layers</b></summary>

| Layer | Trigger | Action |
|---|---|---|
| Firmware brake | Obstacle < 12 cm while driving forward | Active brake, refuses forward motion |
| Python move loop | Proximity checked every 0.1 s | Pause and resume |
| Proximity reflex | Object < 10 cm | Startle reaction |
| Roaming stop | Obstacle < 25 cm | Stop and pick a new heading |
| Link watchdog | Body loses the PC for 3 s | Motors stop |
| User priority | Voice detected | Autonomy yields within ~50–100 ms |
</details>

---

## 10. Testing

The automated suite replaces the robot, camera and language models with fakes, so it runs on a plain PC.

```powershell
pip install pytest

# Core suite (same files as the report)
.\venv\Scripts\python.exe -m pytest tests\test_autonomous_roaming.py tests\test_laya_router.py `
    tests\mic\test_vad_segmenter.py tests\net tests\robot\test_motor_diagnose.py `
    tests\test_autonomous_grounding.py tests\test_visual_memory.py -q

# Other offline tests
.\venv\Scripts\python.exe -m pytest tests\test_idle_behavior.py tests\test_proximity_reactions.py tests\test_emotion_sequences.py -q

# Speech-recognition trial suite (unittest)
cd trial\offline_speech_recognition
..\..\venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

| Suite | Passed |
|---|:-:|
| Roaming and object search | 23 |
| Laya tool router | 30 (+1 skipped) |
| Speech segmentation | 6 |
| Grounded thoughts | 8 |
| Visual memory | 9 |
| Network discovery and bring-up | 17 |
| Motor diagnosis | 9 |
| **Total** | **102** (1 skipped, 0 failed) |

The one skipped test needs the real Laya model. Tests that need real hardware (`tests/robot/test_robot.py`, `tests/robot/test_socket.py` (edit the IP at the top first), `tests/robot/test_motors.py`, `tests/robot/test_ultrasonic*.py`, `tests/robot/test_roam_calibration.py`, `tests/vision/*`) are interactive diagnostics — run them with the robot powered on, not through pytest collection.

> These tests verify logic, not real-world accuracy. The speech results so far use synthetic English audio; Malayalam and other languages still need real-recording evaluation.

---

## 11. Communication Protocol

Plain-text commands over WebSocket (`ws://192.168.4.200:81`), UTF-8, case-insensitive. The body replies `OK` or JSON.

| Group | Examples |
|---|---|
| Motion | `FORWARD`, `BACKWARD`, `LEFT`, `RIGHT`, `STOP` |
| Faces | `HAPPY`, `SAD`, `FOCUSED`, `SLEEPY`, … (18 emotions) |
| Gaze | `BLINK`, `LOOK_LEFT`, `LOOK_RIGHT`, `LOOK_FRONT`, `LOOK_TOP`, `LOOK_BOTTOM`, `LOOK:x:y` |
| Display | `DISPLAY_OPEN`, `DISPLAY:<text>`, `DISPLAY_CLOSE` |
| Sounds | `SIGH`, `GASP`, `GIGGLE`, `LAUGH`, `WHISPER`, … |
| Sensors / safety | `GET_DISTANCE`, `SET_OBSTACLE_THRESHOLD:<cm>`, `OBSTACLE_BRAKE_*` |
| System | `GET_IP`, `SETUP:`/`SETUP_DONE`, `SET_WIFI:` |

| Port | Protocol | Purpose |
|:-:|:-:|---|
| 81 | TCP (WebSocket) | PC ⇄ body control |
| 4210 / 4211 | UDP | Body discovery beacon / PC announcement |
| 2222 | UDP | Camera JPEG stream (1200-byte chunks, 22-byte header) |
| 2223 | UDP | Camera discovery |
| 11434 | HTTP (local) | Ollama |

Python API example:

```python
from ikru.robot import RobotController

robot = RobotController(ip="192.168.4.200")
robot.forward(2)            # drive forward for 2 seconds
robot.happy()               # set the face
robot.display("Hello!")     # scroll text on the OLED
robot.close()
```

---

## 12. Project Structure

```
PROJECT-IKRU/
├── run.py                     # entry point
├── config.json                # settings   (config.local.json = private overrides)
├── requirements.txt
├── software/ikru/
│   ├── main.py                # start-up, bring-up, chat loop
│   ├── mic/                   # PyAudio, Silero VAD, offline Whisper STT
│   ├── chat/                  # Ollama engine, prompts, parser, Laya tool router
│   ├── autonomy/              # brain, world model + visual memory, locomotion, search
│   ├── vision/                # UDP receiver, frame buffer, VLM client
│   ├── memory/                # SQLite + Qdrant memory
│   ├── robot/                 # WebSocket client, sequences, idle, proximity
│   ├── audio/                 # TTS service
│   ├── net/                   # Wi-Fi bring-up, discovery, USB serial
│   └── ui/                    # terminal banner, mascot, system info
├── firmware/
│   ├── controller/            # ESP32 body: motors, OLED face, sonar, WebSocket
│   └── head/                  # ESP32-CAM: access point + UDP video
├── tests/                     # pytest suites and hardware diagnostics
├── trial/offline_speech_recognition/   # isolated speech-recognition test bench
├── data/                      # memory, sequences, local models (git-ignored weights)
├── docs/                      # handbook and diagrams
└── reportsandpaper/           # project report and conference paper
```

---

## 13. Troubleshooting

| Symptom | What to try |
|---|---|
| **Robot not found** | Join Wi-Fi `IKRU-CAM`; power the head first, then reset the body. Guest/campus Wi-Fi blocks device-to-device traffic. |
| **Port 81 refused** | Allow Python through Windows Firewall; power-cycle the body. |
| **`Whisper model not found`** | Run the download command in [5.5](#55-download-the-speech-model-one-time-needs-internet). |
| **`CTranslate2 sees no CUDA device`** | Check `nvidia-smi` and the NVIDIA driver; install PyTorch with the CUDA 12 wheel ([5.3](#53-install-pytorch-with-cuda-then-the-project)). There is no CPU fallback by design. |
| **`cudnn64_9.dll` / `cublas64_12.dll` missing** | They ship in the PyTorch CUDA wheel (`venv\Lib\site-packages\torch\lib`); reinstall `torch` with the `cu124` index. |
| **Mic not found / PyAudio error** | Windows Settings → Privacy → Microphone; set `mic.device_index` in `config.json`. |
| **Speech cut mid-sentence** | Raise `mic.silence_ms`. **Words clipped at start:** raise `mic.preroll_ms`. |
| **Replies get slow after camera looks** | Vision and chat models compete for VRAM — raise `autonomous.vision_min_gap_s` or set `autonomous.glance_s` to `0`. |
| **Ollama errors / no reply** | Run `ollama serve`; check `ollama list` for the configured models. |
| **Motors silent but command received** | Check `EEP`/nSLEEP on GPIO 13, motor supply voltage and common ground. |
| **Terminal looks garbled** | Use Windows Terminal; or run with `--no-ui`. |

---

## 14. Known Limitations and Roadmap

**Current limitations**

- Speech recognition is validated on synthetic English only; Malayalam, other languages and mixed speech need real-recording evaluation.
- Whisper needs an NVIDIA GPU; there is no CPU fallback.
- Navigation is open-loop (no wheel encoders), so the pose estimate drifts.
- IKRU can *find* objects but cannot *fetch* them (no gripper).
- Vision, chat and speech models share limited GPU memory.
- LLM tool arguments are not yet validated against an allow-list.

**Roadmap**

- [x] WebSocket motor control and expressive OLED face
- [x] Local LLM with structured tool calls and parallel Laya routing
- [x] Vision streaming and scene understanding
- [x] Autonomous roaming, object search and world model
- [x] Persistent memory (history, facts, semantic recall)
- [x] Offline multilingual speech recognition (GPU)
- [x] Grounded spontaneous thoughts and persistent visual memory
- [ ] Evaluate Malayalam / mixed speech; compare Whisper `small` vs `medium`
- [ ] Wheel encoders or an IMU to cut dead-reckoning drift
- [ ] Gripper or arm for fetching objects
- [ ] User study of spontaneous thoughts; hardware latency and navigation trials

---

## 15. Documentation

| Resource | Location |
|---|---|
| Developer handbook | [`docs/HOW_IKRU_WORKS.md`](docs/HOW_IKRU_WORKS.md) |
| UML and data-flow diagrams | [`docs/diagrams/`](docs/diagrams/) |
| Speech-recognition trial guide | [`trial/offline_speech_recognition/README.md`](trial/offline_speech_recognition/README.md) |
| Project report and conference paper | [`reportsandpaper/`](reportsandpaper/) |

---

## 16. Contributors and Acknowledgements

### 👩‍💻👨‍💻 Project Team

Students of the Department of Computer Science and Engineering, **Mar Baselios College of Engineering and Technology (Autonomous)**, Nalanchira, Thiruvananthapuram, Kerala, India.

| Name |
|---|
| **Athira S** |
| **Avin Joy** |
| **Divina Ann Shaji** |
| **V. Anantha Krishnan** |

### 🌟 Special Mentions

| | |
|---|---|
| **Priya Mariam Raju** — *Project Guide, Assistant Professor, Dept. of CSE* | For dedicated mentorship, technical insight and steady encouragement throughout the project. |
| **Dr. Anne Dickson** — *Head of the Department of CSE* | For constant support, academic encouragement and the facilities that made this work possible. |
| **Ms. Gayathri K.S.** — *Project Co-ordinator, Dept. of CSE* | For providing the academic environment, resources and coordination. |
| **Mar Baselios College of Engineering and Technology** | For the platform, laboratory access and institutional support. |

### 🙏 Open-Source Acknowledgements

IKRU stands on the shoulders of excellent open-source work:
[Ollama](https://ollama.com) and the [Qwen](https://github.com/QwenLM) model family ·
[OpenAI Whisper](https://github.com/openai/whisper) and [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [CTranslate2](https://github.com/OpenNMT/CTranslate2) ·
[Silero VAD](https://github.com/snakers4/silero-vad) ·
[Laya](https://huggingface.co/convaiinnovations/laya) (ConvAI Innovations) ·
[Chatterbox TTS](https://github.com/resemble-ai/chatterbox) (Resemble AI) ·
[Qdrant](https://qdrant.tech) and FastEmbed ·
[PyTorch](https://pytorch.org) ·
[OpenCV](https://opencv.org) ·
[U8g2](https://github.com/olikraus/u8g2) and the Arduino WebSockets library ·
the [Espressif](https://www.espressif.com) ESP32 Arduino core ·
and [Pollen Robotics' Reachy Mini](https://github.com/pollen-robotics/reachy_mini), whose public code was a reference for expressive robot behaviour (`referencereachycode/`).

---

## 17. License

Released under the **MIT License**.

<div align="center">

*IKRU — where natural language meets physical intelligence.*

</div>
