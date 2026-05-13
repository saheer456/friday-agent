@echo off
setlocal
title FRIDAY Web Server
cd /d "%~dp0"

REM Start browser shortly after server begins accepting connections
start "FRIDAY Browser" cmd /c "ping 127.0.0.1 -n 4 >nul & start http://127.0.0.1:8080/"

echo.
echo  [ FRIDAY ]  Starting web server on http://127.0.0.1:8080
echo  Press Ctrl+C in this window to stop the server.
echo.

python -m uvicorn web.server:app --host 127.0.0.1 --port 8080

if errorlevel 1 (
  echo.
  echo  If python failed, try:  pip install fastapi "uvicorn[standard]"
  echo.
  pause
)
