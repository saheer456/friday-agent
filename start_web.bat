@echo off
setlocal enabledelayedexpansion
title FRIDAY — Initializing...
cd /d "%~dp0"

echo.
echo  ============================================================
echo    F . R . I . D . A . Y   ^|  Full Responsive Interface
echo    Networked Assistant for You  ^|  v2.0 Sentinel
echo  ============================================================
echo.

REM ── Check Python ─────────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
  echo  [ERROR] Python not found. Please install Python 3.10+
  pause & exit /b 1
)

REM ── Check Node / npm ─────────────────────────────────────────
where npm >nul 2>&1
if errorlevel 1 (
  echo  [WARN]  npm not found — skipping frontend build check.
  goto :start_server
)

REM ── Rebuild React frontend if source is newer than dist ──────
if not exist "frontend\dist\index.html" (
  echo  [BUILD] React dist not found — building frontend...
  cd frontend
  call npm install --silent
  call npm run build
  cd ..
  if errorlevel 1 (
    echo  [ERROR] Frontend build failed. Run 'cd frontend ^&^& npm run build' manually.
    pause & exit /b 1
  )
  echo  [BUILD] React frontend built successfully.
  echo.
)

:start_server
title FRIDAY Web — Running on http://127.0.0.1:8080

REM ── Delay, then open browser ─────────────────────────────────
start "" cmd /c "ping 127.0.0.1 -n 5 >nul & start http://127.0.0.1:8080/"

echo  [START] Booting FastAPI server on http://127.0.0.1:8080
echo  [INFO]  Press Ctrl+C to stop the server.
echo  [INFO]  For hot-reload dev mode: cd frontend ^&^& npm run dev
echo  ============================================================
echo.

python -m uvicorn web.server:app --host 127.0.0.1 --port 8080

REM ── Server exited ─────────────────────────────────────────────
echo.
if errorlevel 1 (
  echo  [FAULT] Server exited with an error.
  echo  [TIP]   Try: pip install fastapi "uvicorn[standard]" aiosqlite pydantic
) else (
  echo  [INFO] Server stopped.
)
echo.
pause
