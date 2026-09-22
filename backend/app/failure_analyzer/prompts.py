"""Prompt templates for failure diagnosis."""
from __future__ import annotations

import json
from typing import Any

from app.test_generator.prompts import FAILURE_SYSTEM

FAILURE_ANALYSIS_SYSTEM = FAILURE_SYSTEM


def build_failure_analysis_user_prompt(
    filename: str,
    source_code: str,
    test_result: dict[str, Any],
    case_info: dict[str, Any] | None = None,
) -> str:
    """Build a compact failure-analysis prompt for an external LLM."""
    numbered_source = "\n".join(
        f"{line_no:4d}: {line}" for line_no, line in enumerate(source_code.splitlines(), 1)
    )
    return f"""\
FIRMWARE FILE: {filename}

===== SOURCE (line-numbered) =====
{numbered_source}
===== END SOURCE =====

===== TEST CASE =====
{json.dumps(case_info or {}, indent=2)}
===== FAILED RESULT =====
{json.dumps(test_result, indent=2)}
===== END RESULT =====

Analyse the failure and return ONLY the JSON object.
"""
