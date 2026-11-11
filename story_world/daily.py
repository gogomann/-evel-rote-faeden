"""Täglicher Lauf: Nachrichten abrufen → als Impulse einarbeiten → nächste Folge erzeugen.

Jeder Schritt ist für sich gekapselt – ein Fehler (z. B. eine nicht erreichbare Nachrichtenquelle) verhindert die Folge nicht.
Schutz gegen doppelte Verarbeitung: Das Datum des letzten Laufs steht in world_meta (vor dem Start gesetzt) und
ein Sperr-Set verhindert parallele Läufe derselben Welt. Wiederanlauf: Läuft der Server erst nach der eingestellten
Uhrzeit, wird der Lauf am selben Tag nachgeholt.
"""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime

from . import episodes, llm, news, service, worlds

_RUNNING: set = set()
_LOCK = threading.Lock()


def _claim(slug: str) -> bool:
    with _LOCK:
        if slug in _RUNNING:
            return False
        _RUNNING.add(slug)
        return True


def _release(slug: str) -> None:
    with _LOCK:
        _RUNNING.discard(slug)


def run(slug: str, job_id: int | None = None) -> str:
    """Führt den täglichen Lauf für eine Welt aus und gibt einen kurzen Bericht zurück."""
    if not _claim(slug):
        return "Läuft bereits."
    report = []
    try:
        with worlds.open_world(slug) as conn:
            service.set_meta(conn, "auto_letzter_lauf", datetime.now().strftime("%Y-%m-%d"))
            service.audit(conn, "system", "taeglicher_lauf")
            conn.commit()
            try:
                fetched = news.fetch_all(conn)
                created = news.to_impulses(conn)
                report.append(f"{fetched['neu']} neue Meldungen, {len(created)} als Impuls")
                report += [f"Quelle: {e}" for e in fetched["fehler"]]
            except Exception as exc:
                conn.commit()
                created = []
                report.append(f"Nachrichten übersprungen: {exc}")
            for impulse_id in created:
                row = conn.execute("SELECT * FROM impulses WHERE id = ?", (impulse_id,)).fetchone()
                try:
                    service.set_impulse_status(conn, impulse_id, "in_arbeit")
                    conn.commit()
                    pid = llm.propose(conn, llm.impulse_task(dict(row)), impulse_id=impulse_id, aufgabe="weltenbau",
                                      art="Nachricht", ziel=row["title"])
                    state = conn.execute("SELECT status FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
                    if state == "offen":
                        service.set_impulse_status(conn, impulse_id, "vorschlag")
                    conn.commit()
                except Exception as exc:
                    conn.commit()
                    service.set_impulse_status(conn, impulse_id, "fehler", str(exc)[:600])
                    conn.commit()
                    report.append(f"Nachricht „{row['title'][:40]}“: {exc}")
            try:
                episode_id = episodes.produce(conn, job_id=job_id)
                if episode_id is None:
                    report.append("Szenarien warten auf deine Wahl")
                else:
                    title = conn.execute("SELECT title FROM episodes WHERE id = ?", (episode_id,)).fetchone()[0]
                    report.append(f"Folge „{title}“ erzeugt")
            except Exception as exc:
                report.append(f"Folge fehlgeschlagen: {exc}")
    finally:
        _release(slug)
    return " · ".join(report)


def due(conn, now: datetime) -> bool:
    if service.setting(conn, "auto_folge") != "1":
        return False
    hour, minute = (int(x) for x in service.setting(conn, "auto_uhrzeit").split(":"))
    last = service.meta(conn).get("auto_letzter_lauf")
    return (now.hour, now.minute) >= (hour, minute) and last != now.strftime("%Y-%m-%d")


def start_scheduler(start_job, interval: int = 30) -> threading.Thread:
    """Prüft regelmäßig alle Welten und startet fällige Läufe als Hintergrund-Jobs."""

    def loop():
        while True:
            try:
                now = datetime.now()
                for world in worlds.list_worlds():
                    slug = world["slug"]
                    try:
                        with worlds.open_world(slug) as conn:
                            if not due(conn, now) or slug in _RUNNING:
                                continue
                            # Datum vorab setzen: verhindert Doppelstart, auch wenn der Job später scheitert
                            service.set_meta(conn, "auto_letzter_lauf", now.strftime("%Y-%m-%d"))
                        start_job(slug, "Täglicher Lauf", now.strftime("%d.%m. %H:%M"),
                                  lambda job_id, s=slug: run(s, job_id))
                    except Exception:
                        traceback.print_exc()
            except Exception:
                traceback.print_exc()
            try:  # regelmäßiger Prüfstand (Einstellungen → Qualität), app-weit
                from . import pruefstand, quality
                today = datetime.now().strftime("%Y-%m-%d")
                if quality.bench_due(today):
                    quality.mark_bench(today)
                    q = quality.get_settings()
                    start_job(q["ballast"] or "", "Prüfstand", f"regelmäßig ({q['umfang']})",
                              lambda job_id, q=q: (pruefstand.run_bench(q["umfang"], None, q["ballast"] or None,
                                                                        q["kontext"], job_id) and "Prüfstand fertig."))
            except Exception:
                traceback.print_exc()
            time.sleep(interval)

    thread = threading.Thread(target=loop, daemon=True, name="story-world-zeitplan")
    thread.start()
    return thread
