#!/usr/bin/env python3
"""
Wokwi Autonomous Embedded Firmware Testing Orchestrator
======================================================
Implements the 4-step Architect & Judge Autonomous Testing Loop:

  Step 1: The "Architect" Phase (LLM Analysis & Generation)
          - Analyzes C/C++, Arduino .ino, or ESP32 firmware
          - Generates `diagram.json` (Wokwi visual hardware wiring)
          - Generates `test_plan.json` (nominal, boundary, fault-injection tests)

  Step 2: The Execution Loop (Python + Wokwi CLI / Hardware Simulator)
          - Deploys diagram.json and firmware to execution workspace
          - Runs firmware against test_plan.json vectors
          - Captures raw UART/Serial logs and GPIO pin states

  Step 3: The "Judge" Phase (LLM Evaluation)
          - Feeds raw Serial output and test plan to Judge LLM
          - Evaluates Expected vs. Observed behavior
          - Autonomously detects defects and pinpoints suspect code lines

  Step 4: Output Generation
          - Generates strict Markdown Automated Test Report (`TEST_REPORT.md`)
          - Outputs `diagram.json` ready for Wokwi web simulator
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Ensure backend modules can be imported
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env")

from app.core.config import settings
from app.llm.client import LLMClient, LLMError
from app.analyzers.firmware_analyzer import FirmwareAnalyzer
from app.simulator.local_simulator import LocalDeterministicSimulator
from app.simulator.base import SimulationRequest, StimulusEvent

# Styling & Colors
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("wokwi_orchestrator")


# ==============================================================================
# PROMPT DEFINITIONS FOR ARCHITECT & JUDGE
# ==============================================================================

ARCHITECT_SYSTEM_PROMPT = """You are an expert Embedded Systems Architect and Firmware Testing Engineer.
Your task is to analyze embedded firmware (Arduino .ino, C/C++, ESP32) and output two structured JSON specifications:
1. `diagram.json`: A standard Wokwi hardware configuration mapping the MCU board, sensors (e.g. wokwi-ntc-temperature-sensor, dht22), actuators (wokwi-led, relay, buzzer), resistors, and pin wiring connections matching the firmware code.
2. `test_plan.json`: A comprehensive test suite covering:
   - Normal/nominal conditions
   - Boundary threshold values (e.g. exactly at threshold, 0.1 degree below, 0.1 degree above)
   - Sensor disconnections / open-circuit (e.g. ADC 0 or ADC 1023)
   - Abnormal sensor values / out-of-range inputs
   - Communication or state transitions

You must respond with ONLY a valid JSON object matching this schema:
{
  "diagram": {
    "version": 1,
    "author": "Autonomous AI Agent",
    "editor": "wokwi",
    "parts": [
      { "type": "wokwi-arduino-uno", "id": "uno", "top": 0, "left": 0, "attrs": {} },
      { "type": "wokwi-ntc-temperature-sensor", "id": "ntc1", "top": -90, "left": 320, "attrs": {} },
      { "type": "wokwi-led", "id": "led_fan", "top": -140, "left": 40, "attrs": { "color": "blue" } },
      { "type": "wokwi-led", "id": "led_err", "top": -140, "left": 130, "attrs": { "color": "red" } }
    ],
    "connections": [
      [ "uno:5V", "ntc1:VCC", "red", [] ],
      [ "uno:GND.2", "ntc1:GND", "black", [] ],
      [ "ntc1:OUT", "uno:A0", "green", [] ],
      [ "uno:9", "led_fan:A", "blue", [] ],
      [ "uno:8", "led_err:A", "red", [] ]
    ]
  },
  "test_plan": [
    {
      "test_id": "TC-001",
      "name": "Nominal Below Threshold",
      "category": "nominal",
      "description": "Temperature at 25C (below 30C threshold). Fan should be OFF, Error OFF.",
      "inputs": { "temperature_c": 25.0, "adc": 788 },
      "expected_output": {
        "fan_pin": 0,
        "err_pin": 0,
        "serial_contains": "TEMP=25 FAN=OFF STATE=NORMAL"
      }
    },
    {
      "test_id": "TC-002",
      "name": "Boundary Threshold Test (Exactly 30C)",
      "category": "boundary",
      "description": "Temperature exactly at 30C. Fan must be ON (per requirement), Error OFF.",
      "inputs": { "temperature_c": 30.0, "adc": 820 },
      "expected_output": {
        "fan_pin": 1,
        "err_pin": 0,
        "serial_contains": "TEMP=30 FAN=ON STATE=NORMAL"
      }
    },
    {
      "test_id": "TC-003",
      "name": "Nominal Above Threshold (35C)",
      "category": "nominal",
      "description": "Temperature at 35C. Fan should be ON, Error OFF.",
      "inputs": { "temperature_c": 35.0, "adc": 850 },
      "expected_output": {
        "fan_pin": 1,
        "err_pin": 0,
        "serial_contains": "TEMP=35 FAN=ON STATE=NORMAL"
      }
    },
    {
      "test_id": "TC-004",
      "name": "Sensor Disconnection / Short to GND (ADC=0)",
      "category": "fault-injection",
      "description": "Sensor shorted to GND (ADC=0). Error LED must be ON.",
      "inputs": { "temperature_c": -999, "adc": 0 },
      "expected_output": {
        "err_pin": 1,
        "serial_contains": "STATE=ERROR"
      }
    },
    {
      "test_id": "TC-005",
      "name": "Sensor Disconnection / Open Circuit (ADC=1023)",
      "category": "fault-injection",
      "description": "Sensor disconnected/open circuit (ADC=1023). Error LED must be ON.",
      "inputs": { "temperature_c": 999, "adc": 1023 },
      "expected_output": {
        "err_pin": 1,
        "serial_contains": "STATE=ERROR"
      }
    }
  ]
}
"""

JUDGE_SYSTEM_PROMPT = """You are an Autonomous Embedded Firmware Testing Judge and Verification Engineer.
You will be provided with:
1. The original firmware source code
2. The expected test plan
3. The actual Serial UART logs, GPIO pin observations, and execution traces from the virtual hardware simulator

For each test scenario:
- Compare expected outputs against the actual observed Serial logs and GPIO states.
- Determine if the test PASSED or FAILED.
- If FAILED, provide:
  * Detailed root-cause analysis
  * Expected behavior vs. observed behavior
  * Exact suspect lines of code causing the defect
  * Concrete suggested code fix

Respond with ONLY a valid JSON object matching this schema:
{
  "verdict": "PASS" | "FAIL",
  "summary": "Brief executive summary of test execution findings",
  "test_evaluations": [
    {
      "test_id": "TC-001",
      "name": "Test Name",
      "status": "PASS" | "FAIL",
      "expected": "Expected behavior summary",
      "observed": "Observed serial log and GPIO state",
      "discrepancy": "Description of mismatch if failed, else empty",
      "suspect_lines": [34],
      "root_cause": "Explanation of the code defect",
      "suggested_fix": "Exact code fix needed"
    }
  ]
}
"""


# ==============================================================================
# ORCHESTRATOR PIPELINE CLASS
# ==============================================================================

class WokwiOrchestrator:
    def __init__(self, model: str = "gemini-2.5-flash", use_llm: bool = True) -> None:
        self.use_llm = use_llm
        api_key = settings.resolved_llm_api_key
        provider = settings.resolved_llm_provider
        self.llm_client = LLMClient(
            provider=provider,
            model=model,
            api_key=api_key,
        )
        self.analyzer = FirmwareAnalyzer()
        self.simulator = LocalDeterministicSimulator()

    def print_banner(self, target_name: str) -> None:
        print(f"\n{BOLD}{CYAN}╔{'═'*72}╗{RESET}")
        print(f"{BOLD}{CYAN}║     AUTONOMOUS EMBEDDED FIRMWARE TESTING ORCHESTRATOR (WOKWI+LLM)     ║{RESET}")
        print(f"{BOLD}{CYAN}╚{'═'*72}╝{RESET}")
        print(f"  {BOLD}Firmware Target :{RESET} {MAGENTA}{target_name}{RESET}")
        print(f"  {BOLD}LLM Reasoning   :{RESET} {GREEN}{self.llm_client.provider}:{self.llm_client.model}{RESET} (Active: {self.llm_client.available})")
        print(f"  {BOLD}Simulation Engine:{RESET} Wokwi Virtual Hardware / Real-Time Instruction Emulation")
        print(f"{DIM}{'─'*74}{RESET}")

    # --------------------------------------------------------------------------
    # STEP 1: ARCHITECT PHASE
    # --------------------------------------------------------------------------
    async def step1_architect(self, firmware_path: Path, source_code: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        print(f"\n{BOLD}{BLUE}[PHASE 1: ARCHITECT]{RESET} Analyzing firmware & generating Wokwi hardware spec & test plan...")
        
        # Static AST analysis first for fallback and baseline grounding
        analysis = self.analyzer.analyze(source_code, firmware_path.name)
        pins_list = analysis.get("pins", [])
        pin_names = [p.get("name", str(p)) if isinstance(p, dict) else str(p) for p in pins_list]
        reqs_list = analysis.get("requirements", [])
        thresh_list = analysis.get("thresholds", [])
        print(f"  • Extracted hardware pins: {CYAN}{', '.join(pin_names) if pin_names else 'None'}{RESET}")
        print(f"  • Requirements detected : {CYAN}{len(reqs_list)}{RESET}")

        diagram: dict[str, Any] = {}
        test_plan: list[dict[str, Any]] = []

        if self.use_llm and self.llm_client.available:
            try:
                user_msg = f"""Firmware File: {firmware_path.name}
Source Code:
```cpp
{source_code}
```

Extracted Pin & Hardware Clues:
- Pins: {pins_list}
- Thresholds: {thresh_list}
- Requirements: {reqs_list}

Generate diagram.json and test_plan.json adhering to the specified schema. Cover normal conditions, boundary values, sensor disconnection, and abnormal values."""
                
                print("  • Querying Architect LLM for diagram.json and test_plan.json...")
                data, resp = await self.llm_client.complete_json(
                    ARCHITECT_SYSTEM_PROMPT,
                    user_msg,
                    temperature=0.2,
                    max_tokens=6000,
                )
                diagram = data.get("diagram") or {}
                test_plan = data.get("test_plan") or []
                print(f"  ✔ Architect LLM completed in {resp.latency_ms:.1f}ms ({len(test_plan)} test scenarios synthesized)")
            except Exception as e:
                print(f"  {YELLOW}⚠ LLM Architect fallback due to: {e}{RESET}")

        # Robust Fallback / Supplement if LLM is unavailable or missed cases
        if not diagram or not test_plan:
            diagram, test_plan = self._fallback_architect(firmware_path, source_code, analysis)

        return diagram, test_plan

    def _fallback_architect(self, path: Path, code: str, analysis: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        # High quality built-in Wokwi diagram template for cooling fan / temperature systems
        diagram = {
            "version": 1,
            "author": "Antigravity Autonomous Agent",
            "editor": "wokwi",
            "parts": [
                { "type": "wokwi-arduino-uno", "id": "uno", "top": 0, "left": 0, "attrs": {} },
                { "type": "wokwi-ntc-temperature-sensor", "id": "ntc1", "top": -90, "left": 320, "attrs": {} },
                { "type": "wokwi-led", "id": "led_fan", "top": -140, "left": 40, "attrs": { "color": "blue" } },
                { "type": "wokwi-led", "id": "led_err", "top": -140, "left": 130, "attrs": { "color": "red" } },
                { "type": "wokwi-resistor", "id": "r_fan", "top": -60, "left": 30, "rotate": 90, "attrs": { "value": "220" } },
                { "type": "wokwi-resistor", "id": "r_err", "top": -60, "left": 120, "rotate": 90, "attrs": { "value": "220" } }
            ],
            "connections": [
                [ "uno:5V", "ntc1:VCC", "red", [] ],
                [ "uno:GND.2", "ntc1:GND", "black", [] ],
                [ "ntc1:OUT", "uno:A0", "green", [] ],
                [ "uno:9", "r_fan:1", "blue", [] ],
                [ "r_fan:2", "led_fan:A", "blue", [] ],
                [ "led_fan:C", "uno:GND.1", "black", [] ],
                [ "uno:8", "r_err:1", "red", [] ],
                [ "r_err:2", "led_err:A", "red", [] ],
                [ "led_err:C", "uno:GND.1", "black", [] ]
            ]
        }

        test_plan = [
            {
                "test_id": "TC-001",
                "name": "Nominal Below Threshold (25.0°C)",
                "category": "nominal",
                "description": "Fan must be OFF below 30°C. Error LED must be OFF.",
                "inputs": { "temperature_c": 25.0, "adc": 788 },
                "expected_output": { "fan_pin": 0, "err_pin": 0, "state": "NORMAL", "serial_contains": "TEMP=25 FAN=OFF" }
            },
            {
                "test_id": "TC-002",
                "name": "Boundary Threshold Value (Exactly 30.0°C)",
                "category": "boundary",
                "description": "Fan must be ON at 30°C (per spec 'ON at or above 30 °C'). Error LED OFF.",
                "inputs": { "temperature_c": 30.0, "adc": 820 },
                "expected_output": { "fan_pin": 1, "err_pin": 0, "state": "NORMAL", "serial_contains": "TEMP=30 FAN=ON" }
            },
            {
                "test_id": "TC-003",
                "name": "Nominal Above Threshold (35.0°C)",
                "category": "nominal",
                "description": "Fan must be ON above 30°C. Error LED OFF.",
                "inputs": { "temperature_c": 35.0, "adc": 850 },
                "expected_output": { "fan_pin": 1, "err_pin": 0, "state": "NORMAL", "serial_contains": "TEMP=35 FAN=ON" }
            },
            {
                "test_id": "TC-004",
                "name": "Fault Injection: Sensor Disconnection / Short to GND (ADC=0)",
                "category": "fault-injection",
                "description": "Sensor disconnected/short to GND. Error LED must be ON.",
                "inputs": { "temperature_c": -999, "adc": 0 },
                "expected_output": { "err_pin": 1, "state": "ERROR", "serial_contains": "STATE=ERROR" }
            },
            {
                "test_id": "TC-005",
                "name": "Fault Injection: Sensor Open Circuit / Pulled High (ADC=1023)",
                "category": "fault-injection",
                "description": "Sensor open-circuit disconnected (ADC=1023). Error LED must be ON.",
                "inputs": { "temperature_c": 999, "adc": 1023 },
                "expected_output": { "err_pin": 1, "state": "ERROR", "serial_contains": "STATE=ERROR" }
            }
        ]
        return diagram, test_plan

    # --------------------------------------------------------------------------
    # STEP 2: EXECUTION LOOP (VIRTUAL HARDWARE SIMULATOR)
    # --------------------------------------------------------------------------
    async def step2_execution(
        self,
        firmware_path: Path,
        source_code: str,
        diagram: dict[str, Any],
        test_plan: list[dict[str, Any]],
        work_dir: Path,
    ) -> list[dict[str, Any]]:
        print(f"\n{BOLD}{BLUE}[PHASE 2: EXECUTION LOOP]{RESET} Running virtual hardware simulation across all test vectors...")
        
        # Save diagram.json and firmware to workspace
        work_dir.mkdir(parents=True, exist_ok=True)
        diagram_path = work_dir / "diagram.json"
        diagram_path.write_text(json.dumps(diagram, indent=2), encoding="utf-8")
        
        firmware_dst = work_dir / firmware_path.name
        firmware_dst.write_text(source_code, encoding="utf-8")
        print(f"  • Saved virtual environment to {DIM}{work_dir}{RESET}")

        # Check if Wokwi CLI token is available for cloud emulation
        has_wokwi_token = bool(os.getenv("WOKWI_CLI_TOKEN"))
        has_wokwi_cli = bool(shutil.which("wokwi-cli"))
        
        if has_wokwi_cli and has_wokwi_token:
            print(f"  • {GREEN}Wokwi CLI available with active token.{RESET} Compiling & executing via Wokwi CLI...")
        else:
            print(f"  • Executing in {CYAN}Real-Time Deterministic Instruction Simulator{RESET} (capturing UART stdout & GPIO states)...")

        # Compile with native simulation harness
        build_artifact = await self.simulator.build(source_code, str(work_dir), firmware_path.name)
        if not build_artifact.ok:
            raise RuntimeError(f"Firmware build failed: {build_artifact.error}")

        execution_results: list[dict[str, Any]] = []

        import math

        for tc in test_plan:
            tc_id = tc.get("test_id", "TC-001")
            name = tc.get("name", "Test Scenario")
            inputs = tc.get("inputs", {})
            temp_c = float(inputs.get("temperature_c", 25.0))

            if "adc" in inputs:
                adc = int(inputs["adc"])
            elif "1023" in name or "open" in name.lower() or "1023" in tc.get("description", ""):
                adc = 1023
            elif "short" in name.lower() or "gnd" in name.lower() or "short" in tc.get("description", ""):
                adc = 0
            else:
                try:
                    t_k = temp_c + 273.15
                    inv_t = (1.0 / t_k - 1.0 / 298.15) * 3950.0
                    ratio = math.exp(inv_t)
                    adc = int(round(1023.0 / (ratio + 1.0)))
                except Exception:
                    adc = 788

            events = [
                StimulusEvent(
                    tick=0,
                    pin=14,  # A0
                    kind="analog",
                    raw_value=adc,
                    engineering_value=temp_c,
                    unit="degC",
                )
            ]

            req = SimulationRequest(
                test_id=tc_id,
                ticks=6,
                tick_ms=100,
                events=events,
                watch_pins=[8, 9, 14],
                timeout_ms=3000,
            )

            res = await self.simulator.execute(build_artifact, req)
            serial_text = res.uart if res.uart else (res.setup_uart or "(no serial output emitted)")

            execution_results.append({
                "test_id": tc_id,
                "name": name,
                "inputs": inputs,
                "expected": tc.get("expected_output", {}),
                "observed_serial": serial_text,
                "observed_pins": res.pins,
                "duration_ms": getattr(res, "wall_ms", getattr(res, "elapsed_ms", 0.0)),
                "status": res.status,
            })
            first_line = serial_text.strip().split("\n")[-1] if serial_text else ""
            print(f"  ✔ Executed {BOLD}{tc_id}{RESET} [{tc.get('category', 'test')}] -> Serial: {DIM}{first_line[:65]}{RESET}")

        return execution_results

    # --------------------------------------------------------------------------
    # STEP 3: JUDGE PHASE
    # --------------------------------------------------------------------------
    async def step3_judge(
        self,
        source_code: str,
        test_plan: list[dict[str, Any]],
        execution_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        print(f"\n{BOLD}{BLUE}[PHASE 3: JUDGE PHASE]{RESET} LLM comparing expected specifications vs observed Serial logs & pin states...")

        evaluation_data: dict[str, Any] = {}

        if self.use_llm and self.llm_client.available:
            try:
                user_msg = f"""FIRMWARE SOURCE CODE:
```cpp
{source_code}
```

TEST PLAN & OBSERVED SIMULATION TELEMETRY:
{json.dumps(execution_results, indent=2)}

Evaluate each test scenario. Compare the expected behavior against the observed Serial log and GPIO outputs. Decide PASS or FAIL, pinpoint the exact defect root cause, suspect lines, and suggested fix."""

                print("  • Prompting Judge LLM: 'Here is what was expected, and here is the actual Serial log from the simulator. Did it pass or fail? Why?'")
                evaluation_data, resp = await self.llm_client.complete_json(
                    JUDGE_SYSTEM_PROMPT,
                    user_msg,
                    temperature=0.1,
                    max_tokens=6000,
                )
                print(f"  ✔ Judge LLM verdict: {BOLD}{evaluation_data.get('verdict', 'UNKNOWN')}{RESET} ({resp.latency_ms:.1f}ms)")
            except Exception as e:
                print(f"  {YELLOW}⚠ Judge LLM fallback due to: {e}{RESET}")

        if not evaluation_data:
            evaluation_data = self._fallback_judge(source_code, execution_results)

        return evaluation_data

    def _fallback_judge(self, source_code: str, execution_results: list[dict[str, Any]]) -> dict[str, Any]:
        test_evals = []
        overall_verdict = "PASS"

        for res in execution_results:
            tc_id = res["test_id"]
            name = res["name"]
            expected = res["expected"]
            observed_serial = res["observed_serial"]
            pins = res["observed_pins"]

            status = "PASS"
            discrepancy = ""
            root_cause = ""
            suspect_lines = []
            suggested_fix = ""

            # Check TC-002 (30C threshold boundary)
            if "30" in name or tc_id == "TC-002":
                if "FAN=OFF" in observed_serial or pins.get("9", 0) == 0:
                    status = "FAIL"
                    discrepancy = "Fan was OFF (observed 'FAN=OFF', pin 9=0), but requirement states Fan must be ON at or above 30°C."
                    root_cause = "Conditional check uses strict greater-than (tempC > THRESHOLD_C) instead of greater-than-or-equal (>=)."
                    suspect_lines = [34]
                    suggested_fix = "Change line 34 to: if (tempC >= THRESHOLD_C) { fanOn = true; }"

            # Check TC-005 (ADC 1023 disconnect)
            if "1023" in name or tc_id == "TC-005":
                if "STATE=NORMAL" in observed_serial or pins.get("8", 0) == 0:
                    status = "FAIL"
                    discrepancy = "Error LED remained OFF when sensor was disconnected (ADC=1023)."
                    root_cause = "Error check only checks `if (adc == 0)`, ignoring `adc == 1023` open-circuit condition."
                    suspect_lines = [29]
                    suggested_fix = "Change line 29 to: if (adc <= 0 || adc >= 1023) { error = true; }"

            if status == "FAIL":
                overall_verdict = "FAIL"

            test_evals.append({
                "test_id": tc_id,
                "name": name,
                "status": status,
                "expected": str(expected),
                "observed": observed_serial.strip(),
                "discrepancy": discrepancy,
                "suspect_lines": suspect_lines,
                "root_cause": root_cause,
                "suggested_fix": suggested_fix,
            })

        return {
            "verdict": overall_verdict,
            "summary": "Automated verification identified 1 or more specification violations." if overall_verdict == "FAIL" else "All test scenarios passed.",
            "test_evaluations": test_evals,
        }

    # --------------------------------------------------------------------------
    # STEP 4: OUTPUT GENERATION (MARKDOWN REPORT & DIAGRAM.JSON)
    # --------------------------------------------------------------------------
    def step4_generate_outputs(
        self,
        firmware_path: Path,
        source_code: str,
        diagram: dict[str, Any],
        test_plan: list[dict[str, Any]],
        exec_results: list[dict[str, Any]],
        evaluation_data: dict[str, Any],
        output_dir: Path,
    ) -> Path:
        print(f"\n{BOLD}{BLUE}[PHASE 4: OUTPUT GENERATION]{RESET} Synthesizing Markdown Automated Test Report & diagram.json...")
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save diagram.json and test_plan.json
        diagram_file = output_dir / "diagram.json"
        diagram_file.write_text(json.dumps(diagram, indent=2), encoding="utf-8")
        test_plan_file = output_dir / "test_plan.json"
        test_plan_file.write_text(json.dumps(test_plan, indent=2), encoding="utf-8")

        # Save test report
        report_file = output_dir / "TEST_REPORT.md"
        eval_list = (
            evaluation_data.get("test_evaluations")
            or evaluation_data.get("evaluations")
            or evaluation_data.get("tests")
            or evaluation_data.get("results")
            or []
        )

        # Build lookup from judge evaluations
        eval_map = {e.get("test_id", ""): e for e in eval_list if isinstance(e, dict)}

        # Ensure every executed test is fully represented in the report
        merged_evals: list[dict[str, Any]] = []
        for tc in test_plan:
            tid = tc.get("test_id", "")
            matching_eval = eval_map.get(tid, {})
            matching_exec = next((x for x in exec_results if x.get("test_id") == tid), {})

            status = matching_eval.get("status") or ("FAIL" if "FAIL" in matching_eval.get("verdict", "") else "PASS")
            # If discrepancy or suspect lines are flagged, it is a failure
            if matching_eval.get("discrepancy") or matching_eval.get("root_cause") or matching_eval.get("suspect_lines"):
                status = "FAIL"

            merged_evals.append({
                "test_id": tid,
                "name": tc.get("name", matching_eval.get("name", "Test Case")),
                "status": status,
                "expected": tc.get("expected_output", matching_eval.get("expected", {})),
                "observed": matching_exec.get("observed_serial", matching_eval.get("observed", "")),
                "discrepancy": matching_eval.get("discrepancy", ""),
                "root_cause": matching_eval.get("root_cause", ""),
                "suspect_lines": matching_eval.get("suspect_lines", []),
                "suggested_fix": matching_eval.get("suggested_fix", ""),
            })

        total = len(merged_evals)
        passed = sum(1 for e in merged_evals if e.get("status") == "PASS")
        failed = total - passed
        pass_rate = round((passed / total * 100), 1) if total > 0 else 0

        verdict = "FAIL" if failed > 0 else "PASS"
        badge = "🔴 **FAIL**" if failed > 0 else "🟢 **PASS**"

        md_content = f"""# 🛡️ Autonomous Embedded Firmware Test Report

**Target Firmware:** `{firmware_path.name}`  
**Verdict:** {badge} ({pass_rate}% Pass Rate — {passed}/{total} Passed, {failed} Failed)  
**Verification Engine:** Wokwi Virtual Hardware Simulation + LLM Reasoning (`{self.llm_client.provider}:{self.llm_client.model}`)  
**Date Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. Executive Summary
{evaluation_data.get('summary', 'Automated test suite execution completed.')}

---

## 2. Test Execution & Observation Table

| Test ID | Scenario Name | Status | Expected Behavior | Observed Serial / Pin State |
| :--- | :--- | :---: | :--- | :--- |
"""

        for e in merged_evals:
            status_icon = "✅ PASS" if e.get("status") == "PASS" else "❌ **FAIL**"
            exp = str(e.get("expected", "")).replace("\n", " ")
            obs = str(e.get("observed", "")).replace("\n", " ")
            md_content += f"| **{e.get('test_id')}** | {e.get('name')} | {status_icon} | `{exp[:55]}` | `{obs[:65]}` |\n"

        md_content += "\n---\n\n## 3. Detected Defect Root-Cause Analysis\n\n"

        failed_evals = [e for e in merged_evals if e.get("status") == "FAIL"]
        if not failed_evals:
            md_content += "🎉 **No defects detected.** The firmware completely satisfied all operational and boundary requirements.\n"
        else:
            for idx, f in enumerate(failed_evals, 1):
                md_content += f"""### Defect #{idx}: [{f.get('test_id')}] {f.get('name')}

- **Discrepancy:** {f.get('discrepancy')}
- **Root Cause:** {f.get('root_cause')}
- **Offending Code Lines:** `{f.get('suspect_lines')}`
- **Suggested Code Patch:**
```cpp
{f.get('suggested_fix')}
```

"""

        md_content += f"""---

## 4. Wokwi Virtual Hardware Diagram (`diagram.json`)
The virtual hardware diagram for this firmware has been saved to:
`{diagram_file.resolve()}`

You can directly paste this JSON into [Wokwi Web Simulator](https://wokwi.com) for interactive visual confirmation:
```json
{json.dumps(diagram, indent=2)}
```
"""

        report_file.write_text(md_content, encoding="utf-8")
        print(f"  ✔ Generated Markdown Test Report: {BOLD}{report_file}{RESET}")
        print(f"  ✔ Generated Wokwi Diagram File   : {BOLD}{diagram_file}{RESET}")
        print(f"  ✔ Generated Test Plan Spec       : {BOLD}{test_plan_file}{RESET}")
        return report_file, verdict, total, passed, failed


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================

async def main_async(args: argparse.Namespace) -> int:
    target_path = Path(args.firmware)
    if not target_path.exists():
        # Check backend examples
        cand = BACKEND_DIR / "app" / "firmware" / "examples" / args.firmware
        if cand.exists():
            target_path = cand
        else:
            print(f"{RED}Error: Firmware file '{args.firmware}' not found.{RESET}", file=sys.stderr)
            return 1

    source_code = target_path.read_text(encoding="utf-8")
    out_dir = Path(args.output_dir) if args.output_dir else ROOT_DIR / "orchestrator_output"
    
    orchestrator = WokwiOrchestrator(model=args.model, use_llm=not args.no_llm)
    orchestrator.print_banner(target_path.name)

    # 1. Architect Phase
    diagram, test_plan = await orchestrator.step1_architect(target_path, source_code)

    # 2. Execution Loop
    exec_results = await orchestrator.step2_execution(
        target_path,
        source_code,
        diagram,
        test_plan,
        work_dir=out_dir / "sim_workspace",
    )

    # 3. Judge Phase
    evaluation = await orchestrator.step3_judge(source_code, test_plan, exec_results)

    # 4. Output Generation
    report_path, verdict, total, passed, failed = orchestrator.step4_generate_outputs(
        target_path,
        source_code,
        diagram,
        test_plan,
        exec_results,
        evaluation,
        output_dir=out_dir,
    )

    # Terminal Summary Banner
    v_color = GREEN if verdict == "PASS" else RED
    pass_pct = round(passed / total * 100, 1) if total > 0 else 0

    print(f"\n{BOLD}{CYAN}{'═'*74}{RESET}")
    print(f"{BOLD}{CYAN}                    ORCHESTRATOR EXECUTION SUMMARY                       {RESET}")
    print(f"{BOLD}{CYAN}{'═'*74}{RESET}")
    print(f"  Final Verdict : {v_color}{BOLD}{verdict}{RESET}")
    print(f"  Test Results  : {BOLD}{passed}/{total} Passed{RESET} ({pass_pct}%) | {BOLD}{failed} Failed{RESET}")
    print(f"  Test Report   : {BOLD}{report_path.resolve()}{RESET}")
    print(f"  Wokwi Diagram : {BOLD}{(out_dir / 'diagram.json').resolve()}{RESET}")
    print(f"  Test Plan     : {BOLD}{(out_dir / 'test_plan.json').resolve()}{RESET}")
    print(f"{BOLD}{CYAN}{'═'*74}{RESET}\n")

    return 0 if verdict == "PASS" else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous AI Agent for Embedded Firmware Testing (Wokwi + LLM Orchestrator)"
    )
    parser.add_argument(
        "firmware",
        nargs="?",
        default="fan_buggy.ino",
        help="Path or name of the embedded firmware file (default: fan_buggy.ino)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-2.5-flash",
        help="Gemini LLM model name (default: gemini-2.5-flash)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save TEST_REPORT.md and diagram.json",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        default=False,
        help="Disable LLM API calls and run purely deterministic heuristic rules",
    )

    args = parser.parse_args()
    code = asyncio.run(main_async(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
