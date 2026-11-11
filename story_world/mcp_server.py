"""MCP-Server (stdio, JSON-RPC 2.0) – damit jede KI direkt mit Story World arbeiten kann.

Start: python3 -m story_world mcp   (oder: python3 story_world_mcp.py)
Nur Python-Standardbibliothek. Ausgaben an stdout sind ausschließlich Protokoll, Logs gehen an stderr.
"""

from __future__ import annotations

import json
import sys
import traceback

from . import episodes, llm, runs, service, timeline, worlds

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SPOILER_HINWEIS = ("Der Nutzer ist Hörer und will überrascht werden: Backstage-Inhalte (Geheimnisse, Rätselwahrheiten) "
                   "niemals dem Nutzer zeigen oder andeuten.")


def _s(desc: str, **props) -> dict:
    required = [k for k, v in props.items() if v.pop("required", False)]
    return {"description": desc, "inputSchema": {"type": "object", "properties": props, "required": required}}


WELT = {"type": "string", "description": "Slug der Welt (siehe welten_liste)", "required": True}
BACKSTAGE = {"type": "boolean", "description": "Backstage einbeziehen – nur als Weltenbauer. " + SPOILER_HINWEIS}

TOOLS = {
    "anleitung": _s("Regeln, Projektdokumente (WELT_REGELN, ERZAEHLREGELN …) und das Vorschlagsformat. "
                    "Vor dem ersten Schreiben lesen."),
    "welten_liste": _s("Alle Welten mit Slug und Namen."),
    "welt_anlegen": _s("Neue Welt anlegen.",
                       name={"type": "string", "required": True},
                       beschreibung={"type": "string"},
                       startbestand={"type": "boolean", "description": "Menschen, Aureas, Weltregeln übernehmen (Standard: ja)"}),
    "welt_uebersicht": _s("Bestand, Lücken, Impulse und offene Vorschläge einer Welt.", welt=dict(WELT)),
    "kanon_lesen": _s("Datensätze lesen. Ohne bereich: alle Bereiche.", welt=dict(WELT),
                      bereich={"type": "string", "enum": list(service.ENTITIES)}, backstage=dict(BACKSTAGE)),
    "suchen": _s("Volltextsuche über alle Bereiche.", welt=dict(WELT),
                 text={"type": "string", "required": True}, backstage=dict(BACKSTAGE)),
    "luecken_liste": _s("Fehlende Steckbrief-Angaben.", welt=dict(WELT), backstage=dict(BACKSTAGE)),
    "impuls_anlegen": _s("Impuls des Nutzers festhalten: Grundidee, Informationsstrang, Wunsch oder reale Nachricht "
                         "(art='nachricht'). Optional sofort die eingebaute KI anwerfen (dauert).",
                         welt=dict(WELT), titel={"type": "string", "required": True},
                         inhalt={"type": "string", "required": True},
                         art={"type": "string", "enum": list(service.IMPULSE_KINDS)},
                         ki_anwerfen={"type": "boolean"}),
    "folge_erzeugen": _s("Nächste Folge mit der Pipeline erzeugen (Planer → Autor → Prüfer → Lektor → Archivar). "
                         "Dauert mehrere Minuten; Fortschritt unter ki_laeufe.", welt=dict(WELT),
                         wunsch={"type": "string", "description": "Optionaler Wunsch des Hörers"},
                         strang_id={"type": "integer"}, woerter={"type": "integer", "description": "Ziel-Länge"},
                         genre_id={"type": "integer"},
                         altersfreigabe={"type": "string", "description": "Vom Autor festgelegt, z. B. „ab 12“"}),
    "geschichten_liste": _s("Geschichten (Stränge) zum Weitererzählen mit Genre, Folgenzahl und letzter Folge.",
                            welt=dict(WELT)),
    "folgen_liste": _s("Alle Folgen mit Titel, Strang, Länge und Status.", welt=dict(WELT)),
    "folge_lesen": _s("Text einer Folge (Format [Sprecher] Text).", welt=dict(WELT), id={"type": "integer", "required": True}),
    "zeitreise": _s("Weltzustand zu einer Weltzeit (nur was damals galt) inkl. Kalendernamen.", welt=dict(WELT),
                    weltzeit={"type": "number", "required": True}, backstage=dict(BACKSTAGE)),
    "reise": _s("Entfernung und Reisezeiten je Technik zwischen zwei Orten.", welt=dict(WELT),
                von={"type": "integer", "required": True}, nach={"type": "integer", "required": True}),
    "konsistenz": _s("Automatische Prüfung: zwei Orte gleichzeitig, Reisezeit, tote Figuren.", welt=dict(WELT),
                     backstage=dict(BACKSTAGE)),
    "ki_laeufe": _s("Protokoll der KI-Läufe (Auftrag, Schritte, Status). Mit id: Details eines Laufs.",
                    welt=dict(WELT), id={"type": "integer"}, anzahl={"type": "integer"}),
    "impulse_liste": _s("Impulse mit Status.", welt=dict(WELT)),
    "vorschlag_einreichen": _s(
        "Als Weltenbauer selbst einen Vorschlag einreichen (Format siehe anleitung). Wird geprüft und je nach "
        "Einstellung automatisch übernommen; mit Rückfragen bleibt er zur Freigabe offen.",
        welt=dict(WELT),
        vorschlag={"type": "object", "required": True,
                   "description": '{"zusammenfassung": "...", "operationen": [...], "rueckfragen": []}'},
        auftrag={"type": "string", "description": "Kurz: woran gearbeitet wurde"},
        impuls_id={"type": "integer", "description": "Bearbeiteter Impuls, falls vorhanden"}),
    "vorschlaege_liste": _s("Vorschläge (spoilergefiltert).", welt=dict(WELT),
                            nur_offen={"type": "boolean"}),
    "vorschlag_entscheiden": _s("Vorschlag übernehmen oder verwerfen.", welt=dict(WELT),
                                id={"type": "integer", "required": True},
                                entscheidung={"type": "string", "enum": ["uebernehmen", "verwerfen"], "required": True}),
    "ki_einschuebe": _s("Eingebaute KI legt kleine Einschübe (Sammelsurium) an – Extras für ruhige Phasen.",
                        welt=dict(WELT), anzahl={"type": "integer"}, hinweis={"type": "string"}),
    "ki_luecken_fuellen": _s("Eingebaute KI füllt Lücken (dauert, nutzt das konfigurierte Gateway).", welt=dict(WELT),
                             bereich={"type": "string", "enum": list(service.ENTITIES)},
                             id={"type": "integer"}),
}


def _proposal_state(conn, proposal_id: int) -> dict:
    row = conn.execute("SELECT status, result FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    return {"vorschlag_id": proposal_id, "status": row["status"],
            "ergebnis": json.loads(row["result"]) if row["result"] else None}


def call_tool(name: str, a: dict):
    reveal = bool(a.get("backstage"))
    if name == "anleitung":
        return {"regeln": llm.SYSTEM_PROMPT + llm._schema_description(), "dokumente": llm._read_context_docs(),
                "hinweis": SPOILER_HINWEIS}
    if name == "welten_liste":
        return worlds.list_worlds()
    if name == "welt_anlegen":
        return {"welt": worlds.create_world(a["name"], a.get("beschreibung", ""), a.get("startbestand", True))}
    with worlds.open_world(a["welt"]) as conn:
        if name == "welt_uebersicht":
            gaps = service.gaps(conn)
            return {"meta": service.meta(conn), "bestand": service.stats(conn), "luecken": len(gaps["items"]),
                    "luecken_backstage": gaps["hidden"],
                    "impulse": {r[0]: r[1] for r in conn.execute("SELECT status, COUNT(*) FROM impulses GROUP BY status")},
                    "vorschlaege_offen": conn.execute("SELECT COUNT(*) FROM proposals WHERE status='offen'").fetchone()[0]}
        if name == "kanon_lesen":
            if reveal and not a.get("bereich"):
                return service.canon_snapshot(conn)
            tables = [a["bereich"]] if a.get("bereich") else list(service.ENTITIES)
            out = {}
            for t in tables:
                rows = service.list_rows(conn, t, reveal)["rows"]
                out[t] = [{k: v for k, v in r.items() if v not in (None, "") and not k.startswith("__")} for r in rows]
            return out
        if name == "suchen":
            return service.search(conn, a["text"], reveal)
        if name == "luecken_liste":
            return service.gaps(conn, reveal)
        if name == "impuls_anlegen":
            impulse_id = service.create_impulse(conn, a["titel"], a["inhalt"], a.get("art", "sonstiges"))
            if not a.get("ki_anwerfen"):
                return {"impuls_id": impulse_id, "status": "neu"}
            conn.commit()
            impulse = dict(conn.execute("SELECT * FROM impulses WHERE id = ?", (impulse_id,)).fetchone())
            try:
                pid = llm.propose(conn, llm.impulse_task(impulse), impulse_id=impulse_id, aufgabe="weltenbau",
                                  art="Impuls (MCP)", ziel=impulse["title"])
            except Exception as exc:
                service.set_impulse_status(conn, impulse_id, "fehler", str(exc)[:600])
                raise
            state = _proposal_state(conn, pid)
            if state["status"] == "offen":
                service.set_impulse_status(conn, impulse_id, "vorschlag")
            return dict(state, impuls_id=impulse_id)
        if name == "zeitreise":
            return timeline.world_state(conn, a["weltzeit"], reveal)
        if name == "reise":
            return timeline.travel(conn, a["von"], a["nach"], reveal)
        if name == "konsistenz":
            return timeline.check(conn, reveal)
        if name == "folge_erzeugen":
            episode_id = episodes.produce(conn, a.get("wunsch", ""), a.get("strang_id"), a.get("woerter"),
                                          genre_id=a.get("genre_id"), age_rating=a.get("altersfreigabe"))
            if episode_id is None:
                return {"hinweis": "Szenarien warten auf die Wahl des Menschen (Oberfläche → Geschichten)."}
            return episodes.list_episodes(conn)[0]
        if name == "geschichten_liste":
            return episodes.stories(conn)
        if name == "folgen_liste":
            return episodes.list_episodes(conn)
        if name == "folge_lesen":
            episode = episodes.get_episode(conn, a["id"])
            return {k: episode[k] for k in ("release_nr", "title", "type", "strang", "minuten", "summary", "text")}
        if name == "ki_laeufe":
            if a.get("id"):
                return runs.get_run(conn, a["id"])
            return runs.list_runs(conn, limit=a.get("anzahl", 20))
        if name == "impulse_liste":
            return service.list_impulses(conn)
        if name == "vorschlag_einreichen":
            payload = a["vorschlag"]
            errors = service.validate_payload(payload)
            if errors:
                return {"fehler": errors, "hinweis": "Nichts gespeichert. Korrigieren und erneut einreichen."}
            impulse_id = a.get("impuls_id")
            pid = service.store_proposal(conn, a.get("auftrag") or "Vorschlag über MCP", payload, "mcp", impulse_id)
            llm.maybe_auto_apply(conn, pid, payload)
            state = _proposal_state(conn, pid)
            if impulse_id and state["status"] == "offen":
                service.set_impulse_status(conn, impulse_id, "vorschlag")
            return state
        if name == "vorschlaege_liste":
            items = service.list_proposals(conn)
            return [p for p in items if p["status"] == "offen"] if a.get("nur_offen") else items
        if name == "vorschlag_entscheiden":
            if a["entscheidung"] == "uebernehmen":
                return service.apply_proposal(conn, a["id"])
            service.reject_proposal(conn, a["id"])
            return {"status": "verworfen"}
        if name == "ki_luecken_fuellen":
            pid = llm.propose(conn, llm.gaps_task(conn, a.get("bereich"), a.get("id")), aufgabe="luecken",
                              art="Lücken füllen (MCP)")
            return _proposal_state(conn, pid)
        if name == "ki_einschuebe":
            pid = llm.propose(conn, llm.einschuebe_task(a.get("anzahl", 6), a.get("hinweis", "")), aufgabe="einschuebe",
                              art="Einschübe (MCP)")
            return _proposal_state(conn, pid)
    raise ValueError(f"Unbekanntes Werkzeug: {name}")


def handle(message: dict):
    method, mid = message.get("method"), message.get("id")
    if mid is None:
        return None  # Benachrichtigung (z. B. notifications/initialized)
    if method == "initialize":
        requested = (message.get("params") or {}).get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "story-world", "version": "1.0"},
            "instructions": "Story World: fortlaufende Sci-Fi-Welt. Vor dem Schreiben 'anleitung' lesen. " + SPOILER_HINWEIS,
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [dict(name=n, **spec) for n, spec in TOOLS.items()]}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(params.get("name"), params.get("arguments") or {})
            text, is_error = json.dumps(result, ensure_ascii=False, indent=1), False
        except (service.ValidationError, LookupError, KeyError, ValueError, llm.LLMError, RuntimeError,
                episodes.EpisodeError) as exc:
            text, is_error = f"Fehler: {exc}", True
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            text, is_error = f"Interner Fehler: {exc}", True
        return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": text}], "isError": is_error}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unbekannte Methode: {method}"}}


def serve(stdin=sys.stdin, stdout=sys.stdout) -> None:
    for stream in (stdin, stdout):
        if hasattr(stream, "reconfigure"):  # echte Konsole/Pipe; unter Windows sonst cp1252
            stream.reconfigure(encoding="utf-8")
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Ungültiges JSON"}}
        else:
            response = handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
