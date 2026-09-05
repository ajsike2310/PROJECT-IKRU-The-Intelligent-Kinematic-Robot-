#include "Face.h"
#include <HTTPClient.h>
#include <WebSocketsServer.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <Wire.h>
#include "ESP_I2S.h"

// ============================================================
// IKRU DESK COMPANION ROBOT
//
// Hardware:
// ESP32-WROOM-32
// DRV8833 Dual H-Bridge Motor Driver
// 2x DC Motor
// SSD1306 128x64 I2C OLED (driven via U8g2 through the Face library)
// MAX98357A I2S DAC Amplifier + Speaker
//
// Communication:
// WiFi + WebSocket
//
// OLED:
// IDLE     -> Animated eye expressions (Face library)
// SPEAKING -> Full screen large scrolling text (U8g2)
// ============================================================

// ============================================================
// WIFI (Connecting to GNXS-2.4G-C457E1 or IKRU-CAM Head Access Point)
// ============================================================

const char *primary_ssid = "GNXS-2.4G-C457E1";
const char *primary_pass = "1234567890";
const char *fallback_ssid = "IKRU-CAM";
const char *fallback_pass = "ikru@potato";

WebSocketsServer webSocket(81);

// ============================================================
// MOTOR PINS
// ============================================================

// Enable pins
#define EN1 13
#define EN2 33

// Left motor (remapped to GPIO 18 & 19 to avoid conflict with I2S audio on GPIO 26 & 27)
#define C1A 18
#define C1B 19

// Right motor
#define C2A 14
#define C2B 12

// ============================================================
// MAX98357A / I2S AUDIO
// ============================================================

I2SClass I2S;

#define I2S_WS 25
#define I2S_BCLK 26
#define I2S_DOUT 27

#define AUDIO_SAMPLE_RATE 44100
#define AUDIO_BUFFER_SIZE 16384

uint8_t audioBuffer[AUDIO_BUFFER_SIZE];
char pendingAudioURL[256] = "";
volatile bool hasAudioRequest = false;
volatile bool isAudioPlaying = false;
volatile bool stopAudioRequested = false;
TaskHandle_t audioTaskHandle = NULL;

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

  if (finalTextPosition < 0) {

    if (speechFinishedTime == 0) {
      speechFinishedTime = now;
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
// AUDIO STREAMING & PLAYBACK (I2S MAX98357A)
// ============================================================

static inline uint16_t readLE16(uint8_t *p) {
  return ((uint16_t)p[0]) | ((uint16_t)p[1] << 8);
}

static inline uint32_t readLE32(uint8_t *p) {
  return ((uint32_t)p[0]) | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
         ((uint32_t)p[3] << 24);
}

bool readExact(WiFiClient &stream, uint8_t *buffer, size_t length) {
  size_t received = 0;
  while (received < length && !stopAudioRequested) {
    if (stream.available()) {
      int n = stream.read(buffer + received, length - received);
      if (n > 0) received += n;
    } else {
      if (!stream.connected()) return false;
      vTaskDelay(pdMS_TO_TICKS(1));
    }
  }
  return (received == length);
}

bool skipBytes(WiFiClient &stream, uint32_t length) {
  uint8_t temp[64];
  while (length > 0 && !stopAudioRequested) {
    size_t amount = min(length, (uint32_t)sizeof(temp));
    if (!readExact(stream, temp, amount)) return false;
    length -= amount;
  }
  return (length == 0);
}

bool findWavData(WiFiClient &stream, uint32_t &dataSize) {
  uint8_t header[12];
  if (!readExact(stream, header, 12)) {
    Serial.println("[Audio] Cannot read WAV header");
    return false;
  }

  if (memcmp(header, "RIFF", 4) != 0 || memcmp(header + 8, "WAVE", 4) != 0) {
    Serial.println("[Audio] Invalid WAV header (not RIFF/WAVE)");
    return false;
  }

  bool foundFmt = false;
  while (stream.connected() && !stopAudioRequested) {
    uint8_t chunkHeader[8];
    if (!readExact(stream, chunkHeader, 8)) return false;

    uint32_t chunkSize = readLE32(chunkHeader + 4);

    if (memcmp(chunkHeader, "fmt ", 4) == 0) {
      uint8_t fmt[16];
      if (!readExact(stream, fmt, 16)) return false;

      uint16_t format     = readLE16(fmt);
      uint16_t channels   = readLE16(fmt + 2);
      uint32_t sampleRate = readLE32(fmt + 4);
      uint16_t bits       = readLE16(fmt + 14);

      if (format != 1 || channels != 2 || sampleRate != 44100 || bits != 16) {
        Serial.printf("[Audio] Unsupported format: fmt=%u, ch=%u, rate=%lu, bits=%u\n",
                      format, channels, sampleRate, bits);
        return false;
      }

      if (chunkSize > 16) {
        if (!skipBytes(stream, chunkSize - 16)) return false;
      }
      foundFmt = true;

    } else if (memcmp(chunkHeader, "data", 4) == 0) {
      dataSize = chunkSize;
      return foundFmt;

    } else {
      if (!skipBytes(stream, chunkSize)) return false;
    }
  }

  return false;
}

void audioPlaybackTask(void *pvParameters) {
  while (true) {
    if (hasAudioRequest) {
      hasAudioRequest = false;
      isAudioPlaying = true;
      stopAudioRequested = false;

      String url = String(pendingAudioURL);
      Serial.print("[Audio] Connecting to: ");
      Serial.println(url);

      HTTPClient http;
      http.begin(url);
      int httpCode = http.GET();

      if (httpCode == HTTP_CODE_OK) {
        WiFiClient *stream = http.getStreamPtr();
        uint32_t dataSize = 0;

        if (findWavData(*stream, dataSize)) {
          Serial.printf("[Audio] Streaming %lu bytes to I2S...\n", dataSize);
          uint32_t remaining = dataSize;

          while (remaining > 0 && stream->connected() && !stopAudioRequested) {
            size_t toRead = min((uint32_t)AUDIO_BUFFER_SIZE, remaining);
            toRead -= toRead % 4; // 16-bit stereo frame boundary

            size_t bytesRead = 0;
            while (bytesRead < toRead && !stopAudioRequested) {
              if (stream->available()) {
                int n = stream->read(audioBuffer + bytesRead, toRead - bytesRead);
                if (n > 0) bytesRead += n;
              } else {
                if (!stream->connected()) break;
                vTaskDelay(pdMS_TO_TICKS(1));
              }
            }

            if (bytesRead == 0) break;
            I2S.write(audioBuffer, bytesRead);
            remaining -= bytesRead;
          }
          Serial.println("[Audio] Finished playback");
        } else {
          Serial.println("[Audio] WAV parsing failed");
        }
      } else {
        Serial.printf("[Audio] HTTP GET failed: %d\n", httpCode);
      }

      http.end();
      isAudioPlaying = false;
      stopAudioRequested = false;
    }

    vTaskDelay(pdMS_TO_TICKS(20));
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
  // I2S AUDIO (MAX98357A)
  // ============================================================
  Serial.println("Starting I2S Audio...");
  I2S.setPins(I2S_BCLK, I2S_WS, I2S_DOUT);
  if (!I2S.begin(I2S_MODE_STD, AUDIO_SAMPLE_RATE, I2S_DATA_BIT_WIDTH_16BIT,
                 I2S_SLOT_MODE_STEREO)) {
    Serial.println("[Audio] I2S initialization FAILED!");
  } else {
    Serial.println("[Audio] I2S ready");
  }

  // Pin audio playback task to Core 0 (leaving Core 1 for OLED & WebSocket loops)
  xTaskCreatePinnedToCore(audioPlaybackTask, "audioTask", 10240, NULL, 1,
                          &audioTaskHandle, 0);

  // WiFi
  showConnecting();

  Serial.println("Connecting to WiFi...");

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(true);

  WiFi.begin(primary_ssid, primary_pass);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 25) {
    delay(500);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\nTrying fallback AP (IKRU-CAM)...");
    WiFi.begin(fallback_ssid, fallback_pass);
    while (WiFi.status() != WL_CONNECTED) {
      delay(500);
      Serial.print(".");
    }
  }

  WiFi.setSleep(false);

  Serial.println();
  Serial.println("Connected!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());

  showWiFiConnected();

  // WebSocket
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);

  Serial.println("WebSocket Server Started");

  // Initial emotion
  oledMode = OLED_IDLE;
  face->Expression.GoTo_Normal();
  animationLastMillis = millis();
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {

  // WebSocket
  webSocket.loop();

  // Update speech scroll (returns early if not in speaking mode)
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
  // (speaking, waiting between segments, or during open/close animation)
  if (speechBoxWidth > 0) {
    drawSpeakingText();
  }

  // Draw eyes (handles blinking, random looks, etc.)
  face->Update();

  // Render to OLED
  u8g2.sendBuffer();
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
    oledMessage("Connected!");
    break;

    // DISCONNECTED
  case WStype_DISCONNECTED:
    Serial.println("Client Disconnected");
    stopMotors();
    oledMessage("Disconnected");
    break;

    // TEXT
  case WStype_TEXT: {
    String cmd = String((char *)payload);
    cmd.trim();
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
  // DISPLAY COMMAND
  //
  // DISPLAY:Hello there!
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
  // AUDIO COMMANDS (Case-sensitive URLs)
  // ==========================================================

  if (input.startsWith("SPEAK_URL:") || input.startsWith("AUDIO:")) {
    int idx = input.indexOf(':');
    String url = input.substring(idx + 1);
    url.trim();
    strncpy(pendingAudioURL, url.c_str(), sizeof(pendingAudioURL) - 1);
    pendingAudioURL[sizeof(pendingAudioURL) - 1] = '\0';
    hasAudioRequest = true;
    return;
  }

  if (input == "STOP_AUDIO") {
    stopAudioRequested = true;
    return;
  }

  // Convert to uppercase for all other commands
  input.toUpperCase();

  // ==========================================================
  // EMOTION COMMANDS
  // ==========================================================

  if (input == "NORMAL") {
    emotionNormal();
    return;
  } else if (input == "HAPPY") {
    emotionHappy();
    return;
  } else if (input == "GLEE") {
    emotionGlee();
    return;
  } else if (input == "SAD") {
    emotionSad();
    return;
  } else if (input == "WORRIED") {
    emotionWorried();
    return;
  } else if (input == "FOCUSED") {
    emotionFocused();
    return;
  } else if (input == "ANNOYED") {
    emotionAnnoyed();
    return;
  } else if (input == "SURPRISED") {
    emotionSurprised();
    return;
  } else if (input == "SKEPTIC") {
    emotionSkeptic();
    return;
  } else if (input == "FRUSTRATED") {
    emotionFrustrated();
    return;
  } else if (input == "UNIMPRESSED") {
    emotionUnimpressed();
    return;
  } else if (input == "SLEEPY") {
    emotionSleepy();
    return;
  } else if (input == "SUSPICIOUS") {
    emotionSuspicious();
    return;
  } else if (input == "SQUINT") {
    emotionSquint();
    return;
  } else if (input == "ANGRY") {
    emotionAngry();
    return;
  } else if (input == "FURIOUS") {
    emotionFurious();
    return;
  } else if (input == "SCARED") {
    emotionScared();
    return;
  } else if (input == "AWE") {
    emotionAwe();
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

  digitalWrite(EN1, LOW);
  digitalWrite(EN2, LOW);
  digitalWrite(C1A, LOW);
  digitalWrite(C1B, LOW);
  digitalWrite(C2A, LOW);
  digitalWrite(C2B, LOW);

  Serial.println("Stopped");
}