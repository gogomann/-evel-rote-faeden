@echo off
rem Doppelklick beendet Story World (Server auf Port 8765) und den mitgelieferten Libra-TTS-Server. Der MCP-Server fuer Claude bleibt unangetastet.
chcp 65001 >nul
set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8765 .*LISTENING"') do (
  set "FOUND=1"
  echo Beende Prozess %%p
  taskkill /PID %%p /F >nul 2>&1
)
if exist "%~dp0_update\libra.pid" (
  for /f "usebackq delims=" %%p in ("%~dp0_update\libra.pid") do (
    echo Beende Libra-TTS %%p
    taskkill /F /T /FI "PID eq %%p" /FI "IMAGENAME eq python.exe" >nul 2>&1
  )
  del "%~dp0_update\libra.pid" >nul 2>&1
)
if not defined FOUND echo Story World laeuft nicht.
timeout /t 2 >nul
