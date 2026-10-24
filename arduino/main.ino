// Candy dispenser: send 'd' over USB and the turntable turns until a candy cuts the IR
// break beam across the chute ramp, or for at most MAX_SPIN_MS, then reverses for
// BACKSPIN_MS and stops. A 2 s watchdog reboots the Uno if the sketch ever hangs
// (it prints "ready: ..." again), so every loop that can run longer feeds it.
//
// Board: Arduino Uno. Motor: 23HS5628 NEMA 23 on a TB6600 / DM542 driver box.
//
// Wiring (see README -> Electronics), TB6600 common-anode:
//   TB6600  PUL+ and DIR+ -> Arduino 5V
//           PUL- -> pin 8   DIR- -> pin 9   (a pin driven LOW turns that input on)
//           ENA+/ENA- -> not connected: driver always on (see USE_ENABLE to change that)
//           VCC/GND -> separate 24 V supply; A+/A-/B+/B- -> motor
//   Beam    emitter:  red -> 5V, black -> GND
//           receiver: red -> 5V, black -> GND, signal -> pin 5 (internal pull-up)
//   HC-SR04 VCC -> 5V, GND -> GND, TRIG -> pin 6, ECHO -> pin 7
//           prints "someone: HERE <cm> cm" / "someone: GONE" as a visitor arrives or leaves;
//           and "distance: <cm> cm" / "distance: none" when the reading changes;
//           send 'p' for the last reading in the same form

#include <avr/wdt.h>

const int STEP_PIN = 8;
const int DIR_PIN = 9;
const int BEAM_PIN = 5;
const int ENABLE_PIN = 10;  // only used with USE_ENABLE
const int TRIG_PIN = 6;     // HC-SR04 ultrasonic sensor
const int ECHO_PIN = 7;

// Receiver level when a candy blocks the beam. These NPN receivers pull the signal LOW
// while they see the emitter... or the other way round, depending on the batch. Open the
// Serial Monitor (115200), put a finger between the two heads, and check that it prints
// "beam: BLOCKED". If it prints CLEAR instead, change LOW to HIGH here.
const int BEAM_BLOCKED = LOW;

// Common-anode: a pin driven LOW pulls current through that TB6600 input. Each step holds
// STEP_PIN LOW for half the step time, then HIGH for the other half: the square wave of the
// test sketch that ran the motor. (Short 10 us pulses didn't move it: this TB6600's input
// optocouplers are too slow for them.)
const int STEP_IDLE = HIGH;
const int STEP_ACTIVE = LOW;
const int FORWARD = LOW;  // as in the working test sketch; turntable must turn clockwise seen from above, else HIGH

// ENA not wired: the driver holds the motor powered all the time (it gets warm). To let it
// switch off between candies, wire ENA+ -> 5V and ENA- -> pin 10 and set USE_ENABLE to true:
// pin LOW = current through ENA = driver off.
const bool USE_ENABLE = false;
const int MOTOR_OFF = LOW;
const int MOTOR_ON = HIGH;

// Driver DIP switches set to 400 pulses/rev (half step), as in the original. Our gears
// are 66/14 = 4.71:1, so one turntable turn is ~1886 steps and one pocket (1/8) ~236.
const unsigned long STEP_INTERVAL_US = 4000;  // 2 ms LOW + 2 ms HIGH, as the test sketch: ~7.5 s per turntable turn
const unsigned long MAX_SPIN_MS = 15000;      // give up 15 s after the start (~2 turntable turns): empty or jammed
const unsigned long BACKSPIN_MS = 1000;       // then reverse this long (~250 steps), candy or not

// HC-SR04: someone closer than HERE_CM for HERE_PINGS pings in a row prints "someone: HERE";
// farther, or no echo, for GONE_PINGS in a row prints "someone: GONE".
const unsigned long PING_INTERVAL_MS = 1000;  // the sensor needs >= 60 ms between pings
const int MAX_CM = 200;     // farther counts as no echo: something stands ~2 m behind the door spot
const unsigned long ECHO_TIMEOUT_US = MAX_CM * 58UL;  // stop listening for an echo from beyond MAX_CM
const int HERE_CM = 150;  // voice/dispenser.py HERE_CM matches
const int HERE_PINGS = 2;   // 2 s
const int GONE_PINGS = 10;  // 10 s
int lastCm = 0;             // the last ping's distance (0: no echo), for 'p'
const int REPORT_STEP_CM = 50;   // "distance:" when the reading moves this much: someone stepping in or out

void setup() {
  MCUSR = 0;  // clear the reset flags, then a watchdog left running by a reboot
  wdt_disable();
  Serial.begin(115200);
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  digitalWrite(STEP_PIN, STEP_IDLE);
  digitalWrite(DIR_PIN, FORWARD);
  pinMode(BEAM_PIN, INPUT_PULLUP);  // the receiver's output only pulls down
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);
  pinMode(ECHO_PIN, INPUT_PULLUP);  // no sensor wired: reads HIGH, never an echo pulse
  if (USE_ENABLE) {
    pinMode(ENABLE_PIN, OUTPUT);
    digitalWrite(ENABLE_PIN, MOTOR_OFF);
  }
  Serial.println("ready: send 'd' to dispense");
  // a hang reboots the Uno; tested: Optiboot comes back once, ~2.1 s later, no reset loop
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  reportBeamChanges();
  reportVisitorChanges();
  char command = serialCommand();
  if (command == 'p') {
    reportDistance();
  }
  if (command == 'd') {
    dispense();
  }
}

// The next character sent over USB (Serial Monitor, or tools/dispense.py), or 0 if none.
// Line endings are skipped, so "d" + Enter works from the Serial Monitor.
char serialCommand() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c != '\n' && c != '\r') {
      return c;
    }
  }
  return 0;
}

bool beamBlocked() {
  return digitalRead(BEAM_PIN) == BEAM_BLOCKED;
}

// Prints the beam state whenever it changes, so the sensor can be checked by hand.
void reportBeamChanges() {
  static int last = -1;
  int now = beamBlocked();
  if (now != last) {
    Serial.println(now ? "beam: BLOCKED" : "beam: CLEAR");
    digitalWrite(LED_BUILTIN, now ? HIGH : LOW);
    last = now;
  }
}

// Distance to the nearest thing in cm, or 0 for no echo within MAX_CM. Blocks up to ECHO_TIMEOUT_US.
int distanceCm() {
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long us = pulseIn(ECHO_PIN, HIGH, ECHO_TIMEOUT_US);
  int cm = us / 58;  // sound: ~58 us per cm there and back
  return cm < MAX_CM ? cm : 0;
}

// Prints "someone: HERE <cm> cm" / "someone: GONE" when a visitor arrives or leaves.
void reportVisitorChanges() {
  static unsigned long lastPing = 0;
  static bool here = false;
  static int streak = 0;  // pings in a row that disagree with `here`
  if (millis() - lastPing < PING_INTERVAL_MS) {
    return;
  }
  lastPing = millis();
  int cm = distanceCm();
  lastCm = cm;
  reportDistanceChange(cm);
  bool near = cm > 0 && cm < HERE_CM;
  streak = (near != here) ? streak + 1 : 0;
  if (streak >= (here ? GONE_PINGS : HERE_PINGS)) {
    here = near;
    streak = 0;
    if (here) {
      Serial.print("someone: HERE ");
      Serial.print(cm);
      Serial.println(" cm");
    } else {
      Serial.println("someone: GONE");
    }
  }
}

// Prints "distance: <cm> cm" when a ping moved REPORT_STEP_CM from the last one printed, and
// "distance: none" once when it goes out of range (no echo within MAX_CM).
void reportDistanceChange(int cm) {
  static int reported = 0;  // 0: nothing in range
  if ((cm == 0) != (reported == 0) || abs(cm - reported) >= REPORT_STEP_CM) {
    reported = cm;
    printDistance(cm);
  }
}

// Answers 'p' with the last ping's distance (at most PING_INTERVAL_MS old), for voice/main.py's
// debug log. It doesn't ping again: the sensor needs its 60 ms between pings.
void reportDistance() {
  printDistance(lastCm);
}

void printDistance(int cm) {
  if (cm > 0) {
    Serial.print("distance: ");
    Serial.print(cm);
    Serial.println(" cm");
  } else {
    Serial.println("distance: none");
  }
}

void dispense() {
  if (beamBlocked()) {
    Serial.println("beam already blocked: candy stuck in the chute, or the heads are misaligned");
    return;
  }
  Serial.println("dispensing");
  digitalWrite(DIR_PIN, FORWARD);
  setMotor(MOTOR_ON);
  delay(5);  // let the driver wake (and DIR settle) before the first pulse

  // Step without blocking: flip STEP_PIN every half step and read the beam in between
  // (every few microseconds), so a candy that crosses it in a couple of ms is never missed.
  const unsigned long half = STEP_INTERVAL_US / 2;
  const unsigned long start = millis();
  long steps = 0;
  bool active = false;
  unsigned long lastEdge = micros();
  bool dropped = false;
  while (millis() - start < MAX_SPIN_MS) {
    wdt_reset();
    if (beamBlocked()) {
      dropped = true;
      break;
    }
    if (micros() - lastEdge >= half) {
      lastEdge += half;
      active = !active;
      digitalWrite(STEP_PIN, active ? STEP_ACTIVE : STEP_IDLE);
      if (!active) {
        steps++;  // a full LOW-then-HIGH cycle is one step
      }
    }
  }
  digitalWrite(STEP_PIN, STEP_IDLE);

  if (dropped) {
    Serial.print("candy! after ");
    Serial.print(steps);
    Serial.println(" steps");
  } else {
    Serial.println("no candy after 15 s: refill the bucket or check for a jam");
  }
  backspin();
  if (!dropped) {
    blink(10);
  }
  setMotor(MOTOR_OFF);
}

void setMotor(int state) {
  if (USE_ENABLE) {
    digitalWrite(ENABLE_PIN, state);
  }
}

void backspin() {
  digitalWrite(DIR_PIN, FORWARD == HIGH ? LOW : HIGH);
  delay(5);  // let DIR settle before the first step
  const unsigned long start = millis();
  while (millis() - start < BACKSPIN_MS) {
    wdt_reset();
    digitalWrite(STEP_PIN, STEP_ACTIVE);
    delayMicroseconds(STEP_INTERVAL_US / 2);
    digitalWrite(STEP_PIN, STEP_IDLE);
    delayMicroseconds(STEP_INTERVAL_US / 2);
  }
}

void blink(int times) {
  for (int i = 0; i < times; i++) {
    wdt_reset();
    digitalWrite(LED_BUILTIN, HIGH);
    delay(150);
    digitalWrite(LED_BUILTIN, LOW);
    delay(150);
  }
}
