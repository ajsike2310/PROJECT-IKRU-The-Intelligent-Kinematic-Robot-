/**
 * PROJECT IKRU — Professional Companion UI Controller
 * Handles boot sequence animation timing, real-time WebSocket telemetry,
 * kinematic motor actuation, simulated OLED eye rendering, and Chatterbox TTS.
 */

// Application Configuration
let currentRobotIp = "192.168.1.42";
let currentCamIp = "192.168.4.1";
let nudgeDuration = 0.5;
let activeEmotion = "happy";
let emotionTimerId = null;

// ============================================================
// 1. BOOT SEQUENCE CONTROLLER (~1.4s)
// ============================================================
function runBootSequence() {
  document.body.classList.remove("boot-complete");
  document.body.classList.add("loading");

  const bootStatusText = document.querySelector("#bootStatus .status-text");
  if (bootStatusText) {
    bootStatusText.textContent = "INITIALIZING KINEMATICS...";
  }

  // Stage 1 -> Stage 2: Words Assembly & Subsystem Check (~0.7s)
  setTimeout(() => {
    if (bootStatusText) {
      bootStatusText.textContent = "MOUNTING ESP32 HARDWARE...";
    }
  }, 700);

  // Stage 2 -> Stage 3: Eye Wake & Ready Beacon (~1.2s)
  setTimeout(() => {
    if (bootStatusText) {
      bootStatusText.textContent = "SYSTEM READY // ONLINE";
    }
  }, 1200);

  // Dissolve to Main Dashboard (~1.45s)
  setTimeout(() => {
    document.body.classList.remove("loading");
    document.body.classList.add("boot-complete");
    appendLog("[BOOT] Boot sequence complete. Kinematic kernel active.", "sys");
  }, 1450);
}

function replayBootSequence() {
  appendLog("[SYSTEM] Reboot requested by operator.", "sys");
  runBootSequence();
}

// ============================================================
// 2. NETWORK TELEMETRY & STATUS POLLING
// ============================================================
async function fetchStatus() {
  const t0 = performance.now();
  try {
    const res = await fetch(`/api/status?ip=${encodeURIComponent(currentRobotIp)}`, { cache: "no-store" });
    const latency = Math.round(performance.now() - t0);

    if (res.ok) {
      const data = await res.json();
      updateConnectionStatus(data.status === "online", latency);
    } else {
      updateConnectionStatus(false, latency);
    }
  } catch (err) {
    updateConnectionStatus(false, 0);
  }
}

function updateConnectionStatus(isOnline, latency) {
  const pill = document.getElementById("connPill");
  const text = document.getElementById("connText");
  const displayIp = document.getElementById("displayRobotIp");
  const barPing = document.getElementById("barPingText");

  displayIp.textContent = `${currentRobotIp}:81`;

  if (isOnline) {
    pill.classList.remove("offline");
    pill.classList.add("online");
    text.textContent = "ROBOT ONLINE";
    barPing.textContent = `PING: ${latency}ms`;
  } else {
    pill.classList.remove("online");
    pill.classList.add("offline");
    text.textContent = "STANDBY / RECONNECTING";
    barPing.textContent = `PING: --`;
  }
}

// ============================================================
// 3. KINEMATICS & MOTOR ACTUATION
// ============================================================
async function sendMovement(direction, customDuration = null) {
  const dur = customDuration !== null ? customDuration : nudgeDuration;
  let cmd = `MOVE:${direction.toUpperCase()}:${dur}`;
  if (direction === "stop") cmd = "STOP";
  if (direction === "dance") cmd = "DANCE";
  if (direction === "sing") cmd = "SING";

  appendLog(`[DRV8833] ${cmd}`, "info");

  try {
    const res = await fetch("/api/robot/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: currentRobotIp, command: cmd })
    });
    const data = await res.json();
    if (!data.success) {
      appendLog(`[DRV8833 ERROR] ${data.error || "Execution failed"}`, "error");
    }
  } catch (err) {
    appendLog(`[DRV8833 NET] Failed to dispatch: ${err.message}`, "error");
  }
}

function updateNudgeDuration(val) {
  nudgeDuration = parseFloat(val);
  document.getElementById("nudgeSliderVal").textContent = `${nudgeDuration.toFixed(1)}s`;
  document.getElementById("nudgeDurationLabel").textContent = `${nudgeDuration.toFixed(1)}s NUDGE`;
}

// Keyboard arrow navigation
window.addEventListener("keydown", (e) => {
  if (["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;

  if (e.key === "ArrowUp") {
    e.preventDefault();
    highlightDpadBtn(".btn-up");
    sendMovement("forward");
  } else if (e.key === "ArrowDown") {
    e.preventDefault();
    highlightDpadBtn(".btn-down");
    sendMovement("backward");
  } else if (e.key === "ArrowLeft") {
    e.preventDefault();
    highlightDpadBtn(".btn-left");
    sendMovement("left");
  } else if (e.key === "ArrowRight") {
    e.preventDefault();
    highlightDpadBtn(".btn-right");
    sendMovement("right");
  } else if (e.key === " " || e.key === "Escape") {
    e.preventDefault();
    highlightDpadBtn(".btn-stop");
    sendMovement("stop");
  }
});

function highlightDpadBtn(selector) {
  const btn = document.querySelector(selector);
  if (btn) {
    btn.classList.add("active-key");
    setTimeout(() => btn.classList.remove("active-key"), 180);
  }
}

// ============================================================
// 4. OLED EYE EMULATOR & EXPRESSIONS PALETTE
// ============================================================
async function setEmotion(emotion, duration = 4.0) {
  activeEmotion = emotion.toLowerCase();
  const glass = document.getElementById("oledGlass");
  const badge = document.getElementById("activeEmotionBadge");
  const timer = document.getElementById("oledTimer");

  // Remove previous emotion classes
  glass.className = `oled-glass ${activeEmotion}`;
  badge.textContent = activeEmotion.toUpperCase();

  // Highlight active palette button
  document.querySelectorAll(".emo-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.emo === activeEmotion);
  });

  appendLog(`[OLED] Emotion face set to [${activeEmotion.toUpperCase()}]`, "info");

  // Send to physical robot
  try {
    fetch("/api/robot/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: currentRobotIp, command: `EMOTION:${activeEmotion}` })
    });
  } catch (err) {
    console.error(err);
  }

  // Duration countdown timer
  if (emotionTimerId) clearInterval(emotionTimerId);
  let remaining = duration;
  timer.textContent = `DURATION: ${remaining.toFixed(1)}s`;

  emotionTimerId = setInterval(() => {
    remaining -= 0.5;
    if (remaining <= 0) {
      clearInterval(emotionTimerId);
      timer.textContent = "DURATION: STEADY";
    } else {
      timer.textContent = `DURATION: ${remaining.toFixed(1)}s`;
    }
  }, 500);
}

// ============================================================
// 5. NEURAL VOICE & PARALINGUISTIC SOUND TAGS
// ============================================================
function insertVocalTag(tag) {
  const textarea = document.getElementById("ttsTextInput");
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const text = textarea.value;

  textarea.value = text.substring(0, start) + ` ${tag} ` + text.substring(end);
  textarea.focus();
  textarea.selectionStart = textarea.selectionEnd = start + tag.length + 2;
  appendLog(`[VOICE] Injected paralinguistic sound token: ${tag}`, "sys");
}

async function synthesizeSpeech() {
  const textInput = document.getElementById("ttsTextInput");
  const text = textInput.value.trim();
  if (!text) return;

  const playPc = document.getElementById("chkPlayPC").checked;
  const streamRobot = document.getElementById("chkStreamRobot").checked;
  const btnSpeak = document.getElementById("btnSpeak");
  const voiceBadge = document.getElementById("voiceStatusBadge");

  btnSpeak.disabled = true;
  btnSpeak.innerHTML = `<span>SYNTHESIZING...</span>`;
  voiceBadge.textContent = "GENERATING...";
  appendLog(`[TTS] Synthesizing: "${text}"`, "info");

  try {
    const res = await fetch("/api/audio/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: text,
        ip: currentRobotIp,
        play_pc: playPc,
        stream_robot: streamRobot
      })
    });

    const data = await res.json();
    if (data.success) {
      appendLog(`[TTS OK] Synthesized ${data.duration.toFixed(2)}s audio stream.`, "success");
      voiceBadge.textContent = `PLAYING (${data.duration.toFixed(1)}s)`;
      setTimeout(() => {
        voiceBadge.textContent = "44.1kHz PCM";
      }, (data.duration || 3) * 1000);
    } else {
      appendLog(`[TTS ERROR] ${data.error || "Failed"}`, "error");
      voiceBadge.textContent = "ERR";
    }
  } catch (err) {
    appendLog(`[TTS NET] Error: ${err.message}`, "error");
  } finally {
    btnSpeak.disabled = false;
    btnSpeak.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"></polygon><path d="M19.07 4.93a10 10 0 0 1 0 14.14M15.54 8.46a5 5 0 0 1 0 7.07"></path></svg>
      <span>SYNTHESIZE & SPEAK</span>
    `;
  }
}

// ============================================================
// 6. TELEMETRY EVENT LOG STREAM
// ============================================================
function appendLog(message, type = "normal") {
  const box = document.getElementById("logStreamBox");
  if (!box) return;

  const now = new Date();
  const timeStr = now.toTimeString().split(" ")[0];
  const div = document.createElement("div");
  div.className = `log-entry ${type}`;
  div.textContent = `[${timeStr}] ${message}`;

  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function clearTelemetryLog() {
  const box = document.getElementById("logStreamBox");
  if (box) {
    box.innerHTML = `<div class="log-entry sys">[SYSTEM] Log stream cleared.</div>`;
  }
}

// ============================================================
// 7. SETTINGS & PROVISIONING MODAL
// ============================================================
function toggleSettingsModal() {
  const modal = document.getElementById("settingsModal");
  modal.classList.toggle("open");
}

function saveSettings() {
  const newIp = document.getElementById("cfgRobotIp").value.trim();
  const newCam = document.getElementById("cfgCamIp").value.trim();
  if (newIp) currentRobotIp = newIp;
  if (newCam) currentCamIp = newCam;

  toggleSettingsModal();
  appendLog(`[CONFIG] Applied settings: Robot=${currentRobotIp}, Cam=${currentCamIp}`, "sys");
  fetchStatus();
}

async function scanNetworkNodes() {
  appendLog("[SCAN] Probing subnet for robot nodes...", "sys");
  try {
    const res = await fetch("/api/scan");
    const data = await res.json();
    if (data.nodes && data.nodes.length > 0) {
      appendLog(`[SCAN] Discovered ${data.nodes.length} nodes on subnet.`, "success");
      data.nodes.forEach(n => appendLog(` - ${n.type} at ${n.ip}:${n.port}`, "success"));
    } else {
      appendLog("[SCAN] No active nodes discovered.", "info");
    }
  } catch (err) {
    appendLog(`[SCAN ERR] ${err.message}`, "error");
  }
}

async function provisionWiFi() {
  const ssid = document.getElementById("cfgSsid").value.trim();
  const pass = document.getElementById("cfgPass").value.trim();
  if (!ssid) {
    alert("Please enter a Wi-Fi SSID");
    return;
  }

  appendLog(`[WIFI] Provisioning credentials for SSID: ${ssid}...`, "sys");
  try {
    const res = await fetch("/api/robot/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: currentRobotIp, command: `SET_WIFI:${ssid}:${pass}` })
    });
    const data = await res.json();
    if (data.success) {
      appendLog("[WIFI] Credentials sent. ESP32 switching network...", "success");
    }
  } catch (err) {
    appendLog(`[WIFI ERR] ${err.message}`, "error");
  }
}

// ============================================================
// 8. CONVERSATIONAL COMPANION // TALK TO IKRU
// ============================================================
let speechRecognitionInstance = null;
let isListening = false;

function sendQuickPrompt(promptText) {
  const input = document.getElementById("chatTextInput");
  input.value = promptText;
  sendChatMessage();
}

async function clearChatHistory() {
  try {
    const res = await fetch("/api/chat/clear", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      const transcript = document.getElementById("chatTranscriptBox");
      if (transcript) {
        transcript.innerHTML = `
          <div class="chat-msg assistant">
            <div class="chat-sender">
              <span class="sender-name">IKRU</span>
              <span class="emo-tag">[GLEE]</span>
            </div>
            <div class="chat-bubble">
              Memory reset! I am ready for new questions and commands.
            </div>
          </div>
        `;
      }
      appendLog("[CHAT] Conversation memory reset successfully.", "sys");
    }
  } catch (err) {
    appendLog(`[CHAT ERR] Could not clear memory: ${err.message}`, "error");
  }
}

async function sendChatMessage() {
  const input = document.getElementById("chatTextInput");
  const prompt = input.value.trim();
  if (!prompt) return;

  const btnSend = document.getElementById("btnSendChat");
  const statusBadge = document.getElementById("chatEngineStatus");
  const statusText = document.getElementById("chatStatusText");
  const streamRobot = document.getElementById("chkChatStreamRobot").checked;
  const playPc = document.getElementById("chkChatPlayPC").checked;
  const engineRadio = document.querySelector('input[name="chatTtsEngine"]:checked');
  const ttsEngine = engineRadio ? engineRadio.value : "edge";

  // Append user bubble
  appendChatBubble("user", "YOU", prompt);
  input.value = "";
  btnSend.disabled = true;

  const isVisual = ["see", "look", "watch", "camera", "view", "show", "color", "wearing"].some(kw => prompt.toLowerCase().includes(kw));
  if (isVisual) {
    statusBadge.textContent = "VLM VISION...";
    statusText.textContent = "ANALYZING SCENE...";
  } else {
    statusBadge.textContent = "THINKING...";
    statusText.textContent = ttsEngine === "chatterbox" ? "AI & NEURAL VOICE..." : "AI GENERATING...";
  }
  appendLog(`[CHAT] User: "${prompt}" [Engine: ${ttsEngine}]`, "info");

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: prompt,
        ip: currentRobotIp,
        play_pc: playPc,
        stream_robot: streamRobot,
        engine: ttsEngine
      })
    });

    const data = await res.json();
    if (data.success) {
      // Find primary emotion from segments or response
      let emo = "happy";
      if (data.segments && data.segments.length > 0) {
        emo = data.segments[0][0] || "happy";
      }

      const speechDuration = Number(data.duration) || 2.5;

      // Update OLED face emulator on UI
      setEmotion(emo, Math.max(3.0, speechDuration));

      // Append assistant bubble
      appendChatBubble("assistant", "IKRU", data.response, emo);

      // Play synthesized audio directly in browser if PC speaker enabled
      if (playPc && data.audio_url) {
        try {
          const browserAudio = new Audio(`${data.audio_url}?t=${Date.now()}`);
          browserAudio.play().catch(e => {
            console.warn("[Audio] Browser autoplay policy notice:", e);
          });
        } catch (audioErr) {
          console.warn("[Audio] HTML5 audio error:", audioErr);
        }
      }

      // Display visual scene observation if VLM was triggered
      if (data.visual_context) {
        const obsElem = document.getElementById("cameraObsText");
        if (obsElem) obsElem.textContent = `"${data.visual_context}"`;
        appendLog(`[VLM SCENE] "${data.visual_context}"`, "sys");
      }

      // Tool call logging
      if (data.tools && data.tools.length > 0) {
        data.tools.forEach(t => {
          appendLog(`[TOOL CALL] Executed ${t.tool}(${JSON.stringify(t.parameters || {})})`, "sys");
        });
      }

      statusBadge.textContent = "OLLAMA // READY";
      statusText.textContent = `SPEAKING (${speechDuration.toFixed(1)}s)`;
      setTimeout(() => {
        statusText.textContent = "IDLE";
      }, (speechDuration + 0.5) * 1000);
      appendLog(`[CHAT] Ikru: "${data.response}"`, "success");
    } else {
      appendChatBubble("assistant", "SYSTEM", `Error: ${data.error || "Generation failed"}`);
      statusBadge.textContent = "ERROR";
      statusText.textContent = "FAILED";
      appendLog(`[CHAT ERR] ${data.error || "Failed"}`, "error");
    }
  } catch (err) {
    appendChatBubble("assistant", "SYSTEM", `Network error: ${err.message}`);
    statusBadge.textContent = "OFFLINE";
    statusText.textContent = "NET ERROR";
    appendLog(`[CHAT NET] ${err.message}`, "error");
  } finally {
    btnSend.disabled = false;
  }
}

function appendChatBubble(role, senderName, text, emotionTag = null) {
  const transcript = document.getElementById("chatTranscriptBox");
  if (!transcript) return;

  const msgDiv = document.createElement("div");
  msgDiv.className = `chat-msg ${role}`;

  const senderDiv = document.createElement("div");
  senderDiv.className = "chat-sender";

  const nameSpan = document.createElement("span");
  nameSpan.className = "sender-name";
  nameSpan.textContent = senderName;
  senderDiv.appendChild(nameSpan);

  if (emotionTag) {
    const emoSpan = document.createElement("span");
    emoSpan.className = "emo-tag";
    emoSpan.textContent = `[${emotionTag.toUpperCase()}]`;
    senderDiv.appendChild(emoSpan);
  }

  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "chat-bubble";
  bubbleDiv.textContent = text;

  msgDiv.appendChild(senderDiv);
  msgDiv.appendChild(bubbleDiv);

  transcript.appendChild(msgDiv);
  transcript.scrollTop = transcript.scrollHeight;
}

function toggleVoiceInput() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    alert("Web Speech API is not supported in this browser. Please use Google Chrome or Microsoft Edge for voice input.");
    appendLog("[MIC] Web Speech API not supported in this browser.", "error");
    return;
  }

  const btnMic = document.getElementById("btnMic");
  const statusText = document.getElementById("chatStatusText");

  if (isListening && speechRecognitionInstance) {
    speechRecognitionInstance.stop();
    return;
  }

  try {
    speechRecognitionInstance = new SpeechRecognition();
    speechRecognitionInstance.continuous = false;
    speechRecognitionInstance.interimResults = false;
    speechRecognitionInstance.lang = "en-US";

    speechRecognitionInstance.onstart = () => {
      isListening = true;
      btnMic.classList.add("listening");
      statusText.textContent = "LISTENING...";
      appendLog("[MIC] Microphone listening... Speak your command or question.", "sys");
    };

    speechRecognitionInstance.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      appendLog(`[MIC] Heard: "${transcript}"`, "info");
      document.getElementById("chatTextInput").value = transcript;
      sendChatMessage();
    };

    speechRecognitionInstance.onerror = (event) => {
      console.warn("[MIC] Speech recognition error:", event.error);
      appendLog(`[MIC ERROR] ${event.error}`, "error");
      stopVoiceInputState();
    };

    speechRecognitionInstance.onend = () => {
      stopVoiceInputState();
    };

    speechRecognitionInstance.start();
  } catch (err) {
    console.error(err);
    stopVoiceInputState();
  }
}

function stopVoiceInputState() {
  isListening = false;
  const btnMic = document.getElementById("btnMic");
  if (btnMic) btnMic.classList.remove("listening");
  const statusText = document.getElementById("chatStatusText");
  if (statusText && statusText.textContent === "LISTENING...") {
    statusText.textContent = "IDLE";
  }
}

// ============================================================
// 9. MASTER VOLUME CONTROL
// ============================================================
let lastNonZeroVolume = 100;
let volumeDebounceTimer = null;

function setVolume(val) {
  const vol = parseInt(val, 10);
  const slider = document.getElementById("masterVolSlider");
  const label = document.getElementById("masterVolVal");
  const icon = document.getElementById("volMuteIcon");

  if (slider) slider.value = vol;
  if (label) label.textContent = `${vol}%`;

  if (icon) {
    if (vol === 0) icon.textContent = "🔇";
    else if (vol < 40) icon.textContent = "🔉";
    else icon.textContent = "🔊";
  }

  if (vol > 0) lastNonZeroVolume = vol;

  if (volumeDebounceTimer) clearTimeout(volumeDebounceTimer);
  volumeDebounceTimer = setTimeout(async () => {
    try {
      await fetch("/api/audio/volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ volume: vol })
      });
      appendLog(`[VOLUME] Master Volume set to ${vol}%`, "info");
    } catch (err) {
      console.warn("Volume set error:", err);
    }
  }, 120);
}

function toggleMute() {
  const slider = document.getElementById("masterVolSlider");
  if (!slider) return;
  const current = parseInt(slider.value, 10);
  if (current > 0) {
    setVolume(0);
  } else {
    setVolume(lastNonZeroVolume || 100);
  }
}

// ============================================================
// 10. WI-FI & NETWORK PROVISIONING
// ============================================================
async function scanWiFiNetworks() {
  const badge = document.getElementById("wifiStatusBadge");
  badge.textContent = "SCANNING...";
  appendLog("[WIFI] Scanning nearby Wi-Fi SSIDs...", "sys");

  try {
    const res = await fetch("/api/wifi/scan");
    const data = await res.json();
    if (data.success && data.networks && data.networks.length > 0) {
      const datalist = document.getElementById("wifiNetworkList");
      datalist.innerHTML = "";
      data.networks.forEach(net => {
        const opt = document.createElement("option");
        opt.value = net.ssid;
        opt.label = `${net.ssid} (${net.signal})`;
        datalist.appendChild(opt);
      });
      appendLog(`[WIFI] Found ${data.networks.length} networks.`, "success");
      badge.textContent = "READY";
    } else {
      appendLog("[WIFI] No networks found via scan.", "info");
      badge.textContent = "READY";
    }
  } catch (err) {
    appendLog(`[WIFI SCAN ERR] ${err.message}`, "error");
    badge.textContent = "ERR";
  }
}

function togglePassVisibility() {
  const input = document.getElementById("wifiPassInput");
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
}

async function applyWiFiCredentials() {
  const ssid = document.getElementById("wifiSsidInput").value.trim();
  const pass = document.getElementById("wifiPassInput").value.trim();
  const methodRadio = document.querySelector('input[name="wifiMethod"]:checked');
  const method = methodRadio ? methodRadio.value : "auto";
  const btn = document.getElementById("btnConnectWiFi");
  const badge = document.getElementById("wifiStatusBadge");

  if (!ssid) {
    alert("Please enter a Wi-Fi SSID");
    return;
  }

  btn.disabled = true;
  btn.innerHTML = `<span>CONNECTING...</span>`;
  badge.textContent = "CONNECTING...";
  appendLog(`[WIFI] Provisioning SSID "${ssid}" via ${method.toUpperCase()}...`, "info");

  try {
    const res = await fetch("/api/wifi/configure", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ssid: ssid,
        password: pass,
        method: method,
        ip: currentRobotIp
      })
    });

    const data = await res.json();
    if (data.success) {
      appendLog(`[WIFI OK] ${data.message || "Credentials dispatched successfully"}`, "success");
      badge.textContent = "CONNECTED";
      setTimeout(() => { badge.textContent = "READY"; }, 4000);
    } else {
      appendLog(`[WIFI ERROR] ${data.error || "Configuration failed"}`, "error");
      badge.textContent = "ERR";
    }
  } catch (err) {
    appendLog(`[WIFI NET ERR] ${err.message}`, "error");
    badge.textContent = "NET ERR";
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12.55a11 11 0 0 1 14.08 0M1.42 9a16 16 0 0 1 21.16 0M8.53 16.11a6 6 0 0 1 6.95 0M12 20h.01"/></svg>
      <span>CONNECT IKRU TO WI-FI</span>
    `;
  }
}

// ============================================================
// 11. CHATTERBOX ZERO-SHOT VOICE CLONING STUDIO
// ============================================================
let currentAudioBase64 = null;
let mediaRecorder = null;
let recordedAudioChunks = [];

function handleVoiceFileSelect(input) {
  const file = input.files && input.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = (e) => {
    currentAudioBase64 = e.target.result;
    const player = document.getElementById("cloneAudioPreview");
    const previewBox = document.getElementById("audioPreviewBox");
    const previewTitle = document.getElementById("previewTitle");
    const nameInput = document.getElementById("cloneVoiceName");
    const btnApply = document.getElementById("btnApplyClone");

    player.src = currentAudioBase64;
    previewBox.style.display = "block";
    previewTitle.textContent = `File: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    if (!nameInput.value) {
      nameInput.value = file.name.replace(/\.[^/.]+$/, "");
    }
    btnApply.disabled = false;
    appendLog(`[CLONE] Loaded audio sample: ${file.name}`, "info");
  };
  reader.readAsDataURL(file);
}

async function toggleVoiceSampleRecord() {
  const btn = document.getElementById("btnRecordSample");
  const btnText = document.getElementById("btnRecordSampleText");
  const recDot = document.getElementById("recDot");

  if (mediaRecorder && mediaRecorder.state === "recording") {
    mediaRecorder.stop();
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    recordedAudioChunks = [];
    mediaRecorder = new MediaRecorder(stream);

    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) recordedAudioChunks.push(e.data);
    };

    mediaRecorder.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      btn.classList.remove("recording");
      btnText.textContent = "RECORD SAMPLE";

      const audioBlob = new Blob(recordedAudioChunks, { type: "audio/wav" });
      const reader = new FileReader();
      reader.onload = (e) => {
        currentAudioBase64 = e.target.result;
        const player = document.getElementById("cloneAudioPreview");
        const previewBox = document.getElementById("audioPreviewBox");
        const previewTitle = document.getElementById("previewTitle");
        const nameInput = document.getElementById("cloneVoiceName");
        const btnApply = document.getElementById("btnApplyClone");

        player.src = currentAudioBase64;
        previewBox.style.display = "block";
        previewTitle.textContent = `Recorded Voice Sample (${(audioBlob.size / 1024).toFixed(1)} KB)`;
        if (!nameInput.value) {
          nameInput.value = `custom_voice_${Math.floor(Date.now() / 1000).toString().slice(-4)}`;
        }
        btnApply.disabled = false;
        appendLog(`[CLONE] Recorded voice sample (${(audioBlob.size / 1024).toFixed(1)} KB)`, "success");
      };
      reader.readAsDataURL(audioBlob);
    };

    mediaRecorder.start();
    btn.classList.add("recording");
    btnText.textContent = "STOP RECORDING";
    appendLog("[CLONE] Recording reference voice... Speak for 5-15 seconds.", "sys");
  } catch (err) {
    alert("Microphone access is required to record a voice sample.");
    appendLog(`[CLONE MIC ERR] ${err.message}`, "error");
  }
}

async function saveAndApplyClonedVoice() {
  if (!currentAudioBase64) {
    alert("Please choose an audio file or record a sample first.");
    return;
  }

  const nameInput = document.getElementById("cloneVoiceName");
  const name = nameInput.value.trim() || "custom_voice";
  const btn = document.getElementById("btnApplyClone");
  const badge = document.getElementById("activeVoiceBadge");

  btn.disabled = true;
  btn.innerHTML = `<span>CLONING...</span>`;
  badge.textContent = "CLONING...";
  appendLog(`[CLONE] Conditioning Chatterbox with "${name}" reference audio...`, "info");

  try {
    const res = await fetch("/api/voice/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name,
        audio_data: currentAudioBase64
      })
    });

    const data = await res.json();
    if (data.success) {
      appendLog(`[CLONE OK] Zero-shot voice profile "${name}" activated!`, "success");
      badge.textContent = name.toUpperCase();
      const topPill = document.getElementById("topVoiceEngineVal");
      if (topPill) topPill.textContent = `CLONE: ${name.toUpperCase()}`;
      fetchVoiceProfiles();
    } else {
      appendLog(`[CLONE ERR] ${data.error || "Cloning failed"}`, "error");
      badge.textContent = "ERR";
    }
  } catch (err) {
    appendLog(`[CLONE NET ERR] ${err.message}`, "error");
    badge.textContent = "NET ERR";
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<span>CLONE & ACTIVATE</span>`;
  }
}

async function fetchVoiceProfiles() {
  try {
    const res = await fetch("/api/voice/list");
    const data = await res.json();
    if (!data.success) return;

    const list = document.getElementById("voiceProfilesList");
    const activeBadge = document.getElementById("activeVoiceBadge");
    const topPill = document.getElementById("topVoiceEngineVal");

    if (list) {
      list.innerHTML = "";

      // Default Profile
      const isDefaultActive = !data.active || data.active === "default";
      const defaultDiv = document.createElement("div");
      defaultDiv.className = `profile-item ${isDefaultActive ? "active" : ""}`;
      defaultDiv.onclick = () => selectVoiceProfile("default");
      defaultDiv.innerHTML = `
        <span class="profile-name">Default Ikru (Neural)</span>
        ${isDefaultActive ? '<span class="badge-active">ACTIVE</span>' : ""}
      `;
      list.appendChild(defaultDiv);

      // Custom Profiles
      if (data.voices && data.voices.length > 0) {
        data.voices.forEach(v => {
          const isActive = data.active === v.name;
          const item = document.createElement("div");
          item.className = `profile-item ${isActive ? "active" : ""}`;
          item.onclick = () => selectVoiceProfile(v.name);
          item.innerHTML = `
            <span class="profile-name">${v.name}</span>
            ${isActive ? '<span class="badge-active">ACTIVE</span>' : ""}
          `;
          list.appendChild(item);
        });
      }
    }

    if (activeBadge) {
      activeBadge.textContent = (data.active || "DEFAULT IKRU").toUpperCase();
    }
    if (topPill && data.active && data.active !== "default") {
      topPill.textContent = `CLONE: ${data.active.toUpperCase()}`;
    }
  } catch (err) {
    console.warn("fetchVoiceProfiles error:", err);
  }
}

async function selectVoiceProfile(name) {
  try {
    const res = await fetch("/api/voice/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: name })
    });
    const data = await res.json();
    if (data.success) {
      appendLog(`[VOICE] Switched active voice profile to: ${name}`, "success");
      fetchVoiceProfiles();
    }
  } catch (err) {
    appendLog(`[VOICE ERR] ${err.message}`, "error");
  }
}

// ============================================================
// 12. CAMERA STREAMING & TELEMETRY
// ============================================================
let cameraStreamActive = false;
let cameraPollingInterval = null;

function initCameraFeed() {
  const img = document.getElementById("camStream");
  if (!img) return;

  img.src = `/api/camera/stream?t=${Date.now()}`;
  cameraStreamActive = true;

  img.onload = () => {
    const badge = document.getElementById("camStatusBadge");
    if (badge && !badge.classList.contains("live")) {
      badge.className = "card-status-badge live";
    }
  };

  img.onerror = () => {
    if (cameraStreamActive) {
      console.warn("[Camera] MJPEG stream dropped or unsupported, switching to snapshot polling mode");
      cameraStreamActive = false;
      startFramePollingMode(img);
    }
  };
}

function startFramePollingMode(img) {
  if (cameraPollingInterval) clearInterval(cameraPollingInterval);
  let inFlight = false;
  cameraPollingInterval = setInterval(async () => {
    if (inFlight) return;
    inFlight = true;
    try {
      const res = await fetch(`/api/camera/frame?t=${Date.now()}`);
      if (res.ok) {
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const oldSrc = img.src;
        img.src = url;
        if (oldSrc && oldSrc.startsWith("blob:")) {
          setTimeout(() => URL.revokeObjectURL(oldSrc), 100);
        }
      }
    } catch (err) {
      console.debug("Camera poll frame error:", err);
    } finally {
      inFlight = false;
    }
  }, 40);
}

async function updateCameraStatus() {
  try {
    const res = await fetch("/api/camera/status");
    const data = await res.json();
    const badge = document.getElementById("camStatusBadge");
    const telem = document.querySelector(".vf-telemetry.top-left");
    if (badge) {
      if (data.connected) {
        badge.className = "card-status-badge live";
        badge.textContent = `LIVE UDP (${data.fps} FPS)`;
      } else {
        badge.className = "card-status-badge";
        badge.textContent = "STANDBY";
      }
    }
    if (telem) {
      telem.textContent = `FPS: ${data.fps} // CAM: ${data.cam_ip}`;
    }
  } catch (e) {}
}

async function triggerSceneObservation() {
  const btn = document.getElementById("btnObserveScene");
  const obsElem = document.getElementById("cameraObsText");
  if (btn) {
    btn.textContent = "👁️ OBSERVING...";
    btn.disabled = true;
  }
  appendLog("[VLM] Capturing camera frame for Qwen-VL scene reasoning...", "sys");
  try {
    const res = await fetch("/api/vision/observe");
    const data = await res.json();
    if (data.success && data.observation) {
      if (obsElem) obsElem.textContent = `"${data.observation}"`;
      appendLog(`[VLM SCENE] "${data.observation}"`, "success");
    } else {
      appendLog(`[VLM WARN] ${data.observation || "No observation available"}`, "warning");
    }
  } catch (err) {
    appendLog(`[VLM ERR] ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.textContent = "👁️ OBSERVE SCENE";
      btn.disabled = false;
    }
  }
}

// ============================================================
// INITIALIZATION
// ============================================================
window.addEventListener("DOMContentLoaded", () => {
  runBootSequence();
  fetchStatus();
  fetchVoiceProfiles();
  initCameraFeed();
  updateCameraStatus();
  setInterval(fetchStatus, 3000);
  setInterval(updateCameraStatus, 3000);
});
