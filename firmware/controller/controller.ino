#include "Face.h"
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WebSocketsServer.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <WiFiUdp.h>
#include <Wire.h>

Preferences preferences;

// ============================================================
// IKRU DESK COMPANION ROBOT
//
// Hardware:
// ESP32-WROOM-32
// DRV8833 Dual H-Bridge Motor Driver
// 2x DC Motor
// SSD1306 128x64 I2C OLED (driven via U8g2 through the Face library)
// SmartElex Digital Speaker Module (GPIO 25 Hardware PWM R2-D2 Droid Audio)
//
// Communication:
// WiFi + WebSocket
//
// OLED:
// IDLE     -> Animated eye expressions (Face library)
// SPEAKING -> Full screen large scrolling text (U8g2)
// ============================================================

// ============================================================
// WIFI (Dynamic NVS + SoftAP Web Portal Setup)
// ============================================================

const char *fallback_ssid = "IKRU-CAM";
const char *fallback_pass = "ikru@potato";

// Fixed address on the IKRU-CAM hub (kept outside the head's softAP DHCP pool)
const IPAddress HUB_ROBOT_IP(192, 168, 4, 200);
const IPAddress HUB_GATEWAY(192, 168, 4, 1);
const IPAddress HUB_SUBNET(255, 255, 255, 0);

// LAN discovery beacon — the PC listens on UDP 4210 to find the robot
WiFiUDP beaconUdp;
const uint16_t BEACON_PORT = 4210;
const unsigned long BEACON_INTERVAL_MS = 2000;
const unsigned long WIFI_REJOIN_MS = 20000;
unsigned long lastBeaconMillis = 0;
unsigned long wifiLostMillis = 0;

WebSocketsServer webSocket(81);

// The PC announces "IKRU-PC|<ip>" on UDP 4211 once it has joined IKRU-CAM
WiFiUDP pcUdp;
const uint16_t PC_ANNOUNCE_PORT = 4211;
const unsigned long PC_PRESENCE_MS = 4000;
unsigned long lastPcSeenMillis = 0;

// Network the robot falls back to (saved in NVS) if the hub doesn't show up
String savedSsid = "";
String savedPass = "";
bool tryingSaved = false;
unsigned long wifiAttemptStart = 0;
const unsigned long HUB_ATTEMPT_MS = 30000;
const unsigned long SAVED_ATTEMPT_MS = 15000;

// ============================================================
// SETUP SCREEN STAGES
//
// BOOT -> HUB (find IKRU-CAM) -> JOINED -> WAIT_PC (PC joins IKRU-CAM)
//      -> LINK (PC connected, loading) -> READY -> DONE (face)
// ============================================================

enum SetupStage {
  SETUP_BOOT,
  SETUP_HUB,
  SETUP_JOINED,
  SETUP_WAIT_PC,
  SETUP_LINK,
  SETUP_READY,
  SETUP_DONE
};

SetupStage setupStage = SETUP_BOOT;
unsigned long setupStageStart = 0;
unsigned long lastClientMillis = 0;
String setupStatus = "";  // PC progress line, set by SETUP:<text>

const unsigned long BOOT_ANIM_MS = 2200;
const unsigned long JOINED_ANIM_MS = 1500;
const unsigned long READY_ANIM_MS = 1800;
const unsigned long LINK_TIMEOUT_MS = 120000;  // PC never sent SETUP_DONE -> wake up anyway
const unsigned long PC_LOST_MS = 3000;

// ============================================================
// MOTOR PINS
// ============================================================

// DRV8833 module (IN1-IN4, EEP, ULT)
//   IN1 = GPIO26, IN2 = GPIO27  -> left motor  (OUT1 / OUT2)
//   IN3 = GPIO14, IN4 = GPIO12  -> right motor (OUT3 / OUT4)
//   EEP = GPIO13  (nSLEEP: HIGH = driver awake)
//   ULT = GPIO32  (nFAULT, optional: LOW on over-current / over-heat / low VM)
// Speed = PWM on the IN pins:
//   forward IN_A=PWM IN_B=0 | reverse IN_A=0 IN_B=PWM | brake IN_A=IN_B=1 | coast both 0
#define MOTOR_IN1 26
#define MOTOR_IN2 27
#define MOTOR_IN3 14
#define MOTOR_IN4 12
#define MOTOR_EEP 13
#define MOTOR_EEP_ALT 33   // old second enable line; kept HIGH so either EEP wiring works
#define MOTOR_FAULT 32

const uint32_t MOTOR_PWM_FREQ = 20000;  // 20 kHz: silent, within DRV8833 limits
const uint8_t  MOTOR_PWM_BITS = 8;
int motorSpeedPct = 100;                // drive speed for all moves (0-100)
bool motorFaultActive = false;

// ============================================================
// ULTRASONIC SENSOR (HC-SR04 / HC-SR04P)
// ============================================================

#define TRIG_PIN 18
#define ECHO_PIN 19

float currentDistanceCm = 999.0;
float obstacleThresholdCm = 12.0;
bool safetyBrakeEnabled = true;
bool isMovingForward = false;
unsigned long lastSonarTime = 0;
const unsigned long SONAR_INTERVAL_MS = 60;

// ============================================================
// FORKLIFT SERVO (hobby servo, 50 Hz PWM, signal on GPIO 15)
// 0 deg = lowest, 45 deg = highest. Angle is clamped in forkWrite().
// ============================================================

#define FORK_PIN 15
#define FORK_MIN_DEG 0
#define FORK_MAX_DEG 45
const uint32_t FORK_PWM_FREQ = 50;
const uint8_t  FORK_PWM_BITS = 14;
const int FORK_PULSE_MIN_US = 500;    // pulse at 0 deg (tune if the servo buzzes at the end stop)
const int FORK_PULSE_MAX_US = 2400;   // pulse at 180 deg; we only use the first half
int forkAngle = FORK_MIN_DEG;

void stopMotors();
void driveMotors(int leftPct, int rightPct);
void checkMotorFault();
void forkWrite(int deg);
void updateUltrasonic();

// ============================================================
// SMARTELEX DIGITAL SPEAKER / R2-D2 DROID AUDIO (PWM GLISSANDO)
// ============================================================

#define AUDIO_PIN 25

struct DroidStep {
  uint16_t startFreq; // Start frequency in Hz (0 = rest/silence)
  uint16_t endFreq;   // End frequency in Hz (0 = rest/silence)
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
      digitalWrite(_pin, LOW);
    }
  }

public:
  SonicPlayer(uint8_t pin) : _pin(pin) {}

  void begin() {
    pinMode(_pin, OUTPUT);
    digitalWrite(_pin, LOW);
    noTone(_pin);
    _state = IDLE;
    _lastSetFreq = 0;
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

  // Non-blocking glissando sweep update - called in loop()
  void update() {
    if (_state == IDLE) return;

    unsigned long now = millis();
    unsigned long elapsed = now - _stateStartTime;

    if (_state == PLAYING_NOTE) {
      uint16_t dur = _sequence[_currentStep].duration;
      if (elapsed < dur) {
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

  void playEmotion(String emotion, float intensity = 0.5f);
  void playConversationalChirp(String emotion);

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
String currentActiveEmotion = "normal";

// ============================================================
// OLED MODES
// ============================================================

enum OLEDMode {

  OLED_IDLE,

  OLED_SPEAKING,

  OLED_WAITING   // box open, idle between segments

};

OLEDMode oledMode = OLED_IDLE;

// ============================================================
// FACE (eye animation library)
// ============================================================

// u8g2 is declared as extern in Common.h and defined in Face.cpp
// We reference it here for direct text rendering in speaking mode.

Face *face;

// ============================================================
// TEXT STORAGE
// ============================================================

#define MAX_MESSAGE_LINES 40

String messageLines[MAX_MESSAGE_LINES];

int messageLineCount = 0;

// ============================================================
// SPEECH FONT / SCROLLING
// ============================================================

// U8g2 font used for speech text
// u8g2_font_ncenB14_tr is a clean 14px bold font (included in U8g2)
#define SPEECH_FONT u8g2_font_ncenB14_tr

// Approximate pixel height of the speech font
const int SPEECH_LINE_HEIGHT = 18;

int scrollY = 64;

// Larger = slower
const unsigned long SCROLL_SPEED = 30;

// Pause before scrolling begins
const unsigned long START_PAUSE = 600;

// Pause after message finishes scrolling before exit animation
const unsigned long END_PAUSE = 400;

unsigned long lastScrollUpdate = 0;

unsigned long speechStartTime = 0;

unsigned long speechFinishedTime = 0;

// ============================================================
// SPEECH BOX ANIMATION
// ============================================================

// Animated width of the speech box (0 = closed, 84 = fully open)
float speechBoxWidth = 0.0;

// Duration for the box to open or close in milliseconds
const unsigned long BOX_ANIM_DURATION = 300;

// Flags for box entry / exit animation
bool speechBoxEntering = false;
bool speechBoxExiting  = false;

// Timestamp when the box animation started
unsigned long speechBoxAnimStart = 0;

// When true the box stays open after text finishes scrolling.
// Set by DISPLAY_OPEN, cleared by DISPLAY_CLOSE.
bool speechBoxPersist = false;

// ============================================================
// EYE ANIMATION VARIABLES
// ============================================================

float currentEyeScale = 1.0;
float targetEyeScale = 1.0;
float currentEyeX = 64.0;
float targetEyeX = 64.0;
float currentEyeY = 32.0;
float targetEyeY = 32.0;
unsigned long animationLastMillis = 0;

// ============================================================
// FUNCTION DECLARATIONS
// ============================================================

void oledStartup();

void showWiFiConnected();

void oledOpen();

void oledClose();

void oledMessage(String text);

void prepareMessage(String text);

void updateSpeechScroll();

void drawSpeakingText();

void emotionNormal();
void emotionHappy();
void emotionGlee();
void emotionSad();
void emotionWorried();
void emotionFocused();
void emotionAnnoyed();
void emotionSurprised();
void emotionSkeptic();
void emotionFrustrated();
void emotionUnimpressed();
void emotionSleepy();
void emotionSuspicious();
void emotionSquint();
void emotionAngry();
void emotionFurious();
void emotionScared();
void emotionAwe();

void parseCommand(String input);

void moveForward();
void moveBackward();
void moveLeft();
void moveRight();
void stopMotors();

void webSocketEvent(uint8_t client, WStype_t type, uint8_t *payload,
                    size_t length);

// ============================================================
// EMOTION ACTION FUNCTIONS
//
// Each function sets the Face library expression.
// Python invokes these via WebSocket commands.
// ============================================================

void emotionNormal() {
  face->Expression.GoTo_Normal();
  Serial.println("Emotion: NORMAL");
}

void emotionHappy() {
  face->Expression.GoTo_Happy();
  Serial.println("Emotion: HAPPY");
}

void emotionGlee() {
  face->Expression.GoTo_Glee();
  Serial.println("Emotion: GLEE");
}

void emotionSad() {
  face->Expression.GoTo_Sad();
  Serial.println("Emotion: SAD");
}

void emotionWorried() {
  face->Expression.GoTo_Worried();
  Serial.println("Emotion: WORRIED");
}

void emotionFocused() {
  face->Expression.GoTo_Focused();
  Serial.println("Emotion: FOCUSED");
}

void emotionAnnoyed() {
  face->Expression.GoTo_Annoyed();
  Serial.println("Emotion: ANNOYED");
}

void emotionSurprised() {
  face->Expression.GoTo_Surprised();
  Serial.println("Emotion: SURPRISED");
}

void emotionSkeptic() {
  face->Expression.GoTo_Skeptic();
  Serial.println("Emotion: SKEPTIC");
}

void emotionFrustrated() {
  face->Expression.GoTo_Frustrated();
  Serial.println("Emotion: FRUSTRATED");
}

void emotionUnimpressed() {
  face->Expression.GoTo_Unimpressed();
  Serial.println("Emotion: UNIMPRESSED");
}

void emotionSleepy() {
  face->Expression.GoTo_Sleepy();
  Serial.println("Emotion: SLEEPY");
}

void emotionSuspicious() {
  face->Expression.GoTo_Suspicious();
  Serial.println("Emotion: SUSPICIOUS");
}

void emotionSquint() {
  face->Expression.GoTo_Squint();
  Serial.println("Emotion: SQUINT");
}

void emotionAngry() {
  face->Expression.GoTo_Angry();
  Serial.println("Emotion: ANGRY");
}

void emotionFurious() {
  face->Expression.GoTo_Furious();
  Serial.println("Emotion: FURIOUS");
}

void emotionScared() {
  face->Expression.GoTo_Scared();
  Serial.println("Emotion: SCARED");
}

void emotionAwe() {
  face->Expression.GoTo_Awe();
  Serial.println("Emotion: AWE");
}

// ============================================================
// WORD FIT CHECK (U8g2)
// ============================================================

bool wordFits(String text, int maxWidth) {

  u8g2.setFont(SPEECH_FONT);

  int w = u8g2.getStrWidth(text.c_str());

  return (w <= maxWidth);
}

// ============================================================
// PREPARE MESSAGE
//
// Words are NEVER intentionally split.
// ============================================================

void prepareMessage(String text) {

  messageLineCount = 0;

  // Remove line breaks
  text.replace("\r", " ");
  text.replace("\n", " ");

  // Remove repeated spaces
  while (text.indexOf("  ") >= 0) {
    text.replace("  ", " ");
  }

  text.trim();

  // Restrict width so text stays in the left column, 
  // leaving the right side (X > 75) completely empty for the eyes.
  const int maxWidth = 75;

  int position = 0;

  String currentLine = "";

  while (position < (int)text.length() &&
         messageLineCount < MAX_MESSAGE_LINES) {

    // Skip spaces
    while (position < (int)text.length() && text.charAt(position) == ' ') {
      position++;
    }

    if (position >= (int)text.length()) {
      break;
    }

    // Find next word
    int nextSpace = text.indexOf(' ', position);

    String word;

    if (nextSpace == -1) {
      word = text.substring(position);
      position = text.length();
    } else {
      word = text.substring(position, nextSpace);
      position = nextSpace + 1;
    }

    word.trim();

    if (word.length() == 0) {
      continue;
    }

    // Test line
    String testLine;

    if (currentLine.length() == 0) {
      testLine = word;
    } else {
      testLine = currentLine + " " + word;
    } 

    // Word fits
    if (wordFits(testLine, maxWidth)) {
      currentLine = testLine;
    }

    // Word does not fit
    else {
      if (currentLine.length() > 0) {
        messageLines[messageLineCount] = currentLine;
        messageLineCount++;
        currentLine = "";
      }

      // If the word ITSELF is too long for the max width, we must break it by characters
      if (!wordFits(word, maxWidth)) {
        String partialWord = "";
        for (int c = 0; c < (int)word.length(); c++) {
          String testPartial = partialWord + word.charAt(c);
          if (wordFits(testPartial + "-", maxWidth)) {
            partialWord = testPartial;
          } else {
            messageLines[messageLineCount] = partialWord + "-";
            messageLineCount++;
            partialWord = String(word.charAt(c));
          }
        }
        currentLine = partialWord;
      } else {
        currentLine = word;
      }
    }
  }

  // Final line
  if (currentLine.length() > 0 && messageLineCount < MAX_MESSAGE_LINES) {
    messageLines[messageLineCount] = currentLine;
    messageLineCount++;
  }
}

// ============================================================
// OPEN SPEECH BOX (no text, persistent)
// ============================================================

void oledOpen() {

  speechBoxPersist   = true;
  speechBoxWidth     = 0.0;
  speechBoxEntering  = true;
  speechBoxExiting   = false;
  speechBoxAnimStart = millis();
  oledMode           = OLED_SPEAKING;
  messageLineCount   = 0;
  scrollY            = 64;

  // Target small eyes in corner
  targetEyeScale = 0.45;
  targetEyeX     = 106.0;
  targetEyeY     = 48.0;

  // speechStartTime far in the future so no scroll fires until text arrives
  speechStartTime    = millis() + 60000UL;
  speechFinishedTime = 0;
}

// ============================================================
// CLOSE SPEECH BOX (triggers exit animation)
// ============================================================

void oledClose() {

  speechBoxPersist   = false;
  speechBoxExiting   = true;
  speechBoxAnimStart = millis();
}

// ============================================================
// START SPEAKING
// ============================================================

void oledMessage(String text) {

  Serial.print("OLED message: ");
  Serial.println(text);

  prepareMessage(text);

  // ----------------------------------------------------------
  // If the box is already fully open and persistent,
  // just reset the scroll without re-animating the box.
  // ----------------------------------------------------------

  if (speechBoxPersist &&
      speechBoxWidth >= 84.0 &&
      !speechBoxEntering && !speechBoxExiting) {

    scrollY            = 64;
    speechStartTime    = millis();
    lastScrollUpdate   = millis();
    speechFinishedTime = 0;
    oledMode           = OLED_SPEAKING;
    return;
  }

  // ----------------------------------------------------------
  // Full open animation
  // ----------------------------------------------------------

  scrollY  = 64;
  oledMode = OLED_SPEAKING;

  targetEyeScale = 0.45;
  targetEyeX     = 106.0;
  targetEyeY     = 48.0;

  speechBoxWidth      = 0.0;
  speechBoxEntering   = true;
  speechBoxExiting    = false;
  speechBoxAnimStart  = millis();

  speechStartTime    = millis();
  lastScrollUpdate   = millis();
  speechFinishedTime = 0;
}

// ============================================================
// DRAW SPEAKING TEXT (U8g2)
// ============================================================

void drawSpeakingText() {

  int bw = (int)speechBoxWidth;

  if (bw <= 2) return;  // Box not open yet — nothing to draw

  // Only draw scrolling text once the box is mostly open
  if (bw >= 40) {

    u8g2.setFont(SPEECH_FONT);
    u8g2.setFontMode(1);

    for (int i = 0; i < messageLineCount; i++) {

      int y = scrollY + (i * SPEECH_LINE_HEIGHT) + 14;

      if (y >= 0 && y <= 78) {
        u8g2.drawStr(4, y, messageLines[i].c_str());
      }
    }
  }

  // Mask edges (clips text within the frame)
  u8g2.setDrawColor(0);
  u8g2.drawBox(0, 0, bw, 4);
  u8g2.drawBox(0, 60, bw, 4);
  u8g2.setDrawColor(1);

  // Animated rounded frame — grows from left to right on entry,
  // shrinks from right to left on exit
  u8g2.drawRFrame(0, 0, bw, 64, 4);
}

// ============================================================
// UPDATE SPEECH SCROLL
// ============================================================

void updateSpeechScroll() {

  unsigned long now = millis();

  // ----------------------------------------------------------
  // BOX ENTRY ANIMATION (width 0 -> 84)
  // Runs regardless of oledMode.
  // ----------------------------------------------------------

  if (speechBoxEntering) {

    float elapsed  = (float)(now - speechBoxAnimStart);
    float progress = elapsed / (float)BOX_ANIM_DURATION;

    if (progress >= 1.0) {
      speechBoxEntering = false;
      speechBoxWidth    = 84.0;

      // Start pause begins AFTER box is fully open
      speechStartTime = now;

    } else {
      speechBoxWidth = 84.0 * (1.0 - (1.0 - progress) * (1.0 - progress));
    }

    return;
  }

  // ----------------------------------------------------------
  // BOX EXIT ANIMATION (width 84 -> 0)
  // Runs regardless of oledMode.
  // ----------------------------------------------------------

  if (speechBoxExiting) {

    float elapsed  = (float)(now - speechBoxAnimStart);
    float progress = elapsed / (float)BOX_ANIM_DURATION;

    if (progress >= 1.0) {
      speechBoxExiting = false;
      speechBoxWidth   = 0.0;
      oledMode         = OLED_IDLE;
      targetEyeScale   = 1.0;
      targetEyeX       = 64.0;
      targetEyeY       = 32.0;

      // Reset emotion when box closes
      emotionNormal();

    } else {
      speechBoxWidth = 84.0 * (1.0 - progress * progress);
    }

    return;
  }

  // ----------------------------------------------------------
  // Only continue scrolling logic when actively speaking
  // ----------------------------------------------------------

  if (oledMode != OLED_SPEAKING) {
    return;
  }

  // ----------------------------------------------------------
  // INITIAL PAUSE before scrolling begins
  // ----------------------------------------------------------

  if (now - speechStartTime < START_PAUSE) {
    return;
  }

  // ----------------------------------------------------------
  // CHECK IF ALL TEXT HAS SCROLLED OFF
  // ----------------------------------------------------------

  int finalTextPosition = scrollY + (messageLineCount * SPEECH_LINE_HEIGHT);

  // Continually play conversational droid chatter while text is scrolling on OLED
  if (finalTextPosition >= 0 && speechFinishedTime == 0) {
    if (!player.isPlaying()) {
      player.playConversationalChirp(currentActiveEmotion);
    }
  }

  if (finalTextPosition < 0) {

    if (speechFinishedTime == 0) {
      speechFinishedTime = now;
      player.stop();
      return;
    }

    if (now - speechFinishedTime >= END_PAUSE) {

      if (speechBoxPersist) {
        // Stay open, waiting for next segment
        oledMode         = OLED_WAITING;
        messageLineCount = 0;
      } else {
        // Trigger close animation
        speechBoxExiting   = true;
        speechBoxAnimStart = now;
      }
    }

    return;
  }

  // ----------------------------------------------------------
  // SCROLL TEXT UP ONE PIXEL EACH TICK
  // ----------------------------------------------------------

  if (now - lastScrollUpdate >= SCROLL_SPEED) {
    lastScrollUpdate = now;
    scrollY--;
  }
}

// ============================================================
// OLED STARTUP (U8g2 is initialised inside Face constructor)
// ============================================================

void oledStartup() {

  // SDA = GPIO 21, SCL = GPIO 22
  // The Face library initialises u8g2 internally (clock=4, data=5 in
  // Face.cpp refers to the U8g2 HW_I2C constructor pin order, which on
  // ESP32 maps to the hardware I2C peripheral — the actual SDA/SCL
  // are configured by Wire.begin() below before Face is constructed).

  Wire.begin(21, 22);

  // Construct the Face — this initialises u8g2 and the display
  face = new Face(/* screenWidth = */ 128, /* screenHeight = */ 64,
                  /* eyeSize = */ 40);

  // Start with a normal expression
  face->Expression.GoTo_Normal();

  // Auto-blink enabled
  face->RandomBlink = true;
  face->Blink.Timer.SetIntervalMillis(4000);

  // AI controls emotions — disable random behaviour and random look
  face->RandomBehavior = false;
  face->RandomLook = false;

  // The boot banner is drawn by the setup screen (SETUP_BOOT stage)
}

// ============================================================
// WIFI CONNECTED SCREEN
// ============================================================

void showWiFiConnected() {

  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr(0, 14, "WiFi Connected!");
  u8g2.drawStr(0, 30, "IP Address:");
  u8g2.drawStr(0, 48, WiFi.localIP().toString().c_str());
  u8g2.sendBuffer();

  delay(4000);
}

// ============================================================
// DYNAMIC WIFI CONFIGURATION (NVS + RECONNECT)
// ============================================================

// Starts joining a network in STA mode (non-blocking).
// IKRU-CAM gets the fixed hub IP, anything else uses DHCP.
void beginStation(const char *ssid, const char *pass) {
  if (strcmp(ssid, fallback_ssid) == 0) {
    WiFi.config(HUB_ROBOT_IP, HUB_GATEWAY, HUB_SUBNET);
  } else {
    WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE);
  }
  WiFi.begin(ssid, pass);
  wifiAttemptStart = millis();
}

// Joins a network and blocks until connected or out of retries (used by SET_WIFI).
bool connectStation(const char *ssid, const char *pass, int maxRetries) {
  beginStation(ssid, pass);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < maxRetries) {
    delay(500);
    Serial.print(".");
    retries++;
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) return true;

  WiFi.disconnect();
  delay(100);
  return false;
}

void startMdns() {
  MDNS.end();
  if (MDNS.begin("ikru-robot")) {
    MDNS.addService("ws", "tcp", 81);
    MDNS.addService("http", "tcp", 80);
    Serial.println("[mDNS] Responder active: ikru-robot.local");
  }
}

// Discovery beacon + background re-join (non-blocking, called from loop())
void updateNetwork() {
  unsigned long now = millis();
  if (WiFi.status() == WL_CONNECTED) {
    wifiLostMillis = 0;
    if (now - lastBeaconMillis >= BEACON_INTERVAL_MS) {
      lastBeaconMillis = now;
      String msg = "IKRU-ROBOT|" + WiFi.localIP().toString() + "|" + WiFi.SSID() +
                   "|" + String(WiFi.RSSI()) + "|ws81";
      beaconUdp.beginPacket(IPAddress(255, 255, 255, 255), BEACON_PORT);
      beaconUdp.print(msg);
      beaconUdp.endPacket();
    }
  } else if (wifiLostMillis == 0) {
    wifiLostMillis = now;
  } else if (now - wifiLostMillis >= WIFI_REJOIN_MS) {
    Serial.println("[WiFi] Link down for 20s, forcing re-join...");
    WiFi.reconnect();
    wifiLostMillis = now;
  }
}

void applyNewWiFi(String new_ssid, String new_pass) {
  Serial.println();
  Serial.println("==============================");
  Serial.print("[WiFi] Switching to: ");
  Serial.println(new_ssid);
  Serial.println("==============================");

  // Show on OLED
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr(0, 14, "Configuring WiFi...");
  u8g2.drawStr(0, 30, new_ssid.substring(0, 20).c_str());
  u8g2.drawStr(0, 48, "Please wait...");
  u8g2.sendBuffer();

  WiFi.disconnect(true);
  delay(500);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  if (connectStation(new_ssid.c_str(), new_pass.c_str(), 25)) {
    Serial.println("Connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());

    // Save to NVS
    preferences.begin("ikru_wifi", false);
    preferences.putString("ssid", new_ssid);
    preferences.putString("pass", new_pass);
    preferences.end();
    Serial.println("[WiFi] Saved credentials to flash memory (NVS).");

    startMdns();
    showWiFiConnected();
  } else {
    Serial.println("WiFi connect failed! Reverting to fallback...");
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 20, "WiFi Connect Failed!");
    u8g2.drawStr(0, 38, "Reverting to fallback");
    u8g2.sendBuffer();
    delay(1500);

    // Bounded retry — updateNetwork() keeps re-joining in the background if the hub is down
    if (connectStation(fallback_ssid, fallback_pass, 16)) {
      startMdns();
      showWiFiConnected();
    } else {
      Serial.println("[WiFi] IKRU-CAM hub unreachable. Will keep retrying in background.");
      WiFi.begin(fallback_ssid, fallback_pass);
    }
  }
}

// ============================================================
// SETUP SCREEN (non-blocking, drawn every loop until SETUP_DONE)
//
// Top row: 4 progress pips  BOOT - HUB - PC - LINK
// Middle:  stage animation
// Bottom:  status line
// ============================================================

void setSetupStage(SetupStage stage) {
  setupStage = stage;
  setupStageStart = millis();

  switch (stage) {
  case SETUP_HUB:
    Serial.println("[Setup] Finding IKRU-CAM hub...");
    break;
  case SETUP_JOINED:
    Serial.print("[Setup] Joined ");
    Serial.print(WiFi.SSID());
    Serial.print(" as ");
    Serial.println(WiFi.localIP());
    startMdns();
    player.playEmotion("happy", 0.3);
    break;
  case SETUP_WAIT_PC:
    Serial.println("[Setup] Waiting for the PC to join IKRU-CAM...");
    break;
  case SETUP_LINK:
    Serial.println("[Setup] PC found. Waiting for it to finish loading...");
    player.playEmotion("normal", 0.4);
    break;
  case SETUP_READY:
    Serial.println("[Setup] READY");
    player.playEmotion("success", 0.6);
    break;
  default:
    break;
  }
}

// Closes the setup screen: eyes open from small to full size.
void finishSetup() {
  setupStage = SETUP_DONE;
  lastClientMillis = millis();
  setupStatus = "";

  oledMode = OLED_IDLE;
  speechBoxWidth = 0.0;
  speechBoxEntering = false;
  speechBoxExiting = false;
  speechBoxPersist = false;

  currentEyeScale = 0.3;
  targetEyeScale = 1.0;
  currentEyeX = targetEyeX = 64.0;
  currentEyeY = targetEyeY = 32.0;
  face->Expression.GoTo_Happy();
  face->DoBlink();
  animationLastMillis = millis();
}

bool pcPresent() {
  unsigned long now = millis();
  bool announced = lastPcSeenMillis != 0 && now - lastPcSeenMillis < PC_PRESENCE_MS;
  return announced || webSocket.connectedClients() > 0;
}

// Reads "IKRU-PC|<ip>" announcements from the PC (UDP 4211).
void checkPcAnnounce() {
  int size = pcUdp.parsePacket();
  if (!size) return;
  char buf[48];
  int len = pcUdp.read(buf, sizeof(buf) - 1);
  if (len <= 0) return;
  buf[len] = '\0';
  if (strncmp(buf, "IKRU-PC|", 8) == 0) {
    if (lastPcSeenMillis == 0 || millis() - lastPcSeenMillis >= PC_PRESENCE_MS) {
      Serial.printf("[Setup] PC announced from %s\n", buf + 8);
    }
    lastPcSeenMillis = millis();
  }
}

// Stage transitions. Called every loop while setup is running.
void updateSetupStage() {
  unsigned long now = millis();
  unsigned long t = now - setupStageStart;
  bool online = WiFi.status() == WL_CONNECTED;

  // Losing Wi-Fi at any point sends us back to finding the hub
  if (!online && setupStage >= SETUP_JOINED && setupStage <= SETUP_LINK) {
    tryingSaved = false;
    wifiAttemptStart = now;
    setSetupStage(SETUP_HUB);
    return;
  }

  switch (setupStage) {

  case SETUP_BOOT:
    if (t >= BOOT_ANIM_MS) setSetupStage(online ? SETUP_JOINED : SETUP_HUB);
    break;

  case SETUP_HUB:
    if (online) {
      setSetupStage(SETUP_JOINED);
    } else if (!tryingSaved && savedSsid.length() > 0 &&
               now - wifiAttemptStart >= HUB_ATTEMPT_MS) {
      // Hub hasn't appeared: give the saved network a turn, then go back to the hub
      Serial.printf("[WiFi] Hub not found. Trying saved network: %s\n", savedSsid.c_str());
      tryingSaved = true;
      WiFi.disconnect();
      delay(100);
      beginStation(savedSsid.c_str(), savedPass.c_str());
    } else if (tryingSaved && now - wifiAttemptStart >= SAVED_ATTEMPT_MS) {
      tryingSaved = false;
      WiFi.disconnect();
      delay(100);
      beginStation(fallback_ssid, fallback_pass);
    }
    break;

  case SETUP_JOINED:
    if (t >= JOINED_ANIM_MS) setSetupStage(pcPresent() ? SETUP_LINK : SETUP_WAIT_PC);
    break;

  case SETUP_WAIT_PC:
    if (pcPresent()) setSetupStage(SETUP_LINK);
    break;

  case SETUP_LINK:
    if (!pcPresent() && t > PC_PRESENCE_MS) {
      setupStatus = "";
      setSetupStage(SETUP_WAIT_PC);
    } else if (t >= LINK_TIMEOUT_MS) {
      setSetupStage(SETUP_READY);
    }
    break;

  case SETUP_READY:
    if (t >= READY_ANIM_MS) finishSetup();
    break;

  default:
    break;
  }
}

// After setup: if the PC goes away, go back to the "Waiting for PC" screen.
void watchPcLink() {
  unsigned long now = millis();
  if (webSocket.connectedClients() > 0) {
    lastClientMillis = now;
  } else if (now - lastClientMillis >= PC_LOST_MS) {
    Serial.println("[Setup] PC link lost.");
    stopMotors();
    player.stop();
    setupStatus = "";
    setSetupStage(WiFi.status() == WL_CONNECTED ? SETUP_WAIT_PC : SETUP_HUB);
  }
}

// ---------------- drawing helpers ----------------

void drawCentered(int y, const char *text) {
  int w = u8g2.getStrWidth(text);
  u8g2.drawStr((128 - w) / 2, y, text);
}

// Progress pips: done = filled, current = pulsing ring, upcoming = small ring.
void drawSetupPips(int current, unsigned long now) {
  const int xs[4] = {16, 48, 80, 112};
  const int y = 5;
  for (int i = 0; i < 4; i++) {
    if (i < 3) {
      int x0 = xs[i] + 5;
      int x1 = xs[i + 1] - 5;
      if (i < current) {
        u8g2.drawHLine(x0, y, x1 - x0);
      } else {
        for (int x = x0; x < x1; x += 4) u8g2.drawPixel(x, y);
      }
    }
    if (i < current) {
      u8g2.drawDisc(xs[i], y, 3);
    } else if (i == current) {
      u8g2.drawCircle(xs[i], y, 3 + ((now / 250) % 2));
      u8g2.drawDisc(xs[i], y, 1);
    } else {
      u8g2.drawCircle(xs[i], y, 2);
    }
  }
}

// Small robot face (left) with an occasional blink.
void drawRobotIcon(int x, int y, unsigned long now) {
  u8g2.drawRFrame(x, y, 24, 20, 4);
  bool blink = (now % 2600) < 140;
  if (blink) {
    u8g2.drawHLine(x + 5, y + 9, 5);
    u8g2.drawHLine(x + 14, y + 9, 5);
  } else {
    u8g2.drawRBox(x + 5, y + 6, 5, 7, 1);
    u8g2.drawRBox(x + 14, y + 6, 5, 7, 1);
  }
}

// Small monitor (right).
void drawPcIcon(int x, int y) {
  u8g2.drawRFrame(x, y, 26, 17, 2);
  u8g2.drawBox(x + 10, y + 17, 6, 3);
  u8g2.drawHLine(x + 6, y + 20, 14);
}

void drawSetupScreen() {
  unsigned long now = millis();
  unsigned long t = now - setupStageStart;
  char line[32];

  u8g2.clearBuffer();
  u8g2.setDrawColor(1);
  u8g2.setFontMode(1);

  int pip = 0;
  if (setupStage == SETUP_HUB || setupStage == SETUP_JOINED) pip = 1;
  else if (setupStage == SETUP_WAIT_PC) pip = 2;
  else if (setupStage == SETUP_LINK) pip = 3;
  else if (setupStage == SETUP_READY) pip = 4;
  drawSetupPips(pip, now);

  switch (setupStage) {

  // --- 1. Logo wipes open from the centre, then a loading bar fills
  case SETUP_BOOT: {
    float p = min(1.0f, (float)t / (BOOT_ANIM_MS * 0.4f));
    int reveal = (int)(64 * (1.0f - (1.0f - p) * (1.0f - p)));
    u8g2.setFont(u8g2_font_ncenB14_tr);
    u8g2.setClipWindow(64 - reveal, 12, 64 + reveal, 40);
    drawCentered(34, "IKRU");
    u8g2.setMaxClipWindow();

    float bar = min(1.0f, (float)t / (float)BOOT_ANIM_MS);
    u8g2.drawRFrame(24, 40, 80, 6, 2);
    u8g2.drawBox(26, 42, (int)(76 * bar), 2);

    u8g2.setFont(u8g2_font_6x10_tr);
    drawCentered(60, "powered by potatoes");
    break;
  }

  // --- 2. Wi-Fi arcs radiate while searching for the hub
  case SETUP_HUB: {
    const int cx = 64, cy = 44;
    int phase = (t / 300) % 5;  // 0..3 arcs, then a pause
    u8g2.drawDisc(cx, cy, 2);
    for (int i = 1; i <= 3; i++) {
      if (phase >= i) {
        u8g2.drawCircle(cx, cy, 7 * i, U8G2_DRAW_UPPER_LEFT | U8G2_DRAW_UPPER_RIGHT);
      }
    }
    u8g2.setFont(u8g2_font_6x10_tr);
    if (tryingSaved) {
      snprintf(line, sizeof(line), "Trying %.14s", savedSsid.c_str());
      drawCentered(60, line);
    } else {
      drawCentered(60, (t / 2500) % 2 ? "Is the head on?" : "Finding IKRU-CAM");
    }
    break;
  }

  // --- 3. Check mark draws itself inside a growing ring
  case SETUP_JOINED: {
    const int cx = 64, cy = 30;
    float p = min(1.0f, (float)t / 400.0f);
    u8g2.drawCircle(cx, cy, (int)(4 + 10 * p));
    float c = constrain(((float)t - 300.0f) / 400.0f, 0.0f, 1.0f);
    if (c > 0) {
      float c1 = min(1.0f, c * 2.0f);
      u8g2.drawLine(cx - 6, cy, cx - 6 + (int)(4 * c1), cy + (int)(4 * c1));
      if (c > 0.5f) {
        float c2 = (c - 0.5f) * 2.0f;
        u8g2.drawLine(cx - 2, cy + 4, cx - 2 + (int)(8 * c2), cy + 4 - (int)(9 * c2));
      }
    }
    u8g2.setFont(u8g2_font_6x10_tr);
    if (t < 750) {
      snprintf(line, sizeof(line), "On %.16s", WiFi.SSID().c_str());
    } else {
      snprintf(line, sizeof(line), "%s", WiFi.localIP().toString().c_str());
    }
    drawCentered(60, line);
    break;
  }

  // --- 4. Robot calls out towards the PC (dots travel one way)
  case SETUP_WAIT_PC: {
    drawRobotIcon(8, 20, now);
    drawPcIcon(94, 20);
    int offset = (t / 35) % 18;
    for (int x = 36 + offset; x < 90; x += 18) {
      u8g2.drawDisc(x, 29, 1);
    }
    u8g2.setFont(u8g2_font_6x10_tr);
    if ((t / 2500) % 2) {
      snprintf(line, sizeof(line), "%s", WiFi.localIP().toString().c_str());
      drawCentered(60, line);
    } else {
      drawCentered(60, "Waiting for PC");
    }
    break;
  }

  // --- 5. Linked: solid cable with data flowing both ways + PC progress
  case SETUP_LINK: {
    drawRobotIcon(8, 20, now);
    drawPcIcon(94, 20);
    u8g2.drawHLine(34, 29, 58);
    int a = (t / 20) % 54;
    u8g2.drawBox(35 + a, 27, 3, 5);
    u8g2.drawBox(88 - a, 27, 3, 5);

    u8g2.setFont(u8g2_font_6x10_tr);
    int dots = (t / 400) % 4;
    const char *status = setupStatus.length() > 0 ? setupStatus.c_str() : "PC found";
    snprintf(line, sizeof(line), "%.17s%.*s", status, dots, "...");
    // Centre on the text without dots so it doesn't jump as they animate
    u8g2.drawStr((128 - u8g2.getStrWidth(status)) / 2, 60, line);
    break;
  }

  // --- 6. Big check + READY!
  case SETUP_READY: {
    float p = min(1.0f, (float)t / 300.0f);
    u8g2.drawDisc(64, 26, (int)(12 * p));
    if (p >= 1.0f) {
      u8g2.setDrawColor(0);
      u8g2.drawLine(58, 26, 62, 30);
      u8g2.drawLine(59, 26, 63, 30);
      u8g2.drawLine(62, 30, 70, 21);
      u8g2.drawLine(63, 30, 71, 21);
      u8g2.setDrawColor(1);
    }
    u8g2.setFont(u8g2_font_ncenB14_tr);
    if ((t / 250) % 2 || t > 1000) drawCentered(60, "READY!");
    break;
  }

  default:
    break;
  }

  u8g2.sendBuffer();
}

// Commands the robot still obeys while its setup screen is up
// (face, sound, display and drive commands wait for SETUP_DONE).
bool allowedDuringSetup(const String &cmd) {
  return cmd == "STOP" || cmd == "GET_DISTANCE" || cmd.equalsIgnoreCase("GET_IP") ||
         cmd.startsWith("SET_WIFI:") || cmd.startsWith("SET_OBSTACLE_THRESHOLD:") ||
         cmd.startsWith("THRESHOLD:") || cmd.startsWith("OBSTACLE_BRAKE_") ||
         cmd.startsWith("VOLUME:") || cmd.startsWith("SET_VOLUME:");
}

// ============================================================
// R2-D2 DROID EMOTION & PARALINGUISTIC SOUND SYNTHESIZER
// ============================================================

void SonicPlayer::playEmotion(String emotion, float intensity) {
  emotion.toLowerCase();
  emotion.trim();
  intensity = constrain(intensity, 0.0f, 1.0f);

  DroidStep seq[MAX_SEQUENCE_STEPS];
  uint8_t count = 0;

  Serial.printf("[SonicPlayer] Playing: %s (intensity: %.2f)\n", emotion.c_str(), intensity);

  // 1. HAPPY
  if (emotion == "happy") {
    float p = 1.0f + (0.25f * intensity);
    uint16_t base = 1200 * p;
    uint16_t mid  = 1800 * p;
    uint16_t high = 2600 * p;
    uint16_t top  = 3200 * p;
    seq[count++] = {base, mid, 55, 12};
    seq[count++] = {mid, high, 65, 12};
    seq[count++] = {high, top, 110, 0};
  }

  // 2. GLEE / EXCITED
  else if (emotion == "glee" || emotion == "excited") {
    float p = 1.0f + (0.3f * intensity);
    uint16_t b = 1400 * p;
    seq[count++] = {b, (uint16_t)(b + 500), 35, 6};
    seq[count++] = {(uint16_t)(b + 400), (uint16_t)(b + 1000), 35, 6};
    seq[count++] = {(uint16_t)(b + 900), (uint16_t)(b + 1600), 45, 8};
    seq[count++] = {(uint16_t)(b + 1200), (uint16_t)(b + 1800), 18, 4};
    seq[count++] = {(uint16_t)(b + 1800), (uint16_t)(b + 1200), 18, 4};
    seq[count++] = {(uint16_t)(b + 1400), (uint16_t)(b + 2200), 110, 0};
  }

  // 3. SAD
  else if (emotion == "sad") {
    uint16_t top    = 2400 - (uint16_t)(200 * intensity);
    uint16_t bottom = 550 - (uint16_t)(150 * intensity);
    uint16_t dur    = 320 + (uint16_t)(220 * intensity);
    seq[count++] = {(uint16_t)(top - 100), top, 60, 25};
    seq[count++] = {top, bottom, dur, 30};
    seq[count++] = {(uint16_t)(bottom + 80), bottom, 140, 0};
  }

  // 4. SIGH (Gentle, slow descending melancholic slide)
  else if (emotion == "sigh") {
    uint16_t startF = 1900;
    uint16_t endF   = 450;
    seq[count++] = {startF, (uint16_t)(startF + 100), 60, 15};
    seq[count++] = {(uint16_t)(startF + 100), endF, 420, 0};
  }

  // 5. GASP (Sudden sharp high-speed upward leap)
  else if (emotion == "gasp") {
    seq[count++] = {850, 3600, 45, 8};
    seq[count++] = {3600, 3200, 30, 4};
    seq[count++] = {3200, 3700, 50, 0};
  }

  // 6. GIGGLE / CHUCKLE (Playful high-frequency warbles)
  else if (emotion == "giggle" || emotion == "chuckle") {
    seq[count++] = {2200, 2800, 25, 8};
    seq[count++] = {2800, 2400, 25, 8};
    seq[count++] = {2400, 3100, 25, 8};
    seq[count++] = {3100, 2600, 25, 8};
    seq[count++] = {2600, 3200, 35, 0};
  }

  // 7. LAUGHTER / LAUGH (Hearty multi-burst ascending staccato chirps)
  else if (emotion == "laughter" || emotion == "laugh") {
    seq[count++] = {1600, 2400, 35, 12};
    seq[count++] = {2200, 2800, 35, 12};
    seq[count++] = {2000, 3000, 40, 15};
    seq[count++] = {2600, 3400, 50, 8};
    seq[count++] = {3200, 3600, 60, 0};
  }

  // 8. GROAN (Low-frequency vibrating raspy buzz)
  else if (emotion == "groan") {
    seq[count++] = {400, 320, 90, 15};
    seq[count++] = {320, 240, 140, 15};
    seq[count++] = {240, 180, 180, 0};
  }

  // 9. CLEAR_THROAT / THROAT (Crisp double mid-pitch pulse)
  else if (emotion == "clear_throat" || emotion == "throat") {
    seq[count++] = {1500, 1750, 35, 30};
    seq[count++] = {1600, 1850, 45, 0};
  }

  // 10. CRY / SOB (Melancholic tremolo weeping slide)
  else if (emotion == "cry" || emotion == "sob") {
    seq[count++] = {1800, 1600, 80, 15};
    seq[count++] = {1600, 1700, 60, 10};
    seq[count++] = {1700, 1100, 180, 20};
    seq[count++] = {1100, 600, 220, 0};
  }

  // 11. WHISPER (Delicate tiny soft micro-beeps)
  else if (emotion == "whisper") {
    seq[count++] = {2400, 2600, 18, 12};
    seq[count++] = {2700, 2500, 18, 12};
    seq[count++] = {2800, 3000, 22, 0};
  }

  // 12. SNIFF (Quick upward intake blip)
  else if (emotion == "sniff") {
    seq[count++] = {1300, 2300, 35, 0};
  }

  // 13. COUGH (Low staccato cough thumps)
  else if (emotion == "cough") {
    seq[count++] = {480, 280, 40, 30};
    seq[count++] = {450, 250, 50, 0};
  }

  // 14. SNEEZE (Rising inhale followed by explosive release)
  else if (emotion == "sneeze") {
    seq[count++] = {1400, 2600, 70, 25};
    seq[count++] = {3500, 800, 90, 0};
  }

  // 15. INHALE / EXHALE
  else if (emotion == "inhale") {
    seq[count++] = {1000, 2400, 200, 0};
  } else if (emotion == "exhale") {
    seq[count++] = {2400, 900, 220, 0};
  }

  // 16. THINKING / FOCUSED / PROCESSING
  else if (emotion == "thinking" || emotion == "focused" || emotion == "processing") {
    uint16_t f = 1800 + (uint16_t)(300 * intensity);
    seq[count++] = {f, (uint16_t)(f + 150), 22, 35};
    seq[count++] = {f, (uint16_t)(f + 150), 22, 35};
    seq[count++] = {f, (uint16_t)(f + 150), 22, 35};
    seq[count++] = {f, (uint16_t)(f + 150), 22, 0};
  }

  // 17. ANGRY / FURIOUS / FRUSTRATED / ANNOYED
  else if (emotion == "angry" || emotion == "furious" || emotion == "frustrated" || emotion == "annoyed") {
    uint16_t low_a = 350 + (uint16_t)(50 * intensity);
    uint16_t low_b = 750 + (uint16_t)(100 * intensity);
    seq[count++] = {low_b, low_a, 50, 10};
    seq[count++] = {low_a, (uint16_t)(low_b + 100), 45, 12};
    seq[count++] = {(uint16_t)(low_b + 100), (uint16_t)(low_a - 50), 60, 15};
    if (intensity > 0.4f) {
      seq[count++] = {2200, 3400, 35, 6};
      seq[count++] = {3400, 2200, 35, 6};
      seq[count++] = {2200, 3400, 60, 0};
    }
  }

  // 18. WORRIED
  else if (emotion == "worried") {
    seq[count++] = {1600, 1300, 70, 20};
    seq[count++] = {1300, 1100, 90, 20};
    seq[count++] = {1100, 850, 120, 0};
  }

  // 19. SURPRISED / SCARED
  else if (emotion == "surprised" || emotion == "scared") {
    uint16_t top = 3400 + (uint16_t)(600 * intensity);
    seq[count++] = {800, top, 55, 10};
    seq[count++] = {top, (uint16_t)(top - 400), 30, 6};
    seq[count++] = {(uint16_t)(top - 400), top, 40, 0};
  }

  // 20. CONFUSED / SKEPTIC / SUSPICIOUS
  else if (emotion == "confused" || emotion == "skeptic" || emotion == "suspicious") {
    seq[count++] = {1100, 1400, 45, 25};
    seq[count++] = {1600, 1200, 50, 30};
    seq[count++] = {950, (uint16_t)(2600 + (400 * intensity)), 110, 0};
  }

  // 21. SLEEPY / UNIMPRESSED
  else if (emotion == "sleepy" || emotion == "unimpressed") {
    seq[count++] = {1800, 1500, 90, 40};
    seq[count++] = {1500, 600, 350, 30};
    seq[count++] = {550, 300, 160, 0};
  }

  // 22. AWE / AFFECTION
  else if (emotion == "awe" || emotion == "affection") {
    seq[count++] = {1200, 1600, 70, 15};
    seq[count++] = {1500, 2200, 80, 15};
    seq[count++] = {2200, 1900, 60, 15};
    seq[count++] = {1900, 2800, 150, 0};
  }

  // 23. SQUINT
  else if (emotion == "squint") {
    seq[count++] = {1400, 1650, 40, 50};
    seq[count++] = {1750, 1500, 40, 50};
    seq[count++] = {1550, 1850, 45, 0};
  }

  // 24. SUCCESS / TRIUMPH
  else if (emotion == "success" || emotion == "happy_success") {
    float p = 1.0f + (0.2f * intensity);
    seq[count++] = {(uint16_t)(1100 * p), (uint16_t)(1500 * p), 50, 10};
    seq[count++] = {(uint16_t)(1500 * p), (uint16_t)(2000 * p), 55, 10};
    seq[count++] = {(uint16_t)(2000 * p), (uint16_t)(2700 * p), 65, 12};
    uint16_t top = 3200 * p;
    seq[count++] = {(uint16_t)(top - 150), (uint16_t)(top + 150), 22, 2};
    seq[count++] = {(uint16_t)(top + 150), (uint16_t)(top - 150), 22, 2};
    seq[count++] = {top, (uint16_t)(top * 1.1f), 150, 0};
  }

  // 25. ERROR / FAILED
  else if (emotion == "error" || emotion == "failed") {
    seq[count++] = {700, 220, 90, 40};
    seq[count++] = {650, 180, 120, 0};
  }

  // 26. WARNING
  else if (emotion == "warning") {
    uint16_t high = 2800 + (uint16_t)(400 * intensity);
    uint16_t low  = 1800 + (uint16_t)(300 * intensity);
    seq[count++] = {low, high, 45, 6};
    seq[count++] = {high, low, 45, 8};
    seq[count++] = {low, high, 45, 6};
    seq[count++] = {high, low, 45, 0};
  }

  // 27. CANNOT_PERFORM / BLOCKED
  else if (emotion == "cannot_perform" || emotion == "blocked") {
    seq[count++] = {1300, 750, 110, 40};
    seq[count++] = {900, 450, 140, 0};
  }

  // 28. DEFAULT / NORMAL / NEUTRAL
  else {
    seq[count++] = {1300, 1900, 50, 20};
    seq[count++] = {1700, 2500, 80, 0};
  }

  playSequence(seq, count);
}

void SonicPlayer::playConversationalChirp(String emotion) {
  emotion.toLowerCase();
  DroidStep seq[4];
  uint8_t count = 0;

  // Generate dynamic conversational droid syllables matching the active emotion
  int r = random(3);
  if (emotion == "happy" || emotion == "glee" || emotion == "excited") {
    uint16_t b = 1300 + random(600);
    uint16_t e = b + 300 + random(500);
    seq[count++] = {b, e, (uint16_t)(35 + random(30)), (uint16_t)(15 + random(25))};
    if (r > 0) {
      uint16_t h = e + 200 + random(400);
      seq[count++] = {e, h, (uint16_t)(40 + random(40)), (uint16_t)(25 + random(40))};
    }
  } else if (emotion == "sad" || emotion == "worried") {
    uint16_t b = 1600 + random(400);
    uint16_t e = b > 500 ? b - 300 - random(300) : 500;
    seq[count++] = {b, e, (uint16_t)(60 + random(40)), (uint16_t)(20 + random(30))};
    if (r > 0) {
      seq[count++] = {e, (uint16_t)(e - 150), 70, 30};
    }
  } else if (emotion == "angry" || emotion == "frustrated" || emotion == "annoyed" || emotion == "furious") {
    uint16_t b = 400 + random(300);
    uint16_t e = 250 + random(200);
    seq[count++] = {b, e, (uint16_t)(45 + random(30)), (uint16_t)(15 + random(20))};
    if (r > 0) {
      seq[count++] = {2200, 2800, 30, 20};
    }
  } else {
    // Normal / conversational droid chatter
    uint16_t b = 1200 + random(700);
    uint16_t e = b + (random(2) == 0 ? 350 : -250);
    seq[count++] = {b, e, (uint16_t)(40 + random(35)), (uint16_t)(20 + random(35))};
    if (r > 0) {
      uint16_t e2 = e + 250 + random(400);
      seq[count++] = {e, e2, (uint16_t)(45 + random(35)), (uint16_t)(25 + random(40))};
    }
  }

  playSequence(seq, count);
}



// ============================================================
// ULTRASONIC DISTANCE MEASUREMENT & OBSTACLE AUTO-BRAKE
// ============================================================

// 5-sample median filter to reject noise, floor bounces, and acoustic spikes
const int SONAR_SAMPLES = 5;
float sonarHistory[SONAR_SAMPLES] = {999.0, 999.0, 999.0, 999.0, 999.0};
int sonarHistoryIdx = 0;

float getMedianDistance() {
  float sorted[SONAR_SAMPLES];
  for (int i = 0; i < SONAR_SAMPLES; i++) sorted[i] = sonarHistory[i];
  // Simple insertion sort for 5 elements
  for (int i = 1; i < SONAR_SAMPLES; i++) {
    float key = sorted[i];
    int j = i - 1;
    while (j >= 0 && sorted[j] > key) {
      sorted[j + 1] = sorted[j];
      j--;
    }
    sorted[j + 1] = key;
  }
  return sorted[2]; // Middle element (median)
}

void updateUltrasonic() {
  unsigned long now = millis();
  if (now - lastSonarTime < SONAR_INTERVAL_MS) {
    return;
  }
  lastSonarTime = now;

  // Clear trigger pin
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(4);

  // Emit 10 microsecond HIGH pulse
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // Measure pulse duration (timeout = 25000 us = ~400 cm max range)
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 25000);

  float rawDistance = 999.0;
  if (duration > 0) {
    // Speed of sound = 343 m/s = 0.0343 cm/us -> distance = (duration * 0.0343) / 2
    rawDistance = (duration * 0.0343) / 2.0;

    // Discard acoustic cross-talk / transducer blind zone (< 2.5 cm)
    if (rawDistance < 2.5) {
      rawDistance = 999.0;
    }
  }

  // Push into median filter history buffer
  sonarHistory[sonarHistoryIdx] = rawDistance;
  sonarHistoryIdx = (sonarHistoryIdx + 1) % SONAR_SAMPLES;

  // Compute smooth filtered distance
  currentDistanceCm = getMedianDistance();

  // Autonomous Safety Emergency Brake (uses clean filtered distance)
  if (safetyBrakeEnabled && isMovingForward && currentDistanceCm >= 3.0 && currentDistanceCm < obstacleThresholdCm) {
    stopMotors();
    Serial.printf("[SAFETY] Obstacle detected at %.1f cm! Motors halted.\n", currentDistanceCm);

    // Broadcast obstacle alert JSON over WebSocket
    String alert = "{\"event\":\"obstacle_alert\",\"distance_cm\":" + String(currentDistanceCm, 1) + "}";
    webSocket.broadcastTXT(alert);

    // Visual & audio feedback
    emotionWorried();
    player.playEmotion("worried", 0.6);
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {

  // Motor driver (DRV8833): keep it asleep until the IN pins are held in brake
  pinMode(MOTOR_EEP, OUTPUT);
  pinMode(MOTOR_EEP_ALT, OUTPUT);
  digitalWrite(MOTOR_EEP, LOW);
  digitalWrite(MOTOR_EEP_ALT, LOW);
  pinMode(MOTOR_FAULT, INPUT_PULLUP);
  ledcAttach(MOTOR_IN1, MOTOR_PWM_FREQ, MOTOR_PWM_BITS);
  ledcAttach(MOTOR_IN2, MOTOR_PWM_FREQ, MOTOR_PWM_BITS);
  ledcAttach(MOTOR_IN3, MOTOR_PWM_FREQ, MOTOR_PWM_BITS);
  ledcAttach(MOTOR_IN4, MOTOR_PWM_FREQ, MOTOR_PWM_BITS);
  stopMotors();
  digitalWrite(MOTOR_EEP, HIGH);
  digitalWrite(MOTOR_EEP_ALT, HIGH);

  // Forklift servo: start fully lowered
  ledcAttach(FORK_PIN, FORK_PWM_FREQ, FORK_PWM_BITS);
  forkWrite(FORK_MIN_DEG);

  // Ultrasonic sensor pins
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);

  // Serial
  Serial.begin(115200);
  Serial.println();
  Serial.println("==============================");
  Serial.println("       IKRU STARTING");
  Serial.println("==============================");

  // Stop motors immediately
  stopMotors();

  // OLED + Face library init
  oledStartup();

  // ============================================================
  // SMARTELEX DIGITAL SPEAKER (R2-D2 DROID AUDIO)
  // ============================================================
  Serial.println("Starting SmartElex Sonic Speaker on GPIO 25...");
  player.begin();

  // WiFi: start joining the IKRU-CAM hub. The setup screen (loop) animates
  // each stage and falls back to the saved network if the hub never appears.
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  preferences.begin("ikru_wifi", true);
  savedSsid = preferences.getString("ssid", "");
  savedPass = preferences.getString("pass", "");
  preferences.end();
  if (savedSsid == fallback_ssid) savedSsid = "";

  Serial.println("[WiFi] Joining IKRU-CAM hub (fixed IP 192.168.4.200)...");
  beginStation(fallback_ssid, fallback_pass);

  // WebSocket
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);
  Serial.println("WebSocket Server Started");

  // Listen for the PC's "I'm on the hub" announcements
  pcUdp.begin(PC_ANNOUNCE_PORT);

  face->Expression.GoTo_Normal();
  animationLastMillis = millis();

  setSetupStage(SETUP_BOOT);
  player.playEmotion("inhale", 0.5);
}

// ============================================================
// MAIN LOOP
// ============================================================

void pollSerial() {
  if (Serial.available()) {
    String serialCmd = Serial.readStringUntil('\n');
    serialCmd.trim();
    if (serialCmd.length() > 0) {
      Serial.print("[Serial] Received: ");
      Serial.println(serialCmd);
      parseCommand(serialCmd);
    }
  }
}

void loop() {

  // WebSocket
  webSocket.loop();

  // Discovery beacon + Wi-Fi re-join watchdog
  updateNetwork();

  // PC "I'm on the hub" announcements
  checkPcAnnounce();

  // Ultrasonic distance measurement & obstacle safety brake
  updateUltrasonic();

  // DRV8833 nFAULT line
  checkMotorFault();

  // Non-blocking R2-D2 glissando audio sequencer
  player.update();

  // Setup screen owns the OLED until the PC sends SETUP_DONE
  if (setupStage != SETUP_DONE) {
    updateSetupStage();
    drawSetupScreen();
    player.update();
    delay(5);
    pollSerial();
    return;
  }

  // Back to the setup screen if the PC disconnects
  watchPcLink();

  // Update speech scroll (moves text and triggers conversational droid chatter)
  updateSpeechScroll();

  unsigned long now = millis();
  float dt = (now - animationLastMillis) / 1000.0;
  animationLastMillis = now;

  // Smooth interpolation for eyes (approx 600ms transition)
  float lerpFactor = 10.0 * dt;
  if (lerpFactor > 1.0) lerpFactor = 1.0;

  currentEyeScale += (targetEyeScale - currentEyeScale) * lerpFactor;
  currentEyeX += (targetEyeX - currentEyeX) * lerpFactor;
  currentEyeY += (targetEyeY - currentEyeY) * lerpFactor;

  face->CurrentScale = currentEyeScale;
  face->CenterX = (uint16_t)currentEyeX;
  face->CenterY = (uint16_t)currentEyeY;

  // Clear buffer for new frame
  u8g2.clearBuffer();

  // Draw speech box whenever it has any width
  if (speechBoxWidth > 0) {
    drawSpeakingText();
  }

  // Draw animated eyes (handles blinking, expressions, eye tracking)
  face->Update();

  // Render to OLED
  u8g2.sendBuffer();

  // Intermediate audio update
  player.update();

  // Yield to FreeRTOS (prevents Watchdog Timeout and Wi-Fi drops)
  delay(5);

  // Serial command listener (via USB)
  pollSerial();
}

// ============================================================
// WEBSOCKET EVENT
// ============================================================

void webSocketEvent(uint8_t client, WStype_t type, uint8_t *payload,
                    size_t length) {

  switch (type) {

    // CONNECTED
  case WStype_CONNECTED:
    Serial.println("Client Connected");
    break;

    // DISCONNECTED
  case WStype_DISCONNECTED:
    Serial.println("Client Disconnected");
    stopMotors();
    break;

    // TEXT
  case WStype_TEXT: {
    String cmd = String((char *)payload);
    cmd.trim();

    if (cmd.equalsIgnoreCase("GET_DISTANCE")) {
      String reply = "{\"type\":\"distance\",\"cm\":" + String(currentDistanceCm, 1) + "}";
      webSocket.sendTXT(client, reply);
      return;
    }

    Serial.print("Received: ");
    Serial.println(cmd);

    parseCommand(cmd);
    // Reply to Python
    webSocket.sendTXT(client, "OK");
    break;
  }

  default:
    break;
  }
}

// ============================================================
// COMMAND PARSER
// ============================================================

void parseCommand(String input) {

  input.trim();

  // ==========================================================
  // SETUP SCREEN PROTOCOL
  // SETUP:<text>  -> PC progress line on the link screen
  // SETUP_DONE    -> ready animation, then the face wakes up
  // ==========================================================

  if (input == "SETUP_DONE") {
    if (setupStage != SETUP_DONE && setupStage != SETUP_READY) {
      setSetupStage(SETUP_READY);
    }
    return;
  }

  if (input.startsWith("SETUP:")) {
    setupStatus = input.substring(6);
    setupStatus.trim();
    if (setupStage == SETUP_WAIT_PC) setSetupStage(SETUP_LINK);
    return;
  }

  if (setupStage != SETUP_DONE && !allowedDuringSetup(input)) {
    return;  // Face isn't on screen yet
  }

  // ==========================================================
  // EYE LOOK & BLINK COMMANDS
  // ==========================================================

  if (input == "BLINK") {
    face->DoBlink();
    return;
  }

  if (input.startsWith("LOOK:")) {
    int firstColon = input.indexOf(':');
    int secondColon = input.indexOf(':', firstColon + 1);
    if (secondColon != -1) {
      float lx = input.substring(firstColon + 1, secondColon).toFloat();
      float ly = input.substring(secondColon + 1).toFloat();
      face->Look.LookAt(lx, ly);
    }
    return;
  }

  if (input == "LOOK_LEFT") { face->LookLeft(); return; }
  if (input == "LOOK_RIGHT") { face->LookRight(); return; }
  if (input == "LOOK_FRONT") { face->LookFront(); return; }
  if (input == "LOOK_TOP") { face->LookTop(); return; }
  if (input == "LOOK_BOTTOM") { face->LookBottom(); return; }

  // ==========================================================
  // DISPLAY COMMANDS (Full OLED Scrolling Speech Box)
  // ==========================================================

  if (input == "DISPLAY_OPEN") {
    oledOpen();
    return;
  }

  if (input == "DISPLAY_CLOSE") {
    oledClose();
    return;
  }

  if (input.startsWith("DISPLAY:")) {
    String message = input.substring(8);
    oledMessage(message);
    return;
  }

  // ==========================================================
  // ULTRASONIC SENSOR & SAFETY COMMANDS
  // ==========================================================

  if (input == "GET_DISTANCE") {
    Serial.printf("[SONAR] Distance: %.1f cm\n", currentDistanceCm);
    String reply = "{\"type\":\"distance\",\"cm\":" + String(currentDistanceCm, 1) + "}";
    webSocket.broadcastTXT(reply);
    return;
  }

  if (input.startsWith("SET_OBSTACLE_THRESHOLD:") || input.startsWith("THRESHOLD:")) {
    int colonIdx = input.indexOf(':');
    float th = input.substring(colonIdx + 1).toFloat();
    if (th > 0) {
      obstacleThresholdCm = th;
      Serial.printf("[SONAR] Obstacle threshold set to %.1f cm\n", obstacleThresholdCm);
    }
    return;
  }

  if (input == "OBSTACLE_BRAKE_ON") {
    safetyBrakeEnabled = true;
    Serial.println("[SONAR] Safety auto-brake ENABLED");
    return;
  }

  if (input == "OBSTACLE_BRAKE_OFF") {
    safetyBrakeEnabled = false;
    Serial.println("[SONAR] Safety auto-brake DISABLED");
    return;
  }

  // ==========================================================
  // AUDIO & SOUND COMMANDS
  // ==========================================================

  if (input.startsWith("SOUND:")) {
    String payload = input.substring(6);
    payload.trim();
    int colonIdx = payload.indexOf(':');
    String soundName = payload;
    float intensity = 0.5f;
    if (colonIdx != -1) {
      soundName = payload.substring(0, colonIdx);
      intensity = payload.substring(colonIdx + 1).toFloat();
    }
    soundName.toLowerCase();
    player.playEmotion(soundName, intensity);
    return;
  }

  if (input == "STOP_AUDIO" || input == "STOP_SOUND") {
    player.stop();
    return;
  }

  // ==========================================================
  // VOLUME CONTROL COMMAND
  // Format: VOLUME:<0-100> or SET_VOLUME:<0-100>
  // ==========================================================

  if (input.startsWith("VOLUME:") || input.startsWith("SET_VOLUME:")) {
    int colonIdx = input.indexOf(':');
    int vol = input.substring(colonIdx + 1).toInt();
    vol = constrain(vol, 0, 100);
    Serial.printf("[Audio] Firmware volume command received: %d%%\n", vol);
    return;
  }

  // ==========================================================
  // WIFI CONFIGURATION COMMAND (Case-sensitive SSID & Pass)
  // Format: SET_WIFI:<ssid>:<pass>
  // ==========================================================

  if (input.startsWith("SET_WIFI:")) {
    int firstColon = input.indexOf(':');
    int secondColon = input.indexOf(':', firstColon + 1);
    if (secondColon != -1) {
      String new_ssid = input.substring(firstColon + 1, secondColon);
      String new_pass = input.substring(secondColon + 1);
      new_ssid.trim();
      new_pass.trim();
      applyNewWiFi(new_ssid, new_pass);
    }
    return;
  }

  // ==========================================================
  // NETWORK INFO QUERY (used over USB serial to find the robot)
  // Format: GET_IP -> "IP:<ip> SSID:<ssid> MODE:<STA|AP>"
  // ==========================================================

  if (input.equalsIgnoreCase("GET_IP")) {
    String ip = WiFi.localIP().toString();
    String ssid = WiFi.SSID();
    Serial.printf("IP:%s SSID:%s MODE:STA\n", ip.c_str(), ssid.c_str());
    return;
  }

  // Convert to uppercase for all other commands
  input.toUpperCase();

  // ==========================================================
  // EMOTION & EXPRESSION COMMANDS (SYNCHRONIZED OLED + R2-D2 VOICE)
  // ==========================================================

  currentActiveEmotion = input;
  currentActiveEmotion.toLowerCase();

  if (input == "NORMAL") {
    emotionNormal();
    player.playEmotion("normal");
    return;
  } else if (input == "HAPPY") {
    emotionHappy();
    player.playEmotion("happy");
    return;
  } else if (input == "GLEE") {
    emotionGlee();
    player.playEmotion("glee");
    return;
  } else if (input == "SAD") {
    emotionSad();
    player.playEmotion("sad");
    return;
  } else if (input == "WORRIED") {
    emotionWorried();
    player.playEmotion("worried");
    return;
  } else if (input == "FOCUSED") {
    emotionFocused();
    player.playEmotion("focused");
    return;
  } else if (input == "ANNOYED") {
    emotionAnnoyed();
    player.playEmotion("annoyed");
    return;
  } else if (input == "SURPRISED") {
    emotionSurprised();
    player.playEmotion("surprised");
    return;
  } else if (input == "SKEPTIC") {
    emotionSkeptic();
    player.playEmotion("skeptic");
    return;
  } else if (input == "FRUSTRATED") {
    emotionFrustrated();
    player.playEmotion("frustrated");
    return;
  } else if (input == "UNIMPRESSED") {
    emotionUnimpressed();
    player.playEmotion("unimpressed");
    return;
  } else if (input == "SLEEPY") {
    emotionSleepy();
    player.playEmotion("sleepy");
    return;
  } else if (input == "SUSPICIOUS") {
    emotionSuspicious();
    player.playEmotion("suspicious");
    return;
  } else if (input == "SQUINT") {
    emotionSquint();
    player.playEmotion("squint");
    return;
  } else if (input == "ANGRY") {
    emotionAngry();
    player.playEmotion("angry");
    return;
  } else if (input == "FURIOUS") {
    emotionFurious();
    player.playEmotion("furious");
    return;
  } else if (input == "SCARED") {
    emotionScared();
    player.playEmotion("scared");
    return;
  } else if (input == "AWE") {
    emotionAwe();
    player.playEmotion("awe");
    return;
  } else if (input == "SIGH") {
    emotionWorried();
    player.playEmotion("sigh");
    return;
  } else if (input == "GASP") {
    emotionSurprised();
    player.playEmotion("gasp");
    return;
  } else if (input == "GIGGLE" || input == "CHUCKLE") {
    emotionHappy();
    player.playEmotion("giggle");
    return;
  } else if (input == "LAUGH" || input == "LAUGHTER") {
    emotionGlee();
    player.playEmotion("laughter");
    return;
  } else if (input == "GROAN") {
    emotionFrustrated();
    player.playEmotion("groan");
    return;
  } else if (input == "CLEAR_THROAT" || input == "THROAT") {
    emotionFocused();
    player.playEmotion("clear_throat");
    return;
  } else if (input == "CRY" || input == "SOB") {
    emotionSad();
    player.playEmotion("cry");
    return;
  } else if (input == "WHISPER") {
    emotionSuspicious();
    player.playEmotion("whisper");
    return;
  } else if (input == "SNIFF") {
    emotionFocused();
    player.playEmotion("sniff");
    return;
  } else if (input == "COUGH") {
    emotionAnnoyed();
    player.playEmotion("cough");
    return;
  } else if (input == "SNEEZE") {
    emotionSurprised();
    player.playEmotion("sneeze");
    return;
  } else if (input == "INHALE") {
    emotionFocused();
    player.playEmotion("inhale");
    return;
  } else if (input == "EXHALE") {
    emotionNormal();
    player.playEmotion("exhale");
    return;
  } else if (input == "THINKING" || input == "PROCESSING") {
    emotionFocused();
    player.playEmotion("thinking");
    return;
  } else if (input == "SUCCESS") {
    emotionGlee();
    player.playEmotion("success");
    return;
  } else if (input == "ERROR") {
    emotionSad();
    player.playEmotion("error");
    return;
  }


  // ==========================================================
  // MOTOR COMMANDS
  // ==========================================================

  if (input == "FORWARD") {
    moveForward();
  } else if (input == "BACKWARD") {
    moveBackward();
  } else if (input == "LEFT") {
    moveLeft();
  } else if (input == "RIGHT") {
    moveRight();
  } else if (input == "STOP") {
    stopMotors();
  } else if (input.startsWith("FORK:")) {
    // FORK:<0-45> moves the forklift to that angle (clamped)
    forkWrite(input.substring(5).toInt());
  } else if (input.startsWith("SPEED:")) {
    // Drive speed for subsequent moves; slower roaming keeps IKRU on the table
    motorSpeedPct = constrain(input.substring(6).toInt(), 30, 100);
    Serial.printf("Motor speed set to %d%%\n", motorSpeedPct);
  } else {
    Serial.print("Unknown Command: ");
    Serial.println(input);
  }
}

// ============================================================
// MOVE FORWARD
// ============================================================

void moveForward() {
  if (safetyBrakeEnabled && currentDistanceCm >= 3.0 && currentDistanceCm < obstacleThresholdCm) {
    Serial.printf("[SAFETY] Cannot move forward: obstacle detected at %.1f cm!\n", currentDistanceCm);
    stopMotors();
    String alert = "{\"event\":\"obstacle_blocked\",\"distance_cm\":" + String(currentDistanceCm, 1) + "}";
    webSocket.broadcastTXT(alert);
    emotionWorried();
    player.playEmotion("worried", 0.5);
    return;
  }

  isMovingForward = true;
  driveMotors(motorSpeedPct, motorSpeedPct);

  Serial.println("Moving Forward");
}

// ============================================================
// MOVE BACKWARD
// ============================================================

void moveBackward() {
  isMovingForward = false;
  driveMotors(-motorSpeedPct, -motorSpeedPct);

  Serial.println("Moving Backward");
}

// ============================================================
// MOVE LEFT
// ============================================================

void moveLeft() {
  isMovingForward = false;
  driveMotors(-motorSpeedPct, motorSpeedPct);

  Serial.println("Moving Left");
}

// ============================================================
// MOVE RIGHT
// ============================================================

void moveRight() {
  isMovingForward = false;
  driveMotors(motorSpeedPct, -motorSpeedPct);

  Serial.println("Moving Right");
}

// ============================================================
// STOP MOTORS
// ============================================================

void stopMotors() {
  isMovingForward = false;

  // Active brake (both inputs HIGH) stops faster than coasting — matters for the obstacle brake
  ledcWrite(MOTOR_IN1, 255);
  ledcWrite(MOTOR_IN2, 255);
  ledcWrite(MOTOR_IN3, 255);
  ledcWrite(MOTOR_IN4, 255);

  Serial.println("Stopped");
}

// ============================================================
// DRV8833 HELPERS
// ============================================================

// pct: -100 (full reverse) .. 100 (full forward)
void setMotor(uint8_t inA, uint8_t inB, int pct) {
  pct = constrain(pct, -100, 100);
  uint32_t duty = map(abs(pct), 0, 100, 0, 255);
  if (pct > 0)      { ledcWrite(inA, duty); ledcWrite(inB, 0); }
  else if (pct < 0) { ledcWrite(inA, 0);    ledcWrite(inB, duty); }
  else              { ledcWrite(inA, 0);    ledcWrite(inB, 0); }
}

void driveMotors(int leftPct, int rightPct) {
  setMotor(MOTOR_IN1, MOTOR_IN2, leftPct);
  setMotor(MOTOR_IN3, MOTOR_IN4, rightPct);
}

void forkWrite(int deg) {
  forkAngle = constrain(deg, FORK_MIN_DEG, FORK_MAX_DEG);
  uint32_t us = map(forkAngle, 0, 180, FORK_PULSE_MIN_US, FORK_PULSE_MAX_US);
  ledcWrite(FORK_PIN, (uint32_t)((uint64_t)us * ((1UL << FORK_PWM_BITS) - 1) / 20000));
  Serial.printf("Fork angle: %d\n", forkAngle);
}

// ULT/nFAULT goes LOW on over-current, over-temperature or VM under-voltage.
// Reports each new fault once to Serial and to the PC.
void checkMotorFault() {
  bool fault = digitalRead(MOTOR_FAULT) == LOW;
  if (fault && !motorFaultActive) {
    Serial.println("[MOTOR] DRV8833 fault (over-current / over-heat / low battery)");
    String alert = "{\"event\":\"motor_fault\"}";
    webSocket.broadcastTXT(alert);
  }
  motorFaultActive = fault;
}
