# How IKRU Works — Complete Codebase Manual & Developer Handbook

> **Who this is for:** someone who knows basic programming (variables, functions, loops, classes) but has never seen this project. Read it top to bottom once. After that, use it as a reference.
>
> **What it covers:** the real code in this repository as of the `ikru_dashboard` branch (September 2026), including uncommitted working-tree changes. Every file path, class and function named here exists in the repo. Where the code and the old `README.md` disagree, **this document follows the code**, and Part 17 lists those disagreements.

> **Diagrams:** interactive versions of the system architecture, use case, class, activity, sequence and DFD (levels 1–3) diagrams are in [`diagrams/`](diagrams/). See the index in [`README.md`](README.md).

---

## Table of Contents

- [How to read this document](#how-to-read-this-document)
- [Part 1 — Project at a Glance](#part-1--project-at-a-glance)
- [Part 2 — Technology Stack](#part-2--technology-stack)
- [Part 3 — Project Directory Tree](#part-3--project-directory-tree)
- [Part 4 — Folder-by-Folder Explanation](#part-4--folder-by-folder-explanation)
- [Part 5 — Python Reference: Every Important File, Class and Function](#part-5--python-reference-every-important-file-class-and-function)
- [Part 6 — Firmware Deep Dive (the C++ that runs on the robot)](#part-6--firmware-deep-dive-the-c-that-runs-on-the-robot)
- [Part 7 — What Happens When IKRU Starts (Startup Trace)](#part-7--what-happens-when-ikru-starts-startup-trace)
- [Part 8 — One Conversation Turn, End to End](#part-8--one-conversation-turn-end-to-end)
- [Part 9 — Threads and Concurrency: Who Runs When](#part-9--threads-and-concurrency-who-runs-when)
- [Part 10 — Communication Protocols (the wire formats)](#part-10--communication-protocols-the-wire-formats)
- [Part 11 — Data and Storage](#part-11--data-and-storage)
- [Part 12 — What Happens When Something Fails](#part-12--what-happens-when-something-fails)
- [Part 13 — Setting Up and Running the Project](#part-13--setting-up-and-running-the-project)
- [Part 14 — Tests and Diagnostic Tools](#part-14--tests-and-diagnostic-tools)
- [Part 15 — How to Modify the Project (Recipes)](#part-15--how-to-modify-the-project-recipes)
- [Part 16 — Debugging Guide: Where to Look When Something Breaks](#part-16--debugging-guide-where-to-look-when-something-breaks)
- [Part 17 — Known Gaps, Gotchas and Code-vs-README Differences](#part-17--known-gaps-gotchas-and-code-vs-readme-differences)
- [Part 18 — Glossary](#part-18--glossary)
- [Part 19 — Your First Week: A Learning Path](#part-19--your-first-week-a-learning-path)

---

## How to read this document

Each important idea is explained in **two layers**:

> **Simple meaning** — plain language, often with an analogy.
>
> **Technical meaning** — the precise definition and how this project implements it.

When a technical word appears for the first time it is defined on the spot. Every term is also in the [Glossary](#part-18--glossary).

File references look like `software/ikru/main.py:483`. The number is the line where that thing starts, so you can jump straight to it.

---

# Part 1 — Project at a Glance

## What is this project?

**Simple version:** IKRU (said "Ik-roo") is a small two-wheeled desk robot with a personality. You talk to it out loud. It thinks about what you said, answers with droid-style beeps and scrolling text, pulls faces on its little screen, and drives around when you ask it to. When nobody is talking to it, it explores the desk by itself, mutters thoughts, and remembers things about you between sessions.

**Technical version:** IKRU is a **distributed embedded + AI system** made of three computers that talk over a private Wi-Fi network:

| Computer | Hardware | Language | Job |
|---|---|---|---|
| **The PC ("brain")** | Your Windows laptop | Python 3 | Hears speech, runs the AI models, decides what to do, stores memory |
| **The body** | ESP32-WROOM-32 microcontroller | Arduino C++ | Drives the motors, draws the animated eyes on an OLED screen, plays droid sounds, reads the distance sensor |
| **The head** | AI-Thinker ESP32-CAM | Arduino C++ | Creates the `IKRU-CAM` Wi-Fi network and streams camera video to the PC |

> **Microcontroller**
> **Simple meaning:** a tiny, cheap computer on one chip, built to control hardware (motors, lights, sensors) rather than run apps.
> **Technical meaning:** a single-chip system with CPU, RAM, flash storage and I/O pins, running one program in a loop with no full operating system. The ESP32 used here also has built-in Wi-Fi.

All the "intelligence" runs on the PC. The two ESP32 boards are fairly simple: they do what the PC tells them and report sensor readings back.

## What problem does it solve?

It's a hobby/research project that asks: *can a cheap robot feel alive using only local AI?* In practice it demonstrates:

1. **Natural-language robot control.** You say "move forward for three seconds", not `FORWARD`.
2. **Embodied personality.** Speech is paired with facial expressions, sounds and movement.
3. **Local-first AI.** The language model (LLM) and vision model (VLM) run on your own machine through Ollama. Speech-to-text currently uses Google's free web API, so voice input needs internet access. Part 17 covers this.
4. **Autonomy.** When idle, it roams, builds a rough mental map of the desk, and can search the desk for a named object.

## Who uses it?

- **End user:** the person sitting at the desk, who talks to IKRU.
- **Developer (you):** the person who flashes the firmware, runs the Python program, and extends it.

There is no web interface in the current live system. The user interface is **your voice (or keyboard) plus the robot's face, screen text and sounds**. (An old web dashboard is archived in `dump/`, and it no longer runs. See Part 4.)

## What can users do with it?

| You say… | IKRU does… |
|---|---|
| "Hello!" | Happy face, droid chirps, scrolls a greeting on the OLED |
| "Move forward for 3 seconds" | Drives forward 3 s (stopping early if something is within 12 cm) |
| "Turn left" / "Stop" | Pivots / stops (a "stop" can fire *before* the LLM finishes thinking) |
| "Do a victory twirl" | Plays a multi-step choreographed *sequence* (face + sound + wheels) |
| "What am I wearing?" | Grabs a camera frame, asks the vision model, answers from what it "sees" |
| "Find my coffee mug" | Roams the desk, photographs every obstacle, asks the vision model whether it's the mug |
| "My name is Sam" | Stores the fact in a database and greets Sam by name next time |
| "Be angry!" | Acts it out dramatically |
| "Bye" / "exit" | Sleepy face, sigh sound, program ends |

And without anyone asking, IKRU blinks, glances around, yawns, backs away from hands that come too close, goes on short exploration trips, and says spontaneous things.

## What happens from the moment the user starts it?

In plain words, `python run.py` does this:

1. **Network bring-up.** The PC checks its Wi-Fi adapters, waits for the head unit's `IKRU-CAM` network to appear, and joins it.
2. **Find the body.** The PC listens for the body's "I'm here" radio beacon and probes likely addresses, then opens a live connection to it.
3. **Load the brain.** It loads memory (a database plus a "meaning search" store), wakes up the language model, and optionally loads a fast decision model (Laya).
4. **Open eyes and ears.** It starts the microphone listener and the camera video receiver.
5. **Start background life.** It starts the idle animator, the distance-sensor watchdog, and the autonomous brain.
6. **Wake up.** The robot's boot screen turns into its face, and IKRU greets you, by name if it remembers you.
7. **Conversation loop.** From here it repeats: listen → think → speak/emote → move.

Part 7 walks through this with line numbers.

## What are the major parts?

```text
                     ┌──────────────────────── YOUR PC (Python, software/ikru) ───────────────────────┐
  your voice ──mic──►│ mic/        → speech-to-text                                                  │
                     │ chat/       → LLM conversation + tool routing (Ollama, Laya)                  │
                     │ memory/     → SQLite history + Qdrant semantic memory                         │
                     │ vision/     → UDP camera receiver + vision-language model                     │
                     │ autonomy/   → roaming, world model, object search, spontaneous thoughts       │
                     │ robot/      → RobotController (WebSocket client), idle, proximity, sequences  │
                     │ net/        → Wi-Fi bring-up, robot discovery, USB serial fallback            │
                     │ audio/      → optional neural TTS + tiny HTTP audio server                    │
                     │ main.py     → wires all of the above together                                │
                     └───────┬───────────────────────────────────────────────────────┬──────────────┘
                             │ WebSocket text commands (port 81)                     ▲ UDP JPEG video
                             │ UDP beacons 4210 / PC-announce 4211                   │ (port 2222/2223)
                             ▼                                                       │
        ┌──────────── BODY: ESP32-WROOM-32 (firmware/controller) ─────────┐   ┌──── HEAD: ESP32-CAM (firmware/head) ────┐
        │ WebSocket server → parseCommand()                               │   │ Wi-Fi access point "IKRU-CAM"          │
        │ Face library → SSD1306 OLED eyes + scrolling speech box         │   │ 192.168.4.1                             │
        │ SonicPlayer → R2-D2 style tones on a speaker (GPIO 25)          │   │ OV2640 camera → JPEG → UDP chunks       │
        │ DRV8833 motor driver → 2 wheels                                 │   └─────────────────────────────────────────┘
        │ HC-SR04 ultrasonic sensor → distance + emergency brake          │
        └─────────────────────────────────────────────────────────────────┘
```

## The technical architecture in one paragraph

The PC runs **one Python process** that starts **many threads** (parallel workers inside one program; see Part 9). The **main thread** only pumps the camera preview window. A **chat thread** runs the conversation loop in `main.py`. Several **daemon threads** run background behaviours: idle animation, proximity polling, autonomous roaming, microphone capture, speech-to-text, camera reception, WebSocket heartbeat, and memory indexing. The PC is the **client** of a **WebSocket server** on the body (port 81) and sends plain-text commands such as `HAPPY`, `FORWARD`, `DISPLAY:Hello`. The body replies `OK`, or JSON for sensor queries. The head is a **Wi-Fi access point** that every device joins. The body always takes the fixed IP `192.168.4.200`. The head streams camera frames to the PC over **UDP** in 1200-byte chunks with a 22-byte header. The PC calls **Ollama** over HTTP (localhost:11434) for both the chat model and the vision model.

---

# Part 2 — Technology Stack

The table below is the whole stack. Each technology is explained after it.

```text
 USER LAYER         Microphone ─ PyAudio ─ Silero VAD ─ SpeechRecognition(Google STT)
                                               │
 AI LAYER           Ollama (qwen2.5 chat LLM, qwen3-vl VLM)  +  Laya (decision model, PyTorch)
                                               │
 MEMORY LAYER       SQLite (history, facts)  +  Qdrant embedded + FastEmbed (semantic recall)
                                               │
 CONTROL LAYER      Python threads ─ websocket-client ─► ESP32 WebSocketsServer (Arduino)
                                               │
 HARDWARE LAYER     DRV8833 motors · SSD1306 OLED (U8g2 + Face lib) · HC-SR04 sonar · PWM speaker
 VISION LAYER       ESP32-CAM (esp_camera) ─ UDP ─► OpenCV decode ─► FrameBuffer ─► VLM
 NETWORK LAYER      IKRU-CAM soft-AP · UDP beacons · netsh (Windows Wi-Fi control) · pyserial (USB)
```

### Python 3
1. **What:** a general-purpose programming language.
2. **General use:** scripting, AI, web servers, tooling.
3. **Why here:** all the AI libraries (Ollama client, PyTorch, OpenCV, Qdrant) are Python-first.
4. **Where:** everything under `software/`, `tests/`, and `run.py`.
5. **Interactions:** Python drives the robot by sending WebSocket messages, and calls Ollama over HTTP.
6. **Essential?** Yes.
7. **Alternatives:** Node.js or C++. Both would need different AI libraries.

The code uses Python 3.10+ features such as `tuple[bool, float]` type hints in `connection.py`, and `requirements.txt` references Python 3.13 (`audioop-lts`). Use **Python 3.10 or newer**. 3.11/3.12 are the safest choices for the ML libraries.

### Arduino C++ on ESP32 (Arduino-ESP32 core, v3.x)
1. **What:** C++ with the Arduino framework's simplified hardware API (`pinMode`, `digitalWrite`, `millis`, `setup()`/`loop()`).
2. **General use:** programming microcontrollers.
3. **Why here:** the ESP32 has Wi-Fi and enough speed for animation, and the Arduino ecosystem has ready-made libraries for WebSockets, OLEDs and cameras.
4. **Where:** `firmware/controller/` (body), `firmware/head/` (head), and some test sketches under `tests/`.
5. **Interactions:** it hosts the WebSocket server the Python code connects to.
6. **Essential?** Yes, the robot can't move without it.
7. **Alternatives:** ESP-IDF (Espressif's lower-level framework), MicroPython, PlatformIO (same code, different build tool).

The body firmware calls `ledcAttach(pin, freq, bits)`. That is the **Arduino-ESP32 core 3.x** API. Older 2.x cores use `ledcSetup`/`ledcAttachPin` and will fail to compile.

### WebSocket (Python `websocket-client` ↔ Arduino `WebSocketsServer` by Markus Sattler)
> **WebSocket**
> **Simple meaning:** a phone call between two programs. Once connected, either side can talk at any time without redialling.
> **Technical meaning:** a protocol (RFC 6455) that upgrades an HTTP connection into a persistent, full-duplex, message-framed TCP channel.

- **Why:** low latency and bidirectional. The PC sends commands, and the body can push alerts such as `obstacle_alert`.
- **Where:** `software/ikru/robot/controller.py` (client), `firmware/controller/controller.ino:50` (`WebSocketsServer webSocket(81);`).
- **Essential?** Yes, it's the only live control channel. The USB serial link is a fallback for setup only.
- **Alternatives:** raw TCP sockets, MQTT, HTTP REST.

### Ollama
> **Ollama**
> **Simple meaning:** an app that runs AI chat models on your own computer, like a local ChatGPT server.
> **Technical meaning:** a local model server that loads GGUF-quantised LLMs into CPU/GPU memory and exposes an HTTP API on `127.0.0.1:11434`. The `ollama` Python package wraps that API.

- **Why:** fully local, free, simple API, supports both text and vision models.
- **Where:** `chat/engine.py` (`ollama.chat`, `ollama.generate`), `vision/vlm.py` (`ollama.generate(images=[...])`), `autonomy/brain.py` (`_query_llm`).
- **Models used** (from `config.json`): chat `llm_model: "qwen2.5:7b"` and vision `vlm_model: "qwen3-vl:4b"`. `llm_keep_alive: "30m"` keeps the model loaded in memory for 30 minutes after use.
- **Essential?** Yes for conversation. Without it IKRU replies with a canned "I am having a moment of trouble thinking" line.
- **Alternatives:** llama.cpp server, LM Studio, a cloud API.

> **LLM (Large Language Model)**
> **Simple meaning:** an AI that has read a huge amount of text and predicts good replies.
> **Technical meaning:** a transformer neural network that generates text token by token. Here Qwen 2.5 is asked to answer **in JSON** (`format="json"`) so the program can parse both the spoken reply and the list of physical actions.

> **VLM (Vision-Language Model)**
> **Simple meaning:** an AI that can look at a picture and describe it.
> **Technical meaning:** a multimodal model that takes an image plus a text prompt and produces text. Here that is Qwen3-VL 4B through Ollama.

**Important performance note from the code:** loading the VLM can push the chat LLM out of GPU memory (VRAM). That's why `main.py:88` only calls the camera for clearly visual questions, and why the autonomy code rate-limits vision (`vision_min_gap_s: 75`).

### Laya (tool router)
> **Tool routing / tool calling**
> **Simple meaning:** deciding which physical action ("tool") the robot should run for a sentence.
> **Technical meaning:** mapping an utterance to a structured function call such as `{"action": "forward", "duration": 3}`.

- **What:** `convaiinnovations/laya`, a Hugging Face "decision model". It doesn't write text. It answers multiple-choice questions with probabilities, quickly.
- **Why:** it decides the action in parallel with the LLM, so urgent commands like "stop" run before the LLM has finished its sentence.
- **Where:** `software/ikru/chat/tool_router.py`. It's enabled by `config.json → tool_router.engine: "laya"`.
- **Essential?** No. If it isn't installed or isn't confident, the LLM's own JSON `tools` are used.
- **Alternatives:** the LLM alone (set `engine: "llm"`), regex intent rules, or a small classifier.

### PyTorch / ONNX Runtime
Numerical engines that run neural networks. They're used indirectly by Silero VAD, Laya, Chatterbox TTS and FastEmbed. They aren't essential to the core loop, but voice activity detection needs Silero (or the `webrtcvad` fallback).

### Microphone stack: PyAudio + Silero VAD + SpeechRecognition
> **VAD (Voice Activity Detection)**
> **Simple meaning:** a detector that says "someone is talking now" or "silence now".
> **Technical meaning:** a model that outputs a speech probability for each short audio frame. Here that's Silero VAD on 32 ms frames of 16 kHz mono audio, with `webrtcvad` as a fallback.

> **STT (Speech-to-Text)**
> **Simple meaning:** turning spoken audio into written words.
> **Technical meaning:** automatic speech recognition. Here `speech_recognition.Recognizer.recognize_google()` sends the audio to Google's free Web Speech endpoint, **which needs internet**.

- **PyAudio:** reads raw microphone samples (`mic/controller.py:36`).
- **Where:** `software/ikru/mic/`.
- **Essential?** No. `--no-mic` switches to typed input.
- **Alternatives:** Whisper / faster-whisper for offline STT, Vosk.

### OpenCV (`opencv-python`) + NumPy
- **What:** computer-vision library, plus the standard numeric array library.
- **Why here:** decoding the camera's JPEG frames, drawing the 5×5 grid overlay, showing the preview window, and re-encoding JPEGs for the VLM.
- **Where:** `vision/receiver.py`, `vision/frame_buffer.py`.
- **Essential?** Only for vision.

### SQLite (Python built-in `sqlite3`)
> **Database**
> **Simple meaning:** an organised filing cabinet for data that has to survive restarts.
> **Technical meaning:** SQLite is an embedded relational database. It's a library that reads and writes a single file (`data/memory/ikru_history.db`) using SQL, with no separate server.

- **Where:** `software/ikru/memory/database.py`.
- **Stores:** sessions, every chat message, and extracted user facts.

### Qdrant (embedded) + FastEmbed
> **Vector database / embeddings**
> **Simple meaning:** a "search by meaning" index. "I love pizza" and "my favourite food is pizza" end up close together even though the words differ.
> **Technical meaning:** each text is turned into a 384-number vector by the `BAAI/bge-small-en-v1.5` embedding model (via FastEmbed). Qdrant stores the vectors and finds the nearest ones by cosine similarity.

- **Where:** `software/ikru/memory/vector_store.py`. Runs in-process with files under `data/memory/qdrant/`.
- **Essential?** No. If it fails to load, recall returns nothing and IKRU keeps working.
- **Note:** `qdrant-client` and `fastembed` are **missing from `requirements.txt`**. Install them yourself (Part 13).

### Audio synthesis: Chatterbox TTS / Edge-TTS (optional path)
> **TTS (Text-to-Speech)**
> **Simple meaning:** turning text into spoken audio.
> **Technical meaning:** neural speech synthesis. Chatterbox (Resemble AI) runs locally and supports tags like `[sigh]`. Edge-TTS calls Microsoft's online neural voices.

- **Where:** `software/ikru/audio/service.py`. Only created when you run with `--voice-mode tts`.
- **Reality check:** the default voice mode is **`r2d2`**. The body's speaker plays **droid tones**, not words. Even in `tts` mode, the current `speak_segments()` never actually calls the TTS service (Part 17). Treat this subsystem as experimental.

### U8g2 + the "Face" library (firmware)
- **U8g2:** a popular monochrome display library that draws text and shapes on the 128×64 SSD1306 OLED.
- **Face library:** vendored into `firmware/controller/` (`Face.*`, `Eye*.*`, `*Assistant.*`, `Animations.h`). It's an open-source procedural eye animation engine by Luis Llamas, extended by Alastair Aitchison (AGPL-3.0). It animates two eyes between 18 emotion presets.

### esp_camera (head firmware)
Espressif's camera driver for the OV2640 sensor. It captures **QVGA (320×240) JPEG** frames.

### Windows networking tools: `netsh`, `ipconfig`, `wlanapi`
- **Why:** so the PC can find out which Wi-Fi it's on, see whether `IKRU-CAM` is visible, join it, and trigger scans.
- **Where:** `software/ikru/net/netinfo.py`.
- **Consequence:** bring-up and diagnosis are **Windows-specific**. On macOS/Linux these calls return empty strings and the program still runs, with less helpful diagnostics.

### pyserial
USB serial communication with the ESP32 (`net/serial_link.py`). It's used to ask the robot for its IP (`GET_IP`) or push Wi-Fi credentials when the network isn't working.

### pytest
The test runner for the offline unit tests (`tests/test_autonomous_roaming.py`, `tests/net/`, etc.). It's not listed in `requirements.txt`.

### How they relate (one sentence each)
- The **microphone stack** produces text → the **chat engine** (Ollama + memory + optional vision + Laya) produces `(tools, reply)` → the **RobotController** turns that into **WebSocket** commands → the **firmware** turns commands into **pin voltages**: motors, OLED pixels, speaker tones.
- **SQLite/Qdrant** feed context *into* the LLM prompt and receive every message *out* of it.
- **OpenCV/UDP** keep a fresh camera frame ready, which the **VLM** turns into a sentence that is injected into the LLM prompt.

---

# Part 3 — Project Directory Tree

This is the actual tree, excluding `venv/`, `__pycache__/` and large binary files. Items marked *(untracked)* exist on disk but aren't committed to git yet.

```text
PROJECT-IKRU-The-Intelligent-Kinematic-Robot-/
│
├── run.py                        ← THE entry point: python run.py
├── config.json                   ← main settings (committed)
├── config.local.json             ← secrets/overrides (git-ignored, created at runtime)
├── requirements.txt              ← Python dependencies (incomplete — see Part 13)
├── README.md                     ← original README (partly outdated — see Part 17)
├── ikru-runtime-architecture.json  ← diagram spec (untracked; documentation only)
├── scratch_test_ws.py            ← throwaway WebSocket test (hard-coded IP)
├── circuit.png, *.wav            ← wiring picture and audio test outputs (wav git-ignored)
│
├── software/
│   └── ikru/                     ← the Python package ("import ikru")
│       ├── __init__.py
│       ├── main.py               ← wires everything together; the chat loop
│       ├── config.py             ← env-var defaults (untracked, but imported!)
│       ├── connection.py         ← health state machine (untracked, currently unused)
│       ├── audio/     service.py, voices/
│       ├── autonomy/  brain.py, world_model.py, locomotion.py, search.py, hints.py, config.py
│       ├── chat/      engine.py, parser.py, prompts.py, tool_router.py
│       ├── memory/    manager.py, database.py, vector_store.py
│       ├── mic/       controller.py, vad.py
│       ├── net/       bringup.py, discovery.py, netinfo.py, serial_link.py
│       ├── robot/     controller.py, protocol.py, idle.py, proximity.py, sequences.py,
│       │              autonomous.py, world_model.py   (last two = compatibility shims)
│       └── vision/    receiver.py, frame_buffer.py, vlm.py
│
├── firmware/
│   ├── controller/               ← ESP32 BODY sketch (open controller.ino in Arduino IDE)
│   │   ├── controller.ino        ← main firmware (2,445 lines)
│   │   ├── Face.h/.cpp           ← face engine entry point; owns the u8g2 display object
│   │   ├── FaceExpression.*      ← GoTo_Happy(), GoTo_Sad(), … (18 emotions)
│   │   ├── FaceBehavior.*, FaceEmotions.hpp   ← random-emotion behaviour (disabled by IKRU)
│   │   ├── Eye.*, EyeConfig.h, EyePresets.h, EyeDrawer.h
│   │   ├── EyeTransition.*, EyeTransformation.*, EyeVariation.*, EyeBlink.*
│   │   ├── BlinkAssistant.*, LookAssistant.*, AsyncTimer.*, Animations.h, Common.h
│   └── head/
│       └── head.ino              ← ESP32-CAM HEAD sketch (AP + UDP video)
│
├── data/
│   ├── memory/
│   │   ├── ikru_history.db       ← SQLite memory (committed — contains real chat history!)
│   │   ├── qdrant/               ← vector store files
│   │   └── world_model.json      ← landmark familiarity (created at runtime)
│   └── sequences/
│       └── celebrate.json        ← example on-disk choreography (overrides the built-in)
│
├── tests/
│   ├── test_autonomous_roaming.py, test_laya_router.py      ← offline pytest suites
│   ├── test_emotion_sequences.py, test_idle_behavior.py,
│   │   test_proximity_reactions.py                          ← need a live robot
│   ├── audio/   TTS experiments, R2-D2 speaker tester, latency benchmark, ESP32 I2S sketch
│   ├── memory/  test_memory.py
│   ├── mic/     test_vad_segmenter.py (pytest), test_mic_stt.py (manual)
│   ├── net/     test_bringup.py, test_discovery.py          ← offline pytest
│   ├── robot/   test_motors.py, test_motor_diagnose.py, test_ultrasonic.py,
│   │            test_roam_calibration.py, test_robot.py, test_socket.py,
│   │            motor_drv8833/*.ino, motor_l293d/*.ino       ← standalone motor sketches
│   ├── vision/  test_udp_receiver.py (MobileNet-SSD demo), test_object_identification.py
│   └── data/memory/test_qdrant/  ← test fixture store
│
├── dump/                         ← ARCHIVED old web dashboard (does not run as-is)
│   ├── run_dashboard.py
│   └── ui/ server.py, static/{index.html, app.js, style.css}
│
├── docs/images/                  ← ESP32.jpeg, L293Dmotordriver.jpeg
├── scratch/                      ← git-ignored experiments
├── .agents/knowledge_graph.json  ← AI-assistant context file
└── .claude/settings.local.json   ← Claude Code permissions
```

---

# Part 4 — Folder-by-Folder Explanation

## `/` (repository root)

**Beginner:** the front door. `run.py` is what you run. `config.json` holds the settings you're most likely to change.

**Technical:**
- `run.py` adds `software/` to `sys.path` (the list of folders Python searches for imports) and calls `ikru.main.main()`. That's why you can run the project without installing it as a package.
- `config.json` is read once at import time by `main.py`. `config.local.json` (git-ignored) is **merged over it**, so values there win. It holds Wi-Fi credentials and adapter names.
- `requirements.txt` is a dump of an environment. It's large (Gradio, FastAPI and similar are leftovers from the dashboard) yet still **misses** some packages the code imports. See Part 13.

## `software/ikru/` — the Python brain

**Beginner:** everything the PC does. Each sub-folder is one "organ": ears (`mic`), mouth and face control (`robot`), thinking (`chat`), memory (`memory`), eyes (`vision`), free will (`autonomy`), networking (`net`).

**Technical:** a Python *package*, meaning a folder with `__init__.py`. Each sub-package re-exports its public classes in its `__init__.py`, so `main.py` can write `from ikru.robot import RobotController, IdleManager, ProximityMonitor`. Dependencies flow **downward**:

```text
main.py
  ├── chat ──────► memory,  config
  ├── autonomy ──► chat (prompts, parser), robot (via duck typing), vision (via duck typing)
  ├── robot ─────► net (discovery), config
  ├── vision, mic, memory, audio  (leaf packages; no ikru imports except audio/config paths)
  └── net ───────► (leaf)
```

> **Duck typing**
> **Simple meaning:** "if it walks like a duck…". Code uses any object that has the right methods, whatever its class.
> **Technical meaning:** `AutonomousBrain` never imports `RobotController`. It just calls `self.robot.stop()`, `self.robot.set_emotion(...)` and so on. That's what lets tests pass a `FakeRobot` (`tests/test_autonomous_roaming.py:25`).

### `software/ikru/chat/` — conversation
**Beginner:** turns what you said into what IKRU says and does.
**Technical:** `ChatEngine` keeps a sliding window of messages, adds memory/vision/sensor context, calls Ollama in JSON mode, and parses the result with `parser.py`. `prompts.py` holds the huge system prompt that defines IKRU's personality and output format. `tool_router.py` is the optional Laya decision layer.
**Imported by:** `main.py`, `autonomy/brain.py` (prompts + parser only).
**Imports:** `ollama`, `ikru.config`, sibling modules.

### `software/ikru/robot/` — the body's remote control
**Beginner:** the "remote control" for the physical robot, plus a few background habits (blinking, flinching).
**Technical:** `RobotController` is the WebSocket client with one method per firmware command. `IdleManager` and `ProximityMonitor` are daemon threads. `SequenceRunner` plays choreographies. `protocol.py` mirrors firmware timing constants. `autonomous.py` and `world_model.py` are **shims**: tiny files that re-export from `ikru.autonomy` so older imports keep working.
**Imported by:** `main.py`, tests, `dump/`.
**Imports:** `websocket`, `ikru.net`, `ikru.config`.

### `software/ikru/autonomy/` — free will
**Beginner:** what IKRU does when nobody is talking: exploring, thinking aloud, searching for things.
**Technical:** `AutonomousBrain` is a state machine thread (`resting` / `roaming` / `searching`). `WorldModel` tracks position by dead reckoning, keeps an occupancy grid and remembers landmarks. `Locomotion` provides safe motion primitives. `ObjectSearcher` implements "find X". `hints.py` and `config.py` hold prompt nudges and tuning constants.
**Imported by:** `main.py`, `robot/autonomous.py` shim, tests.

### `software/ikru/memory/` — long-term memory
**Beginner:** IKRU's diary (every message) and address book (facts about you), plus a "find similar memories" search.
**Technical:** `SQLiteStore` (relational), `QdrantMemory` (vector), and `MemoryManager` (a facade combining both, with regex fact extraction and prompt-context assembly).

> **Facade**
> **Simple meaning:** a single reception desk in front of several back offices.
> **Technical meaning:** a design pattern where one class exposes a simple API over several subsystems. The rest of the code only talks to `MemoryManager`.

### `software/ikru/vision/` — eyes
**Beginner:** receives the camera video and can ask an AI what's in the picture.
**Technical:** `VisionReceiver` (UDP reassembly thread + OpenCV window), `FrameBuffer` (thread-safe "latest frame only" slot), `VLMClient` (three prompts: describe, list objects, classify target).

### `software/ikru/mic/` — ears
**Beginner:** listens for speech and writes down what you said.
**Technical:** `MicController` runs two threads (capture+VAD, and STT). `vad.py` holds `SpeechSegmenter`, a pure state machine that's unit-tested without a microphone.

### `software/ikru/net/` — networking helpers
**Beginner:** gets the PC and robot onto the same Wi-Fi and finds each other, and explains clearly when that fails.
**Technical:** `bringup.py` (4-stage guided startup), `discovery.py` (`find_robot()` using a UDP beacon plus parallel TCP probes, returning `RobotFound` or `Diagnosis`), `netinfo.py` (Windows network introspection), `serial_link.py` (USB fallback).

### `software/ikru/audio/` — optional neural voice
**Beginner:** can make a human-sounding voice, but it isn't wired into speaking yet.
**Technical:** `AudioService` synthesises WAV with Chatterbox or Edge-TTS, and serves the cache directory over HTTP on port 8000 (`SimpleHTTPRequestHandler`) so an ESP32 with an I2S amp could stream it. `voices/` holds a reference WAV for voice cloning.

### `software/ikru/config.py` and `connection.py`
- `config.py`: module-level constants with environment-variable overrides (`IKRU_ROBOT_IP`, `IKRU_LLM_MODEL`, …). It's imported by `robot/controller.py` and `chat/engine.py` **for fallback defaults only**, because `main.py` always passes explicit values from `config.json`. ⚠️ It's untracked in git. If you commit `controller.py` without it, fresh clones will crash with `ImportError`.
- `connection.py`: a `ConnectionManager` health state machine (`DISCONNECTED → CONNECTING → READY/DEGRADED/FAILED`) for robot, camera and Ollama. **Nothing imports it yet.** It looks like groundwork for a dashboard.

## `firmware/` — code that runs on the robot

### `firmware/controller/` — the body
**Beginner:** the program living inside the robot. It listens for commands, animates the eyes, beeps, and drives the wheels.
**Technical:** an Arduino sketch folder. The Arduino IDE compiles every `.ino`, `.cpp` and `.h` in the folder together. `controller.ino` has `setup()` and `loop()`. The other files are the Face animation library. Part 6 covers it in detail.

### `firmware/head/` — the head
**Beginner:** the camera board. It also acts as the Wi-Fi router everyone connects to.
**Technical:** `head.ino` starts a soft-AP `IKRU-CAM` at `192.168.4.1` with its DHCP gateway offer disabled, waits for a UDP `IKRU_DISCOVER` on port 2223, then streams JPEG frames to whoever sent it.

> **Soft-AP (Access Point)**
> **Simple meaning:** the camera board pretends to be a Wi-Fi router.
> **Technical meaning:** the ESP32 runs in `WIFI_AP` mode, broadcasting an SSID and handing out IP addresses by DHCP.

## `data/` — things IKRU remembers
**Beginner:** IKRU's saved memories and dance moves.
**Technical:** runtime state. `memory/ikru_history.db` (SQLite), `memory/qdrant/` (vectors), `memory/world_model.json` (landmarks), `sequences/*.json` (choreographies). ⚠️ The `.db` file is committed, so personal chat history is in git. Consider git-ignoring it.

## `tests/`
**Beginner:** scripts that check things work. Some run on their own, some need the real robot.
**Technical:** mixed. There are proper pytest suites that use fakes (roaming, Laya, VAD, discovery, bring-up, motor diagnosis) and interactive hardware scripts (motors, ultrasonic, speaker, TTS). See Part 14.

## `dump/` — archived dashboard
**Beginner:** an old web control panel that's been parked. It won't start as-is.
**Technical:** `dump/run_dashboard.py` imports `ikru.ui.server`, but the `ui` package was moved to `dump/ui/`, so the import fails. `dump/ui/server.py` is an `http.server`-based API (851 lines) plus an `index.html`/`app.js`/`style.css` front end. Useful as reference if you rebuild a dashboard. `config.py`'s `STATIC_DIR` and `AudioService`'s `ui/static/audio` writes are leftovers from it.

## `scratch/`, `docs/`, `.agents/`, `.claude/`
Experiments (git-ignored), images, and AI-assistant context. They're not part of the runtime.

---

# Part 5 — Python Reference: Every Important File, Class and Function

Each entry answers: **what it does**, **who calls it**, **what it calls**, and **what to watch out for**.

## 5.1 `run.py`

| Function | What | Called by | Calls |
|---|---|---|---|
| module body | Inserts `software/` into `sys.path` | you (`python run.py`) | `ikru.main.main()` |

## 5.2 `software/ikru/main.py` — the conductor

**Beginner:** `main.py` is the orchestra conductor. It doesn't play any instrument itself. It creates every subsystem, connects them to each other, and runs the conversation loop.

**Technical:** procedural composition root.

> **Composition root**
> **Simple meaning:** the one place where all the parts get built and plugged together.
> **Technical meaning:** the entry module that instantiates objects and injects dependencies into them (dependency injection). For example, `AutonomousBrain(robot=robot, memory=memory, vision=vision, …)`.

### Module-level code (runs on import)
| Name | Line | Purpose |
|---|---|---|
| UTF-8 reconfigure | 10 | Stops emoji `print`s crashing on Windows consoles |
| `CONFIG_FILE`, `CONFIG_LOCAL_FILE` | 36–38 | Paths to `config.json` / `config.local.json` at repo root |
| `_load_json(path)` | 41 | Returns `{}` if missing or invalid, never raises |
| `_save_config(path=CONFIG_FILE, **updates)` | 52 | Read-modify-write **one** file, so secrets only ever go to `config.local.json`. Also updates the in-memory `config_data` |
| `config_data` | 66 | `{**config.json, **config.local.json}` (local wins) |
| `ROBOT_IP … TOOL_ROUTER_CONFIG` | 68–85 | Settings pulled from `config_data` with defaults |
| `VISUAL_PATTERN` | 88 | Regex. If the user's words match (e.g. "what do you see", "shirt", "holding"), the camera + VLM are consulted |
| `EXIT_PHRASES`, `_is_exit(text)` | 96–104 | Substring match. ⚠️ "later", "sleep" and "see you" anywhere in a sentence end the program ("I'll do it later" quits!) |

### Helper functions
| Function | Line | What it does | Called by |
|---|---|---|---|
| `_print_diagnosis(diag)` | 111 | Pretty-prints a `Diagnosis` (why the robot wasn't found + hints) | `_connection_wizard` |
| `_prompt_wifi_credentials()` | 121 | Asks for SSID/password (`getpass` hides the password), rejects `:` in the SSID because it's the protocol separator, saves to `config.local.json` | `_usb_serial_menu`, `_provision_wifi_over_ws` |
| `_usb_serial_menu(robot)` | 146 | `serial_link.query_ip()`. If a STA IP comes back, puts it first in `robot.extra_hosts`. Optionally `serial_link.send_wifi()` | `_connection_wizard` (choice `u`) |
| `_connection_wizard(robot, interactive)` | 173 | Loop: show diagnosis → `[r]etry [m]anual IP [u]sb [c]ontinue`. Non-interactive returns immediately | `main()` step 2 |
| `_provision_wifi_over_ws(robot)` | 203 | Sends `SET_WIFI:<ssid>:<pass>` over WebSocket, drops the link, waits 15 s, reconnects | `main()` if `--provision-wifi` |
| `_remember_robot_ip(ip)` | 219 | Persists `robot_last_ip` to `config.json` | `_on_robot_connect` callback |

### `main()` — line 224
Covered step by step in Part 7. Its sections:
1. **argparse** flags: `--ip`, `--cam-ip`, `--volume`, `--pc-audio`, `--voice-mode {r2d2,tts}`, `--tts-engine`, `--voice`, `--voice-prompt`, `--lang`, `--no-mic`, `--no-vision`, `--no-wizard`, `--provision-wifi`.
2. `Bringup(...).run_network()` → create `RobotController(connect_now=False)` → `bringup.link_body(robot)`.
3. Wizard, then optional provisioning.
4. Build `MemoryManager`, `ChatEngine` (warm-up thread), optional `LayaToolRouter` (warm-up thread) + a 1-worker `ThreadPoolExecutor`, optional `AudioService`, `IdleManager`, `ProximityMonitor`, obstacle brake, `MicController`, `VisionReceiver` + `VLMClient`, `AutonomousBrain`.
5. Mic callbacks `on_text` / `on_speech_start`, and a `busy` Event + `busy_until` echo guard.
6. `bringup.finish()`, `robot.setup_done()`, greeting.
7. `chat_loop()` (nested function, line 483) runs in a thread. The main thread pumps `vision.update_display()`.
8. `finally:` shutdown of everything.

### `chat_loop()` — line 483 (the heart of the program)
Covered in detail in Part 8. The inner helpers:
- `run_immediate(decision)` (534): if Laya flagged a decision as `immediate` (stop / cancel_search), executes it **right now** on the Laya worker thread and records it in `executed_now` so it isn't run twice.
- `laya_decide()` (546): `tool_router.decide(user_input)` → print → `run_immediate`.
- `play_filler()` (561): after 10 s of thinking, plays a pre-generated "Hmm, let me think" audio URL (TTS mode only).

## 5.3 `software/ikru/chat/engine.py` — `ChatEngine`

**Beginner:** the part that actually "talks to the AI". It remembers the last few exchanges, adds useful background notes, sends everything to the model, and turns the answer into something the robot can perform.

| Method | Line | What it does | Called by | Calls |
|---|---|---|---|---|
| `__init__(model, memory, keep_alive)` | 17 | Stores the model name. History starts as `[system prompt]`. `_messages_lock` protects it | `main()` | — |
| `warm_up()` | 30 | `ollama.generate(prompt="")` to load the model into memory early | thread from `main()` | Ollama |
| `clear_history()` | 38 | Reset to only the system prompt | nothing currently | — |
| `note_autonomous_utterance(text, tools)` | 48 | Appends something IKRU said on its own as an `assistant` message, so if the user answers IKRU's question, the reply has context | `AutonomousBrain._deliver` | — |
| **`ask(user_input, visual_context, sensor_context, action_context)`** | 61 | The main call. Returns `(tools, response_text, segments)` | `chat_loop` | `memory.build_memory_context`, `memory.record_*`, `ollama.chat`, `parse_llm_json`, `parse_segments` |
| `ask_stream(...)` | 165 | Generator for token-by-token streaming with sentence splitting | **nothing** (only the latency benchmark test) | Ollama streaming, `StreamSentenceParser` |

**How `ask()` builds the prompt** (lines 70–116):

```text
[Recalled Long-Term Memories: …]          ← from Qdrant (if any)
[Known User Facts: …]                     ← from SQLite
[Camera Visual Observation: …]            ← only for visual questions
[Proximity Sensor: Path clear (43.0 cm)]  ← always (from ProximityMonitor)
[Action System: your body is performing this action: move forward for 3 seconds. …]  ← Laya, sequential mode only
User: move forward for 3 seconds
```

This whole block becomes one `user` message. The window is trimmed to `system + last 10 messages` **before** appending, so the model sees at most system + 11 messages.

**Failure handling:** JSON call fails → retry without `format="json"` → if that fails too, return a canned sad line. Memory errors only print warnings.

> **Sliding window**
> **Simple meaning:** only the last few exchanges are kept "in mind", like short-term memory.
> **Technical meaning:** the `messages` list is capped so the prompt fits the model's context length and stays fast. Older turns survive only through SQLite/Qdrant long-term memory.

## 5.4 `software/ikru/chat/parser.py`

| Name | Line | What it does |
|---|---|---|
| `OLED_EMOTIONS`, `EMOTION_REGEX` | 5–11 | The 18 face names, and a regex that finds `[happy]`-style tags |
| `VOCAL_TO_OLED` | 14 | Maps sound tags to a face when no face tag was given (`[laugh]`→glee, `[sigh]`→worried, …) |
| **`parse_segments(text)`** | 27 | Splits `"[happy]Hi! [sad]But…"` into `[("happy","Hi!"), ("sad","But…")]`. Text before the first tag becomes `normal`. `normal` segments are then **re-guessed** from vocal tags or keywords, and fall back to `happy` |
| **`parse_llm_json(raw_text)`** | 84 | Strips code fences, `json.loads`, returns `(tools, response_text)`. Handles a legacy `"tool": "forward"` field and a stray top-level `"emotion"` field. **On invalid JSON returns `([], raw_text)`**, so IKRU still says *something* |
| `StreamSentenceParser` | 123 | Buffers streamed tokens and emits a sentence at `. ! ? ; \n` when outside `[...]`. Only used by `ask_stream` |

Called by: `ChatEngine`, `AutonomousBrain` (`_query_llm`, `_make_thought`).

## 5.5 `software/ikru/chat/prompts.py`

Two big strings:
- `SYSTEM_PROMPT`: IKRU's identity, vocal sound tags (`[sigh]`, `[giggle]`, …), how to treat `[Camera Visual Observation]`, `[Proximity Sensor]`, `[Action System]`, `[Recalled Long-Term Memories]`, the list of movement tools and sequences, the 18 allowed emotions, and the **mandatory JSON output format** `{"tools": [...], "response": "[emotion]text"}` with examples.
- `AUTONOMOUS_ADDENDUM`: extra rules for self-generated thoughts (one short sentence, never greet, movement ≤ 0.6 s, don't read out the `[World Model: …]`).

**The prompt is the contract.** If you add a tool, emotion or context tag, you must teach the model about it here. Otherwise it will never use it.

## 5.6 `software/ikru/chat/tool_router.py` — Laya decision layer

**Beginner:** a quick "reflex" brain. While the big language model is still composing its sentence, this small model answers "is this a stop command? a move? a search?" in a fraction of a second.

| Name | Line | What it does |
|---|---|---|
| `INTENT_LABELS`, `DIRECTIONS`, `PERFORMANCES`, `SEQUENCES` | 32–62 | The answer options shown to Laya |
| `IMMEDIATE_INTENTS` | 65 | `{"stop", "cancel_search"}`: run the moment Laya answers |
| `DEFAULT_DURATIONS` | 67 | forward/backward 1 s, turns 0.5 s when no duration was spoken |
| `extract_duration(text)` | 86 | Regex: "3 seconds", "half a second", "500 ms" → float, clamped 0–30 |
| `extract_search_target(text)` | 103 | Regex: "find my coffee mug please" → `"coffee mug"` |
| `ToolDecision` | 112 | Result object: `intent, confidence, tools, action_text, needs_target, needs_duration_from_llm, immediate` |
| `ToolDecision.context_line()` | 125 | Produces the `[Action System: …]` hint for the LLM |
| `LayaToolRouter.warm_up()` | 158 | `import laya; laya.load(...)`, then a dummy predict. On failure prints "Unavailable" and stays unavailable |
| `LayaToolRouter.available` | 178 | True once loaded |
| `LayaToolRouter.decide(user_text)` | 213 | Stage 1: intent question. If intent is move/perform, stage 2: direction/performance + "multi-step?". Returns `None` (defer to the LLM) when confidence < `min_confidence` (0.8), multi-step, or "just talking" (unless `veto`) |
| `merge_tool_calls(decision, llm_tools, skip_actions)` | 302 | Final tool list: Laya's tools, with missing duration/target borrowed from the LLM's tools, minus actions already run immediately |

**Two modes** (`config.json → tool_router.mode`):
- `parallel` (default): Laya and the LLM run at the same time, and the LLM is **not** told the action.
- `sequential`: Laya first, then the LLM gets an `[Action System: …]` line so its words match the movement. This is slower.

## 5.7 `software/ikru/robot/controller.py` — `RobotController`

**Beginner:** a TV remote for the robot. Every button (method) sends one short text command over Wi-Fi.

**Technical:** a thread-safe WebSocket client with auto-discovery, heartbeat and auto-reconnect.

| Method | Line | Sends / does | Called by |
|---|---|---|---|
| `__init__(ip, port=81, …, extra_hosts, on_connect, connect_now)` | 18 | Stores settings. Optionally connects. **Always starts `_heartbeat_loop` thread** | `main()`, tests |
| `_connect(silent)` | 53 | `find_robot([ip]+extra_hosts)` → `websocket.create_connection(ws://ip:81, ping_interval=5, ping_timeout=3)`. Calls `on_connect(ip)` | `connect()`, heartbeat, bring-up, wizard |
| `_handle_disconnect()` | 94 | Closes the socket, `connected=False` | send errors, heartbeat, provisioning |
| `_heartbeat_loop()` | 104 | Connected: `ws.ping()` every 5 s. Disconnected: retry with backoff 5→10→20→30 s | own thread |
| **`send(cmd)`** | 128 | `ws.send(cmd)` under `_lock`. **Silently does nothing when disconnected** | everything |
| `forward(duration, check_proximity=True)` | 141 | `FORWARD`, then in 0.1 s chunks watches `proximity_monitor.get_distance()`. If < 12 cm: STOP, worried face, wait until ≥ 14 cm, resume. Ends with `STOP` | chat loop, locomotion, sequences |
| `backward/left/right(duration)` | 173–189 | Send the command, `sleep(duration)`, `STOP` (if duration > 0) | same |
| `stop()` | 191 | `STOP` | everywhere |
| `dance()`, `sing()` | 194–198 | `DANCE`, `SING` — ⚠️ **firmware has no handler** (logs "Unknown Command") | LLM tools |
| `spin_left/right`, `wiggle` | 200–211 | Composites of left/right | sequences |
| `play_sequence(name_or_list)` | 213 | Creates a `SequenceRunner` and plays it | chat loop, brain |
| `get_distance(timeout)` | 220 | Sends `GET_DISTANCE`, then reads replies until one is `{"type":"distance"}`. Returns cm or −1.0. **Holds `_lock` while waiting** | `ProximityMonitor`, `Locomotion` fallback |
| `set_speed(pct)` | 255 | `SPEED:<30-100>` | `Locomotion.set_speed` |
| `set_obstacle_threshold(cm)`, `enable/disable_obstacle_brake()` | 259–269 | Firmware safety brake config | `main()` |
| `display(text)` | 272 | `DISPLAY:<text>`: opens the speech box and scrolls text | `speak_segments`, sequences |
| `display_open/close()` | 275–281 | `DISPLAY_OPEN/CLOSE` + 0.35 s wait | not used by main loop |
| `play_audio(url)` | 283 | `SPEAK_URL:<url>` or `SOUND:<name>`. ⚠️ firmware ignores `SPEAK_URL` | filler playback |
| `play_sound(name, intensity)` | 291 | `SOUND:<name>:<0.00-1.00>` | `speak_segments`, sequences |
| `stop_audio()` | 296 | `STOP_AUDIO` | interruptions |
| `set_volume(v)` | 300 | `VOLUME:<0-100>` (firmware only logs it) | `main()` |
| **`speak_segments(segments, audio_service, …, interrupt_event)`** | 306 | For each `(emotion, text)`: if the text has a sound tag like `[sigh]`, call that method (face + sound), else `set_emotion(emotion)`. Then `DISPLAY:<clean text>` and **sleep for the computed scroll time** (in 0.1 s chunks so it can be interrupted). Ends with `NORMAL` | chat loop, greeting, brain |
| `set_emotion(e)` / `set_face(e)` | 384 / 450 | `getattr(self, e)()`. Unknown names → `happy()` | many |
| 18 emotion methods `normal()`…`awe()` | 391–408 | Send `HAPPY`, `SAD`, … (firmware changes the face **and** plays a matching chirp) | |
| `blink()`, `look_at(x,y)`, `look_left/right/front/top/bottom()` | 411–417 | Eye control | idle, locomotion |
| `yawn()` | 420 | sleepy + exhale + 1.2 s + normal | `IdleManager` |
| vocal sounds `sigh()`…`error()` | 429–447 | `SIGH`, `GASP`, `GIGGLE`, … | `speak_segments` via tags |
| `connect(silent)` | 456 | Public wrapper around `_connect` | bring-up, wizard |
| `setup_status(text)` | 460 | `SETUP:<≤20 chars>` shown on the robot's boot screen | `main()` |
| `setup_done()` | 464 | `SETUP_DONE` ends the boot screen, and the face appears | `main()`, reconnect callback |
| `close()` | 468 | Stops heartbeat and reconnect, closes the socket | shutdown |

> **Lock (mutex)**
> **Simple meaning:** a "talking stick". Only the thread holding it may use the shared thing.
> **Technical meaning:** `threading.Lock`. Here `_lock` stops two threads writing to the WebSocket at once, which would corrupt frames.

⚠️ **Side effect worth knowing:** `ProximityMonitor` calls `get_distance()` every 0.25 s and holds `_lock` for up to 0.6 s. Any `send()` from another thread (like a face change) waits for it. That's normally a few milliseconds, but it's the first thing to suspect if commands feel laggy.

## 5.8 `software/ikru/robot/protocol.py`

`ALL_EMOTIONS`, `ALL_MOVEMENTS`, and the scroll-timing constants copied from the firmware. `calculate_speech_scroll_time(text)` = `0.6 + (64 + ceil(len/8)*18) * 0.030 + 0.4` seconds. That's an estimate of how long the OLED takes to scroll the text, so Python waits the right amount before the next segment. **If you change `SCROLL_SPEED`, `START_PAUSE` etc. in the firmware, change them here too.**

## 5.9 `software/ikru/robot/idle.py` — `IdleManager`

**Beginner:** makes IKRU fidget like a living thing: blinks, eye drifts, occasional yawns.

- `start()` / `stop()`: daemon thread `_idle_loop`, ticking every 0.3 s.
- `notify_activity()`: sets `paused=True`. Called when speech starts or a turn begins, or when the autonomous brain takes the stage.
- `notify_speech_done()`: unpauses and resets the 3 s idle countdown.
- The loop: blink every 3.5–6.5 s (15% chance of a double blink), gaze drift every 4.5–9 s, micro-expression every 25–45 s (yawn 40%, curious glance 30%, soft whisper chirp 30%).

## 5.10 `software/ikru/robot/proximity.py` — `ProximityMonitor`

**Beginner:** IKRU's sense of personal space. It keeps checking the distance sensor and flinches if something gets too close.

| Method | What |
|---|---|
| `start/stop()` | Poll thread (`poll_interval=0.25` s) |
| `pause/resume()` | Suppress **reflexes** while busy. Polling continues so the LLM always gets fresh distance |
| `get_distance()`, `get_zone()` | Latest cached values (cheap, no network) |
| `get_sensor_context()` | `"[Proximity Sensor: …]"` string for the LLM |
| `_monitor_loop()` | Zones: **DANGER** < 10 cm → stop, scared, gasp, back up 0.4 s, worried (max once per 2 s). **CAUTION** 10–30 cm (entered from CLEAR) → surprised glance + whisper (max once per 3.5 s). **CLEAR** otherwise |

Note that a sensor timeout returns `-1`, and the firmware reports `999` for "nothing". Both count as CLEAR.

## 5.11 `software/ikru/robot/sequences.py` — `SequenceRunner`

**Beginner:** a choreography player. A sequence is a list of steps. Each step says which face, which sound, which wheel move, and for how long.

- `BUILTIN_SEQUENCES`: `celebrate, happy_dance, confused_wiggle, scared_retreat, victory_twirl, curious_scan, disapproval_shake`.
- `load_sequence(name)`: **`data/sequences/<name>.json` wins over the built-in** of the same name.
- `play_sequence(name_or_list)`: for each step, set emotion → `look_at(gaze)` → `play_sound(sound, sound_intensity)` → optional `display(display_text)` → movement (`left/right/forward/backward/spin_left/spin_right/wiggle` for `duration`, otherwise stop and wait `duration`). Always finishes with stop + normal + look front.

Step format:
```json
{"emotion": "glee", "sound": "laughter", "sound_intensity": 0.5,
 "movement": "spin_left", "duration": 0.6, "gaze": [0.0, 0.2], "display_text": "Yay!"}
```

## 5.12 `software/ikru/autonomy/` — the autonomous brain

### `config.py`
`DEFAULT_CONFIG` holds user-overridable settings (merged with `config.json → autonomous`) plus module constants (energy rates, thresholds, probabilities). **Calibrate `forward_cm_per_s` and `turn_deg_per_s` with `tests/robot/test_roam_calibration.py`.** Dead reckoning depends entirely on them.

### `hints.py`
"Mode hints" are one-line nudges put into the LLM prompt ("Ask a random curious question…"). The LLM writes the actual words.

### `brain.py` — `AutonomousBrain`

**Beginner:** IKRU's inner life. When nobody is talking it either **rests** (recharging "energy", sometimes thinking aloud) or goes on an **excursion** (short scoots around the desk). When asked to find something, it **searches**. The moment a human talks, it freezes and listens.

State machine:

```text
                 user asks "find X"
   ┌──────────┐  ────────────────────►  ┌───────────┐
   │ resting  │                          │ searching │──found / gave up / cancelled──┐
   │ (energy↑)│◄─────────────────────────└───────────┘                               │
   └────┬─────┘◄──────────────────────────────────────────────────────────────────────┘
        │ energy ≥ 0.5 AND quiet ≥ 30 s AND timer due AND roam_enabled
        ▼
   ┌──────────┐  user speaks / search requested → stop at once
   │ roaming  │  timer over / energy < 0.2 ("tired") / 90% explored ("bored") → wind down & go home
   │ (energy↓)│
   └──────────┘
```

| Method | Line | What it does |
|---|---|---|
| `start/stop()` | 122/136 | Thread `_loop`. `stop` also shuts the thought worker down and saves the world model |
| `pause()/resume()` | 144/151 | Called by `chat_loop` around every user turn. `pause` sets `_interrupt` so motion/speech stops quickly |
| `attention(hold_s=8)` | 157 | Called when the mic hears a voice: stay still for 8 s |
| `is_vocalizing()` | 164 | True while IKRU's own chirps are playing, plus a 1.2 s echo guard, so the mic doesn't treat IKRU's beeps as a human |
| `start_search(target)` | 172 | Queues a `SearchTask` (needs camera + VLM). Returns False otherwise |
| `cancel_search()`, `is_searching()` | 186/196 | |
| `_should_yield()` | 206 | True if stopped, paused, holding attention, or robot disconnected |
| `_loop()` | 220 | 25 s quiet start, then every 0.5 s: recharge energy → search if queued → excursion if due → otherwise resting thought (every 60–180 s) |
| `_build_trigger(...)` | 329 | Assembles memory + vision + proximity + `world.summary()` + recent thoughts + `[INTERNAL SIGNAL — AUTONOMOUS MODE]` |
| `_query_llm(trigger)` | 367 | **Separate** `ollama.chat` with `SYSTEM_PROMPT + AUTONOMOUS_ADDENDUM`. Doesn't touch ChatEngine history |
| `_compose(...)`, `_compose_observation(jpeg)` | 384/404 | Build a "thought" dict. The observation variant first asks the VLM to list objects and diff them against the world model (new / missing / familiar) |
| `note_external_motion(action, duration)` | 445 | Keeps dead reckoning in sync with user-commanded moves. **A duration of 0 (untimed move) resets home** |
| `_execute_tool_safely(tool)` | 480 | Autonomy may only run safe sequences and ≤ 0.6 s moves, and forward is blocked if < 20 cm |
| `_take_stage()/_release_stage()` | 522/528 | Pause/resume idle + proximity reflexes around autonomous speech |
| `_deliver(thought)` | 538 | Speak it (interruptible), run tools, remember it in memory and in the ChatEngine window |
| `_say(text)` | 586 | Scripted line, no LLM (used by search) |
| `_act()` | 594 | One resting thought |
| `_run_search()` | 619 | Runs `ObjectSearcher.run`. Resumes later if interrupted (status stays `active`) |
| `_excursion()` / `_roam_step()` / `_wind_down()` | 716/675/787 | The roaming loop. Thoughts are composed on a **1-worker thread pool** so the wheels keep moving while the LLM thinks. Thoughts older than 25–45 s are dropped as stale |

### `world_model.py` — `WorldModel`

**Beginner:** IKRU's rough mental map. It guesses where it is by counting how long it drove ("I went forward 1 second at 25 cm/s, so I'm 25 cm ahead"), marks spots where the sensor saw something, and remembers objects the camera identified.

> **Dead reckoning**
> **Simple meaning:** estimating your position from speed × time, like walking with your eyes closed and counting steps.
> **Technical meaning:** integrating commanded velocities into a pose `(x, y, heading)` without external positioning. Errors accumulate, which is why IKRU returns "home" after each excursion.

> **Occupancy grid**
> **Simple meaning:** a checkerboard map where each square is marked "free", "blocked" or "unknown".
> **Technical meaning:** a dict `(i, j) → {"occ": float, "visits": int}` over 10 cm cells. Each sonar reading lowers `occ` along the free ray (−0.35) and raises it at the hit (+0.7), clamped to ±2. A cell with `occ > 0.5` counts as blocked.

| Method | What |
|---|---|
| `apply_forward(cm)`, `apply_turn(deg)` | Update the pose (left turn = positive heading) |
| `reset_home()` | Current spot becomes (0,0,0), grid cleared |
| `predict_range()` | Distance to the first blocked cell straight ahead |
| `observe_range(cm)` | Integrate a sonar reading. Returns a **surprise**: `new_obstacle` (something appeared where it was open) or `obstacle_gone`, with a 15 s cooldown |
| `choose_turn(step_cm)` | Scores 10 candidate headings: prefer unexplored, unblocked, inside the leash (35 cm), gentle turns, plus randomness. Outside the leash → head home |
| `distance_from_home()`, `bearing_to_home()`, `bearing_to(x,y)`, `point_ahead(d)` | Geometry helpers |
| `explored_fraction()` | Share of leash-disc cells visited |
| `observe_objects(labels, scene)` | Landmark bookkeeping → `{"new","familiar","again","missing"}` |
| `summary()` | The `[World Model: …]` sentence for the LLM |
| `load()/save()` | `data/memory/world_model.json`. Only **familiarity** persists (positions are meaningless next session). Saved atomically via a `.tmp` file + `os.replace` |

Free functions: `labels_match(a,b)` (loose word overlap, ignoring colours/sizes/articles), `clean_label`, `describe_direction`.

### `locomotion.py` — `Locomotion`

Safe motion primitives. Every one checks `should_yield()` and updates the world model.

| Method | What |
|---|---|
| `wait(s)` | Sleep in 50 ms chunks. Returns False if it should yield |
| `express(emotion)` | Echo-guard + `set_emotion` |
| `read_distance()` | From `ProximityMonitor` cache (or a direct `get_distance`) |
| `sense()` | Read + `world.observe_range` → `(cm, surprise)` |
| `turn(deg)` | Look toward the turn, `left/right(duration)`, update heading |
| `drive_burst(duration)` | Raw `FORWARD`. Stops when < `roam_stop_cm` (25) or yielding. Updates position |
| `look_around()` | Glance left/right |
| `explore_step(preferred_turn)` | `choose_turn` → turn → burst 0.25–0.5 s |
| `go_home(max_steps=12)` | Steer back to (0,0) |

### `search.py` — `SearchTask`, `ObjectSearcher`

**Beginner:** "find my mug" mode. IKRU wanders. Every time the distance sensor bumps into something, it stops, takes a photo, and asks the vision model "is this the mug?". If it isn't, IKRU says so, remembers that spot, and turns away.

- `SearchTask`: target, deadline (`search_timeout_s`=180), status (`active|found|gave_up|cancelled`), list of already-checked positions (15 cm radius).
- `classify_obstacle(vlm, jpeg, target)`: prefers `vlm.classify_target`, falling back to `list_objects` + `labels_match`.
- `ObjectSearcher.run(task)`: the loop described above. Speaks scripted lines (`FOUND_LINES`, `NOT_IT_LINES`, `GIVE_UP_LINES`). Match needs `match==true` **and** `confidence ≥ 0.6`. It first heads toward where the world model last saw the target, if known.

## 5.13 `software/ikru/memory/`

### `database.py` — `SQLiteStore`
- A new SQLite connection per call (safe across threads) with `PRAGMA journal_mode=WAL` (better concurrent reads), plus a Python lock.
- Creates a **new session row on every startup**.
- Methods: `save_message`, `get_recent_messages`, `get_session_messages`, `get_message_count`, `save_fact` (upsert on unique text), `get_all_facts`, `get_facts_by_category`, `clear_all`, `get_stats`.
- Schema: Part 11.

### `vector_store.py` — `QdrantMemory`
- `__init__` starts `_lazy_init` in a background thread: opens the embedded Qdrant at `storage_path`, creates collection `ikru_longterm_memory` (384-dim, cosine) if needed, loads FastEmbed. The first run downloads the embedding model.
- `_wait_ready(timeout=30)`: joins the init thread. ⚠️ The first `ask()` can block for up to 30 s while this finishes.
- `add_memory(text, metadata)`, `search_memories(query, top_k, score_threshold)`, `get_count`, `clear_all`.

### `manager.py` — `MemoryManager`
| Method | What | Called by |
|---|---|---|
| `record_user_message(text, visual_context)` | SQLite insert, then **background threads** for vector indexing and fact extraction | `ChatEngine.ask` |
| `record_assistant_message(text, tools_used)` | SQLite insert + background indexing | `ChatEngine.ask`, `AutonomousBrain._deliver` |
| `_extract_facts(text)` | Runs `FACT_PATTERNS` regexes: name, age, city, likes/dislikes, favourites, job, pets, "remember that…" | background thread |
| `build_memory_context(query, top_k=3, score_threshold=0.55)` | Qdrant recall + up to 10 facts → `[Recalled Long-Term Memories: …]` / `[Known User Facts: …]` | `ChatEngine.ask`, brain |
| `get_stats()`, `clear_all()`, `save_explicit_fact()` | | `main()` / tools |

⚠️ `config.json → memory.recall_top_k / recall_threshold` are **not passed through**. The defaults (3, 0.55) in `build_memory_context` are what's used.

## 5.14 `software/ikru/vision/`

### `receiver.py` — `VisionReceiver`
- `start()` → `_worker` thread: bind UDP `0.0.0.0:2222` with a 4 MB receive buffer, and send `IKRU_DISCOVER` to `cam_ip:2223` every 2 s (the head only streams to whoever last said hello).
- Packet handling: unpack the 22-byte header `<HBBIHHIHI` (magic `0x494B` "IK", version 1, type, frameId, chunkId, totalChunks, frameLength, chunkLength, timestamp), drop stale frames, collect chunks in a dict. When all chunks are present, verify the JPEG start/end markers (`FF D8` … `FF D9`), `cv2.imdecode`, **draw a white 5×5 grid** (the VLM uses it to estimate distance), then `buffer.set_frame`.
- Incomplete frames are dropped after 150 ms. Video favours freshness over completeness.
- `update_display()`: `cv2.imshow("IKRU EYES (UDP)")`. **Must run on the main thread**, which is why `main()` keeps the main thread for it. Pressing Esc stops vision.

### `frame_buffer.py` — `FrameBuffer`
One-slot, lock-protected "latest frame". `get_jpeg_bytes(quality=85)` re-encodes for the VLM.

### `vlm.py` — `VLMClient`
| Method | Prompt | Returns | Used by |
|---|---|---|---|
| `describe_scene(jpeg)` | 1–2 sentences + distance estimate using the grid | `str` or None | chat loop (visual questions), resting thoughts |
| `list_objects(jpeg)` | JSON `{"scene", "objects":[≤5]}` | dict or None | roaming observations |
| `classify_target(jpeg, target)` | JSON `{"what","match","confidence"}` | dict or None | object search |

## 5.15 `software/ikru/mic/`

### `vad.py`
- Constants: 16 kHz, 512-sample frames (32 ms).
- `SpeechSegmenter.process(frame, prob)` → events `("start", None)`, `("end", pcm_bytes)`, `("drop", None)`. It needs 2 consecutive speech frames to start, keeps 300 ms of pre-roll, ends after `silence_ms` (500 ms) below `threshold-0.15` (hysteresis), drops utterances with < 250 ms voiced, and force-cuts at 12 s.
- `load_vad(kind)`: Silero ONNX, or the `webrtcvad` fallback (⚠️ `webrtcvad` isn't in requirements).

> **Hysteresis**
> **Simple meaning:** needing a clearly different signal to switch back, so the detector doesn't flicker.
> **Technical meaning:** separate on/off thresholds (0.5 to start speech, below 0.35 to count as silence).

### `controller.py` — `MicController`
- `__init__(**config.json mic)`: loads the VAD, opens PyAudio.
- `start_background_listening(on_text, on_speech_start)`: **two threads**. `capture_loop` reads frames → segmenter → on `start` call `on_speech_start()`, on `end` queue the PCM. `stt_loop` → `recognize_google` → `on_text(text, t_end)`. Returns a `stop()` function.
- `listen()`: blocking single-utterance variant (unused by `main`).

## 5.16 `software/ikru/net/`

### `netinfo.py`
Constants: `HUB_SSID="IKRU-CAM"`, `HUB_PASSWORD="ikru@potato"`, `HUB_SUBNET=192.168.4.0/24`, `CAM_IP=192.168.4.1`, `HUB_ROBOT_IP=192.168.4.200`.
Functions: `pc_ssid`, `pc_ipv4s`, `visible_ssids`, `is_ip`, `same_subnet`, `on_hub`, `check_tcp_port`, `wifi_interfaces` / `parse_wlan_interfaces`, `parse_ipconfig`, `adapter_info`, `hub_ip_of`, `ssid_visible`, `request_scan` (Windows `wlanapi.WlanScan` via ctypes), `ensure_hub_profile` / `connect_hub` (installs a WPA2 profile and `netsh wlan connect`), `has_internet`, `fix_hub_route_command`, `run_elevated` (UAC PowerShell).

### `discovery.py`
- `RobotFound(ip, method, ssid, rssi)`, `Diagnosis(reason, message, hints)`.
- `find_robot(hint_hosts, port=81, timeout=3.0)`: starts `_BeaconListener` (UDP 4210) **and** parallel TCP probes of `hints + ["192.168.4.200", "ikru-robot.local"]`. The first confirmed success wins (hint order is respected). On failure → `diagnose()`.
- `diagnose()` classifies the failure: `port_blocked` (beacon heard but port closed → firewall), `hub_missing`, `isolation` (same subnet, no reply → guest network), `wrong_network`, `robot_missing`.

### `bringup.py`
- `pick_adapters(interfaces, internet_pref, hub_pref)`: with 2+ Wi-Fi adapters, one keeps the home internet and the other joins IKRU-CAM. With 1 adapter, both roles share it (and joining the hub costs internet, so voice STT won't work).
- `Bringup.run_network()` = stage 1 (PC network) → 2 (wait for `IKRU-CAM` to appear, forcing scans every 4 s, up to 180 s) → 3 (join the hub, get a 192.168.4.x IP, start `PcAnnouncer`, check internet still works, offer the metric fix).
- `Bringup.link_body(robot)` = stage 4 (retry `robot.connect` up to 60 s, then `SETUP:PC linked`).
- `PcAnnouncer`: sends `IKRU-PC|<pc_ip>` to the body and broadcast every second on UDP 4211, so the body's boot screen shows "PC here".
- Ctrl+C during any wait **skips that stage** instead of quitting.
- Optional `config.json → bringup: {power_on_timeout_s, join_timeout_s, body_timeout_s}`.

### `serial_link.py`
`list_ports()`, `query_ip()` (writes `GET_IP\n` to every COM port, parses `IP:… SSID:… MODE:…`), `send_wifi(ssid, pass)`. It opens ports with DTR/RTS low so the ESP32 isn't reset.

## 5.17 `software/ikru/audio/service.py` — `AudioService` (experimental)
- Starts an HTTP file server on port 8000 serving `cache_dir` (`software/ikru/audio/cache`).
- `synthesize(text)`: `_clean_text_for_tts` (normalise "IKRU"→"Ikru", strip face tags, map sound tags to Chatterbox tokens) → Chatterbox (local neural) or Edge-TTS (online) → resample to 44.1 kHz stereo → write `ikru_chunk_<ms>.wav` (also into `ui/static/audio`) → optionally play on the PC with `winsound`. Returns `/audio/<name>` (a relative path that doesn't match the served directory layout).
- `pregenerate_fillers()` / `get_random_filler()`: filler phrase URLs. ⚠️ `synthesize` writes to a timestamped chunk name, not `filler_N.wav`, so the filler files are never actually created, and the robot firmware ignores `SPEAK_URL` anyway.

---

# Part 6 — Firmware Deep Dive (the C++ that runs on the robot)

## 6.1 How an Arduino program runs

**Beginner:** an Arduino program has two functions. `setup()` runs once when the board powers on. `loop()` then runs forever, thousands of times a second. There are no threads in this sketch. Everything has to be **non-blocking**: each piece of work does a little bit and returns, so the other pieces also get a turn.

**Technical:** the ESP32 Arduino core runs `loop()` inside a FreeRTOS task. Long `delay()` calls starve Wi-Fi and trip the watchdog, so the body firmware uses **time-sliced state machines** based on `millis()` (animation, sonar every 60 ms, sound sequencer, scroll every 30 ms) and a `delay(5)` yield.

> **State machine**
> **Simple meaning:** something that is always in exactly one "mode", with clear rules for switching modes.
> **Technical meaning:** a set of states plus transition conditions. Examples here: `SetupStage` (BOOT → HUB → JOINED → WAIT_PC → LINK → READY → DONE), `OLEDMode` (IDLE/SPEAKING/WAITING), and `SonicPlayer` (IDLE/PLAYING_NOTE/PLAYING_PAUSE).

## 6.2 Body hardware map (`firmware/controller/controller.ino`)

| Function | GPIO | Notes |
|---|---|---|
| DRV8833 IN1 / IN2 (left motor) | 26 / 27 | 20 kHz, 8-bit PWM via `ledcAttach` |
| DRV8833 IN3 / IN4 (right motor) | 14 / 12 | ⚠️ GPIO12 is a strapping pin. If the board won't boot, check it isn't pulled high at reset |
| DRV8833 EEP / nSLEEP | 13 (and 33 alt) | HIGH = driver awake |
| DRV8833 ULT / nFAULT | 32 | LOW = fault → `{"event":"motor_fault"}` broadcast |
| HC-SR04 TRIG / ECHO | 18 / 19 | Use a 3.3 V-safe sensor (HC-SR04P) or a divider on ECHO |
| OLED SDA / SCL | 21 / 22 | SSD1306 128×64 at I2C 0x3C |
| Speaker (SmartElex, PWM tone) | 25 | `tone()` / `noTone()` |

**Motor truth table** (`setMotor`, line 2422): forward = `IN_A=PWM, IN_B=0`, reverse = `IN_A=0, IN_B=PWM`, **stop = both 255 (active brake)**. Left turn = left backward + right forward, i.e. a spin in place.

## 6.3 `setup()` (line 1789)
1. Keep the motor driver asleep, attach PWM, brake, then wake the driver.
2. Sonar pins, `Serial.begin(115200)`.
3. `oledStartup()`: `Wire.begin(21,22)` and `new Face(128, 64, 40)`. Auto-blink is on, random behaviour and random look are **off** because the PC controls emotions.
4. `player.begin()` (speaker).
5. Wi-Fi STA: read a saved fallback network from NVS (`Preferences` namespace `ikru_wifi`), then `beginStation("IKRU-CAM")` with a **fixed IP 192.168.4.200**.
6. `webSocket.begin()` on port 81, `pcUdp.begin(4211)`.
7. `setSetupStage(SETUP_BOOT)` and an "inhale" chirp.

> **NVS (Non-Volatile Storage)**
> **Simple meaning:** a small notebook on the chip that survives power-off.
> **Technical meaning:** a key-value flash partition, accessed through the Arduino `Preferences` API.

## 6.4 `loop()` (line 1875), every ~5–20 ms
```text
webSocket.loop()          ← receive commands, fire webSocketEvent()
updateNetwork()           ← beacon "IKRU-ROBOT|ip|ssid|rssi|ws81" to UDP 4210 every 2 s; rejoin after 20 s offline
checkPcAnnounce()         ← read "IKRU-PC|<ip>" on UDP 4211
updateUltrasonic()        ← every 60 ms: ping, 5-sample median, EMERGENCY BRAKE if moving forward & < threshold
checkMotorFault()
player.update()           ← advance the droid-sound sequencer
if setupStage != DONE:  updateSetupStage(); drawSetupScreen(); return   ← boot screen owns the OLED
watchPcLink()             ← no WebSocket client for 3 s → stop motors, go back to "waiting for PC"
updateSpeechScroll()      ← speech-box open/close animation, 1 px scroll per 30 ms, chatter while scrolling
lerp eye scale/position   ← eyes shrink into the corner while the speech box is open
u8g2.clearBuffer(); drawSpeakingText(); face->Update(); u8g2.sendBuffer()
pollSerial()              ← same parseCommand() for USB serial input
```

## 6.5 The boot / setup screen
The robot shows a progress screen instead of a face until the PC says it's ready:

| Stage | Meaning | Leaves when |
|---|---|---|
| `SETUP_BOOT` | Banner animation (2.2 s) | timer → HUB or JOINED |
| `SETUP_HUB` | Looking for `IKRU-CAM`. After 30 s it tries the saved network for 15 s, then back | Wi-Fi connected |
| `SETUP_JOINED` | Joined animation (1.5 s), mDNS `ikru-robot.local` starts | → WAIT_PC or LINK |
| `SETUP_WAIT_PC` | "Waiting for PC" | PC announce seen **or** a WebSocket client connects |
| `SETUP_LINK` | Shows the PC's `SETUP:<text>` status ("Loading memory", "Waking brain"…) | `SETUP_DONE` command, or 120 s timeout |
| `SETUP_READY` | Success animation (1.8 s) | → `finishSetup()`: eyes grow from small to full, happy + blink |
| `SETUP_DONE` | Normal operation | PC link lost → WAIT_PC |

`allowedDuringSetup()` (line 1413): while not DONE, only `STOP`, `GET_DISTANCE`, `GET_IP`, `SET_WIFI:`, threshold/brake and volume commands are obeyed. **Face, sound, display and drive commands sent before `SETUP_DONE` are silently dropped.** That's why `main.py` sends `setup_done()` before greeting.

## 6.6 Command handling: `webSocketEvent` (1955) → `parseCommand` (2000)
- `GET_DISTANCE` is answered straight to the requesting client with `{"type":"distance","cm":43.2}`, and **no** `OK` follows.
- Every other text command → `parseCommand(cmd)` → reply `OK`.
- On client **disconnect** the motors stop, a safety feature.
- `parseCommand` checks, in order: setup protocol → setup gate → eye/look → display → sonar/safety → `SOUND:`/`STOP_AUDIO` → `VOLUME:` → `SET_WIFI:` → `GET_IP` → **uppercase** → emotions & vocal sounds → motors & `SPEED:` → otherwise `Unknown Command`.

The full command table is in Part 10.

## 6.7 Emergency brake (line 1771 and `moveForward` 2351)
Two independent layers:
1. `moveForward()` refuses to start if the filtered distance is between 3 cm and the threshold (12 cm by default, set by Python) and broadcasts `{"event":"obstacle_blocked",…}`.
2. `updateUltrasonic()` stops a forward move that's already running when an obstacle enters the threshold, and broadcasts `{"event":"obstacle_alert",…}`. It also sets the worried face and plays a sound.

The brake only applies to **forward** motion, since the sensor faces forward. Readings < 2.5 cm are treated as noise (999).

## 6.8 Speech box (OLED)
`DISPLAY:<text>` → `oledMessage()` → `prepareMessage()` word-wraps into lines ≤ 75 px wide (≤ 40 lines) using font `ncenB14`. The box animates open (300 ms, ease-out), waits `START_PAUSE` 600 ms, scrolls up 1 px every 30 ms, plays `playConversationalChirp(currentActiveEmotion)` whenever the speaker is idle (that's the "droid talking" sound), waits `END_PAUSE` 400 ms, then closes and resets the face to normal. Meanwhile the eyes shrink to 45% and move to the right corner (x=106, y=48).

## 6.9 `SonicPlayer` — droid sounds
A non-blocking sequencer of up to 32 `DroidStep {startFreq, endFreq, duration, pause}`. Frequencies slide linearly between start and end (a *glissando*, which gives the R2-D2 sound). `playEmotion(name, intensity)` (line 1424) has about 28 hand-designed patterns (happy, glee, sad, sigh, gasp, giggle, laughter, groan, clear_throat, cry, whisper, sniff, cough, sneeze, inhale, exhale, thinking, angry family, worried, surprised/scared, skeptic family, sleepy, awe, squint, success, error, warning, cannot_perform). **Unknown names play a default two-note chirp.**

## 6.10 The Face library (vendored)
```text
Face ─┬─ LeftEye / RightEye (Eye) ─ Config → Transition → Transformation → Variation1/2 → BlinkTransformation → EyeDrawer::Draw
      ├─ Expression (FaceExpression)  GoTo_<Emotion>() → both eyes TransitionTo(Preset_<Emotion>)
      ├─ Look (LookAssistant)         LookAt(x,y) moves eyes; note LookLeft = LookAt(+1, 0)
      ├─ Blink (BlinkAssistant)       timed/random blinks
      └─ Behavior (FaceBehavior)      random emotion wandering (disabled in IKRU)
```
- `EyePresets.h` defines an `EyeConfig` per emotion: offset, width/height, top/bottom slope, corner radii, inverse radii. **To change how an emotion looks, edit its preset there.**
- `Face.cpp` defines the single global `u8g2` object that `controller.ino` also draws on (through `Common.h`).
- License: AGPL-3.0 (Luis Llamas, Alastair Aitchison). Keep the headers if you redistribute.

## 6.11 Head firmware (`firmware/head/head.ino`)
- `initCamera()`: AI-Thinker pin map, QVGA JPEG, quality 20 (quality 12 with 1 frame buffer without PSRAM), vertical flip enabled.
- `startAP()`: SSID `IKRU-CAM`, password `ikru@potato`, IP 192.168.4.1. `disableGatewayOffer()` stops DHCP advertising a router, so a PC on two Wi-Fi adapters keeps its internet on home Wi-Fi.
- `checkDiscovery()`: any UDP packet containing `DISCOVER` on port 2223 records the sender as `pcIP` and replies `IKRU_CAM_ACK` (to 2223) and `IKRU_CAMERA` (to 2222).
- `loop()`: once a PC is known, grab a frame → `sendFrame()` splits it into 1200-byte chunks, each with the 22-byte `CameraPacketHeader` → UDP to `pcIP:2222`.
- There is no flow control and no retransmission. Lost chunks mean a dropped frame, which the PC handles.

---

# Part 7 — What Happens When IKRU Starts (Startup Trace)

Follow along in `software/ikru/main.py`. Times are rough.

```text
t=0s   python run.py
       └─ run.py: sys.path += software/ ; from ikru.main import main
          └─ importing ikru.main triggers module code:
             • imports every subsystem module (torch/cv2 etc. load lazily inside functions where possible)
             • config_data = config.json ⊕ config.local.json
             • ROBOT_IP, LLM_MODEL, … resolved
       main()
t≈0s   argparse → print banner
       ── STEP 1: bring-up (net/bringup.py) ─────────────────────────────────────────
       Bringup.run_network()
         [1/4] PC network   pick internet vs hub Wi-Fi adapter; check internet
         [2/4] Power on     wait (≤180 s) for SSID IKRU-CAM to be visible   ← power the HEAD first
         [3/4] Join hub     netsh connect; wait for a 192.168.4.x address; start PcAnnouncer (UDP 4211)
       robot = RobotController(ip, extra_hosts=[robot_last_ip], on_connect=…, connect_now=False)
         └─ starts heartbeat/reconnect thread immediately
       Bringup.link_body(robot)
         [4/4] Body link    robot.connect() repeatedly (≤60 s)
                            └─ find_robot(): UDP beacon 4210 + TCP probes → websocket ws://192.168.4.200:81
                            └─ on_connect → save robot_last_ip
                            └─ SETUP:PC linked      (robot OLED shows it)
       ── STEP 2/3: not found? wizard [r/m/u/c]; --provision-wifi? SET_WIFI ─────────
       ── STEP 4: subsystems ───────────────────────────────────────────────────────
       SETUP:Loading memory   → MemoryManager (SQLite now, Qdrant in background thread)
       SETUP:Waking brain     → ChatEngine; thread: chat.warm_up() (loads LLM into VRAM)
                               → LayaToolRouter; thread: warm_up() (may download ~1.5 GB first time)
       [tts mode only]        → SETUP:Warming voice → AudioService (+ HTTP :8000) + fillers
       robot.set_volume(); IdleManager.start(); ProximityMonitor.start()
       SET_OBSTACLE_THRESHOLD:12.0 ; OBSTACLE_BRAKE_ON
       SETUP:Opening ears     → MicController (loads Silero VAD, opens PyAudio)
       SETUP:Opening eyes     → VisionReceiver.start() (UDP 2222 thread) ; VLMClient
       AutonomousBrain(...).start()   (sleeps 25 s before doing anything)
       mic.start_background_listening(on_text, on_speech_start)  → 2 threads
       bringup.finish()  (stop PC announcer); app_ready.set()
       SETUP_DONE → robot plays ready animation (1.8 s), face wakes up
       sleep 2.5 s
       greeting: "Hi <name>! I am online and ready."  (name from facts table)
       chat_thread = Thread(chat_loop).start()
       main thread: while chat alive → vision.update_display()  (OpenCV window)
```

**Why is the order like this?**
- The head must be on before the body can join `IKRU-CAM`, and the PC needs the hub to reach either of them.
- The robot is told `SETUP:<status>` at each step so the human watching the robot can see progress.
- Heavy model loads (LLM, Laya, Qdrant, embeddings) run in background threads so the robot is usable sooner. The first reply may still wait on them.
- `SETUP_DONE` is sent **after** everything is built because the firmware ignores face and motion commands until then.

**If the robot reboots mid-session:** the heartbeat thread reconnects, `_on_robot_connect` sees `app_ready` is set and immediately sends `SETUP_DONE`, skipping the boot screen.

---

# Part 8 — One Conversation Turn, End to End

Example: you say **"Can you move forward for 2 seconds?"**

```text
 ①  MIC CAPTURE THREAD (mic/controller.py capture_loop)
     PyAudio 32 ms frames → Silero prob → SpeechSegmenter
     "start" event ─► on_speech_start()  (main.py:446)
                       ├─ idle_manager.notify_activity()       (stop fidgeting)
                       └─ autonomous_brain.attention()         (stop roaming, hold 8 s)
     500 ms silence → "end" + PCM ─► utterances queue

 ②  MIC STT THREAD (stt_loop)
     recognize_google(PCM) → "can you move forward for 2 seconds"
     on_text(text, t_end)  (main.py:435)
       ├─ exit phrase?  → interrupt_event.set() + queue it
       ├─ busy or within 0.3 s echo guard? → ignore ("Ignored while busy")
       └─ mic_queue.put((text, t_end))

 ③  CHAT THREAD (main.py chat_loop, line 483)
     user_input = mic_queue.get()
     busy.set(); idle.notify_activity(); proximity.pause(); brain.pause()
     _is_exit? no
     robot.focused(); robot.thinking()          → "FOCUSED", "THINKING" (face + chirp)

     ┌─ Laya worker (parallel) ────────────────────────────────┐
     │ decide(): intent "drive" p=0.93 → direction "forward"   │
     │ extract_duration → 2.0  → ToolDecision(move, forward 2s)│
     └──────────────────────────────────────────────────────────┘
     filler thread: waits 10 s (TTS mode only)
     VISUAL_PATTERN? no → no camera
     prox_context = "[Proximity Sensor: Path clear (61.0 cm)]"

     chat.ask(user_input, sensor_context=prox_context)            (engine.py:61)
       ├─ memory.build_memory_context()  → Qdrant + facts
       ├─ memory.record_user_message()   → SQLite + bg threads (vector index, fact regex)
       ├─ ollama.chat(model, messages, format="json")
       │     ← {"tools":[{"action":"forward","duration":2}],
       │        "response":"[happy]Rolling forward for two seconds [giggle]!"}
       ├─ parse_llm_json → tools, response_text
       ├─ parse_segments → [("happy","Rolling forward for two seconds [giggle]!")]
       └─ memory.record_assistant_message()
     decision = laya_future.result(5 s)
     tools = merge_tool_calls(decision, llm_tools, skip=executed_now)
           → [{"action":"forward","duration":2.0}]
     print [Timing] prep … | LLM … | end-of-speech → reply …

 ④  SPEAK (robot/controller.py speak_segments, line 306)
     segment has [giggle] → robot.giggle() → "GIGGLE" (happy face + giggle chirp)
     DISPLAY:Rolling forward for two seconds!   → OLED box opens & scrolls, droid chatter
     sleep calculate_speech_scroll_time(...) ≈ 3.8 s (interruptible)
     NORMAL

 ⑤  ACT (main.py:634)
     action "forward" → robot.forward(2.0)
        FORWARD … every 0.1 s check proximity (<12 cm → stop, wait, resume) … STOP
     brain.note_external_motion("forward", 2.0) → world model moves ~50 cm (at 25 cm/s)

 ⑥  WRAP-UP
     print "Assistant [HAPPY]: Rolling forward for two seconds!"
     busy_until = now + 0.3 s; busy.clear()
     idle.notify_speech_done(); proximity.resume(); brain.resume()
```

**Key insight for beginners:** IKRU **speaks first, then moves**. The body waits for the speech scroll to finish before the wheels turn. The exception is Laya's *immediate* actions (stop, cancel search), which fire at step ③ as soon as Laya answers.

**Variations:**
- **Visual question** ("what am I holding?"): at ③, `vision.buffer.get_jpeg_bytes()` → `vlm.describe_scene()` → `[Camera Visual Observation: …]` is added to the prompt.
- **Search** ("find my keys"): the tool `search_object` → `autonomous_brain.start_search("keys")`. The chat turn ends, then `brain.resume()` lets the brain thread run the search.
- **Sequence** ("celebrate!"): tool `play_sequence` → `robot.play_sequence("celebrate")` → loads `data/sequences/celebrate.json`.
- **Exit while speaking**: `on_text` sets `interrupt_event` → `speak_segments` stops mid-scroll → tools are skipped → next loop iteration handles "exit" → sleepy face, sigh, `break` → `finally:` shutdown.
- **Typed mode** (`--no-mic`): step ①–② is replaced by `input("You: ")`.

---

# Part 9 — Threads and Concurrency: Who Runs When

> **Thread**
> **Simple meaning:** a worker inside the program. Several workers run at once, sharing the same memory.
> **Technical meaning:** an OS thread (`threading.Thread`). Python's GIL (Global Interpreter Lock) lets only one thread run Python bytecode at a time, but threads waiting on network, sleep or I/O release it, so I/O-heavy work like this project runs concurrently just fine.

> **Daemon thread**
> **Simple meaning:** a background worker that's automatically killed when the program exits.
> **Technical meaning:** `daemon=True`. The interpreter doesn't wait for it on shutdown.

| Thread | Created in | Loop period | Talks to robot? |
|---|---|---|---|
| **main** | `run.py` | 1 ms (OpenCV `waitKey`) or 100 ms | no |
| **chat_loop** | `main.py:686` | blocks on mic queue / `input()` | yes (speech, tools) |
| robot heartbeat/reconnect | `RobotController.__init__` | 5 s ping; 5–30 s reconnect | ping only |
| IdleManager | `idle.start()` | 0.3 s | yes (blink, look, yawn) |
| ProximityMonitor | `proximity.start()` | 0.25 s + up to 0.6 s wait | yes (GET_DISTANCE, reflexes) |
| AutonomousBrain `_loop` | `brain.start()` | 0.5 s (plus long excursions) | yes (roaming, speech) |
| brain thought worker (pool of 1) | `ThreadPoolExecutor` | on demand | no (LLM/VLM only) |
| mic capture / mic STT | `start_background_listening` | 32 ms / queue | no |
| VisionReceiver | `vision.start()` | 0.5 s socket timeout | no |
| Laya worker (pool of 1) | `main()` | per turn | stop only |
| filler timer | per turn | 10 s wait | play_audio |
| chat warm-up, Laya warm-up, Qdrant init | once | — | no |
| memory index / fact extraction | per message | — | no |
| AudioService HTTP server | tts mode | serve_forever | no |
| PcAnnouncer, beacon listener, probe pool | during bring-up | 1 s / 50 ms | no |

**How they avoid fighting over the robot** (the "who has the stage" protocol):
1. **User turn:** `chat_loop` calls `idle.notify_activity()`, `proximity.pause()`, `brain.pause()` **before** thinking, and the matching resume calls after. The brain's `pause()` sets `_interrupt`, so any in-progress autonomous speech or motion aborts within ~50–100 ms.
2. **Voice detected:** `on_speech_start` → `brain.attention()` freezes roaming for 8 s even before the words are transcribed.
3. **Autonomous speech:** the brain's `_take_stage()` pauses idle + proximity reflexes. `_release_stage()` resumes them **only if the user hasn't taken over**.
4. **Echo guards:** `busy_until` (0.3 s after IKRU finishes) and `brain.is_vocalizing()` (1.2 s) keep IKRU's own chirps from being treated as human speech.
5. **Locks:** `RobotController._lock` (socket), `ChatEngine._messages_lock` (history, because the brain appends too), `WorldModel._lock` (RLock), `SQLiteStore._lock`, `QdrantMemory._lock`, `FrameBuffer._lock`, `SequenceRunner._lock`.

> **Event**
> **Simple meaning:** a flag one thread raises and others can check or wait for.
> **Technical meaning:** `threading.Event` with `set()`, `clear()`, `is_set()`, `wait(timeout)`. Used here for `busy`, `interrupt_event`, `app_ready`, `thinking_event`, the brain's `_interrupt`, and `LayaToolRouter._ready`.

> **Race condition**
> **Simple meaning:** a bug where the result depends on which worker happens to go first.
> **Technical meaning:** unsynchronised access to shared state. The flags above are simple booleans (atomic enough under the GIL). Compound state such as the message list or world model is always accessed under a lock.

---

# Part 10 — Communication Protocols (the wire formats)

> **Protocol**
> **Simple meaning:** the agreed language two machines use, like both sides agreeing to speak English and say "over" at the end.
> **Technical meaning:** the message formats, ports, ordering and meaning shared by the sender and receiver.

> **Port**
> **Simple meaning:** an apartment number at an address. The IP address picks the building (machine), the port picks the door (program).
> **Technical meaning:** a 16-bit number that identifies a TCP/UDP endpoint on a host.

> **TCP vs UDP**
> **Simple meaning:** TCP is registered mail (guaranteed, in order). UDP is shouting across a room (fast, but some words get lost).
> **Technical meaning:** TCP is a reliable, ordered byte stream with connections. UDP is connectionless datagrams with no delivery guarantee. IKRU uses TCP (WebSocket) for commands, where losing one would be bad, and UDP for video and beacons, where freshness beats reliability.

## 10.1 Network topology

```text
                      Wi-Fi "IKRU-CAM" (WPA2, password ikru@potato), subnet 192.168.4.0/24
   ┌────────────────────────┐        ┌──────────────────────────┐       ┌──────────────────────────┐
   │ HEAD  ESP32-CAM        │        │ BODY  ESP32-WROOM         │       │ PC                       │
   │ 192.168.4.1 (AP, DHCP) │◄──────►│ 192.168.4.200 (static)    │◄─────►│ 192.168.4.2–.11 (DHCP)   │
   │ UDP 2223 discovery in  │        │ TCP 81  WebSocket server  │       │ UDP 2222 video in        │
   │ UDP 2222 video out ────┼────────┼───────────────────────────┼──────►│ UDP 4210 beacon in       │
   └────────────────────────┘        │ UDP 4210 beacon out (bcast)│      │ UDP 4211 announce out    │
                                     │ UDP 4211 PC-announce in    │      │ HTTP 11434 → Ollama (lo) │
                                     │ mDNS ikru-robot.local      │      │ HTTP 8000 audio (tts)    │
                                     └────────────────────────────┘      └──────────────────────────┘
```

A PC with two Wi-Fi adapters keeps home internet on one and IKRU-CAM on the other. That's why the head **doesn't** offer itself as a gateway.

## 10.2 WebSocket commands: PC → Body (`ws://192.168.4.200:81`)

Plain UTF-8 text, one command per message. The body replies `OK` to every command except `GET_DISTANCE`.

| Command | Effect | Python method |
|---|---|---|
| `FORWARD` / `BACKWARD` / `LEFT` / `RIGHT` / `STOP` | Drive (run until STOP) / active brake | `forward()` … `stop()` |
| `SPEED:<30-100>` | Speed % for subsequent moves | `set_speed()` |
| `NORMAL` `HAPPY` `GLEE` `SAD` `WORRIED` `FOCUSED` `ANNOYED` `SURPRISED` `SKEPTIC` `FRUSTRATED` `UNIMPRESSED` `SLEEPY` `SUSPICIOUS` `SQUINT` `ANGRY` `FURIOUS` `SCARED` `AWE` | Face + matching chirp | emotion methods |
| `SIGH` `GASP` `GIGGLE`/`CHUCKLE` `LAUGH`/`LAUGHTER` `GROAN` `CLEAR_THROAT`/`THROAT` `CRY`/`SOB` `WHISPER` `SNIFF` `COUGH` `SNEEZE` `INHALE` `EXHALE` `THINKING`/`PROCESSING` `SUCCESS` `ERROR` | Face + vocal-style sound | vocal methods |
| `SOUND:<name>[:<intensity>]` | Sound only (any `playEmotion` name) | `play_sound()` |
| `STOP_AUDIO` / `STOP_SOUND` | Silence | `stop_audio()` |
| `BLINK` | Blink | `blink()` |
| `LOOK:<x>:<y>` (−1..1) | Gaze | `look_at()` |
| `LOOK_LEFT/RIGHT/FRONT/TOP/BOTTOM` | Gaze presets | `look_*()` |
| `DISPLAY:<text>` | Open speech box and scroll text | `display()` |
| `DISPLAY_OPEN` / `DISPLAY_CLOSE` | Persistent box open/close | `display_open/close()` |
| `GET_DISTANCE` | Reply `{"type":"distance","cm":<float>}` | `get_distance()` |
| `SET_OBSTACLE_THRESHOLD:<cm>` / `THRESHOLD:<cm>` | Brake distance | `set_obstacle_threshold()` |
| `OBSTACLE_BRAKE_ON` / `_OFF` | Enable/disable brake | `enable/disable_obstacle_brake()` |
| `VOLUME:<0-100>` / `SET_VOLUME:` | Logged only (no hardware volume control) | `set_volume()` |
| `SET_WIFI:<ssid>:<pass>` | Join a network, save to NVS on success | `_provision_wifi_over_ws` |
| `GET_IP` | Prints `IP:<ip> SSID:<ssid> MODE:STA` to **Serial** (USB) | `serial_link.query_ip` |
| `SETUP:<text>` | Status line on the boot screen | `setup_status()` |
| `SETUP_DONE` | Finish boot screen → face | `setup_done()` |
| `DANCE`, `SING`, `SPEAK_URL:<url>` | ⚠️ **Not implemented in firmware** ("Unknown Command") | `dance()`, `sing()`, `play_audio()` |

Case: everything after the `GET_IP` check is uppercased, but `SETUP*`, `DISPLAY:`, `LOOK*`, `SOUND:`, `SET_WIFI:` and similar are matched **case-sensitively before that**. Always send them uppercase, as Python does.

## 10.3 Body → PC messages
| Message | When |
|---|---|
| `OK` | After each command (Python mostly ignores these. `get_distance` skips over them) |
| `{"type":"distance","cm":43.2}` | Reply to `GET_DISTANCE` |
| `{"event":"obstacle_alert","distance_cm":9.8}` | Brake stopped a forward move (broadcast) |
| `{"event":"obstacle_blocked","distance_cm":9.8}` | `FORWARD` refused (broadcast) |
| `{"event":"motor_fault"}` | DRV8833 nFAULT went low (broadcast) |

Python doesn't currently react to the `event` messages. It relies on its own proximity polling.

## 10.4 UDP discovery & presence
| Port | Direction | Payload | Purpose |
|---|---|---|---|
| 4210 | Body → broadcast, every 2 s | `IKRU-ROBOT|<ip>|<ssid>|<rssi>|ws81` | PC finds the body (`discovery.parse_beacon`) |
| 4211 | PC → body + broadcast, every 1 s during bring-up | `IKRU-PC|<pc_ip>` | Body's boot screen shows "PC arrived" |
| 2223 | PC → head, every 2 s | `IKRU_DISCOVER` | Head learns where to stream |
| 2223 / 2222 | Head → PC | `IKRU_CAM_ACK` / `IKRU_CAMERA` | Acks |

## 10.5 Camera video packets (UDP 2222)
```text
 offset size field         value
 0      2    magic         0x494B ("IK", little-endian)
 2      1    version       1
 3      1    packetType    0 = video
 4      4    frameId       increments per frame
 8      2    chunkId       0 … totalChunks-1
 10     2    totalChunks
 12     4    frameLength   total JPEG bytes
 16     2    chunkLength   bytes in this packet's payload (≤1200)
 18     4    timestamp     head millis()
 22     …    payload       JPEG slice
```
Python format string: `"<HBBIHHIHI"` (22 bytes). A frame is accepted only if every chunk arrives within 150 ms and the bytes form a valid JPEG.

## 10.6 USB serial (115200 baud)
Every line typed into the Serial Monitor goes through the same `parseCommand()`. Useful lines: `GET_IP`, `SET_WIFI:ssid:pass`, `FORWARD`, `STOP`, `HAPPY`.

## 10.7 PC ↔ Ollama (HTTP localhost:11434)
Via the `ollama` package: `ollama.chat(model, messages, format="json", keep_alive)`, `ollama.generate(model, prompt, images=[jpeg_bytes], format="json")`.

**LLM output contract** (enforced by the prompt, parsed by `parse_llm_json`):
```json
{"tools": [{"action": "forward", "duration": 2},
           {"action": "play_sequence", "sequence": "celebrate"},
           {"action": "search_object", "target": "coffee mug"}],
 "response": "[happy]Text with [giggle] sound tags. [focused]Second emotion segment."}
```

---

# Part 11 — Data and Storage

| Data | Where | Format | Written by | Read by | Survives restart? |
|---|---|---|---|---|---|
| Settings | `config.json` | JSON | you, `_save_config` (robot_ip, robot_last_ip), calibration test | `main.py` at import | yes |
| Secrets/overrides | `config.local.json` | JSON (git-ignored) | Wi-Fi prompt, bring-up (adapter names) | `main.py` | yes |
| Conversation window | `ChatEngine.messages` | Python list | `ask`, brain | Ollama | **no** |
| Chat history | `data/memory/ikru_history.db` → `messages` | SQLite | `MemoryManager.record_*` | stats | yes |
| User facts | same db → `user_facts` | SQLite | `_extract_facts` | prompt context, greeting | yes |
| Semantic memories | `data/memory/qdrant/` | Qdrant embedded | background indexing | `build_memory_context` | yes |
| Landmark familiarity | `data/memory/world_model.json` | JSON | `WorldModel.save` | `WorldModel.load` | yes (positions are not kept) |
| Occupancy grid, pose | `WorldModel` in RAM | dict | autonomy | autonomy | **no** |
| Choreographies | `data/sequences/*.json` | JSON list of steps | you | `SequenceRunner` | yes |
| Latest camera frame | `FrameBuffer` | NumPy BGR array | receiver thread | VLM callers | no |
| Robot fallback Wi-Fi | ESP32 NVS `ikru_wifi` | key/value | `SET_WIFI` | firmware boot | yes (on chip) |
| TTS audio | `software/ikru/audio/cache/` | WAV | `AudioService` | HTTP server | yes |

## SQLite schema (`memory/database.py`)
```sql
sessions(session_id INTEGER PK AUTOINCREMENT, created_at TEXT, title TEXT)
messages(id INTEGER PK, session_id INTEGER → sessions, timestamp TEXT,
         role TEXT  -- 'user' | 'assistant'
         content TEXT, visual_context TEXT NULL, tools_used TEXT NULL  -- JSON string)
user_facts(id INTEGER PK, category TEXT  -- 'personal' | 'preference' | 'general'
           fact TEXT UNIQUE, created_at TEXT, confidence REAL)
INDEX idx_messages_session(session_id, timestamp); INDEX idx_facts_category(category)
```
Inspect it with any SQLite browser, or:
```bash
python -c "import sqlite3;c=sqlite3.connect('data/memory/ikru_history.db');print(c.execute('select category,fact from user_facts').fetchall())"
```

## Qdrant collection
`ikru_longterm_memory`: 384-dim cosine vectors. Payload `{text, timestamp, role, type: 'conversation'|'fact', …}`. IDs are random UUIDs. Autonomous thoughts are stored with the prefix `[autonomous thought]`.

> **Note on the greeting:** `main.py:467` looks for a `personal` fact containing "name is" and takes the text after the last "is". So "User's name is Sam" → "Sam".

---

# Part 12 — What Happens When Something Fails

The project's general philosophy is **degrade, don't crash**. Most subsystems are optional, and failures are printed as `[Subsystem] Warning…`.

| Failure | What the code does | Where |
|---|---|---|
| `IKRU-CAM` never appears | Stage 2 warns and returns. Robot + vision are offline | `bringup._stage_power_on` |
| PC can't join hub | Stage 3 warns | `bringup._stage_join_hub` |
| Hub steals internet route | Offers to run `Set-NetIPInterface … -InterfaceMetric 9000` as admin | `bringup._fix_route` |
| Robot not found | `Diagnosis` + wizard (retry/manual/USB/offline). Offline mode keeps reconnecting every 5–30 s | `discovery.diagnose`, `main._connection_wizard` |
| Robot disconnects mid-session | `send()` error → `_handle_disconnect`. Heartbeat reconnects and re-sends `SETUP_DONE`. Commands meanwhile are **silently dropped** | `controller.py` |
| Body loses the PC | After 3 s without a client: stop motors, back to "Waiting for PC" screen | firmware `watchPcLink` |
| Body loses Wi-Fi | Beacon stops. Forced rejoin after 20 s. Tries saved network if the hub is gone | firmware `updateNetwork`, `updateSetupStage` |
| Obstacle ahead | Firmware brake (< 12 cm) + Python `forward()` pause/resume + ProximityMonitor reflex (< 10 cm) + roaming stop (< 25 cm) | several layers |
| Motor driver fault | Broadcast `motor_fault` (Python ignores it; check Serial) | firmware |
| Ollama down / model missing | `ask` retries without JSON mode, then says a canned sad line | `engine.py:128` |
| LLM returns invalid JSON | Whole text is spoken, no tools | `parse_llm_json` |
| LLM invents an unknown action | `getattr(robot, action, None)` is None → ignored | `main.py:658` |
| Laya missing / unsure | Returns None → LLM tools used | `tool_router.py` |
| Memory init fails | `memory=None`, runs without memory | `main.py:316` |
| Qdrant/FastEmbed missing | Warning, recall empty, SQLite still works | `vector_store._lazy_init` |
| Mic init fails | Falls back to typed input | `main.py:389` |
| STT can't understand / no internet | Utterance ignored / `[STT Error]` printed | `mic/controller.stt_loop` |
| Silero missing | Falls back to webrtcvad (must be installed) | `vad.load_vad` |
| Camera port busy / no frames | `[Vision] Bind error`. VLM gets None, and no visual context is used | `receiver._worker` |
| Search without camera | Robot says "I need my camera working to search for things" | `main.py:647` |
| Autonomous cycle exception | Printed, motors stopped, loop continues | `brain._loop` |
| TTS fails | Chatterbox → Edge-TTS → None | `AudioService.synthesize` |
| Ctrl+C | `finally:` stops mic, audio, vision, idle, proximity, brain, robot | `main.py:697` |

⚠️ **Unhandled cases** (the chat thread would die and the program would exit): the LLM returns a non-numeric `duration` (`float("a lot")` raises), or `tools` isn't a list of dicts. See Part 17.

---

# Part 13 — Setting Up and Running the Project

## 13.1 Hardware checklist
- ESP32-WROOM-32 DevKit (body) + DRV8833 + 2 TT motors + battery (VM 2.7–10.8 V) with **common ground**
- SSD1306 128×64 I2C OLED (SDA 21, SCL 22)
- HC-SR04P ultrasonic (TRIG 18, ECHO 19)
- SmartElex digital speaker module (IN → GPIO 25)
- AI-Thinker ESP32-CAM (head) + USB-TTL adapter for flashing
- Windows PC, ideally with **two Wi-Fi adapters** (built-in + USB dongle): one for internet (needed for Google STT), one for IKRU-CAM

## 13.2 Flash the firmware (Arduino IDE 2.x)
1. Boards Manager: install **esp32 by Espressif, version 3.x**.
2. Libraries: **WebSockets** (Markus Sattler), **U8g2** (olikraus).
3. **Head:** open `firmware/head/head.ino`, board "AI Thinker ESP32-CAM", upload. Serial should show `[READY] Video on UDP 2222 | Discovery on 2223`.
4. **Body:** open `firmware/controller/controller.ino` (the whole folder compiles together), board "ESP32 Dev Module", upload. The OLED shows the boot screen, then "Finding IKRU-CAM".
5. Wi-Fi credentials are **already hard-coded** (`IKRU-CAM` / `ikru@potato`). The README's "edit your SSID" step is outdated.

## 13.3 Python environment
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
# Missing from requirements.txt but imported by the code:
pip install qdrant-client fastembed webrtcvad pytest
```
`PyAudio` may need a prebuilt wheel on Windows (`pip install pipwin; pipwin install pyaudio`, or a wheel matching your Python version). `torch` is large. Install the CUDA build if you have an NVIDIA GPU.

## 13.4 Ollama
```powershell
ollama pull qwen2.5:7b      # or change llm_model in config.json (qwen2.5:3b is lighter)
ollama pull qwen3-vl:4b     # vision; skip if you run --no-vision
ollama serve                # usually already running as a service
```

## 13.5 Run
Power on the **head**, then the **body**, then:
```powershell
python run.py                    # voice + vision + autonomy
python run.py --no-mic           # type instead of talk
python run.py --no-vision        # no camera, no VLM, no object search
python run.py --no-wizard        # never block on menus (good for unattended runs)
python run.py --ip 192.168.1.50  # body on another network
python run.py --provision-wifi   # push a fallback Wi-Fi to the body
python run.py --voice-mode tts --tts-engine edge   # experimental neural voice path
```
Say or type **"exit"** to quit.

## 13.6 `config.json` reference
| Key | Meaning |
|---|---|
| `robot_ip`, `robot_last_ip` | Hints for discovery (last good IP is saved automatically) |
| `cam_ip` | Head address (192.168.4.1) |
| `enable_vision`, `enable_mic` | Master switches (CLI `--no-*` also works) |
| `play_pc_audio`, `tts_engine`, `voice`, `volume` | Audio options (TTS mode) |
| `mic.vad`, `vad_threshold`, `silence_ms`, `max_utterance_s`, `device_index` | Microphone/VAD tuning. `device_index` picks a specific mic |
| `llm_model`, `vlm_model`, `llm_keep_alive` | Ollama models |
| `memory.enabled`, `sqlite_path`, `qdrant_path` | Memory (`recall_*` currently unused) |
| `autonomous.*` | See `autonomy/config.py` `DEFAULT_CONFIG` |
| `tool_router.engine` | `"laya"` or `"llm"` |
| `tool_router.mode` | `"parallel"` or `"sequential"` |
| `tool_router.min_confidence`, `veto`, `device`, `laya_model` | Laya tuning |
| `bringup.*` (optional) | Stage timeouts |
| `internet_adapter`, `hub_adapter` (in config.local.json) | Which Wi-Fi adapter does what |

---

# Part 14 — Tests and Diagnostic Tools

## Offline (no hardware) — run these first
```powershell
python -m pytest tests/test_autonomous_roaming.py tests/test_laya_router.py tests/mic/test_vad_segmenter.py tests/net tests/robot/test_motor_diagnose.py -v
```
| Test file | What it proves | Technique |
|---|---|---|
| `tests/test_autonomous_roaming.py` | Dead reckoning, homing, obstacle avoidance, surprises, landmarks, excursions, yielding to the user | `FakeRobot`, `FakeProximity`, `FakeVLM` |
| `tests/test_laya_router.py` | Duration/target extraction, intent → tools, confidence fallback, merge rules | `FakeLaya` script. Live model with `IKRU_LAYA_LIVE=1` |
| `tests/mic/test_vad_segmenter.py` | Speech start/end, pre-roll, hysteresis, force-cut | synthetic frames |
| `tests/net/test_discovery.py` | Beacon parsing, probe/beacon discovery, each diagnosis | localhost fake port + monkeypatch |
| `tests/net/test_bringup.py` | netsh/ipconfig parsing, adapter selection, PC announcer | canned command output |
| `tests/robot/test_motor_diagnose.py` | Motor wiring diagnosis logic | pure function |

> **Mock / fake**
> **Simple meaning:** a pretend object that behaves like the real one, so you can test without the robot.
> **Technical meaning:** a test double that implements the same methods (duck typing) and records calls for assertions.

## Hardware diagnostics (need the robot)
| Script | Use it to |
|---|---|
| `tests/robot/test_motors.py [--ip] [--auto]` | Guided wiring check (tells you if a motor is reversed or sides are swapped), WASD drive |
| `tests/robot/test_ultrasonic.py` | Live distance bar + brake test |
| `tests/robot/test_roam_calibration.py` | Measure cm/s and °/s, saved into `config.json` |
| `tests/audio/test_r2d2_speaker.py` | Play every droid sound |
| `tests/test_idle_behavior.py`, `test_proximity_reactions.py`, `test_emotion_sequences.py` | Watch each background behaviour on the real robot (`RobotController()` with no IP still finds the body, because discovery always tries `192.168.4.200` and the UDP beacon) |
| `tests/vision/test_udp_receiver.py` | Standalone camera receiver + MobileNet-SSD demo |
| `tests/memory/test_memory.py` | Memory round-trip. Its path setup points at `tests/`, so run it with `$env:PYTHONPATH="software"; python tests/memory/test_memory.py` |
| `tests/robot/motor_drv8833/*.ino`, `motor_l293d/*.ino` | Minimal motor-only firmware to isolate hardware issues |
| `tests/audio/*` | TTS experiments and latency benchmark (use `ask_stream`) |

Several older scripts (`test_robot.py`, `test_socket.py`, `scratch_test_ws.py`) hard-code IPs like `192.168.1.34`. Edit them to `192.168.4.200` first.

---

# Part 15 — How to Modify the Project (Recipes)

A general rule for this codebase: **a robot capability lives in up to four places.**

```text
 1. firmware/controller/controller.ino   parseCommand()        ← the body can do it
 2. software/ikru/robot/controller.py    RobotController.xxx() ← Python can ask for it
 3. software/ikru/chat/prompts.py        SYSTEM_PROMPT          ← the LLM knows it exists
 4. software/ikru/main.py  chat_loop     tool execution         ← only if it needs special handling
    (+ chat/tool_router.py if Laya should pick it)
```

Most simple actions only need 1–3, because `main.py:658` calls **any** `RobotController` method whose name matches the tool's `action`.

## Recipe A — Add a new physical action, e.g. "nod"

1. **Firmware** (`controller.ino`, in `parseCommand` near the motor commands):
   ```cpp
   } else if (input == "NOD") {
     face->LookTop();    // playful "nod" with the eyes
     player.playEmotion("happy", 0.4);
   ```
   Put it before the final `else { Unknown Command }`, after the `toUpperCase()` line. Re-flash.
2. **Python** (`robot/controller.py`):
   ```python
   def nod(self): self.send("NOD")
   ```
3. **Prompt** (`chat/prompts.py`): add `nod` to "Single actions:" and give one example:
   `'User: Nod if you agree\nAssistant: {"tools": [{"action": "nod", "duration": 0}], "response": "[happy]Absolutely [giggle]!"}\n\n'`
4. **Test:** `python run.py --no-mic`, type "nod at me". You should see `Executing: nod (0.0s)` in the terminal.
5. *(Optional)* **Laya:** add `"nod": "nod yes"` to `PERFORMANCES` in `tool_router.py`, plus a test in `tests/test_laya_router.py`.

⚠️ Movement methods (`forward/backward/left/right/stop`) get `method(duration)`. Everything else gets `method()` with **no arguments**, so don't give new non-movement methods required parameters.

## Recipe B — Add a new choreographed sequence (no code!)

Create `data/sequences/peekaboo.json`:
```json
[
  {"emotion": "scared",  "sound": "gasp",     "movement": "backward", "duration": 0.3, "gaze": [0.0, -0.3]},
  {"emotion": "glee",    "sound": "laughter", "movement": "forward",  "duration": 0.3, "gaze": [0.0, 0.3], "display_text": "Peekaboo!"},
  {"emotion": "happy",   "sound": "giggle",   "movement": "stop",     "duration": 0.6}
]
```
Then tell the LLM about it in `prompts.py` ("Multi-step sequences: …, peekaboo"). Test it directly:
```python
from ikru.robot import RobotController; r = RobotController(); r.setup_done(); r.play_sequence("peekaboo")
```
If you want autonomy to be allowed to trigger it, add it to `SAFE_SEQUENCES` in `autonomy/config.py`.

## Recipe C — Add a new emotion / face
1. `EyePresets.h`: add `static const EyeConfig Preset_Proud = {...}` (copy a similar preset and tweak it).
2. `FaceExpression.h/.cpp`: add `GoTo_Proud()` (copy an existing one).
3. `controller.ino`: add `emotionProud()` and an `else if (input == "PROUD")` branch, plus optionally a sound in `SonicPlayer::playEmotion`.
4. Python: `def proud(self): self.send("PROUD")` in `robot/controller.py`, add it to `ALL_EMOTIONS` in `robot/protocol.py`, `OLED_EMOTIONS` in `chat/parser.py`, and `OLED_EMOTION_TAGS` in `audio/service.py`.
5. `prompts.py`: add it to "AVAILABLE EMOTIONS" and "EMOTION DEFINITIONS".

## Recipe D — Teach IKRU a new kind of user fact
Add a tuple to `FACT_PATTERNS` in `memory/manager.py`:
```python
(r"my birthday is (?:on )?(.+?)(?:\.|,|$)", "personal", "User's birthday is {0}", False),
```
It's saved automatically and injected as `[Known User Facts]` on the next turn.

## Recipe E — Add a new sensor context for the LLM (e.g. battery level)
1. Firmware: answer `GET_BATTERY` like `GET_DISTANCE` (JSON `{"type":"battery","v":7.4}`).
2. Python: a `get_battery()` in `RobotController`. Copy `get_distance()` and change the `type` check.
3. `main.py` chat loop: build `"[Battery Sensor: 7.4 V, about 60%]"` and pass it. `ChatEngine.ask` accepts one `sensor_context` string, so join it with the proximity string using `"\n"`.
4. `prompts.py`: explain the new tag and say "never read it aloud".

## Recipe F — Change what triggers the camera
Edit `VISUAL_PATTERN` in `main.py:88`. Keep it tight. Every VLM call can evict the chat model from GPU memory and make the next reply slow.

## Recipe G — Tune autonomy
Put overrides in `config.json → "autonomous"`, for example `"roam_enabled": false` (sit still but keep thinking aloud), `"enabled": false` (quiet, but search still works), or `"leash_cm": 60` (roam further). Recalibrate speeds after any mechanical change.

## Recipe H — Switch the chat model
`config.json → "llm_model": "qwen2.5:3b"` (faster/lighter) and `ollama pull` it. Smaller models follow the JSON and emotion-tag rules less reliably. Watch for `[ChatEngine] Warning` lines.

## Recipe I — Add an offline unit test
Follow `tests/test_autonomous_roaming.py`: put `software/` on `sys.path`, build fakes with only the methods your code calls, and assert on recorded commands:
```python
class FakeRobot:
    connected = True
    def __init__(self): self.sent = []
    def send(self, c): self.sent.append(c)
    def stop(self, *a): self.sent.append("STOP")
```

## Where NOT to put things
- Don't put new blocking waits in firmware `loop()`. Use `millis()` timers.
- Don't call Ollama from the chat thread **and** hold `RobotController._lock`.
- Don't write secrets to `config.json`. Use `_save_config(CONFIG_LOCAL_FILE, …)`.
- Don't send face or motion commands before `SETUP_DONE`. They're ignored.

---

# Part 16 — Debugging Guide: Where to Look When Something Breaks

**Golden rule:** read the bracketed prefix in the terminal. Every subsystem logs with its own tag: `[Robot]`, `[Mic]`, `[Laya]`, `[ChatEngine]`, `[Memory]`, `[Vision]`, `[VLM]`, `[Autonomous]`, `[Search]`, `[Proximity]`, `[Idle]`, `[Sequence]`, `[WiFi]`, `[USB]`. On the body, open the Arduino **Serial Monitor at 115200 baud**. It prints every received command, `Unknown Command`, `[SAFETY]`, `[Setup]` and `[SonicPlayer]` lines.

| Symptom | Likely cause | Look at / do |
|---|---|---|
| Bring-up stuck at "[2/4] Power on" | Head not powered or not flashed | Head Serial: `[WIFI] Head AP Started!` |
| "[3/4] couldn't join IKRU-CAM" | Wrong adapter / old profile | `netsh wlan show interfaces`; set `hub_adapter` in `config.local.json` |
| "ROBOT NOT REACHABLE — isolation" | Guest/campus Wi-Fi | Use IKRU-CAM |
| "announcing itself … port 81 isn't accepting" | Windows Firewall | Allow Python on private networks |
| PC loses internet after joining hub | Hub route preferred | Accept the metric fix, or re-flash the head (gateway offer disabled) |
| Robot face never appears | `SETUP_DONE` never sent (Python crashed during startup) | Python traceback; the robot also self-wakes after 120 s |
| Robot ignores commands but says OK | Before `SETUP_DONE`, or a typo in the command | Serial Monitor shows `Received:` + `Unknown Command` |
| "dance"/"sing" does nothing | Not implemented in firmware | Part 17 |
| Motors don't move at all | EEP not HIGH, no VM power, no common ground, fault | `tests/robot/test_motors.py` guided check; Serial `[MOTOR]` |
| Won't drive forward, others work | Emergency brake (object < 12 cm or noisy sonar) | `tests/robot/test_ultrasonic.py`; send `OBSTACLE_BRAKE_OFF` to confirm |
| Wheels go the wrong way | Motor wires reversed or sides swapped | Guided check tells you which; swap wires or IN pins |
| Board won't boot after wiring | GPIO12 strapping pin pulled high | Disconnect IN4 at boot, or move it to another pin (update firmware) |
| Mic hears nothing | Wrong input device | Set `mic.device_index`; list devices with `tests/mic/test_mic_stt.py` |
| "Ignored while busy" | Talking while IKRU speaks/moves | By design. Wait, or say an exit phrase |
| `[STT Error]` | No internet (Google STT) | Two-adapter setup, or `--no-mic` |
| Program exits when you say "later" / "sleep" | Exit phrase substring match | Edit `EXIT_PHRASES` in `main.py` |
| Replies are slow (10 s+) | Model cold, too big, or evicted by the VLM | Watch `[Timing]`; use `qwen2.5:3b`; keep visual questions rare |
| IKRU says "trouble thinking" | Ollama not running / model not pulled | `ollama list`, `ollama serve` |
| Reply has no emotion change | Model ignored the format | Check the raw JSON; strengthen the prompt examples |
| First reply takes ~30 s more | Qdrant/FastEmbed initialising (first run downloads a model) | `[Memory] Qdrant vector memory ready` log |
| Doesn't remember name | Name must be capitalised: "My name is Sam" | `user_facts` table |
| Camera window black "Connecting to IKRU-CAM…" | PC not on hub, port 2222 busy, head not streaming | Head Serial `[DISCOVERY] PC Connected` |
| "I need my camera working to search" | Vision disabled/failed | Remove `--no-vision`; check `[Vision]` logs |
| IKRU roams off the table | Speeds uncalibrated → leash wrong | `tests/robot/test_roam_calibration.py`; reduce `leash_cm` |
| IKRU keeps talking to itself too much | Autonomy intervals | `MIN/MAX_INTERVAL_S`, `thought_gap_s` in `autonomy/config.py` |
| `ImportError: cannot import name 'config' from 'ikru'` | `software/ikru/config.py` missing (untracked file) | Restore/commit `config.py` |
| `ModuleNotFoundError: qdrant_client` / `fastembed` / `webrtcvad` | Not in requirements | `pip install …` (Part 13) |

**Debugging techniques:**
- **Isolate layers.** Serial Monitor → `FORWARD` proves the firmware. `tests/robot/test_motors.py` proves WebSocket + firmware. `python run.py --no-mic --no-vision` proves the chat path.
- **Print the raw LLM output.** Temporarily add `print(assistant_raw)` after `engine.py:126`.
- **Turn off background noise.** Set `"autonomous": {"enabled": false}`, and comment out `idle_manager.start()` / `proximity_monitor.start()` so only your command reaches the robot.

---

# Part 17 — Known Gaps, Gotchas and Code-vs-README Differences

These come from reading the code, not from runtime testing. Treat them as a starting to-do list. Each is phrased as a fact about the current code.

**Behaviour gaps**
1. **`DANCE`, `SING`, `SPEAK_URL` have no firmware handler.** The prompt advertises `dance`/`sing`, but the body logs "Unknown Command". Map them to sequences in Python, or implement them in `parseCommand`.
2. **TTS voice mode doesn't speak.** `RobotController.speak_segments()` accepts `audio_service` but never calls it. The body has no I2S audio path in the current firmware, and `SPEAK_URL` is unhandled.
3. **Filler audio never exists.** `pregenerate_fillers()` expects `filler_N.wav`, but `synthesize()` writes `ikru_chunk_<ms>.wav`.
4. **`VOLUME:` is a no-op** on the body (only logged).
5. **Body events are ignored.** `obstacle_alert`, `obstacle_blocked` and `motor_fault` are broadcast but not handled in Python.
6. **Exit phrases are substring matches**: "later", "sleep", "see you", "quit" anywhere in a sentence end the program.
7. **Tool execution robustness.** `float(t.get("duration", 0))` and `getattr(robot, action)` trust the LLM. A non-numeric duration raises inside the chat thread and ends the program. Any `RobotController` method name, e.g. `close`, could be invoked by the model. Consider an allow-list.
8. **`memory.recall_top_k` / `recall_threshold` in `config.json` are not wired** to `build_memory_context`.
9. **STT is not offline.** `recognize_google` needs internet, despite the "fully offline" claim in the README.

**Repository hygiene**
10. `software/ikru/config.py` is **untracked but imported** by `robot/controller.py` and `chat/engine.py`. Commit it together with them.
11. `software/ikru/connection.py` is untracked and unused.
12. `requirements.txt` lacks `qdrant-client`, `fastembed`, `webrtcvad`, `pytest`, and includes many unused packages (gradio, fastapi, …).
13. `data/memory/ikru_history.db` and the Qdrant store are committed, which puts personal conversation data in git.
14. `dump/run_dashboard.py` imports `ikru.ui.server`, which no longer exists.
15. `AudioService` writes into `software/ikru/ui/static/audio` (a dashboard leftover).
16. `ChatEngine.ask_stream`, `config.STREAM_SENTENCES` and `PUNCTUATION_DELIMITERS` are only used by the benchmark test.

**README.md is out of date in these places**
| README says | Code actually does |
|---|---|
| phi3 / qwen2.5:3b | `config.json` uses `qwen2.5:7b` |
| Run `python chat.py` in `src/` | Run `python run.py` at the repo root |
| Edit Wi-Fi in `src/esp32_controller/...` | Firmware is in `firmware/controller/` and joins `IKRU-CAM` automatically |
| Camera at its own home-network IP, HTTP stream | Head *is* the AP at 192.168.4.1 and streams UDP |
| `firmware/camera/`, `firmware/eyes-demo/`, `tests/speaker/` | These folders don't exist. The head sketch is `firmware/head/head.ino` |
| STOP = coast | Firmware STOP = **active brake** (both inputs HIGH) |
| Protocol = 5 commands | ~60 commands (Part 10) |
| Roadmap: ultrasonic, camera, voice "todo" | All implemented |

---

# Part 18 — Glossary

| Term | Simple meaning | In this project |
|---|---|---|
| **Access Point (AP)** | A Wi-Fi "router" others join | The head creates `IKRU-CAM` |
| **Active brake** | Stopping the motor by shorting it, not letting it coast | `stopMotors()` sets both inputs HIGH |
| **Beacon** | A repeated "I'm here" broadcast | Body → UDP 4210 every 2 s |
| **Broadcast (UDP)** | Sending to everyone on the network | `255.255.255.255` / `192.168.4.255` |
| **Callback** | A function you hand over to be called later | `on_text`, `on_connect`, `on_speech_start` |
| **Composition root** | Where objects are built and wired | `main()` |
| **Context (LLM)** | Extra information put into the prompt | memory, camera, proximity, world model tags |
| **Daemon thread** | A background worker that dies with the program | nearly all threads here |
| **Dead reckoning** | Position from speed × time | `WorldModel.apply_forward/apply_turn` |
| **DHCP** | Automatic IP address assignment | Head gives the PC 192.168.4.2–.11 |
| **Duck typing** | Using any object that has the right methods | Brain works with `FakeRobot` in tests |
| **Embedding** | Text turned into a list of numbers capturing meaning | FastEmbed bge-small, 384 dims |
| **Event (threading)** | A shared on/off flag threads can wait on | `busy`, `interrupt_event` |
| **Facade** | One simple front for several subsystems | `MemoryManager` |
| **Firmware** | Software that lives on a hardware chip | `firmware/` |
| **Glissando** | A sliding pitch | droid sounds in `SonicPlayer` |
| **GIL** | Python's one-bytecode-at-a-time lock | I/O-bound threads still overlap |
| **GPIO** | A programmable pin on the chip | motor/sonar/speaker pins |
| **H-bridge** | A circuit that can drive a motor both ways | DRV8833 |
| **Hysteresis** | Different thresholds for on and off | VAD 0.5 on / 0.35 off |
| **I2C** | A 2-wire bus for chips | OLED on GPIO 21/22 |
| **JSON** | A text format for structured data | LLM replies, sequences, config |
| **Keep-alive (Ollama)** | How long a model stays loaded | `llm_keep_alive: 30m` |
| **Laya** | A fast decision model that picks options | tool routing |
| **Leash** | Maximum roaming radius from home | `leash_cm: 35` |
| **LLM** | A text-generating AI model | Qwen 2.5 via Ollama |
| **Lock / mutex** | Only one thread at a time | `RobotController._lock` etc. |
| **mDNS** | Finding a device by name on the LAN | `ikru-robot.local` |
| **Median filter** | Take the middle of recent readings to reject spikes | 5-sample sonar filter |
| **Microcontroller** | A small single-chip computer | ESP32 |
| **NVS** | Flash key/value storage on ESP32 | saved fallback Wi-Fi |
| **Occupancy grid** | A map of free/blocked squares | 10 cm cells in `WorldModel` |
| **OLED** | A small self-lit display | SSD1306 128×64 face |
| **Paralinguistic tag** | A non-word vocal sound marker | `[sigh]`, `[giggle]` |
| **Port** | A numbered door on a machine | 81, 2222, 4210, 11434 … |
| **Pre-roll** | Audio kept from just before speech started | 300 ms in `SpeechSegmenter` |
| **Prompt** | The text instructions given to the LLM | `SYSTEM_PROMPT` + augmented input |
| **PWM** | Rapid on/off switching to control power | 20 kHz motor speed, speaker tones |
| **Race condition** | A bug caused by thread timing | avoided with locks/events |
| **Sequence** | A scripted multi-step performance | `SequenceRunner` |
| **Sliding window** | Keeping only the latest N messages | system + 10 |
| **Soft-AP** | A device acting as a Wi-Fi AP | head |
| **SQLite** | A file-based SQL database | `ikru_history.db` |
| **State machine** | A system in one mode at a time, with rules to switch | setup stages, brain states |
| **STT** | Speech to text | Google via SpeechRecognition |
| **System prompt** | Permanent instructions for the LLM | `chat/prompts.py` |
| **TCP / UDP** | Reliable stream / fast unreliable datagrams | WebSocket / video + beacons |
| **Thread** | A parallel worker inside a program | Part 9 |
| **Tool call** | A structured action the AI requests | `{"action":"forward","duration":2}` |
| **TTS** | Text to speech | Chatterbox / Edge-TTS (experimental) |
| **VAD** | Detecting when someone speaks | Silero / webrtcvad |
| **Vector database** | Search by meaning | Qdrant |
| **VLM** | An AI that understands images | qwen3-vl via Ollama |
| **VRAM** | GPU memory | LLM and VLM compete for it |
| **WAL (SQLite)** | A journaling mode allowing concurrent reads | `PRAGMA journal_mode=WAL` |
| **WebSocket** | A persistent two-way connection | `ws://192.168.4.200:81` |
| **World model** | The robot's internal picture of its surroundings | `autonomy/world_model.py` |

---

# Part 19 — Your First Week: A Learning Path

**Day 1 — Read and run without hardware**
- Read Parts 1, 3, 7 and 8 of this document.
- Create the venv, install requirements plus the extras, then run the offline tests (Part 14). All should pass.
- Open `main.py` and follow `main()` → `chat_loop()` alongside Part 8.

**Day 2 — Talk to it without the robot**
- `ollama pull qwen2.5:3b`, set `llm_model` to it, run `python run.py --no-mic --no-vision --no-wizard` and choose to continue offline.
- Chat. Read the `[Timing]` and `[Memory]` lines. Tell it your name, restart, and check it greets you.
- Open `data/memory/ikru_history.db` and find your messages.

**Day 3 — Hardware bring-up**
- Flash the head and body. Watch both Serial Monitors.
- Run `tests/robot/test_motors.py` (wheels off the ground) and `tests/robot/test_ultrasonic.py`.
- Type commands in the body's Serial Monitor: `HAPPY`, `DISPLAY:Hello`, `LOOK:0.5:0`, `SOUND:giggle`.

**Day 4 — Full system**
- `python run.py`. Walk through the four bring-up stages. Ask a visual question. Ask it to find an object.
- Calibrate roaming with `tests/robot/test_roam_calibration.py`.

**Day 5 — First change**
- Do Recipe B (a new sequence), then Recipe A (a new action).
- Pick one item from Part 17 (for example, mapping `dance`/`sing` to sequences) and fix it with a unit test.

**Checklist: you're ready to contribute when you can answer…**
- [ ] Which three computers make up IKRU, and what does each run?
- [ ] What text travels over the WebSocket when IKRU looks happy?
- [ ] Where does the LLM learn which actions exist?
- [ ] Why does IKRU speak before it moves?
- [ ] What stops IKRU from roaming off the desk (three mechanisms)?
- [ ] Where is your name stored, and how does it get into the prompt?
- [ ] What happens to the autonomous brain the instant you start speaking?
- [ ] Why are face commands ignored right after the robot boots?

---

*Generated from a full read of the repository source. When you change behaviour, update the relevant Part here. It's much cheaper than rediscovering it later.*
