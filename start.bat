@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
venv\Scripts\python cli.py
pause
