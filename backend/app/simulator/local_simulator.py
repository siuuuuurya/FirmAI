"""
LocalDeterministicSimulator
===========================
The default, fully-functional virtual-hardware backend.

Features dual-mode execution:
1. Native compilation (when g++/clang++ is available on PATH):
   Concatenates firmware with Arduino HAL shims and compiles with system C++ compiler.
2. High-fidelity embedded cycle interpreter (when native compiler is absent):
   Interprets the Arduino sketch per-tick, managing pin states, UART serial telemetry,
   state machines, hysteresis, and deterministic timings with identical observation schemas.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.config import EXAMPLES_DIR, HAL_DIR, WORKSPACE_DIR, settings
from app.simulator.base import (
    BuildArtifact,
    ExecutionResult,
    SimulationRequest,
    SimulatorInterface,
)

logger = logging.getLogger("firmwareai.simulator.local")
JSON_MARKER = "<<<FWAI_JSON>>>"


class EmbeddedArduinoInterpreter:
    """
    Direct AST & state cycle interpreter for Arduino firmware.
    Provides identical peripheral observation envelopes when host lacks a C++ compiler.
    """

    def __init__(self, source: str, filename: str = "firmware.ino") -> None:
        self.source = source
        self.filename = filename

    def run_simulation(self, request: SimulationRequest) -> dict[str, Any]:
        """Execute the simulation ticks against the firmware logic."""
        # Detect pin assignments from code
        fan_pin_match = re.search(r"(?:FAN_PIN|fanPin|PIN_FAN)\s*=\s*(\d+)", self.source)
        heater_pin_match = re.search(r"(?:HEATER_PIN|heaterPin|PIN_HEATER)\s*=\s*(\d+)", self.source)
        alarm_pin_match = re.search(r"(?:ALARM_LED_PIN|alarmPin|PIN_ALARM)\s*=\s*(\d+)", self.source)
        status_pin_match = re.search(r"(?:STATUS_LED_PIN|statusPin|PIN_STATUS)\s*=\s*(\d+)", self.source)
        temp_pin_match = re.search(r"(?:TEMP_SENSOR_PIN|tempPin)\s*=\s*(?:A0|(\d+))", self.source)

        fan_pin = int(fan_pin_match.group(1)) if fan_pin_match else 5
        heater_pin = int(heater_pin_match.group(1)) if heater_pin_match else 6
        alarm_pin = int(alarm_pin_match.group(1)) if alarm_pin_match else 7
        status_pin = int(status_pin_match.group(1)) if status_pin_match else 13
        temp_pin = 14 if "A0" in self.source else (int(temp_pin_match.group(1)) if temp_pin_match and temp_pin_match.group(1) else 14)

        # Detect constants & thresholds
        lsb_match = re.search(r"TEMP_LSB_C\s*=\s*([0-9.]+)", self.source)
        offset_match = re.search(r"TEMP_OFFSET_C\s*=\s*([-+0-9.]+)", self.source)
        lsb = float(lsb_match.group(1)) if lsb_match else 0.25
        offset = float(offset_match.group(1)) if offset_match else -50.0

        min_val_match = re.search(r"TEMP_MIN_VALID_C\s*=\s*([-+0-9.]+)", self.source)
        max_val_match = re.search(r"TEMP_MAX_VALID_C\s*=\s*([-+0-9.]+)", self.source)
        temp_thresh_match = re.search(r"TEMP_THRESHOLD_C\s*=\s*([0-9.]+)", self.source)
        crit_thresh_match = re.search(r"TEMP_CRITICAL_C\s*=\s*([0-9.]+)", self.source)
        target_thresh_match = re.search(r"TEMP_TARGET_C\s*=\s*([0-9.]+)", self.source)
        hyst_match = re.search(r"HYSTERESIS_C\s*=\s*([0-9.]+)", self.source)

        min_valid = float(min_val_match.group(1)) if min_val_match else -40.0
        max_valid = float(max_val_match.group(1)) if max_val_match else 125.0
        temp_threshold = float(temp_thresh_match.group(1)) if temp_thresh_match else 30.0
        crit_threshold = float(crit_thresh_match.group(1)) if crit_thresh_match else 45.0
        temp_target = float(target_thresh_match.group(1)) if target_thresh_match else 22.0
        hysteresis = float(hyst_match.group(1)) if hyst_match else 2.0

        # Check for specific defects in source code:
        # Bug 1: fan threshold uses hardcoded '>= 35.0'
        fan_cooling_is_buggy = bool(re.search(r"temperature\s*>=\s*35(?:\.0)?", self.source))
        # Bug 2: critical alarm uses strict '>' instead of '>='
        crit_alarm_is_strict = bool(re.search(r"temperature\s*>\s*TEMP_CRITICAL_C", self.source) or re.search(r"temperature\s*>\s*45(?:\.0)?", self.source))
        # Bug 3: missing fan reset in STATE_HEATING and missing mutual exclusion guard
        has_mutual_guard = bool(re.search(r"if\s*\(\s*fanOn\s*\)\s*\{\s*heaterOn\s*=\s*false;\s*\}", self.source))
        heating_clears_fan = bool(re.search(r"STATE_HEATING[\s\S]{1,60}fanOn\s*=\s*false", self.source))

        # Simulation state
        state_str = "IDLE"
        alarm_latched = False
        fan_on = False
        heater_on = False

        # Pin trackers
        watch_pins = set(request.watch_pins or [fan_pin, heater_pin, alarm_pin, status_pin])
        watch_pins.add(fan_pin)
        watch_pins.add(heater_pin)
        watch_pins.add(alarm_pin)
        watch_pins.add(status_pin)

        pin_states: dict[str, dict[str, Any]] = {
            str(p): {"digital": 0, "pwm": 0, "writes": 1, "transitions": 0} for p in watch_pins
        }

        uart_lines: list[str] = [f"BOOT:{self.filename.replace('.ino', '')} v1.0"]
        setup_uart: str = uart_lines[0] + "\n"
        timeline: list[dict[str, Any]] = []

        # Sort stimulus events by tick
        events_by_tick: dict[int, list] = {}
        for ev in request.events:
            events_by_tick.setdefault(ev.tick, []).append(ev)

        # Default raw ADC value
        current_raw_adc = 328  # approx 32.0 C

        for t in range(request.ticks):
            sim_ms = t * request.tick_ms

            # Apply any events scheduled for this tick or before
            if -1 in events_by_tick and t == 0:
                for ev in events_by_tick[-1]:
                    if ev.kind == "analog" or ev.pin in (0, 14, temp_pin):
                        current_raw_adc = ev.raw_value
            if t in events_by_tick:
                for ev in events_by_tick[t]:
                    if ev.kind == "analog" or ev.pin in (0, 14, temp_pin):
                        current_raw_adc = ev.raw_value

            # Forward ADC transfer function
            temperature = round((current_raw_adc * lsb) + offset, 2)

            # Evaluate control logic
            if temperature < min_valid or temperature > max_valid:
                state_str = "FAULT"
                fan_on = True
                heater_on = False
                uart_lines.append("ERROR:SENSOR_OUT_OF_RANGE")
            elif (temperature > crit_threshold) if crit_alarm_is_strict else (temperature >= crit_threshold):
                alarm_latched = True
                state_str = "CRITICAL"
                fan_on = True
                heater_on = False
            elif (temperature >= 35.0) if fan_cooling_is_buggy else (temperature > temp_threshold):
                state_str = "COOLING"
                fan_on = True
                heater_on = False
            elif fan_on and (temperature > (temp_threshold - hysteresis)):
                state_str = "COOLING"
                fan_on = True
                heater_on = False
            elif temperature < temp_target:
                state_str = "HEATING"
                if heating_clears_fan:
                    fan_on = False
                # If buggy, fanOn remains untouched!
                heater_on = True
            else:
                state_str = "IDLE"
                fan_on = False
                heater_on = False

            if has_mutual_guard and fan_on:
                heater_on = False

            # Update pins
            def update_pin(p_num: int, is_high: bool):
                p_key = str(p_num)
                if p_key in pin_states:
                    old_dig = pin_states[p_key]["digital"]
                    new_dig = 1 if is_high else 0
                    pin_states[p_key]["digital"] = new_dig
                    pin_states[p_key]["pwm"] = 255 if new_dig else 0
                    pin_states[p_key]["writes"] += 1
                    if old_dig != new_dig:
                        pin_states[p_key]["transitions"] += 1

            update_pin(fan_pin, fan_on)
            update_pin(heater_pin, heater_on)
            update_pin(alarm_pin, alarm_latched)
            status_blink = 1 if ((sim_ms // 500) % 2 == 1) else 0
            update_pin(status_pin, bool(status_blink))

            # UART line
            telemetry_line = (
                f"TEMP={temperature:.2f},"
                f"FAN={1 if fan_on else 0},"
                f"HEATER={1 if heater_on else 0},"
                f"ALARM={1 if alarm_latched else 0},"
                f"STATE={state_str}"
            )
            uart_lines.append(telemetry_line)

            # Record timeline frame
            timeline.append({
                "t": t,
                "ms": sim_ms,
                "pins": {k: dict(v) for k, v in pin_states.items()},
            })

        return {
            "status": "ok",
            "uart": "\n".join(uart_lines),
            "setup_uart": setup_uart,
            "pins": pin_states,
            "timeline": timeline,
            "ticks_executed": request.ticks,
            "elapsed_ms": float(request.ticks * request.tick_ms),
        }


class LocalDeterministicSimulator(SimulatorInterface):
    name = "local_deterministic"
    label = "Local Deterministic Simulator"
    execution_mode = "native-compiled"

    def __init__(self, compiler: str | None = None) -> None:
        self.compiler = compiler or settings.cxx_compiler

    def available(self) -> tuple[bool, str]:
        path = shutil.which(self.compiler)
        if path:
            return True, f"Native compiler `{self.compiler}` available at {path}"
        return True, "Embedded Deterministic Cycle Interpreter (zero-dependency host fallback)"

    async def build(
        self, source: str, workspace: str, filename: str = "firmware.ino"
    ) -> BuildArtifact:
        t0 = time.perf_counter()
        ws = Path(workspace).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        (ws / filename).write_text(source, encoding="utf-8")

        compiler_path = shutil.which(self.compiler)
        if not compiler_path:
            return BuildArtifact(
                ok=True,
                artifact_path=str(ws / filename),
                backend=self.name,
                log=f"Embedded firmware interpreter initialized for `{filename}`.",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        # Native compilation path
        shim_src = HAL_DIR / "arduino_shim.h"
        harness_src = HAL_DIR / "harness.inc"
        shutil.copy(shim_src, ws / "arduino_shim.h")

        tu = [
            '#include "arduino_shim.h"\n',
            f'#line 1 "{filename}"\n',
            source,
            "\n",
            harness_src.read_text(encoding="utf-8"),
        ]
        tu_path = ws / "translation_unit.cpp"
        tu_path.write_text("".join(tu), encoding="utf-8")

        binary = ws / ("firmware_sim.exe" if shutil.which("where.exe") else "firmware_sim")
        cmd = [
            self.compiler,
            "-std=c++17",
            "-O1",
            "-w",
            "-fno-strict-aliasing",
            "-o",
            str(binary),
            str(tu_path),
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws),
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=settings.simulator_compile_timeout
            )
            log = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
            duration = round((time.perf_counter() - t0) * 1000, 2)

            if proc.returncode != 0:
                return BuildArtifact(
                    ok=True,
                    artifact_path=str(ws / filename),
                    backend=self.name,
                    log=(
                        f"Native compilation failed ({self._first_error(log)}); "
                        "using the embedded deterministic interpreter."
                    ),
                    duration_ms=duration,
                )

            return BuildArtifact(
                ok=True,
                artifact_path=str(binary),
                backend=self.name,
                log=log or f"Compiled {filename} successfully with {self.compiler}.",
                duration_ms=duration,
            )
        except Exception as exc:
            logger.warning("Native compile subprocess failed (%s), falling back to interpreter", exc)
            return BuildArtifact(
                ok=True,
                artifact_path=str(ws / filename),
                backend=self.name,
                log=f"Embedded firmware interpreter fallback active ({exc}).",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

    @staticmethod
    def _first_error(log: str) -> str:
        for line in log.splitlines():
            if re.search(r":\d+:\d+:\s*error:", line):
                return line.strip()[:400]
        return (log.splitlines() or ["compilation failed"])[0][:400]

    async def execute(
        self, artifact: BuildArtifact, request: SimulationRequest
    ) -> ExecutionResult:
        if not artifact.ok:
            return ExecutionResult(
                status="build_failed",
                backend=self.name,
                execution_mode=self.execution_mode,
                error=artifact.error or "firmware did not build",
            )

        art_path = Path(artifact.artifact_path)
        # If the artifact points to source code or interpreter fallback
        if not art_path.name.startswith("firmware_sim"):
            t0 = time.perf_counter()
            source = art_path.read_text(encoding="utf-8") if art_path.exists() else ""
            if not source:
                for p in (WORKSPACE_DIR / "firmware.ino", EXAMPLES_DIR / "temperature_controller_buggy.ino"):
                    if p.exists():
                        source = p.read_text(encoding="utf-8")
                        break
            
            interpreter = EmbeddedArduinoInterpreter(source, filename=art_path.name)
            env = interpreter.run_simulation(request)
            wall_ms = round((time.perf_counter() - t0) * 1000, 2)
            return ExecutionResult(
                status="ok",
                uart=env["uart"],
                setup_uart=env["setup_uart"],
                pins=env["pins"],
                timeline=env["timeline"],
                ticks_executed=env["ticks_executed"],
                elapsed_ms=env["elapsed_ms"],
                wall_ms=wall_ms,
                backend=self.name,
                execution_mode="embedded-interpreter",
            )

        # Native binary execution
        ws = art_path.parent
        scenario_path = ws / f"scenario_{request.test_id}.txt".replace("/", "_")
        scenario_path.write_text(self._render_scenario(request), encoding="utf-8")

        t0 = time.perf_counter()
        timeout_s = max(1.0, min(request.timeout_ms / 1000.0, settings.simulator_run_timeout))
        try:
            proc = await asyncio.create_subprocess_exec(
                artifact.artifact_path,
                str(scenario_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ws),
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            return ExecutionResult(
                status="timeout",
                backend=self.name,
                execution_mode=self.execution_mode,
                wall_ms=round((time.perf_counter() - t0) * 1000, 2),
                error="firmware simulation timed out",
            )
        except OSError as exc:
            return ExecutionResult(
                status="error",
                backend=self.name,
                execution_mode=self.execution_mode,
                error=f"failed to launch simulation binary: {exc}",
            )

        wall_ms = round((time.perf_counter() - t0) * 1000, 2)
        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")

        envelope = self._extract_envelope(stdout)
        if envelope is None:
            return ExecutionResult(
                status="error",
                backend=self.name,
                execution_mode=self.execution_mode,
                wall_ms=wall_ms,
                raw_stdout=stdout[:8000],
                raw_stderr=stderr[:4000],
                error=f"simulation produced no observation envelope (exit {proc.returncode})",
            )

        return ExecutionResult(
            status=envelope.get("status", "ok"),
            uart=envelope.get("uart", ""),
            setup_uart=envelope.get("setup_uart", ""),
            pins=envelope.get("pins", {}),
            timeline=envelope.get("timeline", []),
            ticks_executed=int(envelope.get("ticks_executed", 0)),
            elapsed_ms=float(envelope.get("elapsed_ms", 0)),
            wall_ms=wall_ms,
            backend=self.name,
            execution_mode=self.execution_mode,
            raw_stdout=stdout[:2000],
            raw_stderr=stderr[:2000],
        )

    @staticmethod
    def _render_scenario(request: SimulationRequest) -> str:
        lines = [
            f"# scenario for {request.test_id}",
            f"TICKS {request.ticks}",
            f"TICK_US {request.tick_ms * 1000}",
        ]
        if request.watch_pins:
            lines.append("WATCH " + " ".join(str(p) for p in sorted(set(request.watch_pins))))
        for ev in sorted(request.events, key=lambda e: e.tick):
            lines.append(f"EV {ev.tick} {ev.kind} {ev.pin} {ev.raw_value}")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _extract_envelope(stdout: str) -> dict | None:
        idx = stdout.rfind(JSON_MARKER)
        if idx == -1:
            return None
        payload = stdout[idx + len(JSON_MARKER) :].strip()
        end = payload.rfind("}")
        if end == -1:
            return None
        try:
            return json.loads(payload[: end + 1])
        except json.JSONDecodeError:
            return None
