@echo off
setlocal

title FRIDAY — Initializing...
cd /d "%~dp0"

echo.
echo  ============================================================
echo    F . R . I . D . A . Y   ^|  Full Responsive Interface
echo    Networked Assistant for You  ^|  v2.6 Sentinel
echo  ============================================================
echo.

REM ─────────────────────────────────────────────────────────────
REM Verify venv exists
REM ─────────────────────────────────────────────────────────────

if not exist "venv\Scripts\python.exe" (
echo [ERROR] Virtual environment not found.
echo.
echo Create it with:
echo     py -3.11 -m venv venv
echo.
pause
exit /b 1
)

REM ─────────────────────────────────────────────────────────────
REM Force isolated environment
REM ─────────────────────────────────────────────────────────────

set PYTHONNOUSERSITE=1
set PYTHONPATH=
set PIP_DISABLE_PIP_VERSION_CHECK=1

REM Activate venv
call venv\Scripts\activate.bat

REM ─────────────────────────────────────────────────────────────
REM Verify correct interpreter
REM ─────────────────────────────────────────────────────────────

echo [INFO] Python executable:
where python

echo.
python --version

echo.
echo [INFO] Checking environment isolation...
python -c "import sys; print('\n'.join(sys.path))"

echo.
echo ============================================================
echo.

REM ─────────────────────────────────────────────────────────────
REM Check npm
REM ─────────────────────────────────────────────────────────────

where npm >nul 2>&1
if errorlevel 1 (
echo [WARN] npm not found — skipping frontend build.
goto :start_server
)

REM ─────────────────────────────────────────────────────────────
REM Build frontend if needed or requested
REM ─────────────────────────────────────────────────────────────

set BUILD_FRONTEND=0
if "%1"=="--build" set BUILD_FRONTEND=1
if "%1"=="-b" set BUILD_FRONTEND=1
if "%2"=="--build" set BUILD_FRONTEND=1
if "%2"=="-b" set BUILD_FRONTEND=1

if not exist "frontend\dist\index.html" (
    set BUILD_FRONTEND=1
)

if "%BUILD_FRONTEND%"=="1" (
    echo [BUILD] Frontend build requested or missing — compiling...
    cd frontend
    if not exist "node_modules" (
        echo [BUILD] Installing npm packages...
        call npm install
        if errorlevel 1 (
            echo [ERROR] npm install failed.
            pause
            exit /b 1
        )
    )
    call npm run build
    if errorlevel 1 (
        echo [ERROR] Frontend build failed.
        pause
        exit /b 1
    )
    cd ..
    echo [BUILD] Frontend build complete.
    echo.
) else (
    echo [INFO] Skipping frontend build (dist/index.html exists). Use --build to rebuild.
    echo.
)


:start_server

title FRIDAY Web — http://127.0.0.1:8080

echo [START] Booting FastAPI server...
echo [INFO]  URL: http://127.0.0.1:8080
echo [INFO]  Ctrl+C to stop
echo ============================================================
echo.

REM Open browser after delay
start "" cmd /c "ping 127.0.0.1 -n 5 >nul && start http://127.0.0.1:8080/"

REM ─────────────────────────────────────────────────────────────
REM Run server
REM ─────────────────────────────────────────────────────────────

python -X faulthandler -m uvicorn web.server:app ^
    --host 127.0.0.1 ^
    --port 8080 ^
    --log-level info

REM ─────────────────────────────────────────────────────────────
REM Exit handling
REM ─────────────────────────────────────────────────────────────

echo.
echo ============================================================

if errorlevel 1 (
echo [FAULT] Server exited with error.
) else (
echo [INFO] Server stopped normally.
)

echo ============================================================
echo.
pause
