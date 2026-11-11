#!/bin/bash
# Doppelklick startet Story World und öffnet den Browser. Fenster offen lassen; Strg+C beendet.
cd "$(dirname "$0")"
if lsof -ti tcp:8765 >/dev/null 2>&1; then
  open "http://127.0.0.1:8765/"
else
  python3 -m story_world ui
fi
