/*
===============================================================================
 PROJECT IKRU — DRV8833 MOTOR DRIVER TEST (standalone, no Wi-Fi)
===============================================================================
 Flash this to the ESP32, open Serial Monitor at 115200 baud, send commands.
 Uses the same ESP32 GPIOs as firmware/controller, so no re-wiring on the ESP32 side.

 WIRING  (common red DRV8833 module: IN1-IN4, OUT1-OUT4, EEP, ULT, VCC, GND)
 ---------------------------------------------------------------------------
   Module pin     Connect to            Purpose
   IN1            ESP32 GPIO26          Left motor (A) input 1   (PWM)
   IN2            ESP32 GPIO27          Left motor (A) input 2   (PWM)
   IN3            ESP32 GPIO14          Right motor (B) input 1  (PWM)
   IN4            ESP32 GPIO12          Right motor (B) input 2  (PWM)
   EEP (nSLEEP)   ESP32 GPIO13          HIGH = driver awake, LOW = sleep / outputs off
   ULT (nFAULT)   ESP32 GPIO32          Optional. Pulled LOW on over-current / over-heat / low voltage
   OUT1, OUT2     Left motor leads
   OUT3, OUT4     Right motor leads
   VCC (VM)       Motor battery +       2.7 V – 10.8 V (2S Li-ion 7.4 V is ideal)
   GND            Common GND            ESP32 GND and battery – together

   The module has ONE EEP/nSLEEP pin for both motors. GPIO33 (EN2 in the main
   firmware) is also driven HIGH here, so older wiring with GPIO33 on EEP still works.

 NOTES
   * Speed = PWM on the IN pins (there is no separate enable pin like the L293D).
       forward: IN1 = PWM, IN2 = 0     reverse: IN1 = 0, IN2 = PWM
       coast:   IN1 = IN2 = 0          brake:   IN1 = IN2 = 1
   * 1.5 A RMS / 2 A peak per channel, MOSFET outputs, very small voltage drop.
   * Some modules have a jumper/pad that ties EEP HIGH permanently. Then GPIO13 does nothing.
   * GPIO12 is a boot strapping pin and must be LOW at reset. The DRV8833 inputs have
     internal pull-downs, so that's fine. Don't add a pull-up.

 SERIAL COMMANDS
   f / b / l / r   both motors: forward / backward / turn left / turn right (MOVE_MS then stop)
   1               LEFT motor only:  forward, pause, reverse
   2               RIGHT motor only: forward, pause, reverse
   a               auto test: sleep-pin check, 1, 2, then f, b, l, r
   p               speed ramp 0 -> 100% -> 0 (find the duty where the wheels start)
   z               sleep-pin test: tries to drive with EEP LOW (wheels must NOT move)
   + / -           speed +/- 10%
   s               stop (coast)
   x               brake (both inputs HIGH)
   h               help
===============================================================================
*/

#include <Arduino.h>

// ---------------- Pins ----------------
#define IN1 26        // AIN1 -> left motor
#define IN2 27        // AIN2
#define IN3 14        // BIN1 -> right motor
#define IN4 12        // BIN2
#define EEP 13        // nSLEEP
#define EEP_ALT 33    // legacy second "enable" from the L293D layout; driven with EEP
#define FAULT_PIN 32  // ULT / nFAULT (open drain, active LOW). Set to -1 if not wired.

// ---------------- Settings ----------------
const uint32_t PWM_FREQ = 20000;  // 20 kHz: above hearing, well inside the DRV8833's limit
const uint8_t  PWM_BITS = 8;
const uint32_t MOVE_MS  = 1500;

int speedPct = 80;

void wake(bool on) {
  digitalWrite(EEP, on ? HIGH : LOW);
  digitalWrite(EEP_ALT, on ? HIGH : LOW);
  if (on) delay(2);  // datasheet wake-up time is ~1 ms
}

void setMotor(uint8_t inA, uint8_t inB, int pct) {
  pct = constrain(pct, -100, 100);
  uint32_t duty = map(abs(pct), 0, 100, 0, 255);
  if (pct > 0)      { ledcWrite(inA, duty); ledcWrite(inB, 0); }
  else if (pct < 0) { ledcWrite(inA, 0);    ledcWrite(inB, duty); }
  else              { ledcWrite(inA, 0);    ledcWrite(inB, 0); }
}

void leftMotor(int pct)  { setMotor(IN1, IN2, pct); }
void rightMotor(int pct) { setMotor(IN3, IN4, pct); }

void coast() {
  leftMotor(0);
  rightMotor(0);
}

void brake() {
  ledcWrite(IN1, 255); ledcWrite(IN2, 255);
  ledcWrite(IN3, 255); ledcWrite(IN4, 255);
  delay(200);
  coast();
}

void checkFault() {
#if FAULT_PIN >= 0
  if (digitalRead(FAULT_PIN) == LOW) {
    Serial.println("  [!] nFAULT is LOW: over-current (stalled/shorted motor), over-temperature");
    Serial.println("      or VM under-voltage (battery too low / sagging).");
  }
#endif
}

void run(const char* label, int left, int right, uint32_t ms = MOVE_MS) {
  Serial.printf("  %-28s L=%4d%%  R=%4d%%\n", label, left, right);
  leftMotor(left);
  rightMotor(right);
  uint32_t end = millis() + ms;
  while (millis() < end) {
    delay(50);
  }
  checkFault();
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
  Serial.println("  If the other wheel moved: motors are on the wrong outputs (swap OUT1/2 with OUT3/4).");
  Serial.println("  If 'forward' spun backward: swap that motor's two leads.");
}

void sleepTest() {
  Serial.println("\n[Sleep pin] Driving FORWARD with EEP LOW. The wheels must NOT move...");
  wake(false);
  leftMotor(speedPct); rightMotor(speedPct);
  delay(1200);
  coast();
  wake(true);
  Serial.println("  If they moved anyway: EEP is tied HIGH on the module (jumper/pad) or not wired to GPIO13.");
  Serial.println("  That's OK for driving. You just can't put the driver to sleep from the ESP32.");
}

void rampTest() {
  Serial.println("\n[Ramp] Both motors forward. Note the % where the wheels START to turn.");
  for (int p = 0; p <= 100; p += 5) {
    leftMotor(p); rightMotor(p);
    Serial.printf("  %3d%%\n", p);
    delay(300);
  }
  checkFault();
  for (int p = 100; p >= 0; p -= 10) {
    leftMotor(p); rightMotor(p);
    delay(150);
  }
  coast();
  Serial.println("  Ramp done. Set your minimum speed a little above the start %.");
}

void autoTest() {
  Serial.println("\n===== AUTO TEST (DRV8833) =====");
  sleepTest();
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
  Serial.println("\nDRV8833 test. Commands: f b l r | 1 2 (single motor) | a (auto) | p (ramp) | z (sleep pin) | + - (speed) | s (stop) | x (brake) | h");
  Serial.printf("Speed: %d%%   Move time: %lu ms\n", speedPct, (unsigned long)MOVE_MS);
}

void setup() {
  pinMode(EEP, OUTPUT);
  pinMode(EEP_ALT, OUTPUT);
  wake(false);
#if FAULT_PIN >= 0
  pinMode(FAULT_PIN, INPUT_PULLUP);
#endif
  ledcAttach(IN1, PWM_FREQ, PWM_BITS);
  ledcAttach(IN2, PWM_FREQ, PWM_BITS);
  ledcAttach(IN3, PWM_FREQ, PWM_BITS);
  ledcAttach(IN4, PWM_FREQ, PWM_BITS);
  coast();
  wake(true);

  Serial.begin(115200);
  delay(300);
  Serial.println("\n==========================================");
  Serial.println("  PROJECT IKRU — DRV8833 Motor Test");
  Serial.println("  IN1=26 IN2=27 IN3=14 IN4=12 | EEP=13 | ULT=32");
  Serial.println("==========================================");
  checkFault();
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
    case 'z': sleepTest(); break;
    case '+': speedPct = min(100, speedPct + 10); Serial.printf("Speed %d%%\n", speedPct); break;
    case '-': speedPct = max(10, speedPct - 10);  Serial.printf("Speed %d%%\n", speedPct); break;
    case 's': coast(); Serial.println("STOP (coast)"); break;
    case 'x': brake(); Serial.println("BRAKE"); break;
    case 'h': printHelp(); break;
    default: break;
  }
}
