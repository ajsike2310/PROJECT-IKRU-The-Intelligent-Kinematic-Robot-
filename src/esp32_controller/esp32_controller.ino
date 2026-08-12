#include "Face.h"
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
// SSD1306 128x64 I2C OLED (driven via U8g2 through the Face library)
//
// Communication:
// WiFi + WebSocket
//
// OLED:
// IDLE     -> Animated eye expressions (Face library)
// SPEAKING -> Full screen large scrolling text (U8g2)
// ============================================================

// ============================================================
// WIFI
// ============================================================

const char *ssid = "AJx24";
const char *password = "avin1236";

WebSocketsServer webSocket(81);

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
const unsigned long SCROLL_SPEED = 120;

// Pause before scrolling begins
const unsigned long START_PAUSE = 1000;

// Pause after message finishes scrolling
const unsigned long END_PAUSE = 800;

unsigned long lastScrollUpdate = 0;

unsigned long speechStartTime = 0;

unsigned long speechFinishedTime = 0;

// ============================================================
// FUNCTION DECLARATIONS
// ============================================================

void oledStartup();

void showConnecting();

void showWiFiConnected();

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

  const int maxWidth = 126;

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

    // Word does not fit — flush current line
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

  // Start text below screen bottom
  scrollY = 64;

  // Switch to speaking mode (stops face->Update() in loop)
  oledMode = OLED_SPEAKING;

  // Reset timers
  speechStartTime = millis();
  lastScrollUpdate = millis();
  speechFinishedTime = 0;

  // Draw immediately
  drawSpeakingText();
}

// ============================================================
// DRAW SPEAKING TEXT (U8g2)
// ============================================================

void drawSpeakingText() {

  u8g2.clearBuffer();

  u8g2.setFont(SPEECH_FONT);

  u8g2.setFontMode(1);

  for (int i = 0; i < messageLineCount; i++) {

    // U8g2 draws text at the baseline, so add font ascent (~14px)
    int y = scrollY + (i * SPEECH_LINE_HEIGHT) + 14;

    if (y >= 0 && y <= 78) {

      u8g2.drawStr(1, y, messageLines[i].c_str());
    }
  }

  u8g2.sendBuffer();
}

// ============================================================
// UPDATE SPEECH SCROLL
// ============================================================

void updateSpeechScroll() {

  if (oledMode != OLED_SPEAKING) {
    return;
  }

  unsigned long now = millis();

  // Initial pause before scroll begins
  if (now - speechStartTime < START_PAUSE) {
    return;
  }

  // Check if all text has scrolled off the top
  int finalTextPosition = scrollY + (messageLineCount * SPEECH_LINE_HEIGHT);

  if (finalTextPosition < 0) {

    if (speechFinishedTime == 0) {
      speechFinishedTime = now;
      drawSpeakingText();
      return;
    }

    if (now - speechFinishedTime >= END_PAUSE) {

      // Return to face/eye mode
      oledMode = OLED_IDLE;

      return;
    }
  }

  // Move text upward one pixel each tick
  if (now - lastScrollUpdate >= SCROLL_SPEED) {
    lastScrollUpdate = now;
    scrollY--;
    drawSpeakingText();
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

  // Start with a happy expression
  face->Expression.GoTo_Happy();

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

  showWiFiConnected();

  // WebSocket
  webSocket.begin();
  webSocket.onEvent(webSocketEvent);

  Serial.println("WebSocket Server Started");

  // Initial emotion
  oledMode = OLED_IDLE;
  face->Expression.GoTo_Happy();
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {

  // WebSocket
  webSocket.loop();

  // Update speech scroll (returns early if not in speaking mode)
  updateSpeechScroll();

  // Update face animation only while in idle (eye) mode
  if (oledMode == OLED_IDLE) {
    face->Update();
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