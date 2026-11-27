"""Installiert Abhängigkeiten ins .venv, lädt das Modell und schreibt das Backend in server.conf.

Aufruf über install.sh / install.bat:  [--backend auto|mlx|cuda|onnx] [--ja]
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONF = ROOT / "server.conf"


def pip(*args: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *args])


def detect_backend() -> str:
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "mlx"
    if shutil.which("nvidia-smi"):
        return "cuda"
    return "onnx"


def set_conf(key: str, value: str) -> None:
    lines = CONF.read_text(encoding="utf-8").splitlines() if CONF.exists() else []
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    CONF.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cuda_works() -> bool:
    code = "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"
    return subprocess.call([sys.executable, "-c", code]) == 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="auto", choices=["auto", "mlx", "cuda", "onnx"])
    ap.add_argument("--ja", action="store_true", help="Japanisch-Unterstützung (pyopenjtalk) mitinstallieren")
    a = ap.parse_args()

    if sys.version_info < (3, 10):
        sys.exit(f"Python 3.10 oder neuer nötig (gefunden: {platform.python_version()})")

    backend = detect_backend() if a.backend == "auto" else a.backend
    print(f"== Backend: {backend}", flush=True)

    pip("-U", "pip")
    pip("-r", str(ROOT / "requirements.txt"))

    if backend == "mlx":
        pip("mlx>=0.29")
    elif backend == "cuda":
        if sys.platform == "win32":
            pip("torch>=2.5", "--index-url", "https://download.pytorch.org/whl/cu126")
        else:
            pip("torch>=2.5")
        pip("safetensors>=0.4")
        if not cuda_works():
            print("!! PyTorch findet keine NVIDIA-GPU – wechsle auf CPU (onnx).", flush=True)
            backend = "onnx"
    if backend == "onnx":
        pip("onnxruntime>=1.18")

    if a.ja:
        try:
            pip("pyopenjtalk-plus>=0.4.1" if sys.platform == "win32" else "pyopenjtalk>=0.4")
        except subprocess.CalledProcessError:
            print("!! pyopenjtalk ließ sich nicht installieren – Japanisch bleibt deaktiviert.", flush=True)

    sys.path.insert(0, str(ROOT))
    from download_model import ensure_model
    ensure_model(backend)

    if not CONF.exists():
        shutil.copy(ROOT / "server.conf.example", CONF)
    set_conf("BACKEND", backend)
    print(f"\n== Fertig. Backend {backend} in server.conf eingetragen.")
    print("   Starten:  ./start.sh [PORT]   bzw.   start.bat [PORT]")


if __name__ == "__main__":
    main()
