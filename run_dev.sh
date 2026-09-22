#!/usr/bin/env bash
# ==============================================================================
# FirmAI Full-Stack Development Launcher (Backend API + Interactive React UI)
# ==============================================================================
set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting FirmAI Backend on http://localhost:8000..."
cd "$ROOT_DIR/backend"
"$ROOT_DIR/backend/venv/bin/python3" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
BACKEND_PID=$!

echo "Starting FirmAI Frontend on http://localhost:5173..."
cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true" EXIT INT TERM

echo ""
echo "=================================================================="
echo " FirmAI Autonomous Embedded Firmware Testing Agent is running!   "
echo "=================================================================="
echo "  • Web Dashboard : http://localhost:5173"
echo "  • Swagger API   : http://localhost:8000/docs"
echo "  • Health Check  : http://localhost:8000/api/health"
echo "=================================================================="
echo "Press Ctrl+C to stop both servers."

wait
