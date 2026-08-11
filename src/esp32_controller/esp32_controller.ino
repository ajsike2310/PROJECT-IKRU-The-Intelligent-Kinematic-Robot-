#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WebSocketsServer.h>
#include <WiFi.h>
#include <Wire.h>

// ============================================================
// IKRU DESK COMPANION ROBOT
//
// Hardware:
// ESP32-WROOM-32
// L293D Motor Driver
// 2x DC Motor
// SSD1306 128x64 I2C OLED
//
// Communication:
// WiFi + WebSocket
//
// OLED:
// IDLE      -> Emotional animated eyes
// SPEAKING  -> Full screen large scrolling text
// ============================================================

// ============================================================
// WIFI
// ============================================================

const char *ssid = "AJx24";
const char *password = "avin1236";

WebSocketsServer webSocket(81);

// ============================================================
// OLED
// ============================================================

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

#define OLED_RESET -1
#define OLED_ADDRESS 0x3C

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

// ============================================================
// MOTOR PINS
// ============================================================

// Enable pins
#define EN1 13
#define EN2 33

// Left motor
#define C1A 26
#define C1B 27

// Right motor
#define C2A 14
#define C2B 12

// ============================================================
// OLED MODES
// ============================================================

enum OLEDMode {

  OLED_IDLE,

  OLED_SPEAKING

};

OLEDMode oledMode = OLED_IDLE;

// ============================================================
// EMOTIONS
// ============================================================

enum Emotion {

  EMOTION_IDLE,

  EMOTION_HAPPY,

  EMOTION_EXCITED,

  EMOTION_ANGRY,

  EMOTION_SAD,

  EMOTION_SURPRISED,

  EMOTION_THINKING,

  EMOTION_SLEEPY,

  EMOTION_WORRIED

};

// Current emotion
Emotion currentEmotion = EMOTION_HAPPY;

// ============================================================
// TEXT STORAGE
// ============================================================

#define MAX_MESSAGE_LINES 40

String messageLines[MAX_MESSAGE_LINES];

int messageLineCount = 0;

// ============================================================
// SPEECH FONT
// ============================================================

const uint8_t SPEECH_TEXT_SIZE = 2;

const int SPEECH_LINE_HEIGHT = 16;

// ============================================================
// SPEECH SCROLLING
// ============================================================

int scrollY = SCREEN_HEIGHT;

// Larger = slower
const unsigned long SCROLL_SPEED = 120;

// Pause before scrolling
const unsigned long START_PAUSE = 1000;

// Pause after message finishes
const unsigned long END_PAUSE = 800;

unsigned long lastScrollUpdate = 0;

unsigned long speechStartTime = 0;

unsigned long speechFinishedTime = 0;

// ============================================================
// BLINK SETTINGS
// ============================================================

bool blinking = false;

unsigned long lastBlink = 0;

unsigned long blinkStart = 0;

// Blink every 4 seconds
const unsigned long BLINK_INTERVAL = 4000;

// Blink duration
const unsigned long BLINK_DURATION = 180;

// ============================================================
// THINKING ANIMATION
// ============================================================

unsigned long lastThinkingMove = 0;

int thinkingDirection = 0;

const unsigned long THINKING_MOVE_INTERVAL = 900;

// ============================================================
// FUNCTION DECLARATIONS
// ============================================================

void oledStartup();

void showConnecting();

void showWiFiConnected();

void oledMessage(String text);

void prepareMessage(String text);

void updateOLED();

void drawEyes();

void drawHappyEyes();

void drawIdleEyes();

void drawExcitedEyes();

void drawAngryEyes();

void drawSadEyes();

void drawSurprisedEyes();

void drawThinkingEyes();

void drawSleepyEyes();

void drawWorriedEyes();

void updateBlink();

void updateThinkingAnimation();

void updateSpeechScroll();

void drawSpeakingText();

void idle();

void happy();

void excited();

void angry();

void sad();

void surprised();

void thinking();

void sleepy();

void worried();

void parseCommand(String input);

void moveForward();

void moveBackward();

void moveLeft();

void moveRight();

void stopMotors();

void webSocketEvent(uint8_t client, WStype_t type, uint8_t *payload,
                    size_t length);

// ============================================================
// DRAW IKRU'S EYES
// ============================================================

void drawEyes() {

  // Do not show eyes while speaking
  if (oledMode != OLED_IDLE) {

    return;
  }

  switch (currentEmotion) {

  case EMOTION_IDLE:

    drawIdleEyes();

    break;

  case EMOTION_HAPPY:

    drawHappyEyes();

    break;

  case EMOTION_EXCITED:

    drawExcitedEyes();

    break;

  case EMOTION_ANGRY:

    drawAngryEyes();

    break;

  case EMOTION_SAD:

    drawSadEyes();

    break;

  case EMOTION_SURPRISED:

    drawSurprisedEyes();

    break;

  case EMOTION_THINKING:

    drawThinkingEyes();

    break;

  case EMOTION_SLEEPY:

    drawSleepyEyes();

    break;

  case EMOTION_WORRIED:

    drawWorriedEyes();

    break;
  }
}

// ============================================================
// IDLE EYES
//
// Friendly normal expression
// ============================================================

void drawIdleEyes() {

  if (blinking) {

    display.fillRoundRect(21, 29, 28, 6, 3, SSD1306_WHITE);

    display.fillRoundRect(79, 29, 28, 6, 3, SSD1306_WHITE);

    return;
  }

  display.fillRoundRect(20, 16, 30, 27, 9, SSD1306_WHITE);

  display.fillRoundRect(78, 16, 30, 27, 9, SSD1306_WHITE);

  display.fillCircle(35, 29, 6, SSD1306_BLACK);

  display.fillCircle(93, 29, 6, SSD1306_BLACK);

  // Small highlights

  display.fillCircle(33, 27, 2, SSD1306_WHITE);

  display.fillCircle(91, 27, 2, SSD1306_WHITE);
}

// ============================================================
// HAPPY EYES
// ============================================================

void drawHappyEyes() {

  if (blinking) {

    display.fillRoundRect(21, 29, 28, 5, 2, SSD1306_WHITE);

    display.fillRoundRect(79, 29, 28, 5, 2, SSD1306_WHITE);

    return;
  }

  display.fillRoundRect(20, 17, 30, 27, 10, SSD1306_WHITE);

  display.fillRoundRect(78, 17, 30, 27, 10, SSD1306_WHITE);

  // Cut lower section

  display.fillRect(20, 34, 30, 14, SSD1306_BLACK);

  display.fillRect(78, 34, 30, 14, SSD1306_BLACK);

  // Rounded happy tips

  display.fillCircle(29, 33, 8, SSD1306_WHITE);

  display.fillCircle(41, 33, 8, SSD1306_WHITE);

  display.fillCircle(87, 33, 8, SSD1306_WHITE);

  display.fillCircle(99, 33, 8, SSD1306_WHITE);

  display.fillRect(29, 25, 12, 8, SSD1306_WHITE);

  display.fillRect(87, 25, 12, 8, SSD1306_WHITE);
}

// ============================================================
// EXCITED EYES
// ============================================================

void drawExcitedEyes() {

  if (blinking) {

    display.fillRoundRect(18, 29, 34, 6, 3, SSD1306_WHITE);

    display.fillRoundRect(76, 29, 34, 6, 3, SSD1306_WHITE);

    return;
  }

  display.fillRoundRect(17, 12, 36, 34, 11, SSD1306_WHITE);

  display.fillRoundRect(75, 12, 36, 34, 11, SSD1306_WHITE);

  display.fillCircle(35, 29, 8, SSD1306_BLACK);

  display.fillCircle(93, 29, 8, SSD1306_BLACK);

  display.fillCircle(32, 26, 3, SSD1306_WHITE);

  display.fillCircle(90, 26, 3, SSD1306_WHITE);
}

// ============================================================
// ANGRY EYES
//
// Strong inward slant
// ============================================================

void drawAngryEyes() {

  if (blinking) {

    display.fillRoundRect(21, 30, 28, 5, 2, SSD1306_WHITE);

    display.fillRoundRect(79, 30, 28, 5, 2, SSD1306_WHITE);

    return;
  }

  // Left eye

  display.fillRoundRect(20, 18, 30, 27, 8, SSD1306_WHITE);

  // Right eye

  display.fillRoundRect(78, 18, 30, 27, 8, SSD1306_WHITE);

  // Angry upper eyelids

  display.fillTriangle(18, 14, 50, 23, 50, 30, SSD1306_BLACK);

  display.fillTriangle(110, 14, 78, 23, 78, 30, SSD1306_BLACK);

  // Lower eye areas

  display.fillRoundRect(24, 29, 22, 11, 5, SSD1306_WHITE);

  display.fillRoundRect(82, 29, 22, 11, 5, SSD1306_WHITE);

  // Pupils

  display.fillCircle(35, 34, 5, SSD1306_BLACK);

  display.fillCircle(93, 34, 5, SSD1306_BLACK);
}

// ============================================================
// SAD / BAGGY EYES
//
// Pixel bitmap based eyes.
//
// The shape is intentionally:
//
// Tall
// Puffy
// Drooping
// Rounded at the bottom
//
// This is based on the reference image you provided.
// ============================================================

// ------------------------------------------------------------
// LEFT SAD EYE BITMAP
//
// 32 pixels wide
// 40 pixels high
// ------------------------------------------------------------

const uint8_t sadLeftBitmap[] PROGMEM = {

    0x00, 0x00, 0x1C, 0x00, 0x00, 0x00, 0x1E, 0x00, 0x00, 0x00, 0x1F, 0x00,
    0x00, 0x00, 0x7F, 0x00, 0x00, 0x00, 0xFF, 0x80, 0x00, 0x01, 0xFF, 0xC0,
    0x00, 0x03, 0xFF, 0xC0, 0x00, 0x07, 0xFF, 0xC0, 0x00, 0x0F, 0xFF, 0xE0,
    0x00, 0x1F, 0xFF, 0xE0, 0x00, 0x3F, 0xFF, 0xE0, 0x00, 0x7F, 0xFF, 0xF0,
    0x00, 0xFF, 0xFF, 0xF8, 0x00, 0xFF, 0xFF, 0xF8, 0x00, 0xFF, 0xFF, 0xF8,
    0x00, 0xFF, 0xFF, 0xF8, 0x00, 0xFF, 0xFF, 0xF8, 0x00, 0xFF, 0xFF, 0xF8,
    0x00, 0xFF, 0xFF, 0xF8, 0x00, 0xFF, 0xFF, 0xF8, 0x00, 0xFF, 0xFF, 0xF8,
    0x00, 0xFF, 0xFF, 0xF8, 0x00, 0x7F, 0xFF, 0xF0, 0x00, 0x7F, 0xFF, 0xF0,
    0x00, 0x3F, 0xFF, 0xE0, 0x00, 0x3F, 0xFF, 0xE0, 0x00, 0x1F, 0xFF, 0xC0,
    0x00, 0x1F, 0xFF, 0xC0, 0x00, 0x0F, 0xFF, 0x80, 0x00, 0x0F, 0xFF, 0x80,
    0x00, 0x07, 0xFF, 0x00, 0x00, 0x07, 0xFF, 0x00, 0x00, 0x03, 0xFE, 0x00,
    0x00, 0x03, 0xFE, 0x00, 0x00, 0x01, 0xFC, 0x00, 0x00, 0x01, 0xFC, 0x00,
    0x00, 0x00, 0xF8, 0x00, 0x00, 0x00, 0x7C, 0x00, 0x00, 0x00, 0x3E, 0x00,
    0x00, 0x00, 0x1C, 0x00};

// ------------------------------------------------------------
// RIGHT SAD EYE BITMAP
//
// Mirrored version of the left eye.
// ------------------------------------------------------------

const uint8_t sadRightBitmap[] PROGMEM = {

    0x00, 0x38, 0x00, 0x00, 0x00, 0x78, 0x00, 0x00, 0x00, 0xF8, 0x00, 0x00,
    0x00, 0xFE, 0x00, 0x00, 0x01, 0xFF, 0x00, 0x00, 0x03, 0xFF, 0x80, 0x00,
    0x03, 0xFF, 0xC0, 0x00, 0x03, 0xFF, 0xE0, 0x00, 0x07, 0xFF, 0xF0, 0x00,
    0x07, 0xFF, 0xF8, 0x00, 0x07, 0xFF, 0xFC, 0x00, 0x0F, 0xFF, 0xFE, 0x00,
    0x1F, 0xFF, 0xFF, 0x00, 0x1F, 0xFF, 0xFF, 0x00, 0x1F, 0xFF, 0xFF, 0x00,
    0x1F, 0xFF, 0xFF, 0x00, 0x1F, 0xFF, 0xFF, 0x00, 0x1F, 0xFF, 0xFF, 0x00,
    0x1F, 0xFF, 0xFF, 0x00, 0x1F, 0xFF, 0xFF, 0x00, 0x1F, 0xFF, 0xFF, 0x00,
    0x1F, 0xFF, 0xFF, 0x00, 0x0F, 0xFF, 0xFE, 0x00, 0x0F, 0xFF, 0xFE, 0x00,
    0x07, 0xFF, 0xFC, 0x00, 0x07, 0xFF, 0xFC, 0x00, 0x03, 0xFF, 0xF8, 0x00,
    0x03, 0xFF, 0xF8, 0x00, 0x01, 0xFF, 0xF0, 0x00, 0x01, 0xFF, 0xF0, 0x00,
    0x00, 0xFF, 0xE0, 0x00, 0x00, 0xFF, 0xE0, 0x00, 0x00, 0x7F, 0xC0, 0x00,
    0x00, 0x7F, 0xC0, 0x00, 0x00, 0x3F, 0x80, 0x00, 0x00, 0x3F, 0x80, 0x00,
    0x00, 0x1F, 0x00, 0x00, 0x00, 0x3E, 0x00, 0x00, 0x00, 0x7C, 0x00, 0x00,
    0x00, 0x38, 0x00, 0x00};

// ============================================================
// DRAW SAD EYES
// ============================================================

void drawSadEyes() {

  // ----------------------------------------------------------
  // Blink
  // ----------------------------------------------------------

  if (blinking) {

    display.fillRoundRect(20, 31, 30, 5, 2, SSD1306_WHITE);

    display.fillRoundRect(78, 31, 30, 5, 2, SSD1306_WHITE);

    return;
  }

  // ----------------------------------------------------------
  // LEFT BAGGY EYE
  // ----------------------------------------------------------

  display.drawBitmap(18, 12, sadLeftBitmap, 32, 40, SSD1306_WHITE);

  // ----------------------------------------------------------
  // RIGHT BAGGY EYE
  // ----------------------------------------------------------

  display.drawBitmap(78, 12, sadRightBitmap, 32, 40, SSD1306_WHITE);

  // ----------------------------------------------------------
  // LEFT PUPIL
  //
  // Narrow vertical pupil like the reference.
  // ----------------------------------------------------------

  display.fillRoundRect(31, 27, 5, 12, 2, SSD1306_BLACK);

  // ----------------------------------------------------------
  // RIGHT PUPIL
  // ----------------------------------------------------------

  display.fillRoundRect(91, 27, 5, 12, 2, SSD1306_BLACK);
}

// ============================================================
// SURPRISED EYES
// ============================================================

void drawSurprisedEyes() {

  if (blinking) {

    display.fillRoundRect(20, 30, 30, 5, 2, SSD1306_WHITE);

    display.fillRoundRect(78, 30, 30, 5, 2, SSD1306_WHITE);

    return;
  }

  display.fillCircle(35, 28, 16, SSD1306_WHITE);

  display.fillCircle(93, 28, 16, SSD1306_WHITE);

  display.fillCircle(35, 29, 7, SSD1306_BLACK);

  display.fillCircle(93, 29, 7, SSD1306_BLACK);

  display.fillCircle(32, 26, 2, SSD1306_WHITE);

  display.fillCircle(90, 26, 2, SSD1306_WHITE);
}

// ============================================================
// THINKING EYES
// ============================================================

void drawThinkingEyes() {

  if (blinking) {

    display.fillRoundRect(21, 30, 28, 5, 2, SSD1306_WHITE);

    display.fillRoundRect(79, 30, 28, 5, 2, SSD1306_WHITE);

    return;
  }

  display.fillRoundRect(20, 16, 30, 27, 9, SSD1306_WHITE);

  display.fillRoundRect(78, 16, 30, 27, 9, SSD1306_WHITE);

  int pupilOffsetX = 0;

  if (thinkingDirection == 1) {

    pupilOffsetX = 5;

  }

  else if (thinkingDirection == -1) {

    pupilOffsetX = -5;
  }

  display.fillCircle(35 + pupilOffsetX, 23, 5, SSD1306_BLACK);

  display.fillCircle(93 + pupilOffsetX, 23, 5, SSD1306_BLACK);

  display.fillCircle(33 + pupilOffsetX, 21, 2, SSD1306_WHITE);

  display.fillCircle(91 + pupilOffsetX, 21, 2, SSD1306_WHITE);
}

// ============================================================
// SLEEPY EYES
// ============================================================

void drawSleepyEyes() {

  if (blinking) {

    display.fillRoundRect(20, 31, 30, 5, 2, SSD1306_WHITE);

    display.fillRoundRect(78, 31, 30, 5, 2, SSD1306_WHITE);

    return;
  }

  // Left eye

  display.fillRoundRect(20, 21, 30, 19, 8, SSD1306_WHITE);

  // Heavy eyelid

  display.fillRoundRect(20, 21, 30, 10, 7, SSD1306_BLACK);

  // Lower visible eye

  display.fillRoundRect(25, 29, 20, 8, 4, SSD1306_WHITE);

  // Right eye

  display.fillRoundRect(78, 21, 30, 19, 8, SSD1306_WHITE);

  // Heavy eyelid

  display.fillRoundRect(78, 21, 30, 10, 7, SSD1306_BLACK);

  // Lower visible eye

  display.fillRoundRect(83, 29, 20, 8, 4, SSD1306_WHITE);

  // Small pupils

  display.fillCircle(35, 35, 3, SSD1306_BLACK);

  display.fillCircle(93, 35, 3, SSD1306_BLACK);
}

// ============================================================
// WORRIED EYES
// ============================================================

void drawWorriedEyes() {

  if (blinking) {

    display.fillRoundRect(20, 31, 30, 5, 2, SSD1306_WHITE);

    display.fillRoundRect(78, 31, 30, 5, 2, SSD1306_WHITE);

    return;
  }

  // Left eye

  display.fillRoundRect(20, 17, 30, 28, 9, SSD1306_WHITE);

  // Worried upper eyelid

  display.fillTriangle(20, 17, 50, 17, 50, 27, SSD1306_BLACK);

  // Lower visible eye

  display.fillRoundRect(25, 27, 20, 14, 6, SSD1306_WHITE);

  // Right eye

  display.fillRoundRect(78, 17, 30, 28, 9, SSD1306_WHITE);

  // Worried upper eyelid

  display.fillTriangle(108, 17, 78, 17, 78, 27, SSD1306_BLACK);

  // Lower visible eye

  display.fillRoundRect(83, 27, 20, 14, 6, SSD1306_WHITE);

  // Pupils

  display.fillCircle(35, 33, 5, SSD1306_BLACK);

  display.fillCircle(93, 33, 5, SSD1306_BLACK);
}

// ============================================================
// THINKING ANIMATION
// ============================================================

void updateThinkingAnimation() {

  if (currentEmotion != EMOTION_THINKING) {

    return;
  }

  if (oledMode != OLED_IDLE) {

    return;
  }

  unsigned long now = millis();

  if (now - lastThinkingMove >= THINKING_MOVE_INTERVAL) {

    lastThinkingMove = now;

    if (thinkingDirection == 0) {

      thinkingDirection = 1;

    }

    else if (thinkingDirection == 1) {

      thinkingDirection = -1;

    }

    else {

      thinkingDirection = 0;
    }

    updateOLED();
  }
}

// ============================================================
// BLINK SYSTEM
// ============================================================

void updateBlink() {

  // Do not blink while speaking

  if (oledMode != OLED_IDLE) {

    blinking = false;

    return;
  }

  unsigned long now = millis();

  // Start blink

  if (!blinking && now - lastBlink >= BLINK_INTERVAL) {

    blinking = true;

    blinkStart = now;

    updateOLED();
  }

  // End blink

  if (blinking && now - blinkStart >= BLINK_DURATION) {

    blinking = false;

    lastBlink = now;

    updateOLED();
  }
}

// ============================================================
// EMOTION ACTION FUNCTIONS
//
// Python invokes these functions through WebSocket commands.
// ============================================================

void idle() {

  currentEmotion = EMOTION_IDLE;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: IDLE");
}

void happy() {

  currentEmotion = EMOTION_HAPPY;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: HAPPY");
}

void excited() {

  currentEmotion = EMOTION_EXCITED;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: EXCITED");
}

void angry() {

  currentEmotion = EMOTION_ANGRY;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: ANGRY");
}

void sad() {

  currentEmotion = EMOTION_SAD;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: SAD");
}

void surprised() {

  currentEmotion = EMOTION_SURPRISED;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: SURPRISED");
}

void thinking() {

  currentEmotion = EMOTION_THINKING;

  thinkingDirection = 0;

  lastThinkingMove = millis();

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: THINKING");
}

void sleepy() {

  currentEmotion = EMOTION_SLEEPY;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: SLEEPY");
}

void worried() {

  currentEmotion = EMOTION_WORRIED;

  thinkingDirection = 0;

  if (oledMode == OLED_IDLE) {

    updateOLED();
  }

  Serial.println("Emotion: WORRIED");
}

// ============================================================
// CHECK WORD FIT
// ============================================================

bool wordFits(String text, int maxWidth) {

  int16_t x1;
  int16_t y1;

  uint16_t w;
  uint16_t h;

  display.setTextSize(SPEECH_TEXT_SIZE);

  display.getTextBounds(text, 0, 0, &x1, &y1, &w, &h);

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

  const int maxWidth = 126;

  int position = 0;

  String currentLine = "";

  while (position < text.length() && messageLineCount < MAX_MESSAGE_LINES) {

    // Skip spaces

    while (position < text.length() && text.charAt(position) == ' ') {

      position++;
    }

    if (position >= text.length()) {

      break;
    }

    // Find next word

    int nextSpace = text.indexOf(' ', position);

    String word;

    if (nextSpace == -1) {

      word = text.substring(position);

      position = text.length();

    }

    else {

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

    }

    else {

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
      }

      currentLine = word;
    }
  }

  // Final line

  if (currentLine.length() > 0 && messageLineCount < MAX_MESSAGE_LINES) {

    messageLines[messageLineCount] = currentLine;

    messageLineCount++;
  }
}

// ============================================================
// START SPEAKING
// ============================================================

void oledMessage(String text) {

  Serial.print("OLED message: ");

  Serial.println(text);

  prepareMessage(text);

  // Start below screen

  scrollY = SCREEN_HEIGHT;

  // Speaking mode

  oledMode = OLED_SPEAKING;

  // Reset timers

  speechStartTime = millis();

  lastScrollUpdate = millis();

  speechFinishedTime = 0;

  updateOLED();
}

// ============================================================
// DRAW SPEAKING TEXT
// ============================================================

void drawSpeakingText() {

  display.setTextSize(SPEECH_TEXT_SIZE);

  display.setTextColor(SSD1306_WHITE);

  display.setTextWrap(false);

  for (int i = 0; i < messageLineCount; i++) {

    int y = scrollY + (i * SPEECH_LINE_HEIGHT);

    if (y >= -SPEECH_LINE_HEIGHT && y < SCREEN_HEIGHT) {

      display.setCursor(0, y);

      display.println(messageLines[i]);
    }
  }
}

// ============================================================
// UPDATE OLED
// ============================================================

void updateOLED() {

  display.clearDisplay();

  if (oledMode == OLED_IDLE) {

    drawEyes();

  }

  else {

    drawSpeakingText();
  }

  display.display();
}

// ============================================================
// UPDATE SPEECH SCROLL
// ============================================================

void updateSpeechScroll() {

  if (oledMode != OLED_SPEAKING) {

    return;
  }

  unsigned long now = millis();

  // Initial pause

  if (now - speechStartTime < START_PAUSE) {

    return;
  }

  // Check finished

  int finalTextPosition = scrollY + (messageLineCount * SPEECH_LINE_HEIGHT);

  if (finalTextPosition < 0) {

    if (speechFinishedTime == 0) {

      speechFinishedTime = now;

      updateOLED();

      return;
    }

    if (now - speechFinishedTime >= END_PAUSE) {

      oledMode = OLED_IDLE;

      blinking = false;

      lastBlink = millis();

      updateOLED();

      return;
    }
  }

  // Move text upward

  if (now - lastScrollUpdate >= SCROLL_SPEED) {

    lastScrollUpdate = now;

    scrollY--;

    updateOLED();
  }
}

// ============================================================
// OLED STARTUP
// ============================================================

void oledStartup() {

  // SDA = GPIO 21
  // SCL = GPIO 22

  Wire.begin(21, 22);

  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS)) {

    Serial.println("OLED not found!");

    return;
  }

  // IKRU STARTUP

  display.clearDisplay();

  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(2);

  display.setCursor(38, 0);

  display.println("IKRU");

  display.setTextSize(1);

  display.setCursor(28, 22);

  display.println("The Desk Robot");

  display.setCursor(37, 38);

  display.println("Powered by");

  display.setTextSize(2);

  display.setCursor(22, 50);

  display.println("POTATOES");

  display.display();

  delay(1500);
}

// ============================================================
// CONNECTING SCREEN
// ============================================================

void showConnecting() {

  display.clearDisplay();

  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);

  display.setCursor(0, 10);

  display.println("Connecting to WiFi...");

  display.setCursor(0, 30);

  display.println("Please wait");

  display.display();
}

// ============================================================
// WIFI CONNECTED
// ============================================================

void showWiFiConnected() {

  display.clearDisplay();

  display.setTextColor(SSD1306_WHITE);

  display.setTextSize(1);

  display.setCursor(0, 5);

  display.println("WiFi Connected");

  display.setCursor(0, 22);

  display.println(WiFi.localIP());

  display.display();

  // Short delay

  delay(500);
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

  // Stop motors

  stopMotors();

  // OLED

  oledStartup();

  // WiFi

  showConnecting();

  Serial.println("Connecting to WiFi...");

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {

    delay(500);

    Serial.print(".");
  }

  Serial.println();

  Serial.println("Connected!");

  Serial.print("IP Address: ");

  Serial.println(WiFi.localIP());

  // Short IP screen

  showWiFiConnected();

  // WebSocket

  webSocket.begin();

  webSocket.onEvent(webSocketEvent);

  Serial.println("WebSocket Server Started");

  // Initial emotion

  currentEmotion = EMOTION_HAPPY;

  oledMode = OLED_IDLE;

  blinking = false;

  lastBlink = millis();

  updateOLED();
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {

  // WebSocket

  webSocket.loop();

  // Blinking

  updateBlink();

  // Thinking eye movement

  updateThinkingAnimation();

  // Speech scrolling

  updateSpeechScroll();
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

  if (input.startsWith("DISPLAY:")) {

    String message = input.substring(8);

    oledMessage(message);

    return;
  }

  // Convert command to uppercase

  input.toUpperCase();

  // ==========================================================
  // EMOTION COMMANDS
  // ==========================================================

  if (input == "HAPPY") {

    happy();

    return;
  }

  else if (input == "SAD") {

    sad();

    return;
  }

  else if (input == "ANGRY") {

    angry();

    return;
  }

  else if (input == "EXCITED") {

    excited();

    return;
  }

  else if (input == "SURPRISED") {

    surprised();

    return;
  }

  else if (input == "THINKING") {

    thinking();

    return;
  }

  else if (input == "SLEEPY") {

    sleepy();

    return;
  }

  else if (input == "WORRIED") {

    worried();

    return;
  }

  else if (input == "IDLE") {

    idle();

    return;
  }

  // ==========================================================
  // MOTOR COMMANDS
  // ==========================================================

  if (input == "FORWARD") {

    moveForward();
  }

  else if (input == "BACKWARD") {

    moveBackward();
  }

  else if (input == "LEFT") {

    moveLeft();
  }

  else if (input == "RIGHT") {

    moveRight();
  }

  else if (input == "STOP") {

    stopMotors();
  }

  else {

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

  oledMessage("Moving Forward");
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

  oledMessage("Moving Backward");
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

  oledMessage("Moving Left");
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

  oledMessage("Moving Right");
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