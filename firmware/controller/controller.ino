#include "Face.h"
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WebSocketsServer.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <Wire.h>

Preferences preferences;
WebServer setupServer(80);

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

WebSocketsServer webSocket(81);

// ============================================================
// MOTOR PINS
// ============================================================

// Enable pins
#define EN1 13
#define EN2 33

// Left motor (GPIO 26 & 27)
#define C1A 26
#define C1B 27

// Right motor
#define C2A 14
#define C2B 12

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

void stopMotors();
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

void showConnecting();

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

  // Show startup banner via U8g2
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_ncenB14_tr);
  u8g2.drawStr(30, 20, "IKRU");
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr(22, 36, "The Desk Robot");
  u8g2.drawStr(30, 50, "Powered by");
  u8g2.setFont(u8g2_font_ncenB14_tr);
  u8g2.drawStr(10, 64, "POTATOES");
  u8g2.sendBuffer();

  delay(1500);
}

// ============================================================
// CONNECTING SCREEN
// ============================================================

void showConnecting() {

  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr(0, 20, "Connecting to WiFi...");
  u8g2.drawStr(0, 38, "Please wait");
  u8g2.sendBuffer();
}

// ============================================================
// WIFI CONNECTED SCREEN
// ============================================================

void showWiFiConnected() {

  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_6x10_tr);
  u8g2.drawStr(0, 14, "WiFi Connected");
  u8g2.drawStr(0, 30, WiFi.localIP().toString().c_str());
  u8g2.sendBuffer();

  delay(500);
}

// ============================================================
// DYNAMIC WIFI CONFIGURATION (NVS + RECONNECT)
// ============================================================

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
  WiFi.begin(new_ssid.c_str(), new_pass.c_str());

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 25) {
    delay(500);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.println("Connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());

    // Save to NVS
    preferences.begin("ikru_wifi", false);
    preferences.putString("ssid", new_ssid);
    preferences.putString("pass", new_pass);
    preferences.end();
    Serial.println("[WiFi] Saved credentials to flash memory (NVS).");

    showWiFiConnected();
  } else {
    Serial.println();
    Serial.println("WiFi connect failed! Reverting to fallback...");
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 20, "WiFi Connect Failed!");
    u8g2.drawStr(0, 38, "Reverting to fallback");
    u8g2.sendBuffer();
    delay(1500);

    WiFi.begin(fallback_ssid, fallback_pass);
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }
    showWiFiConnected();
  }
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
// WIFI SETUP WEB PORTAL (Dynamic NVS Configuration)
// ============================================================

void handlePortalRoot() {
  int n = WiFi.scanNetworks();
  String options = "";
  for (int i = 0; i < n; ++i) {
    String ssid = WiFi.SSID(i);
    int32_t rssi = WiFi.RSSI(i);
    options += "<option value='" + ssid + "'>" + ssid + " (" + String(rssi) + " dBm)</option>";
  }
  if (n == 0) {
    options = "<option value=''>No networks found</option>";
  }

  String html = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1'>"
                "<style>body{font-family:sans-serif;padding:20px;background:#121212;color:#fff;max-width:400px;margin:auto;}"
                "select,input,button{width:100%;padding:12px;margin:8px 0;box-sizing:border-box;border-radius:6px;border:1px solid #444;background:#222;color:#fff;font-size:15px;}"
                "button{background:#007acc;font-weight:bold;border:none;cursor:pointer;}"
                ".card{background:#1e1e1e;padding:20px;border-radius:10px;box-shadow:0 4px 10px rgba(0,0,0,0.5);}</style></head><body>"
                "<div class='card'><h2>IKRU Wi-Fi Setup</h2>"
                "<form action='/save' method='POST'>"
                "<label>Select Wi-Fi Network:</label>"
                "<select name='ssid_select' onchange='if(this.value) document.getElementById(\"ssid_manual\").value=this.value;'>"
                "<option value=''>-- Select Network --</option>" + options + "</select>"
                "<label>Or Type SSID:</label>"
                "<input type='text' id='ssid_manual' name='ssid' placeholder='Network SSID' required>"
                "<label>Password:</label>"
                "<input type='password' name='pass' placeholder='Wi-Fi Password'>"
                "<button type='submit'>Save & Connect</button></form>"
                "<br><a href='/' style='color:#007acc;text-decoration:none;'>Rescan Networks</a></div></body></html>";
  setupServer.send(200, "text/html", html);
}

void handlePortalSave() {
  if (setupServer.hasArg("ssid")) {
    String s = setupServer.arg("ssid");
    String p = setupServer.arg("pass");
    preferences.begin("ikru_wifi", false);
    preferences.putString("ssid", s);
    preferences.putString("pass", p);
    preferences.end();
    setupServer.send(200, "text/html", "<html><body style='background:#121212;color:#fff;font-family:sans-serif;padding:20px;'><h3>Wi-Fi Credentials Saved!</h3><p>Restarting ESP32 and connecting...</p></body></html>");
    delay(1000);
    ESP.restart();
  } else {
    setupServer.send(400, "text/plain", "Missing SSID");
  }
}

void handlePortalReset() {
  preferences.begin("ikru_wifi", false);
  preferences.clear();
  preferences.end();
  setupServer.send(200, "text/html", "<html><body><h3>Saved Wi-Fi Cleared! Restarting...</h3></body></html>");
  delay(1000);
  ESP.restart();
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

  // Motor pins
  pinMode(EN1, OUTPUT);
  pinMode(EN2, OUTPUT);
  pinMode(C1A, OUTPUT);
  pinMode(C1B, OUTPUT);
  pinMode(C2A, OUTPUT);
  pinMode(C2B, OUTPUT);

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

  // WiFi
  showConnecting();

  Serial.println("Connecting to WiFi...");

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  // Load saved Wi-Fi from NVS Flash
  preferences.begin("ikru_wifi", true);
  String saved_ssid = preferences.getString("ssid", "");
  String saved_pass = preferences.getString("pass", "");
  preferences.end();

  if (saved_ssid.length() > 0) {
    Serial.print("[WiFi] Connecting using saved NVS credentials: ");
    Serial.println(saved_ssid);
    WiFi.begin(saved_ssid.c_str(), saved_pass.c_str());

    int retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 25) {
      delay(500);
      Serial.print(".");
      retries++;
    }
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nTrying fallback AP (IKRU-CAM)...");
    WiFi.begin(fallback_ssid, fallback_pass);
    int retries = 0;
    while (WiFi.status() != WL_CONNECTED && retries < 15) {
      delay(500);
      Serial.print(".");
      retries++;
    }
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n[WiFi] Could not connect to any network. Starting Setup Portal: IKRU-SETUP");
    WiFi.disconnect();
    WiFi.mode(WIFI_AP);
    WiFi.softAP("IKRU-SETUP", "12345678");
    Serial.print("[WiFi] AP IP address: ");
    Serial.println(WiFi.softAPIP());

    setupServer.on("/", HTTP_GET, handlePortalRoot);
    setupServer.on("/save", HTTP_POST, handlePortalSave);
    setupServer.on("/reset", HTTP_GET, handlePortalReset);
    setupServer.begin();

    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_6x10_tr);
    u8g2.drawStr(0, 14, "AP: IKRU-SETUP");
    u8g2.drawStr(0, 30, "Pass: 12345678");
    u8g2.drawStr(0, 48, "IP: 192.168.4.1");
    u8g2.sendBuffer();
    delay(1500);
  } else {
    Serial.println();
    Serial.println("Connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());

    if (MDNS.begin("ikru-robot")) {
      MDNS.addService("ws", "tcp", 81);
      MDNS.addService("http", "tcp", 80);
      Serial.println("[mDNS] Responder active: ikru-robot.local");
    }

    showWiFiConnected();
  }

  // WebSocket
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);

  Serial.println("WebSocket Server Started");

  // Initial emotion
  oledMode = OLED_IDLE;
  face->Expression.GoTo_Normal();
  animationLastMillis = millis();

  // Friendly startup chirp once fully ready and connected
  player.playEmotion("success", 0.6);
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    setupServer.handleClient();
  }

  // WebSocket
  webSocket.loop();

  // Ultrasonic distance measurement & obstacle safety brake
  updateUltrasonic();

  // Non-blocking R2-D2 glissando audio sequencer
  player.update();

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

  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, HIGH);
  digitalWrite(C1B, LOW);
  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, HIGH);
  digitalWrite(C2B, LOW);

  Serial.println("Moving Forward");
}

// ============================================================
// MOVE BACKWARD
// ============================================================

void moveBackward() {
  isMovingForward = false;

  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, LOW);
  digitalWrite(C1B, HIGH);
  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, LOW);
  digitalWrite(C2B, HIGH);

  Serial.println("Moving Backward");
}

// ============================================================
// MOVE LEFT
// ============================================================

void moveLeft() {
  isMovingForward = false;

  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, LOW);
  digitalWrite(C1B, HIGH);
  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, HIGH);
  digitalWrite(C2B, LOW);

  Serial.println("Moving Left");
}

// ============================================================
// MOVE RIGHT
// ============================================================

void moveRight() {
  isMovingForward = false;

  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, HIGH);
  digitalWrite(C1B, LOW);
  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, LOW);
  digitalWrite(C2B, HIGH);

  Serial.println("Moving Right");
}

// ============================================================
// STOP MOTORS
// ============================================================

void stopMotors() {
  isMovingForward = false;

  digitalWrite(EN1, LOW);
  digitalWrite(EN2, LOW);
  digitalWrite(C1A, LOW);
  digitalWrite(C1B, LOW);
  digitalWrite(C2A, LOW);
  digitalWrite(C2B, LOW);

  Serial.println("Stopped");
}