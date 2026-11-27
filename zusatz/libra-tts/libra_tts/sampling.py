"""Seeded sampling shared by the backends: top-k + temperature with Gumbel noise from a counter-based hash of
(seed, frame, code group, token), so a seed gives the same speech on every backend and batch size."""
from __future__ import annotations

import numpy as np

K_SEED, K_STEP, K_GROUP, K_TOK = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F
M32 = 0xFFFFFFFF


def _fmix32(h: np.ndarray) -> np.ndarray:
    h = h ^ (h >> np.uint32(16))
    h = h * np.uint32(0x85EBCA6B)
    h = h ^ (h >> np.uint32(13))
    h = h * np.uint32(0xC2B2AE35)
    return h ^ (h >> np.uint32(16))


def hash_uniform(seed: int, frame: int, group: int, n_tok: int) -> np.ndarray:
    """Uniform (0, 1) float32 [n_tok]."""
    with np.errstate(over="ignore"):
        h = np.array([(seed * K_SEED + frame * K_STEP + group * K_GROUP) & M32], np.uint32)
        h = _fmix32(h)
        h = _fmix32(h ^ (np.arange(n_tok, dtype=np.uint32) * np.uint32(K_TOK)))
        h = _fmix32(h + np.uint32(0x6A09E667))
    return ((h >> np.uint32(8)).astype(np.float32) + 0.5) / float(1 << 24)


def top_k_mask(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 0 or k >= x.shape[-1]:
        return x
    kth = np.partition(x, -k)[-k]
    return np.where(x < kth, -np.inf, x)


def sample(x: np.ndarray, seed: int, frame: int, group: int) -> int:
    u = hash_uniform(seed, frame, group, x.shape[-1])
    with np.errstate(divide="ignore", invalid="ignore"):
        y = x - np.log(-np.log(u))
    return int(np.argmax(np.where(np.isnan(y), -np.inf, y)))  # a masked token drawn u == 1 gives NaN: never chosen


def first_code(logits: np.ndarray, seen: np.ndarray, frame: int, s, eos: int, suppressed) -> np.ndarray:
    """Processed code0 logits (float32 [V]): repetition penalty over codes already used, no EOS before
    ``min_new_frames``, control ids suppressed, temperature, top-k."""
    x = logits.astype(np.float32)
    if s.repetition_penalty != 1.0:
        x = np.where(seen, np.where(x < 0, x * s.repetition_penalty, x / s.repetition_penalty), x)
    keep = x[eos] if frame >= s.min_new_frames else -np.inf
    lo, hi = suppressed
    x[lo:hi] = -np.inf
    x[eos] = keep
    return top_k_mask(x / s.temperature, s.top_k)


def residual_code(logits: np.ndarray, s) -> np.ndarray:
    return top_k_mask(logits.astype(np.float32) / s.sub_temperature, s.sub_top_k)
