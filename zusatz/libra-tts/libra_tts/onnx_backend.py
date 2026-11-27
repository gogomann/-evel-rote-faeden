"""ONNX Runtime backend (CPU or any execution provider): three fp32 graphs in <model>/onnx/

  talker.onnx     prompt / frame embeddings + talker with an explicit KV cache -> last normed hidden, code0 logits
  predictor.onnx  one residual-predictor position (its input and head are picked by the cache length)
  decoder.onnx    codec decoder for one chunk of frames with explicit causal state -> 24 kHz waveform

The loop mirrors the MLX backend: same prompt, same seeded sampling (libra_tts.sampling), same streamed decoding.
"""
from __future__ import annotations

import numpy as np

from . import sampling as S
from .config import Config, Sampling
from .prompt import Prompt

CHUNK = 8  # decoder frames per call; the carried state makes any chunking equal to one pass


class OnnxBackend:
    def __init__(self, cfg: Config, threads: int | None = None, providers=None):
        import onnxruntime as ort
        so = ort.SessionOptions()
        if threads:
            so.intra_op_num_threads = threads
        # the sessions alternate every few milliseconds: spinning thread pools would fight over the cores (~1.5x slower)
        so.add_session_config_entry("session.intra_op.allow_spinning", "0")
        prov = providers or ["CPUExecutionProvider"]

        def load(name):
            return ort.InferenceSession(cfg.file("onnx", name), so, providers=prov)

        self.cfg = cfg
        self.talker, self.predictor, self.decoder = load("talker.onnx"), load("predictor.onnx"), load("decoder.onnx")
        t, p = cfg.talker, cfg.predictor
        self.kv_talker = (t["layers"], 1, t["kv_heads"], 0, t["head_dim"])
        self.kv_pred = (p["layers"], 1, p["kv_heads"], 0, p["head_dim"])
        self.eos = cfg.codec_ids["eos"]
        self.up = int(np.prod(cfg.codec["upsample_rates"]) * np.prod(cfg.codec["upsampling_ratios"]))
        self.dec_state = [(i.name, i.shape) for i in self.decoder.get_inputs() if i.name not in ("codes", "start")]

    def _talker(self, prompt: Prompt | None, codes: np.ndarray | None, k, v):
        n = len(prompt) if prompt is not None else 0
        feed = {
            "text_ids": (prompt.text_ids if n else np.zeros(0, np.int64)).astype(np.int64)[None],
            "text_mask": (prompt.text_mask if n else np.zeros(0)).astype(np.float32)[None],
            "codec_ids": (prompt.codec_ids if n else np.zeros(0, np.int64)).astype(np.int64)[None],
            "codec_mask": (prompt.codec_mask if n else np.zeros(0)).astype(np.float32)[None],
            "codes": (codes if codes is not None else np.zeros((0, self.cfg.num_groups))).astype(np.int64)[None],
            "past_k": k, "past_v": v,
        }
        return self.talker.run(None, feed)  # h [1, D], logits [1, V], present_k, present_v

    def _residuals(self, h: np.ndarray, c0: int, seed: int, frame: int, s: Sampling) -> list:
        """Codes 1..15 of a frame: positions 0 (talker hidden) and 1 (code0) give code 1; position g+1 gives g+1."""
        k = v = np.zeros(self.kv_pred, np.float32)
        _, k, v = self.predictor.run(None, {"h": h, "code": np.array([c0], np.int64), "past_k": k, "past_v": v})
        codes, code = [c0], c0
        for g in range(1, self.cfg.num_groups):
            lg, k, v = self.predictor.run(None, {"h": h, "code": np.array([code], np.int64), "past_k": k,
                                                 "past_v": v})
            code = S.sample(S.residual_code(lg[0], s), seed, frame, g)
            codes.append(code)
        return codes

    def generate(self, prompt: Prompt, seed: int, max_frames: int, sampling: Sampling) -> np.ndarray:
        """Codes int16 [T, 16] of one utterance (EOS excluded), stopping at EOS or ``max_frames``."""
        s = sampling
        z = np.zeros(self.kv_talker, np.float32)
        h, lg, k, v = self._talker(prompt, None, z, z)
        seen = np.zeros(lg.shape[-1], bool)
        frames = []
        for f in range(max_frames):
            c0 = S.sample(S.first_code(lg[0], seen, f, s, self.eos, self.cfg.suppressed), seed, f, 0)
            if c0 == self.eos:
                break
            seen[c0] = True
            codes = self._residuals(h, c0, seed, f, s)
            frames.append(codes)
            if f + 1 < max_frames:
                h, lg, k, v = self._talker(None, np.array([codes]), k, v)
        return np.array(frames, np.int16).reshape(-1, self.cfg.num_groups)

    def decode(self, codes) -> np.ndarray:
        """Codes [T, 16] -> float32 waveform [T * 1920] at 24 kHz, streamed CHUNK frames at a time."""
        c = np.clip(np.asarray(codes, np.int64), 0, None)
        state = {n: np.zeros(shape, np.float32) for n, shape in self.dec_state}
        names, out = ["wave"] + ["new_" + n for n, _ in self.dec_state], []
        for s in range(0, c.shape[0], CHUNK):
            r = self.decoder.run(names, {"codes": c[None, s:s + CHUNK], "start": np.array([s], np.int64), **state})
            out.append(r[0][0])
            state = dict(zip((n for n, _ in self.dec_state), r[1:]))
        return np.concatenate(out) if out else np.zeros(0, np.float32)
