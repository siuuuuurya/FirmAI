"""
AI Test Generator
=================
Orchestrates test-suite synthesis:

    LLM path (preferred)  ->  validated & normalised  ->  TestSuite
         |  failure / no credentials
         v
    Heuristic path (requirement-driven, deterministic)

Whichever engine produced the suite is recorded verbatim on the suite
(`generator_engine`) and surfaced in the UI — the demo never pretends an
LLM ran when it did not.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.llm.client import LLMClient, LLMError
from app.test_generator.heuristic import HeuristicTestGenerator
from app.test_generator.prompts import TEST_GEN_SYSTEM, build_test_gen_user_prompt

logger = logging.getLogger("firmwareai.testgen")

VALID_CATEGORIES = {
    "boundary",
    "functional",
    "safety",
    "state-machine",
    "fault-injection",
    "timing",
    "regression",
    "performance",
}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}
VALID_KINDS = {
    "pin_digital",
    "pin_pwm",
    "telemetry",
    "uart_contains",
    "uart_absent",
    "never_both",
    "no_chatter",
}
VALID_OPERATORS = {"equals", "not_equals", "gt", "lt", "gte", "lte", "contains", "approx"}


@dataclass
class GeneratedSuite:
    name: str
    strategy_notes: str
    coverage_notes: str
    tests: list[dict[str, Any]]
    engine: str
    model: str
    generation_ms: float
    raw_response: str = ""
    warnings: list[str] = field(default_factory=list)


class TestGenerator:
    """LLM-first, heuristic-backed structured test designer."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()
        self.heuristic = HeuristicTestGenerator()

    async def generate(
        self,
        source: str,
        analysis: dict[str, Any],
        filename: str = "firmware.ino",
        max_tests: int = 10,
        focus: str = "",
        use_llm: bool = True,
    ) -> GeneratedSuite:
        t0 = time.perf_counter()
        warnings: list[str] = []

        if use_llm and self.client.available and self.client.provider != "mock":
            try:
                payload, response = await self.client.complete_json(
                    TEST_GEN_SYSTEM,
                    build_test_gen_user_prompt(filename, source, analysis, max_tests, focus),
                    temperature=0.25,
                    max_tokens=8000,
                )
                tests = self._validate(payload.get("tests", []), analysis, max_tests)
                if tests:
                    return GeneratedSuite(
                        name=str(payload.get("suite_name") or "AI-Generated Test Suite"),
                        strategy_notes=str(payload.get("strategy_notes", "")),
                        coverage_notes=str(payload.get("coverage_notes", "")),
                        tests=tests,
                        engine=f"llm:{response.provider}",
                        model=response.model,
                        generation_ms=round((time.perf_counter() - t0) * 1000, 2),
                        raw_response=response.text[:20000],
                        warnings=warnings,
                    )
                warnings.append("LLM returned no schema-valid tests; used the heuristic engine.")
            except LLMError as exc:
                logger.warning("LLM test generation unavailable: %s", exc)
                warnings.append(f"LLM unavailable ({str(exc)[:160]}); used the heuristic engine.")
            except Exception as exc:  # noqa: BLE001
                logger.exception("LLM test generation failed")
                warnings.append(f"LLM error ({str(exc)[:160]}); used the heuristic engine.")

            if not settings.llm_allow_heuristic_fallback:
                raise LLMError("LLM generation failed and heuristic fallback is disabled.")
        elif use_llm:
            warnings.append("No LLM credentials configured; used the deterministic heuristic engine.")

        payload = self.heuristic.generate(source, analysis, max_tests=max_tests, focus=focus)
        tests = self._validate(payload["tests"], analysis, max_tests)
        return GeneratedSuite(
            name=payload["suite_name"],
            strategy_notes=payload["strategy_notes"],
            coverage_notes=payload["coverage_notes"],
            tests=tests,
            engine="heuristic",
            model="rule-based-v1",
            generation_ms=round((time.perf_counter() - t0) * 1000, 2),
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Schema validation / normalisation
    # ------------------------------------------------------------------
    def _validate(
        self, tests: Any, analysis: dict[str, Any], max_tests: int
    ) -> list[dict[str, Any]]:
        """
        Coerce a model-authored plan into the strict execution contract.

        Anything unusable is dropped rather than silently executed — a test the
        simulator cannot drive would otherwise report a meaningless PASS.
        """
        if not isinstance(tests, list):
            return []

        smap = analysis.get("signal_map", {})
        valid_channels = {c["name"] for c in smap.get("stimulus_channels", [])}
        valid_pins = {o["name"] for o in smap.get("observable_outputs", [])}
        valid_keys = {k.upper() for k in smap.get("telemetry_keys", [])}

        out: list[dict[str, Any]] = []
        for idx, raw in enumerate(tests):
            if not isinstance(raw, dict):
                continue

            stimulus = self._validate_stimulus(raw.get("stimulus"), valid_channels)
            if stimulus is None:
                logger.info("dropping test %s: unusable stimulus", raw.get("test_id"))
                continue

            expectations = self._validate_expectations(
                raw.get("expectations"), valid_pins, valid_keys
            )
            if not expectations:
                logger.info("dropping test %s: no valid expectations", raw.get("test_id"))
                continue

            category = str(raw.get("category", "functional")).lower()
            priority = str(raw.get("priority", "medium")).lower()

            out.append(
                {
                    "test_id": str(raw.get("test_id") or f"TC-{idx + 1:03d}")[:64],
                    "name": str(raw.get("name") or f"Test {idx + 1}")[:255],
                    "description": str(raw.get("description", ""))[:2000],
                    "category": category if category in VALID_CATEGORIES else "functional",
                    "priority": priority if priority in VALID_PRIORITIES else "medium",
                    "requirement": str(raw.get("requirement", ""))[:500],
                    "rationale": str(raw.get("rationale", ""))[:2000],
                    "derived_from": [str(d)[:160] for d in (raw.get("derived_from") or [])][:10],
                    "stimulus": stimulus,
                    "expectations": expectations,
                    "timeout_ms": int(raw.get("timeout_ms", 5000) or 5000),
                }
            )
            if len(out) >= max_tests:
                break
        return out

    @staticmethod
    def _validate_stimulus(stim: Any, valid_channels: set[str]) -> dict[str, Any] | None:
        if not isinstance(stim, dict):
            return None
        try:
            ticks = max(1, min(int(stim.get("ticks", 6) or 6), 200))
            tick_ms = max(1, min(int(stim.get("tick_ms", 100) or 100), 5000))
        except (TypeError, ValueError):
            return None

        events: list[dict[str, Any]] = []
        for ev in stim.get("events") or []:
            if not isinstance(ev, dict):
                continue
            channel = str(ev.get("channel", "")).strip()
            if valid_channels and channel not in valid_channels:
                continue
            try:
                tick = int(ev.get("tick", -1))
                value = float(ev.get("value"))
            except (TypeError, ValueError):
                continue
            events.append(
                {
                    "tick": max(-1, min(tick, ticks - 1)),
                    "channel": channel,
                    "unit": str(ev.get("unit", "counts"))[:16],
                    "value": value,
                }
            )
        if not events:
            return None
        return {"ticks": ticks, "tick_ms": tick_ms, "events": events}

    @staticmethod
    def _validate_expectations(
        exps: Any, valid_pins: set[str], valid_keys: set[str]
    ) -> list[dict[str, Any]]:
        if not isinstance(exps, list):
            return []
        out: list[dict[str, Any]] = []
        for i, raw in enumerate(exps):
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind", "")).strip()
            if kind not in VALID_KINDS:
                continue
            target = str(raw.get("target", "")).strip()

            # Target must be resolvable against the real hardware model.
            if kind in ("pin_digital", "pin_pwm", "no_chatter"):
                if valid_pins and target not in valid_pins:
                    continue
            elif kind == "never_both":
                parts = [p.strip() for p in target.split("+") if p.strip()]
                if len(parts) != 2 or (valid_pins and not set(parts) <= valid_pins):
                    continue
            elif kind == "telemetry":
                if valid_keys and target.upper() not in valid_keys:
                    continue

            operator = str(raw.get("operator", "equals")).lower()
            if operator not in VALID_OPERATORS:
                operator = "equals"

            value = raw.get("value")
            if value is None and kind not in ("never_both",):
                continue

            try:
                at_tick = int(raw.get("at_tick", -1))
            except (TypeError, ValueError):
                at_tick = -1

            out.append(
                {
                    "id": str(raw.get("id") or f"E{i + 1}")[:16],
                    "kind": kind,
                    "target": target[:120],
                    "operator": operator,
                    "value": value,
                    "at_tick": at_tick,
                    "description": str(raw.get("description", ""))[:400],
                }
            )
        return out
