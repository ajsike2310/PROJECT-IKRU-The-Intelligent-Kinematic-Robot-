/*
===============================================================================
PROJECT IKRU — R2-D2 ASTROMECH SONIC EMOTION FIRMWARE
===============================================================================

Standalone firmware testing authentic R2-D2 droid sounds on ESP32 + SmartElex speaker.
Features continuous-frequency hardware pitch sweeps (chirps), rapid warbles/trills,
and expressive astromech droid vocalizations with zero delay() blocking.

Compatible with ESP32 Arduino Core 2.x and 3.x+.
===============================================================================
*/

#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsServer.h>

// =============================================================================
// HARDWARE PIN CONFIGURATION
// =============================================================================

// Default GPIO pin connected to SmartElex Speaker IN pin.
#define AUDIO_PIN 2

#define PWM_CHANNEL 0
#define PWM_RESOLUTION 8

// =============================================================================
// WIFI & SERVERS CONFIGURATION
// =============================================================================
// DIRECT ACCESS POINT (AP) CONFIGURATION
// Connect PC directly to Wi-Fi SSID: "IKRU-AUDIO" (Password: "ikru@potato")
// =============================================================================

const char *AP_SSID = "IKRU-AUDIO";
const char *AP_PASS = "ikru@potato";
const IPAddress AP_LOCAL_IP(192, 168, 4, 1);
const IPAddress AP_GATEWAY(192, 168, 4, 1);
const IPAddress AP_SUBNET(255, 255, 255, 0);

WebSocketsServer webSocket(81);
WiFiServer tcpServer(5000);

// =============================================================================
// DROID STEP & NON-BLOCKING CONTINUOUS-SWEEP SEQUENCER
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
            tone(_pin, freq);
        } else {
            noTone(_pin);
        }
    }

public:
    SonicPlayer(uint8_t pin) : _pin(pin) {}

    void begin() {
        pinMode(_pin, OUTPUT);
        noTone(_pin);
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

    // Call update() on every loop() tick to smoothly interpolate glissando sweeps
    void update() {
        if (_state == IDLE) return;

        unsigned long now = millis();
        unsigned long elapsed = now - _stateStartTime;

        if (_state == PLAYING_NOTE) {
            uint16_t dur = _sequence[_currentStep].duration;
            if (elapsed < dur) {
                // Continuous glissando frequency sweep interpolation
                uint16_t sF = _sequence[_currentStep].startFreq;
                uint16_t eF = _sequence[_currentStep].endFreq;

                if (sF == eF || sF == 0 || eF == 0) {
                    setHwTone(sF);
                } else {
                    float progress = (float)elapsed / (float)dur;
                    uint16_t currentFreq = sF + (int)((eF - sF) * progress);
                    setHwTone(currentFreq);
                }
            } else {
                // Tone finished -> silence and pause
                setHwTone(0);
                if (_sequence[_currentStep].pause > 0) {
                    _state = PLAYING_PAUSE;
                    _stateStartTime = now;
                } else {
                    advanceStep(now);
                }
            }
        } else if (_state == PLAYING_PAUSE) {
            if (elapsed >= _sequence[_currentStep].pause) {
                advanceStep(now);
            }
        }
    }

private:
    void advanceStep(unsigned long now) {
        _currentStep++;
        if (_currentStep >= _stepCount) {
            stop();
        } else {
            _state = PLAYING_NOTE;
            _stateStartTime = now;
            setHwTone(_sequence[_currentStep].startFreq);
        }
    }
};

SonicPlayer player(AUDIO_PIN);

// =============================================================================
// R2-D2 DROID ROM PATTERN GENERATOR
// =============================================================================

void playEmotion(String emotion, float intensity = 0.5) {
    emotion.toLowerCase();
    intensity = constrain(intensity, 0.0f, 1.0f);

    DroidStep seq[MAX_SEQUENCE_STEPS];
    uint8_t count = 0;

    Serial.printf("[R2D2] Playing: %s (intensity: %.2f)\n", emotion.c_str(), intensity);

    if (emotion == "happy") {
        float p = 1.0f + (0.25f * intensity);
        uint16_t base = 1200 * p;
        uint16_t mid = 1800 * p;
        uint16_t high = 2600 * p;
        uint16_t top = 3200 * p;

        if (intensity < 0.35f) {
            seq[count++] = {base, mid, 60, 15};
            seq[count++] = {mid, high, 90, 0};
        } else if (intensity < 0.75f) {
            seq[count++] = {base, mid, 55, 12};
            seq[count++] = {mid, high, 65, 12};
            seq[count++] = {high, top, 110, 0};
        } else {
            seq[count++] = {base, mid, 45, 8};
            seq[count++] = {mid, top, 55, 10};
            seq[count++] = {high, top, 18, 2};
            seq[count++] = {top, high, 18, 2};
            seq[count++] = {high, top, 18, 2};
            seq[count++] = {top, high, 18, 8};
            seq[count++] = {high, (uint16_t)(top * 1.15f), 130, 0};
        }
    } else if (emotion == "excited" || emotion == "glee") {
        float p = 1.0f + (0.3f * intensity);
        uint16_t b = 1400 * p;
        seq[count++] = {b, (uint16_t)(b + 500), 35, 6};
        seq[count++] = {(uint16_t)(b + 400), (uint16_t)(b + 1000), 35, 6};
        seq[count++] = {(uint16_t)(b + 900), (uint16_t)(b + 1600), 45, 8};
        seq[count++] = {(uint16_t)(b + 1200), (uint16_t)(b + 1800), 16, 2};
        seq[count++] = {(uint16_t)(b + 1800), (uint16_t)(b + 1200), 16, 2};
        seq[count++] = {(uint16_t)(b + 1200), (uint16_t)(b + 1800), 16, 6};
        seq[count++] = {(uint16_t)(b + 1400), (uint16_t)(b + 2200), 120, 0};
    } else if (emotion == "sad" || emotion == "unimpressed") {
        uint16_t top = 2400 - (uint16_t)(200 * intensity);
        uint16_t bottom = 550 - (uint16_t)(150 * intensity);
        uint16_t dur = 320 + (uint16_t)(220 * intensity);
        seq[count++] = {(uint16_t)(top - 100), top, 60, 25};
        seq[count++] = {top, bottom, dur, 30};
        seq[count++] = {(uint16_t)(bottom + 80), bottom, 140, 0};
    } else if (emotion == "angry" || emotion == "frustrated" || emotion == "annoyed" || emotion == "furious") {
        uint16_t low_a = 350 + (uint16_t)(50 * intensity);
        uint16_t low_b = 750 + (uint16_t)(100 * intensity);
        seq[count++] = {low_b, low_a, 50, 10};
        seq[count++] = {low_a, (uint16_t)(low_b + 100), 45, 12};
        seq[count++] = {(uint16_t)(low_b + 100), (uint16_t)(low_a - 50), 60, 20};
        if (intensity > 0.4f) {
            seq[count++] = {2200, 3400, 40, 8};
            seq[count++] = {3400, 2200, 40, 8};
            seq[count++] = {2200, 3400, 70, 0};
        }
    } else if (emotion == "confused" || emotion == "skeptic" || emotion == "suspicious") {
        seq[count++] = {1100, 1400, 45, 30};
        seq[count++] = {1600, 1200, 50, 40};
        seq[count++] = {950, (uint16_t)(2600 + (400 * intensity)), 120, 0};
    } else if (emotion == "surprised" || emotion == "scared") {
        uint16_t top = 3400 + (uint16_t)(600 * intensity);
        seq[count++] = {800, top, 55, 10};
        seq[count++] = {top, (uint16_t)(top - 400), 30, 6};
        seq[count++] = {(uint16_t)(top - 400), top, 40, 0};
    } else if (emotion == "thinking" || emotion == "focused" || emotion == "squint") {
        uint16_t p = 70 + (uint16_t)(70 * (1.0f - intensity));
        uint16_t base = 1400 + (uint16_t)(200 * intensity);
        seq[count++] = {base, (uint16_t)(base + 250), 40, p};
        seq[count++] = {(uint16_t)(base + 350), (uint16_t)(base + 100), 40, p};
        seq[count++] = {(uint16_t)(base + 150), (uint16_t)(base + 450), 45, p};
        seq[count++] = {(uint16_t)(base + 400), (uint16_t)(base + 200), 40, 0};
    } else if (emotion == "sleepy") {
        uint16_t dur = 400 + (uint16_t)(250 * intensity);
        seq[count++] = {1800, 1600, 90, 40};
        seq[count++] = {1600, 500, dur, 40};
        seq[count++] = {450, 250, 160, 0};
    } else if (emotion == "affection" || emotion == "awe") {
        seq[count++] = {1200, 1600, 70, 15};
        seq[count++] = {1500, 2200, 80, 15};
        seq[count++] = {2200, 1900, 60, 15};
        seq[count++] = {1900, 2800, 150, 0};
    } else if (emotion == "success" || emotion == "happy_success") {
        float p = 1.0f + (0.2f * intensity);
        seq[count++] = {(uint16_t)(1100 * p), (uint16_t)(1500 * p), 50, 10};
        seq[count++] = {(uint16_t)(1500 * p), (uint16_t)(2000 * p), 55, 10};
        seq[count++] = {(uint16_t)(2000 * p), (uint16_t)(2700 * p), 65, 12};
        uint16_t top = 3200 * p;
        seq[count++] = {(uint16_t)(top - 150), (uint16_t)(top + 150), 22, 2};
        seq[count++] = {(uint16_t)(top + 150), (uint16_t)(top - 150), 22, 2};
        seq[count++] = {top, (uint16_t)(top * 1.1f), 160, 0};
    } else if (emotion == "error" || emotion == "failed") {
        uint16_t dur = 80 + (uint16_t)(30 * intensity);
        seq[count++] = {700, 220, dur, 40};
        seq[count++] = {650, 180, (uint16_t)(dur + 20), 0};
    } else if (emotion == "warning") {
        uint16_t high = 2800 + (uint16_t)(400 * intensity);
        uint16_t low = 1800 + (uint16_t)(300 * intensity);
        seq[count++] = {low, high, 45, 6};
        seq[count++] = {high, low, 45, 8};
        seq[count++] = {low, high, 45, 6};
        seq[count++] = {high, low, 45, 0};
    } else if (emotion == "processing") {
        uint16_t f = 1800 + (uint16_t)(300 * intensity);
        seq[count++] = {f, (uint16_t)(f + 150), 22, 35};
        seq[count++] = {f, (uint16_t)(f + 150), 22, 35};
        seq[count++] = {f, (uint16_t)(f + 150), 22, 35};
        seq[count++] = {f, (uint16_t)(f + 150), 22, 0};
    } else if (emotion == "cannot_perform" || emotion == "blocked") {
        seq[count++] = {1300, 750, 110, 40};
        seq[count++] = {900, 450, 140, 0};
    } else {
        // Neutral / Greeting: Classic 2-chirp droid greeting
        seq[count++] = {1300, 1900, 50, 20};
        seq[count++] = {1700, 2500, 80, 0};
    }

    player.playSequence(seq, count);
}

// =============================================================================
// COMMAND PARSER
// =============================================================================

void parseIncomingCommand(String cmd) {
    cmd.trim();
    if (cmd.length() == 0) return;

    Serial.printf("[CMD] Received: '%s'\n", cmd.c_str());

    // 1. Single-key shortcuts
    if (cmd == "1") { playEmotion("happy", 0.8); return; }
    if (cmd == "2") { playEmotion("excited", 0.8); return; }
    if (cmd == "3") { playEmotion("sad", 0.5); return; }
    if (cmd == "4") { playEmotion("angry", 0.7); return; }
    if (cmd == "5") { playEmotion("confused", 0.5); return; }
    if (cmd == "6") { playEmotion("surprised", 0.8); return; }
    if (cmd == "7") { playEmotion("thinking", 0.5); return; }
    if (cmd == "8") { playEmotion("success", 0.8); return; }
    if (cmd == "9") { playEmotion("error", 0.8); return; }
    if (cmd == "0") { playEmotion("neutral", 0.5); return; }

    // 2. Protocol string format: 'SOUND:<EMOTION>:<INTENSITY>'
    if (cmd.startsWith("SOUND:")) {
        String payload = cmd.substring(6);
        int colonIdx = payload.indexOf(':');
        String emo = payload;
        float intensity = 0.5f;

        if (colonIdx > 0) {
            emo = payload.substring(0, colonIdx);
            intensity = payload.substring(colonIdx + 1).toFloat();
        }
        playEmotion(emo, intensity);
        return;
    }

    // 3. Raw tone sequence: 'TONES:start,end,dur,pause;...'
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
            player.playSequence(steps, count);
        }
        return;
    }

    // 4. JSON format
    if (cmd.startsWith("{") && cmd.endsWith("}")) {
        int patIdx = cmd.indexOf("\"pattern\"");
        if (patIdx > 0) {
            int colon = cmd.indexOf(':', patIdx);
            int q1 = cmd.indexOf('\"', colon);
            int q2 = cmd.indexOf('\"', q1 + 1);
            if (q1 > 0 && q2 > q1) {
                String pat = cmd.substring(q1 + 1, q2);
                float intensity = 0.5f;

                int intIdx = cmd.indexOf("\"intensity\"");
                if (intIdx > 0) {
                    int cInt = cmd.indexOf(':', intIdx);
                    intensity = cmd.substring(cInt + 1).toFloat();
                }
                playEmotion(pat, intensity);
                return;
            }
        }
    }

    // Fallback: try raw emotion name
    playEmotion(cmd, 0.5);
}

// =============================================================================
// WEBSOCKET HANDLER
// =============================================================================

void webSocketEvent(uint8_t client, WStype_t type, uint8_t *payload, size_t length) {
    switch (type) {
        case WStype_CONNECTED:
            Serial.printf("[WS] Client #%u connected\n", client);
            break;
        case WStype_DISCONNECTED:
            Serial.printf("[WS] Client #%u disconnected\n", client);
            break;
        case WStype_TEXT: {
            String cmd = String((char *)payload);
            parseIncomingCommand(cmd);
            webSocket.sendTXT(client, "OK");
            break;
        }
        default:
            break;
    }
}

// =============================================================================
// SETUP
// =============================================================================

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("==========================================");
    Serial.println("   PROJECT IKRU — R2-D2 SONIC EMOTIONS    ");
    Serial.println("   Astromech Droid Glissando Sequencer    ");
    Serial.println("==========================================");

    player.begin();
    Serial.printf("[HARDWARE] Audio output initialized on GPIO %d\n", AUDIO_PIN);

    // Initialize ESP32 Standalone Access Point
    WiFi.mode(WIFI_AP);
    WiFi.softAPConfig(AP_LOCAL_IP, AP_GATEWAY, AP_SUBNET);
    WiFi.softAP(AP_SSID, AP_PASS);

    Serial.println("[WIFI AP] Access Point Started!");
    Serial.printf("  SSID     : %s\n", AP_SSID);
    Serial.printf("  Password : %s\n", AP_PASS);
    Serial.printf("  IP       : %s\n", WiFi.softAPIP().toString().c_str());

    webSocket.begin();
    webSocket.onEvent(webSocketEvent);
    tcpServer.begin();

    Serial.println("[SERVER] WebSocket on port 81 | TCP on port 5000");
    Serial.println("[READY] Send commands via Serial (1-9) or WebSocket!");

    // Play R2-D2 Startup Chime
    playEmotion("happy", 0.7);
}

// =============================================================================
// MAIN LOOP
// =============================================================================

void loop() {
    // 1. Non-blocking glissando sweep update
    player.update();

    // 2. Poll WebSocket
    webSocket.loop();

    // 3. Poll TCP
    WiFiClient tcpClient = tcpServer.available();
    if (tcpClient) {
        String line = tcpClient.readStringUntil('\n');
        parseIncomingCommand(line);
        tcpClient.println("OK");
        tcpClient.stop();
    }

    // 4. Poll USB Serial console
    if (Serial.available() > 0) {
        String input = Serial.readStringUntil('\n');
        input.trim();
        if (input.length() > 0) {
            parseIncomingCommand(input);
        }
    }
}
