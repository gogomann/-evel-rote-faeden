"""Diagnose: wie antworten die eingetragenen Modelle? Gibt keine Schlüssel aus."""
import json, sys, time
sys.path.insert(0, ".")
from story_world import providers as P

cfg = P.load()
want = sys.argv[1:] or ["deepseek"]
for prov in cfg.get("providers", []):
    if not any(w in (prov.get("name", "") + prov.get("base_url", "")).lower() for w in want):
        continue
    for model in sorted({e["model"] for t in cfg.get("tasks", {}).values() for e in t if e.get("provider") == prov["id"]}):
        for stream in (True, False):
            body = {"model": model, "max_tokens": 400, "temperature": 0.7, "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": "Antworte nur mit JSON."},
                                 {"role": "user", "content": 'Antworte mit {"ok": true, "satz": "<ein kurzer Satz>"}.'}]}
            t = time.time()
            try:
                if stream:
                    r = P._open(prov, "POST", "/chat/completions", dict(body, stream=True), 120)
                    keys, content, reasoning, finish, n = set(), 0, 0, None, 0
                    with r:
                        ctype = r.headers.get("Content-Type", "")
                        for raw in r:
                            line = raw.decode("utf-8", "replace").strip()
                            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                                continue
                            ev = json.loads(line[5:])
                            n += 1
                            ch = (ev.get("choices") or [{}])[0]
                            d = ch.get("delta") or {}
                            keys |= set(d)
                            content += len(d.get("content") or "")
                            reasoning += len(d.get("reasoning_content") or d.get("reasoning") or "")
                            finish = ch.get("finish_reason") or finish
                    print(f"{prov['name']} · {model} STREAM {ctype[:30]} events={n} delta-keys={sorted(keys)} "
                          f"content={content} reasoning={reasoning} finish={finish} {time.time()-t:.1f}s")
                else:
                    d = P._request(prov, "POST", "/chat/completions", body, 120)
                    ch = d["choices"][0]
                    m = ch["message"]
                    print(f"{prov['name']} · {model} NORMAL keys={sorted(m)} content={(m.get('content') or '')[:80]!r} "
                          f"reasoning={len(m.get('reasoning_content') or '')} finish={ch.get('finish_reason')} {time.time()-t:.1f}s")
            except Exception as exc:
                print(f"{prov['name']} · {model} {'STREAM' if stream else 'NORMAL'} FEHLER: {str(exc)[:300]}")
