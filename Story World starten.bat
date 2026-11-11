@echo off
rem Doppelklick startet Story World und oeffnet den Browser. Fenster offen lassen; Strg+C oder Fenster schliessen beendet.
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if defined PY %PY% -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 || set "PY="
if not defined PY (
  echo Python 3.9 oder neuer wurde nicht gefunden.
  echo Bitte von https://www.python.org/downloads/ installieren ^(Haken bei "Add python.exe to PATH" setzen^).
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
%PY% -m story_world ui
pause
