"""
Integration tests for FirmAI pipeline.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from httpx import AsyncClient, ASGITransport

from app.analyzers.firmware_analyzer import analyze_source
from app.core.config import EXAMPLES_DIR, WORKSPACE_DIR
from app.failure_analyzer.root_cause import AIFailureAnalyzer
from app.main import app
from app.reports.reporter import ReportGenerator
from app.simulator.evaluator import TestEvaluator
from app.simulator.local_simulator import LocalDeterministicSimulator
from app.simulator.manager import SimulatorManager
from app.test_generator.generator import TestGenerator


@pytest.fixture
def buggy_firmware_source():
    path = EXAMPLES_DIR / "temperature_controller_buggy.ino"
    return path.read_text(encoding="utf-8")


@pytest.fixture
def golden_firmware_source():
    path = EXAMPLES_DIR / "temperature_controller.ino"
    return path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_static_analysis(buggy_firmware_source):
    analysis = analyze_source(buggy_firmware_source, "temperature_controller_buggy.ino")
    assert "inputs" in analysis
    assert "outputs" in analysis
    assert "gpio_pins" in analysis
    assert "signal_map" in analysis
    assert len(analysis["gpio_pins"]) >= 4
    assert len(analysis["thresholds"]) >= 3


@pytest.mark.asyncio
async def test_test_generation(buggy_firmware_source):
    analysis = analyze_source(buggy_firmware_source, "temperature_controller_buggy.ino")
    generator = TestGenerator()
    suite = await generator.generate(
        source=buggy_firmware_source,
        analysis=analysis,
        filename="temperature_controller_buggy.ino",
        max_tests=6,
        use_llm=False,
    )
    assert len(suite.tests) >= 3
    for tc in suite.tests:
        assert "test_id" in tc
        assert "stimulus" in tc
        assert "expectations" in tc


@pytest.mark.asyncio
async def test_simulator_and_evaluation(buggy_firmware_source):
    analysis = analyze_source(buggy_firmware_source, "temperature_controller_buggy.ino")
    sim_mgr = SimulatorManager()
    simulator = LocalDeterministicSimulator()
    evaluator = TestEvaluator()

    # Build
    artifact = await simulator.build(buggy_firmware_source, str(WORKSPACE_DIR / "test_run"), "temperature_controller_buggy.ino")
    assert artifact.ok

    # Test Case: Overheat at 32°C (should fail on buggy code because fan starts at 35°C)
    tc = {
        "test_id": "TC-OVERHEAT-32",
        "name": "Cooling above 30C",
        "stimulus": {
            "ticks": 5,
            "tick_ms": 100,
            "events": [{"tick": -1, "channel": "TEMP_SENSOR_PIN", "unit": "counts", "value": 328}], # 328 raw = 32 C
        },
        "expectations": [
            {"id": "E1", "kind": "pin_digital", "target": "FAN_PIN", "value": 1, "at_tick": -1, "description": "Fan ON at 32C"}
        ],
        "timeout_ms": 2000,
    }

    req = sim_mgr.compile_request(tc, analysis["signal_map"])
    result = await simulator.execute(artifact, req)
    assert result.status == "ok"

    evaluation = evaluator.evaluate(tc, result, analysis["signal_map"])
    # On buggy firmware, 32C doesn't trigger fan (buggy threshold is >= 35.0), so this test should FAIL
    assert evaluation["status"] == "FAIL"


@pytest.mark.asyncio
async def test_ai_failure_analyzer(buggy_firmware_source):
    analyzer = AIFailureAnalyzer()
    test_result = {
        "test_id": "TC-002",
        "name": "Critical Overheat Alarm",
        "category": "boundary",
        "assertions": [
            {
                "id": "E1",
                "kind": "pin_digital",
                "target": "ALARM_LED_PIN",
                "outcome": "FAIL",
                "message": "ALARM_LED_PIN at final state: expected 1, observed 0",
            }
        ],
        "observed": {"final_pins": {"ALARM_LED_PIN": {"digital": 0}}},
        "serial_log": "TEMP=45.00,FAN=0,HEATER=0,ALARM=0,STATE=IDLE",
        "trace": [],
    }

    res = await analyzer.analyze(
        source_code=buggy_firmware_source,
        test_result=test_result,
        filename="temperature_controller_buggy.ino",
        use_llm=False,
    )
    assert res.category in ("boundary-error", "logic-error")
    assert res.confidence >= 0.8
    assert len(res.suspect_lines) >= 1
    assert "TEMP_CRITICAL_C" in res.code_snippet or "alarm" in res.root_cause.lower()


@pytest.mark.asyncio
async def test_full_demo_api():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Check root web UI
        web_resp = await ac.get("/")
        assert web_resp.status_code == 200
        assert "FirmAI" in web_resp.text

        # Check health
        h_resp = await ac.get("/api/health")
        assert h_resp.status_code == 200
        assert h_resp.json()["status"] == "ok"

        # Check settings
        s_resp = await ac.get("/api/settings")
        assert s_resp.status_code == 200
        assert "available_simulators" in s_resp.json()

        # Check dashboard
        d_resp = await ac.get("/api/dashboard")
        assert d_resp.status_code == 200

        # Upload Firmware
        up_resp = await ac.post("/api/firmware/upload", json={
            "filename": "test_upload.ino",
            "source_code": "void setup() {} void loop() {}",
            "notes": "Test sketch",
        })
        assert up_resp.status_code == 200
        fw_id = up_resp.json()["id"]

        # Run Analysis
        an_resp = await ac.post(f"/api/firmware/{fw_id}/analyze")
        assert an_resp.status_code == 200

        # Run Demo
        demo_resp = await ac.post("/api/demo/run", json={"variant": "buggy", "max_tests": 5, "use_llm": False})
        assert demo_resp.status_code == 200
        demo_data = demo_resp.json()
        assert demo_data["status"] == "completed"
        assert len(demo_data["results"]) >= 3
        assert demo_data["failed"] >= 1  # Successfully caught injected bugs

        run_id = demo_data["id"]
        # Check HTML report endpoint
        report_html_resp = await ac.get(f"/api/reports/{run_id}/html")
        assert report_html_resp.status_code == 200
        assert "FirmAI Diagnostic Audit" in report_html_resp.text

        # Check JSON report endpoint
        report_json_resp = await ac.get(f"/api/reports/{run_id}")
        assert report_json_resp.status_code == 200
        assert report_json_resp.json()["verdict"] in ("FAIL", "PARTIAL")


@pytest.mark.asyncio
async def test_firmware_pipeline_strict_sequence(buggy_firmware_source):
    """
    Tests the strict 7-step sequence:
      1. Provide embedded firmware to the system
      2. AI analyses the firmware
      3. AI generates test scenarios
      4. Tests run in a virtual hardware environment
      5. Firmware behaviour is observed
      6. Failures are identified
      7. A test/debugging report is generated
    """
    from app.core.firmware_pipeline import FirmwarePipeline

    pipeline = FirmwarePipeline()
    report = await pipeline.run_pipeline(
        source_code=buggy_firmware_source,
        filename="temperature_controller_buggy.ino",
        max_tests=5,
        use_llm=False,
    )

    # Validate 7 steps recorded
    assert len(report.steps) == 7
    step_numbers = [s.step_number for s in report.steps]
    assert step_numbers == [1, 2, 3, 4, 5, 6, 7]

    # Verify Step 1: Firmware ingested
    assert report.firmware.filename == "temperature_controller_buggy.ino"
    assert report.firmware.size_bytes > 0

    # Verify Step 2: AI analysis
    assert len(report.analysis["gpio_pins"]) >= 4

    # Verify Step 3: Test scenarios synthesized
    assert len(report.suite.tests) >= 3

    # Verify Step 4 & 5: Simulation runs and behaviour observed
    assert len(report.observations) >= 3
    for obs in report.observations:
        assert "status" in obs
        assert "assertions" in obs

    # Verify Step 6: Failures identified
    assert len(report.failures) >= 1
    assert any("TEMP" in f["root_cause"] or "Fan" in f["root_cause"] or "threshold" in f["root_cause"].lower() for f in report.failures)

    # Verify Step 7: Reports generated
    assert report.verdict in ("FAIL", "PARTIAL")
    assert report.html_path is not None
    assert report.json_path is not None
    assert Path(report.html_path).exists()
    assert Path(report.json_path).exists()
