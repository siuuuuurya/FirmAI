/*
 * temperature_controller_buggy.ino  —  FAULT-INJECTED VARIANT
 * ============================================================
 * Functionally identical to temperature_controller.ino except for THREE
 * deliberately injected defects.  This is the firmware used by "Run Demo":
 * the agent receives no bug list — it must *discover* the defects by deriving
 * tests from the documented requirements and comparing the observed virtual
 * hardware behaviour against the expected behaviour.
 *
 * Injected defects (ground truth — used to score the agent, never fed to it):
 *   BUG-1 : fan threshold uses `>= 35.0` instead of `> TEMP_THRESHOLD_C`
 *           => the chamber overheats 5 °C beyond spec before the fan starts.
 *           Violates R1.
 *   BUG-2 : critical alarm uses `>` instead of `>=`
 *           => exactly 45.0 °C fails to latch the alarm (boundary off-by-one).
 *           Violates R2.
 *   BUG-3 : the fan/heater mutual-exclusion guard was deleted and the HEATING
 *           branch no longer clears `fanOn`
 *           => once the chamber cools below the setpoint the heater energises
 *              while the fan relay is still asserted.  Violates R3.
 *
 * Sensor model:  T[°C] = raw * 0.25 - 50.0
 *
 * Requirements under test (identical contract to the golden build)
 * ----------------------------------------------------------------
 *  R1  Fan ON when temperature > TEMP_THRESHOLD_C (30 °C), OFF at/below.
 *  R2  Alarm LED latches when temperature >= TEMP_CRITICAL_C (45 °C).
 *  R3  Heater disabled whenever the fan runs (mutual exclusion).
 *  R4  2 °C hysteresis when leaving COOLING.
 *  R5  Telemetry: TEMP=<x.xx>,FAN=<0|1>,HEATER=<0|1>,ALARM=<0|1>,STATE=<name>
 *  R6  Reading outside [-40, 125] °C => STATE_FAULT, fan ON, heater OFF.
 */

// ----------------------------- Pin map -------------------------------------
const int TEMP_SENSOR_PIN = A0;
const int FAN_PIN         = 5;
const int HEATER_PIN      = 6;
const int ALARM_LED_PIN   = 7;
const int STATUS_LED_PIN  = 13;

// ----------------------------- Sensor scaling ------------------------------
const float TEMP_LSB_C    = 0.25;
const float TEMP_OFFSET_C = -50.0;

// ----------------------------- Thresholds ----------------------------------
const float TEMP_THRESHOLD_C = 30.0;
const float TEMP_CRITICAL_C  = 45.0;
const float TEMP_TARGET_C    = 22.0;
const float HYSTERESIS_C     = 2.0;
const float TEMP_MIN_VALID_C = -40.0;
const float TEMP_MAX_VALID_C = 125.0;

// ----------------------------- State machine -------------------------------
enum SystemState {
  STATE_IDLE     = 0,
  STATE_HEATING  = 1,
  STATE_COOLING  = 2,
  STATE_CRITICAL = 3,
  STATE_FAULT    = 4
};

SystemState currentState = STATE_IDLE;
bool alarmLatched = false;
bool fanOn = false;
bool heaterOn = false;

float readTemperatureC() {
  int raw = analogRead(TEMP_SENSOR_PIN);
  return (raw * TEMP_LSB_C) + TEMP_OFFSET_C;
}

const char* stateName(SystemState s) {
  switch (s) {
    case STATE_IDLE:     return "IDLE";
    case STATE_HEATING:  return "HEATING";
    case STATE_COOLING:  return "COOLING";
    case STATE_CRITICAL: return "CRITICAL";
    case STATE_FAULT:    return "FAULT";
  }
  return "UNKNOWN";
}

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(HEATER_PIN, OUTPUT);
  pinMode(ALARM_LED_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);

  digitalWrite(FAN_PIN, LOW);
  digitalWrite(HEATER_PIN, LOW);
  digitalWrite(ALARM_LED_PIN, LOW);

  Serial.println("BOOT:temperature_controller v1.0");
}

void loop() {
  float temperature = readTemperatureC();

  if (temperature < TEMP_MIN_VALID_C || temperature > TEMP_MAX_VALID_C) {
    currentState = STATE_FAULT;
    fanOn = true;
    heaterOn = false;
    Serial.println("ERROR:SENSOR_OUT_OF_RANGE");
  }
  // BUG-2: boundary off-by-one — the specification says ">=", the code uses ">".
  else if (temperature > TEMP_CRITICAL_C) {
    alarmLatched = true;
    currentState = STATE_CRITICAL;
    fanOn = true;
    heaterOn = false;
  }
  // BUG-1: wrong operator AND wrong constant — the specification says
  //        "temperature > TEMP_THRESHOLD_C" (30 °C), the code uses ">= 35.0".
  else if (temperature >= 35.0) {
    currentState = STATE_COOLING;
    fanOn = true;
    heaterOn = false;
  }
  else if (fanOn && temperature > (TEMP_THRESHOLD_C - HYSTERESIS_C)) {
    currentState = STATE_COOLING;
    fanOn = true;
    heaterOn = false;
  }
  else if (temperature < TEMP_TARGET_C) {
    currentState = STATE_HEATING;
    // BUG-3a: `fanOn = false;` is missing here, so a fan asserted during a
    // previous COOLING cycle stays latched on while the heater turns on.
    heaterOn = true;
  }
  else {
    currentState = STATE_IDLE;
    fanOn = false;
    heaterOn = false;
  }

  // BUG-3b: the mutual-exclusion guard applied by the golden build here
  //         (`if (fanOn) { heaterOn = false; }`) has been removed entirely.

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(HEATER_PIN, heaterOn ? HIGH : LOW);
  digitalWrite(ALARM_LED_PIN, alarmLatched ? HIGH : LOW);
  digitalWrite(STATUS_LED_PIN, (millis() / 500) % 2);

  Serial.print("TEMP=");
  Serial.print(temperature, 2);
  Serial.print(",FAN=");
  Serial.print(fanOn ? 1 : 0);
  Serial.print(",HEATER=");
  Serial.print(heaterOn ? 1 : 0);
  Serial.print(",ALARM=");
  Serial.print(alarmLatched ? 1 : 0);
  Serial.print(",STATE=");
  Serial.println(stateName(currentState));

  delay(100);
}
