"""
RenodeSimulator — architectural stub
====================================
Renode (antmicro.com/renode) is a full-system emulator able to run unmodified
firmware binaries for Cortex-M, RISC-V and other targets, with cycle-level
peripheral models and scriptable GPIO/UART manipulation via its Robot/monitor
interface.

Same contract as every other backend; reports UNAVAILABLE unless `renode` is
on PATH.  No synthetic data is ever produced by this class.

To finish the integration
-------------------------
1. Install Renode and a cross toolchain (`arm-none-eabi-gcc`).
2. `build()`  : cross-compile the firmware to an .elf for the chosen platform.
3. `execute()`: emit a `.resc` script that loads the platform description,
   sets GPIO input levels per scenario tick, creates a UART analyzer, runs for
   the requested virtual time, then dumps state — parse it into
   `ExecutionResult`.
"""
from __future__ import annotations

import shutil

from app.simulator.base import (
    BuildArtifact,
    ExecutionResult,
    SimulationRequest,
    SimulatorInterface,
    SimulatorUnavailable,
)


class RenodeSimulator(SimulatorInterface):
    name = "renode"
    label = "Renode Full-System Emulator (Cortex-M / RISC-V)"
    execution_mode = "cycle-accurate-emulation"

    def available(self) -> tuple[bool, str]:
        if not shutil.which("renode"):
            return False, "renode is not installed or not on PATH"
        if not shutil.which("arm-none-eabi-gcc"):
            return False, "arm-none-eabi-gcc cross toolchain not found"
        return True, "renode and cross toolchain detected"

    async def build(self, source: str, workspace: str, filename: str = "firmware.ino") -> BuildArtifact:
        ok, reason = self.available()
        if not ok:
            raise SimulatorUnavailable(f"Renode backend unavailable: {reason}")
        raise SimulatorUnavailable(
            "Renode backend is scaffolded but not implemented in this MVP. "
            "Use simulator_backend=local_deterministic."
        )

    async def execute(self, artifact: BuildArtifact, request: SimulationRequest) -> ExecutionResult:
        raise SimulatorUnavailable(
            "Renode backend is scaffolded but not implemented in this MVP."
        )
