"""Lädt die Libra-TTS-Modelldateien nach ./models/Libra-TTS (nur was das Backend braucht)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "models" / "Libra-TTS"
REPO = "Ekam/Libra-TTS"
COMMON = ["config.json", "tokenizer.json", "frontend/*", "LICENSE"]


def required_files(backend: str) -> list[str]:
    if backend == "onnx":
        return ["onnx/talker.onnx", "onnx/predictor.onnx", "onnx/decoder.onnx"]
    return ["model.safetensors", "codec.safetensors"]


def model_ready(backend: str) -> bool:
    files = ["config.json", "tokenizer.json"] + required_files(backend)
    return all((MODEL_DIR / f).is_file() for f in files)


def ensure_model(backend: str) -> Path:
    if model_ready(backend):
        return MODEL_DIR
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import snapshot_download

    patterns = COMMON + (["onnx/*"] if backend == "onnx" else required_files(backend))
    print(f"Lade Modell {REPO} ({backend}) nach {MODEL_DIR} ...", flush=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_download(REPO, local_dir=str(MODEL_DIR), allow_patterns=patterns)
    if not model_ready(backend):
        raise RuntimeError("Modelldownload unvollständig")
    return MODEL_DIR


if __name__ == "__main__":
    ensure_model(sys.argv[1] if len(sys.argv) > 1 else "onnx")
