@echo off
rem Doppelklick beendet Story World (Server auf Port 8765). Der MCP-Server fuer Claude bleibt unangetastet.
chcp 65001 >nul
set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8765 .*LISTENING"') do (
  set "FOUND=1"
  echo Beende Prozess %%p
  taskkill /PID %%p /F >nul 2>&1
)
if not defined FOUND echo Story World laeuft nicht.
timeout /t 2 >nul
