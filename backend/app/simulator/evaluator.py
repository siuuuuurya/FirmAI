"""
Output Collector & Deterministic Test Evaluator
===============================================
Turns a raw `ExecutionResult` into a verdict.

DESIGN RULE (non-negotiable)
----------------------------
The PASS / FAIL / ERROR verdict is computed by pure, deterministic Python
comparisons of *expected* vs *observed* values.  The LLM is NEVER consulted
here. An LLM may later *explain* a failure, but it can never create, suppress
or overturn one. This is what makes the agent's results trustworthy and
reproducible: re-running the same suite on the same firmware always yields the
identical verdict.

Verdict semantics
-----------------
  PASS  — every assertion held.
  FAIL  — the firmware ran correctly but violated at least one expectation
          (a genuine behavioural defect).
  ERROR — the firmware could not be observed (build failure, crash, timeout,
          missing telemetry). Distinguished from FAIL so dashboards do not
          confuse infrastructure problems with product defects.
"""
from __future__ import annotations

import re
from typing import Any

from app.simulator.base import ExecutionResult

TOLERANCE = 1e-6
APPROX_TOLERANCE = 0.051  # telemetry is printed to 2 decimals


class OutputCollector:
    """Normalises the raw observation envelope into queryable structures."""

    def __init__(self, result: ExecutionResult, signal_map: dict[str, Any]) -> None:
        self.result = result
        self.signal_map = signal_map
        self.pin_by_symbol = {
            o["name"]: int(o["pin"]) for o in signal_map.get("observable_outputs", [])
        }
        self.telemetry = self._parse_telemetry(result.uart)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_telemetry(uart: str) -> list[dict[str, str]]:
        """
        Parse `KEY=value,KEY=value` telemetry lines emitted over the UART.

        Lines that do not match the key=value protocol (banners, error strings)
        are skipped but remain available in the raw log.
        """
        records: list[dict[str, str]] = []
        for line in uart.splitlines():
            line = line.strip()
            if not line or "=" not in line:
                continue
            fields: dict[str, str] = {}
            for k, v in re.findall(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s,]+)", line):
                fields[k.upper()] = v.strip()
            if fields:
                fields["__line__"] = line
                records.append(fields)
        return records

    # ------------------------------------------------------------------
    def pin_state_at(self, symbol: str, tick: int) -> dict[str, Any] | None:
        """Digital/PWM state of a pin at a tick (-1 == final state)."""
        pin = self.pin_by_symbol.get(symbol)
        if pin is None:
            return None
        key = str(pin)
        if tick is None or tick < 0:
            return self.result.pins.get(key)
        frames = self.result.timeline
        if not frames:
            return self.result.pins.get(key)
        idx = min(tick, len(frames) - 1)
        return (frames[idx].get("pins") or {}).get(key)

    def telemetry_at(self, tick: int) -> dict[str, str] | None:
        """
        Telemetry record for a tick.

        The setup() banner may emit non-telemetry lines, so records are indexed
        from the END of the log: record[-1] is the most recent cycle.
        """
        if not self.telemetry:
            return None
        if tick is None or tick < 0:
            return self.telemetry[-1]
        # Align the tail of the telemetry stream with the tail of the timeline.
        executed = self.result.ticks_executed or len(self.telemetry)
        offset = len(self.telemetry) - executed
        idx = tick + offset
        if 0 <= idx < len(self.telemetry):
            return self.telemetry[idx]
        return self.telemetry[min(max(tick, 0), len(self.telemetry) - 1)]

    def observed_snapshot(self) -> dict[str, Any]:
        """Compact observation summary stored with the result for the UI."""
        final_pins: dict[str, Any] = {}
        for symbol, pin in self.pin_by_symbol.items():
            state = self.result.pins.get(str(pin)) or {}
            final_pins[symbol] = {
                "pin": pin,
                "digital": state.get("digital"),
                "pwm": state.get("pwm"),
                "writes": state.get("writes"),
                "transitions": state.get("transitions"),
            }
        return {
            "final_pins": final_pins,
            "telemetry_records": self.telemetry[-40:],
            "telemetry_count": len(self.telemetry),
            "ticks_executed": self.result.ticks_executed,
            "simulated_ms": self.result.elapsed_ms,
            "wall_ms": self.result.wall_ms,
            "backend": self.result.backend,
            "execution_mode": self.result.execution_mode,
        }


class TestEvaluator:
    """Deterministic expected-vs-actual comparison engine."""

    def evaluate(
        self,
        test_case: dict[str, Any],
        result: ExecutionResult,
        signal_map: dict[str, Any],
    ) -> dict[str, Any]:
        collector = OutputCollector(result, signal_map)

        # --- infrastructure-level outcomes -> ERROR (never FAIL) ----------
        if result.status != "ok":
            reason = {
                "build_failed": "firmware failed to compile",
                "timeout": "simulation timed out",
                "crash": "firmware crashed during execution",
            }.get(result.status, "simulation error")
            return {
                "status": "ERROR",
                "assertions": [],
                "observed": collector.observed_snapshot(),
                "serial_log": result.uart,
                "trace": result.timeline[:60],
                "error_message": result.error or reason,
            }

        assertions: list[dict[str, Any]] = []
        for exp in test_case.get("expectations", []):
            assertions.append(self._check(exp, collector))

        has_error = any(a["outcome"] == "ERROR" for a in assertions)
        has_fail = any(a["outcome"] == "FAIL" for a in assertions)
        if not assertions:
            status = "ERROR"
        elif has_fail:
            status = "FAIL"
        elif has_error:
            status = "ERROR"
        else:
            status = "PASS"

        error_message = ""
        if status == "ERROR":
            error_message = next(
                (a["message"] for a in assertions if a["outcome"] == "ERROR"),
                "test produced no verifiable assertions",
            )

        return {
            "status": status,
            "assertions": assertions,
            "observed": collector.observed_snapshot(),
            "serial_log": result.uart,
            "trace": result.timeline[:60],
            "error_message": error_message,
        }

    # ------------------------------------------------------------------
    def _check(self, exp: dict[str, Any], col: OutputCollector) -> dict[str, Any]:
        kind = exp.get("kind")
        handler = {
            "pin_digital": self._check_pin_digital,
            "pin_pwm": self._check_pin_pwm,
            "telemetry": self._check_telemetry,
            "uart_contains": self._check_uart_contains,
            "uart_absent": self._check_uart_absent,
            "never_both": self._check_never_both,
            "no_chatter": self._check_no_chatter,
        }.get(kind)

        if handler is None:
            return self._assertion(exp, "ERROR", None, f"unsupported expectation kind `{kind}`")
        try:
            return handler(exp, col)
        except Exception as exc:  # noqa: BLE001 — evaluation must never crash a run
            return self._assertion(exp, "ERROR", None, f"evaluation error: {exc}")

    # ------------------------------------------------------------------
    @staticmethod
    def _assertion(
        exp: dict[str, Any],
        outcome: str,
        actual: Any,
        message: str,
        expected_repr: Any = None,
    ) -> dict[str, Any]:
        return {
            "id": exp.get("id", "E?"),
            "kind": exp.get("kind", ""),
            "target": exp.get("target", ""),
            "operator": exp.get("operator", "equals"),
            "at_tick": exp.get("at_tick", -1),
            "description": exp.get("description", ""),
            "expected": exp.get("value") if expected_repr is None else expected_repr,
            "actual": actual,
            "outcome": outcome,
            "message": message,
        }

    # ------------------------------------------------------------------
    def _check_pin_digital(self, exp, col: OutputCollector):
        target, tick = exp["target"], exp.get("at_tick", -1)
        state = col.pin_state_at(target, tick)
        if state is None:
            return self._assertion(
                exp, "ERROR", None,
                f"pin `{target}` was never observed — the firmware may not drive it",
            )
        actual = 1 if state.get("digital") else 0
        expected = 1 if self._num(exp.get("value")) else 0
        ok = actual == expected
        where = "final state" if tick < 0 else f"tick {tick}"
        return self._assertion(
            exp,
            "PASS" if ok else "FAIL",
            actual,
            f"{target} at {where}: expected {expected}, observed {actual}",
            expected,
        )

    def _check_pin_pwm(self, exp, col: OutputCollector):
        target, tick = exp["target"], exp.get("at_tick", -1)
        state = col.pin_state_at(target, tick)
        if state is None:
            return self._assertion(exp, "ERROR", None, f"pin `{target}` was never observed")
        actual = state.get("pwm")
        if actual is None or actual < 0:
            return self._assertion(exp, "ERROR", actual, f"pin `{target}` has no PWM value")
        expected = self._num(exp.get("value"))
        ok = self._compare(actual, exp.get("operator", "equals"), expected)
        return self._assertion(
            exp,
            "PASS" if ok else "FAIL",
            actual,
            f"{target} PWM: expected {exp.get('operator')} {expected}, observed {actual}",
            expected,
        )

    def _check_telemetry(self, exp, col: OutputCollector):
        key, tick = str(exp["target"]).upper(), exp.get("at_tick", -1)
        record = col.telemetry_at(tick)
        if record is None:
            return self._assertion(
                exp, "ERROR", None,
                "no telemetry was emitted on the UART — cannot verify the protocol contract",
            )
        if key not in record:
            return self._assertion(
                exp, "FAIL", None,
                f"telemetry field `{key}` missing from `{record.get('__line__', '')}`",
            )
        actual_raw = record[key]
        expected_raw = exp.get("value")
        operator = exp.get("operator", "equals")

        BOOLEAN_MAP = {
            "0": 0, "off": 0, "false": 0, "low": 0,
            "1": 1, "on": 1, "true": 1, "high": 1,
        }
        a_lower = str(actual_raw).strip().lower()
        e_lower = str(expected_raw).strip().lower()
        a_bool = BOOLEAN_MAP.get(a_lower)
        e_bool = BOOLEAN_MAP.get(e_lower)

        if a_bool is not None and e_bool is not None:
            ok = self._compare(a_bool, operator, e_bool)
            actual_out: Any = actual_raw
        else:
            a_num, e_num = self._num(actual_raw), self._num(expected_raw)
            if a_num is not None and e_num is not None:
                ok = self._compare(a_num, operator, e_num)
                actual_out = a_num
            else:
                a_s, e_s = str(actual_raw).strip(), str(expected_raw).strip()
                ok = (e_s.lower() in a_s.lower()) if operator == "contains" else (a_s.lower() == e_s.lower())
                actual_out = a_s
        where = "final cycle" if tick < 0 else f"tick {tick}"
        return self._assertion(
            exp,
            "PASS" if ok else "FAIL",
            actual_out,
            f"telemetry {key} at {where}: expected {operator} {expected_raw}, observed {actual_raw}",
            expected_raw,
        )

    def _check_uart_contains(self, exp, col: OutputCollector):
        needle = str(exp.get("value", ""))
        ok = needle in col.result.uart
        return self._assertion(
            exp,
            "PASS" if ok else "FAIL",
            "present" if ok else "absent",
            f"UART {'contains' if ok else 'does NOT contain'} `{needle}`",
            needle,
        )

    def _check_uart_absent(self, exp, col: OutputCollector):
        needle = str(exp.get("value", ""))
        ok = needle not in col.result.uart
        return self._assertion(
            exp,
            "PASS" if ok else "FAIL",
            "absent" if ok else "present",
            f"UART {'correctly omits' if ok else 'unexpectedly contains'} `{needle}`",
            f"absent:{needle}",
        )

    def _check_never_both(self, exp, col: OutputCollector):
        """Safety interlock: two pins must never be HIGH in the same cycle."""
        parts = [p.strip() for p in str(exp.get("target", "")).split("+") if p.strip()]
        if len(parts) != 2:
            return self._assertion(exp, "ERROR", None, "never_both needs `PIN_A+PIN_B`")
        a_sym, b_sym = parts
        pin_a, pin_b = col.pin_by_symbol.get(a_sym), col.pin_by_symbol.get(b_sym)
        if pin_a is None or pin_b is None:
            return self._assertion(exp, "ERROR", None, f"unknown pin in `{exp.get('target')}`")

        violations: list[dict[str, Any]] = []
        for frame in col.result.timeline:
            pins = frame.get("pins") or {}
            a = (pins.get(str(pin_a)) or {}).get("digital", 0)
            b = (pins.get(str(pin_b)) or {}).get("digital", 0)
            if a and b:
                violations.append({"tick": frame.get("t"), "ms": frame.get("ms")})
        ok = not violations
        detail = (
            f"{a_sym} and {b_sym} were never simultaneously HIGH across "
            f"{len(col.result.timeline)} cycle(s)"
            if ok
            else (
                f"SAFETY VIOLATION: {a_sym} and {b_sym} were both HIGH at "
                f"{len(violations)} cycle(s): ticks {[v['tick'] for v in violations][:12]}"
            )
        )
        return self._assertion(
            exp,
            "PASS" if ok else "FAIL",
            f"{len(violations)} simultaneous-on cycle(s)",
            detail,
            "0 simultaneous-on cycles",
        )

    def _check_no_chatter(self, exp, col: OutputCollector):
        target = exp["target"]
        state = col.pin_state_at(target, -1)
        if state is None:
            return self._assertion(exp, "ERROR", None, f"pin `{target}` was never observed")
        actual = int(state.get("transitions", 0))
        limit = int(self._num(exp.get("value")) or 0)
        ok = actual <= limit
        return self._assertion(
            exp,
            "PASS" if ok else "FAIL",
            actual,
            f"{target} toggled {actual} time(s); limit is {limit}"
            + ("" if ok else " — relay chatter / missing hysteresis"),
            limit,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _num(value: Any) -> float | None:
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            m = re.search(r"[-+]?\d+(?:\.\d+)?", value.strip())
            if m:
                try:
                    return float(m.group(0))
                except ValueError:
                    return None
        return None

    @staticmethod
    def _compare(actual: float, operator: str, expected: float | None) -> bool:
        if expected is None:
            return False
        return {
            "equals": lambda: abs(actual - expected) < TOLERANCE,
            "not_equals": lambda: abs(actual - expected) >= TOLERANCE,
            "gt": lambda: actual > expected,
            "lt": lambda: actual < expected,
            "gte": lambda: actual >= expected - TOLERANCE,
            "lte": lambda: actual <= expected + TOLERANCE,
            "approx": lambda: abs(actual - expected) <= APPROX_TOLERANCE,
            "contains": lambda: abs(actual - expected) < TOLERANCE,
        }.get(operator, lambda: abs(actual - expected) < TOLERANCE)()
