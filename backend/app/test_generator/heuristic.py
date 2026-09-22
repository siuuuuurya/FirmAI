"""
Requirement-driven heuristic test generator
===========================================
A fully deterministic test-design engine used when no LLM credentials are
available (or when the LLM call fails).  It is *not* a stub: it implements
the same classical V&V techniques a human embedded test engineer applies.

Techniques implemented
----------------------
* Requirement mining     — parses `Rn  <text>` requirement blocks from the
                           source comments and treats them as the oracle.
* Boundary value analysis— for each named threshold: just-below / at / just-above.
* Equivalence classes    — nominal operating point per state region.
* Safety interlocks      — mutually-exclusive actuator pairs (never_both).
* Latching verification   — monotonic alarm latch across a falling stimulus.
* Hysteresis / chatter    — transition counting on relay outputs.
* Fault injection         — out-of-range sensor values.
* Protocol conformance    — telemetry key presence & format.

Because expectations are derived from the *requirements*, not the code, this
engine detects requirement-vs-implementation divergence exactly like the LLM
path does.
"""
from __future__ import annotations

import re
from typing import Any

# Phrases / operators indicating the requirement boundary is INCLUSIVE.
# NOTE: no `\b` anchors — `>=` starts with a non-word character, so a word
# boundary would never match it.
_INCLUSIVE_RE = re.compile(
    r"(>=|<=|≥|≤|at or (?:above|below|over|under)|reaches or exceeds|"
    r"or (?:more|greater|higher|above)|not less than|inclusive)",
    re.I,
)
# Phrases explicitly marking the boundary as EXCLUSIVE (checked first).
_EXCLUSIVE_RE = re.compile(r"(strictly (?:greater|less|above|below)|exclusive)", re.I)


def requirement_is_inclusive(text: str) -> bool:
    """
    Decide whether a requirement's threshold comparison includes the boundary.

    `"reaches or exceeds 45"` / `">= 45"`  -> inclusive (the boundary triggers)
    `"strictly greater than 30"` / `"> 30"` -> exclusive (the boundary does not)
    """
    if _EXCLUSIVE_RE.search(text):
        return False
    return bool(_INCLUSIVE_RE.search(text))


def parse_requirements(source: str) -> list[dict[str, str]]:
    """Extract `R1  ...` style requirement statements from header comments."""
    reqs: list[dict[str, str]] = []
    pattern = re.compile(r"^\s*\*?\s*(R\d+)\s+(.+?)(?=^\s*\*?\s*R\d+\s|\Z)", re.M | re.S)
    for m in pattern.finditer(source):
        body = m.group(2)
        # A requirement block ends at the end of its comment — never let the
        # last requirement swallow the code that follows it.
        for terminator in ("*/", "\n//", "\n/*"):
            idx = body.find(terminator)
            if idx != -1:
                body = body[:idx]
        text = re.sub(r"\s*\*\s*", " ", body)
        text = re.sub(r"\s+", " ", text).strip().rstrip("*/").strip()
        if len(text) > 5:
            reqs.append({"id": m.group(1), "text": text})
    return reqs


def _find_requirement(reqs: list[dict[str, str]], *keywords: str) -> dict[str, str] | None:
    for r in reqs:
        low = r["text"].lower()
        if all(k.lower() in low for k in keywords):
            return r
    return None


class HeuristicTestGenerator:
    """Deterministic requirement-driven test designer."""

    engine = "heuristic"

    def generate(
        self,
        source: str,
        analysis: dict[str, Any],
        max_tests: int = 10,
        focus: str = "",
    ) -> dict[str, Any]:
        smap = analysis.get("signal_map", {})
        reqs = parse_requirements(source)
        channels = smap.get("stimulus_channels", [])
        outputs = smap.get("observable_outputs", [])
        named = smap.get("named_thresholds", {})
        telemetry = smap.get("telemetry_keys", [])

        primary = next((c for c in channels if c["kind"] == "analog"), None)
        if primary is None and channels:
            primary = channels[0]

        tests: list[dict[str, Any]] = []
        counter = [0]

        def nid() -> str:
            counter[0] += 1
            return f"TC-{counter[0]:03d}"

        if primary is not None:
            tests += self._threshold_tests(nid, primary, outputs, named, telemetry, reqs, analysis)
            tests += self._latch_tests(nid, primary, outputs, named, telemetry, reqs)
            tests += self._interlock_tests(nid, primary, outputs, named, telemetry, reqs)
            tests += self._fault_tests(nid, primary, outputs, named, telemetry, reqs, analysis)
            tests += self._protocol_tests(nid, primary, telemetry, reqs)

        # Order: critical first, then by generation order.
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        tests.sort(key=lambda t: (rank.get(t["priority"], 9), t["test_id"]))
        tests = tests[:max_tests]
        for i, t in enumerate(tests, 1):
            t["test_id"] = f"TC-{i:03d}"

        covered = sorted({t["requirement"].split(":")[0] for t in tests if ":" in t["requirement"]})
        return {
            "suite_name": "Requirement-Driven Boundary & Safety Suite",
            "strategy_notes": (
                "Expectations are derived from the documented requirements (the oracle), "
                "never from the implementation's own conditionals — so any divergence between "
                "specification and code surfaces as a failing assertion. The suite applies "
                "boundary-value analysis to every named threshold, verifies actuator safety "
                "interlocks and alarm latching, and injects out-of-range sensor faults."
            ),
            "coverage_notes": (
                f"Covers requirements {', '.join(covered) if covered else 'n/a'} across "
                f"{len(named)} named threshold(s), {len(outputs)} observable output(s) and "
                f"{len(telemetry)} telemetry field(s)."
            ),
            "tests": tests,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _stim(channel: dict[str, Any], points: list[tuple[int, float]], ticks: int, tick_ms: int = 100) -> dict[str, Any]:
        return {
            "ticks": ticks,
            "tick_ms": tick_ms,
            "events": [
                {
                    "tick": tick,
                    "channel": channel["name"],
                    "unit": channel.get("unit", "counts"),
                    "value": value,
                }
                for tick, value in points
            ],
        }

    # ------------------------------------------------------------------
    def _threshold_tests(
        self,
        nid,
        ch: dict[str, Any],
        outputs: list[dict[str, Any]],
        named: dict[str, float],
        telemetry: list[str],
        reqs: list[dict[str, str]],
        analysis: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Boundary value analysis for the fan-on / critical thresholds."""
        tests: list[dict[str, Any]] = []
        actuators = [o for o in outputs if o["role"] == "actuator"]
        indicators = [o for o in outputs if o["role"] == "indicator" and "STATUS" not in o["name"].upper()]

        fan = next((o for o in actuators if re.search(r"fan|cool", o["name"], re.I)), actuators[0] if actuators else None)
        alarm = next((o for o in indicators if re.search(r"alarm|alert", o["name"], re.I)), indicators[0] if indicators else None)

        # --- fan-on threshold -------------------------------------------
        thr_name, thr_val = self._pick(named, r"threshold")
        if fan and thr_val is not None:
            req = _find_requirement(reqs, "fan") or {"id": "R1", "text": f"Fan ON when value > {thr_val}."}
            inclusive = requirement_is_inclusive(req["text"])
            tele_key = self._tele_for(fan["name"], telemetry)

            for label, offset, expect_on in (
                ("just below", -1.0, False),
                ("exactly at", 0.0, inclusive),
                ("just above", +1.0, True),
            ):
                value = round(thr_val + offset, 3)
                expected = 1 if expect_on else 0
                exps = [
                    {
                        "id": "E1",
                        "kind": "pin_digital",
                        "target": fan["name"],
                        "operator": "equals",
                        "value": expected,
                        "at_tick": 3,
                        "description": f"{fan['name']} must be {'ENERGISED' if expected else 'OFF'} at {value}",
                    }
                ]
                if tele_key:
                    exps.append(
                        {
                            "id": "E2",
                            "kind": "telemetry",
                            "target": tele_key,
                            "operator": "equals",
                            "value": str(expected),
                            "at_tick": 3,
                            "description": f"telemetry {tele_key} reports {expected}",
                        }
                    )
                tests.append(
                    {
                        "test_id": nid(),
                        "name": f"Fan threshold — {label} {thr_name} ({value}{self._u(ch)})",
                        "description": (
                            f"Hold the {ch['name']} channel at {value}{self._u(ch)} "
                            f"({label} the {thr_name} limit of {thr_val}) and verify the cooling "
                            f"actuator state."
                        ),
                        "category": "boundary",
                        "priority": "critical" if offset >= 0 else "high",
                        "requirement": f"{req['id']}: {req['text'][:200]}",
                        "rationale": (
                            f"Boundary-value analysis on {thr_name}. Wrong comparison operators "
                            f"(`>=` vs `>`) and drifted constants are the single most common defect "
                            f"class at a threshold; probing {label} the limit isolates them. "
                            f"The expected value comes from requirement {req['id']}, not from the "
                            f"implementation, so a spec/code mismatch fails here."
                        ),
                        "derived_from": [
                            f"threshold:{thr_name}={thr_val}",
                            f"requirement:{req['id']}",
                            "technique:boundary-value-analysis",
                        ],
                        "stimulus": self._stim(ch, [(-1, value)], ticks=5),
                        "expectations": exps,
                    }
                )

        # --- critical alarm threshold ------------------------------------
        crit_name, crit_val = self._pick(named, r"critical")
        if alarm and crit_val is not None:
            req = _find_requirement(reqs, "alarm") or {
                "id": "R2",
                "text": f"Alarm latches when value reaches or exceeds {crit_val}.",
            }
            inclusive = requirement_is_inclusive(req["text"])
            tele_key = self._tele_for(alarm["name"], telemetry)
            for label, offset, expect_on in (
                ("exactly at", 0.0, inclusive),
                ("just above", +1.0, True),
            ):
                value = round(crit_val + offset, 3)
                expected = 1 if expect_on else 0
                exps = [
                    {
                        "id": "E1",
                        "kind": "pin_digital",
                        "target": alarm["name"],
                        "operator": "equals",
                        "value": expected,
                        "at_tick": 3,
                        "description": f"{alarm['name']} must be {'ON' if expected else 'OFF'} at {value}",
                    }
                ]
                if tele_key:
                    exps.append(
                        {
                            "id": "E2",
                            "kind": "telemetry",
                            "target": tele_key,
                            "operator": "equals",
                            "value": str(expected),
                            "at_tick": 3,
                            "description": f"telemetry {tele_key} reports {expected}",
                        }
                    )
                tests.append(
                    {
                        "test_id": nid(),
                        "name": f"Critical alarm — {label} {crit_name} ({value}{self._u(ch)})",
                        "description": (
                            f"Drive {ch['name']} to {value}{self._u(ch)} and verify the critical "
                            f"alarm indicator responds per requirement."
                        ),
                        "category": "safety",
                        "priority": "critical",
                        "requirement": f"{req['id']}: {req['text'][:200]}",
                        "rationale": (
                            f"The requirement states the alarm triggers when the reading *reaches or "
                            f"exceeds* {crit_val}, i.e. an inclusive `>=` comparison. Testing the exact "
                            f"boundary detects the classic off-by-one where the implementation uses a "
                            f"strict `>` and silently fails to alarm at precisely {crit_val} — a safety "
                            f"hazard in a thermal cut-off path."
                        ),
                        "derived_from": [
                            f"threshold:{crit_name}={crit_val}",
                            f"requirement:{req['id']}",
                            "technique:boundary-value-analysis",
                            "risk:strict-inequality-boundary",
                        ],
                        "stimulus": self._stim(ch, [(-1, value)], ticks=5),
                        "expectations": exps,
                    }
                )
        return tests

    # ------------------------------------------------------------------
    def _latch_tests(self, nid, ch, outputs, named, telemetry, reqs) -> list[dict[str, Any]]:
        """Alarm must stay latched after the stimulus falls back to normal."""
        indicators = [o for o in outputs if o["role"] == "indicator" and "STATUS" not in o["name"].upper()]
        alarm = next((o for o in indicators if re.search(r"alarm|alert", o["name"], re.I)), None)
        _, crit_val = self._pick(named, r"critical")
        if not alarm or crit_val is None:
            return []
        req = _find_requirement(reqs, "latch") or {
            "id": "R2",
            "text": "The alarm shall latch and remain asserted until reset.",
        }
        high = round(crit_val + 5.0, 3)
        low = round(crit_val - 20.0, 3)
        return [
            {
                "test_id": nid(),
                "name": "Alarm latch persists after temperature returns to normal",
                "description": (
                    f"Spike {ch['name']} to {high}{self._u(ch)} to trip the alarm, then drop it to "
                    f"{low}{self._u(ch)} and confirm the alarm remains latched."
                ),
                "category": "state-machine",
                "priority": "high",
                "requirement": f"{req['id']}: {req['text'][:200]}",
                "rationale": (
                    "A latching safety indicator must not self-clear when the hazardous condition "
                    "disappears — an operator has to acknowledge it. This test drives a rising then "
                    "falling profile to catch a non-latching (purely combinational) implementation, "
                    "which would silently hide a transient over-temperature event."
                ),
                "derived_from": [f"requirement:{req['id']}", "technique:state-transition-testing"],
                "stimulus": self._stim(ch, [(-1, low), (1, high), (4, low)], ticks=8),
                "expectations": [
                    {
                        "id": "E1",
                        "kind": "pin_digital",
                        "target": alarm["name"],
                        "operator": "equals",
                        "value": 1,
                        "at_tick": 2,
                        "description": "alarm asserts on the over-temperature spike",
                    },
                    {
                        "id": "E2",
                        "kind": "pin_digital",
                        "target": alarm["name"],
                        "operator": "equals",
                        "value": 1,
                        "at_tick": 7,
                        "description": "alarm REMAINS latched after cooling down",
                    },
                ],
            }
        ]

    # ------------------------------------------------------------------
    def _interlock_tests(self, nid, ch, outputs, named, telemetry, reqs) -> list[dict[str, Any]]:
        """Mutually exclusive actuators must never be energised together."""
        actuators = [o for o in outputs if o["role"] == "actuator"]
        if len(actuators) < 2:
            return []
        a, b = actuators[0], actuators[1]
        req = _find_requirement(reqs, "heater") or {
            "id": "R3",
            "text": "The heater shall be disabled whenever the fan is running.",
        }
        _, thr = self._pick(named, r"threshold")
        _, target = self._pick(named, r"target")
        hot = round((thr if thr is not None else 30.0) + 8.0, 3)
        cold = round((target if target is not None else 22.0) - 5.0, 3)
        return [
            {
                "test_id": nid(),
                "name": f"Safety interlock — {a['name']} and {b['name']} never energised together",
                "description": (
                    f"Sweep {ch['name']} from {hot}{self._u(ch)} (cooling demand) down to "
                    f"{cold}{self._u(ch)} (heating demand) and assert mutual exclusion at every tick."
                ),
                "category": "safety",
                "priority": "critical",
                "requirement": f"{req['id']}: {req['text'][:200]}",
                "rationale": (
                    "Energising a heater and a cooler simultaneously wastes energy, fights the control "
                    "loop and can damage hardware. The dangerous window is the STATE TRANSITION: a stale "
                    "actuator flag from the previous cycle may persist when the controller switches "
                    "regimes. This test forces exactly that transition and asserts the interlock holds "
                    "across the whole timeline, not just in steady state."
                ),
                "derived_from": [
                    f"requirement:{req['id']}",
                    "risk:actuator-mutual-exclusion",
                    "technique:state-transition-testing",
                ],
                "stimulus": self._stim(ch, [(-1, hot), (2, cold)], ticks=8),
                "expectations": [
                    {
                        "id": "E1",
                        "kind": "never_both",
                        "target": f"{a['name']}+{b['name']}",
                        "operator": "equals",
                        "value": 0,
                        "at_tick": -1,
                        "description": f"{a['name']} and {b['name']} are never HIGH in the same cycle",
                    },
                    {
                        "id": "E2",
                        "kind": "pin_digital",
                        "target": a["name"],
                        "operator": "equals",
                        "value": 1,
                        "at_tick": 1,
                        "description": "cooling actuator is active during the hot phase",
                    },
                ],
            }
        ]

    # ------------------------------------------------------------------
    def _fault_tests(self, nid, ch, outputs, named, telemetry, reqs, analysis) -> list[dict[str, Any]]:
        """Out-of-range sensor plausibility handling."""
        _, max_valid = self._pick(named, r"max_valid|maxvalid")
        if max_valid is None:
            return []
        req = _find_requirement(reqs, "range") or {
            "id": "R6",
            "text": "An out-of-range sensor reading shall be rejected as a fault.",
        }
        actuators = [o for o in outputs if o["role"] == "actuator"]
        fan = next((o for o in actuators if re.search(r"fan|cool", o["name"], re.I)), None)

        tf = ch.get("transfer_function") or {}
        raw_max = tf.get("raw_max", 1023)
        scale = tf.get("scale", 1.0) or 1.0
        offset = tf.get("offset", 0.0)
        # Highest physically representable reading on this channel.
        extreme = round(raw_max * scale + offset, 3)
        if extreme <= max_valid:
            return []

        exps: list[dict[str, Any]] = [
            {
                "id": "E1",
                "kind": "uart_contains",
                "target": "",
                "operator": "contains",
                "value": "ERROR",
                "at_tick": -1,
                "description": "firmware reports a sensor fault on the UART",
            }
        ]
        if fan:
            exps.append(
                {
                    "id": "E2",
                    "kind": "pin_digital",
                    "target": fan["name"],
                    "operator": "equals",
                    "value": 1,
                    "at_tick": 3,
                    "description": "fail-safe: cooling engaged while the sensor is untrusted",
                }
            )
        return [
            {
                "test_id": nid(),
                "name": f"Fault injection — sensor reads out of range ({extreme}{self._u(ch)})",
                "description": (
                    f"Inject a physically impossible reading of {extreme}{self._u(ch)} "
                    f"(above the {max_valid} validity limit) simulating a shorted or disconnected sensor."
                ),
                "category": "fault-injection",
                "priority": "high",
                "requirement": f"{req['id']}: {req['text'][:200]}",
                "rationale": (
                    "Real sensors fail open or shorted, producing rail-to-rail readings. Firmware that "
                    "trusts the ADC blindly will take a catastrophic control action. This test verifies "
                    "the plausibility guard fires and the system degrades into a documented fail-safe "
                    "state rather than acting on garbage data."
                ),
                "derived_from": [
                    f"requirement:{req['id']}",
                    "risk:sensor-range-validation",
                    "technique:fault-injection",
                ],
                "stimulus": self._stim(ch, [(-1, extreme)], ticks=5),
                "expectations": exps,
            }
        ]

    # ------------------------------------------------------------------
    def _protocol_tests(self, nid, ch, telemetry, reqs) -> list[dict[str, Any]]:
        if not telemetry:
            return []
        req = _find_requirement(reqs, "telemetry") or _find_requirement(reqs, "uart") or {
            "id": "R5",
            "text": "Every control cycle shall emit one telemetry line on the UART.",
        }
        return [
            {
                "test_id": nid(),
                "name": "Telemetry protocol conformance — all fields present each cycle",
                "description": (
                    f"Run a nominal profile and verify every telemetry key ({', '.join(telemetry)}) "
                    f"is emitted on the UART."
                ),
                "category": "functional",
                "priority": "medium",
                "requirement": f"{req['id']}: {req['text'][:200]}",
                "rationale": (
                    "Downstream monitoring and field diagnostics parse this UART contract. A silently "
                    "dropped or renamed field breaks every consumer, so the protocol shape is verified "
                    "independently of the control logic."
                ),
                "derived_from": [f"requirement:{req['id']}", "technique:protocol-conformance"],
                "stimulus": self._stim(ch, [(-1, 25.0)], ticks=4),
                "expectations": [
                    {
                        "id": f"E{i+1}",
                        "kind": "uart_contains",
                        "target": "",
                        "operator": "contains",
                        "value": f"{key}=",
                        "at_tick": -1,
                        "description": f"telemetry field `{key}` present",
                    }
                    for i, key in enumerate(telemetry)
                ],
            }
        ]

    # ------------------------------------------------------------------
    @staticmethod
    def _pick(named: dict[str, float], pattern: str) -> tuple[str | None, float | None]:
        for name, value in named.items():
            if re.search(pattern, name, re.I):
                return name, value
        return None, None

    @staticmethod
    def _tele_for(pin_symbol: str, telemetry: list[str]) -> str | None:
        base = re.sub(r"_(PIN|LED|LED_PIN)$", "", pin_symbol, flags=re.I)
        base = base.replace("_LED", "").replace("_PIN", "")
        for key in telemetry:
            if key.upper() == base.upper() or base.upper().startswith(key.upper()):
                return key
        return None

    @staticmethod
    def _u(ch: dict[str, Any]) -> str:
        unit = ch.get("unit", "")
        return "°C" if unit == "degC" else (f" {unit}" if unit else "")
