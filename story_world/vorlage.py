"""Vorlage: Eine Welt aus einem Buch oder einer Geschichte aufbauen – als Start oder als Fortsetzung.

Ablauf beim Anlegen einer Welt mit Vorlage:
1. Text aus der Datei (textimport) → in Abschnitte teilen → jeder Abschnitt wird ein Impuls der Art „text“ und von der
   KI wie „Texte als Basis“ eingearbeitet (Figuren, Völker, Orte, Technik, Ereignisse, Regeln, Stränge).
2. Analyse (eine KI-Anfrage mit Anfang und Ende der Vorlage plus Namensverzeichnis): Titel, Genre, Zusammenfassung,
   Ton, Stand am Ende, offene Fäden, Hauptstrang.
3. Abschluss: Genre festlegen (bestehendes oder neues), Hauptstrang anlegen bzw. markieren, Zeit-Cursor hinter das
   letzte Ereignis setzen, Beschreibung der Welt ergänzen.

Modus (world_meta „vorlage“):
- start:        Das Buch ist der Ausgangspunkt, die Welt darf darüber hinaus wachsen.
- fortsetzung:  Die Welt ist gesetzt. Neue Folgen setzen nach dem Ende des Buchs an; die Welt wird nur erweitert, wo
                eine Geschichte es zwingend braucht.
Genre:
- fest:  Alle Folgen und Geschichten bleiben im Genre der Vorlage (genres.resolve erzwingt es).
- frei:  Genre je Folge frei wählbar.

Der Block `prompt_block` steht in jedem KI-Aufruf dieser Welt (Weltenbau, Planer, Autor, Prüfer, Szenarien).
"""

from __future__ import annotations

import json
import sqlite3
import time

from . import llm, runs, service

MODI = {"start": "Welt damit starten", "fortsetzung": "Fortsetzung des Buchs"}
GENRE_MODI = {"fest": "im Genre der Vorlage bleiben", "frei": "Genre frei"}
EXCERPT = 14000  # Zeichen vom Anfang und vom Ende für die Analyse

TEIL_HINWEIS = {
    "start": "Diese Vorlage ist der AUSGANGSPUNKT der Welt. Übernimm das Wesentliche (Figuren mit Vor- und Nachname, "
             "Orte, Völker, Technik/Magie mit Regeln, Ereignisse mit Weltzeit, Beziehungen).",
    "fortsetzung": "Diese Vorlage soll FORTGESETZT werden. Übernimm genau, was im Text steht – Figuren mit Vor- und "
                   "Nachname, Orte, Beziehungen, Ereignisse mit Weltzeit, Wissen der Figuren. Erfinde nichts hinzu; "
                   "die Welt soll nicht größer werden, als das Buch sie zeigt.",
}

ANALYSE_PROMPT = """Du bist Lektorin und liest eine VORLAGE (Buch oder Geschichte), auf der eine Story-Welt aufbaut.
Aus Anfang und Ende der Vorlage und dem Namensverzeichnis der bereits übernommenen Welt erstellst du den Steckbrief.
Antworte NUR mit JSON:
{
  "titel": "Titel der Vorlage",
  "autor": "Autor, falls erkennbar, sonst leer",
  "genre_id": <id eines passenden Genres aus der Liste oder null>,
  "genre_neu": null oder {"name": "...", "description": "Kern", "rules": "Regeln/Konventionen", "tension": "Spannungsbogen",
                          "tone": "Ton", "age_rating": "alle|ab 6|ab 12|ab 16|ab 18"},
  "zusammenfassung": "5–8 Sätze: worum es in der Vorlage geht",
  "ton": "Erzählton, Tempo und Atmosphäre in 2–3 Sätzen",
  "ende": "Stand am Ende: wo stehen die Hauptfiguren, was ist geklärt, was offen (3–6 Sätze)",
  "offene_faeden": ["Fäden, an die eine Fortsetzung anknüpfen kann"],
  "strang": {"id": <id eines bestehenden Strangs, der die Haupthandlung ist, oder null>,
             "title": "Titel der Haupthandlung", "premise": "Prämisse in 2–3 Sätzen", "level": "makro|meso|mikro"}
}
Nur wenn kein Genre der Liste passt, "genre_neu" füllen (dann genre_id null)."""


class VorlageError(ValueError):
    pass


def get(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT value FROM world_meta WHERE key = 'vorlage'").fetchone()
    if not row:
        return None
    try:
        data = json.loads(row[0])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def save(conn: sqlite3.Connection, data: dict) -> None:
    service.set_meta(conn, "vorlage", json.dumps(data, ensure_ascii=False))


def fixed_genre(conn: sqlite3.Connection) -> int | None:
    v = get(conn)
    if v and v.get("genre_modus") == "fest" and v.get("genre_id"):
        if conn.execute("SELECT 1 FROM genres WHERE id = ?", (v["genre_id"],)).fetchone():
            return int(v["genre_id"])
    return None


def prompt_block(conn: sqlite3.Connection) -> str:
    v = get(conn)
    if not v:
        return ""
    lines = [f"VORLAGE DIESER WELT: „{v.get('titel') or 'ohne Titel'}“"
             + (f" von {v['autor']}" if v.get("autor") else "") + " – die Welt wurde aus diesem Text aufgebaut."]
    if v.get("modus") == "fortsetzung":
        lines.append("MODUS FORTSETZUNG: Die Welt ist durch die Vorlage gesetzt. Neue Folgen setzen die Handlung NACH dem "
                     "Ende der Vorlage fort, mit ihren Figuren, Orten und Konflikten. Erweitere die Welt nur, wo eine "
                     "Geschichte es zwingend braucht – keine neuen Völker, Systeme oder großen Schauplätze ohne Anlass; "
                     "lieber Bestehendes vertiefen als Neues anlegen.")
        if v.get("ende"):
            lines.append(f"STAND AM ENDE DER VORLAGE: {v['ende']}")
        if v.get("offene_faeden"):
            lines.append("OFFENE FÄDEN: " + "; ".join(str(x) for x in v["offene_faeden"][:8]))
    else:
        lines.append("MODUS START: Die Vorlage ist der Ausgangspunkt. Die Welt darf über sie hinaus wachsen, muss aber zu "
                     "ihr passen (Ton, Regeln, Technik/Magie, Gesellschaft).")
    if v.get("zusammenfassung"):
        lines.append(f"WORUM ES GEHT: {v['zusammenfassung']}")
    if v.get("ton"):
        lines.append(f"TON DER VORLAGE: {v['ton']}")
    genre = None
    if v.get("genre_id"):
        row = conn.execute("SELECT name FROM genres WHERE id = ?", (v["genre_id"],)).fetchone()
        genre = row[0] if row else None
    if v.get("genre_modus") == "fest" and genre:
        lines.append(f"GENRE FEST: Alle Folgen und Geschichten bleiben im Genre „{genre}“.")
    else:
        lines.append("GENRE FREI: Folgen und Geschichten dürfen das Genre wechseln" + (f" (Vorlage: {genre})." if genre else "."))
    lines.append("Ton, Genre und Regeln der Vorlage haben Vorrang vor allgemeinen Angaben (z. B. Sci-Fi oder Star-Trek-Ton) "
                 "in Anweisungen und Projektdokumenten.")
    return "\n".join(lines)


def world_header(conn: sqlite3.Connection) -> str:
    """„WELT: …“-Kopf für alle KI-Aufrufe, bei Welten mit Vorlage samt Modus und Genre."""
    world = service.meta(conn)
    head = f"WELT: {world.get('name', '')}\n{world.get('beschreibung', '')}"
    block = prompt_block(conn)
    return f"{head}\n\n{block}" if block else head


def start(conn: sqlite3.Connection, titel: str, modus: str, genre_modus: str, datei: str = "", zeichen: int = 0,
          genre_id: int | None = None, titel_vorgabe: bool = True, name_vorgabe: bool = True) -> dict:
    """titel_vorgabe/name_vorgabe=False: Titel bzw. Weltname kamen nur aus dem Dateinamen – die Analyse darf sie ersetzen."""
    if modus not in MODI:
        raise VorlageError("Bitte wählen: Welt damit starten oder Fortsetzung.")
    if genre_modus not in GENRE_MODI:
        raise VorlageError("Bitte wählen: im Genre bleiben oder Genre frei.")
    if genre_id and not conn.execute("SELECT 1 FROM genres WHERE id = ?", (genre_id,)).fetchone():
        raise VorlageError("Unbekanntes Genre.")
    data = {"titel": (titel or "").strip()[:160], "modus": modus, "genre_modus": genre_modus, "datei": datei[:200],
            "zeichen": zeichen, "genre_id": genre_id, "genre_vorgabe": bool(genre_id), "titel_vorgabe": bool(titel_vorgabe),
            "name_vorgabe": bool(name_vorgabe), "status": "liest",
            "importiert": time.strftime("%Y-%m-%d %H:%M")}
    save(conn, data)
    if genre_id and genre_modus == "fest":
        service.set_setting(conn, "standard_genre", str(genre_id))
    return data


def text_path(slug: str):
    from . import worlds
    return worlds.worlds_dir() / "vorlagen" / f"{slug}.txt"


def store_text(slug: str, text: str) -> None:
    """Kopie der Vorlage neben den Welten (0600) – für eine spätere neue Analyse. Ältere Kopie bleibt erhalten."""
    import os
    path = text_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.rename(path.with_name(f"{slug}-{time.strftime('%Y%m%d-%H%M%S')}.txt"))
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def read_text(slug: str) -> str:
    path = text_path(slug)
    if not path.exists():
        raise VorlageError("Der Text der Vorlage liegt nicht mehr vor.")
    return path.read_text(encoding="utf-8")


def analyse_job(slug: str, job_id: int | None) -> str:
    from . import worlds
    text = read_text(slug)
    with worlds.open_world(slug) as conn:
        v = apply_analysis(conn, analyse(conn, text, job_id))
    return f"Vorlage „{v.get('titel', '')}“ ausgewertet."


def _excerpt(text: str) -> str:
    if len(text) <= 2 * EXCERPT:
        return text
    return f"{text[:EXCERPT]}\n\n[… Mittelteil ausgelassen …]\n\n{text[-EXCERPT:]}"


def analyse_messages(conn: sqlite3.Connection, text: str) -> list:
    from . import kontext
    genres = "\n".join(f"- {r[0]}: {r[1]} – {(r[2] or '')[:120]}" for r in
                       conn.execute("SELECT id, name, description FROM genres WHERE visibility = 'offen' ORDER BY id"))
    threads = "\n".join(f"- {r[0]}: {r[1]}" for r in conn.execute("SELECT id, title FROM threads ORDER BY id"))
    user = (f"GENRES:\n{genres or '(keine)'}\n\nBESTEHENDE STRÄNGE:\n{threads or '(keine)'}\n\n"
            f"NAMENSVERZEICHNIS DER ÜBERNOMMENEN WELT:\n{kontext.text_index(conn)}\n\n"
            f"VORLAGE (Anfang und Ende):\n{_excerpt(text)}")
    return [{"role": "system", "content": ANALYSE_PROMPT}, {"role": "user", "content": user}]


def analyse(conn: sqlite3.Connection, text: str, job_id: int | None = None) -> dict:
    conn.commit()
    run = runs.Run(conn, "Vorlage analysieren", (get(conn) or {}).get("titel") or "Vorlage", "weltenbau",
                   "Steckbrief der Vorlage: Genre, Zusammenfassung, Stand am Ende, Hauptstrang", None, job_id)
    try:
        messages = analyse_messages(conn, text)
        run.set_prompt(messages)
        run.step("Anfang und Ende der Vorlage werden ausgewertet", 10)
        data, _ = llm.complete(messages, "weltenbau", run)
        if not isinstance(data, dict):
            raise llm.LLMError("Analyse lieferte kein JSON-Objekt.")
        run.step("Steckbrief der Vorlage erstellt", 100, "ok")
        run.finish("fertig")
        return data
    except Exception as exc:
        run.step(f"Abgebrochen: {exc}", None, "fehler")
        run.finish("fehler", error=str(exc)[:1000])
        raise


def apply_analysis(conn: sqlite3.Connection, data: dict) -> dict:
    """Ergebnis der Analyse übernehmen: Genre, Hauptstrang, Zeit-Cursor, Beschreibung. Vorhandenes bleibt stehen."""
    v = get(conn) or {}
    text = lambda k, n=2000: str(data.get(k) or "").strip()[:n]  # noqa: E731
    for key in ("zusammenfassung", "ton", "ende"):
        if text(key):
            v[key] = text(key)
    if text("autor", 160):
        v["autor"] = text("autor", 160)
    if text("titel", 160) and (not v.get("titel") or not v.get("titel_vorgabe", True)):
        v["titel"] = text("titel", 160)
        if not v.get("name_vorgabe", True):
            service.set_meta(conn, "name", v["titel"])
    if isinstance(data.get("offene_faeden"), list):
        v["offene_faeden"] = [str(x)[:300] for x in data["offene_faeden"][:10] if str(x).strip()]

    # Genre: Vorgabe des Nutzers > Analyse > neues Genre
    genre_id = v.get("genre_id") if v.get("genre_vorgabe") else None
    if not genre_id and isinstance(data.get("genre_id"), int) and \
            conn.execute("SELECT 1 FROM genres WHERE id = ?", (data["genre_id"],)).fetchone():
        genre_id = data["genre_id"]
    neu = data.get("genre_neu")
    if not genre_id and isinstance(neu, dict) and str(neu.get("name") or "").strip():
        existing = conn.execute("SELECT id FROM genres WHERE lower(name) = lower(?)", (neu["name"].strip(),)).fetchone()
        if existing:
            genre_id = existing[0]
        else:
            fields = {k: str(neu.get(k) or "").strip() for k in ("name", "description", "rules", "tension", "tone")}
            if neu.get("age_rating") in ("alle", "ab 6", "ab 12", "ab 16", "ab 18"):
                fields["age_rating"] = neu["age_rating"]
            genre_id = service.create_row(conn, "genres", {k: x for k, x in fields.items() if x}, actor="ki")
    v["genre_id"] = genre_id
    if genre_id and v.get("genre_modus") == "fest":
        service.set_setting(conn, "standard_genre", str(genre_id))

    # Hauptstrang: bestehenden nutzen oder anlegen; Zeit-Cursor hinter das letzte Ereignis
    last_time = conn.execute("SELECT MAX(world_time) FROM events").fetchone()[0] or 0
    strang = data.get("strang") if isinstance(data.get("strang"), dict) else {}
    tid = strang.get("id") if isinstance(strang.get("id"), int) else None
    if tid and not conn.execute("SELECT 1 FROM threads WHERE id = ?", (tid,)).fetchone():
        tid = None
    fortsetzung = v.get("modus") == "fortsetzung"
    if tid is None:
        title = str(strang.get("title") or v.get("titel") or "Haupthandlung").strip()[:120]
        premise = str(strang.get("premise") or v.get("zusammenfassung") or "").strip()
        if fortsetzung and v.get("ende"):
            premise = (premise + f"\n\nStand am Ende der Vorlage: {v['ende']}").strip()
        level = strang.get("level") if strang.get("level") in ("makro", "meso", "mikro") else "meso"
        tid = service.create_row(conn, "threads", {
            "title": title, "level": level, "status": "aktiv" if fortsetzung else "beendet", "premise": premise,
            "genre_id": genre_id, "world_time_cursor": last_time}, actor="ki")
    else:
        row = conn.execute("SELECT status, genre_id, world_time_cursor FROM threads WHERE id = ?", (tid,)).fetchone()
        changes = {}
        if fortsetzung and row["status"] in (None, "geplant", "ruhend"):
            changes["status"] = "aktiv"
        if genre_id and row["genre_id"] is None:
            changes["genre_id"] = genre_id
        if (row["world_time_cursor"] or 0) < last_time:
            changes["world_time_cursor"] = last_time
        if changes:
            service.update_row(conn, "threads", tid, changes, actor="system", reveal=True)
    v["strang_id"] = tid
    v["status"] = "fertig"
    save(conn, v)
    if not str(service.meta(conn).get("beschreibung") or "").strip() and v.get("zusammenfassung"):
        service.set_meta(conn, "beschreibung", f"Nach der Vorlage „{v.get('titel', '')}“: {v['zusammenfassung']}")
    service.audit(conn, "system", "vorlage", "threads", tid, detail=f"{MODI.get(v.get('modus'), '')}, "
                  f"{GENRE_MODI.get(v.get('genre_modus'), '')}")
    return v


def teile_einlesen(slug: str, parts: list, titel: str, hint: str, job_id: int | None, besitzer: str | None = None,
                   text_id: str | None = None, fremd: bool = False) -> dict:
    """Jeden Abschnitt als Impuls „text“ von der KI einarbeiten lassen. Ein Fehler hält die anderen Abschnitte nicht auf."""
    from . import worlds
    done, waiting, empty, failed = 0, 0, 0, []
    for i, part in enumerate(parts, 1):
        title = f"{titel} – Teil {i}/{len(parts)}" if len(parts) > 1 else titel
        with worlds.open_world(slug) as conn:
            impulse_id = service.create_impulse(conn, title, part + (f"\n\nHINWEIS DES NUTZERS: {hint}" if hint else ""), "text")
            if besitzer:
                conn.execute("UPDATE impulses SET besitzer = ?, quelle_text = ?, fremd = ? WHERE id = ?",
                             (besitzer, text_id, 1 if fremd else 0, impulse_id))
            service.set_impulse_status(conn, impulse_id, "in_arbeit")
            conn.commit()
            impulse = dict(conn.execute("SELECT * FROM impulses WHERE id = ?", (impulse_id,)).fetchone())
            try:
                proposal = llm.propose(conn, llm.impulse_task(impulse), impulse_id=impulse_id, aufgabe="weltenbau",
                                       art="Text einlesen", ziel=title, job_id=job_id, allow_empty=True)
                if proposal is None:
                    service.set_impulse_status(conn, impulse_id, "eingearbeitet", "Kein neues Weltwissen in diesem Abschnitt.")
                    empty += 1
                    conn.commit()
                    continue
                state = conn.execute("SELECT status FROM proposals WHERE id = ?", (proposal,)).fetchone()[0]
                if state == "offen":
                    service.set_impulse_status(conn, impulse_id, "vorschlag")
                    waiting += 1
                else:
                    service.set_impulse_status(conn, impulse_id, "eingearbeitet")
                done += 1
            except Exception as exc:  # noqa: BLE001
                service.set_impulse_status(conn, impulse_id, "fehler", str(exc)[:600])
                failed.append(f"Teil {i}: {str(exc)[:120]}")
            conn.commit()
    return {"done": done, "waiting": waiting, "empty": empty, "failed": failed, "total": len(parts)}


def bericht(r: dict) -> str:
    return (f"{r['done'] + r['empty']} von {r['total']} Abschnitten verarbeitet"
            + (f", {r['waiting']} Vorschläge warten auf dich" if r["waiting"] else "")
            + (f", {r['empty']} ohne neues Weltwissen" if r["empty"] else ""))


def import_job(slug: str, text: str, job_id: int | None, besitzer: str | None = None, text_id: str | None = None,
               fremd: bool = False) -> str:
    """Hintergrund-Auftrag: Abschnitte einarbeiten, analysieren, abschließen."""
    from . import profiles, worlds
    with worlds.open_world(slug) as conn:
        v = get(conn) or {}
    parts = profiles.split_text(text)
    r = teile_einlesen(slug, parts, v.get("titel") or "Vorlage", TEIL_HINWEIS.get(v.get("modus"), ""), job_id,
                       besitzer, text_id, fremd)
    if besitzer and text_id:
        profiles.note_import(besitzer, text_id, slug, len(parts))
    message = bericht(r)
    if r["failed"] and not r["done"] and not r["empty"]:
        with worlds.open_world(slug) as conn:
            save(conn, dict(get(conn) or {}, status="fehler"))
        raise RuntimeError(message + ". " + " · ".join(r["failed"][:3]))
    with worlds.open_world(slug) as conn:
        try:
            v = apply_analysis(conn, analyse(conn, text, job_id))
        except Exception as exc:  # noqa: BLE001 – Welt ist trotzdem gefüllt; Analyse lässt sich wiederholen
            save(conn, dict(get(conn) or {}, status="analyse_fehlt"))
            conn.commit()
            return message + f". Steckbrief der Vorlage fehlt noch: {str(exc)[:200]}"
    genre = ""
    with worlds.open_world(slug) as conn:
        if v.get("genre_id"):
            row = conn.execute("SELECT name FROM genres WHERE id = ?", (v["genre_id"],)).fetchone()
            genre = f", Genre {row[0]}" if row else ""
    return message + f". Vorlage ausgewertet{genre}." + (f" Fehler: {' · '.join(r['failed'][:3])}" if r["failed"] else "")
