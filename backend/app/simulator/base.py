"""
Abstract simulator interface
============================
Every execution backend (local native simulation, Wokwi, Renode, real
hardware-in-the-loop) implements this contract, so the orchestrator is fully
decoupled from *how* the firmware runs.

Two-phase protocol
------------------
    build(firmware)        -> BuildArtifact   (compile once)
    execute(artifact, req) -> ExecutionResult (run per test case)

`ExecutionResult` is the single observation envelope the evaluator consumes;
it is intentionally hardware-agnostic (pins + UART + timeline + status).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


class SimulatorUnavailable(RuntimeError):
    """Raised when a backend cannot run in the current environment."""


@dataclass
class BuildArtifact:
    """Result of compiling/preparing firmware for a specific backend."""

    ok: bool
    artifact_path: str = ""
    log: str = ""
    duration_ms: float = 0.0
    backend: str = ""
    error: str = ""


@dataclass
class StimulusEvent:
    """A scheduled change of a virtual input channel."""

    tick: int
    pin: int
    kind: str  # "analog" | "digital"
    raw_value: int
    engineering_value: float | None = None
    unit: str = "counts"
    channel: str = ""


@dataclass
class SimulationRequest:
    """Everything a backend needs to execute one test case."""

    test_id: str
    ticks: int = 6
    tick_ms: int = 100
    events: list[StimulusEvent] = field(default_factory=list)
    watch_pins: list[int] = field(default_factory=list)
    timeout_ms: int = 5000


@dataclass
class ExecutionResult:
    """Hardware-agnostic observation envelope."""

    status: str  # "ok" | "error" | "timeout" | "crash" | "build_failed"
    uart: str = ""
    setup_uart: str = ""
    pins: dict[str, dict[str, Any]] = field(default_factory=dict)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    ticks_executed: int = 0
    elapsed_ms: float = 0.0
    wall_ms: float = 0.0
    backend: str = ""
    execution_mode: str = ""
    error: str = ""
    raw_stdout: str = ""
    raw_stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class SimulatorInterface(abc.ABC):
    """Abstract virtual-hardware backend."""

    #: stable identifier used in configuration and the UI
    name: str = "abstract"
    #: human-readable label
    label: str = "Abstract Simulator"
    #: describes how faithfully firmware is executed — surfaced in the UI so a
    #: viewer always knows whether code really ran
    execution_mode: str = "unknown"

    @abc.abstractmethod
    def available(self) -> tuple[bool, str]:
        """Return (is_available, human-readable reason)."""

    @abc.abstractmethod
    async def build(self, source: str, workspace: str, filename: str = "firmware.ino") -> BuildArtifact:
        """Compile/prepare the firmware once per run."""

    @abc.abstractmethod
    async def execute(self, artifact: BuildArtifact, request: SimulationRequest) -> ExecutionResult:
        """Execute a single test scenario against the built firmware."""

    async def teardown(self, artifact: BuildArtifact) -> None:  # pragma: no cover - optional
        """Release backend resources (no-op by default)."""
        return None

    def describe(self) -> dict[str, Any]:
        ok, reason = self.available()
        return {
            "name": self.name,
            "label": self.label,
            "execution_mode": self.execution_mode,
            "available": ok,
            "reason": reason,
        }
