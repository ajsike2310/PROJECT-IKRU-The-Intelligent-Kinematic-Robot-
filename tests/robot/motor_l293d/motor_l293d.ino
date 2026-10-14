/*
===============================================================================
 PROJECT IKRU — L293D MOTOR DRIVER TEST (standalone, no Wi-Fi)
===============================================================================
 Flash this to the ESP32, open Serial Monitor at 115200 baud, send commands.
 Uses the same ESP32 GPIOs as firmware/controller, so no re-wiring on the ESP32 side.

 WIRING  (L293D, 16-pin DIP — notch/dot marks pin 1, count anti-clockwise)
 Same names and GPIOs as firmware/controller/controller.ino.
 ---------------------------------------------------------------------------
   Firmware   ESP32     L293D pin        Purpose
   EN1        GPIO13    1   (1,2EN)      Left motor enable / speed (PWM)
   C1A        GPIO26    2   (1A)         Left motor direction A
   C1B        GPIO27    7   (2A)         Left motor direction B
   EN2        GPIO33    9   (3,4EN)      Right motor enable / speed (PWM)
   C2A        GPIO14    10  (3A)         Right motor direction A
   C2B        GPIO12    15  (4A)         Right motor direction B

   L293D pin 3 (1Y) + 6 (2Y)     Left motor leads
   L293D pin 11 (3Y) + 14 (4Y)   Right motor leads
   L293D pin 16 (VCC1)           5 V logic supply (4.5 – 7 V): ESP32 VIN/5V or a 5 V regulator
   L293D pin 8  (VCC2)           Motor battery + (4.5 – 36 V)
   L293D pins 4, 5, 12, 13       GND. Solder all 4 (they're also the heat sink)

   ESP32 GND  <->  L293D GND  <->  battery –      (common ground is mandatory)

 NOTES
   * 3.3 V ESP32 outputs are a valid HIGH for the L293D (VIH min 2.3 V).
   * L293D drops ~1.5–3 V across its transistors. With a 2S Li-ion (7.4 V) pack
     the motors only see ~5 V. Weak motion with a full battery is normal for this chip.
   * Max 600 mA per channel (1.2 A peak). TT gear motors stalling can exceed this;
     the chip gets hot and shuts down thermally.
   * GPIO12 (C2B) is a boot strapping pin and must be LOW at reset. Don't add a pull-up to it.
     If the ESP32 won't boot while the L293D is connected, add a 10k pull-down on GPIO12.
   * Recommended: 10k pull-down resistors from EN1 (GPIO13) and EN2 (GPIO33) to GND.
     Floating L293D inputs read as HIGH, and GPIO14 toggles during ESP32 boot, so
     without them the right wheel can twitch at power-on.

 SERIAL COMMANDS
   f / b / l / r   both motors: forward / backward / turn left / turn right (MOVE_MS then stop)
   1               LEFT motor only:  forward, pause, reverse
   2               RIGHT motor only: forward, pause, reverse
   a               auto test: 1, 2, then f, b, l, r
   p               speed ramp 0 -> 100% -> 0 (find the duty where the wheels start)
   + / -           speed +/- 10%
   s               stop (coast, EN LOW)
   x               brake (EN HIGH, both inputs LOW)
   h               help
===============================================================================
*/

#include <Arduino.h>

// ---------------- Pins ----------------
#define EN1 13   // L293D pin 1  (1,2EN)  left speed
#define C1A 26   // L293D pin 2  (1A)
#define C1B 27   // L293D pin 7  (2A)
#define EN2 33   // L293D pin 9  (3,4EN)  right speed
#define C2A 14   // L293D pin 10 (3A)
#define C2B 12   // L293D pin 15 (4A)

// ---------------- Settings ----------------
const uint32_t PWM_FREQ = 1000;  // L293D is a slow bipolar driver: keep PWM low (~1 kHz)
const uint8_t  PWM_BITS = 8;
const uint32_t MOVE_MS  = 1500;

int speedPct = 80;

void setMotor(uint8_t en, uint8_t inA, uint8_t inB, int pct) {
  pct = constrain(pct, -100, 100);
  if (pct == 0) {
    ledcWrite(en, 0);
    digitalWrite(inA, LOW);
    digitalWrite(inB, LOW);
    return;
  }
  digitalWrite(inA, pct > 0 ? HIGH : LOW);
  digitalWrite(inB, pct > 0 ? LOW : HIGH);
  ledcWrite(en, map(abs(pct), 0, 100, 0, 255));
}

void leftMotor(int pct)  { setMotor(EN1, C1A, C1B, pct); }
void rightMotor(int pct) { setMotor(EN2, C2A, C2B, pct); }

void coast() {
  leftMotor(0);
  rightMotor(0);
}

void brake() {
  digitalWrite(C1A, LOW); digitalWrite(C1B, LOW);
  digitalWrite(C2A, LOW); digitalWrite(C2B, LOW);
  ledcWrite(EN1, 255);
  ledcWrite(EN2, 255);
  delay(200);
  coast();
}

void run(const char* label, int left, int right, uint32_t ms = MOVE_MS) {
  Serial.printf("  %-28s L=%4d%%  R=%4d%%\n", label, left, right);
  leftMotor(left);
  rightMotor(right);
  delay(ms);
  coast();
  delay(400);
}

void singleMotorTest(bool left) {
  const char* name = left ? "LEFT" : "RIGHT";
  Serial.printf("\n[%s motor only] Watch which wheel turns and which way.\n", name);
  char label[40];
  snprintf(label, sizeof(label), "%s forward", name);
  run(label, left ? speedPct : 0, left ? 0 : speedPct);
  snprintf(label, sizeof(label), "%s reverse", name);
  run(label, left ? -speedPct : 0, left ? 0 : -speedPct);
  Serial.println("  If the other wheel moved: the motors are on the wrong channels (swap 3/6 with 11/14).");
  Serial.println("  If 'forward' spun backward: swap that motor's two leads.");
}

void rampTest() {
  Serial.println("\n[Ramp] Both motors forward. Note the % where the wheels START to turn.");
  for (int p = 0; p <= 100; p += 5) {
    leftMotor(p); rightMotor(p);
    Serial.printf("  %3d%%\n", p);
    delay(300);
  }
  for (int p = 100; p >= 0; p -= 10) {
    leftMotor(p); rightMotor(p);
    delay(150);
  }
  coast();
  Serial.println("  Ramp done. Set your minimum speed a little above the start %.");
}

void autoTest() {
  Serial.println("\n===== AUTO TEST (L293D) =====");
  singleMotorTest(true);
  singleMotorTest(false);
  Serial.println("\n[Both motors]");
  run("FORWARD", speedPct, speedPct);
  run("BACKWARD", -speedPct, -speedPct);
  run("LEFT (spin)", -speedPct, speedPct);
  run("RIGHT (spin)", speedPct, -speedPct);
  Serial.println("===== AUTO TEST DONE =====");
}

void printHelp() {
  Serial.println("\nL293D test. Commands: f b l r | 1 2 (single motor) | a (auto) | p (ramp) | + - (speed) | s (stop) | x (brake) | h");
  Serial.printf("Speed: %d%%   Move time: %lu ms\n", speedPct, (unsigned long)MOVE_MS);
}

void setup() {
  // Direction pins LOW first so nothing twitches at boot
  pinMode(C1A, OUTPUT); pinMode(C1B, OUTPUT);
  pinMode(C2A, OUTPUT); pinMode(C2B, OUTPUT);
  digitalWrite(C1A, LOW); digitalWrite(C1B, LOW);
  digitalWrite(C2A, LOW); digitalWrite(C2B, LOW);
  ledcAttach(EN1, PWM_FREQ, PWM_BITS);
  ledcAttach(EN2, PWM_FREQ, PWM_BITS);
  coast();

  Serial.begin(115200);
  delay(300);
  Serial.println("\n==========================================");
  Serial.println("  PROJECT IKRU — L293D Motor Test");
  Serial.println("  EN1=13 C1A=26 C1B=27 | EN2=33 C2A=14 C2B=12");
  Serial.println("==========================================");
  printHelp();
}

void loop() {
  if (!Serial.available()) return;
  char c = tolower(Serial.read());
  switch (c) {
    case 'f': run("FORWARD", speedPct, speedPct); break;
    case 'b': run("BACKWARD", -speedPct, -speedPct); break;
    case 'l': run("LEFT (spin)", -speedPct, speedPct); break;
    case 'r': run("RIGHT (spin)", speedPct, -speedPct); break;
    case '1': singleMotorTest(true); break;
    case '2': singleMotorTest(false); break;
    case 'a': autoTest(); break;
    case 'p': rampTest(); break;
    case '+': speedPct = min(100, speedPct + 10); Serial.printf("Speed %d%%\n", speedPct); break;
    case '-': speedPct = max(10, speedPct - 10);  Serial.printf("Speed %d%%\n", speedPct); break;
    case 's': coast(); Serial.println("STOP (coast)"); break;
    case 'x': brake(); Serial.println("BRAKE"); break;
    case 'h': printHelp(); break;
    default: break;  // ignore newlines etc.
  }
}
