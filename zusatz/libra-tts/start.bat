@echo off
rem Start (Windows):  start.bat [PORT] [--lang de] [--voice nina] [--host 127.0.0.1] [--api-key KEY]
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Bitte zuerst install.bat ausfuehren.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" server.py %*
pause
