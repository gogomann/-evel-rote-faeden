"""Model folder: config.json, weights, tokenizer and front-end data, from a local path or the Hugging Face Hub."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass

DEFAULT_REPO = "Ekam/Libra-TTS"


def model_dir(path_or_repo: str | None = None, backend: str = "mlx") -> str:
    """A local folder holding config.json, or a Hub repo id to download (cached by huggingface_hub): the MLX weights
    or the ONNX graphs, whichever the backend reads."""
    p = path_or_repo or DEFAULT_REPO
    if os.path.isfile(os.path.join(p, "config.json")):
        return p
    from huggingface_hub import snapshot_download
    files = ["onnx/*"] if backend == "onnx" else ["model.safetensors", "codec.safetensors"]
    return snapshot_download(p, allow_patterns=["config.json", "tokenizer.json", "frontend/*"] + files)


@dataclass
class Sampling:
    temperature: float = 0.5  # first code of each frame
    top_k: int = 50
    repetition_penalty: float = 1.05
    min_new_frames: int = 2
    sub_temperature: float = 0.5  # the 15 residual codes
    sub_top_k: int = 50


class Config:
    def __init__(self, path: str):
        self.path = path
        with open(os.path.join(path, "config.json"), encoding="utf-8") as f:
            self.raw = c = json.load(f)
        self.talker, self.predictor, self.codec = c["talker"], c["predictor"], c["codec"]
        self.tokens, self.codec_ids = c["tokens"], c["codec_ids"]
        self.num_groups, self.codebook_size = c["num_code_groups"], c["codebook_size"]
        self.suppressed = tuple(c["suppressed_code0"])  # [lo, hi) of code0 ids never sampled (except EOS)
        self.sample_rate, self.frame_rate, self.max_frames = c["sample_rate"], c["frame_rate"], c["max_frames"]
        self.languages = c["languages"]  # ISO code -> {name, id, chars_per_second}
        self.voices = {v["name"]: v for v in c["voices"]}
        self.default_voice = c["default_voice"]
        self.styles = c.get("styles", {})  # name -> trained phrasings (a name invokes the first)
        self.paces = c.get("paces", {})  # slow / fast -> the word appended to the style
        self.tags = c.get("tags", [])  # inline events: <laugh>, <sigh>, <short pause>, ...
        self.sampling = Sampling(**c["sampling"])

    def file(self, *parts: str) -> str:
        return os.path.join(self.path, *parts)

    def language(self, lang: str) -> dict:
        if lang not in self.languages:
            raise ValueError(f"unknown language {lang!r}; one of {', '.join(sorted(self.languages))}")
        return self.languages[lang]

    def style_text(self, style: str | None, pace: str | None = None) -> str | None:
        """The instruction the model was trained on: a style name ("warm") or one of its phrasings ("soft and kind"),
        optionally with a pace ("slow" / "fast"): "warm and gentle, slowly"."""
        if style is None:
            if pace is not None:
                raise ValueError("pace needs a style, e.g. style='calm', pace='slow'")
            return None
        s = style.strip().lower()
        if s in self.styles:
            s = self.styles[s][0]
        elif not any(s in ph for ph in self.styles.values()):
            raise ValueError(f"unknown style {style!r}; one of {', '.join(self.styles)}")
        if pace is not None:
            if pace not in self.paces:
                raise ValueError(f"unknown pace {pace!r}; one of {', '.join(self.paces)}")
            s += ", " + self.paces[pace]
        return s

    def voice_id(self, voice: str) -> int:
        v = voice.lower()
        if v not in self.voices:
            raise ValueError(f"unknown voice {voice!r}; one of {', '.join(self.voices)}")
        return self.voices[v]["id"]
