"""NVIDIA GPU backend (PyTorch, CUDA): the MLX backend's model and loop in PyTorch. Talker and predictor run in
bfloat16 (float16 on GPUs without it), the codec decoder in float32 (head) and float16 (body), as on the Mac.

A frame (code0 sampling, the 15 residual codes, the talker step) is thousands of small kernels; on CUDA each frame
is captured once as a CUDA graph over fixed-size buffers and replayed, so it costs one launch. Where Triton is
available (Linux), torch.compile also fuses each layer's elementwise work (norms, rotary embedding, activations,
residuals) into a few kernels; the first run compiles them (about a minute, cached on disk). Several utterances
decode together in one batch, with the same seeded sampling as the other backends. Without CUDA (tests) the same
code runs eagerly.
"""
from __future__ import annotations

import os
import warnings
from collections import OrderedDict
from typing import Dict, List, Sequence

import numpy as np
import torch
import torch.nn.functional as F

from .config import Config, Sampling
from .prompt import Prompt

PROJ = ("q", "k", "v", "o", "gate", "up", "down")
K_SEED, K_STEP, K_GROUP, K_TOK = 0x9E3779B1, 0x85EBCA77, 0xC2B2AE3D, 0x27D4EB2F
M32 = 0xFFFFFFFF
GRAPHS = 2  # captured frame graphs kept (one per batch size / cache length / sampling settings)


def _has_triton() -> bool:
    try:
        from torch.utils._triton import has_triton
        return has_triton()
    except Exception:
        return False


def _load(path: str, device) -> Dict[str, torch.Tensor]:
    from safetensors.torch import load_file
    return load_file(path, device=str(device))


def _rms(x, w, eps):
    return F.rms_norm(x, (x.shape[-1],), w, eps)  # one fused kernel, computed in float32


def _rotate_half(x):  # codec transformer
    h = x.shape[-1] // 2
    return torch.cat([-x[..., h:], x[..., :h]], -1)


# ------------------------------------------------------------------------------------------------ weights
class Op:
    """y = x W^T (+ b), W dense [out, in] or low-rank U [out, r] V [r, in]."""

    def __init__(self, w: Dict[str, torch.Tensor], p: str, dt):
        g = lambda k: w[p + k].to(dt) if p + k in w else None  # noqa: E731
        self.W, self.U, self.V, self.b = g(".W"), g(".U"), g(".V"), g(".b")

    def __call__(self, x):
        if self.W is not None:
            return F.linear(x, self.W, self.b)
        return F.linear(F.linear(x, self.V), self.U, self.b)


class Emb:
    def __init__(self, w: Dict[str, torch.Tensor], p: str, dt):
        g = lambda k: w[p + k].to(dt) if p + k in w else None  # noqa: E731
        self.W, self.A, self.B = g(".W"), g(".A"), g(".B")

    def __call__(self, ids):
        return F.embedding(ids, self.W) if self.W is not None else F.embedding(ids, self.A) @ self.B


def _attn_in(x, ln1, qkv_V, Uq, Uk, Uv, qn, kn, cos, sin, rq: int, rk: int, H: int, KV: int, eps: float):
    """A low-rank layer's queries, keys, values: norm, one matmul through the stacked V factors, the three U
    factors, q/k norms and the rotary embedding of queries and keys together."""
    B, T, _ = x.shape
    hd = qn.shape[0]
    r = F.linear(_rms(x, ln1, eps), qkv_V)
    q, k, v = F.linear(r[..., :rq], Uq), F.linear(r[..., rq:rq + rk], Uk), F.linear(r[..., rq + rk:], Uv)
    qk = torch.cat([_rms(q.view(B, T, H, hd), qn, eps), _rms(k.view(B, T, KV, hd), kn, eps)], 2)
    qf = qk.float()
    qk = torch.addcmul(qf * cos, qf.roll(hd // 2, -1), sin).to(x.dtype).transpose(1, 2)
    return qk[:, :H], qk[:, H:], v.view(B, T, KV, hd).transpose(1, 2)


def _attn_out(x, a, oV, oU, ln2, gu_V, Ug, Uu, dV, dU, rg: int, eps: float):
    """The rest of a low-rank layer from the attention output a [B, H, T, hd]: output projection, residual, norm,
    gated MLP (gate and up through one stacked V matmul), residual."""
    B, T, _ = x.shape
    x = x + F.linear(F.linear(a.transpose(1, 2).reshape(B, T, -1), oV), oU)
    r = F.linear(_rms(x, ln2, eps), gu_V)
    return x + F.linear(F.linear(F.silu(F.linear(r[..., :rg], Ug)) * F.linear(r[..., rg:], Uu), dV), dU)


class Stack:
    """Transformer stack. The low-rank q/k/v (and gate/up) projections share one input matmul (their V factors
    stacked); norms are fused kernels and queries and keys are rotated together: a frame is mostly many tiny
    kernels, so their number sets the speed. f_in / f_out are _attn_in / _attn_out, or their compiled versions."""

    def __init__(self, w: Dict[str, torch.Tensor], p: str, g: dict, dt):
        self.n_heads, self.n_kv, self.hd, self.eps = g["heads"], g["kv_heads"], g["head_dim"], g["eps"]
        self.scale = self.hd ** -0.5
        self.layers = []
        for k in range(g["layers"]):
            L = {n: w[f"{p}.{k}.{n}"].to(dt) for n in ("ln1", "ln2", "qn", "kn")}
            L.update({n: Op(w, f"{p}.{k}.{n}", dt) for n in PROJ})
            if all(L[n].W is None and L[n].b is None for n in PROJ):  # low-rank: stack the V factors
                L["qkv_V"] = torch.cat([L[n].V for n in ("q", "k", "v")])
                L["qkv_r"] = [L[n].V.shape[0] for n in ("q", "k", "v")]
                L["gu_V"] = torch.cat([L[n].V for n in ("gate", "up")])
                L["gu_r"] = [L[n].V.shape[0] for n in ("gate", "up")]
            self.layers.append(L)
        self.norm = w[p + ".norm"].to(dt)
        self.f_in, self.f_out = _attn_in, _attn_out
        dev = self.norm.device
        self.inv = 1.0 / (g["rope_theta"] ** (torch.arange(0, self.hd, 2, device=dev, dtype=torch.float32) / self.hd))

    def rope(self, pos):
        """cos, signed sin [B, T, 1, hd] for integer positions pos [B, T]: x*cos + rotate_half(x)*sin is
        x*cos + roll(x)*signed_sin."""
        ang = pos.float()[..., None, None] * self.inv
        return torch.cat([ang, ang], -1).cos(), torch.cat([-ang.sin(), ang.sin()], -1)

    def _proj(self, L, h, names):
        """The listed projections of h, through one stacked V matmul when the layer is low-rank."""
        key = "qkv" if len(names) == 3 else "gu"
        if key + "_V" not in L:
            return [L[n](h) for n in names]
        r = F.linear(h, L[key + "_V"])
        out, lo = [], 0
        for n, rk in zip(names, L[key + "_r"]):
            out.append(F.linear(r[..., lo:lo + rk], L[n].U, L[n].b))
            lo += rk
        return out

    def layer(self, k, x, cs, kv_write, mask=None, causal=False):
        L = self.layers[k]
        if "qkv_V" in L:
            # compiled only for single-utterance frame steps (fixed shapes, compiled once each); batches and
            # prefills would recompile for every size and ran slower compiled
            f_in, f_out = (self.f_in, self.f_out) if x.shape[0] == 1 and x.shape[1] <= 2 else (_attn_in, _attn_out)
            q, kk, v = f_in(x, L["ln1"], L["qkv_V"], L["q"].U, L["k"].U, L["v"].U, L["qn"], L["kn"], *cs,
                                 L["qkv_r"][0], L["qkv_r"][1], self.n_heads, self.n_kv, self.eps)
            K, V = kv_write(k, kk, v)
            a = F.scaled_dot_product_attention(q, K, V, attn_mask=mask, is_causal=causal, scale=self.scale,
                                               enable_gqa=True)
            return f_out(x, a, L["o"].V, L["o"].U, L["ln2"], L["gu_V"], L["gate"].U, L["up"].U, L["down"].V,
                              L["down"].U, L["gu_r"][0], self.eps)
        B, T, _ = x.shape
        H, KV, hd = self.n_heads, self.n_kv, self.hd
        cos, sin = cs
        h = _rms(x, L["ln1"], self.eps)
        q, kk, v = self._proj(L, h, ("q", "k", "v"))
        qk = torch.cat([_rms(q.view(B, T, H, hd), L["qn"], self.eps), _rms(kk.view(B, T, KV, hd), L["kn"], self.eps)], 2)
        qf = qk.float()
        qk = torch.addcmul(qf * cos, qf.roll(hd // 2, -1), sin).to(x.dtype).transpose(1, 2)
        K, V = kv_write(k, qk[:, H:], v.view(B, T, KV, hd).transpose(1, 2))
        a = F.scaled_dot_product_attention(qk[:, :H], K, V, attn_mask=mask, is_causal=causal, scale=self.scale,
                                           enable_gqa=True)
        x = x + L["o"](a.transpose(1, 2).reshape(B, T, H * hd))
        h = _rms(x, L["ln2"], self.eps)
        g, u = self._proj(L, h, ("gate", "up"))
        return x + L["down"](F.silu(g) * u)


# ------------------------------------------------------------------------------------------------ sampling
def _fmix32(h):
    """murmur3 finalizer on uint32 values held in int64 (products wrap; the low 32 bits stay exact)."""
    h = h ^ (h >> 16)
    h = (h * 0x85EBCA6B) & M32
    h = h ^ (h >> 13)
    h = (h * 0xC2B2AE35) & M32
    return h ^ (h >> 16)


def _gumbel(seed, frame, groups, tok):
    """Gumbel noise [n, len(groups), V] of a frame, a hash of (seed, frame, group, token):
    libra_tts.sampling.hash_uniform. Sampling a group is argmax(logits + its noise)."""
    h = _fmix32((seed[:, None] * K_SEED + frame[:, None] * K_STEP + groups[None, :] * K_GROUP) & M32)
    h = _fmix32((_fmix32(h[..., None] ^ tok) + 0x6A09E667) & M32)
    u = ((h >> 8).float() + 0.5) / float(1 << 24)
    # u rounds to 1 once in 2^24 draws: infinite noise, NaN on a masked (-inf) logit, which torch.argmax would pick.
    # Capped, a masked token stays -inf and a kept one still wins, as in libra_tts.sampling.sample.
    return (-torch.log(-torch.log(u))).clamp(max=1e30)


def _top_k(x, k: int):
    if k <= 0 or k >= x.shape[-1]:
        return x
    kth = torch.topk(x, k, -1).values[..., -1:]
    return x.masked_fill(x < kth, float("-inf"))


# ------------------------------------------------------------------------------------------------ backend
class _Frame:
    """Fixed-size state of one batch: talker KV cache, last hidden state, sampling state, the frame's outputs."""

    def __init__(self, be: "TorchBackend", n: int, S: int):
        T, P, dev, dt = be.talker, be.predictor, be.device, be.dtype
        self.K = [torch.zeros(n, T.n_kv, S, T.hd, device=dev, dtype=dt) for _ in T.layers]
        self.V = [torch.zeros(n, T.n_kv, S, T.hd, device=dev, dtype=dt) for _ in T.layers]
        G = be.cfg.num_groups
        self.pK = [torch.zeros(n, P.n_kv, G, P.hd, device=dev, dtype=dt) for _ in P.layers]
        self.pV = [torch.zeros(n, P.n_kv, G, P.hd, device=dev, dtype=dt) for _ in P.layers]
        self.h = torch.zeros(n, be.cfg.talker["hidden"], device=dev, dtype=dt)
        self.seen = torch.zeros(n, be.cfg.talker["vocab"], device=dev, dtype=torch.bool)
        self.seed, self.frame, self.pos = (torch.zeros(n, device=dev, dtype=torch.long) for _ in range(3))
        self.codes = torch.zeros(n, G, device=dev, dtype=torch.long)
        self.eos = torch.zeros(n, device=dev, dtype=torch.bool)
        self.keys = torch.arange(S, device=dev)
        self.graph = None


class TorchBackend:
    def __init__(self, cfg: Config, device: str | None = None, dtype=None, compile: bool | None = None):
        """dtype: of talker and predictor (default bfloat16, float16 on GPUs without it; float32 for tests).
        compile: fuse each layer's single-utterance frame step with torch.compile (default: on CUDA with Triton,
        unless LIBRA_COMPILE=0)."""
        self.cfg = cfg
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        cuda = self.device.type == "cuda"
        self.dtype = dtype or (torch.bfloat16 if not cuda or torch.cuda.is_bf16_supported() else torch.float16)
        dt = self.dtype
        w = _load(cfg.file("model.safetensors"), self.device)
        self.talker = Stack(w, "talker", cfg.talker, dt)
        self.predictor = Stack(w, "predictor", cfg.predictor, dt)
        self.text_emb, self.codec_emb = Emb(w, "text_emb", dt), Emb(w, "codec_emb", dt)
        self.fc1, self.fc2, self.codec_head = Op(w, "fc1", dt), Op(w, "fc2", dt), Op(w, "codec_head", dt)
        G = cfg.num_groups
        self.pred_emb = [Emb(w, f"pred_emb.{i}", dt) for i in range(G - 1)]
        self.pred_head = [Op(w, f"pred_head.{i}", dt) for i in range(G - 1)]
        self.pred_proj = Op(w, "pred_proj", dt) if "pred_proj.W" in w or "pred_proj.U" in w else None
        V, lo, hi, self.eos = cfg.talker["vocab"], *cfg.suppressed, cfg.codec_ids["eos"]
        sup = torch.zeros(V, dtype=torch.bool)
        sup[lo:hi] = True
        sup[self.eos] = False
        self.suppress = sup.to(self.device)
        self.eos_col = (torch.arange(V) == self.eos).to(self.device)
        self.tok = {v: (torch.arange(v, device=self.device) * K_TOK) & M32 for v in (V, cfg.predictor["vocab"])}
        self.groups = torch.arange(G, device=self.device)
        with torch.inference_mode():
            self.pad_embed = self.text_embed(torch.tensor([cfg.tokens["tts_pad"]], device=self.device))[0]
        self.use_graphs = cuda
        if compile is None:
            compile = cuda and os.environ.get("LIBRA_COMPILE", "1") != "0" and _has_triton()
        if compile:
            self._compile()
        self._frames: "OrderedDict[tuple, _Frame]" = OrderedDict()
        self.decoder = CodecDecoder(cfg, self.device)

    def _compile(self):
        """Compiled layer halves for both stacks, tried once on the talker's frame-step shapes; any failure (no C
        compiler for Triton, an unsupported GPU) leaves the uncompiled ones in place."""
        os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR", os.path.join(os.path.expanduser("~"), ".cache", "libra-tts",
                                                                     "inductor"))
        import torch._dynamo
        torch._dynamo.config.cache_size_limit = max(torch._dynamo.config.cache_size_limit, 64)
        mode = os.environ.get("LIBRA_COMPILE_MODE") or None  # e.g. max-autotune-no-cudagraphs (slower first compile)
        f_in, f_out = (torch.compile(f, fullgraph=True, dynamic=False, mode=mode) for f in (_attn_in, _attn_out))
        T, L = self.talker, self.talker.layers[0]
        if "qkv_V" not in L:
            return
        try:
            with torch.inference_mode():
                x = torch.zeros(1, 1, self.cfg.talker["hidden"], device=self.device, dtype=self.dtype)
                q, k, v = f_in(x, L["ln1"], L["qkv_V"], L["q"].U, L["k"].U, L["v"].U, L["qn"], L["kn"],
                               *T.rope(torch.zeros(1, 1, dtype=torch.long, device=self.device)), L["qkv_r"][0],
                               L["qkv_r"][1], T.n_heads, T.n_kv, T.eps)
                f_out(x, q, L["o"].V, L["o"].U, L["ln2"], L["gu_V"], L["gate"].U, L["up"].U, L["down"].V, L["down"].U,
                      L["gu_r"][0], T.eps)
        except Exception as e:  # pragma: no cover - depends on the machine
            warnings.warn(f"torch.compile unavailable ({type(e).__name__}: {e}); running uncompiled", stacklevel=3)
            return
        for st in (self.talker, self.predictor):
            st.f_in, st.f_out = f_in, f_out

    def text_embed(self, ids):
        return self.fc2(F.silu(self.fc1(self.text_emb(ids))))

    def proj(self, x):
        return self.pred_proj(x) if self.pred_proj is not None else x

    # one frame, on the fixed-size state st: everything a CUDA graph replays
    def _step(self, st: _Frame, s: Sampling):
        T, P, G = self.talker, self.predictor, self.cfg.num_groups
        n = st.h.shape[0]
        lg = self.codec_head(st.h).float()
        rp = s.repetition_penalty
        if rp != 1.0:
            lg = torch.where(st.seen, torch.where(lg < 0, lg * rp, lg / rp), lg)
        lg = lg.masked_fill((st.frame < s.min_new_frames)[:, None] & self.eos_col[None, :], float("-inf"))
        lg = _top_k(lg.masked_fill(self.suppress[None, :], float("-inf")) / s.temperature, s.top_k)
        c0 = torch.argmax(lg + _gumbel(st.seed, st.frame, self.groups[:1], self.tok[lg.shape[-1]])[:, 0], -1)
        noise = _gumbel(st.seed, st.frame, self.groups[1:], self.tok[self.cfg.predictor["vocab"]])
        is_eos = c0 == self.eos
        c0 = torch.where(is_eos, torch.zeros_like(c0), c0)
        # the 15 residual codes; predictor positions are the same for every slot
        x = self.proj(torch.stack([st.h, self.codec_emb(c0)], 1))
        ar = torch.arange(G, device=st.h.device)

        def kvw(lo, hi):
            def w(i, k, v):
                st.pK[i][:, :, lo:hi] = k
                st.pV[i][:, :, lo:hi] = v
                return st.pK[i][:, :, :hi], st.pV[i][:, :, :hi]
            return w

        cs = P.rope(ar[None, :2].expand(n, 2))
        for i in range(len(P.layers)):
            x = P.layer(i, x, cs, kvw(0, 2), causal=True)
        h = _rms(x[:, -1], P.norm, P.eps)
        codes = [c0]
        for g in range(1, G):
            lgp = self.pred_head[g - 1](h).float()
            cg = torch.argmax(_top_k(lgp / s.sub_temperature, s.sub_top_k) + noise[:, g - 1], -1)
            codes.append(cg)
            if g == G - 1:
                break
            x = self.proj(self.pred_emb[g - 1](cg))[:, None]
            cs = P.rope(ar[None, g + 1:g + 2].expand(n, 1))
            for i in range(len(P.layers)):
                x = P.layer(i, x, cs, kvw(g + 1, g + 2))
            h = _rms(x[:, -1], P.norm, P.eps)
        codes = torch.stack(codes, 1)
        st.seen.scatter_(1, c0[:, None], True)
        # talker step on the new frame at each slot's position (finished slots write harmless garbage at 0)
        e = self.codec_emb(codes[:, 0])
        for g in range(G - 1):
            e = e + self.pred_emb[g](codes[:, g + 1])
        x = (e + self.pad_embed)[:, None]
        idx = st.pos[:, None, None, None].expand(n, T.n_kv, 1, T.hd)
        mask = (st.keys[None, :] <= st.pos[:, None])[:, None, None, :]

        def kv_step(i, k, v):
            st.K[i].scatter_(2, idx, k)
            st.V[i].scatter_(2, idx, v)
            return st.K[i], st.V[i]

        cs = T.rope(st.pos[:, None])
        for i in range(len(T.layers)):
            x = T.layer(i, x, cs, kv_step, mask)
        st.h.copy_(_rms(x[:, 0], T.norm, T.eps))
        st.codes.copy_(codes)
        st.eos.copy_(is_eos)

    def _frame_state(self, n: int, S: int, s: Sampling) -> _Frame:
        key = (n, S, s.temperature, s.top_k, s.repetition_penalty, s.min_new_frames, s.sub_temperature,
               s.sub_top_k)
        if key in self._frames:
            self._frames.move_to_end(key)
            return self._frames[key]
        while len(self._frames) >= GRAPHS:
            self._frames.popitem(last=False)
        st = _Frame(self, n, S)
        if self.use_graphs:
            side = torch.cuda.Stream()
            side.wait_stream(torch.cuda.current_stream())
            with torch.cuda.stream(side):
                for _ in range(2):  # warm-up (cuBLAS workspaces, kernel selection) before capture
                    self._step(st, s)
            torch.cuda.current_stream().wait_stream(side)
            st.graph = torch.cuda.CUDAGraph()
            with torch.cuda.graph(st.graph):
                self._step(st, s)
        self._frames[key] = st
        return st

    @torch.inference_mode()
    def generate(self, prompts: Sequence[Prompt], seeds: Sequence[int], max_frames: Sequence[int],
                 s: Sampling) -> List[np.ndarray]:
        """Codes int16 [T_i, 16] of each prompt (EOS excluded), all decoded in one batch."""
        T, n, dev, dt = self.talker, len(prompts), self.device, self.dtype
        P = np.array([len(p) for p in prompts])
        Pm = int(P.max())
        cap = np.minimum(np.array(max_frames), self.cfg.max_frames)
        S = int(((int((P + cap).max()) + 1 + 255) // 256) * 256)  # coarse sizes: fewer graphs to capture
        st = self._frame_state(n, S, s)
        # prefill, right-padded, into the frame state's cache
        ti, ci = np.zeros((n, Pm), np.int64), np.zeros((n, Pm), np.int64)
        tm, cm, km = (np.zeros((n, Pm), bool) for _ in range(3))
        for i, p in enumerate(prompts):
            L = len(p)
            ti[i, :L], tm[i, :L], ci[i, :L], cm[i, :L], km[i, :L] = p.text_ids, p.text_mask, p.codec_ids, p.codec_mask, True
        t = lambda a: torch.from_numpy(a).to(dev)  # noqa: E731
        x = self.text_embed(t(ti)) * t(tm)[..., None].to(dt) + self.codec_emb(t(ci)) * t(cm)[..., None].to(dt)
        mask = (torch.tril(torch.ones(Pm, Pm, dtype=torch.bool, device=dev))[None, None] & t(km)[:, None, None, :]) | \
            torch.eye(Pm, dtype=torch.bool, device=dev)

        def kv_pre(i, k, v):
            st.K[i][:, :, :Pm] = k
            st.V[i][:, :, :Pm] = v
            return k, v

        cs = T.rope(torch.arange(Pm, device=dev)[None].expand(n, Pm))
        for i in range(len(T.layers)):
            x = T.layer(i, x, cs, kv_pre, mask)
        st.h.copy_(_rms(x, T.norm, T.eps)[torch.arange(n, device=dev), t(P - 1)])
        st.seen.zero_()
        st.seed.copy_(t(np.array([sd & 0xFFFFFFFF for sd in seeds], np.int64)))
        lens, frame, active = P.astype(np.int64).copy(), np.zeros(n, np.int64), np.ones(n, bool)
        out: List[List[np.ndarray]] = [[] for _ in range(n)]
        while active.any():
            st.frame.copy_(t(frame))
            st.pos.copy_(t(np.where(active, lens, 0)))
            if st.graph is not None:
                st.graph.replay()
            else:
                self._step(st, s)
            codes_np, eos_np = st.codes.cpu().numpy().astype(np.int16), st.eos.cpu().numpy()
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
def _unflatten(flat: Dict[str, torch.Tensor]):
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
    xf = x.float()  # SnakeBeta in fp32: x + 1/(exp(beta)+1e-9) * sin(x*exp(alpha))^2
    return (xf + p["ib"] * torch.sin(xf * p["a"]).square()).to(x.dtype)


def _causal_conv(x, c, hist, dilation: int = 1):
    """Causal conv of x [N, T, C] given `hist`, the previous (k-1)*dilation inputs -> (y, the new history)."""
    w, b = c["w"], c["b"]
    T, span = x.shape[1], hist.shape[1]
    xp = torch.cat([hist, x], 1) if span else x
    if w.dtype == torch.float32:  # [O, K, I]
        y = F.conv1d(xp.transpose(1, 2), w.permute(0, 2, 1), dilation=dilation).transpose(1, 2) + b
    else:  # [K, I, O]: y = b + sum_j x[t-(k-1-j)d] @ W_j
        y = torch.addmm(b, xp[0, 0:T], w[0])
        for j in range(1, w.shape[0]):
            y = torch.addmm(y, xp[0, j * dilation: j * dilation + T], w[j])
        y = y[None]
    return y, xp[:, xp.shape[1] - span:]


def _conv_shape(c, dilation: int = 1):
    w = c["w"]
    k, i = (w.shape[1], w.shape[2]) if w.dtype == torch.float32 else (w.shape[0], w.shape[1])
    return (k - 1) * dilation, i


def _transformer(x, P, cos, sin, mask, K, V, cfg):
    """Sliding-window transformer over n new positions; K, V: each layer's previous window-1 keys/values."""
    N, L, _ = x.shape
    H, hd, eps, inter = cfg["num_attention_heads"], cfg["head_dim"], cfg["rms_norm_eps"], cfg["intermediate_size"]
    keep = cfg["sliding_window"] - 1
    dt = x.dtype
    K2, V2 = [], []
    x = P["in_b"] + x @ P["in_w"]
    for lp, pk, pv in zip(P["layers"], K, V):
        h = _rms(x, lp["ln1"], eps)
        qkv = (h @ lp["wqkv"]).reshape(N, L, 3, H, hd).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0].float(), qkv[1].float(), qkv[2]
        q = (q * cos + _rotate_half(q) * sin).to(dt)
        k = torch.cat([pk, (k * cos + _rotate_half(k) * sin).to(dt)], 2)
        v = torch.cat([pv, v], 2)
        K2.append(k[:, :, k.shape[2] - keep:])
        V2.append(v[:, :, v.shape[2] - keep:])
        a = F.scaled_dot_product_attention(q, k, v, attn_mask=mask, scale=hd ** -0.5)
        x = x + lp["ls1"] * (a.transpose(1, 2).reshape(N, L, H * hd) @ lp["wo"])
        h = _rms(x, lp["ln2"], eps)
        gu = h @ lp["wgu"]
        gt, up = gu[..., :inter].float(), gu[..., inter:]
        x = x + lp["ls2"] * ((F.silu(gt).to(dt) * up) @ lp["wd"])
    return P["out_b"] + _rms(x, P["norm"], eps) @ P["out_w"], K2, V2


def _upsample(x, U, hist):
    N, T, C = x.shape
    x = (U["tb"] + x @ U["tw"]).reshape(N, 2 * T, C)  # ConvTranspose k=2 s=2
    T = 2 * T
    xp = torch.cat([hist, x], 1)  # depthwise causal conv k=7
    w = U["dw_w"]
    y = U["dw_b"] + xp[:, 0:T] * w[0]
    for j in range(1, 7):
        y = y + xp[:, j: j + T] * w[j]
    y = F.layer_norm(y, (C,), U["ln_w"], U["ln_b"], 1e-6)
    y = (U["b1"] + y @ U["w1"]).float()
    y = (0.5 * y * (1.0 + torch.erf(y * (1.0 / np.sqrt(2.0))))).to(x.dtype)
    return x + U["gamma"] * (U["b2"] + y @ U["w2"]), xp[:, xp.shape[1] - 6:]


def _block(x, Bp, rate: int, prev, res):
    N, T, _ = x.shape
    x = _snake(x, Bp["snake"])
    xs = torch.cat([prev, x], 1)[:, :T]
    y = Bp["tb"] + x @ Bp["tw_a"] + xs @ Bp["tw_b"]  # causal ConvTranspose k=2r s=r
    x2 = y.reshape(N, T * rate, y.shape[-1] // rate)
    res2 = []
    for R, d, hist in zip(Bp["res"], (1, 3, 9), res):
        h, hist = _causal_conv(_snake(x2, R["s1"]), R["c1"], hist, d)
        x2 = x2 + R["b2"] + _snake(h, R["s2"]) @ R["w2"]
        res2.append(hist)
    return x2, x[:, T - 1:], res2


def _decode_step(P, S, codes, cos, sin, mask, cfg):
    """codes long [1, n, 16] and the stream state S -> (waveform float32 [1, n*1920] in [-1, 1], the new state)."""
    H, Bd = P["head"], P["body"]
    Q = codes.shape[-1]
    offs = torch.arange(Q - 1, device=codes.device) * cfg["codebook_size"]
    h = H["cb_first"][codes[..., 0]] @ H["proj_first"] + H["cb_rest"][codes[..., 1:] + offs].sum(2) @ H["proj_rest"]
    h, pre = _causal_conv(h, H["pre_conv"], S["pre"])
    h, K, V = _transformer(h, H["tr"], cos, sin, mask, S["K"], S["V"], cfg)
    up = []
    for U, hist in zip(H["up"], S["up"]):
        h, hist = _upsample(h, U, hist)
        up.append(hist)
    h, conv0 = _causal_conv(h, H["conv0"], S["conv0"])
    h = h.to(Bd["blocks"][0]["tw_a"].dtype)
    prev, res = [], []
    for Bp, r, pb, rb in zip(Bd["blocks"], cfg["upsample_rates"], S["prev"], S["res"]):
        h, pb, rb = _block(h, Bp, r, pb, rb)
        prev.append(pb)
        res.append(rb)
    h = _snake(h, Bd["snake_out"])
    T = h.shape[1]
    z = torch.cat([S["out"], (h @ Bd["conv_out"]["w"]).float()], 1)  # causal conv k=7, 96 -> 1
    y = z[:, 0:T, 0]
    for j in range(1, 7):
        y = y + z[:, j: j + T, j]
    state = {"pre": pre, "K": K, "V": V, "up": up, "conv0": conv0, "prev": prev, "res": res, "out": z[:, T:]}
    return torch.clamp(y + Bd["conv_out"]["b"], -1.0, 1.0), state


class CodecDecoder:
    """Codes [T, 16] -> 24 kHz audio, streamed in chunks of CHUNK frames with exactly the causal history each stage
    needs (see the MLX backend's CodecDecoder), so chunked decoding equals one pass."""
    CHUNK = 48

    def __init__(self, cfg: Config, device):
        self.c, self.device = cfg.codec, device
        self.params = _unflatten(_load(cfg.file("codec.safetensors"), device))
        hd, th = self.c["head_dim"], float(self.c["rope_theta"])
        self.inv = np.float32(1.0) / (np.float32(th) ** (np.arange(0, hd, 2).astype(np.float32) / np.float32(hd)))

    def initial_state(self):
        H, Bd, c, dev = self.params["head"], self.params["body"], self.c, self.device
        hdt, bdt = H["proj_first"].dtype, Bd["blocks"][0]["tw_a"].dtype
        z = lambda shape, dt: torch.zeros((1,) + tuple(shape), dtype=dt, device=dev)  # noqa: E731
        kv = (c["num_attention_heads"], c["sliding_window"] - 1, c["head_dim"])
        n_tr = len(H["tr"]["layers"])
        return {"pre": z(_conv_shape(H["pre_conv"]), hdt), "K": [z(kv, hdt) for _ in range(n_tr)],
                "V": [z(kv, hdt) for _ in range(n_tr)], "up": [z((6, U["ln_w"].shape[0]), hdt) for U in H["up"]],
                "conv0": z(_conv_shape(H["conv0"]), hdt),
                "prev": [z((1, Bp["tw_a"].shape[0]), bdt) for Bp in Bd["blocks"]],
                "res": [[z(_conv_shape(R["c1"], d), bdt) for R, d in zip(Bp["res"], (1, 3, 9))] for Bp in Bd["blocks"]],
                "out": z((6, Bd["conv_out"]["w"].shape[1]), torch.float32)}

    def aux(self, start: int, n: int):
        """RoPE tables of positions [start, start + n) and the mask over the window-1 carried keys + n new ones."""
        win = self.c["sliding_window"]
        ang = np.arange(start, start + n, dtype=np.float32)[:, None] * self.inv[None, :]
        emb = np.concatenate([ang, ang], -1).astype(np.float64)
        q = start + np.arange(n)[:, None]
        k = start - (win - 1) + np.arange(win - 1 + n)[None, :]
        mask = (k >= 0) & (k <= q) & (k > q - win)
        t = lambda a: torch.from_numpy(a).to(self.device)  # noqa: E731
        return t(np.cos(emb).astype(np.float32)), t(np.sin(emb).astype(np.float32)), t(mask)

    @torch.inference_mode()
    def decode(self, codes: np.ndarray) -> np.ndarray:
        c = torch.from_numpy(np.clip(np.asarray(codes, np.int64), 0, None)).to(self.device)
        S, out = self.initial_state(), []
        tf32 = torch.backends.cudnn.allow_tf32
        torch.backends.cudnn.allow_tf32 = False  # exact fp32 in the codec head, as on the other backends
        try:
            for s in range(0, c.shape[0], self.CHUNK):
                seg = c[s: s + self.CHUNK]
                y, S = _decode_step(self.params, S, seg[None], *self.aux(s, len(seg)), self.c)
                out.append(y[0].float().cpu().numpy())
        finally:
            torch.backends.cudnn.allow_tf32 = tf32
        return np.concatenate(out) if out else np.zeros(0, np.float32)
