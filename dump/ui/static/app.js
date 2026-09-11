// PROJECT IKRU — Companion Studio Dashboard Logic

let currentMode = "wifi";
let isAssistantRunning = false;
let logPollInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  fetchStatus();
  fetchWifiConfig();
  fetchComPorts();
  setInterval(fetchStatus, 3000);
});

// Mode Switching: Home Wi-Fi vs Portable AP
function setMode(mode) {
  currentMode = mode;
  const btnWifi = document.getElementById("btnModeWifi");
  const btnAP = document.getElementById("btnModeAP");
  const inputRobot = document.getElementById("inputRobotIp");
  const inputCam = document.getElementById("inputCamIp");

  if (mode === "wifi") {
    btnWifi.classList.add("active");
    btnAP.classList.remove("active");
    inputRobot.value = "192.168.1.34";
    inputCam.value = "192.168.4.1";
  } else {
    btnAP.classList.add("active");
    btnWifi.classList.remove("active");
    inputRobot.value = "192.168.4.2";
    inputCam.value = "192.168.4.1";
  }
  fetchStatus();
}

// Fetch Diagnostics & Health Status
async function fetchStatus() {
  const robotIp = document.getElementById("inputRobotIp").value.trim();
  const camIp = document.getElementById("inputCamIp").value.trim();

  try {
    const res = await fetch(`/api/status?ip=${encodeURIComponent(robotIp)}&cam_ip=${encodeURIComponent(camIp)}`);
    if (!res.ok) return;
    const data = await res.json();

    // 1. Robot Body Status
    const pillRobot = document.getElementById("pillRobot");
    const robotDetails = document.getElementById("robotDetails");
    if (data.robot_connected) {
      pillRobot.className = "status-pill online";
      pillRobot.textContent = "Online";
      robotDetails.textContent = `ws://${data.robot_ip}:81 (Connected)`;
      if (data.robot_ip && data.robot_ip !== robotIp) {
        document.getElementById("inputRobotIp").value = data.robot_ip;
      }
    } else {
      pillRobot.className = "status-pill offline";
      pillRobot.textContent = "Offline";
      robotDetails.textContent = `ws://${data.robot_ip}:81 (Unreachable)`;
    }

    // 2. Ollama Status
    const pillOllama = document.getElementById("pillOllama");
    const ollamaDetails = document.getElementById("ollamaDetails");
    if (data.ollama && data.ollama.running) {
      if (data.ollama.has_qwen) {
        pillOllama.className = "status-pill online";
        pillOllama.textContent = "Ready";
        ollamaDetails.textContent = "qwen2.5:3b available";
      } else {
        pillOllama.className = "status-pill pending";
        pillOllama.textContent = "Model Missing";
        ollamaDetails.textContent = "Run: ollama pull qwen2.5:3b";
      }
    } else {
      pillOllama.className = "status-pill offline";
      pillOllama.textContent = "Stopped";
      ollamaDetails.textContent = "Run: ollama serve";
    }

    // 3. ESP32-CAM Status
    const pillCam = document.getElementById("pillCam");
    const camDetails = document.getElementById("camDetails");
    if (data.cam_connected) {
      pillCam.className = "status-pill online";
      pillCam.textContent = "Connected";
      camDetails.textContent = `UDP Stream @ ${data.cam_ip}:2222`;
    } else {
      pillCam.className = "status-pill pending";
      pillCam.textContent = "No AP";
      camDetails.textContent = `Connect Wi-Fi to IKRU-CAM`;
    }

    // 4. Audio Streaming Server
    const audioDetails = document.getElementById("audioDetails");
    audioDetails.textContent = `http://${data.local_ip}:8000/ (Active)`;

    // 5. Global Header Pill
    const globalDot = document.getElementById("globalStatusDot");
    const globalText = document.getElementById("globalStatusText");
    if (data.robot_connected) {
      globalDot.className = "status-dot online";
      globalText.textContent = `Robot Online (${data.robot_ip})`;
    } else {
      globalDot.className = "status-dot offline";
      globalText.textContent = `Robot Offline (${data.robot_ip})`;
    }

    // 6. Assistant Running State
    isAssistantRunning = data.assistant_running;
    updateAssistantButtonState();

  } catch (err) {
    console.error("Status check failed:", err);
  }
}

// Auto-Scan Subnet for Robot
async function scanNetwork() {
  const btnScan = document.getElementById("btnScan");
  const scanBtnText = document.getElementById("scanBtnText");
  btnScan.disabled = true;
  scanBtnText.textContent = "⏳ Scanning...";

  try {
    const res = await fetch("/api/scan");
    const data = await res.json();
    if (data.found_robots && data.found_robots.length > 0) {
      const detectedIp = data.found_robots[0];
      document.getElementById("inputRobotIp").value = detectedIp;
      appendLog(`[Auto-Scan] Discovered ESP32 Robot at: ${detectedIp}`);
      fetchStatus();
    } else {
      appendLog(`[Auto-Scan] No robot detected on port 81. Make sure ESP32 is powered on.`);
    }
  } catch (err) {
    appendLog(`[Auto-Scan Error] ${err.message}`);
  } finally {
    btnScan.disabled = false;
    scanBtnText.textContent = "🔍 Auto-Scan";
  }
}

// Test Emotion
async function testEmotion(emotion) {
  const robotIp = document.getElementById("inputRobotIp").value.trim();
  appendLog(`[Test] Setting OLED emotion: ${emotion}`);
  try {
    const res = await fetch("/api/test/emotion", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: robotIp, emotion })
    });
    const data = await res.json();
    if (data.status === "ok") {
      if (data.resolved_ip && data.resolved_ip !== robotIp) {
        document.getElementById("inputRobotIp").value = data.resolved_ip;
        appendLog(`[Auto-Resolved] Connected to active robot at ${data.resolved_ip}`);
        fetchStatus();
      }
      appendLog(`[Test] OLED updated to: ${emotion}`);
    } else {
      appendLog(`[Test Error] ${data.message}`);
    }
  } catch (err) {
    appendLog(`[Test Error] Could not reach robot at ${robotIp}: ${err.message}`);
  }
}

// Test Motor Move
async function testMove(action) {
  const robotIp = document.getElementById("inputRobotIp").value.trim();
  appendLog(`[Test] Motor action: ${action}`);
  try {
    const res = await fetch("/api/test/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: robotIp, action, duration: 0.5 })
    });
    const data = await res.json();
    if (data.status === "ok") {
      if (data.resolved_ip && data.resolved_ip !== robotIp) {
        document.getElementById("inputRobotIp").value = data.resolved_ip;
        appendLog(`[Auto-Resolved] Connected to active robot at ${data.resolved_ip}`);
        fetchStatus();
      }
      appendLog(`[Test] Executed motor action: ${action}`);
    }
  } catch (err) {
    appendLog(`[Test Error] Motor error: ${err.message}`);
  }
}

// Test Speech
async function testSpeech() {
  const robotIp = document.getElementById("inputRobotIp").value.trim();
  const text = document.getElementById("inputSpeakText").value.trim();
  const voice = document.getElementById("selectVoice").value;
  const playPc = document.getElementById("checkTestPcAudio").checked;

  if (!text) return;

  appendLog(`[Speech Test] Synthesizing ("${voice}"${playPc ? " + PC speaker" : " [Robot Only]"}): "${text}"...`);
  try {
    const res = await fetch("/api/test/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: robotIp, text, voice, play_pc: playPc })
    });
    const data = await res.json();
    if (data.status === "ok") {
      if (data.resolved_ip && data.resolved_ip !== robotIp) {
        document.getElementById("inputRobotIp").value = data.resolved_ip;
        appendLog(`[Auto-Resolved] Connected to active robot at ${data.resolved_ip}`);
        fetchStatus();
      }
      appendLog(`[Speech Test] Audio streamed to robot: ${data.url} (${data.duration.toFixed(2)}s)`);
    } else {
      appendLog(`[Speech Error] ${data.message}`);
    }
  } catch (err) {
    appendLog(`[Speech Error] ${err.message}`);
  }
}

// Toggle Assistant Run / Stop
async function toggleAssistant() {
  const btnLaunch = document.getElementById("btnLaunch");
  const robotIp = document.getElementById("inputRobotIp").value.trim();
  const camIp = document.getElementById("inputCamIp").value.trim();
  const playPc = document.getElementById("checkLaunchPcAudio").checked;
  const noMic = document.getElementById("checkLaunchNoMic").checked;
  const noVision = document.getElementById("checkLaunchNoVision").checked;

  if (!isAssistantRunning) {
    // START
    appendLog(`[Launcher] Starting IKRU Assistant with Target IP: ${robotIp}...`);
    try {
      const res = await fetch("/api/assistant/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ip: robotIp,
          cam_ip: camIp,
          play_pc: playPc,
          no_mic: noMic,
          no_vision: noVision
        })
      });
      const data = await res.json();
      if (data.status === "started" || data.status === "already_running") {
        isAssistantRunning = true;
        updateAssistantButtonState();
        startLogPolling();
      }
    } catch (err) {
      appendLog(`[Launcher Error] Could not start: ${err.message}`);
    }
  } else {
    // STOP
    appendLog(`[Launcher] Stopping assistant...`);
    try {
      await fetch("/api/assistant/stop", { method: "POST" });
      isAssistantRunning = false;
      updateAssistantButtonState();
    } catch (err) {
      appendLog(`[Launcher Error] ${err.message}`);
    }
  }
}

function updateAssistantButtonState() {
  const btnLaunch = document.getElementById("btnLaunch");
  const launchBtnIcon = document.getElementById("launchBtnIcon");
  const launchBtnText = document.getElementById("launchBtnText");
  const pillAssistant = document.getElementById("pillAssistant");

  if (isAssistantRunning) {
    btnLaunch.className = "btn btn-launch running";
    launchBtnIcon.textContent = "⏹";
    launchBtnText.textContent = "Stop AI Assistant";
    pillAssistant.className = "status-pill online";
    pillAssistant.textContent = "Active";
    startLogPolling();
  } else {
    btnLaunch.className = "btn btn-launch";
    launchBtnIcon.textContent = "🚀";
    launchBtnText.textContent = "Start AI Assistant";
    pillAssistant.className = "status-pill offline";
    pillAssistant.textContent = "Stopped";
  }
}

function startLogPolling() {
  if (logPollInterval) return;
  logPollInterval = setInterval(async () => {
    try {
      const res = await fetch("/api/assistant/logs");
      const data = await res.json();
      if (data.logs && data.logs.length > 0) {
        renderLogs(data.logs);
      }
      if (!data.running && isAssistantRunning) {
        isAssistantRunning = false;
        updateAssistantButtonState();
        clearInterval(logPollInterval);
        logPollInterval = null;
      }
    } catch (err) {
      // Ignore polling errors
    }
  }, 1000);
}

function renderLogs(logs) {
  const terminal = document.getElementById("terminalOutput");
  terminal.innerHTML = "";
  logs.forEach(line => {
    const div = document.createElement("div");
    div.className = "log-line";
    div.textContent = line;
    terminal.appendChild(div);
  });
  terminal.scrollTop = terminal.scrollHeight;
}

function appendLog(line) {
  const terminal = document.getElementById("terminalOutput");
  const div = document.createElement("div");
  div.className = "log-line";
  div.textContent = line;
  terminal.appendChild(div);
  terminal.scrollTop = terminal.scrollHeight;
}

function clearLogs() {
  document.getElementById("terminalOutput").innerHTML = "";
}

// ============================================================
// WI-FI PROVISIONING & SERIAL UTILITIES
// ============================================================

let wifiPanelVisible = true;
function toggleWifiPanel() {
  const panel = document.getElementById("wifiProvisionPanel");
  const btn = document.getElementById("btnToggleWifiPanel");
  wifiPanelVisible = !wifiPanelVisible;
  panel.style.display = wifiPanelVisible ? "flex" : "none";
  btn.textContent = wifiPanelVisible ? "📶 Wi-Fi Provisioning & Credentials ▲" : "📶 Wi-Fi Provisioning & Credentials ▼";
}

function togglePasswordVisibility(inputId) {
  const input = document.getElementById(inputId);
  if (!input) return;
  input.type = input.type === "password" ? "text" : "password";
}

async function fetchWifiConfig() {
  try {
    const res = await fetch("/api/wifi/config");
    if (!res.ok) return;
    const data = await res.json();
    if (data.ssid) {
      document.getElementById("inputWifiSsid").value = data.ssid;
      const badge = document.getElementById("badgeCurrentFirmwareSsid");
      if (badge) badge.textContent = `Firmware Default: ${data.ssid}`;
    }
    if (data.pass) {
      document.getElementById("inputWifiPass").value = data.pass;
    }
  } catch (err) {
    console.error("Failed to load firmware wifi config:", err);
  }
}

async function fetchComPorts() {
  const select = document.getElementById("selectComPort");
  if (!select) return;
  select.innerHTML = '<option value="">Scanning...</option>';
  try {
    const res = await fetch("/api/serial/ports");
    const data = await res.json();
    select.innerHTML = "";
    if (data.ports && data.ports.length > 0) {
      let defaultSelected = false;
      data.ports.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.port;
        opt.textContent = `${p.port} (${p.description})`;
        // Prefer CH340 / CH9102 ESP32 body on COM7
        if (!defaultSelected && (p.port === "COM7" || p.description.includes("CH9102") || p.description.includes("CH340"))) {
          opt.selected = true;
          defaultSelected = true;
        }
        select.appendChild(opt);
      });
      appendLog(`[Serial] Detected ${data.ports.length} COM port(s). Selected: ${select.value}`);
    } else {
      select.innerHTML = '<option value="">No COM ports detected</option>';
      appendLog("[Serial] No COM ports found. Connect ESP32 via USB cable.");
    }
  } catch (err) {
    select.innerHTML = '<option value="">Failed to scan ports</option>';
    appendLog(`[Serial Error] ${err.message}`);
  }
}

async function pushWifiActive() {
  const robotIp = document.getElementById("inputRobotIp").value.trim();
  const ssid = document.getElementById("inputWifiSsid").value.trim();
  const pass = document.getElementById("inputWifiPass").value.trim();

  if (!ssid) {
    alert("Please enter a Wi-Fi SSID (network name).");
    return;
  }

  appendLog(`[Wi-Fi Provision] Pushing credentials for "${ssid}" to robot at ${robotIp}...`);
  try {
    const res = await fetch("/api/robot/wifi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: robotIp, ssid, pass })
    });
    const data = await res.json();
    if (data.status === "ok") {
      appendLog(`[Wi-Fi Provision] Success! Robot received new Wi-Fi and is reconnecting...`);
      appendLog(`[Wi-Fi Provision] Robot will save credentials to flash (NVS) and display new IP on OLED.`);
      setTimeout(scanNetwork, 4000);
    } else {
      appendLog(`[Wi-Fi Provision Error] ${data.message}`);
    }
  } catch (err) {
    appendLog(`[Wi-Fi Provision Error] ${err.message}`);
  }
}

async function pushWifiSerial() {
  const port = document.getElementById("selectComPort").value;
  const ssid = document.getElementById("inputWifiSsid").value.trim();
  const pass = document.getElementById("inputWifiPass").value.trim();

  if (!port) {
    alert("Please select a valid COM port. Connect ESP32 via USB and click 🔄.");
    return;
  }
  if (!ssid) {
    alert("Please enter a Wi-Fi SSID.");
    return;
  }

  appendLog(`[USB Serial] Sending Wi-Fi configuration for "${ssid}" to ${port}...`);
  appendLog(`[USB Serial] (Note: Ensure Arduino Serial Monitor is closed so port is accessible)`);
  try {
    const res = await fetch("/api/serial/wifi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ port, ssid, pass })
    });
    const data = await res.json();
    if (data.status === "ok") {
      appendLog(`[USB Serial Success] ${data.message}`);
      if (data.output && data.output.length > 0) {
        data.output.forEach(line => appendLog(`  ESP32: ${line}`));
      }
      setTimeout(scanNetwork, 3000);
    } else {
      appendLog(`[USB Serial Error] ${data.message}`);
    }
  } catch (err) {
    appendLog(`[USB Serial Error] ${err.message}`);
  }
}

async function saveFirmwareWifi() {
  const ssid = document.getElementById("inputWifiSsid").value.trim();
  const pass = document.getElementById("inputWifiPass").value.trim();

  if (!ssid) {
    alert("Please enter a Wi-Fi SSID.");
    return;
  }

  appendLog(`[Firmware Config] Updating controller.ino default credentials to "${ssid}"...`);
  try {
    const res = await fetch("/api/wifi/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ssid, pass })
    });
    const data = await res.json();
    if (data.status === "ok") {
      const badge = document.getElementById("badgeCurrentFirmwareSsid");
      if (badge) badge.textContent = `Firmware Default: ${ssid}`;
      appendLog(`[Firmware Config] Successfully updated controller.ino! Re-flashing will now default to "${ssid}".`);
    } else {
      appendLog(`[Firmware Config Error] Failed to write controller.ino.`);
    }
  } catch (err) {
    appendLog(`[Firmware Config Error] ${err.message}`);
  }
}
