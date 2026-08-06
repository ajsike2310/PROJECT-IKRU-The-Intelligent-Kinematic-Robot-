#include <WiFi.h>
#include <WebSocketsServer.h>
// ============================================================
//  ESP32 Desktop Robot Controller - Phase 1
//  Hardware : ESP32-WROOM-32 DevKit + L293D Motor Driver Module + 2x DC Motor
//  Communication : USB Serial @ 115200 baud
//  Author   : AI Robotics Agent
// ============================================================
const char* ssid = "IEDC Maker Studio";
const char* password = "Iedcmks@2023";

WebSocketsServer webSocket(81);
// ------------------------------------------------------------
//  Pin Definitions – matches exact L293D module labels and
//  ESP32 board labels (Dxx = physical header pin label)
//
//  Motor 1 (Left)  → M1 screw terminal
//  Motor 2 (Right) → M2 screw terminal
// ------------------------------------------------------------

// Enable pins – must be HIGH for motors to run
#define EN1  13   // D13 → Module EN1  (Enable Left  motor)
#define EN2  33   // D33 → Module EN2  (Enable Right motor)
// NOTE: D34 is INPUT-ONLY on ESP32 – cannot be used for EN2.
//       Move EN2 wire from D34 to D33 on your breadboard.

// Direction pins – Left motor (M1)
#define C1A  26   // D26 → Module C1-A (Left  Motor – Direction A)
#define C1B  27   // D27 → Module C1-B (Left  Motor – Direction B)

// Direction pins – Right motor (M2)
#define C2A  14   // D14 → Module C2-A (Right Motor – Direction A)
#define C2B  12   // D12 → Module C2-B (Right Motor – Direction B)

// ============================================================
//  SETUP
// ============================================================
void setup() {

  pinMode(EN1, OUTPUT);
  pinMode(EN2, OUTPUT);
  pinMode(C1A, OUTPUT);
  pinMode(C1B, OUTPUT);
  pinMode(C2A, OUTPUT);
  pinMode(C2B, OUTPUT);

  stopMotors();

  Serial.begin(115200);

  Serial.println();
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

  webSocket.begin();
  webSocket.onEvent(webSocketEvent);

  Serial.println("WebSocket Server Started");
}

// ============================================================
//  MAIN LOOP
// ============================================================
void loop() {

    webSocket.loop();

}

void webSocketEvent(
    uint8_t client,
    WStype_t type,
    uint8_t * payload,
    size_t length
){

    switch(type){

        case WStype_CONNECTED:

            Serial.println("Client Connected");
            break;

        case WStype_DISCONNECTED:

            Serial.println("Client Disconnected");
            stopMotors();
            break;

        case WStype_TEXT:

            {

                String cmd = String((char*)payload);

                cmd.trim();

                Serial.print("Received: ");
                Serial.println(cmd);

                parseCommand(cmd);

                webSocket.sendTXT(client, "OK");

            }

            break;

        default:
            break;
    }

}
// ============================================================
//  COMMAND PARSER
//  Converts raw string input → motor action.
//  Keeping parsing separate from motor logic means the
//  communication layer (Serial, WiFi, BLE) can be swapped
//  later without touching movement functions.
// ============================================================
void parseCommand(String input) {
  input.toUpperCase();

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
//  MOTOR CONTROL FUNCTIONS
//
//  L293D module truth table (EN must be HIGH):
//    C_-A = HIGH, C_-B = LOW  → Forward
//    C_-A = LOW,  C_-B = HIGH → Backward
//    EN   = LOW               → Coast (stop)
//
//  Left  motor : EN1 (D13), C1-A (D26), C1-B (D27) → M1
//  Right motor : EN2 (D33), C2-A (D14), C2-B (D12) → M2
// ============================================================

// ------------------------------------------------------------
//  moveForward – Both motors forward
// ------------------------------------------------------------
void moveForward() {
  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, HIGH);
  digitalWrite(C1B, LOW);

  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, HIGH);
  digitalWrite(C2B, LOW);

  Serial.println("Moving Forward");
}

// ------------------------------------------------------------
//  moveBackward – Both motors backward
// ------------------------------------------------------------
void moveBackward() {
  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, LOW);
  digitalWrite(C1B, HIGH);

  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, LOW);
  digitalWrite(C2B, HIGH);

  Serial.println("Moving Backward");
}

// ------------------------------------------------------------
//  moveLeft – Left motor backward, Right motor forward (pivot)
// ------------------------------------------------------------
void moveLeft() {
  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, LOW);
  digitalWrite(C1B, HIGH);

  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, HIGH);
  digitalWrite(C2B, LOW);

  Serial.println("Moving Left");
}

// ------------------------------------------------------------
//  moveRight – Left motor forward, Right motor backward (pivot)
// ------------------------------------------------------------
void moveRight() {
  digitalWrite(EN1, HIGH);
  digitalWrite(C1A, HIGH);
  digitalWrite(C1B, LOW);

  digitalWrite(EN2, HIGH);
  digitalWrite(C2A, LOW);
  digitalWrite(C2B, HIGH);

  Serial.println("Moving Right");
}

// ------------------------------------------------------------
//  stopMotors – Disable both motors (coast to stop)
// ------------------------------------------------------------
void stopMotors() {
  // Pull enable LOW to disable both channels
  digitalWrite(EN1, LOW);
  digitalWrite(EN2, LOW);

  // Clear direction pins
  digitalWrite(C1A, LOW);
  digitalWrite(C1B, LOW);
  digitalWrite(C2A, LOW);
  digitalWrite(C2B, LOW);

  Serial.println("Stopped");
}
