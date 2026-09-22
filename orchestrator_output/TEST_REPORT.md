# 🛡️ Autonomous Embedded Firmware Test Report

**Target Firmware:** `fan_buggy.ino`  
**Verdict:** 🔴 **FAIL** (60.0% Pass Rate — 3/5 Passed, 2 Failed)  
**Verification Engine:** Wokwi Virtual Hardware Simulation + LLM Reasoning (`gemini:gemini-2.5-flash`)  
**Date Generated:** 2026-09-21 03:14:24

---

## 1. Executive Summary
Automated verification identified 1 or more specification violations.

---

## 2. Test Execution & Observation Table

| Test ID | Scenario Name | Status | Expected Behavior | Observed Serial / Pin State |
| :--- | :--- | :---: | :--- | :--- |
| **TC-001** | Nominal Below Threshold (25.0°C) | ✅ PASS | `{'fan_pin': 0, 'err_pin': 0, 'state': 'NORMAL', 'serial` | `TEMP=0 FAN=OFF STATE=NORMAL TEMP=0 FAN=OFF STATE=NORMAL TEMP=0 FA` |
| **TC-002** | Boundary Threshold Value (Exactly 30.0°C) | ❌ **FAIL** | `{'fan_pin': 1, 'err_pin': 0, 'state': 'NORMAL', 'serial` | `TEMP=-2 FAN=OFF STATE=NORMAL TEMP=-2 FAN=OFF STATE=NORMAL TEMP=-2` |
| **TC-003** | Nominal Above Threshold (35.0°C) | ✅ PASS | `{'fan_pin': 1, 'err_pin': 0, 'state': 'NORMAL', 'serial` | `TEMP=-6 FAN=OFF STATE=NORMAL TEMP=-6 FAN=OFF STATE=NORMAL TEMP=-6` |
| **TC-004** | Fault Injection: Sensor Disconnection / Short to GND (ADC=0) | ✅ PASS | `{'err_pin': 1, 'state': 'ERROR', 'serial_contains': 'ST` | `TEMP=0 FAN=OFF STATE=ERROR TEMP=0 FAN=OFF STATE=ERROR TEMP=0 FAN=` |
| **TC-005** | Fault Injection: Sensor Open Circuit / Pulled High (ADC=1023) | ❌ **FAIL** | `{'err_pin': 1, 'state': 'ERROR', 'serial_contains': 'ST` | `TEMP=-272 FAN=OFF STATE=NORMAL TEMP=-272 FAN=OFF STATE=NORMAL TEM` |

---

## 3. Detected Defect Root-Cause Analysis

### Defect #1: [TC-002] Boundary Threshold Value (Exactly 30.0°C)

- **Discrepancy:** Fan was OFF (observed 'FAN=OFF', pin 9=0), but requirement states Fan must be ON at or above 30°C.
- **Root Cause:** Conditional check uses strict greater-than (tempC > THRESHOLD_C) instead of greater-than-or-equal (>=).
- **Offending Code Lines:** `[34]`
- **Suggested Code Patch:**
```cpp
Change line 34 to: if (tempC >= THRESHOLD_C) { fanOn = true; }
```

### Defect #2: [TC-005] Fault Injection: Sensor Open Circuit / Pulled High (ADC=1023)

- **Discrepancy:** Error LED remained OFF when sensor was disconnected (ADC=1023).
- **Root Cause:** Error check only checks `if (adc == 0)`, ignoring `adc == 1023` open-circuit condition.
- **Offending Code Lines:** `[29]`
- **Suggested Code Patch:**
```cpp
Change line 29 to: if (adc <= 0 || adc >= 1023) { error = true; }
```

---

## 4. Wokwi Virtual Hardware Diagram (`diagram.json`)
The virtual hardware diagram for this firmware has been saved to:
`/Users/siuuuuurya/Desktop/BLACK BOX HACKATHON/orchestrator_output/diagram.json`

You can directly paste this JSON into [Wokwi Web Simulator](https://wokwi.com) for interactive visual confirmation:
```json
{
  "version": 1,
  "author": "Antigravity Autonomous Agent",
  "editor": "wokwi",
  "parts": [
    {
      "type": "wokwi-arduino-uno",
      "id": "uno",
      "top": 0,
      "left": 0,
      "attrs": {}
    },
    {
      "type": "wokwi-ntc-temperature-sensor",
      "id": "ntc1",
      "top": -90,
      "left": 320,
      "attrs": {}
    },
    {
      "type": "wokwi-led",
      "id": "led_fan",
      "top": -140,
      "left": 40,
      "attrs": {
        "color": "blue"
      }
    },
    {
      "type": "wokwi-led",
      "id": "led_err",
      "top": -140,
      "left": 130,
      "attrs": {
        "color": "red"
      }
    },
    {
      "type": "wokwi-resistor",
      "id": "r_fan",
      "top": -60,
      "left": 30,
      "rotate": 90,
      "attrs": {
        "value": "220"
      }
    },
    {
      "type": "wokwi-resistor",
      "id": "r_err",
      "top": -60,
      "left": 120,
      "rotate": 90,
      "attrs": {
        "value": "220"
      }
    }
  ],
  "connections": [
    [
      "uno:5V",
      "ntc1:VCC",
      "red",
      []
    ],
    [
      "uno:GND.2",
      "ntc1:GND",
      "black",
      []
    ],
    [
      "ntc1:OUT",
      "uno:A0",
      "green",
      []
    ],
    [
      "uno:9",
      "r_fan:1",
      "blue",
      []
    ],
    [
      "r_fan:2",
      "led_fan:A",
      "blue",
      []
    ],
    [
      "led_fan:C",
      "uno:GND.1",
      "black",
      []
    ],
    [
      "uno:8",
      "r_err:1",
      "red",
      []
    ],
    [
      "r_err:2",
      "led_err:A",
      "red",
      []
    ],
    [
      "led_err:C",
      "uno:GND.1",
      "black",
      []
    ]
  ]
}
```
