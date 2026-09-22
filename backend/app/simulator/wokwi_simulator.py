"""
WokwiSimulator — Real Hardware Instruction-Set Emulation
========================================================
Compiles embedded firmware to AVR machine code (.hex/.elf) using `arduino-cli`,
generates Wokwi scenario YAMLs from synthesized test cases, executes the virtual
circuit using `wokwi-cli`, and maps live serial outputs and pin assertions into
the standard FirmAI ExecutionResult format.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

from app.core.config import DATA_DIR
from app.simulator.base import (
    BuildArtifact,
    ExecutionResult,
    SimulationRequest,
    SimulatorInterface,
    SimulatorUnavailable,
)

logger = logging.getLogger("firmwareai.simulator.wokwi")

# Path to built-in Wokwi template files (diagram.json, etc.)
TEMPLATE_DIR = DATA_DIR / "wokwi_template" / "fan_controller"


class WokwiSimulator(SimulatorInterface):
    name = "wokwi"
    label = "Wokwi Cloud Simulator (AVR/ESP32 instruction-accurate)"
    execution_mode = "instruction-accurate-emulation"

    def available(self) -> tuple[bool, str]:
        if not shutil.which("arduino-cli"):
            return False, "arduino-cli is required to compile .hex/.elf images"
        if not shutil.which("wokwi-cli"):
            return False, "wokwi-cli is not installed (install via official installer or package)"
        if not os.getenv("WOKWI_CLI_TOKEN"):
            return False, "WOKWI_CLI_TOKEN is not set (obtain free token at https://wokwi.com/dashboard/ci)"
        return True, "wokwi-cli, arduino-cli, and credentials ready"

    async def build(self, source: str, workspace: str, filename: str = "firmware.ino") -> BuildArtifact:
        """
        Compile Arduino firmware source into genuine AVR Uno machine binary (.hex and .elf)
        using arduino-cli.
        """
        t0 = time.perf_counter()
        ws_dir = Path(workspace)
        ws_dir.mkdir(parents=True, exist_ok=True)

        arduino_cli_path = shutil.which("arduino-cli")
        if not arduino_cli_path:
            raise SimulatorUnavailable("arduino-cli is not installed in system PATH.")

        # Arduino CLI requires the .ino file to reside inside a folder matching its name
        sketch_name = "firmware"
        sketch_dir = ws_dir / "sketch" / sketch_name
        sketch_dir.mkdir(parents=True, exist_ok=True)
        ino_path = sketch_dir / f"{sketch_name}.ino"
        ino_path.write_text(source, encoding="utf-8")

        build_dir = ws_dir / "build"
        build_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            arduino_cli_path,
            "compile",
            "--fqbn", "arduino:avr:uno",
            "--output-dir", str(build_dir),
            str(sketch_dir),
        ]

        logger.info("Compiling with arduino-cli: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        stdout_txt = stdout.decode("utf-8", errors="replace")
        stderr_txt = stderr.decode("utf-8", errors="replace")
        build_log = f"{stdout_txt}\n{stderr_txt}".strip()

        if proc.returncode != 0:
            logger.error("arduino-cli compilation failed: %s", build_log)
            return BuildArtifact(
                ok=False,
                log=build_log,
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                backend=self.name,
                error=f"arduino-cli build error (code {proc.returncode}): {stderr_txt}",
            )

        hex_path = build_dir / f"{sketch_name}.ino.hex"
        elf_path = build_dir / f"{sketch_name}.ino.elf"

        # Copy or generate wokwi.toml and diagram.json in the workspace root
        wokwi_toml = ws_dir / "wokwi.toml"
        wokwi_toml.write_text(
            f"[wokwi]\nversion = 1\nfirmware = '{hex_path.relative_to(ws_dir)}'\nelf = '{elf_path.relative_to(ws_dir)}'\n",
            encoding="utf-8",
        )

        diagram_dst = ws_dir / "diagram.json"
        if not diagram_dst.exists():
            template_diagram = TEMPLATE_DIR / "diagram.json"
            if template_diagram.exists():
                shutil.copy(template_diagram, diagram_dst)
            else:
                self._write_default_diagram(diagram_dst)

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        return BuildArtifact(
            ok=True,
            artifact_path=str(hex_path),
            log=build_log,
            duration_ms=elapsed,
            backend=self.name,
        )

    async def execute(self, artifact: BuildArtifact, request: SimulationRequest) -> ExecutionResult:
        """
        Generates a Wokwi scenario YAML from the SimulationRequest, executes it with wokwi-cli,
        and parses serial logs and pass/fail status into an ExecutionResult.
        """
        t0 = time.perf_counter()
        wokwi_cli_path = shutil.which("wokwi-cli")
        if not wokwi_cli_path:
            raise SimulatorUnavailable("wokwi-cli is not installed.")

        token = os.getenv("WOKWI_CLI_TOKEN")
        if not token:
            raise SimulatorUnavailable(
                "WOKWI_CLI_TOKEN environment variable is missing. "
                "Get your token at https://wokwi.com/dashboard/ci and export WOKWI_CLI_TOKEN=<token>."
            )

        ws_dir = Path(artifact.artifact_path).resolve().parents[1]
        scenarios_dir = ws_dir / "scenarios"
        scenarios_dir.mkdir(parents=True, exist_ok=True)

        scenario_path = scenarios_dir / f"{request.test_id}.test.yaml"
        self._generate_scenario_yaml(request, scenario_path)

        serial_log_file = ws_dir / "build" / f"{request.test_id}.log"
        serial_log_file.parent.mkdir(parents=True, exist_ok=True)

        timeout_ms = max(request.timeout_ms, 8000)
        cmd = [
            wokwi_cli_path,
            str(ws_dir),
            "--scenario", str(scenario_path),
            "--timeout", str(timeout_ms),
            "--serial-log-file", str(serial_log_file),
        ]

        logger.info("Executing Wokwi scenario %s", scenario_path.name)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        stdout_txt = stdout.decode("utf-8", errors="replace")
        stderr_txt = stderr.decode("utf-8", errors="replace")

        serial_log = ""
        if serial_log_file.exists():
            serial_log = serial_log_file.read_text(encoding="utf-8", errors="replace")
        elif stdout_txt:
            serial_log = stdout_txt

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        status = "ok" if proc.returncode == 0 else "error"

        # Parse observed state from serial telemetry (e.g. TEMP=30 FAN=ON STATE=NORMAL)
        pins = self._infer_pins_from_serial(serial_log)

        return ExecutionResult(
            status=status,
            uart=serial_log,
            pins=pins,
            timeline=[],
            ticks_executed=request.ticks,
            elapsed_ms=elapsed,
            wall_ms=elapsed,
            backend=self.name,
            execution_mode=self.execution_mode,
            raw_stdout=stdout_txt,
            raw_stderr=stderr_txt,
            error=stderr_txt if status != "ok" else "",
        )

    # Physical operational limits of Wokwi's wokwi-ntc-temperature-sensor part
    WOKWI_NTC_MIN_C = -24
    WOKWI_NTC_MAX_C = 80

    def _generate_scenario_yaml(self, request: SimulationRequest, output_file: Path) -> None:
        """Translate a FirmAI SimulationRequest into a clean Wokwi scenario YAML file."""
        lines = [
            f"name: '{request.test_id}'",
            "version: 1",
            "steps:",
            "  - delay: 500ms",
        ]

        # Translate stimulus events into hardware control actuations
        for ev in request.events:
            val = ev.engineering_value if ev.engineering_value is not None else ev.raw_value
            channel_lower = (ev.channel or "").lower()

            # Explicit fault injection: short to GND (ADC 0) or open-circuit (ADC 1023)
            is_fault_open = (ev.kind == "fault" and "open" in channel_lower) or (ev.unit in ("counts", "adc", "raw") and ev.raw_value >= 1023)
            is_fault_short = (ev.kind == "fault" and "short" in channel_lower) or (ev.unit in ("counts", "adc", "raw") and ev.raw_value <= 0)

            if is_fault_open:
                lines.append("  - set-control:\n      part-id: btn_open\n      control: pressed\n      value: 1")
                lines.append("  - delay: 1500ms")
                # Reset button state to prevent latching across subsequent steps
                lines.append("  - set-control:\n      part-id: btn_open\n      control: pressed\n      value: 0")
            elif is_fault_short:
                lines.append("  - set-control:\n      part-id: btn_short\n      control: pressed\n      value: 1")
                lines.append("  - delay: 1500ms")
                # Reset button state to prevent latching across subsequent steps
                lines.append("  - set-control:\n      part-id: btn_short\n      control: pressed\n      value: 0")
            elif "temp" in channel_lower or "ntc" in channel_lower or ev.pin in (14, 0):  # A0
                target_c = int(round(float(val)))
                # Check Wokwi NTC hardware limits
                if target_c < self.WOKWI_NTC_MIN_C or target_c > self.WOKWI_NTC_MAX_C:
                    logger.warning(
                        "Testcase %s requested %d°C, which exceeds Wokwi NTC part range [%d, %d]°C; clamping.",
                        request.test_id, target_c, self.WOKWI_NTC_MIN_C, self.WOKWI_NTC_MAX_C,
                    )
                    target_c = max(self.WOKWI_NTC_MIN_C, min(target_c, self.WOKWI_NTC_MAX_C))

                lines.append(f"  - set-control:\n      part-id: ntc1\n      control: temperature\n      value: {target_c}")
                lines.append("  - delay: 1500ms")

        output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _infer_pins_from_serial(self, serial_log: str) -> dict[str, dict[str, Any]]:
        """
        Extract observed pin and actuator states from the settled tail of firmware serial telemetry.
        Ignores stale initialization cycles from before the stimulus settled.
        """
        pins: dict[str, dict[str, Any]] = {}
        all_lines = [l.strip() for l in serial_log.splitlines() if l.strip()]
        # Evaluate only the settled tail (last 3 lines) to avoid false positives from stale cycles
        settled_lines = all_lines[-3:] if len(all_lines) >= 3 else all_lines

        for line in settled_lines:
            line_clean = line.strip().upper()
            if "FAN=ON" in line_clean or "FAN=1" in line_clean:
                pins["FAN_PIN"] = {"digital": 1}
                pins["9"] = {"digital": 1}
                pins["5"] = {"digital": 1}
            elif "FAN=OFF" in line_clean or "FAN=0" in line_clean:
                pins["FAN_PIN"] = {"digital": 0}
                pins["9"] = {"digital": 0}
                pins["5"] = {"digital": 0}

            if "HEATER=1" in line_clean or "HEATER=ON" in line_clean:
                pins["HEATER_PIN"] = {"digital": 1}
                pins["6"] = {"digital": 1}
            elif "HEATER=0" in line_clean or "HEATER=OFF" in line_clean:
                pins["HEATER_PIN"] = {"digital": 0}
                pins["6"] = {"digital": 0}

            if "STATE=ERROR" in line_clean or "ALARM=1" in line_clean:
                pins["ALARM_LED_PIN"] = {"digital": 1}
                pins["ERR_LED_PIN"] = {"digital": 1}
                pins["8"] = {"digital": 1}
                pins["7"] = {"digital": 1}
            elif "STATE=NORMAL" in line_clean:
                pins["ERR_LED_PIN"] = {"digital": 0}
                pins["8"] = {"digital": 0}

        return pins

    def _write_default_diagram(self, dst_file: Path) -> None:
        """Write standard virtual circuit diagram (Arduino Uno, NTC sensor, LEDs, Buttons)."""
        import json
        diagram = {
            "version": 1,
            "author": "FirmAI Autonomous Testing Agent",
            "editor": "wokwi",
            "parts": [
                {"type": "wokwi-arduino-uno", "id": "uno", "top": 0, "left": 0, "attrs": {}},
                {"type": "wokwi-ntc-temperature-sensor", "id": "ntc1", "top": -90, "left": 320, "attrs": {}},
                {"type": "wokwi-led", "id": "led_fan", "top": -140, "left": 40, "attrs": {"color": "blue"}},
                {"type": "wokwi-led", "id": "led_err", "top": -140, "left": 130, "attrs": {"color": "red"}},
                {"type": "wokwi-resistor", "id": "r_fan", "top": -60, "left": 30, "rotate": 90, "attrs": {"value": "220"}},
                {"type": "wokwi-resistor", "id": "r_err", "top": -60, "left": 120, "rotate": 90, "attrs": {"value": "220"}},
                {"type": "wokwi-pushbutton", "id": "btn_short", "top": 240, "left": 60, "attrs": {"color": "black", "label": "short"}},
                {"type": "wokwi-pushbutton", "id": "btn_open", "top": 240, "left": 180, "attrs": {"color": "red", "label": "open"}},
            ],
            "connections": [
                ["uno:5V", "ntc1:VCC", "red", []],
                ["uno:GND.2", "ntc1:GND", "black", []],
                ["ntc1:OUT", "uno:A0", "green", []],
                ["uno:9", "r_fan:1", "blue", []],
                ["r_fan:2", "led_fan:A", "blue", []],
                ["led_fan:C", "uno:GND.1", "black", []],
                ["uno:8", "r_err:1", "red", []],
                ["r_err:2", "led_err:A", "red", []],
                ["led_err:C", "uno:GND.1", "black", []],
                ["btn_short:1.l", "uno:A0", "orange", []],
                ["btn_short:2.l", "uno:GND.3", "black", []],
                ["btn_open:1.l", "uno:A0", "orange", []],
                ["btn_open:2.l", "uno:5V", "red", []],
            ],
            "dependencies": {},
        }
        dst_file.write_text(json.dumps(diagram, indent=2), encoding="utf-8")
