@echo off
setlocal

set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD where py >nul 2>nul && set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
  echo Python 3 was not found. Install Python 3.11+ or add it to PATH, then run this script again.
  pause
  exit /b 1
)

echo Starting FirmAI backend on http://localhost:8000...
start "FirmAI Backend" cmd /k "cd /d %~dp0backend && if not exist venv %PYTHON_CMD% -m venv venv && call venv\Scripts\activate.bat && python -m pip install -r requirements.txt && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"

echo Starting FirmAI frontend on http://localhost:5173...
start "FirmAI Frontend" cmd /k "cd /d %~dp0frontend && if not exist node_modules npm install && npm run dev"

echo FirmAI is starting.
echo Backend API: http://localhost:8000/docs
echo Frontend UI: http://localhost:5173
endlocal
