"""
FirmAI Main FastAPI Application
================================
Autonomous Embedded C/C++ Firmware Testing Agent API.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy import delete, desc, func, select
from sqlalchemy.orm import Session, selectinload

from app.analyzers.firmware_analyzer import analyze_source
from app.core.config import DATA_DIR, EXAMPLES_DIR, UPLOAD_DIR, WORKSPACE_DIR, settings
from app.core.database import get_db, init_db
from app.failure_analyzer.root_cause import get_failure_analyzer
from app.llm.client import get_llm_client
from app.models.entities import (
    AnalysisResult,
    FailureAnalysis,
    Firmware,
    TestCase,
    TestResult,
    TestRun,
    TestSuite,
)
from app.reports.reporter import get_report_generator
from app.schemas.dto import (
    AnalysisOut,
    AnalyzeRequest,
    DashboardStats,
    DemoRunRequest,
    FailureAnalysisOut,
    FailureAnalyzeRequest,
    FirmwareDetailOut,
    FirmwareOut,
    FirmwareTextUpload,
    HealthOut,
    ReportOut,
    RunRequest,
    SettingsOut,
    TestCaseOut,
    TestGenerateRequest,
    TestResultOut,
    TestRunOut,
    TestRunSummaryOut,
    TestSuiteOut,
)
from app.simulator.base import SimulatorUnavailable
from app.simulator.evaluator import TestEvaluator
from app.simulator.manager import get_simulator_manager
from app.test_generator.generator import TestGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("firmwareai.api")

SUPPORTED_FIRMWARE_SUFFIXES = {".ino", ".cpp", ".c", ".h", ".hpp"}


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database...")
    init_db()
    logger.info("FirmAI backend initialized successfully.")
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Autonomous Embedded Firmware Testing Agent",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mount static files & web root
STATIC_DIR = Path(__file__).resolve().parent / "static"
if STATIC_DIR.exists():
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    if (STATIC_DIR / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.exception_handler(SimulatorUnavailable)
async def simulator_unavailable_handler(request: Request, exc: SimulatorUnavailable):
    logger.warning("Simulator unavailable for %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc), "code": "SIMULATOR_UNAVAILABLE"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.info("Invalid request payload for %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Invalid request payload.",
            "code": "VALIDATION_ERROR",
            "errors": jsonable_encoder(exc.errors()),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled backend error for %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": str(exc) or "Internal backend error.", "code": "BACKEND_ERROR"},
    )


@app.get("/", response_class=HTMLResponse, tags=["Web UI"])
async def serve_web_ui():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"), media_type="text/html")
    return HTMLResponse(content="<h1>FirmAI Backend Running</h1><p>API documentation available at <a href='/docs'>/docs</a></p>")


@app.get("/favicon.svg", include_in_schema=False)
async def serve_favicon():
    fav = STATIC_DIR / "favicon.svg"
    if fav.exists():
        return FileResponse(str(fav), media_type="image/svg+xml")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Health & Diagnostics
# ---------------------------------------------------------------------------
@app.get(f"{settings.api_prefix}/health", response_model=HealthOut, tags=["System"])
async def health():
    llm = get_llm_client()
    compiler_path = shutil.which(settings.cxx_compiler)
    return HealthOut(
        status="ok",
        version=settings.app_version,
        llm_enabled=llm.available and llm.provider != "mock",
        llm_provider=llm.provider,
        llm_model=llm.model,
        simulator_backend=settings.simulator_backend,
        compiler_available=bool(compiler_path),
    )


@app.get(f"{settings.api_prefix}/settings", response_model=SettingsOut, tags=["System"])
async def get_system_settings():
    llm = get_llm_client()
    sim_mgr = get_simulator_manager()
    compiler_path = shutil.which(settings.cxx_compiler)
    return SettingsOut(
        llm_provider=llm.provider,
        llm_model=llm.model,
        llm_enabled=llm.available and llm.provider != "mock",
        llm_base_url_host=settings.resolved_llm_base_url,
        simulator_backend=settings.simulator_backend,
        available_simulators=sim_mgr.describe_all(),
        compiler=settings.cxx_compiler,
        compiler_available=bool(compiler_path),
        compiler_version=f"{settings.cxx_compiler} (detected: {bool(compiler_path)})",
        heuristic_fallback=settings.llm_allow_heuristic_fallback,
    )


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------
@app.get(f"{settings.api_prefix}/dashboard", response_model=DashboardStats, tags=["Dashboard"])
async def get_dashboard(db: Session = Depends(get_db)):
    fw_count = db.execute(select(func.count(Firmware.id))).scalar() or 0
    suite_count = db.execute(select(func.count(TestSuite.id))).scalar() or 0
    case_count = db.execute(select(func.count(TestCase.id))).scalar() or 0
    run_count = db.execute(select(func.count(TestRun.id))).scalar() or 0

    total_exec = db.execute(select(func.count(TestResult.id))).scalar() or 0
    total_pass = db.execute(select(func.count(TestResult.id)).where(TestResult.status == "PASS")).scalar() or 0
    total_fail = db.execute(select(func.count(TestResult.id)).where(TestResult.status == "FAIL")).scalar() or 0
    total_err = db.execute(select(func.count(TestResult.id)).where(TestResult.status == "ERROR")).scalar() or 0

    overall_pass_rate = round((total_pass / total_exec * 100.0), 1) if total_exec > 0 else 0.0
    open_failures = total_fail + total_err
    ai_analyses_count = db.execute(select(func.count(FailureAnalysis.id))).scalar() or 0

    recent_runs_res = db.execute(
        select(TestRun).order_by(desc(TestRun.created_at)).limit(10)
    )
    recent_runs = [TestRunSummaryOut.model_validate(r) for r in recent_runs_res.scalars().all()]

    # Categories breakdown
    cat_res = db.execute(
        select(TestResult.category, func.count(TestResult.id), func.count(TestResult.id).filter(TestResult.status == "PASS"))
        .group_by(TestResult.category)
    )
    category_breakdown = [
        {"category": row[0] or "functional", "total": row[1], "passed": row[2], "failed": row[1] - row[2]}
        for row in cat_res.all()
    ]

    # Severity breakdown
    sev_res = db.execute(
        select(FailureAnalysis.severity, func.count(FailureAnalysis.id))
        .group_by(FailureAnalysis.severity)
    )
    severity_breakdown = [
        {"severity": row[0] or "medium", "count": row[1]}
        for row in sev_res.all()
    ]

    status_distribution = [
        {"status": "PASS", "count": total_pass, "color": "#10b981"},
        {"status": "FAIL", "count": total_fail, "color": "#ef4444"},
        {"status": "ERROR", "count": total_err, "color": "#f59e0b"},
    ]

    pass_rate_trend = [
        {"run_id": r.id[:8], "date": r.created_at.strftime("%H:%M:%S"), "pass_rate": r.pass_rate}
        for r in reversed(recent_runs[:8])
    ]

    return DashboardStats(
        firmware_count=fw_count,
        suite_count=suite_count,
        test_case_count=case_count,
        run_count=run_count,
        total_tests_executed=total_exec,
        total_passed=total_pass,
        total_failed=total_fail,
        total_errored=total_err,
        overall_pass_rate=overall_pass_rate,
        open_failures=open_failures,
        ai_analyses=ai_analyses_count,
        recent_runs=recent_runs,
        pass_rate_trend=pass_rate_trend,
        category_breakdown=category_breakdown,
        severity_breakdown=severity_breakdown,
        status_distribution=status_distribution,
    )


# ---------------------------------------------------------------------------
# Firmware Endpoints
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/firmware/upload", response_model=FirmwareOut, tags=["Firmware"])
async def upload_firmware(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await _read_firmware_payload(request)
    firmware = _create_firmware_record(db, payload, commit=True)

    return FirmwareOut(
        id=firmware.id,
        filename=firmware.filename,
        language=firmware.language,
        size_bytes=firmware.size_bytes,
        sha256=firmware.sha256,
        origin=firmware.origin,
        notes=firmware.notes,
        created_at=firmware.created_at,
        analysis_count=0,
        suite_count=0,
        run_count=0,
    )


@app.get(f"{settings.api_prefix}/firmware", response_model=list[FirmwareOut], tags=["Firmware"])
async def list_firmware(db: Session = Depends(get_db)):
    result = db.execute(
        select(Firmware).options(
            selectinload(Firmware.analyses),
            selectinload(Firmware.suites),
            selectinload(Firmware.runs),
        ).order_by(desc(Firmware.created_at))
    )
    firmwares = result.scalars().all()
    return [
        FirmwareOut(
            id=f.id,
            filename=f.filename,
            language=f.language,
            size_bytes=f.size_bytes,
            sha256=f.sha256,
            origin=f.origin,
            notes=f.notes,
            created_at=f.created_at,
            analysis_count=len(f.analyses),
            suite_count=len(f.suites),
            run_count=len(f.runs),
        )
        for f in firmwares
    ]


@app.get(f"{settings.api_prefix}/firmware/{{firmware_id}}", response_model=FirmwareDetailOut, tags=["Firmware"])
async def get_firmware(firmware_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        select(Firmware)
        .options(
            selectinload(Firmware.analyses),
            selectinload(Firmware.suites),
            selectinload(Firmware.runs),
        )
        .where(Firmware.id == firmware_id)
    )
    firmware = result.scalar_one_or_none()
    if not firmware:
        raise HTTPException(status_code=404, detail="Firmware not found.")

    latest_analysis = firmware.analyses[-1].id if firmware.analyses else None
    latest_suite = firmware.suites[-1].id if firmware.suites else None

    return FirmwareDetailOut(
        id=firmware.id,
        filename=firmware.filename,
        language=firmware.language,
        size_bytes=firmware.size_bytes,
        sha256=firmware.sha256,
        origin=firmware.origin,
        notes=firmware.notes,
        created_at=firmware.created_at,
        analysis_count=len(firmware.analyses),
        suite_count=len(firmware.suites),
        run_count=len(firmware.runs),
        source_code=firmware.source_code,
        latest_analysis_id=latest_analysis,
        latest_suite_id=latest_suite,
    )


@app.delete(f"{settings.api_prefix}/firmware/{{firmware_id}}", tags=["Firmware"])
async def delete_firmware(firmware_id: str, db: Session = Depends(get_db)):
    result = db.execute(select(Firmware).where(Firmware.id == firmware_id))
    firmware = result.scalar_one_or_none()
    if not firmware:
        raise HTTPException(status_code=404, detail="Firmware not found.")
    db.delete(firmware)
    db.commit()
    return {"message": "Firmware deleted successfully"}


# ---------------------------------------------------------------------------
# Static Analysis Endpoints
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/firmware/{{firmware_id}}/analyze", response_model=AnalysisOut, tags=["Analysis"])
async def analyze_firmware(
    firmware_id: str,
    req: AnalyzeRequest | None = None,
    db: Session = Depends(get_db),
):
    result = db.execute(select(Firmware).where(Firmware.id == firmware_id))
    firmware = result.scalar_one_or_none()
    if not firmware:
        raise HTTPException(status_code=404, detail="Firmware not found.")

    # Check if existing analysis is cached
    if req and not req.force:
        cached = db.execute(
            select(AnalysisResult)
            .where(AnalysisResult.firmware_id == firmware_id)
            .order_by(desc(AnalysisResult.created_at))
        )
        existing = cached.scalars().first()
        if existing:
            return AnalysisOut.model_validate(existing)

    t0 = time.perf_counter()
    extracted = analyze_source(firmware.source_code, firmware.filename)
    duration_ms = round((time.perf_counter() - t0) * 1000, 2)

    analysis = AnalysisResult(
        firmware_id=firmware.id,
        inputs=extracted["inputs"],
        outputs=extracted["outputs"],
        gpio_pins=extracted["gpio_pins"],
        constants=extracted["constants"],
        thresholds=extracted["thresholds"],
        states=extracted["states"],
        conditions=extracted["conditions"],
        functions=extracted["functions"],
        serial_prints=extracted["serial_prints"],
        peripherals=extracted["peripherals"],
        risk_areas=extracted["risk_areas"],
        metrics=extracted["metrics"],
        signal_map=extracted["signal_map"],
        summary=extracted["summary"],
        analyzer_version=extracted.get("analyzer_version", "1.2.0"),
        duration_ms=duration_ms,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return AnalysisOut.model_validate(analysis)


@app.get(f"{settings.api_prefix}/firmware/{{firmware_id}}/analyses", response_model=list[AnalysisOut], tags=["Analysis"])
async def get_firmware_analyses(firmware_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.firmware_id == firmware_id)
        .order_by(desc(AnalysisResult.created_at))
    )
    analyses = result.scalars().all()
    return [AnalysisOut.model_validate(a) for a in analyses]


# ---------------------------------------------------------------------------
# Test Generation Endpoints
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/tests/generate", response_model=TestSuiteOut, tags=["Test Generation"])
async def generate_tests(req: TestGenerateRequest, db: Session = Depends(get_db)):
    fw_res = db.execute(select(Firmware).where(Firmware.id == req.firmware_id))
    firmware = fw_res.scalar_one_or_none()
    if not firmware:
        raise HTTPException(status_code=404, detail="Firmware not found.")

    # Get analysis
    if req.analysis_id:
        an_res = db.execute(select(AnalysisResult).where(AnalysisResult.id == req.analysis_id))
        analysis = an_res.scalar_one_or_none()
    else:
        an_res = db.execute(
            select(AnalysisResult)
            .where(AnalysisResult.firmware_id == req.firmware_id)
            .order_by(desc(AnalysisResult.created_at))
        )
        analysis = an_res.scalars().first()

    if not analysis:
        # Run static analysis on the fly
        extracted = analyze_source(firmware.source_code, firmware.filename)
        analysis = AnalysisResult(
            firmware_id=firmware.id,
            inputs=extracted["inputs"],
            outputs=extracted["outputs"],
            gpio_pins=extracted["gpio_pins"],
            constants=extracted["constants"],
            thresholds=extracted["thresholds"],
            states=extracted["states"],
            conditions=extracted["conditions"],
            functions=extracted["functions"],
            serial_prints=extracted["serial_prints"],
            peripherals=extracted["peripherals"],
            risk_areas=extracted["risk_areas"],
            metrics=extracted["metrics"],
            signal_map=extracted["signal_map"],
            summary=extracted["summary"],
            duration_ms=10.0,
        )
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

    analysis_payload = {
        "inputs": analysis.inputs,
        "outputs": analysis.outputs,
        "gpio_pins": analysis.gpio_pins,
        "constants": analysis.constants,
        "thresholds": analysis.thresholds,
        "states": analysis.states,
        "conditions": analysis.conditions,
        "functions": analysis.functions,
        "serial_prints": analysis.serial_prints,
        "peripherals": analysis.peripherals,
        "risk_areas": analysis.risk_areas,
        "metrics": analysis.metrics,
        "signal_map": analysis.signal_map,
    }

    generator = TestGenerator()
    generated = await generator.generate(
        source=firmware.source_code,
        analysis=analysis_payload,
        filename=firmware.filename,
        max_tests=req.max_tests,
        focus=req.focus,
        use_llm=req.use_llm,
    )

    suite = TestSuite(
        firmware_id=firmware.id,
        analysis_id=analysis.id,
        name=generated.name,
        strategy_notes=generated.strategy_notes,
        coverage_notes=generated.coverage_notes,
        generator_engine=generated.engine,
        generator_model=generated.model,
        generation_ms=generated.generation_ms,
        raw_llm_response=generated.raw_response,
    )
    db.add(suite)
    db.flush()

    for idx, tc in enumerate(generated.tests):
        case = TestCase(
            suite_id=suite.id,
            order_index=idx,
            test_id=tc.get("test_id", f"TC-{idx + 1:03d}"),
            name=tc.get("name", f"Test {idx + 1}"),
            description=tc.get("description", ""),
            category=tc.get("category", "functional"),
            priority=tc.get("priority", "medium"),
            requirement=tc.get("requirement", ""),
            rationale=tc.get("rationale", ""),
            derived_from=tc.get("derived_from", []),
            stimulus=tc.get("stimulus", {}),
            expectations=tc.get("expectations", []),
            timeout_ms=tc.get("timeout_ms", 5000),
        )
        db.add(case)

    db.commit()
    db.refresh(suite)

    # Return with loaded test cases
    suite_res = db.execute(
        select(TestSuite).options(selectinload(TestSuite.cases)).where(TestSuite.id == suite.id)
    )
    loaded_suite = suite_res.scalar_one()
    return TestSuiteOut.model_validate(loaded_suite)


@app.get(f"{settings.api_prefix}/tests/suites/{{suite_id}}", response_model=TestSuiteOut, tags=["Test Generation"])
async def get_test_suite(suite_id: str, db: Session = Depends(get_db)):
    suite_res = db.execute(
        select(TestSuite).options(selectinload(TestSuite.cases)).where(TestSuite.id == suite_id)
    )
    suite = suite_res.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=404, detail="Test suite not found.")
    return TestSuiteOut.model_validate(suite)


# ---------------------------------------------------------------------------
# Test Execution Endpoints
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/tests/run", response_model=TestRunOut, tags=["Execution"])
async def run_test_suite(req: RunRequest, db: Session = Depends(get_db)):
    suite_res = db.execute(
        select(TestSuite).options(selectinload(TestSuite.cases)).where(TestSuite.id == req.suite_id)
    )
    suite = suite_res.scalar_one_or_none()
    if not suite:
        raise HTTPException(status_code=404, detail="Test suite not found.")

    fw_res = db.execute(select(Firmware).where(Firmware.id == suite.firmware_id))
    firmware = fw_res.scalar_one_or_none()
    if not firmware:
        raise HTTPException(status_code=404, detail="Target firmware not found.")

    # Latest analysis
    an_res = db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.firmware_id == firmware.id)
        .order_by(desc(AnalysisResult.created_at))
    )
    analysis = an_res.scalars().first()
    signal_map = analysis.signal_map if analysis else {}

    sim_mgr = get_simulator_manager()
    backend_name = req.simulator_backend or settings.simulator_backend
    simulator = sim_mgr.get(backend_name)

    # Initialize TestRun
    t0 = time.perf_counter()
    test_run = TestRun(
        firmware_id=firmware.id,
        suite_id=suite.id,
        status="running",
        stage="building",
        progress=0.1,
        simulator_backend=simulator.name,
        execution_mode=simulator.execution_mode,
        total=len(suite.cases),
        started_at=datetime.now(timezone.utc),
    )
    db.add(test_run)
    db.commit()
    db.refresh(test_run)

    # Build firmware artifact
    ws_dir = WORKSPACE_DIR / f"run_{test_run.id}"
    ws_dir.mkdir(parents=True, exist_ok=True)
    build_artifact = await simulator.build(firmware.source_code, str(ws_dir), firmware.filename)
    test_run.build_log = build_artifact.log

    evaluator = TestEvaluator()
    results_to_save: list[TestResult] = []
    passed = 0
    failed = 0
    errored = 0
    skipped = 0

    test_run.stage = "running"
    db.commit()

    for idx, case in enumerate(suite.cases):
        case_dict = {
            "test_id": case.test_id,
            "name": case.name,
            "stimulus": case.stimulus,
            "expectations": case.expectations,
            "timeout_ms": case.timeout_ms,
        }
        sim_req = sim_mgr.compile_request(case_dict, signal_map)
        exec_res = await simulator.execute(build_artifact, sim_req)
        evaluation = evaluator.evaluate(case_dict, exec_res, signal_map)

        st = evaluation["status"]
        if st == "PASS":
            passed += 1
        elif st == "FAIL":
            failed += 1
        elif st == "ERROR":
            errored += 1
        else:
            skipped += 1

        tr = TestResult(
            run_id=test_run.id,
            case_id=case.id,
            order_index=idx,
            test_id=case.test_id,
            name=case.name,
            category=case.category,
            priority=case.priority,
            rationale=case.rationale,
            status=st,
            stimulus=case.stimulus,
            expectations=case.expectations,
            assertions=evaluation["assertions"],
            observed=evaluation["observed"],
            serial_log=evaluation["serial_log"],
            trace=evaluation["trace"],
            duration_ms=exec_res.wall_ms,
            error_message=evaluation["error_message"],
        )
        db.add(tr)
        results_to_save.append(tr)

    db.flush()

    # Automatic failure analysis
    if req.auto_analyze_failures and (failed > 0 or errored > 0):
        test_run.stage = "analyzing"
        db.commit()

        failure_analyzer = get_failure_analyzer()
        for tr in results_to_save:
            if tr.status in ("FAIL", "ERROR"):
                case_info = next((c for c in suite.cases if c.id == tr.case_id or c.test_id == tr.test_id), None)
                fa_res = await failure_analyzer.analyze(
                    source_code=firmware.source_code,
                    test_result={
                        "test_id": tr.test_id,
                        "name": tr.name,
                        "category": tr.category,
                        "rationale": tr.rationale,
                        "assertions": tr.assertions,
                        "observed": tr.observed,
                        "serial_log": tr.serial_log,
                        "trace": tr.trace,
                    },
                    filename=firmware.filename,
                    case_info={"requirement": case_info.requirement if case_info else ""},
                )
                fa_entity = FailureAnalysis(
                    result_id=tr.id,
                    run_id=test_run.id,
                    root_cause=fa_res.root_cause,
                    explanation=fa_res.explanation,
                    category=fa_res.category,
                    severity=fa_res.severity,
                    confidence=fa_res.confidence,
                    suspect_lines=fa_res.suspect_lines,
                    code_snippet=fa_res.code_snippet,
                    suggested_fix=fa_res.suggested_fix,
                    fix_diff=fa_res.fix_diff,
                    evidence=fa_res.evidence,
                    engine=fa_res.engine,
                    model=fa_res.model,
                    duration_ms=fa_res.duration_ms,
                )
                db.add(fa_entity)

    # Wrap up TestRun
    total = len(suite.cases)
    pass_rate = round((passed / total * 100.0), 1) if total > 0 else 0.0
    duration_ms = round((time.perf_counter() - t0) * 1000, 2)

    test_run.status = "completed"
    test_run.stage = "completed"
    test_run.progress = 1.0
    test_run.passed = passed
    test_run.failed = failed
    test_run.errored = errored
    test_run.skipped = skipped
    test_run.pass_rate = pass_rate
    test_run.duration_ms = duration_ms
    test_run.finished_at = datetime.now(timezone.utc)

    db.commit()

    loaded_run = _get_full_test_run(test_run.id, db)
    _save_report_safely(
        run_id=test_run.id,
        run_data=loaded_run,
        firmware_data={"id": firmware.id, "filename": firmware.filename, "size_bytes": firmware.size_bytes, "sha256": firmware.sha256},
        analysis_data={"metrics": analysis.metrics if analysis else {}, "gpio_pins": analysis.gpio_pins if analysis else []},
    )

    return TestRunOut(
        id=test_run.id,
        firmware_id=test_run.firmware_id,
        suite_id=test_run.suite_id,
        status=test_run.status,
        stage=test_run.stage,
        progress=test_run.progress,
        simulator_backend=test_run.simulator_backend,
        execution_mode=test_run.execution_mode,
        total=test_run.total,
        passed=test_run.passed,
        failed=test_run.failed,
        errored=test_run.errored,
        skipped=test_run.skipped,
        pass_rate=test_run.pass_rate,
        duration_ms=test_run.duration_ms,
        created_at=test_run.created_at,
        started_at=test_run.started_at,
        finished_at=test_run.finished_at,
        error_message=test_run.error_message,
        is_demo=bool(test_run.is_demo),
        build_log=test_run.build_log,
        firmware_filename=firmware.filename,
        results=[TestResultOut.model_validate(r) for r in loaded_run["results_entities"]],
    )


@app.get(f"{settings.api_prefix}/tests/runs/{{run_id}}", response_model=TestRunOut, tags=["Execution"])
async def get_test_run(run_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        select(TestRun)
        .options(
            selectinload(TestRun.firmware),
            selectinload(TestRun.results).selectinload(TestResult.failure_analysis),
        )
        .where(TestRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    return TestRunOut(
        id=run.id,
        firmware_id=run.firmware_id,
        suite_id=run.suite_id,
        status=run.status,
        stage=run.stage,
        progress=run.progress,
        simulator_backend=run.simulator_backend,
        execution_mode=run.execution_mode,
        total=run.total,
        passed=run.passed,
        failed=run.failed,
        errored=run.errored,
        skipped=run.skipped,
        pass_rate=run.pass_rate,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        error_message=run.error_message,
        is_demo=bool(run.is_demo),
        build_log=run.build_log,
        firmware_filename=run.firmware.filename if run.firmware else "",
        results=[TestResultOut.model_validate(r) for r in run.results],
    )


@app.get(f"{settings.api_prefix}/tests/runs/{{run_id}}/status", response_model=TestRunSummaryOut, tags=["Execution"])
async def get_test_run_status(run_id: str, db: Session = Depends(get_db)):
    result = db.execute(select(TestRun).where(TestRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")
    return TestRunSummaryOut.model_validate(run)


# ---------------------------------------------------------------------------
# Failure Analysis Endpoints
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/failures/{{run_id}}/analyze", response_model=list[FailureAnalysisOut], tags=["Failures"])
async def analyze_failures(
    run_id: str,
    req: FailureAnalyzeRequest | None = None,
    db: Session = Depends(get_db),
):
    run_res = db.execute(
        select(TestRun)
        .options(
            selectinload(TestRun.firmware),
            selectinload(TestRun.results).selectinload(TestResult.failure_analysis),
        )
        .where(TestRun.id == run_id)
    )
    run = run_res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    analyzer = get_failure_analyzer()
    out: list[FailureAnalysisOut] = []

    for tr in run.results:
        if tr.status in ("FAIL", "ERROR"):
            if tr.failure_analysis and req and not req.force:
                out.append(FailureAnalysisOut.model_validate(tr.failure_analysis))
                continue

            fa_res = await analyzer.analyze(
                source_code=run.firmware.source_code,
                test_result={
                    "test_id": tr.test_id,
                    "name": tr.name,
                    "category": tr.category,
                    "rationale": tr.rationale,
                    "assertions": tr.assertions,
                    "observed": tr.observed,
                    "serial_log": tr.serial_log,
                    "trace": tr.trace,
                },
                filename=run.firmware.filename,
            )
            fa = FailureAnalysis(
                result_id=tr.id,
                run_id=run.id,
                root_cause=fa_res.root_cause,
                explanation=fa_res.explanation,
                category=fa_res.category,
                severity=fa_res.severity,
                confidence=fa_res.confidence,
                suspect_lines=fa_res.suspect_lines,
                code_snippet=fa_res.code_snippet,
                suggested_fix=fa_res.suggested_fix,
                fix_diff=fa_res.fix_diff,
                evidence=fa_res.evidence,
                engine=fa_res.engine,
                model=fa_res.model,
                duration_ms=fa_res.duration_ms,
            )
            db.add(fa)
            db.flush()
            out.append(FailureAnalysisOut.model_validate(fa))

    db.commit()
    return out


@app.get(f"{settings.api_prefix}/failures/{{run_id}}", response_model=list[FailureAnalysisOut], tags=["Failures"])
async def get_failures(run_id: str, db: Session = Depends(get_db)):
    result = db.execute(
        select(FailureAnalysis).where(FailureAnalysis.run_id == run_id)
    )
    analyses = result.scalars().all()
    return [FailureAnalysisOut.model_validate(fa) for fa in analyses]


# ---------------------------------------------------------------------------
# Reports Endpoints
# ---------------------------------------------------------------------------
@app.get(f"{settings.api_prefix}/reports/{{run_id}}", response_model=ReportOut, tags=["Reports"])
async def get_report_json(run_id: str, db: Session = Depends(get_db)):
    loaded_run = _get_full_test_run(run_id, db)
    if not loaded_run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    fw_res = db.execute(select(Firmware).where(Firmware.id == loaded_run["firmware_id"]))
    firmware = fw_res.scalar_one_or_none()

    an_res = db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.firmware_id == loaded_run["firmware_id"])
        .order_by(desc(AnalysisResult.created_at))
    )
    analysis = an_res.scalars().first()

    reporter = get_report_generator()
    report_data = reporter.generate_report_data(
        run_data=loaded_run,
        firmware_data={"id": firmware.id if firmware else "", "filename": firmware.filename if firmware else "", "size_bytes": firmware.size_bytes if firmware else 0, "sha256": firmware.sha256 if firmware else ""},
        analysis_data={"metrics": analysis.metrics if analysis else {}, "gpio_pins": analysis.gpio_pins if analysis else []},
    )
    return ReportOut(**report_data)


@app.get(f"{settings.api_prefix}/reports/{{run_id}}/html", response_class=HTMLResponse, tags=["Reports"])
async def get_report_html(run_id: str, db: Session = Depends(get_db)):
    loaded_run = _get_full_test_run(run_id, db)
    if not loaded_run:
        raise HTTPException(status_code=404, detail="Test run not found.")

    fw_res = db.execute(select(Firmware).where(Firmware.id == loaded_run["firmware_id"]))
    firmware = fw_res.scalar_one_or_none()

    an_res = db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.firmware_id == loaded_run["firmware_id"])
        .order_by(desc(AnalysisResult.created_at))
    )
    analysis = an_res.scalars().first()

    reporter = get_report_generator()
    report_data = reporter.generate_report_data(
        run_data=loaded_run,
        firmware_data={"id": firmware.id if firmware else "", "filename": firmware.filename if firmware else "", "size_bytes": firmware.size_bytes if firmware else 0, "sha256": firmware.sha256 if firmware else ""},
        analysis_data={"metrics": analysis.metrics if analysis else {}, "gpio_pins": analysis.gpio_pins if analysis else []},
    )
    html = reporter.render_html(report_data)
    return HTMLResponse(content=html, media_type="text/html")


# ---------------------------------------------------------------------------
# Integrated System Test Orchestrator
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/pipeline/run", response_model=TestRunOut, tags=["Pipeline"])
@app.post(f"{settings.api_prefix}/ist/run", response_model=TestRunOut, tags=["IST"])
@app.post(f"{settings.api_prefix}/ingest/run", response_model=TestRunOut, tags=["IST"])
@app.post(f"{settings.api_prefix}/firmware/ingest-run", response_model=TestRunOut, tags=["IST"])
async def ingest_and_run_ist(request: Request, db: Session = Depends(get_db)):
    """
    Ingest source code and run the full integrated system test pipeline.

    Accepts the same JSON or multipart payload as `/firmware/upload`, plus:
    - max_tests: int
    - focus: str
    - use_llm: bool
    - simulator_backend: str
    - auto_analyze_failures: bool
    """
    payload = await _read_firmware_payload(request)
    max_tests = _coerce_int(payload.get("max_tests"), default=8, minimum=1, maximum=40)
    focus = str(payload.get("focus") or "")
    use_llm = _coerce_bool(payload.get("use_llm"), default=True)
    auto_analyze_failures = _coerce_bool(payload.get("auto_analyze_failures"), default=True)
    simulator_backend = payload.get("simulator_backend")

    firmware = _create_firmware_record(db, payload, commit=False)

    t0 = time.perf_counter()
    extracted = analyze_source(firmware.source_code, firmware.filename)
    analysis = AnalysisResult(
        firmware_id=firmware.id,
        inputs=extracted["inputs"],
        outputs=extracted["outputs"],
        gpio_pins=extracted["gpio_pins"],
        constants=extracted["constants"],
        thresholds=extracted["thresholds"],
        states=extracted["states"],
        conditions=extracted["conditions"],
        functions=extracted["functions"],
        serial_prints=extracted["serial_prints"],
        peripherals=extracted["peripherals"],
        risk_areas=extracted["risk_areas"],
        metrics=extracted["metrics"],
        signal_map=extracted["signal_map"],
        summary=extracted["summary"],
        analyzer_version=extracted.get("analyzer_version", "1.2.0"),
        duration_ms=round((time.perf_counter() - t0) * 1000, 2),
    )
    db.add(analysis)
    db.flush()

    generated = await TestGenerator().generate(
        source=firmware.source_code,
        analysis=extracted,
        filename=firmware.filename,
        max_tests=max_tests,
        focus=focus,
        use_llm=use_llm,
    )

    suite = TestSuite(
        firmware_id=firmware.id,
        analysis_id=analysis.id,
        name=f"IST: {generated.name}",
        strategy_notes=generated.strategy_notes,
        coverage_notes=generated.coverage_notes,
        generator_engine=generated.engine,
        generator_model=generated.model,
        generation_ms=generated.generation_ms,
        raw_llm_response=generated.raw_response,
    )
    db.add(suite)
    db.flush()

    for idx, tc in enumerate(generated.tests):
        db.add(TestCase(
            suite_id=suite.id,
            order_index=idx,
            test_id=tc.get("test_id", f"TC-{idx + 1:03d}"),
            name=tc.get("name", f"Test {idx + 1}"),
            description=tc.get("description", ""),
            category=tc.get("category", "functional"),
            priority=tc.get("priority", "medium"),
            requirement=tc.get("requirement", ""),
            rationale=tc.get("rationale", ""),
            derived_from=tc.get("derived_from", []),
            stimulus=tc.get("stimulus", {}),
            expectations=tc.get("expectations", []),
            timeout_ms=tc.get("timeout_ms", 5000),
        ))

    db.flush()
    return await run_test_suite(
        RunRequest(
            suite_id=suite.id,
            simulator_backend=str(simulator_backend) if simulator_backend else None,
            auto_analyze_failures=auto_analyze_failures,
        ),
        db,
    )


# ---------------------------------------------------------------------------
# Demo End-to-End Orchestrator
# ---------------------------------------------------------------------------
@app.post(f"{settings.api_prefix}/demo/run", response_model=TestRunOut, tags=["Demo"])
async def run_demo(req: DemoRunRequest | None = None, db: Session = Depends(get_db)):
    """
    1-Click Autonomous End-to-End Demo:
    1. Loads sample firmware (temperature_controller_buggy.ino or temperature_controller.ino)
    2. Runs static AST analysis (recovering GPIOs, thresholds, FSM)
    3. Synthesizes test suite across boundary, safety, functional constraints
    4. Executes virtual simulator tests
    5. Pinpoints defects using AI Failure Analyzer
    6. Generates executive HTML audit report
    """
    variant = req.variant if req else "buggy"
    max_tests = req.max_tests if req else 8
    use_llm = req.use_llm if req else True

    filename = (
        "temperature_controller_buggy.ino"
        if variant == "buggy"
        else "temperature_controller.ino"
    )
    sample_path = EXAMPLES_DIR / filename
    if not sample_path.exists():
        raise HTTPException(status_code=500, detail=f"Sample file `{filename}` not found in `{EXAMPLES_DIR}`.")

    source_code = sample_path.read_text(encoding="utf-8")
    size_bytes = len(source_code.encode("utf-8"))
    sha256 = hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    firmware = Firmware(
        filename=filename,
        language="arduino-cpp",
        size_bytes=size_bytes,
        sha256=sha256,
        source_code=source_code,
        origin="demo",
        notes="Automated Demo Run Instance",
    )
    db.add(firmware)
    db.flush()

    # Step 1: Static Analysis
    extracted = analyze_source(source_code, filename)
    analysis = AnalysisResult(
        firmware_id=firmware.id,
        inputs=extracted["inputs"],
        outputs=extracted["outputs"],
        gpio_pins=extracted["gpio_pins"],
        constants=extracted["constants"],
        thresholds=extracted["thresholds"],
        states=extracted["states"],
        conditions=extracted["conditions"],
        functions=extracted["functions"],
        serial_prints=extracted["serial_prints"],
        peripherals=extracted["peripherals"],
        risk_areas=extracted["risk_areas"],
        metrics=extracted["metrics"],
        signal_map=extracted["signal_map"],
        summary=extracted["summary"],
        duration_ms=12.0,
    )
    db.add(analysis)
    db.flush()

    # Step 2: Test Generation
    test_gen = TestGenerator()
    generated = await test_gen.generate(
        source=source_code,
        analysis=extracted,
        filename=filename,
        max_tests=max_tests,
        use_llm=use_llm,
    )

    suite = TestSuite(
        firmware_id=firmware.id,
        analysis_id=analysis.id,
        name=f"Demo: {generated.name}",
        strategy_notes=generated.strategy_notes,
        coverage_notes=generated.coverage_notes,
        generator_engine=generated.engine,
        generator_model=generated.model,
        generation_ms=generated.generation_ms,
        raw_llm_response=generated.raw_response,
    )
    db.add(suite)
    db.flush()

    case_entities = []
    for idx, tc in enumerate(generated.tests):
        case = TestCase(
            suite_id=suite.id,
            order_index=idx,
            test_id=tc.get("test_id", f"TC-{idx + 1:03d}"),
            name=tc.get("name", f"Test {idx + 1}"),
            description=tc.get("description", ""),
            category=tc.get("category", "functional"),
            priority=tc.get("priority", "medium"),
            requirement=tc.get("requirement", ""),
            rationale=tc.get("rationale", ""),
            derived_from=tc.get("derived_from", []),
            stimulus=tc.get("stimulus", {}),
            expectations=tc.get("expectations", []),
            timeout_ms=tc.get("timeout_ms", 5000),
        )
        db.add(case)
        case_entities.append(case)

    db.flush()

    # Step 3: Virtual Hardware Simulation Run
    sim_mgr = get_simulator_manager()
    simulator = sim_mgr.get(settings.simulator_backend)

    ws_dir = WORKSPACE_DIR / f"demo_run_{int(time.time())}"
    ws_dir.mkdir(parents=True, exist_ok=True)
    build_artifact = await simulator.build(source_code, str(ws_dir), filename)

    t_run_start = time.perf_counter()
    test_run = TestRun(
        firmware_id=firmware.id,
        suite_id=suite.id,
        status="running",
        stage="running",
        progress=0.3,
        simulator_backend=simulator.name,
        execution_mode=simulator.execution_mode,
        total=len(case_entities),
        started_at=datetime.now(timezone.utc),
        is_demo=True,
        build_log=build_artifact.log,
    )
    db.add(test_run)
    db.flush()

    evaluator = TestEvaluator()
    results_to_save: list[TestResult] = []
    passed = 0
    failed = 0
    errored = 0

    for idx, case in enumerate(case_entities):
        case_dict = {
            "test_id": case.test_id,
            "name": case.name,
            "stimulus": case.stimulus,
            "expectations": case.expectations,
            "timeout_ms": case.timeout_ms,
        }
        sim_req = sim_mgr.compile_request(case_dict, extracted["signal_map"])
        exec_res = await simulator.execute(build_artifact, sim_req)
        evaluation = evaluator.evaluate(case_dict, exec_res, extracted["signal_map"])

        st = evaluation["status"]
        if st == "PASS":
            passed += 1
        elif st == "FAIL":
            failed += 1
        else:
            errored += 1

        tr = TestResult(
            run_id=test_run.id,
            case_id=case.id,
            order_index=idx,
            test_id=case.test_id,
            name=case.name,
            category=case.category,
            priority=case.priority,
            rationale=case.rationale,
            status=st,
            stimulus=case.stimulus,
            expectations=case.expectations,
            assertions=evaluation["assertions"],
            observed=evaluation["observed"],
            serial_log=evaluation["serial_log"],
            trace=evaluation["trace"],
            duration_ms=exec_res.wall_ms,
            error_message=evaluation["error_message"],
        )
        db.add(tr)
        results_to_save.append(tr)

    db.flush()

    # Step 4: AI Failure Analysis for any defects discovered
    failure_analyzer = get_failure_analyzer()
    for tr in results_to_save:
        if tr.status in ("FAIL", "ERROR"):
            case_info = next((c for c in case_entities if c.test_id == tr.test_id), None)
            fa_res = await failure_analyzer.analyze(
                source_code=source_code,
                test_result={
                    "test_id": tr.test_id,
                    "name": tr.name,
                    "category": tr.category,
                    "rationale": tr.rationale,
                    "assertions": tr.assertions,
                    "observed": tr.observed,
                    "serial_log": tr.serial_log,
                    "trace": tr.trace,
                },
                filename=filename,
                case_info={"requirement": case_info.requirement if case_info else ""},
                use_llm=use_llm,
            )
            fa_entity = FailureAnalysis(
                result_id=tr.id,
                run_id=test_run.id,
                root_cause=fa_res.root_cause,
                explanation=fa_res.explanation,
                category=fa_res.category,
                severity=fa_res.severity,
                confidence=fa_res.confidence,
                suspect_lines=fa_res.suspect_lines,
                code_snippet=fa_res.code_snippet,
                suggested_fix=fa_res.suggested_fix,
                fix_diff=fa_res.fix_diff,
                evidence=fa_res.evidence,
                engine=fa_res.engine,
                model=fa_res.model,
                duration_ms=fa_res.duration_ms,
            )
            db.add(fa_entity)

    # Wrap up demo run
    total = len(case_entities)
    pass_rate = round((passed / total * 100.0), 1) if total > 0 else 0.0
    duration_ms = round((time.perf_counter() - t_run_start) * 1000, 2)

    test_run.status = "completed"
    test_run.stage = "completed"
    test_run.progress = 1.0
    test_run.passed = passed
    test_run.failed = failed
    test_run.errored = errored
    test_run.pass_rate = pass_rate
    test_run.duration_ms = duration_ms
    test_run.finished_at = datetime.now(timezone.utc)

    db.commit()

    loaded_run = _get_full_test_run(test_run.id, db)
    _save_report_safely(
        run_id=test_run.id,
        run_data=loaded_run,
        firmware_data={"id": firmware.id, "filename": filename, "size_bytes": size_bytes, "sha256": sha256},
        analysis_data={"metrics": analysis.metrics, "gpio_pins": analysis.gpio_pins},
    )

    return TestRunOut(
        id=test_run.id,
        firmware_id=test_run.firmware_id,
        suite_id=test_run.suite_id,
        status=test_run.status,
        stage=test_run.stage,
        progress=test_run.progress,
        simulator_backend=test_run.simulator_backend,
        execution_mode=test_run.execution_mode,
        total=test_run.total,
        passed=test_run.passed,
        failed=test_run.failed,
        errored=test_run.errored,
        skipped=test_run.skipped,
        pass_rate=test_run.pass_rate,
        duration_ms=test_run.duration_ms,
        created_at=test_run.created_at,
        started_at=test_run.started_at,
        finished_at=test_run.finished_at,
        error_message=test_run.error_message,
        is_demo=bool(test_run.is_demo),
        build_log=test_run.build_log,
        firmware_filename=filename,
        results=[TestResultOut.model_validate(r) for r in loaded_run["results_entities"]],
    )


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------
async def _read_firmware_payload(request: Request) -> dict[str, Any]:
    """Read firmware source from JSON or multipart form data."""
    content_type = request.headers.get("content-type", "")
    extras: dict[str, Any] = {}

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("file")
        if not uploaded_file:
            raise HTTPException(status_code=400, detail="No file uploaded in form.")
        content_bytes = await uploaded_file.read()
        source_code = content_bytes.decode(errors="replace")
        filename = getattr(uploaded_file, "filename", "firmware.ino") or "firmware.ino"
        notes = str(form.get("notes") or f"Uploaded file: {filename}")
        origin = str(form.get("origin") or "upload")
        for key in ("max_tests", "focus", "use_llm", "simulator_backend", "auto_analyze_failures"):
            if key in form:
                extras[key] = form.get(key)
    else:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON or multipart payload.")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Request body must be a JSON object.")
        source_code = str(body.get("source_code", ""))
        filename = str(body.get("filename", "firmware.ino") or "firmware.ino")
        notes = str(body.get("notes", "") or "Pasted source")
        origin = str(body.get("origin", "") or "paste")
        extras = {
            key: body[key]
            for key in ("max_tests", "focus", "use_llm", "simulator_backend", "auto_analyze_failures")
            if key in body
        }

    if not source_code.strip():
        raise HTTPException(status_code=400, detail="source_code is required.")

    filename = Path(filename).name or "firmware.ino"
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_FIRMWARE_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_FIRMWARE_SUFFIXES))
        raise HTTPException(status_code=400, detail=f"Only {supported} firmware files are supported.")

    return {
        "filename": filename,
        "source_code": source_code,
        "notes": notes,
        "origin": origin,
        **extras,
    }


def _create_firmware_record(db: Session, payload: dict[str, Any], *, commit: bool) -> Firmware:
    source_code = str(payload["source_code"])
    filename = str(payload["filename"])
    size_bytes = len(source_code.encode("utf-8"))
    sha256 = hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    stored_path = UPLOAD_DIR / f"{int(time.time())}_{filename}"
    stored_path.write_text(source_code, encoding="utf-8")

    suffix = Path(filename).suffix.lower()
    firmware = Firmware(
        filename=filename,
        language="arduino-cpp" if suffix in {".ino", ".cpp", ".c", ".h", ".hpp"} else "c",
        size_bytes=size_bytes,
        sha256=sha256,
        source_code=source_code,
        stored_path=str(stored_path),
        origin=str(payload.get("origin") or "upload"),
        notes=str(payload.get("notes") or ""),
    )
    db.add(firmware)
    if commit:
        db.commit()
        db.refresh(firmware)
    else:
        db.flush()
    return firmware


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _save_report_safely(
    *,
    run_id: str,
    run_data: dict[str, Any],
    firmware_data: dict[str, Any],
    analysis_data: dict[str, Any],
) -> None:
    """Persist the HTML/JSON report without failing the completed run response."""
    try:
        reporter = get_report_generator()
        report_data = reporter.generate_report_data(
            run_data=run_data,
            firmware_data=firmware_data,
            analysis_data=analysis_data,
        )
        html_content = reporter.render_html(report_data)
        reporter.save_report(run_id, report_data, html_content)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist report for run %s", run_id)


def _get_full_test_run(run_id: str, db: Session) -> dict[str, Any]:
    result = db.execute(
        select(TestRun)
        .options(
            selectinload(TestRun.results).selectinload(TestResult.failure_analysis),
        )
        .where(TestRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        return {}

    results_data = []
    for r in run.results:
        fa = r.failure_analysis
        results_data.append({
            "id": r.id,
            "test_id": r.test_id,
            "name": r.name,
            "category": r.category,
            "priority": r.priority,
            "rationale": r.rationale,
            "status": r.status,
            "stimulus": r.stimulus,
            "expectations": r.expectations,
            "assertions": r.assertions,
            "observed": r.observed,
            "serial_log": r.serial_log,
            "duration_ms": r.duration_ms,
            "error_message": r.error_message,
            "failure_analysis": {
                "root_cause": fa.root_cause,
                "explanation": fa.explanation,
                "category": fa.category,
                "severity": fa.severity,
                "confidence": fa.confidence,
                "suspect_lines": fa.suspect_lines,
                "code_snippet": fa.code_snippet,
                "suggested_fix": fa.suggested_fix,
                "fix_diff": fa.fix_diff,
                "evidence": fa.evidence,
                "engine": fa.engine,
            } if fa else None,
        })

    return {
        "id": run.id,
        "firmware_id": run.firmware_id,
        "suite_id": run.suite_id,
        "status": run.status,
        "stage": run.stage,
        "progress": run.progress,
        "simulator_backend": run.simulator_backend,
        "execution_mode": run.execution_mode,
        "total": run.total,
        "passed": run.passed,
        "failed": run.failed,
        "errored": run.errored,
        "skipped": run.skipped,
        "pass_rate": run.pass_rate,
        "duration_ms": run.duration_ms,
        "results": results_data,
        "results_entities": run.results,
    }
