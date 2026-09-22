#!/bin/bash
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_EXEC="$DIR/backend/venv/bin/python"

if [ ! -f "$PYTHON_EXEC" ]; then
    echo "Virtual environment not found. Using system python3..."
    PYTHON_EXEC="python3"
fi

"$PYTHON_EXEC" "$DIR/run_pipeline.py" "$@"
