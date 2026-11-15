"""Szenarien mit Abweichungsregler: Erwartung des Hörers → mehrere Pläne → Bewerter → Auswahl.

- Erwartung: ein Agent sieht nur, was der Hörer kennt (kein Backstage) und schreibt auf, was er als Nächstes erwartet.
- Szenarien: der Planer liefert N Pläne mit unterschiedlicher Abweichungsstufe (0 eng … 3 Bruch).
- Bewerter: misst je Szenario Kanonpassung (0–10), Überraschung gegenüber der Erwartung (0–10) und Fairness.
  Harte Prüfungen per Code (tote Figuren, rückwärts laufende Zeit) ziehen zusätzlich Punkte ab.
- Auswahl: unter der Mindest-Kanonpassung fällt alles raus; von den übrigen gewinnt das Szenario, dessen Überraschung
  am nächsten an der Zielvorgabe liegt. Oder der Mensch wählt selbst.
"""

from __future__ import annotations

import json
import sqlite3

from . import episodes, kontext, llm, service, vorlage

ERWARTUNG_PROMPT = """Du bist ein aufmerksamer Stammhörer dieser Hörbuchreihe. Du kennst nur, was bisher erzählt wurde –
keine Geheimnisse, keine Pläne. Sag ehrlich, was du von der nächsten Folge erwartest.
Antworte NUR mit JSON:
{"erwartung": "3–5 Sätze, was vermutlich passiert",
 "wahrscheinlich": ["die drei wahrscheinlichsten Entwicklungen"],
 "sicher_geglaubt": ["was du für sicher hältst – Orte, Figuren, Beziehungen, die bestimmt so bleiben"]}"""

BEWERTER_PROMPT = """Du bist der Bewerter einer fortlaufenden Hörbuchreihe. Du bekommst den Kanon (inklusive Geheimnissen),
die Erwartung eines Stammhörers und mehrere Szenarien (Pläne) für die nächste Folge. Bewerte jedes Szenario einzeln, streng
und ehrlich:
- "kanonpassung" 0–10: 10 = widerspricht nichts (Kanon, Zeitleiste, Figurenstatus, Reisezeiten, Wissensquellen,
  Weltregeln). Jeder echte Widerspruch kostet deutlich. Nenne Widersprüche konkret.
- "ueberraschung" 0–10 gegenüber der ERWARTUNG: 0 = genau das Erwartete, 10 = völlig unerwartet.
- "fair" true/false: Ist eine Wendung vorher angelegt oder rückblickend erklärbar? (Überraschung ja, Betrug nein.)
Antworte NUR mit JSON:
{"bewertungen": [{"nr": 1, "kanonpassung": 0, "widersprueche": ["…"], "ueberraschung": 0, "fair": true,
                  "begruendung": "1–2 Sätze"}]}"""

LEVEL_NAMES = {0: "eng", 1: "Nebenwege", 2: "Wendung", 3: "Bruch"}


# ---------------------------------------------------------------- Werte auflösen (Folge > Strang > Genre > Welt)

def params(conn: sqlite3.Connection, thread_id: int | None, genre_id: int | None,
           abweichung: int | None = None, anzahl: int | None = None) -> dict:
    level = abweichung
    source = "Folge"
    if level is None and thread_id:
        row = conn.execute("SELECT abweichung FROM threads WHERE id = ?", (thread_id,)).fetchone()
        if row and row[0] is not None:
            level, source = row[0], "Strang"
    if level is None and genre_id:
        row = conn.execute("SELECT abweichung FROM genres WHERE id = ?", (genre_id,)).fetchone()
        if row and row[0] is not None:
            level, source = row[0], "Genre"
    if level is None:
        level, source = int(service.setting(conn, "abweichung") or 0), "Welt"
    level = max(0, min(3, int(level)))
    count = anzahl if anzahl is not None else int(service.setting(conn, "szenarien") or 1)
    target = service.setting(conn, "ziel_ueberraschung")
    return {"abweichung": level, "quelle": source, "szenarien": max(1, min(3, int(count))),
            "ziel": float(target) if str(target).strip() else episodes.SURPRISE_TARGET[level],
            "min_kanon": float(service.setting(conn, "min_kanon") or 6),
            "wahl": service.setting(conn, "szenario_wahl")}


def spread(level: int, count: int) -> list:
    """Abweichungsstufen der Szenarien: um die gewählte Stufe herum, möglichst verschieden."""
    if count <= 1:
        return [level]
    order = [level, level - 1, level + 1, level - 2, level + 2, level + 3, level - 3]
    out = []
    for x in order:
        if 0 <= x <= 3 and x not in out:
            out.append(x)
        if len(out) == count:
            break
    return sorted(out)


# ---------------------------------------------------------------- Erwartung (ohne Backstage)

def public_context(conn: sqlite3.Connection, thread_id: int | None, wish: str) -> str:
    eps = [dict(r) for r in conn.execute(
        "SELECT e.release_nr, e.title, e.summary, e.end_handoff, t.title AS strang FROM episodes e "
        "LEFT JOIN threads t ON t.id = e.thread_id WHERE e.status = 'fertig' ORDER BY e.release_nr DESC LIMIT 6")]
    threads = [{"titel": r[0], "praemisse": r[1]} for r in conn.execute(
        "SELECT title, premise FROM threads WHERE visibility = 'offen' AND (status IS NULL OR status != 'beendet')")]
    figures = [r[0] for r in conn.execute("SELECT name FROM characters WHERE visibility = 'offen' ORDER BY id LIMIT 80")]
    parts = [vorlage.world_header(conn),
             "BISHER ERZÄHLT (neueste zuerst):\n" + json.dumps(eps, ensure_ascii=False),
             "BEKANNTE GESCHICHTEN:\n" + json.dumps(threads, ensure_ascii=False),
             "BEKANNTE FIGUREN: " + ", ".join(figures)]
    if thread_id:
        row = conn.execute("SELECT title FROM threads WHERE id = ? AND visibility = 'offen'", (thread_id,)).fetchone()
        if row:
            parts.append(f"ES GEHT WEITER MIT: {row[0]}")
    if wish.strip():
        parts.append(f"WUNSCH DES HÖRERS: {wish.strip()}")
    return "\n\n".join(parts)


def expectation(conn, run, thread_id: int | None, wish: str) -> dict:
    messages = [{"role": "system", "content": ERWARTUNG_PROMPT},
                {"role": "user", "content": public_context(conn, thread_id, wish)}]

    def validate(data):
        return [] if isinstance(data, dict) and data.get("erwartung") else ["erwartung fehlt"]

    data = episodes._ask_json(run, messages, "erwartung", 4, 6, 1200, "Erwartung", validate)
    run.step(f"Erwartung des Hörers: {str(data.get('erwartung', ''))[:140]}", 6, "ok")
    episodes._ev(run, "szenario", "frage", "Erwartung des Hörers vorhergesagt (Maßstab für die Überraschung)",
                 ausgang="ok", call_id=getattr(run, "last_call_id", None), ergebnis=data,
                 regel="Nur öffentliches Wissen – so, wie ein Hörer die nächste Folge erwarten würde.")
    return data


# ---------------------------------------------------------------- Szenarien

def _scenario_instructions(levels: list) -> str:
    lines = ["", "", f"SZENARIEN: Liefere {len(levels)} deutlich verschiedene Szenarien für diese Folge.",
             'Antworte dann NUR mit JSON: {"szenarien": [<Plan im obigen Format, zusätzlich "abweichung": <Stufe>, '
             '"idee": "das Szenario in einem Satz", "wendung": "die geplante Überraschung in einem Satz (oder leer)">]}']
    for i, level in enumerate(levels, 1):
        lines.append(f"Szenario {i}: Stufe {level} ({LEVEL_NAMES[level]}). {episodes.DEVIATION[level] or 'Eng an Plan und naheliegender Fortsetzung.'}")
    lines.append("Jedes Szenario braucht eigene \"vorbereitung\", falls es Neues anlegt. Kanon und Weltregeln gelten für alle.")
    return "\n".join(lines)


def plan_scenarios(conn, run, wish: str, thread_id: int | None, words: int, levels: list, expected: dict) -> list:
    extra = ("\nERWARTUNG DES HÖRERS (daran misst sich die Überraschung):\n"
             + json.dumps(expected, ensure_ascii=False))
    messages = episodes._plan_messages(conn, run, wish, thread_id, words, extra=extra,
                                       system_extra=_scenario_instructions(levels))

    def validate(data):
        items = data.get("szenarien") if isinstance(data, dict) else None
        if not isinstance(items, list) or not items:
            return ["szenarien fehlt (Liste von Plänen)"]
        good = [p for p in items if isinstance(p, dict) and not episodes.plan_check(conn, p)]
        if good:
            return []
        return [f"Szenario {i}: {'; '.join(episodes.plan_check(conn, p))}" for i, p in enumerate(items, 1)]

    data = episodes._ask_json(run, messages, "planer", 6, 12, 4000 * len(levels), "Planer (Szenarien)", validate)
    plans = []
    for i, p in enumerate(data["szenarien"], 1):
        errors = episodes.plan_check(conn, p) if isinstance(p, dict) else ["kein Objekt"]
        if errors:
            run.step(f"Szenario {i} verworfen: {'; '.join(errors)}", None, "warnung")
            episodes._ev(run, "szenario", "eingriff", f"Szenario {i} verworfen (Plan-Prüfung)", ausgang="eingriff",
                         regel="Jedes Szenario muss die Plan-Prüfung bestehen.", ergebnis={"fehler": errors[:8]})
            continue
        level = p.get("abweichung")
        p["abweichung"] = level if isinstance(level, int) and 0 <= level <= 3 else levels[min(i - 1, len(levels) - 1)]
        plans.append(p)
    run.step(f"{len(plans)} Szenarien geplant: " + " | ".join(f"„{p.get('titel', '')}“ (Stufe {p['abweichung']})"
                                                             for p in plans), 10, "ok")
    return plans


# ---------------------------------------------------------------- Bewertung

def hard_checks(conn: sqlite3.Connection, plan: dict) -> list:
    """Code-Prüfungen, die kein Modell wegdiskutieren kann."""
    problems = []
    try:
        start = float(plan.get("welt_start"))
    except (TypeError, ValueError):
        return ["Weltzeit fehlt"]
    for f in plan.get("figuren") or []:
        cid = f.get("id") if isinstance(f, dict) else None
        if not isinstance(cid, int):
            continue
        row = conn.execute("SELECT status FROM character_status_history WHERE character_id = ? AND world_time <= ? "
                           "ORDER BY world_time DESC LIMIT 1", (cid, start)).fetchone()
        if row and row[0] == "tot" and plan.get("typ") != "rueckblende":
            name = conn.execute("SELECT name FROM characters WHERE id = ?", (cid,)).fetchone()
            problems.append(f"{name[0] if name else cid} ist zu Weltzeit {start:g} tot")
    strang = plan.get("strang") or {}
    if isinstance(strang.get("id"), int) and plan.get("typ") in ("gegenwart",):
        row = conn.execute("SELECT world_time_cursor FROM threads WHERE id = ?", (strang["id"],)).fetchone()
        if row and row[0] is not None and start < float(row[0]) - 1e-9:
            problems.append(f"Gegenwart beginnt vor dem Zeit-Cursor des Strangs ({start:g} < {float(row[0]):g})")
    return problems


def evaluate(conn, run, expected: dict, plans: list) -> list:
    if episodes._cascade(run):
        ids = kontext.mentioned(conn, json.dumps(plans, ensure_ascii=False))
        for p in plans:
            ids = kontext.merge_ids(ids, {"characters": [f.get("id") for f in p.get("figuren") or [] if isinstance(f, dict)]})
        context = episodes._context_cascade(conn, ids)
    else:
        context = episodes._context(conn)
    shown = [{"nr": i, **{k: v for k, v in p.items() if not k.startswith("_")}} for i, p in enumerate(plans, 1)]
    messages = [{"role": "system", "content": BEWERTER_PROMPT},
                {"role": "user", "content": context + "\n\nERWARTUNG DES HÖRERS:\n" + json.dumps(expected, ensure_ascii=False)
                 + "\n\nSZENARIEN:\n" + json.dumps(shown, ensure_ascii=False)}]

    def validate(data):
        items = data.get("bewertungen") if isinstance(data, dict) else None
        return [] if isinstance(items, list) and items else ["bewertungen fehlt"]

    data = episodes._ask_json(run, messages, "bewerter", 12, 14, 1500, "Bewerter", validate,
                              temperature=0.0, fixed_temperature=True)
    by_nr = {}
    for item in data["bewertungen"]:
        if isinstance(item, dict) and isinstance(item.get("nr"), int):
            by_nr[item["nr"]] = item
    out = []
    for i, p in enumerate(plans, 1):
        item = by_nr.get(i, {})

        def num(key, default=5.0):
            try:
                return max(0.0, min(10.0, float(item.get(key, default))))
            except (TypeError, ValueError):
                return default

        hard = hard_checks(conn, p)
        canon = max(0.0, num("kanonpassung") - 3 * len(hard))
        out.append({"nr": i, "titel": p.get("titel", ""), "abweichung": p.get("abweichung", 0), "idee": p.get("idee", ""),
                    "kanonpassung": round(canon, 1), "ueberraschung": round(num("ueberraschung"), 1),
                    "fair": bool(item.get("fair", True)),
                    "widersprueche": [str(w) for w in item.get("widersprueche") or []][:6] + [f"Code: {h}" for h in hard],
                    "begruendung": str(item.get("begruendung", ""))[:400]})
    return out


def choose(ratings: list, target: float, min_canon: float, level: int) -> tuple:
    """(Nummer, Begründung) des besten Szenarios."""
    fit = [r for r in ratings if r["kanonpassung"] >= min_canon and (r["fair"] or level < 2)]
    if not fit:
        best = max(ratings, key=lambda r: r["kanonpassung"])
        return best["nr"], (f"Kein Szenario erreicht die Mindest-Kanonpassung {min_canon:g} – genommen wird das "
                            f"passendste (Kanon {best['kanonpassung']:g}).")
    best = min(fit, key=lambda r: (abs(r["ueberraschung"] - target), -r["kanonpassung"]))
    return best["nr"], (f"Kanon {best['kanonpassung']:g} ≥ {min_canon:g}, Überraschung {best['ueberraschung']:g} "
                        f"liegt am nächsten am Ziel {target:g}.")


# ---------------------------------------------------------------- Speichern und Auswählen

def store(conn, run, p: dict, expected: dict, plans: list, ratings: list, chosen: int | None, reason: str) -> int:
    cur = conn.execute(
        "INSERT INTO scenario_sets (run_id, status, params, erwartung, szenarien, bewertungen, gewaehlt) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (run.id, "gewaehlt" if chosen else "offen", json.dumps(dict(p, begruendung=reason, form=getattr(run, "form", "folge")), ensure_ascii=False),
         json.dumps(expected, ensure_ascii=False), json.dumps(plans, ensure_ascii=False),
         json.dumps(ratings, ensure_ascii=False), chosen))
    conn.commit()
    return cur.lastrowid


def get_set(conn, set_id: int, reveal: bool = False) -> dict:
    row = conn.execute("SELECT * FROM scenario_sets WHERE id = ?", (set_id,)).fetchone()
    if row is None:
        raise LookupError("Szenarien nicht gefunden.")
    out = dict(row)
    for key in ("params", "erwartung", "szenarien", "bewertungen"):
        out[key] = json.loads(out[key]) if out.get(key) else None
    if not reveal:  # Pläne können Wendungen und Backstage verraten – ohne Backstage nur Titel, Idee und Werte
        out["szenarien"] = [{"titel": p.get("titel"), "idee": p.get("idee", ""), "abweichung": p.get("abweichung")}
                            for p in out["szenarien"] or []]
        for r in out["bewertungen"] or []:
            r.pop("widersprueche", None)
            r.pop("begruendung", None)
    return out


def open_sets(conn, reveal: bool = False) -> list:
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM scenario_sets WHERE status = 'offen' ORDER BY id DESC")]
    except sqlite3.OperationalError:
        return []
    return [get_set(conn, i, reveal) for i in ids]


def reject_set(conn, set_id: int) -> None:
    conn.execute("UPDATE scenario_sets SET status = 'verworfen' WHERE id = ? AND status = 'offen'", (set_id,))
    conn.commit()


def take(conn, set_id: int, nr: int) -> dict:
    s = get_set(conn, set_id, reveal=True)
    if s["status"] != "offen":
        raise service.ValidationError("Diese Szenarien wurden schon entschieden.")
    plans = s["szenarien"] or []
    if not 1 <= nr <= len(plans):
        raise service.ValidationError("Unbekanntes Szenario.")
    conn.execute("UPDATE scenario_sets SET status = 'gewaehlt', gewaehlt = ? WHERE id = ?", (nr, set_id))
    conn.commit()
    return plans[nr - 1]


def run_flow(conn, run, wish: str, thread_id: int | None, words: int, p: dict) -> tuple:
    """Erwartung → Szenarien → Bewertung → Auswahl. Gibt (Plan oder None, scenario_set_id) zurück."""
    expected = expectation(conn, run, thread_id, wish)
    levels = spread(p["abweichung"], p["szenarien"])
    plans = plan_scenarios(conn, run, wish, thread_id, words, levels, expected)
    if not plans:
        raise episodes.EpisodeError("Kein gültiges Szenario.")
    try:
        ratings = evaluate(conn, run, expected, plans)
    except (episodes.EpisodeError, llm.LLMError) as exc:
        run.step(f"Bewerter übersprungen: {exc} – Szenario mit der gewählten Stufe wird genommen", None, "warnung")
        episodes._ev(run, "szenario", "warnung", "Bewerter fehlgeschlagen – Szenario nach Stufe statt nach Bewertung",
                     ausgang="warnung", ergebnis={"grund": str(exc)})
        ratings = [{"nr": i, "titel": pl.get("titel", ""), "abweichung": pl.get("abweichung", 0), "idee": pl.get("idee", ""),
                    "kanonpassung": None, "ueberraschung": None, "fair": True, "widersprueche": [], "begruendung": ""}
                   for i, pl in enumerate(plans, 1)]
        if p["wahl"] == "ich":
            return None, store(conn, run, p, expected, plans, ratings, None, "Bewerter fehlgeschlagen – wartet auf deine Wahl")
        nr = next((r["nr"] for r in ratings if r["abweichung"] == p["abweichung"]), 1)
        sid = store(conn, run, p, expected, plans, ratings, nr, "Bewerter fehlgeschlagen")
        return plans[nr - 1], sid
    call = getattr(run, "last_call_id", None)
    rule = (f"Kommt in Frage: Kanon ≥ {p['min_kanon']:g}" + (" und fair" if p["abweichung"] >= 2 else "")
            + f"; davon gewinnt die Überraschung am nächsten am Ziel {p['ziel']:g}. "
              "Jede harte Code-Prüfung (z. B. tote Figur, Zeit vor dem Strang-Cursor) zieht 3 Kanon-Punkte ab.")
    for r in ratings:
        run.step(f"Szenario {r['nr']} „{r['titel']}“: Kanon {r['kanonpassung']:g}, Überraschung {r['ueberraschung']:g}"
                 f"{'' if r['fair'] else ', unfair'}", None, "info")
        fits = r["kanonpassung"] >= p["min_kanon"] and (r["fair"] or p["abweichung"] < 2)
        episodes._ev(run, "szenario", "bewertung",
                     f"Szenario {r['nr']} „{r['titel']}“: Kanon {r['kanonpassung']:g}, Überraschung {r['ueberraschung']:g}"
                     + ("" if r["fair"] else ", unfair") + ("" if fits else " – fällt durch"),
                     regel=rule, ausgang="ok" if fits else "warnung", call_id=call, backstage=True,
                     eingaben={"stufe": r["abweichung"], "idee": r["idee"]},
                     ergebnis={k: r[k] for k in ("kanonpassung", "ueberraschung", "fair", "widersprueche", "begruendung")})
    if p["wahl"] == "ich":
        sid = store(conn, run, p, expected, plans, ratings, None, "wartet auf deine Wahl")
        return None, sid
    nr, reason = choose(ratings, p["ziel"], p["min_kanon"], p["abweichung"])
    run.step(f"Gewählt: Szenario {nr} – {reason}", 14, "ok")
    episodes._ev(run, "szenario", "entscheidung", f"Automatisch gewählt: Szenario {nr} „{plans[nr - 1].get('titel', '')}“",
                 regel=rule, ausgang="ok", ergebnis={"gewaehlt": nr, "begruendung": reason})
    sid = store(conn, run, p, expected, plans, ratings, nr, reason)
    return plans[nr - 1], sid
