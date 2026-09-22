"""
Static firmware analyzer
========================
Extracts a structured *machine model* from embedded C/C++ (Arduino) source so
that downstream stages can reason about the firmware without an LLM.

Extraction strategy
-------------------
The analyzer runs a lexical pre-pass (comment/string stripping while keeping
byte offsets stable so line numbers stay exact), then a battery of pattern
matchers that recover:

  * constants & `#define`s (with numeric values)
  * pin assignments and their inferred direction/role
  * digital / analog inputs and outputs
  * comparison thresholds  (`temp > 30.0`)  -> boundary candidates
  * enum-based state machines and state variables
  * conditional branches with their line numbers
  * function definitions and call graph edges
  * `Serial.print` telemetry format (key=value protocol inference)
  * peripherals (UART/ADC/PWM/timers/interrupts)
  * risk areas (magic numbers, unlatched comparisons, missing bounds checks)

The result is a `signal_map`: the canonical contract the test generator and the
simulator both use to drive and observe the virtual hardware.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any

ANALYZER_VERSION = "1.2.0"

# Arduino analog pin aliases -> virtual pin numbers used by the HAL shim.
ANALOG_ALIASES = {f"A{i}": 14 + i for i in range(8)}

NUMERIC_RE = r"[-+]?\d+(?:\.\d+)?(?:[fFuUlL])?"

OUTPUT_ROLE_HINTS = {
    "fan": "actuator",
    "heater": "actuator",
    "motor": "actuator",
    "pump": "actuator",
    "relay": "actuator",
    "valve": "actuator",
    "buzzer": "indicator",
    "alarm": "indicator",
    "led": "indicator",
    "lamp": "indicator",
    "status": "indicator",
}

INPUT_ROLE_HINTS = {
    "temp": "temperature-sensor",
    "therm": "temperature-sensor",
    "humid": "humidity-sensor",
    "light": "light-sensor",
    "ldr": "light-sensor",
    "pot": "potentiometer",
    "sensor": "sensor",
    "adc": "adc-channel",
    "button": "digital-input",
    "switch": "digital-input",
    "btn": "digital-input",
}


# ---------------------------------------------------------------------------
# Lexical helpers
# ---------------------------------------------------------------------------
def strip_comments_and_strings(src: str) -> str:
    """
    Replace comments and string literals with equal-length blanks.

    Keeping the original length means every regex match offset still maps to
    the correct line number in the *original* file — critical for reporting
    accurate suspect lines to the user and to the AI failure analyzer.
    """
    out: list[str] = []
    i, n = 0, len(src)
    state = "code"  # code | line_comment | block_comment | string | char
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                state, i = "line_comment", i + 2
                out.append("  ")
                continue
            if c == "/" and nxt == "*":
                state, i = "block_comment", i + 2
                out.append("  ")
                continue
            if c == '"':
                state, i = "string", i + 1
                out.append(" ")
                continue
            if c == "'":
                state, i = "char", i + 1
                out.append(" ")
                continue
            out.append(c)
            i += 1
        elif state == "line_comment":
            if c == "\n":
                state = "code"
                out.append("\n")
            else:
                out.append(" ")
            i += 1
        elif state == "block_comment":
            if c == "*" and nxt == "/":
                state, i = "code", i + 2
                out.append("  ")
                continue
            out.append("\n" if c == "\n" else " ")
            i += 1
        elif state in ("string", "char"):
            quote = '"' if state == "string" else "'"
            if c == "\\":
                out.append("  ")
                i += 2
                continue
            if c == quote:
                state = "code"
                out.append(" ")
                i += 1
                continue
            out.append("\n" if c == "\n" else " ")
            i += 1
    return "".join(out)


def line_of(src: str, index: int) -> int:
    return src.count("\n", 0, index) + 1


def to_number(token: str) -> float | None:
    if token is None:
        return None
    t = token.strip().rstrip("fFuUlL")
    try:
        return float(t)
    except ValueError:
        return None


@dataclass
class _Ctx:
    raw: str
    code: str
    lines: list[str]
    constants: dict[str, dict[str, Any]] = field(default_factory=dict)
    pin_defs: dict[str, dict[str, Any]] = field(default_factory=dict)


class FirmwareAnalyzer:
    """Pattern-driven structural analyzer for Arduino-style C/C++ firmware."""

    version = ANALYZER_VERSION

    def analyze(self, source: str, filename: str = "firmware.ino") -> dict[str, Any]:
        t0 = time.perf_counter()
        code = strip_comments_and_strings(source)
        ctx = _Ctx(raw=source, code=code, lines=source.splitlines())

        constants = self._constants(ctx)
        pins = self._pins(ctx, constants)
        pin_modes = self._pin_modes(ctx, pins)
        outputs = self._outputs(ctx, pins, pin_modes)
        inputs = self._inputs(ctx, pins, pin_modes)
        thresholds = self._thresholds(ctx, constants)
        states = self._states(ctx)
        conditions = self._conditions(ctx)
        functions = self._functions(ctx)
        prints = self._serial_prints(ctx)
        peripherals = self._peripherals(ctx, inputs, outputs)
        risks = self._risk_areas(ctx, thresholds, inputs, outputs)
        metrics = self._metrics(ctx, functions, conditions)
        signal_map = self._signal_map(inputs, outputs, thresholds, states, prints, constants)
        summary = self._summary(filename, inputs, outputs, thresholds, states, conditions)

        return {
            "inputs": inputs,
            "outputs": outputs,
            "gpio_pins": list(pins.values()),
            "constants": list(constants.values()),
            "thresholds": thresholds,
            "states": states,
            "conditions": conditions,
            "functions": functions,
            "serial_prints": prints,
            "peripherals": peripherals,
            "risk_areas": risks,
            "metrics": metrics,
            "signal_map": signal_map,
            "summary": summary,
            "analyzer_version": self.version,
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        }

    # ------------------------------------------------------------------
    # Constants & #defines
    # ------------------------------------------------------------------
    def _constants(self, ctx: _Ctx) -> dict[str, dict[str, Any]]:
        consts: dict[str, dict[str, Any]] = {}

        define_re = re.compile(r"^[ \t]*#[ \t]*define[ \t]+(\w+)[ \t]+([^\n\\]+)", re.M)
        for m in define_re.finditer(ctx.code):
            name, value = m.group(1), m.group(2).strip()
            consts[name] = {
                "name": name,
                "value": value,
                "numeric": to_number(value),
                "type": "define",
                "line": line_of(ctx.code, m.start()),
            }

        const_re = re.compile(
            r"\b(?:static\s+)?(?:const|constexpr)\s+"
            r"(int|long|float|double|uint8_t|uint16_t|uint32_t|unsigned\s+int|byte|bool|char)\s+"
            r"(\w+)\s*=\s*([^;]+);",
        )
        for m in const_re.finditer(ctx.code):
            ctype, name, value = m.group(1), m.group(2), m.group(3).strip()
            consts[name] = {
                "name": name,
                "value": value,
                "numeric": to_number(value),
                "type": re.sub(r"\s+", " ", ctype),
                "line": line_of(ctx.code, m.start()),
            }
        return consts

    # ------------------------------------------------------------------
    # Pin discovery
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_pin(value: str, constants: dict[str, dict[str, Any]]) -> int | None:
        v = value.strip()
        if v in ANALOG_ALIASES:
            return ANALOG_ALIASES[v]
        if v == "LED_BUILTIN":
            return 13
        num = to_number(v)
        if num is not None:
            return int(num)
        c = constants.get(v)
        if c:
            if isinstance(c.get("value"), str) and c["value"].strip() in ANALOG_ALIASES:
                return ANALOG_ALIASES[c["value"].strip()]
            if c.get("numeric") is not None:
                return int(c["numeric"])
        return None

    def _pins(self, ctx: _Ctx, constants: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        pins: dict[str, dict[str, Any]] = {}
        for name, c in constants.items():
            val = str(c["value"]).strip()
            looks_like_pin = (
                bool(re.search(r"pin|gpio|led|channel", name, re.I))
                or val in ANALOG_ALIASES
                or val == "LED_BUILTIN"
            )
            if not looks_like_pin:
                continue
            number = self._resolve_pin(val, constants)
            if number is None:
                continue
            pins[name] = {
                "symbol": name,
                "number": number,
                "declared_as": val,
                "is_analog_alias": val in ANALOG_ALIASES,
                "line": c["line"],
                "direction": "unknown",
                "role": self._role_for(name),
            }
        return pins

    @staticmethod
    def _role_for(name: str) -> str:
        low = name.lower()
        for hint, role in OUTPUT_ROLE_HINTS.items():
            if hint in low:
                return role
        for hint, role in INPUT_ROLE_HINTS.items():
            if hint in low:
                return role
        return "gpio"

    def _pin_modes(self, ctx: _Ctx, pins: dict[str, dict[str, Any]]) -> dict[str, str]:
        modes: dict[str, str] = {}
        for m in re.finditer(r"\bpinMode\s*\(\s*([^,]+?)\s*,\s*(\w+)\s*\)", ctx.code):
            sym, mode = m.group(1).strip(), m.group(2).strip()
            modes[sym] = mode
            if sym in pins:
                pins[sym]["direction"] = {
                    "OUTPUT": "output",
                    "INPUT": "input",
                    "INPUT_PULLUP": "input-pullup",
                }.get(mode, "unknown")
        return modes

    # ------------------------------------------------------------------
    # Inputs / outputs
    # ------------------------------------------------------------------
    def _outputs(
        self, ctx: _Ctx, pins: dict[str, dict[str, Any]], modes: dict[str, str]
    ) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for fn, kind in (("digitalWrite", "digital"), ("analogWrite", "pwm")):
            for m in re.finditer(rf"\b{fn}\s*\(\s*([^,]+?)\s*,", ctx.code):
                sym = m.group(1).strip()
                number = pins.get(sym, {}).get("number")
                if number is None:
                    number = self._resolve_pin(sym, {})
                if number is None:
                    continue
                key = str(number)
                entry = found.setdefault(
                    key,
                    {
                        "symbol": sym if not sym.isdigit() else f"PIN_{number}",
                        "pin": number,
                        "kind": kind,
                        "role": self._role_for(sym),
                        "writes": 0,
                        "lines": [],
                        "observable": True,
                    },
                )
                entry["writes"] += 1
                entry["lines"].append(line_of(ctx.code, m.start()))
                if kind == "pwm":
                    entry["kind"] = "pwm"
        return sorted(found.values(), key=lambda e: e["pin"])

    def _inputs(
        self, ctx: _Ctx, pins: dict[str, dict[str, Any]], modes: dict[str, str]
    ) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for fn, kind in (("analogRead", "analog"), ("digitalRead", "digital")):
            for m in re.finditer(rf"\b{fn}\s*\(\s*([^)]+?)\s*\)", ctx.code):
                sym = m.group(1).strip()
                number = pins.get(sym, {}).get("number")
                if number is None:
                    number = self._resolve_pin(sym, {})
                if number is None:
                    continue
                key = str(number)
                entry = found.setdefault(
                    key,
                    {
                        "symbol": sym if not sym.isdigit() else f"PIN_{number}",
                        "pin": number,
                        "kind": kind,
                        "role": self._role_for(sym),
                        "reads": 0,
                        "lines": [],
                        "range": [0, 1023] if kind == "analog" else [0, 1],
                        "stimulus_channel": "analog" if kind == "analog" else "digital",
                    },
                )
                entry["reads"] += 1
                entry["lines"].append(line_of(ctx.code, m.start()))

        # Recover the raw-counts -> engineering-units transfer function so the
        # test generator can express stimulus in physical units (°C) instead of
        # ADC codes.  Supports the two dominant idioms:
        #   (a) T = raw * LSB + OFFSET
        #   (b) T = raw * VREF / ADC_MAX * SCALE      (LM35-style)
        for entry in found.values():
            if entry["kind"] != "analog":
                continue
            tf = self._transfer_function(ctx, entry)
            if tf:
                entry["transfer_function"] = tf
        return sorted(found.values(), key=lambda e: e["pin"])

    def _transfer_function(self, ctx: _Ctx, entry: dict[str, Any]) -> dict[str, Any] | None:
        """Infer scale/offset mapping ADC counts to engineering units."""
        consts = self._constants(ctx)

        def val(tok: str) -> float | None:
            tok = tok.strip()
            num = to_number(tok)
            if num is not None:
                return num
            c = consts.get(tok)
            return c["numeric"] if c and c["numeric"] is not None else None

        # Pattern (a): (raw * LSB) + OFFSET
        m = re.search(
            r"\(\s*\w+\s*\*\s*([\w.]+)\s*\)\s*\+\s*([\w.]+)\s*;",
            ctx.code,
        )
        if m:
            scale, offset = val(m.group(1)), val(m.group(2))
            if scale is not None and offset is not None and scale != 0:
                return {
                    "form": "linear",
                    "scale": scale,
                    "offset": offset,
                    "unit": "degC",
                    "expression": f"raw * {scale} + {offset}",
                    "raw_min": 0,
                    "raw_max": 1023,
                }

        # Pattern (b): volts = raw * VREF / ADC_MAX ; degC = volts * SCALE
        mv = re.search(r"=\s*\(\s*\w+\s*\*\s*([\d.]+)\s*\)\s*/\s*([\d.]+)\s*;", ctx.code)
        ms = re.search(r"return\s+\w+\s*\*\s*([\d.]+)\s*;", ctx.code)
        if mv and ms:
            vref, adc_max, scale = val(mv.group(1)), val(mv.group(2)), val(ms.group(1))
            if vref and adc_max and scale:
                return {
                    "form": "linear",
                    "scale": (vref / adc_max) * scale,
                    "offset": 0.0,
                    "unit": "degC",
                    "expression": f"raw * {vref}/{adc_max} * {scale}",
                    "raw_min": 0,
                    "raw_max": 1023,
                }

        # Pattern (c): Beta-parameter NTC thermistor: 1.0 / (log(...) / BETA + 1.0 / 298.15)
        m_beta = re.search(r"BETA\s*=\s*([\d.]+)", ctx.code) or re.search(r"beta\s*=\s*([\d.]+)", ctx.code)
        if m_beta or ("1023.0 /" in ctx.code and "298.15" in ctx.code):
            beta_val = float(m_beta.group(1)) if m_beta else 3950.0
            return {
                "form": "beta",
                "beta": beta_val,
                "t0": 298.15,
                "unit": "degC",
                "expression": f"1.0 / (log(1.0 / (1023.0 / adc - 1.0)) / {beta_val} + 1.0 / 298.15) - 273.15",
                "raw_min": 0,
                "raw_max": 1023,
            }

        return None

    # ------------------------------------------------------------------
    # Thresholds (boundary candidates)
    # ------------------------------------------------------------------
    def _thresholds(self, ctx: _Ctx, constants: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cmp_re = re.compile(
            rf"(\w+(?:\s*\(\s*\))?)\s*(>=|<=|==|!=|>|<)\s*({NUMERIC_RE}|\w+)"
        )
        for m in cmp_re.finditer(ctx.code):
            lhs, op, rhs = m.group(1).strip(), m.group(2), m.group(3).strip()
            if lhs in {"if", "while", "for", "return", "else"}:
                continue
            rhs_num = to_number(rhs)
            symbolic = None
            if rhs_num is None and rhs in constants:
                rhs_num = constants[rhs]["numeric"]
                symbolic = rhs
            if rhs_num is None:
                continue
            line_no = line_of(ctx.code, m.start())
            results.append(
                {
                    "variable": lhs,
                    "operator": op,
                    "value": rhs_num,
                    "symbolic": symbolic,
                    "is_magic_number": symbolic is None,
                    "line": line_no,
                    "source_line": ctx.lines[line_no - 1].strip() if line_no <= len(ctx.lines) else "",
                    "boundary_candidates": self._boundaries(rhs_num, op),
                }
            )
        # De-duplicate identical comparisons on the same line.
        seen, unique = set(), []
        for r in results:
            key = (r["variable"], r["operator"], r["value"], r["line"])
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    @staticmethod
    def _boundaries(value: float, op: str) -> list[dict[str, Any]]:
        """Classic boundary-value analysis: just below / at / just above."""
        step = 0.25 if abs(value) < 1000 else 1.0
        return [
            {"point": round(value - step, 4), "label": "just_below"},
            {"point": round(value, 4), "label": "at_boundary"},
            {"point": round(value + step, 4), "label": "just_above"},
        ]

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def _states(self, ctx: _Ctx) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = []
        for m in re.finditer(r"\benum\s+(?:class\s+)?(\w+)?\s*\{([^}]*)\}", ctx.code):
            enum_name = (m.group(1) or "AnonymousEnum").strip()
            body = m.group(2)
            members = []
            for idx, raw_member in enumerate(x.strip() for x in body.split(",")):
                if not raw_member:
                    continue
                if "=" in raw_member:
                    nm, v = raw_member.split("=", 1)
                    num = to_number(v)
                    members.append({"name": nm.strip(), "value": int(num) if num is not None else idx})
                else:
                    members.append({"name": raw_member, "value": idx})
            if members:
                states.append(
                    {
                        "enum": enum_name,
                        "line": line_of(ctx.code, m.start()),
                        "members": members,
                        "variables": self._state_vars(ctx, enum_name),
                    }
                )
        return states

    @staticmethod
    def _state_vars(ctx: _Ctx, enum_name: str) -> list[str]:
        return list(
            {
                m.group(1)
                for m in re.finditer(rf"\b{re.escape(enum_name)}\s+(\w+)\s*(?:=|;)", ctx.code)
            }
        )

    # ------------------------------------------------------------------
    # Conditions / branches
    # ------------------------------------------------------------------
    def _conditions(self, ctx: _Ctx) -> list[dict[str, Any]]:
        conds: list[dict[str, Any]] = []
        for m in re.finditer(r"\b(if|else\s+if|while|switch)\s*\(", ctx.code):
            start = m.end() - 1
            depth, i = 0, start
            while i < len(ctx.code):
                if ctx.code[i] == "(":
                    depth += 1
                elif ctx.code[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            expr = ctx.code[start + 1 : i].strip()
            line_no = line_of(ctx.code, m.start())
            conds.append(
                {
                    "kind": re.sub(r"\s+", " ", m.group(1)),
                    "expression": re.sub(r"\s+", " ", expr)[:240],
                    "line": line_no,
                    "operators": sorted(set(re.findall(r">=|<=|==|!=|&&|\|\||>|<", expr))),
                    "source_line": ctx.lines[line_no - 1].strip() if line_no <= len(ctx.lines) else "",
                }
            )
        return conds

    # ------------------------------------------------------------------
    # Functions
    # ------------------------------------------------------------------
    def _functions(self, ctx: _Ctx) -> list[dict[str, Any]]:
        fns: list[dict[str, Any]] = []
        fn_re = re.compile(
            r"^[ \t]*(?:static\s+|inline\s+)*"
            r"((?:const\s+)?(?:unsigned\s+)?[\w:]+[\s*&]+)(\w+)\s*\(([^;{)]*)\)\s*\{",
            re.M,
        )
        for m in fn_re.finditer(ctx.code):
            ret, name, params = m.group(1).strip(), m.group(2), m.group(3).strip()
            if name in {"if", "while", "for", "switch", "return", "else", "do"}:
                continue
            body_start = m.end() - 1
            depth, i = 0, body_start
            while i < len(ctx.code):
                if ctx.code[i] == "{":
                    depth += 1
                elif ctx.code[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = ctx.code[body_start : i + 1]
            calls = sorted(
                {
                    c
                    for c in re.findall(r"\b(\w+)\s*\(", body)
                    if c not in {"if", "while", "for", "switch", "return", "sizeof"}
                }
            )
            fns.append(
                {
                    "name": name,
                    "return_type": ret,
                    "params": params,
                    "line": line_of(ctx.code, m.start()),
                    "end_line": line_of(ctx.code, i),
                    "length_lines": line_of(ctx.code, i) - line_of(ctx.code, m.start()) + 1,
                    "branches": len(re.findall(r"\b(?:if|while|for|case)\b", body)),
                    "calls": calls,
                    "is_entrypoint": name in {"setup", "loop", "main"},
                }
            )
        return fns

    # ------------------------------------------------------------------
    # Serial telemetry protocol inference
    # ------------------------------------------------------------------
    def _serial_prints(self, ctx: _Ctx) -> list[dict[str, Any]]:
        prints: list[dict[str, Any]] = []
        # Operate on the RAW source here — we need the string literals back.
        for m in re.finditer(
            r"Serial\d?\.(print|println)\s*\(\s*(?:F\s*\(\s*)?\"((?:[^\"\\]|\\.)*)\"",
            ctx.raw,
        ):
            literal = m.group(2)
            prints.append(
                {
                    "method": m.group(1),
                    "literal": literal,
                    "line": line_of(ctx.raw, m.start()),
                    "keys": re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*=", literal),
                }
            )
        keys: list[str] = []
        for p in prints:
            for k in p["keys"]:
                if k not in keys:
                    keys.append(k)
        for p in prints:
            p["protocol_keys"] = keys
        return prints

    # ------------------------------------------------------------------
    # Peripherals
    # ------------------------------------------------------------------
    def _peripherals(
        self, ctx: _Ctx, inputs: list[dict[str, Any]], outputs: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        peripherals: list[dict[str, Any]] = []
        baud_match = re.search(r"Serial\d?\.begin\s*\(\s*(\d+)", ctx.code)
        if baud_match:
            peripherals.append(
                {
                    "type": "UART",
                    "detail": f"Serial @ {baud_match.group(1)} baud",
                    "line": line_of(ctx.code, baud_match.start()),
                }
            )
        if any(i["kind"] == "analog" for i in inputs):
            peripherals.append(
                {"type": "ADC", "detail": f"{sum(1 for i in inputs if i['kind'] == 'analog')} analog channel(s)", "line": 0}
            )
        if any(o["kind"] == "pwm" for o in outputs):
            peripherals.append({"type": "PWM", "detail": "analogWrite duty control", "line": 0})
        if re.search(r"\bmillis\s*\(|\bmicros\s*\(", ctx.code):
            peripherals.append({"type": "Timer", "detail": "millis()/micros() time base", "line": 0})
        if re.search(r"\battachInterrupt\s*\(", ctx.code):
            peripherals.append({"type": "Interrupt", "detail": "external interrupt handler", "line": 0})
        if re.search(r"\bWire\.", ctx.code):
            peripherals.append({"type": "I2C", "detail": "Wire library", "line": 0})
        if re.search(r"\bSPI\.", ctx.code):
            peripherals.append({"type": "SPI", "detail": "SPI library", "line": 0})
        return peripherals

    # ------------------------------------------------------------------
    # Risk heuristics
    # ------------------------------------------------------------------
    def _risk_areas(
        self,
        ctx: _Ctx,
        thresholds: list[dict[str, Any]],
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        risks: list[dict[str, Any]] = []

        for t in thresholds:
            if t["is_magic_number"] and t["value"] not in (0, 1, 2, -1):
                risks.append(
                    {
                        "kind": "magic-number-threshold",
                        "severity": "medium",
                        "line": t["line"],
                        "detail": (
                            f"Comparison `{t['variable']} {t['operator']} {t['value']}` uses a hard-coded "
                            f"literal instead of a named constant — a classic site for spec drift."
                        ),
                        "test_hint": "boundary-value",
                    }
                )
            if t["operator"] in (">", "<"):
                risks.append(
                    {
                        "kind": "strict-inequality-boundary",
                        "severity": "high" if t["is_magic_number"] else "medium",
                        "line": t["line"],
                        "detail": (
                            f"`{t['variable']} {t['operator']} {t['value']}` excludes the exact boundary "
                            f"value. If the requirement says 'at or above', this is an off-by-one defect."
                        ),
                        "test_hint": "at_boundary",
                    }
                )

        if re.search(r"\bdelay\s*\(\s*(\d{4,})\s*\)", ctx.code):
            risks.append(
                {
                    "kind": "long-blocking-delay",
                    "severity": "medium",
                    "line": line_of(ctx.code, re.search(r"\bdelay\s*\(\s*\d{4,}\s*\)", ctx.code).start()),
                    "detail": "Long blocking delay() stalls the control loop and delays fault reaction.",
                    "test_hint": "timing",
                }
            )

        # Mutually-exclusive actuators driven without an explicit interlock.
        actuators = [o for o in outputs if o["role"] == "actuator"]
        if len(actuators) >= 2:
            names = ", ".join(a["symbol"] for a in actuators)
            risks.append(
                {
                    "kind": "actuator-mutual-exclusion",
                    "severity": "high",
                    "line": actuators[0]["lines"][0] if actuators[0]["lines"] else 0,
                    "detail": (
                        f"Multiple actuators ({names}) are driven from the same control loop. "
                        f"Verify they can never be energised simultaneously."
                    ),
                    "test_hint": "mutual-exclusion",
                }
            )

        for i in inputs:
            if i["kind"] == "analog":
                guarded = bool(re.search(r"(MIN_VALID|MAX_VALID|isnan|out_of_range|OUT_OF_RANGE)", ctx.raw, re.I))
                risks.append(
                    {
                        "kind": "sensor-range-validation",
                        "severity": "low" if guarded else "high",
                        "line": i["lines"][0] if i["lines"] else 0,
                        "detail": (
                            f"Analog input `{i['symbol']}` "
                            + ("has a plausibility guard — verify it triggers correctly."
                               if guarded else
                               "is consumed without any range/plausibility check.")
                        ),
                        "test_hint": "fault-injection",
                    }
                )
        return risks

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def _metrics(
        self, ctx: _Ctx, functions: list[dict[str, Any]], conditions: list[dict[str, Any]]
    ) -> dict[str, Any]:
        loc = len([ln for ln in ctx.lines if ln.strip()])
        branches = len(conditions)
        logical = len(re.findall(r"&&|\|\|", ctx.code))
        return {
            "total_lines": len(ctx.lines),
            "code_lines": loc,
            "comment_lines": len([ln for ln in ctx.lines if ln.strip().startswith(("//", "*", "/*"))]),
            "function_count": len(functions),
            "branch_count": branches,
            "cyclomatic_complexity": branches + logical + 1,
            "max_function_length": max((f["length_lines"] for f in functions), default=0),
            "sha256": hashlib.sha256(ctx.raw.encode()).hexdigest()[:16],
        }

    # ------------------------------------------------------------------
    # Signal map — the execution contract
    # ------------------------------------------------------------------
    def _signal_map(
        self,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        thresholds: list[dict[str, Any]],
        states: list[dict[str, Any]],
        prints: list[dict[str, Any]],
        constants: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        primary_input = next((i for i in inputs if i["kind"] == "analog"), None)
        telemetry_keys = prints[0]["protocol_keys"] if prints else []
        return {
            "stimulus_channels": [
                {
                    "name": i["symbol"],
                    "pin": i["pin"],
                    "kind": i["kind"],
                    "unit": i.get("transfer_function", {}).get("unit", "counts"),
                    "transfer_function": i.get("transfer_function"),
                    "range": i["range"],
                }
                for i in inputs
            ],
            "observable_outputs": [
                {"name": o["symbol"], "pin": o["pin"], "kind": o["kind"], "role": o["role"]}
                for o in outputs
            ],
            "telemetry_keys": telemetry_keys,
            "primary_input": primary_input["symbol"] if primary_input else None,
            "named_thresholds": {
                c["name"]: c["numeric"]
                for c in constants.values()
                if c["numeric"] is not None and re.search(r"threshold|critical|target|limit|max|min|hyster", c["name"], re.I)
            },
            "state_enum": states[0]["enum"] if states else None,
            "state_names": [m["name"] for m in states[0]["members"]] if states else [],
        }

    # ------------------------------------------------------------------
    def _summary(
        self,
        filename: str,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        thresholds: list[dict[str, Any]],
        states: list[dict[str, Any]],
        conditions: list[dict[str, Any]],
    ) -> str:
        parts = [
            f"`{filename}` exposes {len(inputs)} input channel(s) and {len(outputs)} observable output(s).",
            f"{len(thresholds)} numeric comparison(s) were recovered as boundary-test candidates.",
        ]
        if states:
            parts.append(
                f"A {len(states[0]['members'])}-state machine (`{states[0]['enum']}`) drives the control flow."
            )
        parts.append(f"{len(conditions)} conditional branch(es) require coverage.")
        return " ".join(parts)


def analyze_source(source: str, filename: str = "firmware.ino") -> dict[str, Any]:
    """Convenience wrapper used by the API layer."""
    return FirmwareAnalyzer().analyze(source, filename)
