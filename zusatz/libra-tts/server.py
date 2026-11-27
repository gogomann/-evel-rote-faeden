"""Libra-TTS als OpenAI-kompatibler Server (POST /v1/audio/speech).

Start:  python server.py [PORT] [--host H] [--backend B] [--lang de] [--voice nina] [--api-key KEY]
"""
from __future__ import annotations

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Union

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import Depends, FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402
from pydantic import BaseModel, ConfigDict  # noqa: E402

from download_model import MODEL_DIR, ensure_model  # noqa: E402

DEFAULTS = {"HOST": "0.0.0.0", "PORT": "8880", "BACKEND": "auto", "LANG": "auto", "VOICE": "nina",
            "FORMAT": "mp3", "API_KEY": "", "THREADS": ""}

# OpenAI-Stimmnamen -> Libra-Stimmen, damit Clients mit fester Stimmliste funktionieren
OPENAI_VOICES = {"alloy": "nina", "ash": "jon", "ballad": "sam", "coral": "sofia", "echo": "omar", "fable": "bob",
                 "nova": "maya", "onyx": "omar", "sage": "aliya", "shimmer": "sofia", "verse": "jon",
                 "marin": "maya", "cedar": "bob"}
MODEL_IDS = ["libra-tts", "tts-1", "tts-1-hd", "gpt-4o-mini-tts"]
MIME = {"mp3": "audio/mpeg", "wav": "audio/wav", "flac": "audio/flac", "opus": "audio/ogg", "aac": "audio/aac",
        "pcm": "audio/pcm"}
SF_FORMATS = {"wav": ("WAV", "PCM_16"), "flac": ("FLAC", "PCM_16"), "mp3": ("MP3", "MPEG_LAYER_III"),
              "opus": ("OGG", "OPUS")}
FFMPEG_ARGS = {"mp3": ["-f", "mp3", "-b:a", "128k"], "opus": ["-f", "ogg", "-c:a", "libopus"],
               "aac": ["-f", "adts", "-c:a", "aac"], "flac": ["-f", "flac"], "wav": ["-f", "wav"]}


def read_conf(path: Path) -> dict:
    conf = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                conf[k.strip().upper()] = v.strip()
    return conf


def parse_settings(argv=None) -> argparse.Namespace:
    conf = read_conf(ROOT / "server.conf")

    def d(key: str) -> str:
        return os.environ.get(f"LIBRA_{key}") or conf.get(key) or DEFAULTS[key]

    ap = argparse.ArgumentParser(description="Libra-TTS OpenAI-kompatibler Server")
    ap.add_argument("port_pos", nargs="?", type=int, metavar="PORT", help="Port (Kurzform für --port)")
    ap.add_argument("--port", type=int, default=int(d("PORT")))
    ap.add_argument("--host", default=d("HOST"))
    ap.add_argument("--backend", default=d("BACKEND"), choices=["auto", "mlx", "cuda", "onnx"])
    ap.add_argument("--lang", default=d("LANG"), help="Standardsprache (de, en, ... oder auto)")
    ap.add_argument("--voice", default=d("VOICE"), help="Standardstimme")
    ap.add_argument("--format", default=d("FORMAT"), choices=list(MIME), help="Standard-Ausgabeformat")
    ap.add_argument("--api-key", default=d("API_KEY"), help="optionaler Bearer-Token")
    ap.add_argument("--threads", type=int, default=int(d("THREADS")) if d("THREADS") else None)
    a = ap.parse_args(argv)
    if a.port_pos:
        a.port = a.port_pos
    return a


# ---------------------------------------------------------------- Audio-Kodierung

def encode_audio(audio: np.ndarray, sr: int, fmt: str) -> bytes:
    pcm16 = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    if fmt == "pcm":
        return pcm16.tobytes()
    if fmt in SF_FORMATS:
        try:
            buf = io.BytesIO()
            container, subtype = SF_FORMATS[fmt]
            sf.write(buf, audio, sr, format=container, subtype=subtype)
            return buf.getvalue()
        except Exception:
            pass  # libsndfile ohne dieses Format -> ffmpeg
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError(f"Format '{fmt}' braucht ffmpeg (nicht gefunden); wav, flac oder pcm gehen immer")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
           *FFMPEG_ARGS[fmt], "pipe:1"]
    return subprocess.run(cmd, input=pcm16.tobytes(), capture_output=True, check=True).stdout


# ---------------------------------------------------------------- Anfrage

class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str = "libra-tts"
    input: str
    voice: Optional[Union[str, dict]] = None
    response_format: Optional[str] = None
    speed: Optional[float] = None
    instructions: Optional[str] = None
    # Erweiterungen (nicht OpenAI)
    lang: Optional[str] = None
    language: Optional[str] = None
    style: Optional[str] = None
    pace: Optional[str] = None
    seed: Optional[int] = None
    temperature: Optional[float] = None
    gap: Optional[float] = None


class Engine:
    """Modell laden und jede Synthese im selben, einzigen Arbeitsthread (MLX bindet Streams an den Thread)."""

    def __init__(self, s: argparse.Namespace):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="libra")
        self.pool.submit(self._load, s).result()

    def run(self, fn, *args, **kwargs):
        return self.pool.submit(fn, *args, **kwargs).result()

    def _load(self, s: argparse.Namespace):
        from libra_tts import LibraTTS

        backend = s.backend
        if backend == "auto":
            from libra_tts.api import _default_backend
            backend = _default_backend()
        ensure_model(backend)
        t0 = time.time()
        self.tts = LibraTTS(str(MODEL_DIR), backend=backend, threads=s.threads)
        self.cfg = self.tts.cfg
        self.default_lang = self.lang(s.lang)
        self.default_voice = self.voice(s.voice)
        print(f"Modell geladen: {self.tts.backend_name} in {time.time() - t0:.1f} s", flush=True)
        self.tts.synthesize("Hallo.", voice=self.default_voice, lang="de")  # Aufwärmen

    def voice(self, v) -> str:
        if isinstance(v, dict):
            v = v.get("id") or v.get("name")
        if not v:
            return getattr(self, "default_voice", self.cfg.default_voice)
        v = str(v).strip().lower()
        v = OPENAI_VOICES.get(v, v)
        if v not in self.cfg.voices:
            raise ValueError(f"unbekannte Stimme '{v}'; verfügbar: {', '.join(self.cfg.voices)}")
        return v

    def lang(self, lg: Optional[str]) -> str:
        if not lg:
            return getattr(self, "default_lang", "auto")
        lg = lg.strip().lower()
        if lg == "auto" or lg in self.cfg.languages:
            return lg
        names = {v["name"].lower(): k for k, v in self.cfg.languages.items()}
        base = lg.split("-")[0].split("_")[0]
        if base in self.cfg.languages:
            return base
        if lg in names:
            return names[lg]
        raise ValueError(f"unbekannte Sprache '{lg}'; verfügbar: auto, {', '.join(sorted(self.cfg.languages))}")

    def style(self, style: Optional[str], instructions: Optional[str]) -> Optional[str]:
        styles = self.cfg.styles
        for cand in (style, instructions):
            if not cand:
                continue
            s = cand.strip().lower()
            if s in styles or any(s in ph for ph in styles.values()):
                return s
            for name in styles:
                if re.search(rf"\b{re.escape(name)}\b", s):
                    return name
        if style:
            raise ValueError(f"unbekannter Stil '{style}'; verfügbar: {', '.join(styles)}")
        return None

    @staticmethod
    def pace(pace: Optional[str], speed: Optional[float], instructions: Optional[str]) -> Optional[str]:
        if pace:
            p = pace.strip().lower()
            if p not in ("slow", "fast"):
                raise ValueError("pace muss 'slow' oder 'fast' sein")
            return p
        if speed is not None:
            if speed <= 0.85:
                return "slow"
            if speed >= 1.15:
                return "fast"
            return None
        if instructions:
            t = instructions.lower()
            if re.search(r"\b(slow|slowly|langsam)\b", t):
                return "slow"
            if re.search(r"\b(fast|quickly|schnell)\b", t):
                return "fast"
        return None

    def speak(self, r: SpeechRequest) -> np.ndarray:
        if not r.input or not r.input.strip():
            raise ValueError("'input' ist leer")
        voice = self.voice(r.voice)
        lang = self.lang(r.lang or r.language)
        style = self.style(r.style, r.instructions)
        pace = self.pace(r.pace, r.speed, r.instructions) if style else None
        sampling = None
        if r.temperature is not None:
            from dataclasses import replace
            sampling = replace(self.cfg.sampling, temperature=r.temperature, sub_temperature=r.temperature)
        return self.run(self.tts.synthesize, r.input, voice=voice, lang=lang, style=style, pace=pace,
                        seed=r.seed or 0, sampling=sampling, gap=0.3 if r.gap is None else r.gap)


# ---------------------------------------------------------------- App

def build_app(s: argparse.Namespace, engine: Engine) -> FastAPI:
    app = FastAPI(title="Libra-TTS Server", version="1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def auth(authorization: Optional[str] = Header(default=None)):
        if s.api_key and authorization != f"Bearer {s.api_key}":
            raise HTTPException(401, "ungültiger API-Schlüssel")

    @app.exception_handler(HTTPException)
    async def http_err(_: Request, e: HTTPException):
        return JSONResponse({"error": {"message": e.detail, "type": "invalid_request_error"}}, e.status_code)

    @app.get("/", include_in_schema=False)
    def web_ui():
        return FileResponse(ROOT / "web" / "index.html", media_type="text/html")

    @app.get("/health")
    def health():
        return {"status": "ok", "backend": engine.tts.backend_name, "sample_rate": engine.tts.sample_rate}

    @app.get("/v1/models", dependencies=[Depends(auth)])
    def models():
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "libra"} for m in MODEL_IDS]}

    @app.get("/ui/config", include_in_schema=False)
    def ui_config():
        return voices()

    @app.get("/v1/audio/voices", dependencies=[Depends(auth)])
    def voices():
        c = engine.cfg
        return {"voices": [{"id": n, "name": v["display"], "gender": v["gender"]} for n, v in c.voices.items()],
                "openai_aliases": OPENAI_VOICES, "default_voice": engine.default_voice,
                "languages": {k: v["name"] for k, v in c.languages.items()}, "default_lang": engine.default_lang,
                "styles": list(c.styles), "paces": list(c.paces), "tags": c.tags,
                "formats": list(MIME), "default_format": s.format, "auth": bool(s.api_key)}

    @app.post("/v1/audio/speech", dependencies=[Depends(auth)])
    def speech(r: SpeechRequest):
        fmt = (r.response_format or s.format).lower()
        if fmt not in MIME:
            raise HTTPException(400, f"response_format '{fmt}' nicht unterstützt; {', '.join(MIME)}")
        try:
            audio = engine.speak(r)
            data = encode_audio(audio, engine.tts.sample_rate, fmt)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except subprocess.CalledProcessError as e:
            raise HTTPException(500, f"ffmpeg-Fehler: {e.stderr.decode(errors='ignore')[:300]}")
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        return Response(data, media_type=MIME[fmt],
                        headers={"Content-Disposition": f'inline; filename="speech.{fmt}"',
                                 "X-Sample-Rate": str(engine.tts.sample_rate)})

    return app


def main():
    s = parse_settings()
    engine = Engine(s)
    app = build_app(s, engine)
    url = f"http://{'localhost' if s.host in ('0.0.0.0', '::') else s.host}:{s.port}"
    print(f"Libra-TTS läuft – Web-Oberfläche: {url}/  ·  API: {url}/v1 "
          f"(Backend {engine.tts.backend_name}, Sprache {engine.default_lang}, Stimme {engine.default_voice})",
          flush=True)
    uvicorn.run(app, host=s.host, port=s.port, log_level="info")


if __name__ == "__main__":
    main()
