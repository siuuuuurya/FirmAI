"""
Firmware Testing & Debugging Pipeline Orchestrator
=================================================
Strictly implements and enforces the 7-step path sequence of execution:

  Step 1: Provide embedded firmware to the system
  Step 2: AI analyses the firmware
  Step 3: AI generates test scenarios
  Step 4: Tests run in a virtual hardware environment
  Step 5: Firmware behaviour is observed
  Step 6: Failures are identified
  Step 7: A test/debugging report is generated
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.analyzers.firmware_analyzer import analyze_source
from app.core.config import EXAMPLES_DIR, REPORT_DIR, WORKSPACE_DIR
from app.failure_analyzer.root_cause import AIFailureAnalyzer
from app.reports.reporter import ReportGenerator
from app.simulator.evaluator import TestEvaluator
from app.simulator.local_simulator import LocalDeterministicSimulator
from app.simulator.manager import SimulatorManager
from app.test_generator.generator import TestGenerator

logger = logging.getLogger("firmwareai.pipeline")


@dataclass
class FirmwareRecord:
    """Metadata and content for embedded firmware provided to the system."""
    id: str
    filename: str
    source_code: str
    size_bytes: int
    line_count: int
    sha256: str
    language: str = "arduino-cpp"
    notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class StepExecutionLog:
    """Telemetry captured for each step in the pipeline sequence."""
    step_number: int
    step_name: str
    status: str  # "completed", "failed", "running"
    duration_ms: float
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineReport:
    """Comprehensive result returned by the 7-step pipeline."""
    run_id: str
    firmware: FirmwareRecord
    analysis: dict[str, Any]
    suite: Any
    total_tests: int
    passed_tests: int
    failed_tests: int
    errored_tests: int
    pass_rate: float
    verdict: str
    observations: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    report_data: dict[str, Any]
    html_report: str
    json_path: str | None = None
    html_path: str | None = None
    steps: list[StepExecutionLog] = field(default_factory=list)
    total_duration_ms: float = 0.0


class FirmwarePipeline:
    """
    Executes the firmware verification workflow in strict sequence:

    Step 1: Provide embedded firmware to the system
    Step 2: AI analyses the firmware
    Step 3: AI generates test scenarios
    Step 4: Tests run in a virtual hardware environment
    Step 5: Firmware behaviour is observed
    Step 6: Failures are identified
    Step 7: A test/debugging report is generated
    """

    def __init__(
        self,
        progress_callback: Callable[[int, str, str], None] | None = None,
    ) -> None:
        """
        :param progress_callback: Optional hook (step_number, step_name, status_message)
        """
        self.progress_callback = progress_callback
        self.sim_manager = SimulatorManager()
        self.evaluator = TestEvaluator()
        self.failure_analyzer = AIFailureAnalyzer()
        self.report_generator = ReportGenerator()
        self.test_generator = TestGenerator()

    def _notify(self, step_num: int, step_name: str, message: str) -> None:
        logger.info("[STEP %d/7] %s: %s", step_num, step_name, message)
        if self.progress_callback:
            self.progress_callback(step_num, step_name, message)

    # ------------------------------------------------------------------
    # Step 1: Provide embedded firmware to the system
    # ------------------------------------------------------------------
    def step_1_provide_firmware(
        self,
        source_code: str | None = None,
        file_path: str | Path | None = None,
        filename: str | None = None,
        notes: str = "",
    ) -> FirmwareRecord:
        """
        Step 1: Ingest embedded firmware into the system.
        Validates content, calculates SHA-256 hash, parses size and lines.
        """
        t0 = time.perf_counter()
        self._notify(1, "Provide Embedded Firmware", "Ingesting and validating firmware source...")

        if file_path:
            p = Path(file_path)
            if not p.exists():
                raise FileNotFoundError(f"Firmware file `{file_path}` not found.")
            source_code = p.read_text(encoding="utf-8")
            if not filename:
                filename = p.name

        if not source_code or not source_code.strip():
            raise ValueError("Embedded firmware source code cannot be empty.")

        filename = filename or "firmware.ino"
        encoded = source_code.encode("utf-8")
        size_bytes = len(encoded)
        line_count = len(source_code.splitlines())
        sha256 = hashlib.sha256(encoded).hexdigest()
        fw_id = f"fw_{uuid.uuid4().hex[:12]}"

        fw = FirmwareRecord(
            id=fw_id,
            filename=filename,
            source_code=source_code,
            size_bytes=size_bytes,
            line_count=line_count,
            sha256=sha256,
            notes=notes,
        )

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        self._notify(1, "Provide Embedded Firmware", f"Ingested {filename} ({size_bytes} bytes, {line_count} lines, SHA256: {sha256[:10]}...) in {elapsed}ms")
        return fw

    # ------------------------------------------------------------------
    # Step 2: AI analyses the firmware
    # ------------------------------------------------------------------
    async def step_2_ai_analyze_firmware(self, firmware: FirmwareRecord) -> dict[str, Any]:
        """
        Step 2: AI analyses the firmware.
        Performs AST inspection, pin configuration extraction, state machine detection,
        threshold extraction, and mathematical transfer function modeling.
        """
        t0 = time.perf_counter()
        self._notify(2, "AI Firmware Analysis", f"Analyzing AST, I/O channels, state machines for `{firmware.filename}`...")

        analysis = analyze_source(firmware.source_code, firmware.filename)

        num_pins = len(analysis.get("gpio_pins", []))
        num_thresholds = len(analysis.get("thresholds", []))
        num_states = len(analysis.get("states", []))
        elapsed = round((time.perf_counter() - t0) * 1000, 2)

        self._notify(
            2,
            "AI Firmware Analysis",
            f"Extracted {num_pins} GPIOs, {num_thresholds} thresholds, {num_states} FSM states in {elapsed}ms",
        )
        return analysis

    # ------------------------------------------------------------------
    # Step 3: AI generates test scenarios
    # ------------------------------------------------------------------
    async def step_3_ai_generate_test_scenarios(
        self,
        firmware: FirmwareRecord,
        analysis: dict[str, Any],
        max_tests: int = 8,
        focus: str = "",
        use_llm: bool = False,
    ) -> Any:
        """
        Step 3: AI generates test scenarios.
        Synthesizes boundary value, safety limit, stress, and functional test cases.
        """
        t0 = time.perf_counter()
        self._notify(3, "AI Test Generation", f"Generating up to {max_tests} test scenarios (focus: '{focus or 'boundary/safety'}')...")

        suite = await self.test_generator.generate(
            source=firmware.source_code,
            analysis=analysis,
            filename=firmware.filename,
            max_tests=max_tests,
            focus=focus,
            use_llm=use_llm,
        )

        test_count = len(suite.tests)
        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        self._notify(3, "AI Test Generation", f"Generated {test_count} scenarios ({suite.engine}) in {elapsed}ms")
        return suite

    # ------------------------------------------------------------------
    # Step 4: Tests run in a virtual hardware environment
    # ------------------------------------------------------------------
    async def step_4_run_tests_in_virtual_hardware(
        self,
        firmware: FirmwareRecord,
        analysis: dict[str, Any],
        suite: Any,
        simulator_backend: str | None = None,
        workspace_base: Path | None = None,
    ) -> tuple[Any, list[tuple[dict[str, Any], Any]]]:
        """
        Step 4: Tests run in a virtual hardware environment.
        Compiles the firmware image and steps through clock ticks on virtual hardware.
        """
        t0 = time.perf_counter()
        backend_name = simulator_backend or "local_deterministic"
        simulator = self.sim_manager.get(backend_name)
        self._notify(4, "Virtual Hardware Simulation", f"Compiling and executing on `{simulator.label}`...")

        ws_dir = (workspace_base or WORKSPACE_DIR) / f"run_{uuid.uuid4().hex[:8]}"
        ws_dir.mkdir(parents=True, exist_ok=True)

        build_artifact = await simulator.build(
            firmware.source_code,
            str(ws_dir),
            firmware.filename,
        )

        if not build_artifact.ok:
            raise RuntimeError(f"Virtual hardware build failed: {build_artifact.log}")

        raw_executions: list[tuple[dict[str, Any], Any]] = []
        signal_map = analysis.get("signal_map", {})

        for idx, case in enumerate(suite.tests):
            case_dict = {
                "test_id": case.get("test_id", f"TC-{idx+1:03d}"),
                "name": case.get("name", f"Test {idx+1}"),
                "category": case.get("category", "functional"),
                "priority": case.get("priority", "medium"),
                "requirement": case.get("requirement", ""),
                "rationale": case.get("rationale", ""),
                "stimulus": case.get("stimulus", {}),
                "expectations": case.get("expectations", []),
                "timeout_ms": case.get("timeout_ms", 5000),
            }
            sim_req = self.sim_manager.compile_request(case_dict, signal_map)
            exec_res = await simulator.execute(build_artifact, sim_req)
            raw_executions.append((case_dict, exec_res))

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        self._notify(4, "Virtual Hardware Simulation", f"Completed {len(raw_executions)} test runs in {elapsed}ms")
        return build_artifact, raw_executions

    # ------------------------------------------------------------------
    # Step 5: Firmware behaviour is observed
    # ------------------------------------------------------------------
    def step_5_observe_firmware_behaviour(
        self,
        analysis: dict[str, Any],
        raw_executions: list[tuple[dict[str, Any], Any]],
    ) -> list[dict[str, Any]]:
        """
        Step 5: Firmware behaviour is observed.
        Samples pin transitions, UART output stream, state changes, and evaluates assertions.
        """
        t0 = time.perf_counter()
        self._notify(5, "Behaviour Observation", f"Observing pin waveform transitions, serial logs, and register states...")

        signal_map = analysis.get("signal_map", {})
        observed_results: list[dict[str, Any]] = []

        for idx, (case_dict, exec_res) in enumerate(raw_executions):
            evaluation = self.evaluator.evaluate(case_dict, exec_res, signal_map)
            evaluation["order_index"] = idx
            evaluation["test_id"] = case_dict["test_id"]
            evaluation["name"] = case_dict["name"]
            evaluation["category"] = case_dict.get("category", "functional")
            evaluation["priority"] = case_dict.get("priority", "medium")
            evaluation["requirement"] = case_dict.get("requirement", "")
            evaluation["rationale"] = case_dict.get("rationale", "")
            evaluation["stimulus"] = case_dict.get("stimulus", {})
            evaluation["expectations"] = case_dict.get("expectations", [])
            evaluation["duration_ms"] = exec_res.wall_ms
            observed_results.append(evaluation)

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        passed_count = sum(1 for r in observed_results if r["status"] == "PASS")
        failed_count = sum(1 for r in observed_results if r["status"] == "FAIL")
        errored_count = sum(1 for r in observed_results if r["status"] == "ERROR")

        self._notify(
            5,
            "Behaviour Observation",
            f"Observed {len(observed_results)} runs ({passed_count} PASS, {failed_count} FAIL, {errored_count} ERROR) in {elapsed}ms",
        )
        return observed_results

    # ------------------------------------------------------------------
    # Step 6: Failures are identified
    # ------------------------------------------------------------------
    async def step_6_identify_failures(
        self,
        firmware: FirmwareRecord,
        observed_results: list[dict[str, Any]],
        use_llm: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Step 6: Failures are identified.
        Flags assertion deviations, runs AI failure analyzer to diagnose root cause,
        suspect code lines, and suggested fixes.
        """
        t0 = time.perf_counter()
        failed_results = [r for r in observed_results if r["status"] in ("FAIL", "ERROR")]
        self._notify(6, "Failure Identification", f"Pinpointing defects for {len(failed_results)} failed scenario(s)...")

        failure_diagnoses: list[dict[str, Any]] = []

        for tr in failed_results:
            fa_res = await self.failure_analyzer.analyze(
                source_code=firmware.source_code,
                test_result={
                    "test_id": tr["test_id"],
                    "name": tr["name"],
                    "category": tr["category"],
                    "rationale": tr["rationale"],
                    "assertions": tr["assertions"],
                    "observed": tr["observed"],
                    "serial_log": tr["serial_log"],
                    "trace": tr["trace"],
                },
                filename=firmware.filename,
                case_info={"requirement": tr.get("requirement", "")},
                use_llm=use_llm,
            )

            diagnosis = {
                "test_id": tr["test_id"],
                "name": tr["name"],
                "category": fa_res.category,
                "severity": fa_res.severity,
                "root_cause": fa_res.root_cause,
                "explanation": fa_res.explanation,
                "confidence": fa_res.confidence,
                "suspect_lines": fa_res.suspect_lines,
                "code_snippet": fa_res.code_snippet,
                "suggested_fix": fa_res.suggested_fix,
                "fix_diff": fa_res.fix_diff,
                "evidence": fa_res.evidence,
                "engine": fa_res.engine,
                "duration_ms": fa_res.duration_ms,
            }
            failure_diagnoses.append(diagnosis)
            # Attach back to test result for report generator
            tr["failure_analysis"] = diagnosis

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        if failure_diagnoses:
            defects_summary = ", ".join(f"{d['test_id']} ({d['severity']})" for d in failure_diagnoses)
            self._notify(6, "Failure Identification", f"Identified {len(failure_diagnoses)} defect(s): {defects_summary} in {elapsed}ms")
        else:
            self._notify(6, "Failure Identification", f"No failures detected; all assertions passed in {elapsed}ms")

        return failure_diagnoses

    # ------------------------------------------------------------------
    # Step 7: A test/debugging report is generated
    # ------------------------------------------------------------------
    def step_7_generate_debugging_report(
        self,
        run_id: str,
        firmware: FirmwareRecord,
        analysis: dict[str, Any],
        suite: Any,
        observed_results: list[dict[str, Any]],
        failures: list[dict[str, Any]],
        build_log: str = "",
        output_dir: str | Path | None = None,
    ) -> tuple[dict[str, Any], str, str, str]:
        """
        Step 7: A test/debugging report is generated.
        Synthesizes structured JSON audit data and rendered interactive HTML report.
        """
        t0 = time.perf_counter()
        self._notify(7, "Report Generation", "Synthesizing executive audit report and diagnostic cards...")

        run_data = {
            "id": run_id,
            "status": "completed",
            "build_log": build_log,
            "results": observed_results,
        }

        firmware_data = {
            "id": firmware.id,
            "filename": firmware.filename,
            "size_bytes": firmware.size_bytes,
            "sha256": firmware.sha256,
        }

        analysis_data = {
            "metrics": analysis.get("metrics", {}),
            "gpio_pins": analysis.get("gpio_pins", []),
            "thresholds": analysis.get("thresholds", []),
        }

        report_data = self.report_generator.generate_report_data(
            run_data=run_data,
            firmware_data=firmware_data,
            analysis_data=analysis_data,
        )

        html_content = self.report_generator.render_html(report_data)

        target_dir = Path(output_dir) if output_dir else REPORT_DIR
        target_dir.mkdir(parents=True, exist_ok=True)

        json_path = target_dir / f"report_{run_id}.json"
        html_path = target_dir / f"report_{run_id}.html"

        import json
        json_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        html_path.write_text(html_content, encoding="utf-8")

        elapsed = round((time.perf_counter() - t0) * 1000, 2)
        self._notify(
            7,
            "Report Generation",
            f"Generated reports in {elapsed}ms -> HTML: {html_path.name} | JSON: {json_path.name} (Verdict: {report_data['verdict']})",
        )
        return report_data, html_content, str(json_path), str(html_path)

    # ------------------------------------------------------------------
    # Strictly Sequential End-to-End Execution
    # ------------------------------------------------------------------
    async def run_pipeline(
        self,
        source_code: str | None = None,
        file_path: str | Path | None = None,
        filename: str | None = None,
        max_tests: int = 8,
        focus: str = "",
        use_llm: bool = False,
        simulator_backend: str | None = None,
        output_dir: str | Path | None = None,
    ) -> PipelineReport:
        """
        Executes the 7 steps in strict sequential order.
        """
        t_start = time.perf_counter()
        run_id = uuid.uuid4().hex[:16]
        steps_log: list[StepExecutionLog] = []

        # Step 1: Provide embedded firmware to the system
        t_step = time.perf_counter()
        firmware = self.step_1_provide_firmware(
            source_code=source_code,
            file_path=file_path,
            filename=filename,
        )
        steps_log.append(StepExecutionLog(
            step_number=1,
            step_name="Provide embedded firmware to the system",
            status="completed",
            duration_ms=round((time.perf_counter() - t_step) * 1000, 2),
            details={"filename": firmware.filename, "size_bytes": firmware.size_bytes, "sha256": firmware.sha256},
        ))

        # Step 2: AI analyses the firmware
        t_step = time.perf_counter()
        analysis = await self.step_2_ai_analyze_firmware(firmware)
        steps_log.append(StepExecutionLog(
            step_number=2,
            step_name="AI analyses the firmware",
            status="completed",
            duration_ms=round((time.perf_counter() - t_step) * 1000, 2),
            details={"gpio_pins": len(analysis.get("gpio_pins", [])), "states": len(analysis.get("states", []))},
        ))

        # Step 3: AI generates test scenarios
        t_step = time.perf_counter()
        suite = await self.step_3_ai_generate_test_scenarios(
            firmware=firmware,
            analysis=analysis,
            max_tests=max_tests,
            focus=focus,
            use_llm=use_llm,
        )
        steps_log.append(StepExecutionLog(
            step_number=3,
            step_name="AI generates test scenarios",
            status="completed",
            duration_ms=round((time.perf_counter() - t_step) * 1000, 2),
            details={"test_count": len(suite.tests), "engine": suite.engine},
        ))

        # Step 4: Tests run in a virtual hardware environment
        t_step = time.perf_counter()
        build_artifact, raw_executions = await self.step_4_run_tests_in_virtual_hardware(
            firmware=firmware,
            analysis=analysis,
            suite=suite,
            simulator_backend=simulator_backend,
        )
        steps_log.append(StepExecutionLog(
            step_number=4,
            step_name="Tests run in a virtual hardware environment",
            status="completed",
            duration_ms=round((time.perf_counter() - t_step) * 1000, 2),
            details={"executed_runs": len(raw_executions), "build_ok": build_artifact.ok},
        ))

        # Step 5: Firmware behaviour is observed
        t_step = time.perf_counter()
        observed_results = self.step_5_observe_firmware_behaviour(
            analysis=analysis,
            raw_executions=raw_executions,
        )
        total = len(observed_results)
        passed = sum(1 for r in observed_results if r["status"] == "PASS")
        failed = sum(1 for r in observed_results if r["status"] == "FAIL")
        errored = sum(1 for r in observed_results if r["status"] == "ERROR")
        pass_rate = round((passed / total * 100.0), 1) if total > 0 else 0.0

        steps_log.append(StepExecutionLog(
            step_number=5,
            step_name="Firmware behaviour is observed",
            status="completed",
            duration_ms=round((time.perf_counter() - t_step) * 1000, 2),
            details={"total": total, "passed": passed, "failed": failed, "errored": errored, "pass_rate": pass_rate},
        ))

        # Step 6: Failures are identified
        t_step = time.perf_counter()
        failures = await self.step_6_identify_failures(
            firmware=firmware,
            observed_results=observed_results,
            use_llm=use_llm,
        )
        steps_log.append(StepExecutionLog(
            step_number=6,
            step_name="Failures are identified",
            status="completed",
            duration_ms=round((time.perf_counter() - t_step) * 1000, 2),
            details={"defects_identified": len(failures)},
        ))

        # Step 7: A test/debugging report is generated
        t_step = time.perf_counter()
        report_data, html_content, json_path, html_path = self.step_7_generate_debugging_report(
            run_id=run_id,
            firmware=firmware,
            analysis=analysis,
            suite=suite,
            observed_results=observed_results,
            failures=failures,
            build_log=build_artifact.log,
            output_dir=output_dir,
        )
        steps_log.append(StepExecutionLog(
            step_number=7,
            step_name="A test/debugging report is generated",
            status="completed",
            duration_ms=round((time.perf_counter() - t_step) * 1000, 2),
            details={"verdict": report_data["verdict"], "html_report": html_path, "json_report": json_path},
        ))

        total_duration = round((time.perf_counter() - t_start) * 1000, 2)

        return PipelineReport(
            run_id=run_id,
            firmware=firmware,
            analysis=analysis,
            suite=suite,
            total_tests=total,
            passed_tests=passed,
            failed_tests=failed,
            errored_tests=errored,
            pass_rate=pass_rate,
            verdict=report_data["verdict"],
            observations=observed_results,
            failures=failures,
            report_data=report_data,
            html_report=html_content,
            json_path=json_path,
            html_path=html_path,
            steps=steps_log,
            total_duration_ms=total_duration,
        )
