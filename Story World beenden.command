#!/bin/bash
# Doppelklick beendet Story World: Server auf Port 8765, alle "python -m story_world"-Prozesse und den
# mitgelieferten Libra-TTS-Server (zusatz/libra-tts/server.py).
# Der MCP-Server für Claude (story_world_mcp.py) bleibt bewusst unangetastet.
PORT=8765

pids=$( { lsof -ti tcp:$PORT 2>/dev/null; pgrep -f -- "-m story_world( |$)" 2>/dev/null;
          pgrep -f -- "libra-tts/server.py" 2>/dev/null; } | sort -u )

if [ -z "$pids" ]; then
  echo "Story World läuft nicht."
else
  echo "Beende: $pids"
  kill $pids 2>/dev/null
  for i in 1 2 3 4 5; do
    sleep 1
    alive=$(for p in $pids; do kill -0 "$p" 2>/dev/null && echo "$p"; done)
    [ -z "$alive" ] && break
  done
  if [ -n "$alive" ]; then
    echo "Erzwinge Beenden: $alive"
    kill -9 $alive 2>/dev/null
  fi
  echo "Story World beendet."
fi

sleep 2
osascript -e 'tell application "Terminal" to close (every window whose name contains "Story World")' >/dev/null 2>&1 &
exit 0
