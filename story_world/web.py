"""Lokale Verwaltungsoberfläche (nur Python-Standardbibliothek).

Sicherheit im lokalen Betrieb:
- bindet ausschließlich an 127.0.0.1
- prüft Host-Header (gegen DNS-Rebinding)
- schreibende Anfragen brauchen den Header X-Story-World und ggf. passenden Origin
  (ein fremder Browser-Tab kann diesen Header ohne CORS-Freigabe nicht senden)
- Backstage-Inhalte nur mit Header X-Reveal: 1, serverseitig gefiltert
"""

from __future__ import annotations

import base64
import http.client
import json
import re
import sqlite3
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import audio, tts, daily, episodes, genres, profiles, llm, textimport, news, timeline, migrations, providers, pruefstand, quality, runs, service, status, szenarien, vergleich, worlds

STATIC = Path(__file__).with_name("static")
FAVICON = STATIC / "favicon"
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/evel-icon.svg": ("evel-icon.svg", "image/svg+xml")}

JOBS: list = []
JOBS_LOCK = threading.Lock()


class HTTPError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- KI-Jobs

def _start_job(slug: str, art: str, ziel: str, fn) -> dict:
    job = {"id": int(time.time() * 1000), "welt": slug, "art": art, "ziel": ziel,
           "status": "laeuft", "meldung": "", "start": time.strftime("%H:%M:%S")}
    with JOBS_LOCK:
        JOBS.insert(0, job)
        del JOBS[30:]

    def run():
        try:
            message = fn(job["id"])
            job["status"], job["meldung"] = "fertig", message or "Fertig."
        except Exception as exc:  # Fehler sichtbar machen statt verschlucken
            job["status"], job["meldung"] = "fehler", str(exc)[:600]
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()
    return job


def _impulse_job(slug: str, impulse_id: int) -> dict:
    with worlds.open_world(slug) as conn:
        row = conn.execute("SELECT * FROM impulses WHERE id = ?", (impulse_id,)).fetchone()
        if row is None:
            raise HTTPError(404, "Impuls nicht gefunden.")
        if row["status"] == "in_arbeit":
            raise HTTPError(409, "Die KI arbeitet bereits an diesem Impuls.")
        impulse = dict(row)
        service.set_impulse_status(conn, impulse_id, "in_arbeit")

    def work(job_id):
        try:
            with worlds.open_world(slug) as conn:
                pid = llm.propose(conn, llm.impulse_task(impulse), impulse_id=impulse_id, aufgabe="weltenbau",
                                  art="Impuls", ziel=impulse["title"], job_id=job_id)
                state = conn.execute("SELECT status FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
                if state == "offen":
                    service.set_impulse_status(conn, impulse_id, "vorschlag")
                    return "Vorschlag wartet auf dich (Rückfragen)."
                return "Eingearbeitet."
        except Exception as exc:
            with worlds.open_world(slug) as conn:
                service.set_impulse_status(conn, impulse_id, "fehler", str(exc)[:600])
            raise

    return _start_job(slug, "Impuls", impulse["title"], work)


def _einschuebe_job(slug: str, anzahl: int, hinweis: str) -> dict:
    task = llm.einschuebe_task(anzahl, hinweis)

    def work(job_id):
        with worlds.open_world(slug) as conn:
            pid = llm.propose(conn, task, aufgabe="einschuebe", art="Einschübe", ziel=f"{anzahl} Einschübe",
                              job_id=job_id)
            state = conn.execute("SELECT status FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
            return "Einschübe ergänzt." if state == "uebernommen" else "Vorschlag wartet auf dich."

    return _start_job(slug, "Einschübe", f"{anzahl} Einschübe", work)


def _gaps_job(slug: str, table: str | None, row_id: int | None) -> dict:
    with worlds.open_world(slug) as conn:
        task = llm.gaps_task(conn, table, row_id)

    ziel_text = (service.ENTITIES[table]["label"] if table else "alle Bereiche") + (f" #{row_id}" if row_id else "")

    def work(job_id):
        with worlds.open_world(slug) as conn:
            pid = llm.propose(conn, task, aufgabe="luecken", art="Lücken füllen", ziel=ziel_text, job_id=job_id)
            state = conn.execute("SELECT status FROM proposals WHERE id = ?", (pid,)).fetchone()[0]
            return "Lücken gefüllt." if state == "uebernommen" else "Vorschlag wartet auf dich."

    ziel = service.ENTITIES[table]["label"] if table else "alle Bereiche"
    return _start_job(slug, "Lücken füllen", ziel + (f" #{row_id}" if row_id else ""), work)


# ---------------------------------------------------------------- Routing

ROUTES = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


W = r"/api/w/(?P<slug>[a-z0-9][a-z0-9_-]{0,47})"
T = r"(?P<table>[a-z_]+)"


@route("GET", "/api/worlds")
def get_worlds(req, body):
    return {"welten": worlds.list_worlds()}


@route("POST", "/api/worlds")
def post_world(req, body):
    slug = worlds.create_world(body.get("name", ""), body.get("beschreibung", ""), bool(body.get("startbestand", True)))
    return {"slug": slug}


@route("GET", "/api/status")
def get_status(req, body):
    return status.project_status()


@route("GET", "/api/config")
def get_config(req, body):
    return {
        "entities": {k: {"label": v["label"], "singular": v["singular"], "title": v["title"],
                         "fields": [{"name": f[0], "label": f[1], "type": f[2], "required": f[3], "secret": f[4]}
                                    for f in v["fields"]]}
                     for k, v in service.ENTITIES.items()},
        "impuls_arten": list(service.IMPULSE_KINDS),
        "ort_rang": {k: service.ort_rang(k) for k in service.ORT_ARTEN},
        "stufen": {k: service.stufe_label(k) for k in (*service.MASSSTAB_LABEL, *service.ORT_ARTEN)},
    }


# ---- Einstellungen (app-weit): Anbieter, Modelle je Aufgabe, Darstellung

P = r"/api/settings/providers/(?P<pid>[A-Za-z0-9_]+)"


@route("GET", "/api/settings")
def get_settings(req, body):
    return providers.public_settings()


@route("POST", "/api/settings/providers")
def post_provider(req, body):
    return {"id": providers.add_provider(body)}


@route("PUT", P)
def put_provider(req, body, pid):
    return providers.update_provider(pid, body)


@route("POST", P + "/archivieren")
def post_provider_archive(req, body, pid):
    providers.archive_provider(pid)
    return {"ok": True}


@route("POST", P + "/wiederherstellen")
def post_provider_restore(req, body, pid):
    providers.restore_provider(pid)
    return {"ok": True}


@route("POST", P + "/pruefen")
def post_provider_verify(req, body, pid):
    try:
        return providers.verify(pid)
    except providers.ProviderError as exc:
        return {"ok": False, "fehler": str(exc)}


@route("POST", P + "/modelle")
def post_provider_models(req, body, pid):
    try:
        return dict(providers.load_models(pid), ok=True)
    except providers.ProviderError as exc:
        return {"ok": False, "fehler": str(exc)}


@route("GET", P + "/modelle")
def get_provider_models(req, body, pid):
    return {"modelle": providers.get_provider(pid).get("models", [])}


@route("PUT", r"/api/settings/tasks/(?P<task>[a-z_]+)")
def put_task(req, body, task):
    before = providers.load()["tasks"].get(task, [])
    chain = providers.set_chain(task, body.get("kette", []))
    if chain and (not before or before[0] != chain[0]):
        label = dict((t[0], t[1]) for t in providers.TASKS).get(task, task)
        quality.hint(f"modellwechsel:{task}", f"Modell für „{label}“ geändert ({chain[0]['model']}) – "
                                              "Prüfstand empfohlen, damit du siehst, ob es im Rahmen arbeitet.")
    return {"kette": chain}


@route("PUT", r"/api/settings/tasks/(?P<task>[a-z_]+)/werte")
def put_task_params(req, body, task):
    try:
        return {"werte": providers.set_task_params(task, body)}
    except ValueError as exc:
        raise HTTPError(400, str(exc))


# ---- Qualität (app-weit): Übersicht, Prüfstand, Referenzen, Serien

@route("GET", "/api/qualitaet")
def get_quality(req, body):
    data = quality.overview()
    for s in data["serien"]:
        s["ergebnis"] = vergleich.public(s["ergebnis"], req.reveal)
    data["einstellungen"] = quality.get_settings()
    data["pruefstand_aufgaben"] = pruefstand.TASK_TESTS
    data["welten"] = worlds.list_worlds()
    return data


@route("PUT", "/api/qualitaet/einstellungen")
def put_quality_settings(req, body):
    try:
        return quality.set_settings(body)
    except ValueError as exc:
        raise HTTPError(400, str(exc))


def _bench_job(umfang: str, modelle: dict | None, ballast: str | None, kontext: str, titel: str) -> dict:
    sid = quality.series_start("pruefstand", titel, ballast)

    def work(job_id):
        result = pruefstand.run_bench(umfang, modelle, ballast, kontext, job_id, sid=sid)
        return f"Prüfstand fertig ({len(result['modelle'])} Modell(e), {result.get('dauer', 0):.0f} s)."

    job = _start_job(ballast or "", "Prüfstand", titel, work)
    job["serie"] = sid
    return job


@route("POST", "/api/qualitaet/pruefstand")
def post_bench(req, body):
    umfang = "voll" if body.get("umfang") == "voll" else "schnell"
    kontext = "kaskade" if body.get("kontext") == "kaskade" else "voll"
    ballast = body.get("ballast") or None
    if ballast:
        worlds.path_for(ballast)
    modelle = body.get("modelle") if isinstance(body.get("modelle"), dict) else None
    titel = f"Prüfstand {umfang}" + (f", Ballast {ballast}" if ballast else "") + f", Kontext {kontext}"
    return {"job": _bench_job(umfang, modelle, ballast, kontext, titel)}


@route("GET", r"/api/qualitaet/serien/(?P<sid>[a-z0-9]+)")
def get_quality_series(req, body, sid):
    data = quality.get_series(sid)
    data["ergebnis"] = vergleich.public(data["ergebnis"], req.reveal)
    return data


@route("POST", "/api/qualitaet/referenz")
def post_quality_reference(req, body):
    return {"gesetzt": quality.set_reference(body.get("modell") or None, body.get("test") or None)}


@route("GET", "/api/qualitaet/verlauf")
def get_quality_history(req, body):
    q = _query(req)
    return {"verlauf": quality.history(q.get("test", ""), q.get("modell") or None)}


@route("POST", "/api/qualitaet/hinweise/erledigt")
def post_quality_hints_done(req, body):
    quality.close_hints(body.get("art") or "")
    return {"ok": True}


@route("POST", r"/api/settings/tasks/(?P<task>[a-z_]+)/test")
def post_task_test(req, body, task):
    try:
        return providers.test_chain(task)
    except providers.ProviderError as exc:
        return {"ok": False, "fehler": str(exc)}


@route("PUT", "/api/settings/theme")
def put_theme(req, body):
    return providers.save_theme(body)


@route("GET", "/api/jobs")
def get_jobs(req, body):
    live = runs.live_by_job()
    with JOBS_LOCK:
        jobs = [dict(j) for j in JOBS]
    for job in jobs:
        state = live.get(job["id"])
        if state:
            job.update(progress=state["progress"], phase=state["phase"], run_id=state["run_id"])
    return {"jobs": jobs}


@route("GET", W + "/overview")
def get_overview(req, body, slug):
    with worlds.open_world(slug) as conn:
        gaps = service.gaps(conn, req.reveal)
        impulses = conn.execute("SELECT status, COUNT(*) n FROM impulses GROUP BY status").fetchall()
        return {
            "meta": service.meta(conn),
            "ki_eingerichtet": providers.public_settings()["eingerichtet"],
            "bestand": service.stats(conn),
            "luecken": len(gaps["items"]), "luecken_verborgen": gaps["hidden"],
            "impulse": {r["status"]: r["n"] for r in impulses},
            "vorschlaege_offen": conn.execute("SELECT COUNT(*) FROM proposals WHERE status='offen'").fetchone()[0],
            "termine": [
                r for r in service.list_rows(conn, "events", req.reveal)["rows"] if r.get("important")
            ][:20],
        }


@route("GET", W + "/rows/" + T)
def get_rows(req, body, slug, table):
    with worlds.open_world(slug) as conn:
        return service.list_rows(conn, table, req.reveal)


@route("POST", W + "/rows/" + T)
def post_row(req, body, slug, table):
    with worlds.open_world(slug) as conn:
        vis = body.pop("visibility", "offen") if req.reveal else "offen"
        new_id = service.create_row(conn, table, body, "nutzer", vis, req.reveal)
        return {"id": new_id}


@route("GET", W + "/rows/" + T + r"/(?P<row_id>\d+)")
def get_one(req, body, slug, table, row_id):
    with worlds.open_world(slug) as conn:
        return service.get_row(conn, table, int(row_id), req.reveal)


@route("PUT", W + "/rows/" + T + r"/(?P<row_id>\d+)")
def put_row(req, body, slug, table, row_id):
    with worlds.open_world(slug) as conn:
        return service.update_row(conn, table, int(row_id), body, "nutzer", req.reveal)


@route("DELETE", W + "/rows/" + T + r"/(?P<row_id>\d+)")
def delete_row(req, body, slug, table, row_id):
    with worlds.open_world(slug) as conn:
        service.delete_row(conn, table, int(row_id), req.reveal)
        return {"ok": True}


@route("GET", W + r"/dossier/(?P<kind>locations|characters)/(?P<row_id>\d+)")
def get_dossier(req, body, slug, kind, row_id):
    with worlds.open_world(slug) as conn:
        fn = service.location_dossier if kind == "locations" else service.character_dossier
        return fn(conn, int(row_id), req.reveal)


@route("GET", W + "/gaps")
def get_gaps(req, body, slug):
    with worlds.open_world(slug) as conn:
        return service.gaps(conn, req.reveal)


@route("POST", W + "/gaps/ki")
def post_gaps_ki(req, body, slug):
    table = body.get("table") or None
    if table is not None and table not in service.ENTITIES:
        raise HTTPError(400, "Unbekannter Bereich.")
    row_id = int(body["id"]) if body.get("id") else None
    return {"job": _gaps_job(slug, table, row_id)}


@route("POST", W + "/einschuebe/ki")
def post_einschuebe_ki(req, body, slug):
    worlds.path_for(slug)
    return {"job": _einschuebe_job(slug, int(body.get("anzahl") or 6), body.get("hinweis", ""))}


@route("GET", W + "/impulses")
def get_impulses(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"impulse": service.list_impulses(conn)}


@route("POST", W + "/impulses")
def post_impulse(req, body, slug):
    with worlds.open_world(slug) as conn:
        new_id = service.create_impulse(conn, body.get("title", ""), body.get("content", ""),
                                        body.get("kind", "sonstiges"))
    job = _impulse_job(slug, new_id) if body.get("ki_sofort") else None
    return {"id": new_id, "job": job}


@route("POST", W + r"/impulses/(?P<impulse_id>\d+)/ki")
def post_impulse_ki(req, body, slug, impulse_id):
    return {"job": _impulse_job(slug, int(impulse_id))}


@route("POST", W + r"/impulses/(?P<impulse_id>\d+)/verwerfen")
def post_impulse_reject(req, body, slug, impulse_id):
    with worlds.open_world(slug) as conn:
        service.set_impulse_status(conn, int(impulse_id), "verworfen")
        return {"ok": True}


@route("GET", W + "/proposals")
def get_proposals(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"vorschlaege": service.list_proposals(conn, req.reveal)}


@route("POST", W + r"/proposals/(?P<pid>\d+)/uebernehmen")
def post_accept(req, body, slug, pid):
    with worlds.open_world(slug) as conn:
        return service.apply_proposal(conn, int(pid))


@route("POST", W + r"/proposals/(?P<pid>\d+)/verwerfen")
def post_reject(req, body, slug, pid):
    with worlds.open_world(slug) as conn:
        service.reject_proposal(conn, int(pid))
        return {"ok": True}


@route("GET", W + "/search")
def get_search(req, body, slug):
    query = parse_qs(urlparse(req.path).query).get("q", [""])[0]
    with worlds.open_world(slug) as conn:
        return {"treffer": service.search(conn, query, req.reveal)}


@route("POST", W + "/backup")
def post_backup(req, body, slug):
    with worlds.open_world(slug) as conn:
        target = migrations.backup(conn, worlds.path_for(slug), "manuell")
        service.audit(conn, "nutzer", "sicherung", detail=target.name)
        return {"datei": str(target)}


@route("POST", W + "/settings")
def post_settings(req, body, slug):
    with worlds.open_world(slug) as conn:
        for key, value in body.items():
            service.set_setting(conn, key, value)
        return service.meta(conn)["einstellungen"]


def _episode_job(slug: str, wish: str, thread_id: int | None, words: int | None, genre_id: int | None = None,
                 profile_id: str | None = None, age_rating: str | None = None, abweichung: int | None = None,
                 anzahl: int | None = None, scenario_set_id: int | None = None, scenario_nr: int | None = None) -> dict:
    def work(job_id):
        with worlds.open_world(slug) as conn:
            episode_id = episodes.produce(conn, wish, thread_id, words, job_id=job_id, genre_id=genre_id,
                                          profile_id=profile_id, age_rating=age_rating, abweichung=abweichung,
                                          szenarien_anzahl=anzahl, scenario_set_id=scenario_set_id,
                                          scenario_nr=scenario_nr)
            if episode_id is None:
                return "Szenarien warten auf deine Wahl – Seite „Geschichten“."
            title = conn.execute("SELECT title FROM episodes WHERE id = ?", (episode_id,)).fetchone()[0]
            return f"Folge „{title}“ ist fertig."

    return _start_job(slug, "Folge", wish.strip()[:60] or ("gewähltes Szenario" if scenario_set_id else "nächste Folge"), work)


def _small_int(value, low: int, high: int, label: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise HTTPError(400, f"{label} muss eine Zahl sein.")
    if not low <= number <= high:
        raise HTTPError(400, f"{label} bitte zwischen {low} und {high}.")
    return number


@route("POST", W + "/episodes/ki")
def post_episode_ki(req, body, slug):
    worlds.path_for(slug)
    thread_id = int(body["thread_id"]) if body.get("thread_id") else None
    words = int(body["woerter"]) if body.get("woerter") else None
    if words is not None and not 500 <= words <= 20000:
        raise HTTPError(400, "Länge bitte zwischen 500 und 20.000 Wörtern.")
    genre_id = int(body["genre_id"]) if body.get("genre_id") else None
    wish = str(body.get("wunsch") or "")
    if body.get("neue_geschichte") and not thread_id:
        wish = ("NEUE GESCHICHTE: Lege einen neuen Strang an und setze keinen bestehenden fort."
                + (f" {wish.strip()}" if wish.strip() else ""))
    parts = [f"{label}: {str(body.get(key) or '').strip()[:1500]}"
             for key, label in (("anfang", "ANFANG"), ("mitte", "MITTE"), ("ende", "ENDE")) if str(body.get(key) or "").strip()]
    if parts:
        wish = (wish.strip() + "\n" if wish.strip() else "") + "VORGABEN FÜR DIE TEILE (verbindlich):\n" + "\n".join(parts)
    age = str(body.get("altersfreigabe") or "").strip()
    if len(age) > 40:
        raise HTTPError(400, "Altersfreigabe bitte kurz halten (z. B. „ab 12“).")
    abweichung = _small_int(body.get("abweichung"), 0, 3, "Überraschung")
    anzahl = _small_int(body.get("szenarien"), 1, 3, "Anzahl Szenarien")
    return {"job": _episode_job(slug, wish, thread_id, words, genre_id, body.get("profil_id") or None, age or None,
                                abweichung, anzahl)}


@route("GET", W + "/szenarien")
def get_scenarios(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"offen": szenarien.open_sets(conn, req.reveal)}


@route("GET", W + r"/szenarien/(?P<set_id>\d+)")
def get_scenario_set(req, body, slug, set_id):
    with worlds.open_world(slug) as conn:
        return szenarien.get_set(conn, int(set_id), req.reveal)


@route("POST", W + r"/szenarien/(?P<set_id>\d+)/waehlen")
def post_scenario_choose(req, body, slug, set_id):
    nr = _small_int(body.get("nr"), 1, 3, "Szenario") or 1
    with worlds.open_world(slug) as conn:
        s = szenarien.get_set(conn, int(set_id), True)
        if s["status"] != "offen":
            raise HTTPError(409, "Diese Szenarien wurden schon entschieden.")
        run = conn.execute("SELECT auftrag FROM ai_runs WHERE id = ?", (s["run_id"],)).fetchone()
    auftrag = run[0] if run else ""
    words = None
    for line in (auftrag or "").splitlines():
        if line.startswith("Neue Folge erzeugen (Ziel ca. "):
            digits = "".join(ch for ch in line.split("ca. ", 1)[1].split(" ")[0] if ch.isdigit())
            words = int(digits) if digits else None
    return {"job": _episode_job(slug, "", None, words, body.get("genre_id") or None, body.get("profil_id") or None,
                                body.get("altersfreigabe") or None, scenario_set_id=int(set_id), scenario_nr=nr)}


@route("POST", W + r"/szenarien/(?P<set_id>\d+)/verwerfen")
def post_scenario_reject(req, body, slug, set_id):
    with worlds.open_world(slug) as conn:
        szenarien.reject_set(conn, int(set_id))
    return {"ok": True}


@route("POST", W + r"/aufrufe/(?P<call_id>\d+)/vergleich")
def post_compare(req, body, slug, call_id):
    modelle = body.get("modelle") if isinstance(body.get("modelle"), list) else []
    if not modelle:
        raise HTTPError(400, "Bitte mindestens ein Modell wählen.")
    with worlds.open_world(slug) as conn:
        call = runs.get_call(conn, int(call_id))
    sid = quality.series_start("vergleich", f"Vergleich: {call.get('step') or call.get('task')}", slug)

    def work(job_id):
        result = vergleich.compare(slug, int(call_id), modelle, bool(body.get("richter", True)), sid=sid)
        best = (result.get("richter") or {}).get("bester")
        return "Vergleich fertig" + (f" – vorn: {best}" if best else "") + "."

    job = _start_job(slug, "Modellvergleich", call.get("step") or call.get("task") or "Aufruf", work)
    job["serie"] = sid
    return {"job": job, "serie": sid}


@route("GET", W + r"/aufrufe/(?P<call_id>\d+)")
def get_call(req, body, slug, call_id):
    if not req.reveal:
        raise HTTPError(403, "Prompt und Antwort können Geheimnisse enthalten – nur mit Backstage sichtbar.")
    with worlds.open_world(slug) as conn:
        call = runs.get_call(conn, int(call_id))
    call.pop("messages", None)
    return call


@route("GET", W + "/stories")
def get_stories(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"geschichten": episodes.stories(conn), "altersstufen": list(genres.AGE_RATINGS),
                "genres": [dict(r) for r in conn.execute(
                    "SELECT id, name, description, age_rating, taboos, abweichung FROM genres WHERE visibility = 'offen' ORDER BY id")]}


@route("GET", W + "/episodes")
def get_episodes(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"folgen": episodes.list_episodes(conn)}


@route("GET", W + r"/episodes/(?P<episode_id>\d+)")
def get_episode(req, body, slug, episode_id):
    with worlds.open_world(slug) as conn:
        return episodes.get_episode(conn, int(episode_id), req.reveal)


def _query(req) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(req.path).query).items()}


@route("GET", W + "/zeit")
def get_zeit(req, body, slug):
    q = _query(req)
    with worlds.open_world(slug) as conn:
        latest = conn.execute("SELECT MAX(world_time_cursor) FROM threads").fetchone()[0] or 0
        t = float(q.get("t") or latest)
        return {"weltzeit": t, "aktuell": latest, "zustand": timeline.world_state(conn, t, req.reveal)}


@route("GET", W + "/reise")
def get_reise(req, body, slug):
    q = _query(req)
    with worlds.open_world(slug) as conn:
        return timeline.travel(conn, int(q["von"]), int(q["nach"]), req.reveal)


@route("GET", W + "/konsistenz")
def get_konsistenz(req, body, slug):
    with worlds.open_world(slug) as conn:
        return timeline.check(conn, req.reveal)


@route("POST", W + r"/episodes/(?P<episode_id>\d+)/freigeben")
def post_episode_release(req, body, slug, episode_id):
    with worlds.open_world(slug) as conn:
        cur = conn.execute("UPDATE episodes SET status = 'fertig' WHERE id = ? AND status = 'freigabe'", (int(episode_id),))
        if not cur.rowcount:
            raise HTTPError(409, "Folge wartet nicht auf Freigabe.")
        service.audit(conn, "nutzer", "freigabe", "episodes", int(episode_id))
        return {"ok": True}


@route("GET", W + "/news")
def get_news(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"quellen": news.sources(conn), "meldungen": news.items(conn)}


@route("POST", W + "/news/sources")
def post_news_source(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"id": news.add_source(conn, body.get("name", ""), body.get("url", ""))}


@route("POST", W + r"/news/sources/(?P<sid>\d+)/umschalten")
def post_news_toggle(req, body, slug, sid):
    with worlds.open_world(slug) as conn:
        news.toggle_source(conn, int(sid))
        return {"ok": True}


@route("POST", W + "/news/abrufen")
def post_news_fetch(req, body, slug):
    with worlds.open_world(slug) as conn:
        report = news.fetch_all(conn)
        report["impulse"] = news.to_impulses(conn) if body.get("als_impulse") else []
        return report


@route("POST", W + "/daily/run")
def post_daily_run(req, body, slug):
    worlds.path_for(slug)
    return {"job": _start_job(slug, "Täglicher Lauf", "jetzt", lambda job_id: daily.run(slug, job_id))}


# ---- Menschen & Erzählprofile (app-weit, kein Login)

U = r"/api/profiles/(?P<pid>u_[0-9a-f]{8})"


@route("GET", "/api/profiles")
def get_profiles(req, body):
    return dict(profiles.list_profiles(), fragen=profiles.QUESTIONS,
                felder=[{"id": k, "label": v} for k, v in profiles.PROFILE_FIELDS])


@route("POST", "/api/profiles")
def post_profile(req, body):
    try:
        return profiles.create(body.get("name", ""))
    except profiles.ProfileError as exc:
        raise HTTPError(400, str(exc))


@route("POST", U + "/aktiv")
def post_profile_active(req, body, pid):
    profile = profiles.touch(pid)
    slug = body.get("welt")
    if slug:
        with worlds.open_world(slug) as conn:
            service.set_meta(conn, "nutzer_id", pid)
    return profile


@route("PUT", U + "/antworten")
def put_profile_answers(req, body, pid):
    return profiles.save_answers(pid, body.get("antworten") or {})


@route("PUT", U + "/nachfragen")
def put_profile_followups(req, body, pid):
    return profiles.save_followups(pid, body.get("antworten") or [])


@route("POST", U + "/auswerten")
def post_profile_analyze(req, body, pid):
    try:
        return profiles.analyze(pid)
    except (profiles.ProfileError, llm.LLMError) as exc:
        raise HTTPError(400, str(exc))


@route("PUT", U + "/profil")
def put_profile_fields(req, body, pid):
    return profiles.edit_profile(pid, body.get("profil") or {})


@route("GET", U)
def get_profile(req, body, pid):
    p = profiles.get(pid)
    if p is None:
        raise HTTPError(404, "Profil nicht gefunden.")
    return dict(p, fragen=profiles.QUESTIONS, felder=[{"id": k, "label": v} for k, v in profiles.PROFILE_FIELDS],
                formate=list(textimport.FORMATS))


T = U + r"/texte/(?P<tid>t_[0-9a-f]{8})"


@route("POST", U + "/texte")
def post_profile_text(req, body, pid):
    text = body.get("text") or ""
    name = str(body.get("dateiname") or "")
    if body.get("daten_b64"):
        try:
            data = base64.b64decode(body["daten_b64"], validate=True)
        except (ValueError, TypeError):
            raise HTTPError(400, "Datei konnte nicht übertragen werden.")
        try:
            text = textimport.extract(name, data)
        except textimport.ImportError_ as exc:
            raise HTTPError(400, str(exc))
    try:
        title = body.get("titel") or (name.rsplit(".", 1)[0] if name else "")
        return profiles.add_text(pid, title, text, name or "eingefügt", bool(body.get("stil", True)))
    except profiles.ProfileError as exc:
        raise HTTPError(400, str(exc))


@route("GET", T)
def get_profile_text(req, body, pid, tid):
    return {"text": profiles.read_text(pid, tid)}


@route("PUT", T)
def put_profile_text(req, body, pid, tid):
    return profiles.update_text(pid, tid, body)


@route("POST", T + "/archivieren")
def post_profile_text_archive(req, body, pid, tid):
    return profiles.archive_text(pid, tid)


@route("POST", T + "/wiederherstellen")
def post_profile_text_restore(req, body, pid, tid):
    return profiles.archive_text(pid, tid, back=True)


@route("POST", W + "/texte/einlesen")
def post_text_import(req, body, slug):
    pid, tid = str(body.get("profil_id") or ""), str(body.get("text_id") or "")
    p = profiles.get(pid)
    meta = next((t for t in (p or {}).get("texte", []) if t["id"] == tid), None)
    if meta is None:
        raise HTTPError(404, "Text nicht gefunden.")
    parts = profiles.split_text(profiles.read_text(pid, tid))
    hint = str(body.get("hinweis") or "").strip()[:1000]

    def work(job_id):
        done, waiting, empty, failed = 0, 0, 0, []
        for i, part in enumerate(parts, 1):
            title = f"{meta['titel']} – Teil {i}/{len(parts)}" if len(parts) > 1 else meta["titel"]
            with worlds.open_world(slug) as conn:
                impulse_id = service.create_impulse(conn, title, part + (f"\n\nHINWEIS DES NUTZERS: {hint}" if hint else ""),
                                                    "text")
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
                except Exception as exc:  # ein Abschnitt darf die anderen nicht aufhalten
                    service.set_impulse_status(conn, impulse_id, "fehler", str(exc)[:600])
                    failed.append(f"Teil {i}: {str(exc)[:120]}")
                conn.commit()
        profiles.note_import(pid, tid, slug, len(parts))
        message = (f"{done + empty} von {len(parts)} Abschnitten verarbeitet" + (f", {waiting} Vorschläge warten auf dich" if waiting else "")
                   + (f", {empty} ohne neues Weltwissen" if empty else ""))
        if failed and not done and not empty:
            raise RuntimeError(message + ". " + " · ".join(failed[:3]))
        return message + (f". Fehler: {' · '.join(failed[:3])}" if failed else ".")

    return {"job": _start_job(slug, "Text einlesen", meta["titel"], work), "teile": len(parts)}


@route("POST", U + "/archivieren")
def post_profile_archive(req, body, pid):
    profiles.archive(pid)
    return {"ok": True}


@route("POST", U + "/wiederherstellen")
def post_profile_restore(req, body, pid):
    profiles.restore(pid)
    return {"ok": True}


@route("GET", "/api/backups")
def get_backups(req, body):
    return {"sicherungen": worlds.list_backups()}


@route("POST", "/api/backups/wiederherstellen")
def post_restore(req, body):
    return {"slug": worlds.restore_backup(body.get("datei", ""))}


@route("GET", "/api/audio/stimmen")
def get_voices(req, body):
    all_voices = audio.voices()
    return {"verfuegbar": audio.available(), "deutsch": audio.german(all_voices), "alle": all_voices}


@route("POST", W + r"/episodes/(?P<episode_id>\d+)/audio")
def post_episode_audio(req, body, slug, episode_id):
    worlds.path_for(slug)
    if not audio.available():
        raise HTTPError(400, "Vertonung braucht den macOS-Befehl „say“. Nutze sonst den JSON-Export für ein anderes TTS.")

    def work(job_id):
        with worlds.open_world(slug) as conn:
            path = audio.render(conn, slug, int(episode_id), job_id=job_id)
        return f"Hörbuch fertig: {path.name}"

    return {"job": _start_job(slug, "Hörbuch", f"Folge #{episode_id}", work)}


@route("GET", W + r"/episodes/(?P<episode_id>\d+)/export.json")
def get_episode_json(req, body, slug, episode_id):
    with worlds.open_world(slug) as conn:
        return audio.export_json(conn, int(episode_id))


# ---- TTS-Server (app-weit) und Vertonung über TTS-Server (je Folge)

TS = r"/api/tts/server/(?P<sid>t_[0-9a-f]{8})"


@route("GET", "/api/tts")
def get_tts(req, body):
    return tts.public_settings()


@route("POST", "/api/tts/server")
def post_tts_server(req, body):
    try:
        return {"id": tts.add_server(body)}
    except ValueError as exc:
        raise HTTPError(400, str(exc))


@route("PUT", TS)
def put_tts_server(req, body, sid):
    try:
        return tts.update_server(sid, body)
    except ValueError as exc:
        raise HTTPError(400, str(exc))


@route("POST", TS + "/pruefen")
def post_tts_verify(req, body, sid):
    return tts.verify(sid)


@route("POST", TS + "/archivieren")
def post_tts_archive(req, body, sid):
    tts.archive_server(sid)
    return {"ok": True}


@route("POST", TS + "/wiederherstellen")
def post_tts_restore(req, body, sid):
    tts.restore_server(sid)
    return {"ok": True}


def _tts_state(conn, slug: str, episode_id: int) -> dict:
    p = tts.plan(conn, episode_id)
    out = tts.output_file(conn, slug, episode_id)
    return {"einstellung": p["einstellung"], "modus": p["modus"], "modi": tts.MODI, "sprecher": p["sprecher"],
            "fehlt": p["fehlt"], "besetzung": tts.cast(conn), "server_anzahl": len(tts.servers()),
            "datei": out.name if out else None,
            "erstellt": time.strftime("%d.%m.%Y %H:%M", time.localtime(out.stat().st_mtime)) if out else None}


@route("GET", W + r"/episodes/(?P<episode_id>\d+)/tts")
def get_episode_tts(req, body, slug, episode_id):
    with worlds.open_world(slug) as conn:
        return _tts_state(conn, slug, int(episode_id))


@route("PUT", W + r"/episodes/(?P<episode_id>\d+)/tts")
def put_episode_tts(req, body, slug, episode_id):
    with worlds.open_world(slug) as conn:
        try:
            tts.set_episode_settings(conn, int(episode_id), {k: body[k] for k in ("modus", "stimme") if k in body})
            if isinstance(body.get("besetzung"), dict):
                tts.set_cast(conn, body["besetzung"])
        except ValueError as exc:
            raise HTTPError(400, str(exc))
        conn.commit()
        return _tts_state(conn, slug, int(episode_id))


@route("POST", W + r"/episodes/(?P<episode_id>\d+)/tts/vertonen")
def post_episode_tts_render(req, body, slug, episode_id):
    with worlds.open_world(slug) as conn:
        p = tts.plan(conn, int(episode_id))
    if p["fehlt"]:
        raise HTTPError(400, "Keine Stimme für: " + ", ".join(p["fehlt"]) + ".")

    def work(job_id):
        with worlds.open_world(slug) as conn:
            path = tts.render(conn, slug, int(episode_id), job_id=job_id)
        return f"Hörbuch (TTS-Server) fertig: {path.name}"

    return {"job": _start_job(slug, "Hörbuch (TTS)", f"Folge #{episode_id}", work)}


@route("GET", W + "/runs")
def get_runs(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"laeufe": runs.list_runs(conn, req.reveal)}


@route("GET", W + r"/runs/(?P<run_id>\d+)")
def get_run(req, body, slug, run_id):
    with worlds.open_world(slug) as conn:
        return runs.get_run(conn, int(run_id), req.reveal)


@route("GET", W + "/audit")
def get_audit(req, body, slug):
    with worlds.open_world(slug) as conn:
        return {"eintraege": service.audit_entries(conn, req.reveal)}


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "StoryWorld/1"
    reveal = False

    def log_message(self, fmt, *args):  # ruhiger Log, keine Inhalte
        pass

    def _allowed_hosts(self):
        port = self.server.server_address[1]
        return {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _send(self, code: int, payload, content_type="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, download: bool = False):
        """Audiodatei mit Range-Unterstützung (Spulen im Browser)."""
        size = path.stat().st_size
        ctype = "audio/mp4" if path.suffix == ".m4a" else "audio/wav"
        start, end, status = 0, size - 1, 200
        match = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
            else:
                start = max(0, size - int(match.group(2)))
            end = min(end, size - 1)
            status = 206
        length = max(0, end - start + 1)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if download:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(path, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(1 << 16, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _handle(self, method: str):
        try:
            if self.headers.get("Host", "") not in self._allowed_hosts():
                raise HTTPError(403, "Unzulässiger Host.")
            path = urlparse(self.path).path
            if method != "GET":
                origin = self.headers.get("Origin")
                if self.headers.get("X-Story-World") != "1":
                    raise HTTPError(403, "Schreibzugriff nur über die Oberfläche.")
                if origin and origin.replace("http://", "") not in self._allowed_hosts():
                    raise HTTPError(403, "Fremder Ursprung.")
            if method == "GET" and path == "/favicon.ico":
                path = "/favicon/favicon-32x32.ico"
            icon = re.match(r"^/favicon/([a-z0-9-]+\.(png|ico))$", path)
            if method == "GET" and icon and (FAVICON / icon.group(1)).is_file():
                return self._send(200, (FAVICON / icon.group(1)).read_bytes(),
                                  "image/png" if icon.group(2) == "png" else "image/x-icon")
            listen = re.match("^" + W + r"/episodes/(?P<eid>\d+)/audio$", path)
            if method == "GET" and listen:
                with worlds.open_world(listen.group("slug")) as conn:
                    return self._send_file(audio.audio_file(conn, int(listen.group("eid"))))
            tts_file = re.match("^" + W + r"/episodes/(?P<eid>\d+)/tts\.wav$", path)
            if method == "GET" and tts_file:
                with worlds.open_world(tts_file.group("slug")) as conn:
                    found = tts.output_file(conn, tts_file.group("slug"), int(tts_file.group("eid")))
                if found is None:
                    raise HTTPError(404, "Für diese Folge gibt es noch keine Vertonung über TTS-Server.")
                return self._send_file(found, download="download" in (urlparse(self.path).query or ""))
            probe = re.match(r"^/api/tts/server/(?P<sid>t_[0-9a-f]{8})/probe$", path)
            if method == "GET" and probe:
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                server = tts.get_server(probe.group("sid"))
                voice = q.get("stimme") or ""
                data = tts.synth(server, (q.get("text") or "Hallo, so klinge ich.")[:300], voice, tts.language_of(server, voice))
                return self._send(200, data, "audio/wav")
            export = re.match("^" + W + r"/episodes/(?P<eid>\d+)/export(?P<pdf>\.pdf)?$", path)
            if method == "GET" and export:
                with worlds.open_world(export.group("slug")) as conn:
                    if export.group("pdf"):
                        name, data = episodes.export_pdf(conn, int(export.group("eid")))
                    else:
                        name, text = episodes.export_text(conn, int(export.group("eid")))
                        data = text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf" if export.group("pdf") else "text/plain; charset=utf-8")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if method == "GET" and path in STATIC_FILES:
                name, ctype = STATIC_FILES[path]
                return self._send(200, (STATIC / name).read_bytes(), ctype)
            self.reveal = self.headers.get("X-Reveal") == "1"
            body = {}
            if method in ("POST", "PUT"):
                length = int(self.headers.get("Content-Length") or 0)
                if length > 12_000_000:
                    raise HTTPError(413, "Anfrage zu groß.")
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw.decode("utf-8")) if raw else {}
                if not isinstance(body, dict):
                    raise HTTPError(400, "JSON-Objekt erwartet.")
            for m, pattern, fn in ROUTES:
                match = pattern.match(path)
                if m == method and match:
                    return self._send(200, fn(self, body, **match.groupdict()))
            raise HTTPError(404, "Nicht gefunden.")
        except HTTPError as exc:
            self._send(exc.code, {"fehler": exc.message})
        except service.ValidationError as exc:
            self._send(400, {"fehler": str(exc)})
        except providers.ProviderError as exc:
            self._send(502, {"fehler": str(exc)})
        except tts.TTSError as exc:
            self._send(502, {"fehler": str(exc)})
        except LookupError as exc:
            self._send(404, {"fehler": str(exc).strip("'\"")})
        except (ValueError, KeyError) as exc:
            self._send(400, {"fehler": f"Ungültige Anfrage: {exc}"})
        except sqlite3.DatabaseError as exc:
            self._send(500, {"fehler": f"Datenbankfehler: {exc}"})
        except ConnectionError:  # Client hat abgebrochen (Spulen/Pause/Tab zu) – nichts mehr zu senden
            return
        except Exception as exc:
            traceback.print_exc()
            self._send(500, {"fehler": f"Interner Fehler: {exc}"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class _Server(ThreadingHTTPServer):
    # Unter Windows erlaubt SO_REUSEADDR, einen belegten Port still mitzubenutzen – dort abschalten.
    allow_reuse_address = sys.platform != "win32"


def make_server(port: int = 8765) -> ThreadingHTTPServer:
    server = _Server(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def _already_running(port: int) -> bool:
    """True, wenn auf dem Port schon eine Story-World-Instanz antwortet."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1.5)
        conn.request("GET", "/favicon.ico", headers={"Host": f"127.0.0.1:{port}"})
        server = conn.getresponse().getheader("Server") or ""
        conn.close()
        return server.startswith(Handler.server_version)
    except OSError:
        return False


def serve(port: int = 8765, open_browser: bool = True) -> None:
    url = f"http://127.0.0.1:{port}/"
    if _already_running(port):
        print(f"Story World läuft bereits auf {url}")
        if open_browser:
            webbrowser.open(url)
        return
    try:
        server = make_server(port)
    except OSError as exc:
        sys.exit(f"Port {port} ist belegt ({exc}). Anderen Port wählen: python3 -m story_world ui --port 8800")
    print(f"Story World läuft auf {url}  (Welten: {worlds.worlds_dir()})  – Beenden mit Strg+C")
    daily.start_scheduler(_start_job)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        server.server_close()
