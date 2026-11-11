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
                _write(self.path, "INSERT INTO ai_calls (run_id, step, task, model, ok, error, messages, response, "
                       "prompt_chars, response_chars, seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (self.id, step, task, model, 0 if error else 1, (error or "")[:2000] or None,
                        zlib.compress(raw.encode("utf-8"), 6), text, sum(len(str(m.get("content", ""))) for m in messages),
                        len(text or ""), round(seconds, 2)))
            except sqlite3.Error:
                pass  # Protokoll darf den Lauf nie gefährden
        return record

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
        out["prompt"] = json.loads(out["prompt"])
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
    episode = conn.execute("SELECT id, release_nr, title, summary, word_count, status FROM episodes WHERE run_id = ?",
                           (run_id,)).fetchone()
    if episode:
        out["folge"] = dict(episode)
    out["aufrufe"] = list_calls(conn, run_id)  # nur Metadaten (Schritt, Modell, Größen) – Prompt/Antwort bleiben verborgen
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


def get_call(conn: sqlite3.Connection, call_id: int) -> dict:
    row = conn.execute("SELECT * FROM ai_calls WHERE id = ?", (call_id,)).fetchone()
    if row is None:
        raise LookupError("KI-Aufruf nicht gefunden.")
    out = dict(row)
    out["messages"] = json.loads(zlib.decompress(out["messages"]).decode("utf-8")) if out.get("messages") else []
    return out
