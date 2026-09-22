/*
 * temperature_controller.ino  —  REFERENCE ("golden") IMPLEMENTATION
 * ==================================================================
 * Closed-loop thermal safety controller for a heating chamber.
 *
 * Sensor model
 * ------------
 * A 0.25 °C/LSB digital temperature sensor with a -50 °C offset is sampled
 * through the ADC channel:   T[°C] = raw * 0.25 - 50.0
 * (chosen so every threshold lands exactly on an integer code, which keeps
 *  boundary testing exact and fully deterministic).
 *
 * Requirements under test
 * -----------------------
 *  R1  The cooling fan SHALL turn ON when temperature is strictly greater
 *      than TEMP_THRESHOLD_C (30 °C) and OFF at or below it.
 *  R2  The red alarm LED SHALL latch ON when temperature reaches or exceeds
 *      TEMP_CRITICAL_C (45 °C) and stay latched until a reset.
 *  R3  The heater SHALL be disabled whenever the fan is running (mutual
 *      exclusion — never heat and cool simultaneously).
 *  R4  The controller SHALL apply HYSTERESIS_C (2 °C) when leaving the
 *      COOLING state to avoid relay chatter around the threshold.
 *  R5  Every control cycle SHALL emit one telemetry line on the UART in the
 *      format:  TEMP=<x.xx>,FAN=<0|1>,HEATER=<0|1>,ALARM=<0|1>,STATE=<name>
 *  R6  A sensor reading outside [-40, 125] °C SHALL be rejected as a fault:
 *      the system enters STATE_FAULT, fan ON, heater OFF.
 */

// ----------------------------- Pin map -------------------------------------
const int TEMP_SENSOR_PIN = A0;  // analog temperature sensor channel
const int FAN_PIN         = 5;   // cooling fan relay
const int HEATER_PIN      = 6;   // heater relay
const int ALARM_LED_PIN   = 7;   // red alarm LED
const int STATUS_LED_PIN  = 13;  // heartbeat LED

// ----------------------------- Sensor scaling ------------------------------
const float TEMP_LSB_C    = 0.25;   // °C per ADC count
const float TEMP_OFFSET_C = -50.0;  // code 0 maps to -50 °C

// ----------------------------- Thresholds ----------------------------------
const float TEMP_THRESHOLD_C = 30.0;   // fan-on threshold
const float TEMP_CRITICAL_C  = 45.0;   // critical alarm
const float TEMP_TARGET_C    = 22.0;   // heater setpoint
const float HYSTERESIS_C     = 2.0;    // anti-chatter band
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

  // --- R6: sensor plausibility check ---------------------------------------
  if (temperature < TEMP_MIN_VALID_C || temperature > TEMP_MAX_VALID_C) {
    currentState = STATE_FAULT;
    fanOn = true;
    heaterOn = false;
    Serial.println("ERROR:SENSOR_OUT_OF_RANGE");
  }
  // --- R2: critical alarm latch --------------------------------------------
  else if (temperature >= TEMP_CRITICAL_C) {
    alarmLatched = true;
    currentState = STATE_CRITICAL;
    fanOn = true;
    heaterOn = false;
  }
  // --- R1: cooling ----------------------------------------------------------
  else if (temperature > TEMP_THRESHOLD_C) {
    currentState = STATE_COOLING;
    fanOn = true;
    heaterOn = false;
  }
  // --- R4: hysteresis band --------------------------------------------------
  else if (fanOn && temperature > (TEMP_THRESHOLD_C - HYSTERESIS_C)) {
    currentState = STATE_COOLING;
    fanOn = true;
    heaterOn = false;
  }
  // --- heating --------------------------------------------------------------
  else if (temperature < TEMP_TARGET_C) {
    currentState = STATE_HEATING;
    fanOn = false;          // leaving cooling: clear the stale fan flag
    heaterOn = true;
  }
  // --- idle -----------------------------------------------------------------
  else {
    currentState = STATE_IDLE;
    fanOn = false;
    heaterOn = false;
  }

  // --- R3: enforce mutual exclusion ----------------------------------------
  if (fanOn) {
    heaterOn = false;
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(HEATER_PIN, heaterOn ? HIGH : LOW);
  digitalWrite(ALARM_LED_PIN, alarmLatched ? HIGH : LOW);
  digitalWrite(STATUS_LED_PIN, (millis() / 500) % 2);

  // --- R5: telemetry --------------------------------------------------------
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
