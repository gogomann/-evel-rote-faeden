"""Apple-silicon backend (MLX): talker + residual-code predictor in bfloat16, codec decoder with a float32 head and a
float16 body, the precision the benchmarks were measured with.

Several utterances decode together in one batch (one slot each, with its own positions and sampling state). The same
text, seed and batch give the same audio; one utterance per batch reproduces the reference engine's codes exactly.
"""
from __future__ import annotations

import os

os.environ.setdefault("MLX_ENABLE_TF32", "0")  # exact fp32 in the codec head; must precede MLX's first matmul

from typing import Dict, List, Sequence  # noqa: E402

import mlx.core as mx  # noqa: E402
import numpy as np  # noqa: E402

from .config import Config, Sampling  # noqa: E402
from .prompt import Prompt  # noqa: E402

PROJ = ("q", "k", "v", "o", "gate", "up", "down")
CACHE_LIMIT = 256 << 20  # MLX keeps freed buffers for reuse; uncapped, it held 5.6 GB after one 24 s read


# ------------------------------------------------------------------------------------------------ weights
class Op:
    """y = x W^T (+ b), W dense [out, in] or low-rank U [out, r] V [r, in]."""

    def __init__(self, w: Dict[str, mx.array], p: str):
        self.W, self.U, self.V, self.b = w.get(p + ".W"), w.get(p + ".U"), w.get(p + ".V"), w.get(p + ".b")

    def __call__(self, x):
        y = x @ self.W.T if self.W is not None else (x @ self.V.T) @ self.U.T
        return y + self.b if self.b is not None else y


class Emb:
    def __init__(self, w: Dict[str, mx.array], p: str):
        self.W, self.A, self.B = w.get(p + ".W"), w.get(p + ".A"), w.get(p + ".B")

    def __call__(self, ids):
        return self.W[ids] if self.W is not None else self.A[ids] @ self.B


class Stack:
    def __init__(self, w: Dict[str, mx.array], p: str, g: dict):
        self.n_heads, self.n_kv, self.hd, self.eps, self.theta = g["heads"], g["kv_heads"], g["head_dim"], g["eps"], \
            g["rope_theta"]
        self.scale = self.hd ** -0.5
        self.layers = [{"ln1": w[f"{p}.{k}.ln1"], "ln2": w[f"{p}.{k}.ln2"], "qn": w[f"{p}.{k}.qn"],
                        "kn": w[f"{p}.{k}.kn"], **{n: Op(w, f"{p}.{k}.{n}") for n in PROJ}} for k in range(g["layers"])]
        self.norm = w[p + ".norm"]

    def layer(self, k, x, offset, kv_write, mask):
        L = self.layers[k]
        B, T, _ = x.shape
        h = mx.fast.rms_norm(x, L["ln1"], self.eps)
        q = mx.fast.rms_norm(L["q"](h).reshape(B, T, self.n_heads, self.hd), L["qn"], self.eps).transpose(0, 2, 1, 3)
        kk = mx.fast.rms_norm(L["k"](h).reshape(B, T, self.n_kv, self.hd), L["kn"], self.eps).transpose(0, 2, 1, 3)
        v = L["v"](h).reshape(B, T, self.n_kv, self.hd).transpose(0, 2, 1, 3)
        q = mx.fast.rope(q, self.hd, traditional=False, base=self.theta, scale=1.0, offset=offset)
        kk = mx.fast.rope(kk, self.hd, traditional=False, base=self.theta, scale=1.0, offset=offset)
        K, V = kv_write(k, kk, v)
        a = mx.fast.scaled_dot_product_attention(q, K, V, scale=self.scale, mask=mask)
        x = x + L["o"](a.transpose(0, 2, 1, 3).reshape(B, T, self.n_heads * self.hd))
        h = mx.fast.rms_norm(x, L["ln2"], self.eps)
        g = L["gate"](h)
        return x + L["down"]((g * mx.sigmoid(g)) * L["up"](h))


# ------------------------------------------------------------------------------------------------ sampling
K_SEED, K_STEP, K_GROUP, K_TOK = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F


def _u32(x: int):
    return mx.array(x & 0xFFFFFFFF, dtype=mx.uint32)


def _fmix32(h):
    h = h ^ (h >> 16)
    h = h * _u32(0x85EBCA6B)
    h = h ^ (h >> 13)
    h = h * _u32(0xC2B2AE35)
    return h ^ (h >> 16)


def _gumbel_argmax(x, seed, frame, group: int):
    """argmax(x + Gumbel noise), the noise a hash of (seed, frame, group, token): libra_tts.sampling.hash_uniform."""
    tok = mx.arange(x.shape[-1], dtype=mx.uint32) * _u32(K_TOK)
    h = _fmix32(seed.astype(mx.uint32) * _u32(K_SEED) + frame.astype(mx.uint32) * _u32(K_STEP) + _u32(group * K_GROUP))
    h = _fmix32(_fmix32(h[:, None] ^ tok[None, :]) + _u32(0x6A09E667))
    u = ((h >> 8).astype(mx.float32) + 0.5) / float(1 << 24)
    return mx.argmax(x - mx.log(-mx.log(u)), axis=-1)


def _top_k(x, k: int):
    if k <= 0 or k >= x.shape[-1]:
        return x
    kth = mx.min(mx.topk(x, k, axis=-1), axis=-1, keepdims=True)
    return mx.where(x < kth, -mx.inf, x)


# ------------------------------------------------------------------------------------------------ backend
class MLXBackend:
    def __init__(self, cfg: Config, compile_predictor: bool = True):
        self.cfg = cfg
        prev = mx.set_cache_limit(CACHE_LIMIT)
        if prev < CACHE_LIMIT:  # never raise a lower limit the caller set
            mx.set_cache_limit(prev)
        w = mx.load(cfg.file("model.safetensors"))
        self.talker = Stack(w, "talker", cfg.talker)
        self.predictor = Stack(w, "predictor", cfg.predictor)
        self.text_emb, self.codec_emb = Emb(w, "text_emb"), Emb(w, "codec_emb")
        self.fc1, self.fc2, self.codec_head = Op(w, "fc1"), Op(w, "fc2"), Op(w, "codec_head")
        G = cfg.num_groups
        self.pred_emb = [Emb(w, f"pred_emb.{i}") for i in range(G - 1)]
        self.pred_head = [Op(w, f"pred_head.{i}") for i in range(G - 1)]
        self.pred_proj = Op(w, "pred_proj") if "pred_proj.W" in w or "pred_proj.U" in w else None
        V, lo, hi, self.eos = cfg.talker["vocab"], *cfg.suppressed, cfg.codec_ids["eos"]
        sup = np.zeros(V, bool)
        sup[lo:hi] = True
        sup[self.eos] = False
        self.suppress, self.eos_col = mx.array(sup), mx.array(np.arange(V) == self.eos)
        self.pad_embed = self.text_embed(mx.array([cfg.tokens["tts_pad"]]))[0]
        mx.eval(self.pad_embed)
        self.decoder = CodecDecoder(cfg)
        self.compile_predictor, self._predictors = compile_predictor, {}

    def text_embed(self, ids):
        h = self.fc1(self.text_emb(ids))
        return self.fc2(h * mx.sigmoid(h))

    def proj(self, x):
        return self.pred_proj(x) if self.pred_proj is not None else x

    def predictor_fn(self, temp: float, top_k: int):
        """(h_last, c0, seeds, frame) -> the frame's 16 codes, for one residual-code temperature and top-k."""
        key = (temp, top_k)
        if key not in self._predictors:
            f = lambda h, c0, sd, fr: self._predict(h, c0, sd, fr, temp, top_k)  # noqa: E731
            self._predictors[key] = mx.compile(f) if self.compile_predictor else f
        return self._predictors[key]

    def _predict(self, h_last, c0, seeds, frame, temp: float, top_k: int):
        """The 15 residual codes of a frame from the talker state and its first code."""
        P, G = self.predictor, self.cfg.num_groups
        x = self.proj(mx.stack([h_last, self.codec_emb(c0)], 1))
        Kc, Vc = [None] * len(P.layers), [None] * len(P.layers)

        def kvw(i, k, v):
            Kc[i], Vc[i] = (k, v) if Kc[i] is None else (mx.concatenate([Kc[i], k], 2), mx.concatenate([Vc[i], v], 2))
            return Kc[i], Vc[i]

        for i in range(len(P.layers)):
            x = P.layer(i, x, 0, kvw, "causal")
        h = mx.fast.rms_norm(x[:, -1], P.norm, P.eps)
        codes = [c0]
        for g in range(1, G):
            lg = self.pred_head[g - 1](h).astype(mx.float32)
            cg = _gumbel_argmax(_top_k(lg / temp, top_k), seeds, frame, g)
            codes.append(cg)
            if g == G - 1:
                break
            x = self.proj(self.pred_emb[g - 1](cg))[:, None]
            for i in range(len(P.layers)):
                x = P.layer(i, x, g + 1, kvw, None)
            h = mx.fast.rms_norm(x[:, -1], P.norm, P.eps)
        return mx.stack(codes, 1)

    def generate(self, prompts: Sequence[Prompt], seeds: Sequence[int], max_frames: Sequence[int],
                 s: Sampling) -> List[np.ndarray]:
        """Codes int16 [T_i, 16] of each prompt (EOS excluded), all decoded in one batch."""
        T, n = self.talker, len(prompts)
        P = np.array([len(p) for p in prompts])
        Pm = int(P.max())
        cap = np.minimum(np.array(max_frames), self.cfg.max_frames)
        S = int(((int((P + cap).max()) + 1 + 63) // 64) * 64)
        dt = mx.bfloat16
        Kc = [mx.zeros((n, T.n_kv, S, T.hd), dtype=dt) for _ in T.layers]
        Vc = [mx.zeros((n, T.n_kv, S, T.hd), dtype=dt) for _ in T.layers]
        # prefill, right-padded
        ti, ci = np.zeros((n, Pm), np.int32), np.zeros((n, Pm), np.int32)
        tm, cm, km = (np.zeros((n, Pm), bool) for _ in range(3))
        for i, p in enumerate(prompts):
            L = len(p)
            ti[i, :L], tm[i, :L], ci[i, :L], cm[i, :L], km[i, :L] = p.text_ids, p.text_mask, p.codec_ids, p.codec_mask, True
        x = self.text_embed(mx.array(ti)) * mx.array(tm)[..., None].astype(dt) + \
            self.codec_emb(mx.array(ci)) * mx.array(cm)[..., None].astype(dt)
        mask = mx.array((np.tril(np.ones((Pm, Pm), bool))[None, None] & km[:, None, None, :]) | np.eye(Pm, dtype=bool))
        ks, vs = [None] * len(T.layers), [None] * len(T.layers)

        def kv_pre(i, k, v):
            ks[i], vs[i] = k, v
            return k, v

        for i in range(len(T.layers)):
            x = T.layer(i, x, 0, kv_pre, mask)
        h_last = mx.fast.rms_norm(x, T.norm, T.eps)[mx.arange(n), mx.array(P - 1)]
        for i in range(len(T.layers)):
            Kc[i][:, :, :Pm, :] = ks[i]
            Vc[i][:, :, :Pm, :] = vs[i]
        seen = mx.zeros((n, self.cfg.talker["vocab"]), dtype=mx.bool_)
        lens, frame, active = P.astype(np.int32).copy(), np.zeros(n, np.int32), np.ones(n, bool)
        out: List[List[np.ndarray]] = [[] for _ in range(n)]
        seed_arr = mx.array(np.array([sd & 0xFFFFFFFF for sd in seeds], np.uint32))
        predict, rp = self.predictor_fn(s.sub_temperature, s.sub_top_k), s.repetition_penalty
        while active.any():
            fr = mx.array(frame)
            lg = self.codec_head(h_last).astype(mx.float32)
            if rp != 1.0:
                lg = mx.where(seen, mx.where(lg < 0, lg * rp, lg / rp), lg)
            lg = mx.where((fr < s.min_new_frames)[:, None] & self.eos_col[None, :], -mx.inf, lg)
            lg = _top_k(mx.where(self.suppress[None, :], -mx.inf, lg) / s.temperature, s.top_k)
            c0 = _gumbel_argmax(lg, seed_arr, fr, 0)
            is_eos = c0 == self.eos
            c0 = mx.where(is_eos, 0, c0)
            codes = predict(h_last, c0, seed_arr, fr)
            seen = mx.put_along_axis(seen, c0[:, None].astype(mx.int32), mx.array(True), axis=1)
            # talker step on the new frame (finished slots compute harmless garbage at position 0)
            wpos = np.where(active, lens, 0)
            pos = mx.array(wpos)
            e = self.codec_emb(codes[:, 0])
            for g in range(self.cfg.num_groups - 1):
                e = e + self.pred_emb[g](codes[:, g + 1])
            x = (e + self.pad_embed)[:, None]
            S_used = int(min(S, ((int(wpos.max()) + 1 + 63) // 64) * 64))
            mask = (mx.arange(S_used)[None, :] <= pos[:, None])[:, None, None, :]
            idx = mx.broadcast_to(pos[:, None, None, None], (n, T.n_kv, 1, T.hd))

            def kv_step(i, k, v):
                Kc[i] = mx.put_along_axis(Kc[i], idx, k, axis=2)
                Vc[i] = mx.put_along_axis(Vc[i], idx, v, axis=2)
                return Kc[i][:, :, :S_used], Vc[i][:, :, :S_used]

            for i in range(len(T.layers)):
                x = T.layer(i, x, pos, kv_step, mask)
            h_last = mx.fast.rms_norm(x[:, 0], T.norm, T.eps)
            mx.eval(codes, is_eos, h_last, seen, Kc, Vc)
            codes_np, eos_np = np.array(codes).astype(np.int16), np.array(is_eos)
            for i in np.nonzero(active)[0]:
                if eos_np[i]:
                    active[i] = False
                    continue
                out[i].append(codes_np[i])
                frame[i] += 1
                if frame[i] >= cap[i]:
                    active[i] = False
            lens[active] += 1
        G = self.cfg.num_groups
        return [np.stack(o) if o else np.zeros((0, G), np.int16) for o in out]

    def decode(self, codes: np.ndarray) -> np.ndarray:
        return self.decoder.decode(codes)


# ------------------------------------------------------------------------------------------------ codec decoder
def _unflatten(flat: Dict[str, mx.array]):
    root: dict = {}
    for k, v in flat.items():
        d, parts = root, k.split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = v

    def fix(d):
        if not isinstance(d, dict):
            return d
        if d and all(k.isdigit() for k in d):
            return [fix(d[k]) for k in sorted(d, key=int)]
        return {k: fix(v) for k, v in d.items()}
    return fix(root)


def _snake(x, p):
    xf = x.astype(mx.float32)  # SnakeBeta in fp32: x + 1/(exp(beta)+1e-9) * sin(x*exp(alpha))^2
    return (xf + p["ib"] * mx.square(mx.sin(xf * p["a"]))).astype(x.dtype)


def _causal_conv(x, c, hist, dilation: int = 1):
    """Causal conv of x given `hist`, the previous (k-1)*dilation inputs -> (y, the new history)."""
    w, b = c["w"], c["b"]
    T, span = x.shape[1], hist.shape[1]
    xp = mx.concatenate([hist, x], axis=1) if span else x
    if w.dtype == mx.float32:  # [O, K, I]
        y = mx.conv1d(xp, w, dilation=dilation) + b
    else:  # [K, I, O]: y = b + sum_j x[t-(k-1-j)d] @ W_j
        y = mx.addmm(b, xp[:, 0:T, :], w[0])
        for j in range(1, w.shape[0]):
            y = mx.addmm(y, xp[:, j * dilation: j * dilation + T, :], w[j])
    return y, xp[:, xp.shape[1] - span:]


def _conv_shape(c, dilation: int = 1):
    """(history length, input channels) of a causal conv."""
    w = c["w"]
    k, i = (w.shape[1], w.shape[2]) if w.dtype == mx.float32 else (w.shape[0], w.shape[1])
    return (k - 1) * dilation, i


def _rotate_half(x):
    h = x.shape[-1] // 2
    return mx.concatenate([-x[..., h:], x[..., :h]], axis=-1)


def _transformer(x, P, cos, sin, mask, K, V, cfg):
    """Sliding-window transformer over n new positions; K, V: each layer's previous window-1 keys/values."""
    N, L, _ = x.shape
    H, hd, eps, inter = cfg["num_attention_heads"], cfg["head_dim"], cfg["rms_norm_eps"], cfg["intermediate_size"]
    keep = cfg["sliding_window"] - 1
    dt = x.dtype
    K2, V2 = [], []
    x = mx.addmm(P["in_b"], x, P["in_w"])
    for lp, pk, pv in zip(P["layers"], K, V):
        h = mx.fast.rms_norm(x, lp["ln1"], eps)
        qkv = (h @ lp["wqkv"]).reshape(N, L, 3, H, hd).transpose(2, 0, 3, 1, 4)
        q, k, v = qkv[0].astype(mx.float32), qkv[1].astype(mx.float32), qkv[2]
        q = (q * cos + _rotate_half(q) * sin).astype(dt)
        k = mx.concatenate([pk, (k * cos + _rotate_half(k) * sin).astype(dt)], axis=2)
        v = mx.concatenate([pv, v], axis=2)
        K2.append(k[:, :, k.shape[2] - keep:])
        V2.append(v[:, :, v.shape[2] - keep:])
        a = mx.fast.scaled_dot_product_attention(q, k, v, scale=hd ** -0.5, mask=mask)
        x = x + lp["ls1"] * (a.transpose(0, 2, 1, 3).reshape(N, L, H * hd) @ lp["wo"])
        h = mx.fast.rms_norm(x, lp["ln2"], eps)
        gu = h @ lp["wgu"]
        gt, up = gu[..., :inter].astype(mx.float32), gu[..., inter:]
        x = x + lp["ls2"] * (((gt * mx.sigmoid(gt)).astype(dt) * up) @ lp["wd"])
    return mx.addmm(P["out_b"], mx.fast.rms_norm(x, P["norm"], eps), P["out_w"]), K2, V2


def _upsample(x, U, hist):
    N, T, C = x.shape
    x = mx.addmm(U["tb"], x, U["tw"]).reshape(N, 2 * T, C)  # ConvTranspose k=2 s=2
    T = 2 * T
    xp = mx.concatenate([hist, x], axis=1)  # depthwise causal conv k=7
    w = U["dw_w"]
    y = U["dw_b"] + xp[:, 0:T, :] * w[0]
    for j in range(1, 7):
        y = y + xp[:, j: j + T, :] * w[j]
    y = mx.fast.layer_norm(y, U["ln_w"], U["ln_b"], 1e-6)
    y = mx.addmm(U["b1"], y, U["w1"]).astype(mx.float32)
    y = (0.5 * y * (1.0 + mx.erf(y * (1.0 / np.sqrt(2.0))))).astype(x.dtype)
    return x + U["gamma"] * mx.addmm(U["b2"], y, U["w2"]), xp[:, xp.shape[1] - 6:]


def _block(x, Bp, rate: int, prev, res):
    N, T, _ = x.shape
    x = _snake(x, Bp["snake"])
    xs = mx.concatenate([prev, x], axis=1)[:, :T, :]
    y = mx.addmm(mx.addmm(Bp["tb"], x, Bp["tw_a"]), xs, Bp["tw_b"])  # causal ConvTranspose k=2r s=r
    x2 = y.reshape(N, T * rate, y.shape[-1] // rate)
    res2 = []
    for R, d, hist in zip(Bp["res"], (1, 3, 9), res):
        h, hist = _causal_conv(_snake(x2, R["s1"]), R["c1"], hist, d)
        x2 = mx.addmm(x2 + R["b2"], _snake(h, R["s2"]), R["w2"])
        res2.append(hist)
    return x2, x[:, T - 1:], res2


def _decode_step(P, S, codes, cos, sin, mask, cfg):
    """codes int32 [1, n, 16] and the stream state S -> (waveform float32 [1, n*1920] in [-1, 1], the new state)."""
    H, Bd = P["head"], P["body"]
    Q = codes.shape[-1]
    offs = mx.arange(Q - 1, dtype=mx.int32) * cfg["codebook_size"]
    h = H["cb_first"][codes[..., 0]] @ H["proj_first"] + H["cb_rest"][codes[..., 1:] + offs].sum(axis=2) @ H["proj_rest"]
    h, pre = _causal_conv(h, H["pre_conv"], S["pre"])
    h, K, V = _transformer(h, H["tr"], cos, sin, mask, S["K"], S["V"], cfg)
    up = []
    for U, hist in zip(H["up"], S["up"]):
        h, hist = _upsample(h, U, hist)
        up.append(hist)
    h, conv0 = _causal_conv(h, H["conv0"], S["conv0"])
    h = h.astype(Bd["blocks"][0]["tw_a"].dtype)
    prev, res = [], []
    for Bp, r, pb, rb in zip(Bd["blocks"], cfg["upsample_rates"], S["prev"], S["res"]):
        h, pb, rb = _block(h, Bp, r, pb, rb)
        prev.append(pb)
        res.append(rb)
    h = _snake(h, Bd["snake_out"])
    T = h.shape[1]
    z = mx.concatenate([S["out"], (h @ Bd["conv_out"]["w"]).astype(mx.float32)], axis=1)  # causal conv k=7, 96 -> 1
    y = z[:, 0:T, 0]
    for j in range(1, 7):
        y = y + z[:, j: j + T, j]
    state = {"pre": pre, "K": K, "V": V, "up": up, "conv0": conv0, "prev": prev, "res": res, "out": z[:, T:]}
    return mx.clip(y + Bd["conv_out"]["b"], -1.0, 1.0), state


class CodecDecoder:
    """Codes [T, 16] -> 24 kHz audio, streamed in chunks of CHUNK frames (port of the ODIN app's CodecStream).

    Every stage is causal: the convolutions read only past inputs, each decoder block's transposed convolution reads
    the current and the previous input, and the transformer attends to a sliding window of 72 positions. Carrying
    exactly that history (conv tails, the previous input, the last 71 keys and values) makes chunked decoding equal
    to one pass over the whole utterance, while memory stays that of one chunk."""
    CHUNK = 12  # frames (0.96 s): ~0.4 GB of working memory (one pass over 20 s: ~1.2 GB), ~1% slower end to end

    def __init__(self, cfg: Config):
        self.c = cfg.codec
        self.params = _unflatten(mx.load(cfg.file("codec.safetensors")))
        mx.eval(self.params)
        hd, th = self.c["head_dim"], float(self.c["rope_theta"])
        self.inv = np.float32(1.0) / (np.float32(th) ** (np.arange(0, hd, 2).astype(np.float32) / np.float32(hd)))
        self._step = mx.compile(lambda P, S, codes, cos, sin, mask: _decode_step(P, S, codes, cos, sin, mask, self.c))

    def initial_state(self):
        """Zeros (the one-pass zero padding); the key/value window starts fully masked."""
        H, Bd, c = self.params["head"], self.params["body"], self.c
        hdt, bdt = H["proj_first"].dtype, Bd["blocks"][0]["tw_a"].dtype
        z = lambda shape, dt: mx.zeros((1,) + shape, dtype=dt)  # noqa: E731
        kv = (c["num_attention_heads"], c["sliding_window"] - 1, c["head_dim"])
        n_tr = len(H["tr"]["layers"])
        return {"pre": z(_conv_shape(H["pre_conv"]), hdt), "K": [z(kv, hdt) for _ in range(n_tr)],
                "V": [z(kv, hdt) for _ in range(n_tr)], "up": [z((6, U["ln_w"].shape[0]), hdt) for U in H["up"]],
                "conv0": z(_conv_shape(H["conv0"]), hdt),
                "prev": [z((1, Bp["tw_a"].shape[0]), bdt) for Bp in Bd["blocks"]],
                "res": [[z(_conv_shape(R["c1"], d), bdt) for R, d in zip(Bp["res"], (1, 3, 9))] for Bp in Bd["blocks"]],
                "out": z((6, Bd["conv_out"]["w"].shape[1]), mx.float32)}

    def aux(self, start: int, n: int):
        """RoPE tables of positions [start, start + n) and the mask over the window-1 carried keys + n new ones."""
        win = self.c["sliding_window"]
        ang = np.arange(start, start + n, dtype=np.float32)[:, None] * self.inv[None, :]
        emb = np.concatenate([ang, ang], -1).astype(np.float64)
        q = start + np.arange(n)[:, None]
        k = start - (win - 1) + np.arange(win - 1 + n)[None, :]
        mask = (k >= 0) & (k <= q) & (k > q - win)
        return mx.array(np.cos(emb).astype(np.float32)), mx.array(np.sin(emb).astype(np.float32)), mx.array(mask)

    def decode(self, codes: np.ndarray) -> np.ndarray:
        c = np.clip(np.asarray(codes, np.int32), 0, None)
        S, out = self.initial_state(), []
        for s in range(0, c.shape[0], self.CHUNK):
            seg = c[s: s + self.CHUNK]
            y, S = self._step(self.params, S, mx.array(seg[None]), *self.aux(s, len(seg)))
            mx.eval(y, S)
            out.append(np.asarray(y[0]))
        return np.concatenate(out) if out else np.zeros(0, np.float32)
