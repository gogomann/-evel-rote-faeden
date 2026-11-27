@echo off
rem Installation (Windows):  install.bat [--backend auto^|cuda^|onnx] [--ja]
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.10 oder neuer nicht gefunden: https://www.python.org/downloads/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  %PY% -m venv .venv
  if errorlevel 1 goto :err
)
".venv\Scripts\python.exe" installer.py %*
if errorlevel 1 goto :err
pause
exit /b 0

:err
echo.
echo Installation fehlgeschlagen.
pause
exit /b 1
