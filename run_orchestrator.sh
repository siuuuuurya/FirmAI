#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$SCRIPT_DIR/backend:$SCRIPT_DIR:$PYTHONPATH"

# Run the 4-phase Architect & Judge Wokwi Autonomous Testing Orchestrator
"$SCRIPT_DIR/backend/venv/bin/python3" "$SCRIPT_DIR/wokwi_orchestrator.py" "$@"
