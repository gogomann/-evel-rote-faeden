"""Folgen-Pipeline: Planer → Autor (kapitelweise) → Kontinuitätsprüfer → Lektor → Archivar.

Textformat der Folgen (wie im Audiobook Studio): jeder Absatz beginnt mit dem Sprecher in eckigen Klammern,
z. B. „[Erzähler] Der Morgen …“ oder „[Tavi] Wir müssen los.“ – daraus entstehen die Segmente fürs Hörbuch.

Fehler bleiben lokal: Scheitern Prüfer, Lektor oder Archivar, wird die Folge trotzdem gespeichert (mit Hinweis).
Scheitert der Autor mittendrin, wird der bisherige Text als Entwurf gesichert.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time

from . import genres, kontext, llm, pdf, profiles, providers, quality, retrieval, runs, service, timeline

NARRATOR = "Erzähler"
TYPES = ("gegenwart", "rueckblende", "vorausblick", "parallel")
WORDS_PER_MINUTE = 135
CHAPTER_WORDS = 1600
SEGMENT_RE = re.compile(r"^\s*\[([^\]\n]{1,60})\]\s*(.*)$")


class EpisodeError(RuntimeError):
    pass


# ---------------------------------------------------------------- Textformat

def parse_segments(text: str) -> list:
    segments = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        match = SEGMENT_RE.match(line)
        if match:
            speaker = match.group(1).strip()
            segments.append({"typ": "narrator" if speaker.lower() in ("erzähler", "erzaehler", "erzählerin") else "character",
                             "sprecher": speaker, "text": match.group(2).strip()})
        elif segments:
            segments[-1]["text"] = (segments[-1]["text"] + " " + line).strip()
        else:
            segments.append({"typ": "narrator", "sprecher": NARRATOR, "text": line})
    return [s for s in segments if s["text"]]


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", SEGMENT_RE.sub(r"\2", text or "")))


def normalize(text: str) -> str:
    """Codeblöcke entfernen und jeden Absatz mit Sprecher versehen."""
    text = re.sub(r"^```[a-z]*\s*|```\s*$", "", (text or "").strip(), flags=re.M)
    return "\n\n".join(f"[{s['sprecher']}] {s['text']}" for s in parse_segments(text))


# ---------------------------------------------------------------- Kontext

def _episode_history(conn: sqlite3.Connection, limit: int = 4) -> list:
    rows = conn.execute(
        "SELECT e.id, e.release_nr, e.title, e.type, e.world_start, e.world_end, e.summary, e.end_handoff, "
        "t.title AS strang FROM episodes e LEFT JOIN threads t ON t.id = e.thread_id "
        "WHERE e.status = 'fertig' ORDER BY e.release_nr DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in reversed(rows)]


def _cascade(run) -> bool:
    return getattr(run, "kontext", "voll") == "kaskade"


def _context_cascade(conn: sqlite3.Connection, ids: dict, until: float | None = None, index: bool = False,
                     overview: bool = False) -> str:
    """Gezielter Kontext (Kaskade): nur die Beteiligten samt Umfeld statt des ganzen Kanons."""
    world = service.meta(conn)
    history = json.dumps(_episode_history(conn), ensure_ascii=False, separators=(",", ":"))
    parts = [f"WELT: {world.get('name', '')}\n{world.get('beschreibung', '')}",
             f"PROJEKTDOKUMENTE:\n{llm._read_context_docs()}"]
    if overview:
        parts.append("ÜBERBLICK ÜBER DIE WELT (kompakt):\n" + kontext.text_overview(conn))
    parts.append("KANON DER BETEILIGTEN (JSON, inkl. backstage – Geheimnisse nicht ausplaudern):\n"
                 + kontext.text_focus(conn, ids, until))
    if index:
        parts.append("NAMENSVERZEICHNIS ALLER DATENSÄTZE ([id, Name] je Bereich – nichts doppelt anlegen, "
                     "Bestehendes per id ergänzen):\n" + kontext.text_index(conn))
    parts.append(f"LETZTE FOLGEN (älteste zuerst):\n{history}")
    return "\n\n".join(parts)


def _context(conn: sqlite3.Connection) -> str:
    world = service.meta(conn)
    canon = json.dumps(service.canon_snapshot(conn), ensure_ascii=False, separators=(",", ":"))
    history = json.dumps(_episode_history(conn), ensure_ascii=False, separators=(",", ":"))
    snippets = [dict(r) for r in conn.execute("SELECT id, title, content, kind, thread_id FROM snippets WHERE status = 'offen'")]
    return (f"WELT: {world.get('name', '')}\n{world.get('beschreibung', '')}\n\n"
            f"PROJEKTDOKUMENTE:\n{llm._read_context_docs()}\n\n"
            f"KANON (JSON, inkl. backstage – Geheimnisse nicht ausplaudern):\n{canon}\n\n"
            f"LETZTE FOLGEN (älteste zuerst):\n{history}\n\n"
            f"OFFENE EINSCHÜBE (Sammelsurium, frei verwendbar):\n{json.dumps(snippets, ensure_ascii=False)}")


STYLE = """Ziel: eine fortlaufende Sci-Fi-Hörbuchreihe auf Deutsch, die abends zum Einschlafen gehört wird (ERZAEHLREGELN.md).
Für Erwachsene, grundsätzlich hoffnungsvoll, an Star Trek angelehnt; keine reinen Bösewichte.
Zeit wird nie als Tageszahl genannt, sondern über Kalender- und Zyklusnamen (WELT_REGELN.md).
Wissen ohne normale Erreichbarkeit braucht eine Quelle. Geheimnisse und Rätselwahrheiten werden nicht verraten,
höchstens angedeutet, wie es der Plan vorsieht. Der Erzähler ist ehrlich: Er lügt den Hörer nicht an."""


# Vorgabe des Nutzers (2026-11-10, ERZAEHLREGELN.md „Dramaturgie“): jede Folge hat Anfang, Mitte, Ende –
# und der Anfang holt den Hörer emotional ab.
DRAMATURGY = """DRAMATURGIE (verbindlich für jede Folge, auch für Fortsetzungen): Anfang, Mitte, Ende.
- ANFANG – den Hörer abholen: Die ersten Absätze gehören EINER Figur, mit der man mitfühlen kann. Sofort klar:
  Name, Alter oder Lebensphase, was sie ist oder tut, wie es ihr gerade geht (ein deutliches Gefühl), warum (ihre Lage
  in diesem Moment) und wo sie ist (ein, zwei sinnliche Details). Nah und persönlich, z. B. „Iva ist dreiundzwanzig und
  genervt.“ – dann, was passiert ist und wo sie steht. Erst danach Welt, Technik und Hintergrund, und nur so viel, wie
  die Szene braucht. Nicht mitten in einer Beschreibung einsteigen, kein Panorama oder Lexikon-Ton als Eröffnung.
  Fortsetzungen verankern kurz neu, wer wir sind und wo wir stehen, bevor es weitergeht.
- MITTE – die Geschichte: Die Figur will etwas oder hat ein Problem; Hindernisse, Begegnungen, Entscheidungen.
  Gefühle zeigen statt behaupten, Dialoge mit Subtext, Welt und Wissen durch Handlung vermitteln.
- ENDE – abrunden: Der Bogen dieser Folge kommt zu einem spürbaren Ruhepunkt (zum Einschlafen geeignet); die Figur
  hat etwas erlebt, gewonnen oder erkannt. Erst danach die Überleitung zur nächsten Folge."""


def _style(run) -> str:
    """Grundstil + Dramaturgie + Genre-Regeln + Erzählprofil des Menschen, der gerade bedient (+ Abweichungsstufe)."""
    parts = [STYLE, DRAMATURGY]
    level = _deviation(run)
    if level >= 2:
        parts[0] = STYLE.replace("Der Erzähler ist ehrlich: Er lügt den Hörer nicht an.",
                                 "Der Erzähler darf den Hörer in die Irre führen, aber nie betrügen: Jede Täuschung muss "
                                 "fair angelegt sein und sich auflösen lassen.")
        if getattr(run, "genre_rules", "") and "Horror" in run.genre_rules.splitlines()[0]:
            parts[0] = parts[0].replace("grundsätzlich hoffnungsvoll, an Star Trek angelehnt; keine reinen Bösewichte",
                                        "der Ton folgt dem Genre; keine reinen Bösewichte ohne Motiv")
    if level and DEVIATION.get(level):
        parts.append(DEVIATION[level])
    if getattr(run, "genre_rules", ""):
        parts.append(run.genre_rules + "\nDas Genre legt sich über die Welt: Weltregeln gelten weiter.")
    if getattr(run, "age_rating", ""):
        parts.append(f"ALTERSFREIGABE (vom Autor festgelegt, gilt vor der Genre-Vorgabe): {run.age_rating} – "
                     "Inhalte, Härte und Wortwahl daran ausrichten.")
    if getattr(run, "voice", ""):
        parts.append(run.voice)
    return "\n\n".join(parts)


# Abweichung von der Vorgabe: 0 eng · 1 Nebenwege · 2 Wendung · 3 Bruch mit der Erwartung (PLAN.md, Szenarien)
DEVIATION = {
    0: "",
    1: "ABWEICHUNG Stufe 1 (Nebenwege): Du darfst vom Naheliegenden abweichen – Nebenfiguren, Umwege, ein unerwarteter Ort –, "
       "solange die Hauptlinie erkennbar bleibt.",
    2: "ABWEICHUNG Stufe 2 (Wendung): Baue eine echte Wendung ein, die der Hörer nicht kommen sieht. Sie muss fair sein: "
       "vorher angelegt oder rückblickend erklärbar, nie gegen den Kanon. Ein Erzähler darf den Hörer in die Irre führen, "
       "wenn es sich später auflöst.",
    3: "ABWEICHUNG Stufe 3 (Bruch): Brich bewusst mit dem, was der Hörer erwartet – die sichere Seite ist nicht sicher. "
       "Fair bleiben: rückblickend muss alles zum Kanon passen; Täuschung ist erlaubt, Betrug am Hörer nicht. "
       "Ein harter Bruch zur vorigen Folge ist erlaubt.",
}
SURPRISE_TARGET = {0: 2.0, 1: 4.0, 2: 6.5, 3: 8.5}


def _deviation(run) -> int:
    try:
        return max(0, min(3, int(getattr(run, "abweichung", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def _deviation_check_note(run, plan: dict) -> str:
    level = max(_deviation(run), int(plan.get("abweichung") or 0) if str(plan.get("abweichung") or "0").isdigit() else 0)
    if level < 2:
        return ""
    turn = plan.get("wendung") or ""
    return (f"\n\nABWEICHUNG Stufe {level} ist gewollt{f' (Wendung: {turn})' if turn else ''}: Eine Täuschung des Erzählers "
            "ist erlaubt, wenn sie fair angelegt ist und sich auflösen lässt – dann NICHT als Erzähler-Problem melden. "
            "Ein bewusster Bruch zur vorigen Folge ist erlaubt. Widersprüche zum Kanon bleiben Fehler; melde eine Wendung, "
            "die rückblickend nicht erklärbar ist, als „mittel“ mit Beschreibung „Unfaire Wendung: …“.")


# ---------------------------------------------------------------- KI-Aufrufe

def _ask(run: runs.Run, messages: list, task: str, json_mode: bool, low: int, high: int, expected_chars: int,
         label: str, max_tokens: int = 8000, chain: list | None = None, temperature: float | None = None,
         fixed_temperature: bool = False) -> str:
    run.set_range(low, high, expected_chars, label)

    def log(text, level="info"):
        if level == "info":
            run.reset_text()
        run.step(f"{label}: {text}", low if level == "info" else None, level)

    if chain is None:
        chain = getattr(run, "chains", {}).get(task)  # Prüfstand/Vergleich: festes Modell
    try:
        text, used = providers.complete(messages, task, json_mode=json_mode, max_tokens=max_tokens,
                                        log=log, on_chunk=run.chunk, chain=chain, record=run.recorder(label, task),
                                        temperature=temperature, fixed_temperature=fixed_temperature)
    except providers.ProviderError as exc:
        raise EpisodeError(f"{label}: {exc}")
    run.model_used = used
    run.models.setdefault(task, used)
    if task in ("thema", "planer", "autor", "pruefer", "archivar", "bewerter", "erwartung"):
        quality.note(run, "kontext", task, used, sum(len(str(m.get("content", ""))) for m in messages),
                     {"schritt": label})
    return text


def _ask_json(run, messages, task, low, high, expected, label, validate, chain=None, **kw) -> dict:
    """JSON-Antwort mit einer Korrekturrunde. Wie es lief, landet in der Qualitätsmessung (Format-Treue)."""
    text = _ask(run, messages, task, True, low, high, expected, label, chain=chain, **kw)
    try:
        data = llm._extract_json(text)
        errors = validate(data)
    except llm.LLMError as exc:
        data, errors = None, [str(exc)]
    if errors:
        first_model = run.model_used
        run.step(f"{label}: Antwort unvollständig ({'; '.join(errors)}) → Korrekturrunde", None, "warnung")
        messages = messages + [{"role": "assistant", "content": text},
                               {"role": "user", "content": "Fehler: " + "; ".join(errors)
                                + "\nAntworte erneut, nur mit dem korrigierten JSON-Objekt."}]
        text = _ask(run, messages, task, True, low, high, expected, label, chain=chain, **kw)
        try:
            data = llm._extract_json(text)
            errors = validate(data)
        except llm.LLMError as exc:
            data, errors = None, [str(exc)]
        if errors:
            run.set_response(text, run.model_used or "")  # Rohantwort bleibt für die Fehlersuche erhalten
            _note_format(run, task, label, first_model, 0.0)
            raise EpisodeError(f"{label}: {'; '.join(errors)}")
        _note_format(run, task, label, first_model, 0.5)
        return data
    _note_format(run, task, label, run.model_used, 1.0)
    return data


def _note_format(run, task: str, label: str, model: str | None, value: float) -> None:
    """Format-Treue: 1 = sofort gültig, 0,5 = nach Korrektur, 0 = gescheitert."""
    quality.note(run, "format", task, model, value, {"schritt": label})


# ---------------------------------------------------------------- 1. Planer

PLANNER_PROMPT = """Du bist der Planer einer fortlaufenden Hörbuchreihe. Plane die NÄCHSTE Folge.
{style}

Regeln:
- Fortlaufende Zeitleiste (Master-Weltzeit als Zahl). Die Folge darf in der Gegenwart, als Rückblende, als Vorausblick
  oder parallel zu einer früheren Folge spielen; eine Folge darf dieselbe Geschichte aus anderem Blickwinkel erzählen.
- Vergangenheit ist kanon-gesperrt: ergänzen ja, widersprechen nein.
- Nutze vorhandene Stränge und Figuren. Fehlt etwas (z. B. noch gar keine Figuren oder Stränge), lege es unter
  "vorbereitung" an – im selben Format wie Vorschläge des Weltenbauers (nur "anlegen" oder leere Felder "ergaenzen").
- Passiert zu wenig, streue Einschübe aus dem Sammelsurium ein (ihre ids unter "einschuebe").
- Kapitel: {kapitel} Kapitel mit zusammen etwa {woerter} Wörtern. Jedes Kapitel gehört zu "anfang", "mitte" oder "ende"
  (bei nur einem Kapitel: "ganz" – es enthält alle drei Teile).
- Plane den EINSTIEG ausdrücklich (Feld "einstieg"): wessen Moment, wer sie ist, welches Gefühl, welche Lage, welcher Ort.
- Ende: Der Bogen dieser Folge wird abgerundet ("ende_abschluss"), danach leitet die Folge zur nächsten über.
- Vorgaben des Hörers für ANFANG, MITTE oder ENDE sind verbindlich und gehören in "einstieg", "kapitel" bzw. "ende_abschluss".

Antworte NUR mit JSON:
{{
  "titel": "Titel der Folge",
  "strang": {{"id": <bestehende id>}} oder {{"ref": "<kurzname eines in vorbereitung angelegten Strangs>"}},
  "typ": "gegenwart|rueckblende|vorausblick|parallel",
  "perspektive_von_folge": null oder <id einer früheren Folge, falls dieselbe Geschichte aus anderem Blickwinkel>,
  "welt_start": <Zahl>, "welt_ende": <Zahl>,
  "figuren": [{{"id": <id>}} oder {{"ref": "<kurzname>"}}],
  "einstieg": {{"figur": "Name der Figur, mit der die Folge beginnt", "wer": "Alter/Lebensphase und was sie ist oder tut",
               "gefuehl": "wie es ihr in diesem Moment geht", "lage": "warum – was gerade passiert ist",
               "ort": "wo sie ist, 1–2 sinnliche Details", "erster_satz": "Vorschlag für den ersten Satz"}},
  "kapitel": [{{"teil": "anfang|mitte|ende|ganz", "titel": "...", "inhalt": "Was passiert, 3–6 Sätze", "woerter": <Zahl>}}],
  "einschuebe": [<ids>],
  "andeutungen": "Welche Hinweise/Codes gesät werden (wird nicht gezeigt)",
  "ende_abschluss": "Womit der Bogen dieser Folge zur Ruhe kommt (was die Figur erlebt oder erkannt hat)",
  "ende_uebergabe": "Wie die Folge endet und in die nächste überleitet",
  "ripples_erledigt": [<ids fälliger Ripples, die diese Folge aufgreift>],
  "genre_id": <id des Genres oder null>,
  "vorbereitung": [<Operationen im Format unten, sonst leere Liste>]
}}
FORMAT jeder Operation in "vorbereitung" (Schlüssel exakt so, deutsch):
  {{"aktion": "anlegen", "tabelle": "<tabelle>", "ref": "<kurzname>", "sichtbarkeit": "offen|backstage",
    "felder": {{"<spalte>": "<wert>"}}}}
  {{"aktion": "ergaenzen", "tabelle": "<tabelle>", "id": <bestehende id>, "felder": {{"<leere spalte>": "<wert>"}}}}
Beispiel neuer Strang: {{"aktion": "anlegen", "tabelle": "threads", "ref": "neuer_strang",
  "felder": {{"title": "...", "level": "mikro", "world_time_cursor": <Zahl>}}}} – dazu "strang": {{"ref": "neuer_strang"}}.
Verweise in "felder" auf hier angelegte Datensätze per "@kurzname" (vorher anlegen), auf bestehende per numerischer id.
Erlaubte Tabellen und Spalten für "vorbereitung":
"""


def _validate_plan(plan: dict) -> list:
    errors = []
    if not isinstance(plan, dict):
        return ["kein JSON-Objekt"]
    if not isinstance(plan.get("kapitel"), list) or not plan["kapitel"]:
        errors.append("kapitel fehlt")
    strang = plan.get("strang")
    if not isinstance(strang, dict) or not (isinstance(strang.get("id"), int) or strang.get("ref")):
        errors.append("strang braucht id oder ref")
    if plan.get("typ") not in TYPES:
        errors.append(f"typ muss eins von {', '.join(TYPES)} sein")
    try:
        if float(plan.get("welt_ende")) < float(plan.get("welt_start")):
            errors.append("welt_ende liegt vor welt_start")
    except (TypeError, ValueError):
        errors.append("welt_start/welt_ende müssen Zahlen sein")
    entry = plan.get("einstieg")
    missing = [k for k in ("figur", "gefuehl", "lage") if not isinstance(entry, dict) or not str(entry.get(k) or "").strip()]
    if missing:
        errors.append("einstieg braucht figur, gefuehl und lage (wer, wie es ihr geht, warum)")
    prep = plan.get("vorbereitung") or []
    if prep:
        errors += service.validate_payload({"operationen": prep})
    refs = {str(op.get("ref")) for op in prep if isinstance(op, dict) and op.get("ref")}
    if isinstance(strang, dict) and strang.get("ref") and str(strang["ref"]) not in refs:
        errors.append(f"strang-ref {strang['ref']} wird in vorbereitung nicht angelegt")
    return errors


def _plan_errors(conn, plan) -> list:
    """Ist der Plan ausführbar? Prüft den Strang gegen die Datenbank und spielt die Vorbereitung probeweise durch
    (wird zurückgenommen). Fehler gehen in die Korrekturrunde des Planers – so fällt es vor dem Speichern auf."""
    if not isinstance(plan, dict):
        return []
    strang = plan.get("strang") if isinstance(plan.get("strang"), dict) else {}
    if isinstance(strang.get("id"), int):
        if not conn.execute("SELECT 1 FROM threads WHERE id = ?", (strang["id"],)).fetchone():
            return [f"strang id {strang['id']} existiert nicht – bestehende id nehmen oder neuen Strang mit ref anlegen"]
        return []
    prep = plan.get("vorbereitung") or []
    if not prep or not strang.get("ref"):
        return []
    report = service.check_operations(conn, prep)
    reason = report["fehler_refs"].get(str(strang["ref"]))
    if reason:
        return [f"Strang (ref {strang['ref']}) ließe sich nicht anlegen: {reason}"]
    if str(strang["ref"]) not in report["refs"]:
        return [f"Strang (ref {strang['ref']}) ließe sich nicht anlegen: " + " ".join(report["hinweise"])]
    return []


def plan_check(conn, plan) -> list:
    """Form und Ausführbarkeit eines Plans (auch für Szenarien)."""
    return _validate_plan(plan) or _plan_errors(conn, plan)


class PlanBroken(EpisodeError):
    """Vorbereitung lief, aber der Strang fehlt danach – Vorbereitung wurde zurückgenommen."""


def _planning_notes(conn) -> str:
    """Was der Planer zusätzlich wissen muss: fällige Ripples, lange offene Rätsel, Konsistenzprobleme, Kalender."""
    lines = []
    for t in conn.execute("SELECT id, title, world_time_cursor FROM threads WHERE status IS NULL OR status != 'beendet'"):
        for r in conn.execute("SELECT id, effect, earliest_world_time FROM ripples WHERE target_thread_id = ? AND done = 0 "
                              "AND earliest_world_time <= ?", (t[0], t[2] or 0)):
            lines.append(f"- Fälliger Ripple #{r[0]} für Strang #{t[0]} „{t[1]}“ (ab Weltzeit {r[2]:g}): {r[1]}")
    released = conn.execute("SELECT COALESCE(MAX(release_nr), 0) FROM episodes").fetchone()[0]
    for m in conn.execute("SELECT m.id, m.description, m.status, m.max_episodes, e.release_nr FROM mysteries m "
                          "LEFT JOIN episodes e ON e.id = m.seed_episode_id WHERE m.status != 'aufgeloest'"):
        if m[3] and m[4] and released - m[4] >= m[3]:
            lines.append(f"- Rätsel #{m[0]} ist seit {released - m[4]} Folgen offen (Grenze {m[3]}): andeuten oder auflösen.")
    issues = timeline.check(conn, reveal=True)["probleme"]
    for i in issues[:10]:
        lines.append(f"- Konsistenzproblem ({i['art']}): {i['figur']} {i['text']} – nicht verschärfen, wenn möglich auflösen.")
    cursor = conn.execute("SELECT MAX(world_time_cursor) FROM threads").fetchone()[0]
    if cursor is not None:
        for cal in timeline.format_all(conn, cursor, reveal=True):
            if cal["text"]:
                lines.append(f"- Kalender {cal['kalender']} bei Weltzeit {cursor:g}: {cal['text']}")
    return "\n".join(lines) or "- keine"


THEMA_PROMPT = """Du bist der Themenplaner (erste Ebene) einer fortlaufenden Hörbuchreihe. Du siehst nur einen kompakten
Überblick über die Welt und entscheidest: welcher Strang, welches Thema, welche Richtung – und wer bzw. was beteiligt ist.
Die Feinplanung macht danach der Planer mit den vollständigen Datensätzen der Beteiligten.
{style}

Antworte NUR mit JSON:
{{
  "strang": {{"id": <bestehende id>}} oder {{"neu": "Arbeitstitel eines neuen Strangs"}},
  "thema": "Worum es in der Folge geht, 1–2 Sätze",
  "richtung": "Ton und Konfliktlinie (wer mit oder gegen wen, hell oder dunkel, ruhig oder angespannt)",
  "beteiligte": {{"characters": [ids], "locations": [ids], "peoples": [ids], "technologies": [ids],
                 "organizations": [ids], "events": [ids], "snippets": [ids]}}
}}
Nur ids aus dem Überblick verwenden. Lieber wenige, passende Beteiligte als viele."""


def _validate_theme(data) -> list:
    if not isinstance(data, dict):
        return ["kein JSON-Objekt"]
    errors = []
    if not isinstance(data.get("beteiligte"), dict):
        errors.append("beteiligte fehlt")
    strang = data.get("strang")
    if not isinstance(strang, dict) or not (isinstance(strang.get("id"), int) or strang.get("neu")):
        errors.append("strang braucht id oder neu")
    return errors


def _theme(conn, run, task: str, chain=None) -> dict:
    """Ebene 1 der Kaskade: Thema und Beteiligte aus dem kompakten Überblick."""
    world = service.meta(conn)
    messages = [{"role": "system", "content": THEMA_PROMPT.format(style=_style(run))},
                {"role": "user", "content": f"WELT: {world.get('name', '')}\n{world.get('beschreibung', '')}\n\n"
                 f"ÜBERBLICK:\n{kontext.text_overview(conn)}\n\nLETZTE FOLGEN:\n"
                 f"{json.dumps(_episode_history(conn), ensure_ascii=False)}\n\nHINWEISE FÜR DIE PLANUNG:\n"
                 f"{_planning_notes(conn)}\n\nAUFTRAG:\n{task}"}]
    data = _ask_json(run, messages, "thema", 4, 6, 1500, "Thema (Kaskade)", _validate_theme, chain=chain)
    run.step(f"Thema: {str(data.get('thema', ''))[:120]}", 6, "ok")
    return data


def _plan_task(conn, run, wish: str, thread_id: int | None) -> str:
    task = "Plane die nächste Folge."
    if thread_id:
        task += f" Sie soll im Strang mit id {thread_id} spielen."
    if not getattr(run, "genre_rules", ""):
        options = "; ".join(f"{r[0]}: {r[1]} ({r[2] or '–'})" for r in conn.execute("SELECT id, name, age_rating FROM genres"))
        if options:
            task += (f"\nWähle ein passendes Genre (Feld \"genre_id\") aus: {options}. Berücksichtige Strang, Wunsch, "
                     "Publikum und Lieblingsgenres aus dem Erzählprofil.")
    if wish.strip():
        task += f"\nWunsch des Hörers (frei, keine feste Regel): {wish.strip()}"
        memory = retrieval.search(conn, wish, reveal=True, limit=6)
        if memory:
            task += "\nPassende ältere Folgen/Fakten:\n" + "\n".join(f"- {m['titel']}: {m['auszug']}" for m in memory)
    return task


def _plan_messages(conn, run, wish: str, thread_id: int | None, words: int, chain=None, extra: str = "",
                   system_extra: str = "") -> list:
    chapters = max(1, round(words / CHAPTER_WORDS))
    system = (PLANNER_PROMPT.format(style=_style(run), kapitel=chapters, woerter=words) + llm._schema_description()
              + system_extra)
    task = _plan_task(conn, run, wish, thread_id) + extra
    context = None
    if _cascade(run):
        try:
            theme = _theme(conn, run, task)
            ids = kontext.merge_ids(theme.get("beteiligte") or {})
            strang = theme.get("strang") or {}
            if isinstance(strang.get("id"), int):
                ids.setdefault("threads", []).append(strang["id"])
            elif strang.get("neu"):
                task += f"\nEs soll ein NEUER Strang beginnen (Arbeitstitel: {strang['neu']}) – lege ihn unter vorbereitung an."
            task += (f"\nTHEMA (erste Ebene): {theme.get('thema', '')}\nRICHTUNG: {theme.get('richtung', '')}")
            run.theme = theme
            context = _context_cascade(conn, ids)
        except (EpisodeError, llm.LLMError) as exc:
            run.step(f"Kaskade: Themenwahl gescheitert ({exc}) – Planer bekommt den vollen Kontext", None, "warnung")
    if context is None:
        context = _context(conn)
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": context + "\n\nHINWEISE FÜR DIE PLANUNG:\n" + _planning_notes(conn)
                 + "\n\nAUFTRAG:\n" + task}]
    run.set_prompt(messages)
    cascaded = "KANON DER BETEILIGTEN" in context
    run.step(f"Planer: Kontext fertig ({len(messages[1]['content']):,} Zeichen)".replace(",", ".")
             + (" · Kaskade" if cascaded else ""), 4)
    return messages


def _plan(conn, run, wish: str, thread_id: int | None, words: int, chain=None, extra_task: str = "") -> dict:
    extra = ""
    if _deviation(run) >= 2:
        extra = ('\nZusätzlich im JSON: "wendung": "die geplante Überraschung in einem Satz (wird nicht gezeigt)", '
                 f'"abweichung": {_deviation(run)}')
    messages = _plan_messages(conn, run, wish, thread_id, words, chain, extra=extra_task, system_extra=extra)
    return _ask_json(run, messages, "planer", 5, 12, 4000, "Planer", lambda d: plan_check(conn, d), chain=chain)


def _apply_preparation(conn, run, plan: dict) -> tuple:
    """Legt an, was der Plan braucht (neue Figuren, Orte, Stränge …) und löst den Strang auf. Gibt (ref → id, Strang-id)
    zurück. Fehlt der Strang danach, wird die ganze Vorbereitung zurückgenommen (keine verwaisten Datensätze)."""
    ops = plan.get("vorbereitung") or []
    if not ops:
        thread = _resolve(plan["strang"], {}, "threads", conn)
        if not thread:
            raise PlanBroken("Strang existiert nicht und der Plan legt keinen an")
        return {}, thread
    payload = {"zusammenfassung": "Vorbereitung für die Folge „{}“".format(plan.get("titel", "")), "operationen": ops}
    pid = service.store_proposal(conn, "Folgenplanung: Vorbereitung", payload, "planer")
    conn.commit()
    conn.execute("SAVEPOINT vorbereitung")
    try:
        report = service.apply_proposal(conn, pid)
    except service.ValidationError as exc:
        report = {"angelegt": 0, "ergaenzt": 0, "fehlgeschlagen": len(ops), "hinweise": [str(exc)], "refs": {}}
    refs = report.get("refs", {})
    thread = _resolve(plan["strang"], refs, "threads", conn)
    if not thread:
        conn.execute("ROLLBACK TO vorbereitung")
        conn.execute("RELEASE vorbereitung")
        conn.execute("UPDATE proposals SET status='verworfen', result=?, decided_at=CURRENT_TIMESTAMP WHERE id=?",
                     (json.dumps(report, ensure_ascii=False), pid))
        conn.commit()
        for hint in report.get("hinweise", []):
            run.step(f"Vorbereitung: {hint}", None, "warnung")
        strang = plan["strang"]
        reason = report.get("fehler_refs", {}).get(str(strang.get("ref"))) if strang.get("ref") else None
        raise PlanBroken(reason or "Strang existiert nicht und wurde nicht angelegt")
    conn.execute("RELEASE vorbereitung")
    conn.commit()
    run.step(f"Vorbereitung übernommen: {report['angelegt']} angelegt, {report['ergaenzt']} ergänzt"
             + (f", {report['fehlgeschlagen']} übersprungen" if report["fehlgeschlagen"] else ""), 14, "ok")
    for hint in report.get("hinweise", []):
        run.step(f"Vorbereitung: {hint}", None, "warnung")
    return refs, thread


def _resolve(entry, refs: dict, table: str, conn) -> int | None:
    if not isinstance(entry, dict):
        return None
    if isinstance(entry.get("id"), int):
        found = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (entry["id"],)).fetchone()
        return found[0] if found else None
    ref = entry.get("ref")
    return refs.get(str(ref)) if ref else None


def _cast(conn, plan: dict, refs: dict) -> list:
    out = []
    for entry in plan.get("figuren") or []:
        cid = _resolve(entry, refs, "characters", conn)
        if cid:
            row = conn.execute("SELECT c.id, c.name, c.role, c.description, p.name AS volk FROM characters c "
                               "LEFT JOIN peoples p ON p.id = c.people_id WHERE c.id = ?", (cid,)).fetchone()
            if row:
                out.append(dict(row))
    return out


# ---------------------------------------------------------------- 2. Autor

AUTHOR_PROMPT = """Du bist der Autor einer fortlaufenden Hörbuchreihe. Schreibe GENAU EIN Kapitel der aktuellen Folge.
{style}

FORMAT (verbindlich): Jeder Absatz beginnt mit dem Sprecher in eckigen Klammern.
[Erzähler] für erzählende Absätze, [Name] für wörtliche Rede einer Figur (nur der gesprochene Satz, ohne „sagte sie“).
Beispiel:
[Erzähler] Über dem Markt von Kesh hing der Staub wie ein zweiter Himmel.
[Tavi] Wir sind zu spät.
[Erzähler] Sie faltete die Flügel enger an den Körper.
Keine Überschriften, keine Listen, keine Kommentare – nur der Kapiteltext."""


def _opening_brief(plan: dict) -> str:
    """Auftrag für die ersten Absätze von Kapitel 1 (aus dem Plan, sonst die allgemeine Regel)."""
    entry = plan.get("einstieg") if isinstance(plan.get("einstieg"), dict) else {}
    labels = (("figur", "Figur"), ("wer", "Wer sie ist"), ("gefuehl", "Gefühl gerade"), ("lage", "Lage / warum"),
              ("ort", "Ort"), ("erster_satz", "Vorschlag erster Satz"))
    details = "\n".join(f"  {label}: {entry[key]}" for key, label in labels if str(entry.get(key) or "").strip())
    return ("EINSTIEG (verbindlich – die ersten Absätze dieses Kapitels holen den Hörer ab, bevor Welt und Hintergrund "
            "kommen):\n" + (details or "  Wähle die Figur, aus deren Moment die Folge beginnt: Name, Alter/Rolle, "
                                        "Gefühl, Lage, Ort."))


def _write_chapter(conn, run, plan, cast, index, previous_text, low, high) -> str:
    chapter = plan["kapitel"][index]
    words = int(chapter.get("woerter") or CHAPTER_WORDS)
    history = _episode_history(conn, 1)
    opening = ""
    if index == 0:
        opening = "\n" + _opening_brief(plan)
        if history and history[-1].get("end_handoff"):
            opening += ("\nDie letzte Folge endete so (nach dem Einstieg inhaltlich aufgreifen, Überlappung erwünscht): "
                        f"{history[-1]['end_handoff']}")
    if index == len(plan["kapitel"]) - 1:
        opening += ("\nDIES IST DAS LETZTE KAPITEL – ENDE: Runde den Bogen dieser Folge spürbar ab"
                    + (f" ({plan['ende_abschluss']})" if plan.get("ende_abschluss") else "")
                    + ", erst danach die Überleitung zur nächsten Folge.")
    outline = "\n".join(f"{i + 1}. [{k.get('teil') or '–'}] {k.get('titel', '')}: {k.get('inhalt', '')}"
                        for i, k in enumerate(plan["kapitel"]))
    when = "; ".join(f"{c['kalender']}: {c['text']}" for c in timeline.format_all(conn, float(plan["welt_start"]), True)
                     if c["text"]) or "keine Kalenderdaten – Zeit nur umschreiben, keine Zahlen nennen"
    memory = retrieval.search(conn, f"{plan.get('titel', '')} {chapter.get('titel', '')} {chapter.get('inhalt', '')}",
                              until=float(plan["welt_start"]), reveal=True, limit=6)
    then = ("\nERINNERUNG (ältere passende Folgen und Fakten, bis zu diesem Zeitpunkt):\n"
            + "\n".join(f"- {m['titel']}: {m['auszug']}" for m in memory)) if memory else ""
    if plan.get("typ") in ("rueckblende", "vorausblick"):
        state = timeline.world_state(conn, float(plan["welt_start"]), reveal=True)
        then += ("\nWELTZUSTAND ZU BEGINN DIESER FOLGE (nur das galt damals; späteres Wissen darf nicht vorkommen):\n"
                + json.dumps({k: state[k] for k in ("figuren", "ereignisse", "beziehungen", "technik")},
                             ensure_ascii=False))
    task = (f"FOLGE: {plan.get('titel', '')} (Typ: {plan.get('typ')}, Weltzeit {plan.get('welt_start')}–{plan.get('welt_ende')})\n"
            f"FIGUREN: {json.dumps(cast, ensure_ascii=False)}\n"
            f"KAPITELPLAN:\n{outline}\n"
            f"ANDEUTUNGEN (nur andeuten, nie auflösen): {plan.get('andeutungen', '')}\n"
            f"ENDE DER FOLGE: {plan.get('ende_uebergabe', '')}\n{opening}\n"
            f"ZEITANGABE FÜR DEN ERZÄHLER: {when}{then}\n\n"
            f"BISHERIGER TEXT (Ende):\n{previous_text[-3000:] if previous_text else '(Beginn der Folge)'}\n\n"
            f"SCHREIBE JETZT Kapitel {index + 1} von {len(plan['kapitel'])}: „{chapter.get('titel', '')}“ – "
            f"{chapter.get('inhalt', '')}\nUmfang: etwa {words} Wörter.")
    if _cascade(run):
        ids = kontext.merge_ids({"characters": [c["id"] for c in cast]},
                                kontext.mentioned(conn, json.dumps(plan, ensure_ascii=False)))
        thread = plan.get("_thread_id")
        if thread:
            ids.setdefault("threads", []).append(thread)
        context = _context_cascade(conn, ids, until=float(plan["welt_start"]))
    else:
        context = _context(conn)
    messages = [{"role": "system", "content": AUTHOR_PROMPT.format(style=_style(run))},
                {"role": "user", "content": context + "\n\n" + task}]
    label = f"Autor, Kapitel {index + 1}/{len(plan['kapitel'])}"
    full = getattr(run, "chains", {}).get("autor") or providers.resolve_chain("autor")
    refused = getattr(run, "refused", None)
    if refused is None:
        refused = run.refused = set()
    for attempt in range(1, max(2, len(full)) + 2):
        chain = [c for c in full if _label(c) not in refused] or full
        text = normalize(_ask(run, messages, "autor", False, low, high, words * 7, label,
                              max_tokens=max(4000, int(words * 2.6)), chain=chain or None))
        refusal = _refusal(text)
        quality.note(run, "verweigerung", "autor", run.model_used, 1.0 if refusal else 0.0, {"schritt": label})
        if word_count(text) >= words * 0.35 and not refusal:
            run.step(f"{label}: {word_count(text):,} Wörter geschrieben".replace(",", "."), high, "ok")
            quality.note(run, "laenge", "autor", run.model_used, round(word_count(text) / max(1, words), 3),
                         {"schritt": label, "ziel": words})
            return text
        used = run.model_used or "?"
        if refusal:
            refused.add(used)
            others = [c for c in full if _label(c) not in refused]
            run.step(f"{label}: {used} verweigert den Inhalt (nicht jedes Modell macht jedes Genre/jede Altersfreigabe mit)"
                     + (f" – nächste Wahl: {_label(others[0])}" if others else " – kein weiteres Modell, neuer Versuch"),
                     None, "warnung")
            if not others and attempt > 1:
                break
        else:
            if attempt >= 2:
                refused.add(used)
            run.step(f"{label}: zu kurz ({word_count(text)} Wörter) – Versuch {attempt + 1}", None, "warnung")
    raise EpisodeError(f"{label}: Text blieb zu kurz oder wurde von allen Modellen verweigert. "
                       "Unter „Modelle je Aufgabe“ für den Autor ein weiteres Modell eintragen.")


REFUSAL = re.compile(r"^\W*(ich kann (dir )?(dabei|das|diese[nsm]?|hier)? ?(leider )?nicht|es tut mir leid|"
                     r"leider kann ich|tut mir leid|ich werde (das|diese[nsm]?) nicht|"
                     r"i(?:'| a)m sorry|i can(?:'|no)t|i won(?:'|)t|as an ai|i(?:'| a)m not able|i am unable)", re.I)


def _refusal(text: str) -> bool:
    """Absage des Modells statt Geschichte (kurz und beginnt mit typischer Formel)."""
    head = (text or "").strip()[:400]
    return bool(head) and word_count(text) < 250 and bool(REFUSAL.search(head.lstrip("[]").split("]", 1)[-1].strip()))


def _label(entry) -> str:
    return f"{entry[0]['name']} · {entry[1]}"


# ---------------------------------------------------------------- 3. Prüfer

CHECK_PROMPT = """Du bist Kontinuitätsprüfer einer fortlaufenden Hörbuchreihe. Prüfe die Folge gegen Kanon, Plan und Regeln:
Widersprüche zum Kanon, Figuren an zwei Orten gleichzeitig, unmögliche Reisezeiten, Wissen ohne Quelle, tote Figuren in der
Gegenwart, verratene Geheimnisse, Tageszahlen statt Kalendernamen, unehrlicher Erzähler (Kategorie „Erzähler“ in der
Beschreibung nennen), fehlende Anknüpfung an die vorige Folge, Formatfehler (Absatz ohne [Sprecher]).
Dramaturgie: Holt Kapitel 1 den Hörer in den ersten Absätzen NICHT ab (keine Figur mit Name, Alter/Rolle, Gefühl, Lage
und Ort, stattdessen Panorama, Beschreibung oder Hintergrund), melde „mittel“, Kapitel 1, Beschreibung beginnt mit
„Einstieg:“, Korrektur = ein konkreter neuer Anfang (2–4 Sätze). Fehlt im letzten Kapitel ein spürbarer Abschluss des
Bogens, melde „mittel“, Beschreibung beginnt mit „Ende:“.
Antworte NUR mit JSON: {"probleme": [{"schwere": "hoch|mittel|niedrig", "kapitel": <Nummer>, "beschreibung": "...",
"korrektur": "konkreter Änderungsvorschlag"}]}. Keine Probleme → leere Liste."""


def _checker_chain(run) -> list:
    """Prüfer soll ein anderes Modell als der Autor sein (PIPELINE.md): andere Modelle zuerst."""
    chain = getattr(run, "chains", {}).get("pruefer") or providers.resolve_chain("pruefer")
    author = run.models.get("autor", "")
    other = [c for c in chain if f"{c[0]['name']} · {c[1]}" != author]
    if chain and not other:
        run.step("Prüfer nutzt dasselbe Modell wie der Autor – unter „Modelle je Aufgabe“ ein anderes wählen", None, "warnung")
    return other + [c for c in chain if c not in other]


def _check(conn, run, plan, chapters) -> list:
    text = "\n\n".join(f"=== Kapitel {i + 1} ===\n{c}" for i, c in enumerate(chapters))
    history = _episode_history(conn, 1)
    handoff = history[-1].get("end_handoff") if history else None
    auto = timeline.check(conn, reveal=True)["probleme"]
    extra = (f"\n\nÜBERGABE: Die vorige Folge endete so – Kapitel 1 soll daran inhaltlich anknüpfen: {handoff}"
             if handoff else "")
    extra += ("\n\nAUTOMATISCHE PRÜFUNG (Kanon-Daten):\n" + "\n".join(f"- {i['figur']} {i['text']}" for i in auto)
              if auto else "")
    if getattr(run, "genre_rules", ""):
        extra += ("\n\n" + run.genre_rules + "\nVerstöße gegen Tabus des Genres höchstens als „mittel“ melden, "
                  "Beschreibung beginnt mit „Tabu:“ – das wird nur als Warnung an der Folge angezeigt.")
    if getattr(run, "age_rating", ""):
        extra += (f"\n\nALTERSFREIGABE (vom Autor festgelegt): {run.age_rating}. Nicht neu bewerten; passt etwas "
                  "deutlich nicht dazu, höchstens als „mittel“ melden, Beschreibung beginnt mit „Altersfreigabe:“.")
    if getattr(run, "voice", ""):
        extra += ("\n\n" + run.voice + "\nWeicht der Stil deutlich vom Erzählprofil ab, als „niedrig“ oder „mittel“ "
                  "melden (Kategorie „Stil“).")
    extra += _deviation_check_note(run, plan)
    if _cascade(run):
        ids = kontext.merge_ids(kontext.mentioned(conn, text + json.dumps(plan, ensure_ascii=False)),
                                {"characters": [f.get("id") for f in plan.get("figuren") or [] if isinstance(f, dict)]})
        context = _context_cascade(conn, ids, until=float(plan.get("welt_ende") or plan.get("welt_start") or 0))
    else:
        context = _context(conn)
    messages = [{"role": "system", "content": CHECK_PROMPT},
                {"role": "user", "content": context + f"\n\nPLAN:\n{json.dumps(plan, ensure_ascii=False)}"
                 + extra + f"\n\nFOLGE:\n{text}"}]

    def validate(data):
        return [] if isinstance(data, dict) and isinstance(data.get("probleme"), list) else ["probleme fehlt"]

    report = _ask_json(run, messages, "pruefer", 76, 82, 2500, "Prüfer", validate, chain=_checker_chain(run))["probleme"]
    serious = [p for p in report if isinstance(p, dict) and p.get("schwere") in ("hoch", "mittel")]
    run.step(f"Prüfer: {len(report)} Hinweise, davon {len(serious)} wichtig", 82, "ok" if not serious else "warnung")
    return report


# ---------------------------------------------------------------- 4. Lektor

EDITOR_PROMPT = """Du bist der Lektor einer fortlaufenden Hörbuchreihe und sorgst für einen einheitlichen Stil über alle Folgen.
{style}
Überarbeite das Kapitel: Fluss, Klang beim Vorlesen, Stimmigkeit. Setze die genannten Korrekturen um.
Inhalt und Länge im Wesentlichen erhalten. Format beibehalten: jeder Absatz beginnt mit [Sprecher].
Steht unter den Korrekturen „Einstieg:“, schreibe die ersten Absätze neu, sodass sie den Hörer abholen (Figur, Alter/Rolle,
Gefühl, Lage, Ort) – der bisherige Anfang darf danach folgen oder gekürzt werden. Bei „Ende:“ runde das Kapitelende ab.
Antworte nur mit dem überarbeiteten Kapiteltext."""


def _edit(run, chapter_text, issues, index, total, low, high) -> str:
    fixes = "\n".join(f"- {p.get('beschreibung', '')} → {p.get('korrektur', '')}" for p in issues) or "- keine"
    turn = getattr(run, "wendung", "")
    if turn:
        fixes += f"\nNICHT GLÄTTEN: Die geplante Wendung („{turn}“) bleibt überraschend – nicht vorwegnehmen, nicht entschärfen."
    messages = [{"role": "system", "content": EDITOR_PROMPT.format(style=_style(run))},
                {"role": "user", "content": f"KORREKTUREN FÜR DIESES KAPITEL:\n{fixes}\n\nKAPITEL:\n{chapter_text}"}]
    words = word_count(chapter_text)
    label = f"Lektor, Kapitel {index + 1}/{total}"
    chain = (getattr(run, "chains", {}).get("lektor") or providers.resolve_chain("lektor"))[:1]  # immer dasselbe Modell
    edited = normalize(_ask(run, messages, "lektor", False, low, high, len(chapter_text), label,
                            max_tokens=max(4000, int(words * 2.8)), chain=chain))
    if word_count(edited) < words * 0.7:
        run.step(f"{label}: Überarbeitung zu stark gekürzt – Autorfassung bleibt", None, "warnung")
        return chapter_text
    return edited


# ---------------------------------------------------------------- 5. Archivar

ARCHIVE_PROMPT = llm.SYSTEM_PROMPT.replace(
    "Du bist der Weltenbauer", "Du bist der Archivar") + """

Zusätzliche Aufgabe als ARCHIVAR: Lies die fertige Folge und trage nach, was nun Kanon ist – neue Figuren, Orte, Ereignisse
(mit Weltzeit), Wissen (mit Quelle), Beziehungen, Jobs, neue Rätsel oder Codes, verwendete Technik. Nur was in der Folge
tatsächlich passiert oder gesagt wurde. Füge dem JSON zusätzlich hinzu:
  "folgen_zusammenfassung": "3–5 Sätze, was in der Folge passiert (für spätere Folgen)",
  "ende_uebergabe": "Wie die Folge endet – Anknüpfungspunkt für die nächste",
  "einschuebe_verwendet": [ids der tatsächlich verwendeten Einschübe],
  "ripples": [{"quelle_ereignis": <id oder "@ref" eines Ereignisses>, "ziel_strang_id": <id>,
               "fruehestens_weltzeit": <Zahl>, "wirkung": "Was das Ereignis im anderen Strang auslöst"}],
  "raetsel_status": [{"id": <Rätsel-id>, "status": "angedeutet|bestaetigt|aufgeloest"}],
  "codes_verwendet": [ids der in der Folge vorkommenden Codes]
Erlaubte Tabellen und Spalten:
"""


def _archive(conn, run, plan, text) -> dict:
    if _cascade(run):
        context = _context_cascade(conn, kontext.mentioned(conn, text), index=True)
    else:
        context = _context(conn)
    messages = [{"role": "system", "content": ARCHIVE_PROMPT + llm._schema_description()},
                {"role": "user", "content": context + f"\n\nPLAN:\n{json.dumps(plan, ensure_ascii=False)}\n\nFOLGE:\n{text}"}]

    def validate(data):
        if not isinstance(data, dict) or not data.get("folgen_zusammenfassung"):
            return ["folgen_zusammenfassung fehlt"]
        ops = data.get("operationen") or []
        return service.validate_payload({"operationen": ops}) if ops else []

    return _ask_json(run, messages, "archivar", 93, 97, 3000, "Archivar", validate)


# ---------------------------------------------------------------- Ablauf

PLAN_ATTEMPTS = 2  # Planer-Durchläufe, wenn die Vorbereitung den Strang nicht anlegen kann


def produce(conn: sqlite3.Connection, wish: str = "", thread_id: int | None = None, words: int | None = None,
            job_id: int | None = None, genre_id: int | None = None, profile_id: str | None = None,
            age_rating: str | None = None, abweichung: int | None = None, szenarien_anzahl: int | None = None,
            scenario_set_id: int | None = None, scenario_nr: int | None = None) -> int | None:
    """Erzeugt eine Folge. Gibt die Folgen-id zurück – oder None, wenn Szenarien auf die Wahl des Menschen warten."""
    from . import szenarien
    words = int(words or service.setting(conn, "folge_woerter"))
    auftrag = f"Neue Folge erzeugen (Ziel ca. {words} Wörter ≈ {round(words / WORDS_PER_MINUTE)} Minuten)"
    if thread_id:
        auftrag += f"\nStrang: #{thread_id}"
    if wish.strip():
        auftrag += f"\nWunsch: {wish.strip()}"
    if age_rating:
        auftrag += f"\nAltersfreigabe (Autor): {age_rating.strip()[:40]}"
    conn.commit()  # Protokoll schreibt über eine eigene Verbindung
    run = runs.Run(conn, "Folge", wish.strip()[:80] or "nächste Folge", "planer", auftrag, job_id=job_id)
    run.model_used = None
    run.models = {}
    run.qa = []
    try:
        problems_before = len(timeline.check(conn, reveal=True)["probleme"])
    except Exception:  # noqa: BLE001 – Messung ist Beiwerk
        problems_before = None
    profile = profiles.get(profile_id or service.meta(conn).get("nutzer_id"))
    run.voice = profiles.style_block(profile)
    run.genre_id = genres.resolve(conn, genre_id, thread_id)
    run.genre_rules = genres.rules_text(conn, run.genre_id)
    run.age_rating = (age_rating or "").strip()[:40]
    run.kontext = service.setting(conn, "kontext_modus")
    story = szenarien.params(conn, thread_id, run.genre_id, abweichung, szenarien_anzahl)
    run.abweichung = story["abweichung"]
    chapters: list = []
    plan: dict = {}
    episode_id = None
    set_id = scenario_set_id
    try:
        run.step("Auftrag angenommen" + (f" – Erzählprofil: {profile['name']}" if run.voice else " – ohne Erzählprofil")
                 + (f", Genre: {run.genre_rules.splitlines()[0][7:]}" if run.genre_rules else "")
                 + (f", Altersfreigabe (Autor): {run.age_rating}" if run.age_rating else "")
                 + (f", Überraschung Stufe {story['abweichung']} ({story['quelle']})" if story["abweichung"] else "")
                 + (", Kontext: Kaskade" if _cascade(run) else ""), 2)
        if scenario_set_id:
            plan = szenarien.take(conn, scenario_set_id, int(scenario_nr or 1))
            run.abweichung = int(plan.get("abweichung") or run.abweichung)
            run.step(f"Szenario {scenario_nr} aus deiner Wahl übernommen", 12, "ok")
        elif story["szenarien"] > 1:
            plan, set_id = szenarien.run_flow(conn, run, wish, thread_id, words, story)
            if plan is None:
                run.step("Szenarien warten auf deine Wahl → Seite „Geschichten“", 100, "warnung")
                run.finish("fertig")
                return None
            run.abweichung = int(plan.get("abweichung") or run.abweichung)
        else:
            plan = _plan(conn, run, wish, thread_id, words)
        for attempt in range(1, PLAN_ATTEMPTS + 1):
            run.wendung = str(plan.get("wendung") or "") if run.abweichung >= 2 else ""
            run.step(f"Plan: „{plan.get('titel', '')}“ – {len(plan['kapitel'])} Kapitel, Typ {plan['typ']}", 12, "ok")
            try:
                refs, thread = _apply_preparation(conn, run, plan)
                break
            except PlanBroken as exc:
                if attempt == PLAN_ATTEMPTS:
                    raise EpisodeError(f"Der geplante Strang ließ sich auch nach {attempt} Versuchen nicht anlegen: {exc}")
                run.step(f"Plan nicht ausführbar ({exc}) – Vorbereitung zurückgenommen, Planer plant neu "
                         f"(Versuch {attempt + 1}/{PLAN_ATTEMPTS})", 13, "warnung")
                set_id = None  # neuer Plan gehört nicht mehr zum Szenario-Satz
                plan = _plan(conn, run, wish, thread_id, words,
                             extra_task=f"\nDER VORIGE PLAN WAR NICHT AUSFÜHRBAR: {exc}. Plane neu und behebe das.")
        if not run.genre_rules:
            chosen = plan.get("genre_id") if isinstance(plan.get("genre_id"), int) else None
            run.genre_id = genres.resolve(conn, chosen, thread)
            run.genre_rules = genres.rules_text(conn, run.genre_id)
            if run.genre_rules:
                run.step(f"Genre gewählt: {run.genre_rules.splitlines()[0][7:]}", 15)
        if run.genre_id:  # neue Geschichte behält ihr Genre für die nächsten Folgen
            conn.execute("UPDATE threads SET genre_id = ? WHERE id = ? AND genre_id IS NULL", (run.genre_id, thread))
            conn.commit()
        plan["_thread_id"] = thread
        cast = _cast(conn, plan, refs)
        run.step(f"Strang #{thread}, {len(cast)} Figuren besetzt", 15)

        total = len(plan["kapitel"])
        span = 60 / total
        for index in range(total):
            low = int(15 + span * index)
            chapters.append(_write_chapter(conn, run, plan, cast, index, "\n\n".join(chapters), low, int(low + span)))

        drafts = list(chapters)  # Autorfassung – für die Messung des Lektor-Schadens
        issues: list = []
        try:
            issues = _soften(_check(conn, run, plan, chapters))
        except (EpisodeError, llm.LLMError) as exc:
            run.step(f"Prüfer übersprungen: {exc}", 82, "warnung")

        span = 10 / total
        for index in range(total):
            mine = [p for p in issues if isinstance(p, dict) and str(p.get("kapitel")) == str(index + 1)]
            low = int(82 + span * index)
            try:
                chapters[index] = _edit(run, chapters[index], mine, index, total, low, int(low + span))
            except EpisodeError as exc:
                run.step(f"Lektor Kapitel {index + 1} übersprungen: {exc}", None, "warnung")
        run.step("Lektorat abgeschlossen", 92, "ok")

        text = "\n\n".join(chapters)
        episode_id = _save(conn, plan, thread, text, issues, run, status="fertig")
        if set_id:
            conn.execute("UPDATE episodes SET scenario_set_id = ? WHERE id = ?", (set_id, episode_id))
            conn.execute("UPDATE scenario_sets SET episode_id = ? WHERE id = ?", (episode_id, set_id))
            conn.commit()
        run.step(f"Folge #{episode_id} gespeichert: {word_count(text):,} Wörter ≈ "
                 f"{round(word_count(text) / WORDS_PER_MINUTE)} Minuten".replace(",", "."), 93, "ok")

        archive = None
        try:
            archive = _archive(conn, run, plan, text)
            _apply_archive(conn, run, archive, plan, thread, episode_id)
        except (EpisodeError, llm.LLMError, service.ValidationError) as exc:
            conn.commit()
            run.step(f"Archivar übersprungen: {exc} – Folge bleibt erhalten", None, "warnung")

        metrics = _metrics(issues, archive, conn, episode_id)
        metrics["qualitaet"] = _measure(conn, run, episode_id, text, drafts, chapters, profile, problems_before)
        if metrics["warnungen"]:
            run.step(f"{len(metrics['warnungen'])} Warnung(en) zu Tabu/Altersfreigabe an der Folge vermerkt "
                     "(blockiert nichts)", None, "warnung")
        needs_review = any(isinstance(p, dict) and p.get("schwere") == "hoch" for p in issues)
        conn.execute("UPDATE episodes SET metrics = ?, status = ? WHERE id = ?",
                     (json.dumps(metrics, ensure_ascii=False), "freigabe" if needs_review else "fertig", episode_id))
        conn.commit()
        if needs_review:
            run.step("Prüfer fand schwere Probleme – Folge wartet auf deine Freigabe (gezielte Rückfrage)", None, "warnung")
        try:
            _world_development(conn, plan, text)
            run.step("Weltentwicklung abwesender Völker angestoßen (eigener KI-Lauf)", 99, "ok")
        except Exception as exc:  # optional: darf die Folge nie gefährden
            conn.commit()
            run.step(f"Weltentwicklung übersprungen: {exc}", None, "warnung")

        run.set_response(json.dumps({"plan": plan, "pruefung": issues}, ensure_ascii=False, indent=1),
                         run.model_used or "")
        run.step("Fertig", 100, "ok")
        run.finish("fertig")
        _link_run(conn, episode_id, run.id)
        return episode_id
    except Exception as exc:
        try:
            conn.commit()
        except sqlite3.Error:
            pass
        if chapters and episode_id is None and plan:
            try:
                thread = _resolve(plan.get("strang"), {}, "threads", conn)
                if thread:
                    episode_id = _save(conn, plan, thread, "\n\n".join(chapters), [], run, status="entwurf")
                    run.step(f"Bisheriger Text als Entwurf #{episode_id} gesichert", None, "warnung")
            except Exception:  # Sicherung darf den eigentlichen Fehler nicht verdecken
                pass
        run.step(f"Abgebrochen: {exc}", None, "fehler")
        run.finish("fehler", error=str(exc)[:1000])
        raise


def _save(conn, plan, thread_id, text, issues, run, status) -> int:
    release = (conn.execute("SELECT COALESCE(MAX(release_nr), 0) + 1 FROM episodes").fetchone()[0])
    start, end = float(plan["welt_start"]), float(plan["welt_ende"])
    perspective = plan.get("perspektive_von_folge")
    if perspective and not conn.execute("SELECT 1 FROM episodes WHERE id = ?", (perspective,)).fetchone():
        perspective = None
    cur = conn.execute(
        "INSERT INTO episodes (release_nr, thread_id, world_start, world_end, type, text, end_handoff, title, "
        "perspective_of_episode_id, summary, status, word_count, plan, check_report, run_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (release, thread_id, start, end, plan["typ"], text, plan.get("ende_uebergabe"), plan.get("titel"),
         perspective, None, status, word_count(text), json.dumps(plan, ensure_ascii=False),
         json.dumps(issues, ensure_ascii=False), run.id, time.strftime("%Y-%m-%d %H:%M:%S")))
    if getattr(run, "genre_id", None):
        conn.execute("UPDATE episodes SET genre_id = ? WHERE id = ?", (run.genre_id, cur.lastrowid))
    if getattr(run, "age_rating", ""):
        conn.execute("UPDATE episodes SET age_rating = ? WHERE id = ?", (run.age_rating, cur.lastrowid))
    service.audit(conn, "ki", "folge", "episodes", cur.lastrowid, detail=plan.get("titel"))
    conn.commit()
    return cur.lastrowid


def _link_run(conn, episode_id, run_id) -> None:
    conn.execute("UPDATE episodes SET run_id = ? WHERE id = ?", (run_id, episode_id))
    conn.commit()


MYSTERY_ORDER = ("offen", "angedeutet", "bestaetigt", "aufgeloest")


def _apply_archive(conn, run, archive, plan, thread_id, episode_id) -> None:
    conn.execute("UPDATE episodes SET summary = ?, end_handoff = COALESCE(?, end_handoff) WHERE id = ?",
                 (archive.get("folgen_zusammenfassung"), archive.get("ende_uebergabe"), episode_id))
    # Zeit-Cursor des Strangs nachziehen (nur vorwärts) und Strang aktiv setzen
    if plan["typ"] in ("gegenwart", "parallel"):
        conn.execute("UPDATE threads SET world_time_cursor = MAX(world_time_cursor, ?), "
                     "status = CASE WHEN status IN ('geplant', 'ruhend') OR status IS NULL THEN 'aktiv' ELSE status END "
                     "WHERE id = ?", (float(plan["welt_ende"]), thread_id))
    used = [i for i in (archive.get("einschuebe_verwendet") or []) + (plan.get("einschuebe") or []) if isinstance(i, int)]
    for snippet in set(used):
        conn.execute("UPDATE snippets SET status = 'verwendet', used_in_episode_id = ? WHERE id = ? AND status = 'offen'",
                     (episode_id, snippet))
    for ripple in plan.get("ripples_erledigt") or []:
        if isinstance(ripple, int):
            conn.execute("UPDATE ripples SET done = 1 WHERE id = ?", (ripple,))
    release = conn.execute("SELECT release_nr FROM episodes WHERE id = ?", (episode_id,)).fetchone()[0]
    # Rätsel nur vorwärts entwickeln (offen → angedeutet → bestätigt → aufgelöst)
    for item in archive.get("raetsel_status") or []:
        if not isinstance(item, dict) or item.get("status") not in MYSTERY_ORDER:
            continue
        row = conn.execute("SELECT status, seed_episode_id FROM mysteries WHERE id = ?", (item.get("id"),)).fetchone()
        if row and MYSTERY_ORDER.index(item["status"]) > MYSTERY_ORDER.index(row[0]):
            conn.execute("UPDATE mysteries SET status = ?, seed_episode_id = COALESCE(seed_episode_id, ?) WHERE id = ?",
                         (item["status"], episode_id, item["id"]))
    codes = [c for c in archive.get("codes_verwendet") or [] if isinstance(c, int)]
    for code in set(codes):
        row = conn.execute("SELECT appearances FROM codes WHERE id = ?", (code,)).fetchone()
        if row is not None:
            entry = f"Folge {release}"
            current = row[0] or ""
            if entry not in current.split("\n"):
                conn.execute("UPDATE codes SET appearances = ? WHERE id = ?",
                             ((current + "\n" + entry).strip(), code))
    service.audit(conn, "system", "archiv", "episodes", episode_id,
                  detail=f"Zeit-Cursor Strang #{thread_id}, {len(set(used))} Einschübe, {len(set(codes))} Codes")
    conn.commit()
    ops = archive.get("operationen") or []
    refs: dict = {}
    if ops:
        payload = {"zusammenfassung": f"Archiv der Folge „{plan.get('titel', '')}“", "operationen": ops,
                   "rueckfragen": archive.get("rueckfragen") or []}
        pid = service.store_proposal(conn, f"Archivar: Folge #{episode_id}", payload, run.model_used)
        conn.commit()
        llm.maybe_auto_apply(conn, pid, payload, run)
        conn.commit()
        result = conn.execute("SELECT result FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
        refs = (json.loads(result) or {}).get("refs", {}) if result else {}
    stored = 0
    for ripple in archive.get("ripples") or []:
        if not isinstance(ripple, dict):
            continue
        source = ripple.get("quelle_ereignis")
        if isinstance(source, str) and source.startswith("@"):
            source = refs.get(source[1:])
        target = ripple.get("ziel_strang_id")
        try:
            if source and target and conn.execute("SELECT 1 FROM events WHERE id = ?", (source,)).fetchone() \
                    and conn.execute("SELECT 1 FROM threads WHERE id = ?", (target,)).fetchone():
                conn.execute("INSERT INTO ripples (source_event_id, target_thread_id, earliest_world_time, effect) "
                             "VALUES (?, ?, ?, ?)", (source, target, float(ripple.get("fruehestens_weltzeit") or 0),
                                                     str(ripple.get("wirkung") or "")[:2000]))
                stored += 1
        except (TypeError, ValueError, sqlite3.Error):
            continue
    conn.commit()
    run.step(f"Archivar: Zusammenfassung, {len(ops)} Kanon-Einträge, {stored} Ripples verarbeitet", 98, "ok")


def _canon_names(conn) -> list:
    names = []
    for table, col in (("characters", "name"), ("locations", "name"), ("technologies", "name"), ("peoples", "name"),
                       ("organizations", "name")):
        try:
            names += [r[0] for r in conn.execute(f"SELECT {col} FROM {table}") if r[0]]
        except sqlite3.Error:
            pass
    return names


def _secrets(conn) -> list:
    out = []
    for sql in ("SELECT truth FROM mysteries WHERE truth IS NOT NULL", "SELECT meaning FROM codes WHERE meaning IS NOT NULL"):
        try:
            out += [r[0] for r in conn.execute(sql) if r[0]]
        except sqlite3.Error:
            pass
    return out


def _measure(conn, run, episode_id, text, drafts, chapters, profile, problems_before) -> dict:
    """Live-Qualitätsmessung einer fertigen Folge (nur Code, keine KI-Kosten). Fehler bleiben folgenlos."""
    out: dict = {}
    try:
        author = run.models.get("autor")
        names = _canon_names(conn)
        share, _ = quality.spoiler_share(_secrets(conn), text)
        out["spoiler"] = share
        previous = [r[0] for r in conn.execute("SELECT text FROM episodes WHERE id != ? AND text IS NOT NULL "
                                               "ORDER BY release_nr DESC LIMIT 5", (episode_id,))]
        out["wiederholung"] = quality.repetition(text, previous)
        out["konkretheit"] = quality.concreteness(text, names)["wert"]
        reference = profiles.style_samples(profile, 20000) if profile else ""
        if not reference:
            reference = "\n".join(previous[:3])
        dev = quality.style_deviation(text, reference)
        if dev is not None:
            out["stil"] = dev
        for test in ("spoiler", "wiederholung", "konkretheit", "stil"):
            if test in out:
                quality.note(run, test, "autor", author, out[test], {"folge": episode_id})
        editor = run.models.get("lektor")
        if editor and drafts and len(drafts) == len(chapters):
            damage = max(quality.editor_damage(a, b, names) for a, b in zip(drafts, chapters))
            out["lektor_schaden"] = damage
            quality.note(run, "lektor_schaden", "lektor", editor, damage, {"folge": episode_id})
        if problems_before is not None:
            after = len(timeline.check(conn, reveal=True)["probleme"])
            out["kanon_schaden"] = max(0, after - problems_before)
            quality.note(run, "kanon_schaden", "archivar", run.models.get("archivar") or author, out["kanon_schaden"],
                         {"folge": episode_id})
        out["format"] = [q["wert"] for q in run.qa if q["test"] == "format"]
    except Exception as exc:  # noqa: BLE001
        out["fehler"] = str(exc)[:200]
    return out


WARN_PREFIX = re.compile(r"^\W*(tabu|altersfreigabe|genre)\b", re.I)


def _soften(issues: list) -> list:
    """Tabu- und Altersfreigabe-Befunde sind Warnungen: nie „hoch“, nie Freigabe-Zwang."""
    for p in issues:
        if isinstance(p, dict) and WARN_PREFIX.search(str(p.get("beschreibung", ""))):
            p["warnung"] = True
            if p.get("schwere") == "hoch":
                p["schwere"] = "mittel"
    return issues


def _metrics(issues: list, archive: dict | None, conn, episode_id) -> dict:
    warnings = [str(p.get("beschreibung", ""))[:300] for p in issues if isinstance(p, dict) and p.get("warnung")]
    kinds = sorted({WARN_PREFIX.search(w).group(1).capitalize() for w in warnings if WARN_PREFIX.search(w)})
    serious = [p for p in issues if isinstance(p, dict) and p.get("schwere") in ("hoch", "mittel")]
    narrator = [p for p in issues if isinstance(p, dict) and "erzähler" in str(p.get("beschreibung", "")).lower()]
    codes = [c for c in (archive or {}).get("codes_verwendet") or [] if isinstance(c, int)]
    repeats = {}
    for code in set(codes):
        row = conn.execute("SELECT kind, appearances FROM codes WHERE id = ?", (code,)).fetchone()
        if row:
            repeats[str(code)] = len([a for a in (row[1] or "").split("\n") if a.strip()])
    return {"kanon_score": len(serious), "hinweise": len(issues), "erzaehler": len(narrator), "code_wiederholungen": repeats,
            "warnungen": warnings, "warn_arten": kinds}


WORLD_PROMPT_TASK = """Weltentwicklung im Hintergrund: Diese Völker kamen in den letzten Folgen nicht vor, entwickeln sich aber mit der
Weltzeit weiter (OFFENE_PUNKTE.md). Lege für jedes höchstens 1–2 glaubwürdige Entwicklungen als Ereignisse (Tabelle events)
im Zeitraum Weltzeit {start:g} bis {end:g} an, mit "sichtbarkeit": "backstage" (der Hörer erfährt es später in einer Geschichte).
Keine bestehenden Werte ändern. Völker: {names}"""


def _world_development(conn, plan, text) -> None:
    peoples = conn.execute("SELECT id, name FROM peoples").fetchall()
    recent = " ".join(r[0] or "" for r in conn.execute(
        "SELECT text FROM episodes ORDER BY release_nr DESC LIMIT 3")) + " " + text
    absent = [p for p in peoples if p[1] and p[1] not in recent][:3]
    if not absent:
        return
    names = ", ".join(f"{p[1]} (id {p[0]})" for p in absent)
    llm.propose(conn, WORLD_PROMPT_TASK.format(start=float(plan["welt_start"]), end=float(plan["welt_ende"]), names=names),
                aufgabe="weltenbau", art="Weltentwicklung", ziel=", ".join(p[1] for p in absent))


# ---------------------------------------------------------------- Lesen

def list_episodes(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT e.id, e.release_nr, e.title, e.type, e.world_start, e.world_end, e.status, e.word_count, e.created_at, "
        "e.summary, e.run_id, e.audio_path, e.metrics, t.title AS strang, g.name AS genre FROM episodes e "
        "LEFT JOIN threads t ON t.id = e.thread_id LEFT JOIN genres g ON g.id = e.genre_id "
        "ORDER BY e.release_nr DESC").fetchall()
    return [dict(r, minuten=round((r["word_count"] or 0) / WORDS_PER_MINUTE), metrics=_public_metrics(r["metrics"], False))
            for r in rows]


def _public_metrics(raw, reveal: bool):
    """Warnungs-Details können Handlung verraten – ohne Backstage nur Anzahl und Art."""
    try:
        m = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return None
    if not isinstance(m, dict):
        return None
    if not reveal and m.get("warnungen"):
        m["warn_anzahl"] = len(m["warnungen"])
        m.pop("warnungen")
    return m


def stories(conn: sqlite3.Connection) -> list:
    """Geschichten zum Weitererzählen: offene Stränge mit Genre, Folgenzahl und letzter Folge."""
    rows = conn.execute(
        "SELECT t.id, t.title, t.premise, t.level, t.status, t.world_time_cursor, t.genre_id, t.abweichung, g.name AS genre, "
        "g.age_rating AS genre_alter, COUNT(e.id) AS folgen, MAX(e.release_nr) AS letzte_nr "
        "FROM threads t LEFT JOIN genres g ON g.id = t.genre_id LEFT JOIN episodes e ON e.thread_id = t.id "
        "WHERE t.visibility = 'offen' GROUP BY t.id ORDER BY MAX(e.release_nr) IS NULL, MAX(e.release_nr) DESC, t.id DESC"
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        last = conn.execute(
            "SELECT e.id, e.title, e.created_at, e.age_rating, e.status, g.name AS genre FROM episodes e "
            "LEFT JOIN genres g ON g.id = e.genre_id WHERE e.thread_id = ? ORDER BY e.release_nr DESC LIMIT 1",
            (r["id"],)).fetchone()
        item["letzte"] = dict(last) if last else None
        cals = timeline.format_all(conn, float(r["world_time_cursor"] or 0)) if r["world_time_cursor"] is not None else []
        item["zeit"] = next((c["text"] for c in cals if c.get("text")), "")
        out.append(item)
    return out


def get_episode(conn: sqlite3.Connection, episode_id: int, reveal: bool = False) -> dict:
    row = conn.execute("SELECT e.*, t.title AS strang, g.name AS genre FROM episodes e "
                       "LEFT JOIN threads t ON t.id = e.thread_id LEFT JOIN genres g ON g.id = e.genre_id "
                       "WHERE e.id = ?", (episode_id,)).fetchone()
    if row is None:
        raise LookupError("Folge nicht gefunden.")
    out = dict(row)
    out["segmente"] = parse_segments(out.get("text") or "")
    out["minuten"] = round((out.get("word_count") or 0) / WORDS_PER_MINUTE)
    out["metrics"] = _public_metrics(out.get("metrics"), reveal)
    if reveal:
        out["plan"] = json.loads(out["plan"]) if out.get("plan") else None
        out["check_report"] = json.loads(out["check_report"]) if out.get("check_report") else []
    else:
        out.pop("plan", None)
        out.pop("check_report", None)
    return out


def export_text(conn: sqlite3.Connection, episode_id: int) -> tuple:
    row = conn.execute("SELECT release_nr, title, text FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if row is None:
        raise LookupError("Folge nicht gefunden.")
    safe = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "_", row["title"] or "Folge").strip("_")
    return f"Folge_{row['release_nr']:03d}_{safe}.txt", f"[Erzähler] Folge {row['release_nr']}: {row['title']}\n\n{row['text']}\n"


def export_pdf(conn: sqlite3.Connection, episode_id: int) -> tuple:
    """Folge als PDF (Dateiname, Bytes) – nur öffentliche Felder, keine Backstage-Inhalte."""
    ep = get_episode(conn, episode_id, reveal=False)
    name, _ = export_text(conn, episode_id)
    return name[:-4] + ".pdf", pdf.episode_pdf(ep)
