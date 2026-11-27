#!/usr/bin/env bash
# Installation (macOS / Linux):  ./install.sh [--backend auto|mlx|cuda|onnx] [--ja]
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
      PY="$c"; break
    fi
  done
fi
if [ -z "$PY" ]; then
  echo "Python 3.10 oder neuer nicht gefunden (https://www.python.org/downloads/)"; exit 1
fi

[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python installer.py "$@"
