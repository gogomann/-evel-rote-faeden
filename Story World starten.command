#!/bin/bash
# Doppelklick startet Story World und öffnet den Browser. Fenster offen lassen; Strg+C beendet.
# Beim ersten Start nach dem Entpacken (bzw. nach einem Update) prüft Story World die Zusatzprogramme
# (z. B. MP3-Encoder) und bietet an, Fehlendes zu installieren.
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if lsof -ti tcp:8765 >/dev/null 2>&1; then
  open "http://127.0.0.1:8765/"
  exit 0
fi
if ! python3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
  echo "Python 3.9 oder neuer wurde nicht gefunden."
  echo "Bitte von https://www.python.org/downloads/ installieren und Story World danach erneut starten."
  open "https://www.python.org/downloads/"
  read -r -p "Enter schließt dieses Fenster."
  exit 1
fi
python3 -m story_world ui
