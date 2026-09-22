"""
Simulator Manager
=================
* Owns the backend registry and selection policy.
* Translates a *logical* test case (stimulus in engineering units, e.g. °C)
  into a *physical* `SimulationRequest` (raw ADC counts on real pin numbers)
  using the transfer function recovered by the static analyzer.

This translation layer is what lets the AI reason in physical units while the
virtual hardware is still driven at the register level.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.simulator.base import (
    SimulationRequest,
    SimulatorInterface,
    SimulatorUnavailable,
    StimulusEvent,
)
from app.simulator.local_simulator import LocalDeterministicSimulator
from app.simulator.renode_simulator import RenodeSimulator
from app.simulator.wokwi_simulator import WokwiSimulator

logger = logging.getLogger("firmwareai.simulator")


class SimulatorManager:
    """Registry + stimulus compiler for all virtual-hardware backends."""

    def __init__(self) -> None:
        self._backends: dict[str, SimulatorInterface] = {
            b.name: b
            for b in (
                LocalDeterministicSimulator(),
                WokwiSimulator(),
                RenodeSimulator(),
            )
        }

    # ------------------------------------------------------------------
    def get(self, name: str | None = None) -> SimulatorInterface:
        key = (name or settings.simulator_backend or "local_deterministic").lower()
        backend = self._backends.get(key)
        if backend is None:
            raise SimulatorUnavailable(
                f"Unknown simulator backend `{key}`. "
                f"Available: {', '.join(sorted(self._backends))}"
            )
        ok, reason = backend.available()
        if not ok:
            raise SimulatorUnavailable(f"Backend `{key}` is not available: {reason}")
        return backend

    def describe_all(self) -> list[dict[str, Any]]:
        return [b.describe() for b in self._backends.values()]

    # ------------------------------------------------------------------
    # Logical test case -> physical simulation request
    # ------------------------------------------------------------------
    def compile_request(
        self,
        test_case: dict[str, Any],
        signal_map: dict[str, Any],
    ) -> SimulationRequest:
        """Lower engineering-unit stimulus onto concrete pins and ADC codes."""
        stim = test_case.get("stimulus") or {}
        channels = {c["name"]: c for c in signal_map.get("stimulus_channels", [])}
        watch = [o["pin"] for o in signal_map.get("observable_outputs", [])]

        events: list[StimulusEvent] = []
        for ev in stim.get("events") or []:
            channel = channels.get(ev.get("channel"))
            if channel is None:
                logger.debug("skipping stimulus for unknown channel %s", ev.get("channel"))
                continue
            value = float(ev.get("value", 0))
            unit = str(ev.get("unit", "counts"))
            raw = self._to_raw(value, unit, channel)
            events.append(
                StimulusEvent(
                    tick=int(ev.get("tick", -1)),
                    pin=int(channel["pin"]),
                    kind="analog" if channel["kind"] == "analog" else "digital",
                    raw_value=raw,
                    engineering_value=value,
                    unit=unit,
                    channel=channel["name"],
                )
            )

        return SimulationRequest(
            test_id=str(test_case.get("test_id", "TC")),
            ticks=int(stim.get("ticks", 6) or 6),
            tick_ms=int(stim.get("tick_ms", 100) or 100),
            events=events,
            watch_pins=watch,
            timeout_ms=int(test_case.get("timeout_ms", 5000) or 5000),
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _to_raw(value: float, unit: str, channel: dict[str, Any]) -> int:
        """
        Invert the sensor transfer function: engineering units -> ADC counts.

        Falls back to treating the value as raw counts when no transfer
        function was recovered (so the pipeline still works on unknown HW).
        """
        if channel["kind"] != "analog":
            return 1 if value else 0

        tf = channel.get("transfer_function")
        lo, hi = channel.get("range", [0, 1023])
        if not tf or unit in ("counts", "raw", "adc"):
            return int(max(lo, min(round(value), hi)))

        if tf.get("form") == "beta":
            import math
            beta = float(tf.get("beta") or 3950.0)
            t0 = float(tf.get("t0") or 298.15)
            tk = value + 273.15
            if tk <= 0:
                return lo
            try:
                ratio = math.exp(-beta * (1.0 / tk - 1.0 / t0))
                raw = 1023.0 / (1.0 + ratio)
                return int(max(lo, min(round(raw), hi)))
            except (OverflowError, ZeroDivisionError):
                return lo

        scale = float(tf.get("scale") or 1.0)
        offset = float(tf.get("offset") or 0.0)
        if scale == 0:
            return int(max(lo, min(round(value), hi)))

        raw = (value - offset) / scale
        return int(max(lo, min(round(raw), hi)))

    @staticmethod
    def to_engineering(raw: float, channel: dict[str, Any]) -> float:
        """Forward transfer: ADC counts -> engineering units (for reporting)."""
        tf = channel.get("transfer_function")
        if not tf:
            return float(raw)
        if tf.get("form") == "beta":
            import math
            beta = float(tf.get("beta") or 3950.0)
            t0 = float(tf.get("t0") or 298.15)
            if raw <= 0 or raw >= 1023:
                return -273.15
            try:
                t = 1.0 / (math.log(1.0 / (1023.0 / raw - 1.0)) / beta + 1.0 / t0) - 273.15
                return round(t, 2)
            except (ValueError, ZeroDivisionError):
                return -273.15
        return float(raw) * float(tf.get("scale", 1.0)) + float(tf.get("offset", 0.0))


_manager: SimulatorManager | None = None


def get_simulator_manager() -> SimulatorManager:
    global _manager
    if _manager is None:
        _manager = SimulatorManager()
    return _manager
