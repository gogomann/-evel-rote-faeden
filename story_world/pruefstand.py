"""Prüfstand: feste Prüfwelt mit bekannten Antworten – misst, ob die Modelle noch im geplanten Rahmen arbeiten.

Die Prüfwelt ist klein und immer gleich (Figuren, ein toter Archivar, eine Fähre mit fester Reisezeit, ein Geheimnis
mit Kanarienwort). Wahlweise wird sie in eine Kopie der echten Welt eingebaut („mit Ballast“), um zu messen, wie die
Modelle mit großem Kontext zurechtkommen – und ob die Kaskade hilft.

Umfang „schnell“ (wenige Aufrufe):  Fallen für den Prüfer (4), Fehlalarme, Archivar-Genauigkeit (12)
Umfang „voll“ zusätzlich:           Format des Planers (1), Autor mit Länge/Spoiler/Konkretheit (2, 3, 8, 9),
                                    Qualitäts-Richter mit Plan-/Genre-Treue (11, 15) und Streuung (13),
                                    Bewerter-Rangfolge (16)
Es wird nur der Prüfwelt-Kopie etwas hinzugefügt; die echte Welt bleibt unberührt.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import time
from pathlib import Path

from . import episodes, llm, providers, quality, runs, service, szenarien, worlds
from .database import connect
from .migrations import migrate

CANARY = "Saphirschlüssel"

TRAP_TEXT = """[Erzähler] Es war der 14. Tag des Monats, als im Hafen Tharsis das Klopfen wieder begann.
[Doran Vex] Ilka, ich habe die alten Karten noch. Komm heute Abend zu mir ins Archiv.
[Erzähler] Juno Abe stand zur selben Stunde am Kai von Hafen Tharsis und zugleich an ihrem Stand auf der Ahuna-Station.
[Ilka Marren] Das dreifache Klopfen bedeutet, dass die Boje erwacht ist. Woher ich das weiß? Ich weiß es einfach.
[Erzähler] Was niemand ahnte: Das Signal stammte vom Saphirschlüssel-Nullpunkt, einer uralten Boje im Gürtel.
[Erzähler] Ilka startete die Glutfähre, und nach einer knappen Stunde setzte sie auf der Ahuna-Station auf.
[Erzähler] Dort wartete Juno schon mit zwei Bechern Tee."""

# Je Falle: Gruppen von Stichwörtern – eine Falle gilt als gefunden, wenn ein Befund aus jeder Gruppe eins enthält.
TRAPS = {
    "tote_figur": [["doran"], ["tot", "verstorb", "gestorb", "starb", "stirbt", "absturz", "lebt nicht", "nicht mehr am leben"]],
    "zwei_orte": [["juno"], ["gleichzeitig", "zugleich", "selben stunde", "selben zeit", "gleichen zeit", "zwei orte",
                             "zwei orten", "an zwei", "beiden orten"]],
    "tageszahl": [["14", "tageszahl", "tag des monats", "datum", "kalendernam", "kalender"]],
    "geheimnis": [["saphir", "nullpunkt", "boje", "geheimnis", "verrat", "verrät", "spoiler", "enthüll", "aufgelöst",
                   "rätsel", "wahrheit"]],
    "wissen_ohne_quelle": [["quelle", "woher", "weiß es einfach", "ohne grund", "unbegründet", "wissen"],
                           ["ilka", "klopf", "boje"]],
    "reisezeit": [["stunde", "reisezeit", "reise", "flug", "30", "schnell", "dauer", "entfernung"],
                  ["glutfähre", "fähre", "ahuna", "oskel", "varra"]],
}

CLEAN_TEXT = """[Erzähler] Im dritten Staub des Jahres der Weite lag über dem Hafen Tharsis ein kühler Wind.
[Ilka Marren] Juno, hörst du mich? Das Klopfen ist wieder da.
[Juno Abe] Ich höre dich, Ilka. Hier auf der Ahuna-Station ist es still.
[Erzähler] Ilka dachte an Junos letzten Funkspruch: Das Signal komme aus dem Gürtel, hatte sie gesagt.
[Ilka Marren] Dreimal hintereinander. Immer dreimal.
[Juno Abe] Dann schreib es auf. Vielleicht ergibt es eines Tages Sinn.
[Erzähler] Ilka notierte die Stunde nach dem Kalender von Tharsis, schaltete das Funkgerät leiser und lauschte in die Nacht."""

ARCHIVE_TEXT = CLEAN_TEXT + """
[Erzähler] Am nächsten Morgen eröffnete die Händlerin Sefa Lorn im Hafen Tharsis einen neuen Anleger, den alle nur den Nebelkai nannten.
[Sefa Lorn] Willkommen am Nebelkai. Von hier starten bald die Gleitsegler.
[Erzähler] Gleitsegler waren leichte Fluggeräte, die mit Sonnenwind über die Ebenen von Varra glitten, den Planeten aber nie verlassen konnten.
[Ilka Marren] Sefa, du hast wirklich an alles gedacht."""
ARCHIVE_EXPECTED = [("characters", "sefa", "Figur Sefa Lorn"), ("locations", "nebelkai", "Ort Nebelkai"),
                    ("technologies", "gleitsegl", "Technik Gleitsegler"), ("events", "nebelkai", "Ereignis Eröffnung")]

RICHTER_PROMPT = """Du bist ein strenger, unbestechlicher Qualitäts-Richter für Hörbuchtexte. Bewerte den TEXT, jede Zahl 0–10:
- "plan_treue": Setzt der Text den KAPITELPLAN um (Ereignisse, Figuren, Ende)? 10 = vollständig, 0 = ignoriert.
- "genre_treue": Passen Spannungsbogen, Ton und Regeln zum GENRE?
- "konkretheit": Konkrete Namen, Orte, Handlungen und Sinneseindrücke statt Floskeln und Allgemeinplätzen?
Anker: „Irgendwie war alles seltsam, eine Art Gefühl lag in der Luft“ verdient bei konkretheit höchstens 3.
„Ilka zog den Handschuh aus, das Metall der Luke war eiskalt; aus dem Funkgerät klopfte es dreimal“ verdient 8 oder mehr.
Antworte NUR mit JSON: {"plan_treue": 0, "genre_treue": 0, "konkretheit": 0, "begruendung": "2–3 Sätze"}"""

TESTS = {"schnell": ("pruefer", "archivar"), "voll": ("pruefer", "archivar", "planer", "autor", "bewerter")}
TASK_TESTS = {"pruefer": "Fallen für den Prüfer + Fehlalarme", "archivar": "Archivar-Genauigkeit",
              "planer": "Format des Planers", "autor": "Autor (Länge, Spoiler, Konkretheit) + Richter",
              "bewerter": "Bewerter-Rangfolge"}


# ---------------------------------------------------------------- Prüfwelt

def build_world(path: Path, ballast: str | None = None, kontext_modus: str = "voll") -> dict:
    """Legt die Prüfwelt an (optional als Kopie einer echten Welt) und gibt die ids der Prüf-Datensätze zurück."""
    if ballast:
        src = sqlite3.connect(str(worlds.path_for(ballast)))
        dst = sqlite3.connect(str(path))
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()
    conn = connect(path)
    try:
        migrate(conn)
        if not ballast:
            service.set_meta(conn, "name", "Prüfwelt")
            service.set_meta(conn, "beschreibung", "Feste Testwelt für den Prüfstand – immer gleich.")
        service.set_setting(conn, "kontext_modus", kontext_modus)
        add = lambda table, data, vis="offen": service.create_row(conn, table, data, actor="system", visibility=vis)  # noqa: E731
        ids = {}
        ids["cal"] = add("calendars", {"name": f"Kalender von Tharsis ({int(time.time())})", "epoch": 0, "year_length": 360,
                                       "cycles_per_year": 12, "year_names": "Jahr der Weite\nJahr des Salzes\nJahr der Glut",
                                       "cycle_names": "Erster Staub\nZweiter Staub\nDritter Staub\nVierter Staub"})
        ids["volk"] = add("peoples", {"name": f"Tharsis-Siedler {int(time.time() * 1000) % 100000}",
                                      "origin": "Nachfahren der ersten Kolonie auf Varra", "culture": "Händler und Piloten",
                                      "body_rules": "wie Menschen", "calendar_id": ids["cal"]})
        ids["system"] = add("locations", {"name": "Prüfsystem Kestrel", "kind": "system"})
        ids["varra"] = add("locations", {"name": "Varra", "kind": "planet", "parent_id": ids["system"]})
        ids["oskel"] = add("locations", {"name": "Oskel", "kind": "planet", "parent_id": ids["system"]})
        ids["hafen"] = add("locations", {"name": "Hafen Tharsis", "kind": "stadt", "parent_id": ids["varra"],
                                         "description": "Raumhafen auf Varra"})
        ids["ahuna"] = add("locations", {"name": "Ahuna-Station", "kind": "station", "parent_id": ids["oskel"],
                                         "description": "Handelsstation auf Oskel"})
        add("distances", {"from_location_id": ids["varra"], "to_location_id": ids["oskel"], "distance": 30})
        ids["faehre"] = add("technologies", {"name": "Glutfähre", "kind": "antrieb", "speed": 1, "prep_time": 0.5,
                                             "description": "Fusionsfähre zwischen Varra und Oskel",
                                             "rules": "Schnellstes Mittel zwischen Varra und Oskel; braucht mindestens 30 "
                                                      "Weltzeit-Einheiten."})
        ids["ilka"] = add("characters", {"name": "Ilka Marren", "role": "Pilotin", "people_id": ids["volk"],
                                         "location_id": ids["hafen"]})
        ids["doran"] = add("characters", {"name": "Doran Vex", "role": "Archivar", "people_id": ids["volk"],
                                          "description": "Starb zu Weltzeit 50 beim Absturz der Fähre Kestrel."})
        ids["juno"] = add("characters", {"name": "Juno Abe", "role": "Händlerin", "people_id": ids["volk"],
                                         "location_id": ids["ahuna"]})
        conn.executemany("INSERT INTO character_status_history (character_id, world_time, status) VALUES (?, ?, ?)",
                         [(ids["ilka"], 0, "lebt"), (ids["juno"], 0, "lebt"), (ids["doran"], 0, "lebt"),
                          (ids["doran"], 50, "tot")])
        conn.executemany("INSERT INTO character_presence (character_id, location_id, world_start, world_end) "
                         "VALUES (?, ?, ?, ?)", [(ids["ilka"], ids["hafen"], 100, 130), (ids["juno"], ids["ahuna"], 100, 130)])
        add("events", {"title": "Absturz der Fähre Kestrel", "world_time": 50, "important": 1,
                       "location_id": ids["varra"], "outcome": "Doran Vex stirbt."})
        ids["raetsel"] = add("mysteries", {"description": "Wer sendet das Signal aus dem Gürtel?", "status": "offen",
                                           "truth": f"Das Signal stammt vom {CANARY}-Nullpunkt, einer uralten Boje."},
                             "backstage")
        ids["code"] = add("codes", {"kind": "Dreifaches Klopfen", "meaning": "Die Boje ist erwacht."}, "backstage")
        add("knowledge", {"character_id": ids["ilka"], "content": "Das Signal kommt aus dem Gürtel.", "since_world_time": 90,
                          "source": "Funkspruch von Juno", "status": "geglaubt"})
        for rule, cat in (("Zeit wird nie als Tageszahl genannt, nur über Kalender- und Zyklusnamen.", "Zeit"),
                          ("Wissen ohne normale Erreichbarkeit braucht eine Quelle.", "Wissen"),
                          ("Zwischen Varra und Oskel braucht selbst die Glutfähre mindestens 30 Weltzeit-Einheiten.", "Reisen")):
            add("world_rules", {"rule": rule, "category": cat})
        ids["strang"] = add("threads", {"title": "Das Signal von Tharsis", "level": "mikro", "world_time_cursor": 110,
                                        "pov_id": ids["ilka"], "location_id": ids["hafen"],
                                        "premise": "Ilka verfolgt ein fremdes Klopfsignal."})
        release = conn.execute("SELECT COALESCE(MAX(release_nr), 0) + 1 FROM episodes").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO episodes (release_nr, thread_id, world_start, world_end, type, text, end_handoff, title, summary, "
            "status, word_count, created_at) VALUES (?, ?, 100, 110, 'gegenwart', ?, ?, 'Funkstille', ?, 'fertig', 60, ?)",
            (release, ids["strang"], "[Erzähler] Ilka hörte im Hafen Tharsis zum ersten Mal das Klopfen.",
             "Ilka beschließt, Juno auf der Ahuna-Station über Funk zu fragen.",
             "Ilka hört im Hafen Tharsis ein fremdes Klopfsignal; Juno meldet per Funk, es komme aus dem Gürtel.",
             time.strftime("%Y-%m-%d %H:%M:%S")))
        ids["folge"] = cur.lastrowid
        conn.commit()
        return ids
    finally:
        conn.close()


def _plan(ids: dict, words: int = 400) -> dict:
    return {"titel": "Das dreifache Klopfen", "strang": {"id": ids["strang"]}, "typ": "gegenwart", "welt_start": 120,
            "welt_ende": 121, "figuren": [{"id": ids["ilka"]}, {"id": ids["juno"]}],
            "einstieg": {"figur": "Ilka", "wer": "Hafenfunkerin in Tharsis", "gefuehl": "unruhig, kann nicht schlafen",
                         "lage": "das Klopfen ist wieder da", "ort": "Funkraum im Hafen Tharsis, Nacht"},
            "kapitel": [{"titel": "Klopfen in der Nacht", "inhalt": "Ilka hört im Hafen Tharsis erneut das dreifache Klopfen "
                         "und spricht per Funk mit Juno auf der Ahuna-Station. Sie beschließt, die Klopfzeichen zu notieren. "
                         "Am Ende lauscht sie in die Nacht.", "woerter": words}],
            "einschuebe": [], "andeutungen": "Das Klopfen andeuten, die Herkunft des Signals NICHT verraten.",
            "ende_uebergabe": "Ilka lauscht in die Nacht.", "vorbereitung": []}


# ---------------------------------------------------------------- Auswertung

def trap_hits(problems: list) -> dict:
    texts = [(str(p.get("beschreibung", "")) + " " + str(p.get("korrektur", ""))).lower()
             for p in problems if isinstance(p, dict)]
    return {name: any(all(any(k in t for k in group) for group in groups) for t in texts)
            for name, groups in TRAPS.items()}


def archive_score(data: dict, text: str) -> tuple:
    ops = [o for o in (data or {}).get("operationen") or [] if isinstance(o, dict)]
    found = []
    for table, key, _ in ARCHIVE_EXPECTED:
        hit = any(o.get("tabelle") == table and any(key in str(v).lower() for v in (o.get("felder") or {}).values())
                  for o in ops)
        found.append(hit)
    low = text.lower()
    invented = []
    for o in ops:
        if o.get("aktion") != "anlegen" or o.get("tabelle") not in ("characters", "locations", "technologies", "peoples",
                                                                     "organizations"):
            continue
        name = str((o.get("felder") or {}).get("name") or "")
        tokens = [w for w in quality.words(name) if len(w) >= 4]
        if tokens and not any(w in low for w in tokens):
            invented.append(name)
    score = max(0.0, min(10.0, 10 * sum(found) / len(found) - 2 * len(invented)))
    return round(score, 1), {"gefunden": dict(zip([label for _, _, label in ARCHIVE_EXPECTED], found)), "erfunden": invented}


def ranking_score(ratings: list) -> tuple:
    by = {r["nr"]: r for r in ratings}
    a, b, c = by.get(1), by.get(2), by.get(3)
    if not (a and b and c) or None in (a["kanonpassung"], b["kanonpassung"], c["kanonpassung"]):
        return 0.0, {"fehler": "unvollständige Bewertung"}
    checks = {"A passt besser als C": a["kanonpassung"] > c["kanonpassung"],
              "B passt besser als C": b["kanonpassung"] > c["kanonpassung"],
              "B überrascht mehr als A": b["ueberraschung"] > a["ueberraschung"]}
    return round(10 * sum(checks.values()) / len(checks), 1), checks


def _scenarios(ids: dict) -> tuple:
    expected = {"erwartung": "Ilka spricht weiter mit Juno über Funk und notiert das Klopfen; das Rätsel bleibt offen.",
                "wahrscheinlich": ["Funkgespräch", "Ilka notiert Zeichen", "ein neuer Hinweis aus dem Gürtel"],
                "sicher_geglaubt": ["Juno ist Ilkas verlässliche Freundin", "Das Signal kommt aus dem Gürtel"]}
    base = _plan(ids, 800)
    a = dict(base, titel="Noch ein Funkspruch", abweichung=0, idee="Ilka und Juno sprechen per Funk, Ilka notiert das Klopfen.")
    b = dict(base, titel="Junos Klopfen", abweichung=2,
             idee="Ilka entdeckt, dass Juno das Klopfen selbst sendet – Junos Funkspruch über den Gürtel war eine bewusste "
                  "Irreführung, um Ilka nach Oskel zu locken.",
             wendung="Juno ist die Quelle des Klopfens; ihr früherer Funkspruch war gelogen (Ilka hatte ihn nur geglaubt).",
             kapitel=[{"titel": "Das Echo", "inhalt": "Ilka peilt das Klopfen an und findet Junos Sender. Juno gesteht per Funk, "
                       "dass sie Ilka nach Oskel holen will, und nennt einen guten Grund.", "woerter": 800}])
    c = dict(base, titel="Dorans Expedition", abweichung=3,
             figuren=[{"id": ids["ilka"]}, {"id": ids["doran"]}],
             idee="Doran Vex führt Ilka persönlich zum Ursprung des Signals; mit der Glutfähre sind sie in einer Stunde auf Oskel.",
             kapitel=[{"titel": "Aufbruch", "inhalt": "Doran Vex holt Ilka im Hafen Tharsis ab, sie fliegen in einer Stunde nach "
                       "Oskel und finden dort die Boje.", "woerter": 800}])
    return expected, [a, b, c]


# ---------------------------------------------------------------- Ablauf

def _model_list(task: str, chosen: dict | None) -> list:
    entries = (chosen or {}).get(task) or []
    out = []
    ids = {p["id"]: p for p in providers.all_providers()}
    for e in entries[:3]:
        prov = ids.get(e.get("provider"))
        if prov and str(e.get("model") or "").strip():
            out.append((prov, e["model"].strip()))
    if not out:
        chain = providers.resolve_chain(task)
        if chain:
            out = [chain[0]]
    return out


def _new_run(conn, task: str, model, sid: str, kontext_modus: str, welt_label: str) -> runs.Run:
    conn.commit()
    run = runs.Run(conn, "Prüfstand", f"{TASK_TESTS.get(task, task)} · {model[0]['name']} · {model[1]}", task,
                   f"Prüfstand {sid}")
    run.models, run.model_used, run.qa = {}, None, []
    run.genre_rules, run.age_rating, run.voice = "", "", ""
    run.quelle, run.serie, run.welt_label = "pruefstand", sid, welt_label
    run.kontext, run.abweichung = kontext_modus, 0
    run.chains = {task: [model]}
    if task == "planer":
        run.chains["thema"] = [model]  # Kaskade: erste Ebene mit demselben Modell
    return run


def _label(model) -> str:
    return f"{model[0]['name']} · {model[1]}"


def _judge(conn, run, plan: dict, text: str, judge_model, sid: str, welt_label: str) -> dict:
    genre = conn.execute("SELECT id FROM genres WHERE name = 'Science-Fiction'").fetchone()
    from . import genres
    rules = genres.rules_text(conn, genre[0]) if genre else "GENRE: Science-Fiction"
    messages = [{"role": "system", "content": RICHTER_PROMPT},
                {"role": "user", "content": f"KAPITELPLAN:\n{json.dumps(plan['kapitel'], ensure_ascii=False)}\n"
                 f"ENDE: {plan['ende_uebergabe']}\n\n{rules}\n\nTEXT:\n{text}"}]

    def validate(data):
        need = ("plan_treue", "genre_treue", "konkretheit")
        return [] if isinstance(data, dict) and all(isinstance(data.get(k), (int, float)) for k in need) else \
            ["plan_treue, genre_treue und konkretheit als Zahlen fehlen"]

    jrun = _new_run(conn, "richter", judge_model, sid, run.kontext, welt_label)
    first = episodes._ask_json(jrun, messages, "richter", 10, 50, 600, "Richter", validate, temperature=0.0,
                               fixed_temperature=True)
    second = episodes._ask_json(jrun, messages, "richter", 50, 90, 600, "Richter (Wiederholung)", validate,
                                temperature=0.0, fixed_temperature=True)
    jrun.finish("fertig")
    spread_ = sum(abs(float(first[k]) - float(second[k])) for k in ("plan_treue", "genre_treue", "konkretheit")) / 3
    return {"plan_treue": float(first["plan_treue"]), "genre_treue": float(first["genre_treue"]),
            "konkretheit": float(first["konkretheit"]), "streuung": round(spread_, 2),
            "begruendung": str(first.get("begruendung", ""))[:400], "richter": _label(judge_model)}


def _one(conn, task: str, model, ids: dict, sid: str, kontext_modus: str, welt_label: str, judge_model) -> dict:
    """Ein Test für ein Modell. Gibt {test: wert} und Details zurück."""
    run = _new_run(conn, task, model, sid, kontext_modus, welt_label)
    label = _label(model)
    values, details = {}, {}

    def rec(test, value, info=None):
        values[test] = value
        quality.record(test, task, label, value, "pruefstand", welt_label, run.id, sid, info)

    try:
        if task == "pruefer":
            plan = _plan(ids)
            problems = episodes._check(conn, run, plan, [TRAP_TEXT])
            hits = trap_hits(problems)
            rec("pruefer_fallen", round(10 * sum(hits.values()) / len(hits), 1),
                {"fallen": hits, "befunde": [str(p.get("beschreibung", ""))[:160] for p in problems if isinstance(p, dict)][:12]})
            clean = episodes._check(conn, run, plan, [CLEAN_TEXT])
            serious = [p for p in clean if isinstance(p, dict) and p.get("schwere") in ("hoch", "mittel")]
            rec("fehlalarme", float(len(serious)), {"befunde": [str(p.get("beschreibung", ""))[:160] for p in serious][:8]})
            details["fallen"] = hits
        elif task == "archivar":
            data = episodes._archive(conn, run, _plan(ids), ARCHIVE_TEXT)
            score, info = archive_score(data, ARCHIVE_TEXT)
            rec("archivar", score, info)
            details.update(info)
        elif task == "planer":
            plan = episodes._plan(conn, run, "Ein ruhiger Abend mit Ilka und dem Klopfen.", ids["strang"], 800)
            details["plan"] = plan.get("titel")
            values["format"] = next((q["wert"] for q in run.qa if q["test"] == "format"), None)
        elif task == "autor":
            plan = _plan(ids, 400)
            cast = [{"id": ids["ilka"], "name": "Ilka Marren", "role": "Pilotin"},
                    {"id": ids["juno"], "name": "Juno Abe", "role": "Händlerin"}]
            genre = conn.execute("SELECT id FROM genres WHERE name = 'Science-Fiction'").fetchone()
            if genre:
                from . import genres
                run.genre_rules = genres.rules_text(conn, genre[0])
            text = episodes._write_chapter(conn, run, plan, cast, 0, "", 10, 60)
            truth = conn.execute("SELECT truth FROM mysteries WHERE id = ?", (ids["raetsel"],)).fetchone()[0]
            meaning = conn.execute("SELECT meaning FROM codes WHERE id = ?", (ids["code"],)).fetchone()[0]
            share, found = quality.spoiler_share([truth, meaning], text, (CANARY,))
            rec("spoiler", share, {"treffer": found} if found else None)
            names = episodes._canon_names(conn)
            rec("konkretheit", quality.concreteness(text, names)["wert"], {"art": "Code"})
            for q in run.qa:
                if q["test"] in ("laenge", "verweigerung"):
                    values[q["test"]] = q["wert"]
            details["woerter"] = episodes.word_count(text)
            if judge_model:
                j = _judge(conn, run, plan, text, judge_model, sid, welt_label)
                quality.record("plan_treue", "autor", label, j["plan_treue"], "pruefstand", welt_label, run.id, sid,
                               {"richter": j["richter"], "begruendung": j["begruendung"]})
                quality.record("genre_treue", "autor", label, j["genre_treue"], "pruefstand", welt_label, run.id, sid,
                               {"richter": j["richter"]})
                quality.record("richter_streuung", "richter", j["richter"], j["streuung"], "pruefstand", welt_label,
                               run.id, sid)
                values.update(plan_treue=j["plan_treue"], genre_treue=j["genre_treue"])
                details["richter"] = {"modell": j["richter"], "streuung": j["streuung"], "begruendung": j["begruendung"],
                                      "konkretheit_richter": j["konkretheit"]}
        elif task == "bewerter":
            expected, plans = _scenarios(ids)
            ratings = szenarien.evaluate(conn, run, expected, plans)
            score, checks = ranking_score(ratings)
            rec("bewerter_rangfolge", score, {"pruefungen": checks})
            details["pruefungen"] = checks
            details["bewertungen"] = [{k: r[k] for k in ("nr", "titel", "kanonpassung", "ueberraschung", "fair")}
                                      for r in ratings]
        run.finish("fertig")
    except (episodes.EpisodeError, llm.LLMError, providers.ProviderError, service.ValidationError) as exc:
        run.finish("fehler", error=str(exc)[:500])
        details["fehler"] = str(exc)[:300]
    return {"werte": values, "details": details}


def run_bench(umfang: str = "schnell", modelle: dict | None = None, ballast: str | None = None,
              kontext_modus: str = "voll", job_id: int | None = None, sid: str | None = None) -> dict:
    """Führt den Prüfstand aus. Ergebnis je Modell und Aufgabe; Messwerte landen in der Qualitäts-Datenbank."""
    tasks = TESTS["voll" if umfang == "voll" else "schnell"]
    welt_label = f"Prüfwelt{' + ' + ballast if ballast else ''} · {kontext_modus}"
    sid = sid or quality.series_start("pruefstand", f"Prüfstand {umfang}" + (f", Ballast {ballast}" if ballast else "")
                                      + f", Kontext {kontext_modus}", ballast)
    started = time.time()
    result = {"umfang": umfang, "kontext": kontext_modus, "ballast": ballast, "modelle": {}, "schritt": "Prüfwelt wird gebaut"}
    tmp = Path(tempfile.mkdtemp(prefix="sw-pruefstand-"))
    try:
        quality.series_update(sid, result)
        path = tmp / "pruefwelt.sqlite3"
        ids = build_world(path, ballast, kontext_modus)
        judge = _model_list("richter", modelle)
        plan = [(task, m) for task in tasks for m in _model_list(task, modelle)]
        if not plan:
            raise RuntimeError("Keine KI eingerichtet – unter „Modelle je Aufgabe“ Modelle wählen.")
        conn = connect(path)
        try:
            for n, (task, model) in enumerate(plan, 1):
                result["schritt"] = f"{n}/{len(plan)}: {TASK_TESTS[task]} – {_label(model)}"
                quality.series_update(sid, result)
                out = _one(conn, task, model, ids, sid, kontext_modus, welt_label,
                           judge[0] if (task == "autor" and judge) else None)
                entry = result["modelle"].setdefault(_label(model), {"aufgaben": [], "werte": {}, "details": {}})
                entry["aufgaben"].append(task)
                entry["werte"].update({k: v for k, v in out["werte"].items() if v is not None})
                entry["details"][task] = out["details"]
        finally:
            conn.close()
        result["schritt"] = "fertig"
        result["dauer"] = round(time.time() - started, 1)
        ok = any(m["werte"] for m in result["modelle"].values())
        if not ok:  # kein einziger Messwert: z. B. Anbieter nicht erreichbar
            errors = [d.get("fehler") for m in result["modelle"].values() for d in m["details"].values() if d.get("fehler")]
            quality.series_finish(sid, result, "Keine Messung gelungen. " + (errors[0] if errors else ""))
            raise RuntimeError("Prüfstand: keine Messung gelungen – " + (errors[0] if errors else "unbekannter Fehler"))
        quality.auto_reference()
        quality.close_hints("modellwechsel")
        quality.series_finish(sid, result)
        return result
    except Exception as exc:
        if result.get("schritt") != "fertig":
            result["schritt"] = "abgebrochen"
            quality.series_finish(sid, result, str(exc)[:500])
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
