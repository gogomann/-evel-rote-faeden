#!/usr/bin/env bash
# Start (macOS / Linux):  ./start.sh [PORT] [--lang de] [--voice nina] [--host 127.0.0.1] [--api-key KEY]
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Bitte zuerst ./install.sh ausführen."; exit 1
fi
exec .venv/bin/python server.py "$@"
