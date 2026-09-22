"""Pydantic data-transfer objects shared by the API layer."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Health / settings
# ---------------------------------------------------------------------------
class HealthOut(BaseModel):
    status: str
    version: str
    llm_enabled: bool
    llm_provider: str
    llm_model: str
    simulator_backend: str
    compiler_available: bool


class SettingsOut(BaseModel):
    llm_provider: str
    llm_model: str
    llm_enabled: bool
    llm_base_url_host: str
    simulator_backend: str
    available_simulators: list[dict[str, Any]]
    compiler: str
    compiler_available: bool
    compiler_version: str
    heuristic_fallback: bool


# ---------------------------------------------------------------------------
# Firmware
# ---------------------------------------------------------------------------
class FirmwareTextUpload(BaseModel):
    filename: str = Field(default="firmware.ino", max_length=255)
    source_code: str = Field(min_length=1)
    notes: str = ""


class FirmwareOut(ORMModel):
    id: str
    filename: str
    language: str
    size_bytes: int
    sha256: str
    origin: str
    notes: str
    created_at: datetime
    analysis_count: int = 0
    suite_count: int = 0
    run_count: int = 0


class FirmwareDetailOut(FirmwareOut):
    source_code: str
    latest_analysis_id: str | None = None
    latest_suite_id: str | None = None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    force: bool = False


class AnalysisOut(ORMModel):
    id: str
    firmware_id: str
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    gpio_pins: list[dict[str, Any]]
    constants: list[dict[str, Any]]
    thresholds: list[dict[str, Any]]
    states: list[dict[str, Any]]
    conditions: list[dict[str, Any]]
    functions: list[dict[str, Any]]
    serial_prints: list[dict[str, Any]]
    peripherals: list[dict[str, Any]]
    risk_areas: list[dict[str, Any]]
    metrics: dict[str, Any]
    signal_map: dict[str, Any]
    summary: str
    analyzer_version: str
    duration_ms: float
    created_at: datetime


# ---------------------------------------------------------------------------
# Test generation
# ---------------------------------------------------------------------------
class TestGenerateRequest(BaseModel):
    firmware_id: str
    analysis_id: str | None = None
    max_tests: int = Field(default=10, ge=1, le=40)
    focus: str = ""
    use_llm: bool = True


class TestCaseOut(ORMModel):
    id: str
    test_id: str
    name: str
    description: str
    category: str
    priority: str
    requirement: str
    rationale: str
    derived_from: list[str]
    stimulus: dict[str, Any]
    expectations: list[dict[str, Any]]
    timeout_ms: int
    order_index: int


class TestSuiteOut(ORMModel):
    id: str
    firmware_id: str
    analysis_id: str | None
    name: str
    strategy_notes: str
    coverage_notes: str
    generator_engine: str
    generator_model: str
    generation_ms: float
    created_at: datetime
    cases: list[TestCaseOut] = []


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
class RunRequest(BaseModel):
    suite_id: str
    simulator_backend: str | None = None
    auto_analyze_failures: bool = True


class TestResultOut(ORMModel):
    id: str
    run_id: str
    case_id: str
    test_id: str
    name: str
    category: str
    priority: str
    rationale: str
    status: str
    stimulus: dict[str, Any]
    expectations: list[dict[str, Any]]
    assertions: list[dict[str, Any]]
    observed: dict[str, Any]
    serial_log: str
    trace: list[dict[str, Any]]
    duration_ms: float
    error_message: str
    order_index: int
    failure_analysis: "FailureAnalysisOut | None" = None


class TestRunSummaryOut(ORMModel):
    id: str
    firmware_id: str
    suite_id: str
    status: str
    stage: str
    progress: float
    simulator_backend: str
    execution_mode: str
    total: int
    passed: int
    failed: int
    errored: int
    skipped: int
    pass_rate: float
    duration_ms: float
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str
    is_demo: bool


class TestRunOut(TestRunSummaryOut):
    build_log: str
    firmware_filename: str = ""
    results: list[TestResultOut] = []


# ---------------------------------------------------------------------------
# Failure analysis
# ---------------------------------------------------------------------------
class FailureAnalyzeRequest(BaseModel):
    run_id: str | None = None
    result_id: str | None = None
    force: bool = False


class FailureAnalysisOut(ORMModel):
    id: str
    result_id: str
    run_id: str
    root_cause: str
    explanation: str
    category: str
    severity: str
    confidence: float
    suspect_lines: list[int]
    code_snippet: str
    suggested_fix: str
    fix_diff: str
    evidence: list[str]
    engine: str
    model: str
    duration_ms: float
    created_at: datetime


# ---------------------------------------------------------------------------
# Reports / dashboard
# ---------------------------------------------------------------------------
class ReportOut(BaseModel):
    run_id: str
    generated_at: datetime
    firmware: dict[str, Any]
    summary: dict[str, Any]
    coverage: dict[str, Any]
    results: list[dict[str, Any]]
    failures: list[dict[str, Any]]
    recommendations: list[str]
    verdict: Literal["PASS", "FAIL", "PARTIAL", "ERROR"]
    html_url: str
    json_url: str


class DashboardStats(BaseModel):
    firmware_count: int
    suite_count: int
    test_case_count: int
    run_count: int
    total_tests_executed: int
    total_passed: int
    total_failed: int
    total_errored: int
    overall_pass_rate: float
    open_failures: int
    ai_analyses: int
    recent_runs: list[TestRunSummaryOut]
    pass_rate_trend: list[dict[str, Any]]
    category_breakdown: list[dict[str, Any]]
    severity_breakdown: list[dict[str, Any]]
    status_distribution: list[dict[str, Any]]


class DemoRunRequest(BaseModel):
    variant: Literal["buggy", "golden"] = "buggy"
    use_llm: bool = True
    max_tests: int = 8


TestResultOut.model_rebuild()
