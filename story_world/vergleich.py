"""Modellvergleich: einen gespeicherten KI-Aufruf noch einmal an 2–3 andere Modelle schicken und nebeneinander messen.

Gemessen wird per Code (gültiges JSON, Fehler in der Struktur, Länge, Konkretheit, Dauer) und auf Wunsch zusätzlich vom
Qualitäts-Richter, der die Antworten anonym (A, B, C …) gegeneinander bewertet. Die Originalantwort läuft als
Vergleichsmaßstab mit. Ergebnisse landen als Serie in der Qualitäts-Datenbank (Quelle „vergleich“).
"""

from __future__ import annotations

import json
import time

from . import episodes, llm, providers, quality, runs, service, worlds

JSON_TASKS = {"planer", "pruefer", "archivar", "weltenbau", "luecken", "einschuebe", "thema", "erwartung", "bewerter",
              "richter", "profil"}

RICHTER_VERGLEICH = """Du bist ein strenger, unbestechlicher Qualitäts-Richter. Mehrere Modelle haben dieselbe Aufgabe
bekommen. Bewerte jede Antwort 0–10: Erfüllt sie den Auftrag vollständig, korrekt, konkret und im verlangten Format?
Die Reihenfolge sagt nichts über die Qualität. Antworte NUR mit JSON:
{"bewertungen": [{"kennung": "A", "wert": 0, "begruendung": "1–2 Sätze"}], "bester": "A"}"""


def _measure(task: str, text: str, names: list, original: str | None) -> dict:
    out: dict = {"zeichen": len(text or "")}
    if task in JSON_TASKS:
        try:
            data = llm._extract_json(text)
            out["json"] = True
        except llm.LLMError as exc:
            out["json"], out["fehler"] = False, str(exc)[:200]
            return out
        problems = []
        if task == "planer":
            problems = episodes._validate_plan(data) if "szenarien" not in data else []
        elif task in ("weltenbau", "luecken", "einschuebe", "archivar"):
            ops = data.get("operationen") or []
            problems = service.validate_payload({"operationen": ops}) if ops else []
            if task == "archivar" and not data.get("folgen_zusammenfassung"):
                problems.append("folgen_zusammenfassung fehlt")
            out["operationen"] = len(ops)
        elif task == "pruefer":
            items = data.get("probleme") if isinstance(data, dict) else None
            if not isinstance(items, list):
                problems.append("probleme fehlt")
            else:
                out["befunde"] = len(items)
                out["wichtig"] = sum(1 for p in items if isinstance(p, dict) and p.get("schwere") in ("hoch", "mittel"))
        out["strukturfehler"] = problems[:6]
        out["format"] = 1.0 if not problems else 0.5
    else:
        out["woerter"] = episodes.word_count(text)
        out["konkretheit"] = quality.concreteness(text, names)["wert"]
        if original:
            out["stil_abweichung_zum_original"] = quality.style_deviation(text, original)
            out["laenge_zum_original"] = round(episodes.word_count(text) / max(1, episodes.word_count(original)), 2)
    return out


def _judge(call: dict, answers: list, judge) -> dict:
    system = next((m["content"] for m in call["messages"] if m["role"] == "system"), "")
    user = next((m["content"] for m in reversed(call["messages"]) if m["role"] == "user"), "")
    letters = "ABCDE"
    shown = "\n\n".join(f"=== ANTWORT {letters[i]} ===\n{a['text'][:7000]}" for i, a in enumerate(answers))
    messages = [{"role": "system", "content": RICHTER_VERGLEICH},
                {"role": "user", "content": f"AUFGABE (Systemanweisung, gekürzt):\n{system[:3000]}\n\n"
                 f"AUFTRAG (Ende der Nachricht, gekürzt):\n{user[-4000:]}\n\n{shown}"}]
    text, used = providers.complete(messages, "richter", json_mode=True, max_tokens=1500, temperature=0.0,
                                    fixed_temperature=True, chain=judge)
    data = llm._extract_json(text)
    by = {str(b.get("kennung", "")).strip().upper(): b for b in data.get("bewertungen") or [] if isinstance(b, dict)}
    out = {"modell": used, "bester": None, "werte": {}}
    for i, a in enumerate(answers):
        b = by.get(letters[i])
        if b:
            try:
                out["werte"][a["modell"]] = {"wert": max(0.0, min(10.0, float(b.get("wert")))),
                                             "begruendung": str(b.get("begruendung", ""))[:300]}
            except (TypeError, ValueError):
                pass
    best = str(data.get("bester", "")).strip().upper()
    if best in letters[:len(answers)]:
        out["bester"] = answers[letters.index(best)]["modell"]
    return out


def compare(slug: str, call_id: int, modelle: list, richter: bool = True, sid: str | None = None) -> dict:
    with worlds.open_world(slug) as conn:
        call = runs.get_call(conn, call_id)
        names = episodes._canon_names(conn)
    task = call.get("task") or "standard"
    sid = sid or quality.series_start("vergleich", f"Vergleich: {call.get('step') or task}", slug)
    ids = {p["id"]: p for p in providers.all_providers()}
    chosen = [(ids[m["provider"]], m["model"].strip()) for m in modelle[:3]
              if m.get("provider") in ids and str(m.get("model") or "").strip()]
    if not chosen:
        quality.series_finish(sid, None, "Keine Modelle gewählt.")
        raise service.ValidationError("Bitte mindestens ein Modell wählen.")
    result = {"aufruf": {"id": call_id, "schritt": call.get("step"), "aufgabe": task, "modell": call.get("model"),
                         "welt": slug, "lauf_id": call.get("run_id"), "prompt_zeichen": call.get("prompt_chars")},
              "ergebnisse": [], "schritt": "läuft"}
    original = call.get("response") or ""
    if original:
        result["ergebnisse"].append({"modell": f"Original · {call.get('model') or '?'}", "original": True,
                                     "text": original, "sekunden": call.get("seconds"),
                                     "werte": _measure(task, original, names, None)})
    quality.series_update(sid, result)
    max_tokens = max(4000, int(len(original) / 2.5)) if original else 8000
    for prov, model in chosen:
        label = f"{prov['name']} · {model}"
        result["schritt"] = f"frage {label}"
        quality.series_update(sid, result)
        started = time.time()
        entry = {"modell": label}
        try:
            text, _ = providers.complete(call["messages"], task, json_mode=task in JSON_TASKS, max_tokens=max_tokens,
                                         chain=[(prov, model)])
            entry.update(text=text, sekunden=round(time.time() - started, 1),
                         werte=_measure(task, text, names, original or None))
            werte = entry["werte"]
            if "format" in werte or "json" in werte:
                quality.record("format", task, label, werte.get("format", 0.0), "vergleich", slug, call.get("run_id"), sid)
            if "konkretheit" in werte:
                quality.record("konkretheit", task, label, werte["konkretheit"], "vergleich", slug, call.get("run_id"), sid)
        except providers.ProviderError as exc:
            entry.update(text="", sekunden=round(time.time() - started, 1), fehler=str(exc)[:400], werte={})
        result["ergebnisse"].append(entry)
        quality.series_update(sid, result)
    answers = [e for e in result["ergebnisse"] if e.get("text")]
    if richter and len(answers) >= 2:
        result["schritt"] = "Richter bewertet"
        quality.series_update(sid, result)
        try:
            judge = providers.resolve_chain("richter")[:1] or None
            result["richter"] = _judge(call, answers, judge)
        except (providers.ProviderError, llm.LLMError) as exc:
            result["richter"] = {"fehler": str(exc)[:300]}
    result["schritt"] = "fertig"
    quality.series_finish(sid, result)
    return result


def public(result: dict | None, reveal: bool) -> dict | None:
    """Antworttexte können Backstage enthalten – ohne Backstage nur Messwerte."""
    if not result or reveal:
        return result
    out = json.loads(json.dumps(result))
    for e in out.get("ergebnisse") or []:
        e["text"] = None
    if isinstance(out.get("richter"), dict):
        for v in (out["richter"].get("werte") or {}).values():
            v.pop("begruendung", None)
    return out
