@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo ============================================================
echo    F . R . I . D . A . Y   ^|  Web Server
echo ============================================================
echo.
if not exist "venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run: py -3.11 -m venv venv
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
python -m uvicorn web.server:app --host 127.0.0.1 --port 8080
pause
