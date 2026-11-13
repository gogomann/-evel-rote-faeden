"""Protokoll der KI-Läufe: Auftrag, Weg (Schritte), Fortschritt und Ergebnis – dauerhaft in der Welt-Datenbank.

Geschrieben wird über eine eigene, kurzlebige Verbindung je Schritt, damit das Protokoll sofort sichtbar ist
und nie die Arbeitsverbindung des Laufs blockiert. Live-Zustand (Fortschritt, mitlaufender Text) liegt im Speicher.
Schritte enthalten keine Geheimnisse; Prompt und Rohantwort (können Backstage enthalten) nur im Backstage-Modus.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import zlib

LIVE: dict = {}
_LOCK = threading.Lock()
_CURRENT = threading.local()  # Stapel der Läufe dieses Threads – für den Lauf-Bezug im Änderungsprotokoll
EXPECTED_CHARS = 6000  # grobe Erwartung für die Fortschrittsschätzung beim Mitschreiben


def _db_path(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA database_list").fetchone()
    return row[2] if row and row[2] else ""


def _write(path: str, sql: str, params: tuple):
    if not path:
        return None
    db = sqlite3.connect(path, timeout=30)
    try:
        cur = db.execute(sql, params)
        db.commit()
        return cur.lastrowid
    finally:
        db.close()


def _now() -> str:
    return time.strftime("%H:%M:%S")


def current_id() -> int | None:
    """Id des Laufs, der in diesem Thread gerade arbeitet (oder None)."""
    stack = getattr(_CURRENT, "stack", None)
    return stack[-1] if stack else None


def _json(value) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value), ensure_ascii=False)


class Run:
    def __init__(self, conn: sqlite3.Connection, art: str, ziel: str, aufgabe: str, auftrag: str,
                 impulse_id: int | None = None, job_id: int | None = None):
        self.path = _db_path(conn)
        self.started = time.time()
        self.steps: list = []
        self.progress = 0
        self.id = _write(self.path, "INSERT INTO ai_runs (art, ziel, aufgabe, auftrag, impulse_id) VALUES (?, ?, ?, ?, ?)",
                         (art, ziel, aufgabe, auftrag, impulse_id)) or 0
        self.key = f"{self.path}#{self.id}"
        self.last_call_id = None
        if self.id:
            if not hasattr(_CURRENT, "stack"):
                _CURRENT.stack = []
            _CURRENT.stack.append(self.id)
        self._last_flush = 0.0
        self.range = (20, 85, EXPECTED_CHARS)  # Fortschritt beim Mitschreiben: von, bis, erwartete Zeichen
        self.phase_label = "KI schreibt"
        with _LOCK:
            LIVE[self.key] = {"run_id": self.id, "job_id": job_id, "progress": 0, "phase": "startet",
                              "chars": 0, "text": "", "path": self.path}

    def _live(self, **fields):
        with _LOCK:
            if self.key in LIVE:
                LIVE[self.key].update(fields)

    def step(self, text: str, progress: int | None = None, level: str = "info") -> None:
        if progress is not None:
            self.progress = max(self.progress, min(100, int(progress)))
        self.steps.append({"zeit": _now(), "text": text, "stufe": level,
                           "sekunden": round(time.time() - self.started, 1)})
        self._live(progress=self.progress, phase=text)
        _write(self.path, "UPDATE ai_runs SET steps = ?, progress = ? WHERE id = ?",
               (json.dumps(self.steps, ensure_ascii=False), self.progress, self.id))

    def chunk(self, piece: str) -> None:
        """Mitlaufende Antwort der KI (Streaming)."""
        with _LOCK:
            state = LIVE.get(self.key)
            if state is None:
                return
            state["text"] += piece
            state["chars"] = len(state["text"])
            low, high, expected = self.range
            estimate = low + int((high - low) * min(1.0, state["chars"] / max(expected, 1)))
            self.progress = max(self.progress, min(high, estimate))
            state["progress"] = self.progress
            state["phase"] = f"{self.phase_label} … {state['chars']:,} Zeichen".replace(",", ".")
        if time.time() - self._last_flush > 2:
            self._last_flush = time.time()
            _write(self.path, "UPDATE ai_runs SET progress = ? WHERE id = ?", (self.progress, self.id))

    def recorder(self, step: str, task: str):
        """Rückruf für providers.complete: speichert jeden einzelnen KI-Aufruf (auch gescheiterte) mit Prompt und Antwort."""
        def record(model: str, messages: list, text: str | None, error: str | None, seconds: float) -> None:
            try:
                raw = json.dumps(messages, ensure_ascii=False)
                self.last_call_id = _write(
                       self.path, "INSERT INTO ai_calls (run_id, step, task, model, ok, error, messages, response, "
                       "prompt_chars, response_chars, seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (self.id, step, task, model, 0 if error else 1, (error or "")[:2000] or None,
                        zlib.compress(raw.encode("utf-8"), 6), text, sum(len(str(m.get("content", ""))) for m in messages),
                        len(text or ""), round(seconds, 2)))
            except sqlite3.Error:
                pass  # Protokoll darf den Lauf nie gefährden
        return record

    def decide(self, phase: str, art: str, titel: str, eingaben=None, regel: str | None = None, ergebnis=None,
               ausgang: str = "ok", call_id: int | None = None, backstage: bool = False) -> None:
        """Entscheidungsprotokoll (Nachvollzug): was ging hinein, nach welcher Regel, was kam heraus, wie ging es weiter.
        ausgang: info | ok (weitergeleitet) | warnung | eingriff (System griff ein) | mensch (wartet auf/kam von dir) | fehler"""
        if ausgang not in OUTCOMES:
            ausgang = "info"
        try:
            _write(self.path, "INSERT INTO run_events (run_id, call_id, phase, art, titel, eingaben, regel, ergebnis, "
                   "ausgang, backstage, sekunden) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (self.id, call_id, phase, art, str(titel)[:500], _json(eingaben), regel, _json(ergebnis), ausgang,
                    1 if backstage else 0, round(time.time() - self.started, 1)))
        except sqlite3.Error:
            pass  # Protokoll darf den Lauf nie gefährden

    def set_range(self, low: int, high: int, expected_chars: int, label: str = "KI schreibt") -> None:
        self.range, self.phase_label = (low, high, expected_chars), label

    def reset_text(self) -> None:
        self._live(text="", chars=0)

    def set_prompt(self, messages: list) -> None:
        _write(self.path, "UPDATE ai_runs SET prompt = ? WHERE id = ?",
               (json.dumps(messages, ensure_ascii=False), self.id))

    def set_response(self, text: str, model: str) -> None:
        _write(self.path, "UPDATE ai_runs SET response = ?, model = ? WHERE id = ?", (text, model, self.id))

    def finish(self, status: str, proposal_id: int | None = None, error: str | None = None) -> None:
        if status == "fertig":
            self.progress = 100
        duration = round(time.time() - self.started, 1)
        _write(self.path, "UPDATE ai_runs SET status = ?, progress = ?, proposal_id = ?, error = ?, "
                          "finished_at = CURRENT_TIMESTAMP, duration = ?, steps = ? WHERE id = ?",
               (status, self.progress, proposal_id, error, duration,
                json.dumps(self.steps, ensure_ascii=False), self.id))
        with _LOCK:
            LIVE.pop(self.key, None)
        stack = getattr(_CURRENT, "stack", None)
        if stack and self.id in stack:
            stack.reverse()
            stack.remove(self.id)  # den jüngsten Eintrag dieses Laufs entfernen
            stack.reverse()


OUTCOMES = ("info", "ok", "warnung", "eingriff", "mensch", "fehler")
TASK_PHASE = {"erwartung": "szenario", "bewerter": "szenario", "planer": "planer", "thema": "planer", "autor": "autor",
              "pruefer": "pruefer", "lektor": "lektor", "archivar": "archivar", "weltenbau": "weltentwicklung"}


def record_event(conn: sqlite3.Connection, run_id: int | None, phase: str, art: str, titel: str, eingaben=None,
                 regel: str | None = None, ergebnis=None, ausgang: str = "mensch", backstage: bool = False) -> None:
    """Ereignis außerhalb eines laufenden Laufs (z. B. deine Freigabe) nachträglich am Lauf vermerken."""
    if not run_id:
        return
    try:
        conn.execute("INSERT INTO run_events (run_id, phase, art, titel, eingaben, regel, ergebnis, ausgang, backstage) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (run_id, phase, art, str(titel)[:500], _json(eingaben), regel, _json(ergebnis),
                      ausgang if ausgang in OUTCOMES else "info", 1 if backstage else 0))
    except sqlite3.Error:
        pass


def live_for(path: str) -> dict:
    with _LOCK:
        return {s["run_id"]: dict(s) for s in LIVE.values() if s["path"] == path}


def live_by_job() -> dict:
    with _LOCK:
        return {s["job_id"]: dict(s) for s in LIVE.values() if s.get("job_id")}


def _row(row: sqlite3.Row, live: dict, reveal: bool, detail: bool) -> dict:
    out = dict(row)
    out["steps"] = json.loads(out.get("steps") or "[]")
    state = live.get(out["id"])
    if out["status"] == "laeuft":
        if state:
            out["progress"], out["phase"], out["chars"] = state["progress"], state["phase"], state["chars"]
            if detail and reveal:
                out["live_text"] = state["text"]
        else:
            out["status"] = "abgebrochen"  # Server wurde während des Laufs beendet
    if not (detail and reveal):
        out.pop("prompt", None)
        out.pop("response", None)
    elif out.get("prompt"):
        from . import stimmen
        out["prompt"] = [dict(m, content=stimmen.redact(str(m.get("content") or "")))
                         for m in json.loads(out["prompt"]) if isinstance(m, dict)]
    return out


def list_runs(conn: sqlite3.Connection, reveal: bool = False, limit: int = 100) -> list:
    live = live_for(_db_path(conn))
    rows = conn.execute("SELECT id, art, ziel, aufgabe, status, progress, steps, model, proposal_id, impulse_id, error, "
                        "started_at, finished_at, duration FROM ai_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [_row(r, live, reveal, False) for r in rows]


def get_run(conn: sqlite3.Connection, run_id: int, reveal: bool = False) -> dict:
    row = conn.execute("SELECT * FROM ai_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise LookupError("KI-Lauf nicht gefunden.")
    out = _row(row, live_for(_db_path(conn)), reveal, True)
    episode = conn.execute("SELECT id, release_nr, title, summary, word_count, status, form FROM episodes WHERE run_id = ?",
                           (run_id,)).fetchone()
    if episode:
        out["folge"] = dict(episode)
    out["aufrufe"] = list_calls(conn, run_id)  # nur Metadaten (Schritt, Modell, Größen) – Prompt/Antwort bleiben verborgen
    try:
        full = dict(row)
        full["steps"] = out["steps"]
        out["nachvollzug"] = trace(conn, full, out["aufrufe"], reveal)
    except Exception as exc:  # noqa: BLE001 – Nachvollzug darf die Lauf-Ansicht nie verhindern
        out["nachvollzug"] = {"modus": "fehler", "fehler": str(exc)[:300], "phasen": [], "summen": {}, "fehlt": []}
    if out.get("proposal_id"):
        p = conn.execute("SELECT summary, status, result FROM proposals WHERE id = ?", (out["proposal_id"],)).fetchone()
        if p:
            out["vorschlag"] = {"summary": p["summary"], "status": p["status"],
                                "result": json.loads(p["result"]) if p["result"] else None}
    return out



def list_calls(conn: sqlite3.Connection, run_id: int) -> list:
    """KI-Aufrufe eines Laufs ohne Prompt (der ist groß) – für die Übersicht und den Modellvergleich."""
    try:
        rows = conn.execute("SELECT id, step, task, model, ok, error, prompt_chars, response_chars, seconds, created_at "
                            "FROM ai_calls WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def trim_message(message: dict, head: int = 1500, tail: int = 5000) -> dict:
    """Nachricht für die Anzeige: Der große Kontext in der Mitte wird ausgelassen, Anfang und Ende (die eigentliche
    Aufgabe) bleiben stehen."""
    from . import stimmen
    text = stimmen.redact(str(message.get("content") or ""))
    out = {"role": message.get("role"), "zeichen": len(text), "content": text}
    if len(text) > head + tail + 500:
        out["content"] = (text[:head] + f"\n\n[… {len(text) - head - tail:,} Zeichen Kontext ausgelassen …]\n\n".replace(",", ".")
                          + text[-tail:])
        out["gekuerzt"] = True
    return out


def get_call(conn: sqlite3.Connection, call_id: int) -> dict:
    row = conn.execute("SELECT * FROM ai_calls WHERE id = ?", (call_id,)).fetchone()
    if row is None:
        raise LookupError("KI-Aufruf nicht gefunden.")
    out = dict(row)
    out["messages"] = json.loads(zlib.decompress(out["messages"]).decode("utf-8")) if out.get("messages") else []
    return out


# ---------------------------------------------------------------- Nachvollzug

PHASES = [("auftrag", "Auftrag & Gewichtung"), ("szenario", "Szenarien"), ("planer", "Planer"),
          ("vorbereitung", "Vorbereitung"), ("autor", "Autor"), ("pruefer", "Prüfer"), ("lektor", "Lektor"),
          ("speichern", "Speichern"), ("archivar", "Archivar"), ("bewertung", "Bewertung"), ("freigabe", "Freigabe"),
          ("weltentwicklung", "Weltentwicklung"), ("uebernahme", "Übernahme"), ("ablauf", "Ablauf"),
          ("abbruch", "Abbruch")]
RANK = {"info": 0, "ok": 1, "warnung": 2, "eingriff": 3, "mensch": 4, "fehler": 5}

# Protokollzeilen alter Läufe → (Phase, Art, Ausgang). Reihenfolge zählt: erster Treffer gewinnt.
_STEP_RULES = [
    (r"Wahl: Anfrage an |: Antwort von |Kontext fertig|^Fertig$|^Auftrag angenommen", None, None, None),
    (r"Wahl fehlgeschlagen", "?", "ersatzmodell", "eingriff"),
    (r"Antwort unvollständig .*Korrekturrunde", "?", "korrektur", "eingriff"),
    (r"^Szenario \d+ aus deiner Wahl", "szenario", "entscheidung", "mensch"),
    (r"^Szenarien warten auf deine Wahl", "szenario", "entscheidung", "mensch"),
    (r"^Szenario \d+ verworfen", "szenario", "eingriff", "eingriff"),
    (r"^Bewerter übersprungen", "szenario", "warnung", "warnung"),
    (r"^\d+ Szenarien geplant", "planer", "frage", "ok"),
    (r"^Plan nicht ausführbar", "vorbereitung", "eingriff", "eingriff"),
    (r"^Plan: ", "planer", "frage", "ok"),
    (r"^Vorbereitung übernommen", "vorbereitung", "weiterleitung", "ok"),
    (r"^Vorbereitung: ", "vorbereitung", "warnung", "warnung"),
    (r"^Genre gewählt", "vorbereitung", "gewichtung", "info"),
    (r"^Strang #\d+", "vorbereitung", "weiterleitung", "ok"),
    (r"^Autor.*verweigert|^Autor.*zu kurz", "autor", "eingriff", "eingriff"),
    (r"^Autor.*Wörter geschrieben", "autor", "bewertung", "ok"),
    (r"^Prüfer nutzt dasselbe Modell", "pruefer", "warnung", "warnung"),
    (r"^Prüfer übersprungen", "pruefer", "warnung", "warnung"),
    (r"^Prüfer: \d+ Hinweise", "pruefer", "pruefung", "auto"),
    (r"^Lektor.*übersprungen", "lektor", "warnung", "warnung"),
    (r"^Lektorat abgeschlossen", "lektor", "weiterleitung", "ok"),
    (r"^Folge #\d+ gespeichert", "speichern", "weiterleitung", "ok"),
    (r"^Bisheriger Text als Entwurf", "speichern", "eingriff", "eingriff"),
    (r"^Automatische Übernahme nicht möglich", "archivar", "entscheidung", "fehler"),
    (r"^Automatisch übernommen", "archivar", "entscheidung", "ok"),
    (r"^Archivar übersprungen", "archivar", "warnung", "warnung"),
    (r"^Archivar: ", "archivar", "frage", "ok"),
    (r"Warnung\(en\) zu Tabu", "bewertung", "warnung", "warnung"),
    (r"wartet auf deine Freigabe", "bewertung", "entscheidung", "mensch"),
    (r"^Weltentwicklung übersprungen", "weltentwicklung", "warnung", "warnung"),
    (r"^Weltentwicklung", "weltentwicklung", "weiterleitung", "info"),
    (r"^Abgebrochen", "abbruch", "fehler", "fehler"),
]


def _load(value):
    if value is None or value == "":
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _event_out(e: dict, reveal: bool) -> dict:
    out = {k: e.get(k) for k in ("id", "phase", "art", "titel", "regel", "ausgang", "sekunden", "call_id")}
    out["rekonstruiert"] = bool(e.get("rekonstruiert"))
    if e.get("backstage") and not reveal:
        out["verborgen"] = True
    else:
        out["eingaben"], out["ergebnis"] = _load(e.get("eingaben")), _load(e.get("ergebnis"))
    return out


def _label_phase(label: str, calls: list) -> str:
    """Phase einer Protokollzeile über das Präfix vor dem Doppelpunkt (z. B. „Autor, Kapitel 1/2: …“)."""
    head = label.split(":", 1)[0]
    for c in calls:
        if c.get("step") and head == c["step"]:
            return TASK_PHASE.get(c.get("task"), "ablauf")
    low = head.lower()
    for task, phase in TASK_PHASE.items():
        if low.startswith(task[:5]):
            return phase
    if low.startswith("prüfer"):
        return "pruefer"
    return "ablauf"


def _from_steps(steps: list, calls: list, skip: set) -> list:
    import re
    out = []
    for st in steps:
        text = str(st.get("text") or "")
        for pattern, phase, art, outcome in _STEP_RULES:
            if not re.search(pattern, text):
                continue
            if phase is None or phase in skip:
                break
            if phase == "?":
                phase = _label_phase(text, calls)
            if outcome == "auto":
                outcome = "ok" if st.get("stufe") == "ok" else "warnung"
            out.append({"phase": phase, "art": art, "titel": text[:300], "ausgang": outcome,
                        "sekunden": st.get("sekunden"), "rekonstruiert": True})
            break
        else:
            if st.get("stufe") in ("warnung", "fehler"):
                out.append({"phase": _label_phase(text, calls), "art": "warnung", "titel": text[:300],
                            "ausgang": "fehler" if st.get("stufe") == "fehler" else "warnung",
                            "sekunden": st.get("sekunden"), "rekonstruiert": True})
    return out


def _reconstruct(conn: sqlite3.Connection, run: dict, calls: list) -> tuple:
    """Nachvollzug für Läufe von vor dem Entscheidungsprotokoll – aus Protokoll, Szenarien, Prüfbericht und Messwerten."""
    from . import episodes, quality
    events: list = []
    missing: list = []
    steps = run.get("steps") or []
    lines = [line for line in (run.get("auftrag") or "").splitlines() if line.strip()]
    first = next((s["text"] for s in steps if str(s.get("text", "")).startswith("Auftrag angenommen")), "")
    events.append({"phase": "auftrag", "art": "gewichtung", "titel": "Vorgaben laut Auftrag und Protokoll",
                   "eingaben": json.dumps({"auftrag": lines, "protokoll": first}, ensure_ascii=False), "ausgang": "info",
                   "sekunden": 0, "rekonstruiert": True})
    missing.append("Einstellungen beim Start (Schwellen, Modelle je Aufgabe) – nur als Text im Protokoll")
    try:
        sset = conn.execute("SELECT * FROM scenario_sets WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                            (run["id"],)).fetchone()
    except sqlite3.OperationalError:
        sset = None
    if sset:
        params = _load(sset["params"]) or {}
        if sset["erwartung"]:
            events.append({"phase": "szenario", "art": "frage", "titel": "Erwartung des Hörers (Maßstab für die Überraschung)",
                           "ergebnis": sset["erwartung"], "ausgang": "ok", "rekonstruiert": True})
        rule = (f"Kommt in Frage: Kanon ≥ {params.get('min_kanon', 6):g}; davon gewinnt die Überraschung am nächsten "
                f"am Ziel {params.get('ziel', 0):g}. Harte Code-Prüfungen ziehen je 3 Kanon-Punkte ab.")
        for r in _load(sset["bewertungen"]) or []:
            if not isinstance(r, dict):
                continue
            k, u = r.get("kanonpassung"), r.get("ueberraschung")
            fits = k is not None and k >= float(params.get("min_kanon", 6))
            events.append({"phase": "szenario", "art": "bewertung", "rekonstruiert": True, "backstage": 1, "regel": rule,
                           "titel": f"Szenario {r.get('nr')} „{r.get('titel', '')}“: Kanon {k}, Überraschung {u}"
                                    + ("" if fits else " – fällt durch"),
                           "ergebnis": json.dumps({x: r.get(x) for x in ("kanonpassung", "ueberraschung", "fair",
                                                                         "widersprueche", "begruendung")}, ensure_ascii=False),
                           "ausgang": "ok" if fits else "warnung"})
        if sset["gewaehlt"]:
            human = params.get("wahl") == "ich"
            events.append({"phase": "szenario", "art": "entscheidung", "rekonstruiert": True, "regel": rule,
                           "titel": f"Gewählt: Szenario {sset['gewaehlt']}" + (f" – {params.get('begruendung')}"
                                                                              if params.get("begruendung") else ""),
                           "ausgang": "mensch" if human else "ok"})
    episode = conn.execute("SELECT id, status, check_report, metrics FROM episodes WHERE run_id = ?",
                           (run["id"],)).fetchone()
    report = _load(episode["check_report"]) if episode else None
    step_events = _from_steps(steps, calls, set())
    if sset:  # Szenario-Zeilen sind über scenario_sets schon vollständig da
        step_events = [e for e in step_events if not (e["phase"] == "szenario" and e["art"] in ("bewertung",))]
    if isinstance(report, list):
        step_events = [e for e in step_events if not (e["phase"] == "pruefer" and e["art"] == "pruefung")]
    events += step_events
    if isinstance(report, list):
        check_call = next((c["id"] for c in calls if c.get("task") == "pruefer" and c.get("ok")), None)
        rule = "hoch → Freigabe durch dich · mittel/niedrig → Korrektur an den Lektor · Tabu/Altersfreigabe → nur Warnung"
        if not report:
            events.append({"phase": "pruefer", "art": "pruefung", "titel": "Keine Probleme gefunden – weitergeleitet",
                           "regel": rule, "ausgang": "ok", "call_id": check_call, "rekonstruiert": True})
        for n, p in enumerate(report, 1):
            if not isinstance(p, dict):
                continue
            sev = p.get("schwere") or "?"
            events.append({"phase": "pruefer", "art": "pruefung", "regel": rule, "call_id": check_call, "backstage": 1,
                           "titel": f"Befund {n}: {sev}, Kapitel {p.get('kapitel', '?')}", "rekonstruiert": True,
                           "ausgang": "warnung" if p.get("warnung") or sev == "niedrig" else "eingriff",
                           "ergebnis": json.dumps(p, ensure_ascii=False)})
        missing.append("Ursprüngliche Schwere abgeschwächter Tabu-/Altersfreigabe-Befunde")
        events += _reconstruct_editor(conn, calls, report)
    if episode and episode["metrics"]:
        metrics = _load(episode["metrics"]) or {}
        q = metrics.get("qualitaet") or {}
        for test in episodes.QUALITY_SHOWN:
            value = q.get(test)
            if isinstance(value, list):
                value = round(sum(value) / len(value), 3) if value else None
            if value is None:
                continue
            spec = quality.TESTS.get(test, {})
            verdict = quality.judge(test, value)
            events.append({"phase": "bewertung", "art": "bewertung", "rekonstruiert": True,
                           "titel": f"{spec.get('label', test)}: {quality.fmt(test, value)}",
                           "regel": f"Grenze {spec.get('grenze')} ({spec.get('besser')} ist besser)",
                           "ergebnis": json.dumps({"test": test, "wert": value, "grenze": spec.get("grenze"),
                                                   "urteil": verdict}),
                           "ausgang": "ok" if verdict == "ok" else "warnung" if verdict == "warnung" else "info"})
    if episode:
        status = episode["status"]
        counts = {k: sum(1 for p in report or [] if isinstance(p, dict) and p.get("schwere") == k)
                  for k in ("hoch", "mittel", "niedrig")}
        if status in ("fertig", "freigabe") and not any(e["phase"] == "bewertung" and e["art"] == "entscheidung"
                                                        for e in events):
            released = conn.execute("SELECT ts FROM audit_log WHERE action = 'freigabe' AND table_name = 'episodes' "
                                    "AND row_id = ?", (episode["id"],)).fetchone()
            needs = counts["hoch"] > 0
            events.append({"phase": "bewertung", "art": "entscheidung", "rekonstruiert": True,
                           "titel": "Freigabe nötig – Folge wartet auf dich" if needs else "Kein Befund „hoch“ → fertig, ohne deine Freigabe",
                           "regel": "Mindestens ein Befund „hoch“ → Freigabe durch dich.",
                           "ergebnis": json.dumps(counts), "ausgang": "mensch" if needs else "ok"})
            if released:
                events.append({"phase": "freigabe", "art": "entscheidung", "titel": f"Du hast die Folge freigegeben ({released[0]} UTC)",
                               "ausgang": "mensch", "rekonstruiert": True})
    missing.append("Änderungen am Kanon sind diesem Lauf nicht eindeutig zugeordnet (erst ab jetzt mit Lauf-Bezug)")
    return events, missing


def _reconstruct_editor(conn: sqlite3.Connection, calls: list, report: list) -> list:
    """Autor- gegen Lektorfassung je Kapitel aus den gespeicherten KI-Antworten."""
    from . import episodes
    import re
    texts = {}
    for c in calls:
        if not c.get("ok") or c.get("task") not in ("autor", "lektor"):
            continue
        m = re.search(r"Kapitel (\d+)/", c.get("step") or "")
        if not m:
            continue
        row = conn.execute("SELECT response FROM ai_calls WHERE id = ?", (c["id"],)).fetchone()
        texts[(c["task"], int(m.group(1)))] = (row[0] if row else "", c["id"])  # letzte erfolgreiche Antwort zählt
    out = []
    for (task, nr), (after, call_id) in sorted(texts.items()):
        if task != "lektor" or ("autor", nr) not in texts:
            continue
        before = texts[("autor", nr)][0]
        after = episodes.normalize(after or "")
        before = episodes.normalize(before or "")
        fixes = [p for p in report if isinstance(p, dict) and str(p.get("kapitel")) == str(nr)]
        share = episodes._changed_share(before, after)
        checks = [{"beschreibung": f.get("beschreibung"), "korrektur": f.get("korrektur"),
                   "im_text_erkennbar": episodes._fix_visible(f, before, after)} for f in fixes]
        missing = [x for x in checks if x["im_text_erkennbar"] == "nein"]
        out.append({"phase": "lektor", "art": "eingriff" if fixes else "weiterleitung", "call_id": call_id,
                    "rekonstruiert": True, "backstage": 1 if fixes else 0,
                    "titel": f"Kapitel {nr}: {len(fixes)} Korrektur(en), {share * 100:.1f} % des Textes geändert"
                             + (f" – {len(missing)} nicht erkennbar" if missing else ""),
                    "regel": "„Im Text erkennbar“ ist eine Schätzung per Wortabgleich.",
                    "ergebnis": json.dumps({"geaendert_anteil": share, "korrekturen": checks}, ensure_ascii=False),
                    "ausgang": "warnung" if fixes and (share < 0.005 or missing) else "eingriff" if fixes else "ok"})
    return out


def trace(conn: sqlite3.Connection, run: dict, calls: list, reveal: bool = False) -> dict:
    """Nachvollzug eines Laufs: je Phase Gewichtungen, Fragen an die KI, Bewertungen und Eingriffe."""
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM run_events WHERE run_id = ? ORDER BY id", (run["id"],))]
    except sqlite3.OperationalError:
        rows = []
    missing: list = []
    mode = "erfasst"
    if not rows and run.get("art") == "Folge":
        rows, missing = _reconstruct(conn, run, calls)
        mode = "rekonstruiert"
    elif not rows:
        rows = _from_steps(run.get("steps") or [], calls, set())
        mode = "rekonstruiert" if rows else "leer"
    folge = run.get("art") == "Folge"
    if not folge:  # andere Läufe (Lücken füllen, Text einlesen …) haben keine Folgen-Phasen
        for e in rows:
            if e.get("phase") == "archivar":
                e["phase"] = "uebernahme"
    events = [_event_out(e, reveal) for e in rows]
    try:
        changes = [dict(r) for r in conn.execute(
            "SELECT ts, actor, action, table_name, row_id, backstage FROM audit_log WHERE run_id = ? ORDER BY id",
            (run["id"],))]
    except sqlite3.OperationalError:
        changes = []
    seen: dict = {}
    phases = []
    order = [p for p, _ in PHASES]
    by_phase: dict = {}
    for e in events:
        by_phase.setdefault(e["phase"] if e["phase"] in order else "ablauf", []).append(e)
    call_phase: dict = {}
    for c in calls:
        label = c.get("step") or c.get("task") or ""
        seen[label] = seen.get(label, 0) + 1
        item = dict(c, wiederholung=seen[label] > 1)
        call_phase.setdefault(TASK_PHASE.get(c.get("task"), "ablauf") if folge else "ablauf", []).append(item)
    for key, label in PHASES:
        evs, cs = by_phase.get(key, []), call_phase.get(key, [])
        if not evs and not cs:
            continue
        worst = max((RANK.get(e["ausgang"], 0) for e in evs), default=0)
        if any(not c.get("ok") for c in cs):
            worst = max(worst, RANK["eingriff"])
        status = next(k for k, v in RANK.items() if v == worst)
        phases.append({"id": key, "label": label, "status": status, "ereignisse": evs, "aufrufe": cs})
    totals = {k: sum(1 for e in events if e["ausgang"] == k) for k in RANK}
    visible_changes = [c for c in changes if reveal or not c["backstage"]]
    summary: dict = {}
    for c in visible_changes:
        key = f"{c['action']} {c['table_name'] or ''}".strip()
        summary[key] = summary.get(key, 0) + 1
    return {"modus": mode, "phasen": phases, "summen": totals, "fehlt": missing,
            "aenderungen": {"anzahl": len(changes), "sichtbar": summary,
                            "verborgen": len(changes) - len(visible_changes)}}
