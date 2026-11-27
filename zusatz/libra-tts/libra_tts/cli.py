"""libra-tts "Hello there." -o hello.wav [-v nina] [-l en] [-s warm] [--pace slow] [--seed 0] [--backend auto]"""
from __future__ import annotations

import argparse
import sys
import time


def main(argv=None):
    ap = argparse.ArgumentParser(prog="libra-tts", description="Libra TTS: multilingual text to speech")
    ap.add_argument("text", nargs="?", help="text to read (or --file, or stdin)")
    ap.add_argument("-f", "--file", help="read the text from this file")
    ap.add_argument("-o", "--out", default="libra.wav", help="output .wav (default libra.wav)")
    ap.add_argument("-v", "--voice", help="voice (default nina); --list shows all")
    ap.add_argument("-l", "--lang", default="auto", help="language code (en zh ja ko de fr es it pt ru ar hi pa bn ur "
                    "id) or auto (each sentence by its script; Latin script = English)")
    ap.add_argument("-s", "--style", help="speaking style (warm, cheerful, whispering, ...); --list shows all")
    ap.add_argument("--pace", choices=["slow", "fast"], help="with a style: slower or faster")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--temperature", type=float, help="sampling temperature (default 0.5)")
    ap.add_argument("--backend", default="auto", choices=["auto", "mlx", "cuda", "onnx"])
    ap.add_argument("--model", help="local model folder or Hugging Face repo id")
    ap.add_argument("--list", action="store_true", help="list voices, languages, styles and tags")
    a = ap.parse_args(argv)

    from .api import LibraTTS
    t0 = time.time()
    tts = LibraTTS(a.model, backend=a.backend, compile=False)  # one read: compiling would cost more than it saves
    if a.list:
        print("voices:", " ".join(tts.voices))
        print("languages:", " ".join(tts.languages))
        print("styles:", " ".join(tts.styles))
        print("tags:", " ".join(tts.tags))
        return
    text = a.text if a.text is not None else open(a.file, encoding="utf-8").read() if a.file else sys.stdin.read()
    sampling = None
    if a.temperature is not None:
        from dataclasses import replace
        sampling = replace(tts.cfg.sampling, temperature=a.temperature, sub_temperature=a.temperature)
    t1 = time.time()
    audio = tts.synthesize(text, voice=a.voice, lang=a.lang, style=a.style, pace=a.pace, seed=a.seed,
                           sampling=sampling)
    t2 = time.time()
    tts.save(a.out, audio)
    secs = len(audio) / tts.sample_rate
    print(f"{a.out}: {secs:.1f} s of audio in {t2 - t1:.1f} s ({tts.backend_name}, load {t1 - t0:.1f} s)")


if __name__ == "__main__":
    main()
