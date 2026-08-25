#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiUdp.h>

// =============================================================================
// PROJECT IKRU — HEAD UNIT (VISION & SONIC VOICE)
// Hardware: AI-Thinker ESP32-CAM + OV2640 Camera + SmartElex Digital Speaker
//
// Capabilities:
// 1. Wi-Fi Access Point ('IKRU-CAM' @ 192.168.4.1)
// 2. High-speed UDP Video JPEG Streaming (Port 2222) + Discovery Handshake (Port 2223)
// 3. Non-blocking R2-D2 Astromech Glissando Speaker PWM on GPIO 2 via TCP (Port 5000)
// =============================================================================

// ---------------- Wi-Fi AP ----------------
const char* AP_SSID = "IKRU-CAM";
const char* AP_PASSWORD = "ikru@potato";

const IPAddress AP_IP(192, 168, 4, 1);
const IPAddress AP_GATEWAY(192, 168, 4, 1);
const IPAddress AP_SUBNET(255, 255, 255, 0);

// ---------------- UDP Video & Discovery ----------------
WiFiUDP udp;
const uint16_t DISCOVERY_PORT = 2223;
const uint16_t VIDEO_PORT = 2222;

IPAddress pcIP;
bool pcKnown = false;

// ---------------- TCP Audio Command Server ----------------
WiFiServer audioServer(5000);

// =============================================================================
// CAMERA SETTINGS & AI-THINKER PIN MAP
// =============================================================================
#define FRAME_SIZE   FRAMESIZE_QVGA
#define JPEG_QUALITY 20
#define FB_COUNT     2
#define CHUNK_SIZE   1200

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27

#define Y9_GPIO_NUM        35
#define Y8_GPIO_NUM        34
#define Y7_GPIO_NUM        39
#define Y6_GPIO_NUM        36
#define Y5_GPIO_NUM        21
#define Y4_GPIO_NUM        19
#define Y3_GPIO_NUM        18
#define Y2_GPIO_NUM         5

#define VSYNC_GPIO_NUM     25
#define HREF_GPIO_NUM      23
#define PCLK_GPIO_NUM      22

// =============================================================================
// AUDIO HARDWARE PIN & DEDICATED CHANNEL
// Channel 2 is used to strictly avoid colliding with Camera XCLK on Channel 0
// =============================================================================
#define AUDIO_PIN 2
#define AUDIO_PWM_CHANNEL 2
#define AUDIO_PWM_RES 8

// =============================================================================
// VIDEO PACKET PROTOCOL
// =============================================================================
#define MAGIC        0x494B
#define VERSION      1
#define PACKET_VIDEO 0

struct __attribute__((packed)) CameraPacketHeader {
    uint16_t magic;
    uint8_t version;
    uint8_t packetType;
    uint32_t frameId;
    uint16_t chunkId;
    uint16_t totalChunks;
    uint32_t frameLength;
    uint16_t chunkLength;
    uint32_t timestamp;
};

uint32_t frameId = 0;

// =============================================================================
// R2-D2 DROID STEP & NON-BLOCKING GLISSANDO SEQUENCER
// =============================================================================
struct DroidStep {
    uint16_t startFreq; // Start frequency in Hz (0 = rest)
    uint16_t endFreq;   // End frequency in Hz (0 = rest)
    uint16_t duration;  // Duration in milliseconds
    uint16_t pause;     // Silence pause in milliseconds
};

#define MAX_SEQUENCE_STEPS 32

class SonicPlayer {
private:
    uint8_t _pin;
    DroidStep _sequence[MAX_SEQUENCE_STEPS];
    uint8_t _stepCount = 0;
    uint8_t _currentStep = 0;
    uint16_t _lastSetFreq = 0;

    enum PlayerState {
        IDLE,
        PLAYING_NOTE,
        PLAYING_PAUSE
    };

    PlayerState _state = IDLE;
    unsigned long _stateStartTime = 0;

    void setHwTone(uint16_t freq) {
        if (freq == _lastSetFreq) return;
        _lastSetFreq = freq;

        if (freq > 0) {
            #if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
                ledcWriteTone(_pin, freq);
            #else
                ledcWriteTone(AUDIO_PWM_CHANNEL, freq);
            #endif
        } else {
            #if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
                ledcWriteTone(_pin, 0);
            #else
                ledcWriteTone(AUDIO_PWM_CHANNEL, 0);
            #endif
        }
    }

public:
    SonicPlayer(uint8_t pin) : _pin(pin) {}

    void begin() {
        #if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
            ledcAttachChannel(_pin, 1000, AUDIO_PWM_RES, AUDIO_PWM_CHANNEL);
        #else
            ledcSetup(AUDIO_PWM_CHANNEL, 1000, AUDIO_PWM_RES);
            ledcAttachPin(_pin, AUDIO_PWM_CHANNEL);
        #endif
        setHwTone(0);
        _state = IDLE;
    }

    bool isPlaying() const {
        return _state != IDLE;
    }

    void stop() {
        setHwTone(0);
        _state = IDLE;
        _stepCount = 0;
        _currentStep = 0;
        _lastSetFreq = 0;
    }

    bool playSequence(const DroidStep *steps, uint8_t count) {
        if (count == 0) return false;
        if (count > MAX_SEQUENCE_STEPS) count = MAX_SEQUENCE_STEPS;

        for (uint8_t i = 0; i < count; i++) {
            _sequence[i] = steps[i];
        }

        _stepCount = count;
        _currentStep = 0;
        _state = PLAYING_NOTE;
        _stateStartTime = millis();
        _lastSetFreq = 0;

        setHwTone(_sequence[0].startFreq);
        return true;
    }

    // Call on every loop() tick to smoothly interpolate frequency sweeps
    void update() {
        if (_state == IDLE) return;

        unsigned long now = millis();
        unsigned long elapsed = now - _stateStartTime;
        DroidStep &cur = _sequence[_currentStep];

        if (_state == PLAYING_NOTE) {
            if (elapsed < cur.duration) {
                // Continuous glissando frequency interpolation
                if (cur.startFreq != cur.endFreq && cur.duration > 0) {
                    float progress = (float)elapsed / (float)cur.duration;
                    uint16_t currentFreq = cur.startFreq + (uint16_t)((cur.endFreq - cur.startFreq) * progress);
                    setHwTone(currentFreq);
                }
            } else {
                // Note finished -> switch to pause
                setHwTone(0);
                if (cur.pause > 0) {
                    _state = PLAYING_PAUSE;
                    _stateStartTime = now;
                } else {
                    advanceStep();
                }
            }
        } else if (_state == PLAYING_PAUSE) {
            if (elapsed >= cur.pause) {
                advanceStep();
            }
        }
    }

private:
    void advanceStep() {
        _currentStep++;
        if (_currentStep >= _stepCount) {
            stop();
        } else {
            _state = PLAYING_NOTE;
            _stateStartTime = millis();
            setHwTone(_sequence[_currentStep].startFreq);
        }
    }
};

SonicPlayer sonicPlayer(AUDIO_PIN);

// =============================================================================
// R2-D2 SOUND PATTERNS
// =============================================================================
const DroidStep PATTERN_HAPPY[] = {
    {1400, 1850, 45, 10},
    {1850, 2600, 55, 12},
    {2600, 3400, 85, 15},
    {3400, 3600, 180, 0}
};

const DroidStep PATTERN_EXCITED[] = {
    {1800, 2400, 35, 6},
    {2400, 3100, 35, 6},
    {3100, 3700, 40, 8},
    {3700, 3200, 45, 6},
    {3200, 4000, 60, 8},
    {4000, 4200, 150, 0}
};

const DroidStep PATTERN_SAD[] = {
    {2100, 1500, 180, 25},
    {1450, 850, 230, 30},
    {800, 320, 300, 0}
};

const DroidStep PATTERN_CONFUSED[] = {
    {1500, 1750, 40, 70},
    {1800, 1450, 45, 55},
    {950, 2800, 160, 0}
};

const DroidStep PATTERN_THINKING[] = {
    {1450, 1600, 30, 80},
    {1650, 1500, 30, 90},
    {1750, 1900, 35, 75},
    {1850, 1700, 40, 0}
};

const DroidStep PATTERN_SUCCESS[] = {
    {1200, 1600, 40, 8},
    {1600, 2100, 45, 10},
    {2100, 2800, 55, 12},
    {2800, 3500, 190, 0}
};

const DroidStep PATTERN_WARNING[] = {
    {2200, 3400, 50, 15},
    {3400, 2200, 50, 15},
    {2200, 3400, 50, 15},
    {3400, 2200, 50, 0}
};

const DroidStep PATTERN_NEUTRAL[] = {
    {1400, 1700, 40, 18},
    {1700, 2500, 80, 0}
};

void playEmotion(String emotion) {
    emotion.toLowerCase();
    emotion.trim();
    if (emotion == "happy") sonicPlayer.playSequence(PATTERN_HAPPY, 4);
    else if (emotion == "excited" || emotion == "glee") sonicPlayer.playSequence(PATTERN_EXCITED, 6);
    else if (emotion == "sad" || emotion == "worried") sonicPlayer.playSequence(PATTERN_SAD, 3);
    else if (emotion == "confused" || emotion == "skeptic") sonicPlayer.playSequence(PATTERN_CONFUSED, 3);
    else if (emotion == "thinking" || emotion == "focused") sonicPlayer.playSequence(PATTERN_THINKING, 4);
    else if (emotion == "success") sonicPlayer.playSequence(PATTERN_SUCCESS, 4);
    else if (emotion == "warning" || emotion == "scared") sonicPlayer.playSequence(PATTERN_WARNING, 4);
    else sonicPlayer.playSequence(PATTERN_NEUTRAL, 2);
}

// =============================================================================
// AUDIO COMMAND PARSER
// =============================================================================
void parseAudioCommand(String cmd) {
    cmd.trim();
    if (cmd.length() == 0) return;

    // 1. TONES:start,end,dur,pause;start,end,dur,pause;...
    if (cmd.startsWith("TONES:")) {
        String seqStr = cmd.substring(6);
        DroidStep steps[MAX_SEQUENCE_STEPS];
        uint8_t count = 0;

        int start = 0;
        while (start < (int)seqStr.length() && count < MAX_SEQUENCE_STEPS) {
            int semi = seqStr.indexOf(';', start);
            String item = (semi == -1) ? seqStr.substring(start) : seqStr.substring(start, semi);
            start = (semi == -1) ? seqStr.length() : semi + 1;

            int c1 = item.indexOf(',');
            int c2 = item.indexOf(',', c1 + 1);
            int c3 = item.indexOf(',', c2 + 1);
            if (c1 > 0 && c2 > 0 && c3 > 0) {
                uint16_t sf = item.substring(0, c1).toInt();
                uint16_t ef = item.substring(c1 + 1, c2).toInt();
                uint16_t d = item.substring(c2 + 1, c3).toInt();
                uint16_t p = item.substring(c3 + 1).toInt();
                steps[count++] = {sf, ef, d, p};
            }
        }
        if (count > 0) {
            sonicPlayer.playSequence(steps, count);
        }
        return;
    }

    // 2. SOUND:<EMOTION>:<INTENSITY>
    if (cmd.startsWith("SOUND:")) {
        String payload = cmd.substring(6);
        int colonIdx = payload.indexOf(':');
        String emo = (colonIdx > 0) ? payload.substring(0, colonIdx) : payload;
        playEmotion(emo);
        return;
    }

    // Fallback: raw emotion name
    playEmotion(cmd);
}

void pollAudioServer() {
    WiFiClient client = audioServer.available();
    if (client) {
        String line = client.readStringUntil('\n');
        parseAudioCommand(line);
        client.println("OK");
        client.stop();
    }
}

// =============================================================================
// CAMERA INITIALIZATION & UDP STREAMING
// =============================================================================
bool initCamera() {
    camera_config_t config;
    config.ledc_channel = LEDC_CHANNEL_0;
    config.ledc_timer   = LEDC_TIMER_0;
    config.pin_d0       = Y2_GPIO_NUM;
    config.pin_d1       = Y3_GPIO_NUM;
    config.pin_d2       = Y4_GPIO_NUM;
    config.pin_d3       = Y5_GPIO_NUM;
    config.pin_d4       = Y6_GPIO_NUM;
    config.pin_d5       = Y7_GPIO_NUM;
    config.pin_d6       = Y8_GPIO_NUM;
    config.pin_d7       = Y9_GPIO_NUM;
    config.pin_xclk     = XCLK_GPIO_NUM;
    config.pin_pclk     = PCLK_GPIO_NUM;
    config.pin_vsync    = VSYNC_GPIO_NUM;
    config.pin_href     = HREF_GPIO_NUM;
    config.pin_sccb_sda = SIOD_GPIO_NUM;
    config.pin_sccb_scl = SIOC_GPIO_NUM;
    config.pin_pwdn     = PWDN_GPIO_NUM;
    config.pin_reset    = RESET_GPIO_NUM;
    config.xclk_freq_hz = 20000000;
    config.pixel_format = PIXFORMAT_JPEG;

    if (psramFound()) {
        config.frame_size   = FRAME_SIZE;
        config.jpeg_quality = JPEG_QUALITY;
        config.fb_count     = FB_COUNT;
    } else {
        config.frame_size   = FRAMESIZE_QVGA;
        config.jpeg_quality = 12;
        config.fb_count     = 1;
    }

    esp_err_t err = esp_camera_init(&config);
    return (err == ESP_OK);
}

void startAP() {
    WiFi.mode(WIFI_AP);
    WiFi.setSleep(false);
    WiFi.softAPConfig(AP_IP, AP_GATEWAY, AP_SUBNET);
    WiFi.softAP(AP_SSID, AP_PASSWORD);

    Serial.println("[WIFI] Head AP Started!");
    Serial.printf("  SSID     : %s\n", AP_SSID);
    Serial.printf("  Password : %s\n", AP_PASSWORD);
    Serial.printf("  IP       : %s\n", WiFi.softAPIP().toString().c_str());
}

void checkDiscovery() {
    int packetSize = udp.parsePacket();
    if (!packetSize) return;

    char buffer[64];
    int len = udp.read(buffer, sizeof(buffer) - 1);
    if (len <= 0) return;
    buffer[len] = '\0';

    String msg(buffer);
    msg.trim();

    if (msg == "IKRU_DISCOVER" || msg == "DISCOVER_IKRU_CAM" || msg.indexOf("DISCOVER") >= 0) {
        pcIP = udp.remoteIP();
        pcKnown = true;

        // ACK on discovery port
        udp.beginPacket(pcIP, DISCOVERY_PORT);
        udp.write((const uint8_t*)"IKRU_CAM_ACK", 12);
        udp.endPacket();

        // ACK on video port
        udp.beginPacket(pcIP, VIDEO_PORT);
        udp.write((const uint8_t*)"IKRU_CAMERA", 11);
        udp.endPacket();

        Serial.printf("[DISCOVERY] PC Connected: %s\n", pcIP.toString().c_str());
    }
}

void sendFrame(camera_fb_t* fb) {
    if (!pcKnown || !fb) return;

    frameId++;
    uint32_t totalLength = fb->len;
    uint16_t totalChunks = (totalLength + CHUNK_SIZE - 1) / CHUNK_SIZE;
    uint32_t ts = millis();

    for (uint16_t chunkId = 0; chunkId < totalChunks; chunkId++) {
        uint32_t offset = chunkId * CHUNK_SIZE;
        uint16_t currentChunkLength = (chunkId == totalChunks - 1) ? (totalLength - offset) : CHUNK_SIZE;

        CameraPacketHeader header;
        header.magic       = MAGIC;
        header.version     = VERSION;
        header.packetType  = PACKET_VIDEO;
        header.frameId     = frameId;
        header.chunkId     = chunkId;
        header.totalChunks = totalChunks;
        header.frameLength = totalLength;
        header.chunkLength = currentChunkLength;
        header.timestamp   = ts;

        if (!udp.beginPacket(pcIP, VIDEO_PORT)) return;
        udp.write((const uint8_t*)&header, sizeof(CameraPacketHeader));
        udp.write(fb->buf + offset, currentChunkLength);
        if (!udp.endPacket()) return;
    }
}

// =============================================================================
// SETUP & LOOP
// =============================================================================
void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("==========================================");
    Serial.println("   PROJECT IKRU — HEAD UNIT FIRMWARE      ");
    Serial.println("   OV2640 Vision + R2-D2 Voice Sequencer  ");
    Serial.println("==========================================");

    // 1. MUST initialize Camera FIRST to reserve LEDC Channel 0 (XCLK 20MHz)
    if (!initCamera()) {
        Serial.println("[FATAL] Camera init failed!");
        while (true) delay(1000);
    }
    Serial.println("[CAM] Camera initialized successfully.");

    // 2. Initialize Audio on dedicated Channel 2 (GPIO 2)
    sonicPlayer.begin();
    Serial.printf("[AUDIO] Initialized on GPIO %d (Channel 2)\n", AUDIO_PIN);

    // 3. Start AP & Network Services
    startAP();
    udp.begin(DISCOVERY_PORT);
    audioServer.begin();

    Serial.println("[READY] Video on UDP 2222 | Discovery on 2223 | Audio on TCP 5000");

    // Play R2-D2 Startup Chime
    playEmotion("happy");
}

void loop() {
    // 1. Non-blocking glissando frequency interpolation
    sonicPlayer.update();

    // 2. Poll TCP audio commands
    pollAudioServer();

    // 3. Poll UDP discovery
    checkDiscovery();

    // 4. Stream video frame if PC is connected
    if (pcKnown) {
        camera_fb_t* fb = esp_camera_fb_get();
        if (fb) {
            sendFrame(fb);
            esp_camera_fb_return(fb);
        }
    }

    delay(1);
}
