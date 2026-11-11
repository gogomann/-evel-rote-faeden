"""KI-Weltenbauer: erzeugt aus Impulsen, Lücken und Einschub-Wünschen Vorschläge.

Welche Modelle genutzt werden, steht je Aufgabe in den Einstellungen (providers.py) – mit 2. und 3. Wahl als Ausweich.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import providers, quality, runs, service

ROOT = Path(__file__).resolve().parent.parent
CONTEXT_FILES = ("WELT_REGELN.md", "ERZAEHLREGELN.md", "ZEIT_UND_STRAENGE.md", "OFFENE_PUNKTE.md")


class LLMError(RuntimeError):
    pass


def _schema_description() -> str:
    lines = []
    for table, cfg in service.ENTITIES.items():
        parts = []
        for column, label, ftype, required, secret in cfg["fields"]:
            spec = f"{column} ({label}; {ftype}{'; Pflicht' if required else ''}{'; GEHEIM' if secret else ''})"
            parts.append(spec)
        lines.append(f"- {table} [{cfg['label']}]: " + ", ".join(parts))
    return "\n".join(lines)


SYSTEM_PROMPT = """Du bist der Weltenbauer einer fortlaufenden Sci-Fi-Welt (Hörbuch/Lesestoff, Deutsch).
Der Nutzer ist Hörer und will überrascht werden. Er liefert Grundideen und Impulse; du entwickelst die Welt
und füllst Lücken – stimmig, glaubwürdig, hoffnungsvoll im Ton (an Star Trek angelehnt, für Erwachsene).

VERBINDLICH:
1. Die Projektdokumente und der bestehende Kanon sind fixiert. Nichts davon widersprechen.
   Vorhandene Werte niemals ändern – nur Neues anlegen oder LEERE Felder ergänzen.
2. Impulse des Nutzers sind verbindliche Fakten. Baue sie ein und entwickle sie weiter.
3. Weltzeit ist immer eine Zahl im Master-Kalender. In Texten nie Tageszahlen nennen.
4. Wissen ohne normale Erreichbarkeit braucht eine Quelle. Keine zusätzlichen Kommunikationsgrenzen erfinden.
5. Neue Völker bekommen einen vollständigen Steckbrief inkl. Kalender und körperlicher Folgeregeln.
6. Geheimnisse (Rätselwahrheiten, Code-Bedeutungen, verborgene Hintergründe, spätere Wendungen) gehören
   in Datensätze mit "sichtbarkeit": "backstage" bzw. in GEHEIM-Felder. Der Nutzer sieht sie nicht.
7. "zusammenfassung" ist für den Nutzer: 1–3 Sätze, was neu ist – OHNE Geheimnisse oder Auflösungen.
8. Lieber wenige, gut durchdachte Elemente als viele flache. Keine reinen Bösewichte.
9. Jede Technik und jedes Phänomen (Antriebe, Wurmlöcher, Türen …) bekommt einen Eintrag in "technologies"
   mit Regeln & Grenzen, damit spätere Geschichten darauf zurückgreifen können.
10. Rückfragen nur, wenn eine Entscheidung wirklich beim Nutzer liegt – sie halten den Vorschlag zur Freigabe an.
    Formuliere Rückfragen spoilerarm.
11. Maßstab laut ZEIT_UND_STRAENGE.md: Ein Ort liegt immer in einem größeren Ort (parent_id). Die Ebene folgt
    aus Art bzw. Maßstab. Fehlen Zwischenstufen (z. B. Spiralarm), lege sie bei Bedarf an.

ANTWORTE AUSSCHLIESSLICH MIT EINEM JSON-OBJEKT:
{
  "zusammenfassung": "...",
  "operationen": [
    {"aktion": "anlegen", "tabelle": "<tabelle>", "ref": "kurzname", "sichtbarkeit": "offen|backstage",
     "felder": {"<spalte>": "<wert>"}},
    {"aktion": "ergaenzen", "tabelle": "<tabelle>", "id": <bestehende id>, "felder": {"<leere spalte>": "<wert>"}}
  ],
  "rueckfragen": ["nur bei echtem Widerspruch zu fixierten Regeln, sonst leere Liste"]
}
Verweise (ref:-Spalten) auf bestehende Datensätze per numerischer id, auf in DIESEM Vorschlag angelegte per "@kurzname".
Ein Datensatz muss angelegt sein, bevor ein anderer per "@kurzname" auf ihn verweist.
Nur diese Tabellen und Spalten sind erlaubt:
"""


def _read_context_docs() -> str:
    parts = []
    for name in CONTEXT_FILES:
        path = ROOT / name
        if path.exists():
            parts.append(f"===== {name} =====\n{path.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def build_messages(conn: sqlite3.Connection, task: str) -> list:
    world = service.meta(conn)
    canon = json.dumps(service.canon_snapshot(conn), ensure_ascii=False, separators=(",", ":"))
    user = (
        f"WELT: {world.get('name', '')}\n{world.get('beschreibung', '')}\n\n"
        f"PROJEKTDOKUMENTE:\n{_read_context_docs()}\n\n"
        f"AKTUELLER KANON (JSON, inkl. backstage):\n{canon}\n\n"
        f"AUFTRAG:\n{task}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT + _schema_description()},
        {"role": "user", "content": user},
    ]


def impulse_task(impulse: dict) -> str:
    if impulse["kind"] == "nachricht":
        return (
            "Dies ist eine Nachricht aus der realen Welt. Arbeite sie laut ERZAEHLREGELN.md im Untergrund der "
            "Story-Welt ein: Übertrage ihren Kern in die Welt, statt sie nachzuerzählen, sodass das Wissen darin "
            "beim Hören mitschwingt. Halte den Bezug zur realen Nachricht als backstage-Datensatz fest "
            "(z. B. Weltregel der Kategorie 'Nachrichtenquelle').\n"
            f"Titel: {impulse['title']}\n{impulse['content']}"
        )
    if impulse["kind"] == "text":
        return (
            "Dies ist ein Abschnitt aus einem Text des Nutzers, der als GRUNDLAGE der Welt dient. Übernimm daraus, was "
            "für die Welt gilt: Figuren, Völker, Orte, Technik, Ereignisse, Weltregeln, Wissen, Stränge, Rätsel. "
            "Was schon im Kanon steht, nur ergänzen (per 'ergaenzen' mit id), nicht doppelt anlegen. Erfinde nichts "
            "Wesentliches hinzu; fülle nur, was zum Verständnis nötig ist. Widerspricht der Text dem Kanon, überschreibe "
            "nichts, sondern nenne den Widerspruch unter 'rueckfragen'. Enthält der Abschnitt kein neues Weltwissen, "
            "antworte mit leerer Operationsliste.\n"
            f"Titel: {impulse['title']}\n{impulse['content']}"
        )
    return (
        f"Arbeite diesen Impuls des Nutzers in die Welt ein (Art: {impulse['kind']}).\n"
        f"Titel: {impulse['title']}\n{impulse['content']}\n\n"
        "Lege an, was nötig ist, damit daraus erzählbares Material wird (Orte, Figuren, Völker, Stränge, "
        "Ereignisse, Wissen, Rätsel, Codes), und ergänze dabei berührte Lücken."
    )


def gaps_task(conn: sqlite3.Connection, table: str | None = None, row_id: int | None = None) -> str:
    items = service.gaps(conn, reveal=True)["items"]
    if table:
        items = [i for i in items if i["table"] == table and (row_id is None or i["id"] == row_id)]
    if not items:
        raise service.ValidationError("Keine Lücken gefunden.")
    items = items[:25]
    lines = [f"- {i['table']} id={i['id']} ({i['title']}): {', '.join(i['missing'])}" for i in items]
    return ("Fülle diese Lücken per 'ergaenzen' stimmig zum Kanon. Lege nur dann neue Datensätze an, wenn eine "
            "Lücke es erfordert (z. B. fehlender Kalender).\n" + "\n".join(lines))


def einschuebe_task(anzahl: int = 6, hinweis: str = "") -> str:
    anzahl = max(1, min(int(anzahl or 6), 15))
    return (
        f"Lege {anzahl} neue Einschübe in der Tabelle 'snippets' an (Sammelsurium). Das sind kleine, eigenständige "
        "Bausteine, die beim Planen eingestreut werden, wenn in einem Zeitraum zu wenig passiert – z. B. Begegnungen, "
        "Alltag, Socializing, ein Stück Wissen, Atmosphäre, eine Nebenfigur, ein kleines Rätselhäppchen. "
        "Es gibt keine festen Regeln: abwechslungsreich, passend zum Kanon, jeder Einschub für sich verständlich. "
        "Verknüpfe optional mit thread_id, location_id oder people_id. status = 'offen'."
        + (f"\nWunsch des Nutzers: {hinweis.strip()}" if hinweis and hinweis.strip() else "")
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise LLMError("Antwort enthielt kein JSON-Objekt.")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as exc:
        raise LLMError(f"Antwort war kein gültiges JSON: {exc}")


def complete(messages: list, aufgabe: str = "standard", run: "runs.Run | None" = None) -> tuple:
    def log(text, level="info"):
        if run:
            if level == "info":
                run.reset_text()
            run.step(text, 15 if level == "info" else None, level)

    try:
        text, used = providers.complete(messages, aufgabe, log=log if run else None,
                                        on_chunk=run.chunk if run else None,
                                        record=run.recorder(aufgabe, aufgabe) if run else None)
    except providers.ProviderError as exc:
        raise LLMError(str(exc))
    if run:
        run.set_response(text, used)
    try:
        return _extract_json(text), used
    except LLMError:
        if run:
            run.step("Antwort enthielt kein gültiges JSON", None, "fehler")
        raise


def _ops_summary(payload: dict) -> str:
    ops = [o for o in payload.get("operationen", []) if isinstance(o, dict)]
    new = sum(1 for o in ops if o.get("aktion") == "anlegen")
    return f"{len(ops)} Operationen ({new} neu, {len(ops) - new} ergänzen)"


def propose(conn: sqlite3.Connection, task: str, impulse_id: int | None = None, aufgabe: str = "weltenbau",
            art: str | None = None, ziel: str | None = None, job_id: int | None = None,
            allow_empty: bool = False) -> int | None:
    """Ruft die KI auf, prüft den Vorschlag (eine Korrekturrunde), speichert ihn und protokolliert jeden Schritt."""
    conn.commit()  # Protokoll schreibt über eine eigene Verbindung
    run = runs.Run(conn, art or aufgabe, ziel or task.splitlines()[0][:90], aufgabe, task, impulse_id, job_id)
    try:
        run.step("Auftrag angenommen, Kontext wird zusammengestellt", 3)
        messages = build_messages(conn, task)
        canon = service.canon_snapshot(conn)
        records = sum(len(v) for v in canon.values())
        run.set_prompt(messages)
        run.step(f"Kontext fertig: Projektdokumente + Kanon mit {records} Datensätzen "
                 f"({len(messages[1]['content']):,} Zeichen)".replace(",", "."), 10)
        payload, model = complete(messages, aufgabe, run)
        fixes = service.repair_payload(payload) if isinstance(payload, dict) else []
        if fixes:
            run.step("Kleinfehler der KI automatisch behoben: " + "; ".join(fixes[:6]), None, "warnung")
        if allow_empty and isinstance(payload, dict) and payload.get("operationen") == [] and not payload.get("rueckfragen"):
            run.step("Kein neues Weltwissen in diesem Abschnitt – nichts zu übernehmen", 100, "ok")
            run.finish("fertig")
            return None
        errors = service.validate_payload(payload)
        first_model = model
        if errors:
            run.step("Vorschlag ungültig: " + " ".join(errors) + " → Korrekturrunde", 86, "warnung")
            messages += [
                {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)},
                {"role": "user", "content": "Der Vorschlag ist ungültig:\n- " + "\n- ".join(errors)
                 + "\nKorrigiere ihn und antworte erneut nur mit dem JSON-Objekt."},
            ]
            payload, model = complete(messages, aufgabe, run)
            errors = service.validate_payload(payload)
            if errors:
                quality.note(run, "format", aufgabe, first_model, 0.0)
                raise LLMError("Vorschlag ungültig: " + " ".join(errors))
            quality.note(run, "format", aufgabe, first_model, 0.5)
        else:
            quality.note(run, "format", aufgabe, first_model, 1.0)
        run.step(f"Vorschlag geprüft: {_ops_summary(payload)}", 90, "ok")
        proposal_id = service.store_proposal(conn, task, payload, model, impulse_id)
        conn.commit()
        run.step(f"Vorschlag #{proposal_id} gespeichert", 93)
        applied = maybe_auto_apply(conn, proposal_id, payload, run)
        conn.commit()
        if not applied:
            reason = "Rückfragen der KI" if payload.get("rueckfragen") else "manuelle Freigabe eingestellt"
            run.step(f"Wartet auf deine Entscheidung ({reason}) → Vorschläge", 100, "warnung")
        run.finish("fertig", proposal_id)
        return proposal_id
    except Exception as exc:
        try:
            conn.commit()
        except sqlite3.Error:
            pass
        run.step(f"Abgebrochen: {exc}", None, "fehler")
        run.finish("fehler", error=str(exc)[:1000])
        raise


def maybe_auto_apply(conn: sqlite3.Connection, proposal_id: int, payload: dict, run=None) -> bool:
    """Übernimmt automatisch, wenn eingestellt und die KI keine Rückfragen hat.
    Scheitert die Übernahme, bleibt der Vorschlag offen – der Lauf selbst gilt nicht als gescheitert."""
    if service.setting(conn, "auto_uebernehmen") != "1" or payload.get("rueckfragen"):
        return False
    try:
        report = service.apply_proposal(conn, proposal_id)
        conn.commit()  # vor dem Protokollieren freigeben – das Protokoll schreibt über eine eigene Verbindung
    except service.ValidationError as exc:
        conn.commit()
        if run:
            run.step(f"Automatische Übernahme nicht möglich: {exc}", None, "fehler")
        return False
    if run:
        text = f"Automatisch übernommen: {report['angelegt']} angelegt, {report['ergaenzt']} ergänzt"
        if report["fehlgeschlagen"]:
            text += f", {report['fehlgeschlagen']} übersprungen"
        run.step(text, 100, "ok")
        for hint in report["hinweise"]:
            run.step(hint, None, "warnung")
    return True
