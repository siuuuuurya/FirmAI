// Cooling fan controller (BUGGY VERSION - contains 2 planted bugs)
// Sensor: NTC thermistor on A0 | Fan LED: pin 9 | Error LED: pin 8

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

  if (adc == 0) {                     // BUG 2: does not check adc == 1023
    error = true;
  } else {
    float t = 1.0 / (log(1.0 / (1023.0 / adc - 1.0)) / BETA + 1.0 / 298.15) - 273.15;
    tempC = (int)(t + 0.5);           // round to nearest degree
    if (tempC > THRESHOLD_C) {        // BUG 1: should be >= (spec: ON at 30C)
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
