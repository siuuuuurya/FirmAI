#!/usr/bin/env python3
"""
Firmware Verification & Debugging CLI Runner
===========================================
Executes the strict 7-step sequence:
  1. Provide embedded firmware to the system
  2. AI analyses the firmware
  3. AI generates test scenarios
  4. Tests run in a virtual hardware environment
  5. Firmware behaviour is observed
  6. Failures are identified
  7. A test/debugging report is generated
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure backend is in python path
ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# ANSI Color formatting
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
BLUE = "\033[34m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"


def print_step_header(step_num: int, title: str, description: str = "") -> None:
    print(f"\n{BOLD}{CYAN}┌{'─'*70}┐{RESET}")
    print(f"{BOLD}{CYAN}│ [STEP {step_num}/7] {title:<61}│{RESET}")
    if description:
        print(f"{BOLD}{CYAN}│ {DIM}{description:<69}{RESET}{BOLD}{CYAN}│{RESET}")
    print(f"{BOLD}{CYAN}└{'─'*70}┘{RESET}")


def progress_hook(step_num: int, step_name: str, message: str) -> None:
    icons = {
        1: "📥",
        2: "🧠",
        3: "⚡",
        4: "⚙️ ",
        5: "👁️ ",
        6: "🔍",
        7: "📊",
    }
    icon = icons.get(step_num, "▶")
    print(f"  {icon} {BOLD}Step {step_num}:{RESET} {message}")


async def main_async(args: argparse.Namespace) -> int:
    from app.core.config import EXAMPLES_DIR
    from app.core.firmware_pipeline import FirmwarePipeline

    # Determine firmware source
    target_file = Path(args.firmware)
    if not target_file.exists():
        # Check in examples dir
        candidate = EXAMPLES_DIR / args.firmware
        if candidate.exists():
            target_file = candidate
        else:
            print(f"{RED}{BOLD}Error:{RESET} Firmware file `{args.firmware}` not found.", file=sys.stderr)
            return 1

    print(f"\n{BOLD}{MAGENTA}======================================================================{RESET}")
    print(f"{BOLD}{MAGENTA}        AUTONOMOUS EMBEDDED FIRMWARE AI TEST & DEBUG PIPELINE        {RESET}")
    print(f"{BOLD}{MAGENTA}======================================================================{RESET}")
    print(f"  Target Firmware : {BOLD}{target_file.name}{RESET}")
    print(f"  Path            : {DIM}{target_file.resolve()}{RESET}")
    print(f"  Max Scenarios   : {args.max_tests}")
    print(f"  Simulator       : {args.simulator}")
    print(f"  Use LLM Engine  : {args.use_llm}")
    print(f"{DIM}──────────────────────────────────────────────────────────────────────{RESET}")

    pipeline = FirmwarePipeline(progress_callback=progress_hook)

    try:
        report = await pipeline.run_pipeline(
            file_path=target_file,
            max_tests=args.max_tests,
            focus=args.focus,
            use_llm=args.use_llm,
            simulator_backend=args.simulator,
            output_dir=args.output_dir,
        )
    except Exception as exc:
        print(f"\n{RED}{BOLD}Pipeline Execution Halted with Error:{RESET} {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2

    # Executive Summary Banner
    verdict_color = GREEN if report.verdict == "PASS" else (YELLOW if report.verdict == "PARTIAL" else RED)

    print(f"\n{BOLD}{CYAN}======================================================================{RESET}")
    print(f"{BOLD}{CYAN}                       PIPELINE EXECUTION SUMMARY                     {RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}")
    print(f"  Verdict          : {verdict_color}{BOLD}{report.verdict}{RESET}")
    print(f"  Pass Rate        : {BOLD}{report.pass_rate}%{RESET} ({report.passed_tests}/{report.total_tests} passed)")
    print(f"  Failures/Errors  : {BOLD}{report.failed_tests + report.errored_tests}{RESET}")
    print(f"  Total Duration   : {BOLD}{report.total_duration_ms:.1f}ms{RESET}")
    print(f"\n{BOLD}Step Execution Timing:{RESET}")
    for s in report.steps:
        st_color = GREEN if s.status == "completed" else RED
        print(f"   Step {s.step_number} [{st_color}OK{RESET}] {s.step_name:<46} : {s.duration_ms:7.1f}ms")

    if report.failures:
        print(f"\n{BOLD}{RED}Identified Failure Diagnoses ({len(report.failures)}):{RESET}")
        for idx, f in enumerate(report.failures, start=1):
            print(f"\n  {BOLD}{RED}[Defect #{idx}] {f['test_id']}: {f['name']}{RESET}")
            print(f"    Severity     : {f['severity'].upper()}")
            print(f"    Root Cause   : {BOLD}{f['root_cause']}{RESET}")
            print(f"    Explanation  : {f['explanation']}")
            if f.get('suspect_lines'):
                print(f"    Suspect Lines: {f['suspect_lines']}")
            if f.get('suggested_fix'):
                print(f"    Suggested Fix: {CYAN}{f['suggested_fix']}{RESET}")

    print(f"\n{BOLD}{GREEN}Generated Audit Reports:{RESET}")
    if report.html_path:
        print(f"  Interactive HTML Report: {BOLD}file://{Path(report.html_path).resolve()}{RESET}")
    if report.json_path:
        print(f"  Machine-Readable JSON  : {BOLD}file://{Path(report.json_path).resolve()}{RESET}")
    print(f"{BOLD}{CYAN}======================================================================{RESET}\n")

    return 0 if report.verdict == "PASS" else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Strictly sequential 7-step embedded firmware verification & debugging pipeline"
    )
    parser.add_argument(
        "firmware",
        nargs="?",
        default="temperature_controller_buggy.ino",
        help="Path or name of the firmware file (default: temperature_controller_buggy.ino)",
    )
    parser.add_argument(
        "--max-tests",
        type=int,
        default=6,
        help="Maximum synthesized test scenarios (default: 6)",
    )
    parser.add_argument(
        "--focus",
        type=str,
        default="boundary and safety constraints",
        help="Test synthesis focus",
    )
    parser.add_argument(
        "--simulator",
        type=str,
        default="local_deterministic",
        help="Simulator backend (local_deterministic, wokwi, renode)",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        default=False,
        help="Use LLM for test generation and failure diagnosis (requires API key)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write output HTML and JSON reports",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
