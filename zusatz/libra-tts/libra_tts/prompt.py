"""Tokenizer and the two-channel prompt of one utterance.

Every prompt position carries a text-channel id (embedded by the text embedding + projection) and/or a codec-channel
id (codec embedding). Layout, P positions in all:

  [style]                           text = style ids                codec = -
  <|im_start|> assistant \\n        text = role ids                 codec = -
  6 control positions               text = pad pad pad pad pad bos   codec = think think_bos lang think_eos voice pad
  N text tokens + tts_eos           text = x_1 .. x_N eos            codec = pad * (N + 1)
  1 position                        text = pad                       codec = bos

Audio frames follow at positions P, P+1, ...: text = pad, codec = the frame's 16 code embeddings summed. The optional
style is ``<|im_start|>user\\n{instruction}<|im_end|>\\n`` (Config.style_text).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np

from .config import Config


class Tokenizer:
    def __init__(self, cfg: Config):
        from tokenizers import Tokenizer as HFTokenizer
        self.tok = HFTokenizer.from_file(cfg.file("tokenizer.json"))

    def encode(self, text: str) -> List[int]:
        """Ids of ``<|im_start|>assistant\\n{text}<|im_end|>\\n<|im_start|>assistant\\n``."""
        return self.tok.encode(f"<|im_start|>assistant\n{text}<|im_end|>\n<|im_start|>assistant\n",
                               add_special_tokens=False).ids

    def encode_style(self, instruction: str) -> List[int]:
        """Ids of ``<|im_start|>user\\n{instruction}<|im_end|>\\n``."""
        return self.tok.encode(f"<|im_start|>user\n{instruction}<|im_end|>\n", add_special_tokens=False).ids

    def token_text(self, t: int) -> str:
        return self.tok.decode([t])

    def piece_ids(self, s: str) -> List[int]:
        return self.tok.encode(s, add_special_tokens=False).ids


@dataclass
class Prompt:
    text_ids: np.ndarray  # int32 [P]
    text_mask: np.ndarray  # bool [P]
    codec_ids: np.ndarray  # int32 [P]
    codec_mask: np.ndarray  # bool [P]

    def __len__(self) -> int:
        return int(self.text_ids.shape[0])


def build_prompt(cfg: Config, ids: Sequence[int], voice: str, lang: str,
                 style_ids: Optional[Sequence[int]] = None) -> Prompt:
    """``ids``: Tokenizer.encode output (possibly with the Chinese split applied to the text part); ``style_ids``:
    Tokenizer.encode_style output."""
    T, C = cfg.tokens, cfg.codec_ids
    a = list(ids)
    assert a[0] == T["im_start"] and a[-5] == T["im_end"], "unexpected template"
    role, text = list(style_ids or []) + a[:3], a[3:-5]
    codec_ctrl = [C["think"], C["think_bos"], cfg.language(lang)["id"], C["think_eos"], cfg.voice_id(voice), C["pad"]]
    text_ctrl = [T["tts_pad"]] * (len(codec_ctrl) - 1) + [T["tts_bos"]]
    t_ids = role + text_ctrl + text + [T["tts_eos"], T["tts_pad"]]
    c_ids = [0] * len(role) + codec_ctrl + [C["pad"]] * (len(text) + 1) + [C["bos"]]
    c_mask = [False] * len(role) + [True] * (len(c_ids) - len(role))
    return Prompt(np.array(t_ids, np.int32), np.ones(len(t_ids), bool), np.array(c_ids, np.int32), np.array(c_mask))
