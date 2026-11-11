"""Spielt den gespeicherten Prompt eines KI-Laufs erneut gegen ein Modell ab und protokolliert Ende-Grund und Längen.
Aufruf: python3 tools/sw_replay.py <welt> <lauf-id> <Anbietername> <modell> [max_tokens]"""
import json, sqlite3, sys, time
sys.path.insert(0, ".")
from story_world import providers as P

world, run_id, pname, model = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
max_tokens = int(sys.argv[5]) if len(sys.argv) > 5 else 8000
raw = sqlite3.connect(f"welten/{world}.sqlite3").execute("SELECT prompt FROM ai_runs WHERE id = ?", (run_id,)).fetchone()[0]
messages = json.loads(raw)
if isinstance(messages, dict):
    messages = messages.get("messages", messages)
prov = [p for p in P.load()["providers"] if p["name"] == pname][0]
body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.8,
        "response_format": {"type": "json_object"}, "stream": True}
t = time.time()
keys, content, reasoning, finish, n, usage = set(), [], 0, None, 0, None
with P._open(prov, "POST", "/chat/completions", body, 600) as r:
    for line in r:
        line = line.decode("utf-8", "replace").strip()
        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
            continue
        ev = json.loads(line[5:])
        n += 1
        usage = ev.get("usage") or usage
        ch = (ev.get("choices") or [{}])[0]
        d = ch.get("delta") or {}
        keys |= set(d)
        content.append(d.get("content") or "")
        reasoning += len(d.get("reasoning_content") or d.get("reasoning") or "")
        finish = ch.get("finish_reason") or finish
text = "".join(content)
print(json.dumps({"prompt_zeichen": sum(len(str(m.get("content", ""))) for m in messages), "events": n,
                  "delta_keys": sorted(keys), "content_zeichen": len(text), "reasoning_zeichen": reasoning,
                  "finish": finish, "usage": usage, "sekunden": round(time.time() - t, 1),
                  "anfang": text[:200]}, ensure_ascii=False, indent=1))
