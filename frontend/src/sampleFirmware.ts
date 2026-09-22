export interface FirmwarePreset {
  id: string;
  name: string;
  filename: string;
  category: 'prompt_example' | 'complex_fsm';
  variant: 'buggy' | 'fixed';
  description: string;
  code: string;
}

export const FIRMWARE_PRESETS: FirmwarePreset[] = [
  {
    id: 'fan_buggy',
    name: 'Cooling Fan Controller (Hackathon Prompt Example — Buggy)',
    filename: 'fan_buggy.ino',
    category: 'prompt_example',
    variant: 'buggy',
    description: 'Exact hackathon prompt example. Fan OFF below 30°C, ON at/above 30°C, error on sensor disconnection. Contains 2 planted bugs (off-by-one at 30°C and missing 1023 disconnect check).',
    code: `/*
 * Cooling fan controller (BUGGY VERSION - contains 2 planted bugs)
 * Sensor: NTC thermistor on A0 | Fan LED: pin 9 | Error LED: pin 8
 *
 * Requirements under test:
 *   R1  Fan OFF below 30 °C, ON at or above 30 °C.
 *   R2  Error LED ON if sensor stops responding or disconnects (ADC <= 0 or ADC >= 1023).
 *   R3  Serial telemetry emitted every cycle: TEMP=<deg> FAN=<ON|OFF> STATE=<NORMAL|ERROR>.
 */

const int NTC_PIN     = A0;
const int FAN_PIN     = 9;
const int ERR_LED_PIN = 8;
const float BETA      = 3950.0;   // thermistor constant
const int THRESHOLD_C = 30;       // fan turns on at this temperature

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(ERR_LED_PIN, OUTPUT);
}

void loop() {
  int adc = analogRead(NTC_PIN);      // 0..1023
  bool fanOn = false;
  bool error = false;
  int tempC = 0;

  if (adc == 0) {                     // BUG 2: does not check adc == 1023 (sensor disconnect)
    error = true;
  } else {
    float t = 1.0 / (log(1.0 / (1023.0 / adc - 1.0)) / BETA + 1.0 / 298.15) - 273.15;
    tempC = (int)(t + 0.5);           // round to nearest degree
    if (tempC > THRESHOLD_C) {        // BUG 1: should be >= (spec: ON at 30C and above)
      fanOn = true;
    }
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(ERR_LED_PIN, error ? HIGH : LOW);

  Serial.print("TEMP=");
  Serial.print(tempC);
  Serial.print(" FAN=");
  Serial.print(fanOn ? "ON" : "OFF");
  Serial.print(" STATE=");
  Serial.println(error ? "ERROR" : "NORMAL");

  delay(500);
}
`,
  },
  {
    id: 'fan_fixed',
    name: 'Cooling Fan Controller (Hackathon Prompt Example — Fixed)',
    filename: 'fan_fixed.ino',
    category: 'prompt_example',
    variant: 'fixed',
    description: 'Golden reference for the cooling fan controller. Complies 100% with R1, R2, R3 (detects both shorted and disconnected sensor states, boundary exact at 30°C).',
    code: `/*
 * Cooling fan controller (FIXED VERSION)
 * Sensor: NTC thermistor on A0 | Fan LED: pin 9 | Error LED: pin 8
 *
 * Requirements under test:
 *   R1  Fan OFF below 30 °C, ON at or above 30 °C.
 *   R2  Error LED ON if sensor stops responding or disconnects (ADC <= 0 or ADC >= 1023).
 *   R3  Serial telemetry emitted every cycle: TEMP=<deg> FAN=<ON|OFF> STATE=<NORMAL|ERROR>.
 */

const int NTC_PIN     = A0;
const int FAN_PIN     = 9;
const int ERR_LED_PIN = 8;
const float BETA      = 3950.0;   // thermistor constant
const int THRESHOLD_C = 30;       // fan turns on at this temperature

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(ERR_LED_PIN, OUTPUT);
}

void loop() {
  int adc = analogRead(NTC_PIN);      // 0..1023
  bool fanOn = false;
  bool error = false;
  int tempC = 0;

  if (adc <= 0 || adc >= 1023) {      // sensor fault: shorted (0) or open (1023)
    error = true;
  } else {
    float t = 1.0 / (log(1.0 / (1023.0 / adc - 1.0)) / BETA + 1.0 / 298.15) - 273.15;
    tempC = (int)(t + 0.5);           // round to nearest degree
    if (tempC >= THRESHOLD_C) {       // spec: ON at 30C and above
      fanOn = true;
    }
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(ERR_LED_PIN, error ? HIGH : LOW);

  Serial.print("TEMP=");
  Serial.print(tempC);
  Serial.print(" FAN=");
  Serial.print(fanOn ? "ON" : "OFF");
  Serial.print(" STATE=");
  Serial.println(error ? "ERROR" : "NORMAL");

  delay(500);
}
`,
  },
  {
    id: 'temp_buggy',
    name: 'Dual Heating/Cooling Safety FSM (Fault Injected — 3 Defects)',
    filename: 'temperature_controller_buggy.ino',
    category: 'complex_fsm',
    variant: 'buggy',
    description: 'Complex multi-state controller with fan, heater, alarm LED, hysteresis, and sensor fault states. Injected with 3 subtle edge-case safety bugs.',
    code: `/*
 * temperature_controller_buggy.ino  —  FAULT-INJECTED VARIANT
 *
 * Requirements under test:
 *  R1  Fan ON when temperature > TEMP_THRESHOLD_C (30 °C), OFF at/below.
 *  R2  Alarm LED latches when temperature >= TEMP_CRITICAL_C (45 °C).
 *  R3  Heater disabled whenever the fan runs (mutual exclusion).
 *  R4  2 °C hysteresis when leaving COOLING.
 *  R5  Telemetry: TEMP=<x.xx>,FAN=<0|1>,HEATER=<0|1>,ALARM=<0|1>,STATE=<name>
 *  R6  Reading outside [-40, 125] °C => STATE_FAULT, fan ON, heater OFF.
 */

const int TEMP_SENSOR_PIN = A0;
const int FAN_PIN         = 5;
const int HEATER_PIN      = 6;
const int ALARM_LED_PIN   = 7;
const int STATUS_LED_PIN  = 13;

const float TEMP_LSB_C    = 0.25;
const float TEMP_OFFSET_C = -50.0;

const float TEMP_THRESHOLD_C = 30.0;
const float TEMP_CRITICAL_C  = 45.0;
const float TEMP_TARGET_C    = 22.0;
const float HYSTERESIS_C     = 2.0;
const float TEMP_MIN_VALID_C = -40.0;
const float TEMP_MAX_VALID_C = 125.0;

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

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(HEATER_PIN, OUTPUT);
  pinMode(ALARM_LED_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
}

void loop() {
  float temperature = readTemperatureC();

  if (temperature < TEMP_MIN_VALID_C || temperature > TEMP_MAX_VALID_C) {
    currentState = STATE_FAULT;
    fanOn = true;
    heaterOn = false;
  }
  // BUG-2: strict inequality '>' instead of '>='
  else if (temperature > TEMP_CRITICAL_C) {
    alarmLatched = true;
    currentState = STATE_CRITICAL;
    fanOn = true;
    heaterOn = false;
  }
  // BUG-1: wrong constant '>= 35.0' instead of '> TEMP_THRESHOLD_C' (30 C)
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
    // BUG-3: missing fanOn = false -> violates mutual exclusion R3
    heaterOn = true;
  }
  else {
    currentState = STATE_IDLE;
    fanOn = false;
    heaterOn = false;
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(HEATER_PIN, heaterOn ? HIGH : LOW);
  digitalWrite(ALARM_LED_PIN, alarmLatched ? HIGH : LOW);

  Serial.print("TEMP="); Serial.print(temperature, 2);
  Serial.print(",FAN="); Serial.print(fanOn ? 1 : 0);
  Serial.print(",HEATER="); Serial.print(heaterOn ? 1 : 0);
  Serial.print(",ALARM="); Serial.print(alarmLatched ? 1 : 0);
  Serial.println(",STATE=IDLE");
  delay(100);
}
`,
  },
  {
    id: 'temp_golden',
    name: 'Dual Heating/Cooling Safety FSM (Golden Reference — 100% Pass)',
    filename: 'temperature_controller.ino',
    category: 'complex_fsm',
    variant: 'fixed',
    description: 'Golden reference implementation for the dual heating/cooling controller. All R1-R6 safety requirements and interlocks satisfied.',
    code: `/*
 * temperature_controller.ino  —  REFERENCE ("golden") IMPLEMENTATION
 *
 * Requirements under test:
 *  R1  The cooling fan SHALL turn ON when temperature is strictly greater
 *      than TEMP_THRESHOLD_C (30 °C) and OFF at or below it.
 *  R2  The red alarm LED SHALL latch ON when temperature reaches or exceeds
 *      TEMP_CRITICAL_C (45 °C) and stay latched until a reset.
 *  R3  The heater SHALL be disabled whenever the fan is running (mutual
 *      exclusion — never heat and cool simultaneously).
 *  R4  The controller SHALL apply HYSTERESIS_C (2 °C) when leaving the
 *      COOLING state to avoid relay chatter around the threshold.
 *  R5  Every control cycle SHALL emit one telemetry line on the UART.
 *  R6  A sensor reading outside [-40, 125] °C SHALL be rejected as a fault.
 */

const int TEMP_SENSOR_PIN = A0;
const int FAN_PIN         = 5;
const int HEATER_PIN      = 6;
const int ALARM_LED_PIN   = 7;
const int STATUS_LED_PIN  = 13;

const float TEMP_LSB_C    = 0.25;
const float TEMP_OFFSET_C = -50.0;

const float TEMP_THRESHOLD_C = 30.0;
const float TEMP_CRITICAL_C  = 45.0;
const float TEMP_TARGET_C    = 22.0;
const float HYSTERESIS_C     = 2.0;
const float TEMP_MIN_VALID_C = -40.0;
const float TEMP_MAX_VALID_C = 125.0;

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

void setup() {
  Serial.begin(9600);
  pinMode(FAN_PIN, OUTPUT);
  pinMode(HEATER_PIN, OUTPUT);
  pinMode(ALARM_LED_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
}

void loop() {
  float temperature = readTemperatureC();

  if (temperature < TEMP_MIN_VALID_C || temperature > TEMP_MAX_VALID_C) {
    currentState = STATE_FAULT;
    fanOn = true;
    heaterOn = false;
  }
  else if (temperature >= TEMP_CRITICAL_C) {
    alarmLatched = true;
    currentState = STATE_CRITICAL;
    fanOn = true;
    heaterOn = false;
  }
  else if (temperature > TEMP_THRESHOLD_C) {
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
    fanOn = false;
    heaterOn = true;
  }
  else {
    currentState = STATE_IDLE;
    fanOn = false;
    heaterOn = false;
  }

  digitalWrite(FAN_PIN, fanOn ? HIGH : LOW);
  digitalWrite(HEATER_PIN, heaterOn ? HIGH : LOW);
  digitalWrite(ALARM_LED_PIN, alarmLatched ? HIGH : LOW);

  Serial.print("TEMP="); Serial.print(temperature, 2);
  Serial.print(",FAN="); Serial.print(fanOn ? 1 : 0);
  Serial.print(",HEATER="); Serial.print(heaterOn ? 1 : 0);
  Serial.print(",ALARM="); Serial.print(alarmLatched ? 1 : 0);
  Serial.println(",STATE=IDLE");
  delay(100);
}
`,
  },
];

export const SAMPLE_BUGGY_FILENAME = FIRMWARE_PRESETS[0].filename;
export const SAMPLE_BUGGY_SOURCE = FIRMWARE_PRESETS[0].code;
