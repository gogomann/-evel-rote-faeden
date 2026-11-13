"""Qualitätssicherung der KI: Messwerte je Modell und Aufgabe über die Zeit.

Drei Quellen liefern Messwerte in eine gemeinsame, app-weite Datenbank (story_world.qualitaet.sqlite3, nicht im Git):
- live:        jede Folge misst nebenbei per Code (Format, Länge, Spoiler, Wiederholung, Konkretheit, Stil …) – kostet nichts
- pruefstand:  feste Prüfwelt mit bekannten Antworten (Fallen für den Prüfer, Archivar-Faktenliste, Richter …)
- vergleich:   derselbe gespeicherte Prompt an 2–3 Modelle, nebeneinander gemessen

Jeder Test hat eine Grenze (darunter/darüber gibt es eine Warnung) und eine Referenz (Ausgangswert eines Modells).
Weicht der jüngste Mittelwert deutlich von der Referenz ab, meldet die Übersicht eine Drift – so fällt auf, wenn ein
Anbieter sein Modell verändert oder ein neues Modell schlechter arbeitet.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.Lock()

# besser: "hoch" = größer ist besser, "niedrig" = kleiner ist besser, "eins" = möglichst nah an 1
# grenze: ab hier Warnung; toleranz: so weit darf der Mittelwert von der Referenz abweichen, bevor es Drift heißt
TESTS = {
    "format": {"nr": "1", "label": "Format-Treue", "besser": "hoch", "grenze": 0.8, "toleranz": 0.15, "art": "Code",
               "kurz": "Liefert das Modell gleich gültiges JSON? 1 = sofort, 0,5 = nach Korrektur, 0 = gescheitert."},
    "laenge": {"nr": "2", "label": "Längen-Treue", "besser": "eins", "grenze": 0.3, "toleranz": 0.2, "art": "Code",
               "kurz": "Geschriebene Wörter im Verhältnis zur Vorgabe. 1 = genau getroffen."},
    "spoiler": {"nr": "3", "label": "Spoiler-Dichtheit", "besser": "niedrig", "grenze": 0.05, "toleranz": 0.05,
                "art": "Code", "kurz": "Anteil von Geheimnis-Bruchstücken (Rätselwahrheiten, Code-Bedeutungen, Kanarien) "
                                      "im Text. 0 = nichts verraten."},
    "pruefer_fallen": {"nr": "4", "label": "Fallen für den Prüfer", "besser": "hoch", "grenze": 6, "toleranz": 2,
                       "art": "Prüfstand", "kurz": "Wie viele eingebaute Fehler (tote Figur spricht, zwei Orte, Tageszahl, "
                                                    "verratenes Geheimnis, Wissen ohne Quelle, Reisezeit) findet der Prüfer? 0–10."},
    "fehlalarme": {"nr": "4", "label": "Fehlalarme des Prüfers", "besser": "niedrig", "grenze": 1, "toleranz": 1,
                   "art": "Prüfstand", "kurz": "Wichtige Befunde bei einem fehlerfreien Text. 0 = keine Fehlalarme."},
    "wiederholung": {"nr": "6", "label": "Wiederholungen über Folgen", "besser": "niedrig", "grenze": 0.12,
                     "toleranz": 0.06, "art": "Code",
                     "kurz": "Anteil gleicher Wortfolgen (5 Wörter) aus den letzten Folgen. 0 = nichts wiederholt."},
    "kanon_schaden": {"nr": "7", "label": "Kanon-Schaden", "besser": "niedrig", "grenze": 0.5, "toleranz": 1,
                      "art": "Code", "kurz": "Neue Konsistenzprobleme (Zeitleiste, Orte, tote Figuren) nach einer Folge."},
    "verweigerung": {"nr": "8", "label": "Verweigerungen", "besser": "niedrig", "grenze": 0.2, "toleranz": 0.15,
                     "art": "Code", "kurz": "Anteil der Autor-Aufrufe, die eine Absage statt Text lieferten."},
    "konkretheit": {"nr": "9", "label": "Konkretheit", "besser": "hoch", "grenze": 4, "toleranz": 1.5, "art": "Code",
                    "kurz": "Richtwert 0–10: Bezüge auf Figuren, Orte, Technik der Welt und Wortvielfalt gegenüber "
                            "Floskeln („irgendwie“, „eine Art“, „seltsam“ …)."},
    "stil": {"nr": "10", "label": "Stil-Abweichung", "besser": "niedrig", "grenze": 45, "toleranz": 15, "art": "Code",
             "kurz": "Abweichung in Satzlänge und Dialoganteil von deinen Stilproben bzw. den bisherigen Folgen, in %."},
    "plan_treue": {"nr": "11", "label": "Plan-Treue", "besser": "hoch", "grenze": 6, "toleranz": 2, "art": "Richter",
                   "kurz": "Setzt der Autor um, was im Kapitelplan steht? 0–10, bewertet vom Qualitäts-Richter."},
    "archivar": {"nr": "12", "label": "Archivar-Genauigkeit", "besser": "hoch", "grenze": 6, "toleranz": 2,
                 "art": "Prüfstand", "kurz": "Findet der Archivar die bekannten neuen Fakten eines Referenztexts, "
                                             "ohne etwas zu erfinden? 0–10."},
    "richter_streuung": {"nr": "13", "label": "Streuung des Richters", "besser": "niedrig", "grenze": 2, "toleranz": 1,
                         "art": "Prüfstand", "kurz": "Derselbe Text zweimal bewertet: Unterschied in Punkten. 0 = stabil."},
    "lektor_schaden": {"nr": "14", "label": "Lektor-Schaden", "besser": "niedrig", "grenze": 0.25, "toleranz": 0.1,
                       "art": "Code", "kurz": "Anteil an Länge und Namen, die der Lektor gegenüber der Autorfassung verliert."},
    "genre_treue": {"nr": "15", "label": "Genre-Treue", "besser": "hoch", "grenze": 6, "toleranz": 2, "art": "Richter",
                    "kurz": "Passen Spannungsbogen und Ton zum Genre? 0–10, bewertet vom Qualitäts-Richter."},
    "bewerter_rangfolge": {"nr": "16", "label": "Bewerter-Rangfolge", "besser": "hoch", "grenze": 6, "toleranz": 2,
                           "art": "Prüfstand", "kurz": "Erkennt der Bewerter bei vorbereiteten Szenarien, welches passt und "
                                                       "welches überrascht? 0–10."},
    "kontext": {"nr": "K4", "label": "Kontextgröße", "besser": "niedrig", "grenze": None, "toleranz": None, "art": "Code",
                "kurz": "Zeichen im Prompt eines Aufrufs – zum Vergleich voller Kontext gegen Kaskade."},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS messungen (
    id INTEGER PRIMARY KEY,
    zeit TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
    quelle TEXT NOT NULL,
    test TEXT NOT NULL,
    aufgabe TEXT,
    modell TEXT,
    wert REAL,
    welt TEXT,
    lauf_id INTEGER,
    serie TEXT,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_mess_test ON messungen(test, modell, zeit);
CREATE TABLE IF NOT EXISTS referenzen (
    test TEXT NOT NULL,
    modell TEXT NOT NULL,
    wert REAL NOT NULL,
    gesetzt TEXT NOT NULL,
    PRIMARY KEY (test, modell)
);
CREATE TABLE IF NOT EXISTS serien (
    id TEXT PRIMARY KEY,
    art TEXT NOT NULL,
    zeit TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
    status TEXT NOT NULL DEFAULT 'laeuft',
    titel TEXT,
    welt TEXT,
    ergebnis TEXT,
    fehler TEXT
);
CREATE TABLE IF NOT EXISTS einstellungen (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS hinweise (
    id INTEGER PRIMARY KEY,
    zeit TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
    art TEXT NOT NULL,
    text TEXT NOT NULL,
    erledigt INTEGER NOT NULL DEFAULT 0
);
"""


def path() -> Path:
    return Path(os.environ.get("STORY_QUALITY", ROOT / "story_world.qualitaet.sqlite3"))


def connect() -> sqlite3.Connection:
    file = path()
    file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(file), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# Regelmäßiger Prüfstand (app-weit): alle n Tage, 0 = aus
SETTINGS = {"intervall_tage": "0", "umfang": "schnell", "kontext": "voll", "ballast": "", "letzter": ""}


def get_settings() -> dict:
    with _LOCK:
        conn = connect()
        try:
            stored = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM einstellungen")}
        finally:
            conn.close()
    return {k: stored.get(k, v) for k, v in SETTINGS.items()}


def set_settings(values: dict) -> dict:
    clean = {}
    for key, value in values.items():
        if key not in SETTINGS or key == "letzter":
            continue
        value = str(value if value is not None else "").strip()
        if key == "intervall_tage" and not (value.isdigit() and 0 <= int(value) <= 90):
            raise ValueError("Intervall bitte als Tage zwischen 0 (aus) und 90.")
        if key == "umfang" and value not in ("schnell", "voll"):
            raise ValueError("Umfang: schnell oder voll.")
        if key == "kontext" and value not in ("voll", "kaskade"):
            raise ValueError("Kontext: voll oder kaskade.")
        clean[key] = value
    _store_settings(clean)
    return get_settings()


def _store_settings(values: dict) -> None:
    with _LOCK:
        conn = connect()
        try:
            for k, v in values.items():
                conn.execute("INSERT OR REPLACE INTO einstellungen (key, value) VALUES (?, ?)", (k, v))
            conn.commit()
        finally:
            conn.close()


def bench_due(today: str) -> bool:
    s = get_settings()
    days = int(s["intervall_tage"] or 0)
    if not days:
        return False
    if not s["letzter"]:
        return True
    from datetime import date
    try:
        return (date.fromisoformat(today) - date.fromisoformat(s["letzter"])).days >= days
    except ValueError:
        return True


def mark_bench(today: str) -> None:
    _store_settings({"letzter": today})


# ---------------------------------------------------------------- Schreiben

def record(test: str, aufgabe: str | None, modell: str | None, wert: float | None, quelle: str = "live",
           welt: str | None = None, lauf_id: int | None = None, serie: str | None = None, details: dict | None = None) -> None:
    if test not in TESTS or wert is None:
        return
    with _LOCK:
        conn = connect()
        try:
            conn.execute("INSERT INTO messungen (quelle, test, aufgabe, modell, wert, welt, lauf_id, serie, details) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (quelle, test, aufgabe, modell, float(wert), welt, lauf_id, serie,
                          json.dumps(details, ensure_ascii=False) if details else None))
            conn.commit()
        finally:
            conn.close()


def note(run, test: str, aufgabe: str, modell: str | None, wert: float | None, details: dict | None = None) -> None:
    """Live-Messung aus einem KI-Lauf. Fehler hier dürfen den Lauf nie gefährden."""
    try:
        welt = getattr(run, "welt_label", None) or (Path(run.path).stem if getattr(run, "path", "") else None)
        record(test, aufgabe, modell, wert, getattr(run, "quelle", "live"), welt, getattr(run, "id", None),
               serie=getattr(run, "serie", None), details=details)
        if hasattr(run, "qa"):
            run.qa.append({"test": test, "aufgabe": aufgabe, "modell": modell, "wert": wert})
    except Exception:  # noqa: BLE001 – Messung ist Beiwerk
        pass


def hint(art: str, text: str) -> None:
    """Hinweis für die Qualitätsseite, z. B. „Modell für Autor geändert – Prüfstand empfohlen“."""
    try:
        with _LOCK:
            conn = connect()
            try:
                conn.execute("UPDATE hinweise SET erledigt = 1 WHERE art = ? AND erledigt = 0", (art,))
                conn.execute("INSERT INTO hinweise (art, text) VALUES (?, ?)", (art, text))
                conn.commit()
            finally:
                conn.close()
    except sqlite3.Error:
        pass


def close_hints(prefix: str = "") -> None:
    with _LOCK:
        conn = connect()
        try:
            conn.execute("UPDATE hinweise SET erledigt = 1 WHERE art LIKE ?", (prefix + "%",))
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------- Bewerten

def judge(test: str, wert: float | None) -> str:
    """ok / warnung / info für einen einzelnen Wert."""
    spec = TESTS.get(test) or {}
    limit = spec.get("grenze")
    if wert is None or limit is None:
        return "info"
    if spec["besser"] == "hoch":
        return "ok" if wert >= limit else "warnung"
    if spec["besser"] == "eins":
        return "ok" if abs(wert - 1) <= limit else "warnung"
    return "ok" if wert <= limit else "warnung"


def _worse(test: str, now: float, ref: float) -> bool:
    spec = TESTS[test]
    tol = spec.get("toleranz")
    if tol is None:
        return False
    if spec["besser"] == "hoch":
        return now < ref - tol
    if spec["besser"] == "eins":
        return abs(now - 1) > abs(ref - 1) + tol
    return now > ref + tol


def fmt(test: str, wert: float | None) -> str:
    if wert is None:
        return "–"
    if test in ("stil",):
        return f"{wert:.0f} %"
    if test == "kontext":
        return f"{wert:,.0f}".replace(",", ".")
    if TESTS[test]["besser"] in ("eins",) or wert < 1.5 and test in ("format", "spoiler", "wiederholung", "verweigerung",
                                                                     "lektor_schaden"):
        return f"{wert:.2f}".replace(".", ",")
    return f"{wert:.1f}".replace(".", ",")


def overview(days: int = 60, recent: int = 10) -> dict:
    """Alles für die Qualitätsseite: je Modell eine Ampel mit Satz, je Test die Werte, offene Hinweise, letzte Serien."""
    with _LOCK:
        conn = connect()
        try:
            rows = conn.execute(
                "SELECT test, aufgabe, modell, wert, zeit, quelle FROM messungen WHERE zeit >= datetime('now', ?) "
                "ORDER BY zeit", (f"-{int(days)} days",)).fetchall()
            refs = {(r["test"], r["modell"]): dict(r) for r in conn.execute("SELECT * FROM referenzen")}
            hints = [dict(r) for r in conn.execute("SELECT * FROM hinweise WHERE erledigt = 0 ORDER BY id DESC LIMIT 20")]
            series = [dict(r) for r in conn.execute("SELECT * FROM serien ORDER BY zeit DESC LIMIT 15")]
        finally:
            conn.close()
    grouped: dict = {}
    for r in rows:
        grouped.setdefault((r["modell"] or "?", r["test"]), []).append(dict(r))
    models: dict = {}
    for (model, test), items in grouped.items():
        values = [i["wert"] for i in items[-recent:]]
        mean = sum(values) / len(values)
        ref = refs.get((test, model))
        drift = bool(ref) and _worse(test, mean, ref["wert"])
        state = "drift" if drift else judge(test, mean)
        entry = {"test": test, "label": TESTS[test]["label"], "nr": TESTS[test]["nr"], "art": TESTS[test]["art"],
                 "letzter": items[-1]["wert"], "letzter_text": fmt(test, items[-1]["wert"]), "mittel": mean,
                 "mittel_text": fmt(test, mean), "anzahl": len(items), "zuletzt": items[-1]["zeit"],
                 "referenz": ref["wert"] if ref else None, "referenz_text": fmt(test, ref["wert"]) if ref else "–",
                 "status": state, "aufgaben": sorted({i["aufgabe"] for i in items if i["aufgabe"]}),
                 "verlauf": [round(v, 3) for v in values]}
        models.setdefault(model, []).append(entry)
    out = []
    for model, tests in models.items():
        tests.sort(key=lambda t: (len(t["nr"]), t["nr"], t["test"]))
        bad = [t for t in tests if t["status"] in ("warnung", "drift")]
        drift = [t for t in bad if t["status"] == "drift"]
        if drift:
            ampel, satz = "rot", "Schlechter als früher: " + ", ".join(t["label"] for t in drift) + "."
        elif bad:
            ampel, satz = "gelb", "Auffällig: " + ", ".join(t["label"] for t in bad) + "."
        else:
            ampel, satz = "gruen", "Arbeitet im geplanten Rahmen."
        out.append({"modell": model, "ampel": ampel, "satz": satz, "tests": tests,
                    "aufgaben": sorted({a for t in tests for a in t["aufgaben"]}),
                    "messungen": sum(t["anzahl"] for t in tests)})
    order = {"rot": 0, "gelb": 1, "gruen": 2}
    out.sort(key=lambda m: (order[m["ampel"]], m["modell"]))
    for s in series:
        s["ergebnis"] = json.loads(s["ergebnis"]) if s.get("ergebnis") else None
    return {"modelle": out, "hinweise": hints, "serien": series,
            "tests": [{"id": k, **v} for k, v in TESTS.items()], "datei": str(path())}


def set_reference(model: str | None = None, test: str | None = None, recent: int = 10) -> int:
    """Aktuellen Mittelwert als Referenz festhalten (je Modell und Test). Gibt die Anzahl gesetzter Referenzen zurück."""
    data = overview(recent=recent)
    count = 0
    with _LOCK:
        conn = connect()
        try:
            for m in data["modelle"]:
                if model and m["modell"] != model:
                    continue
                for t in m["tests"]:
                    if test and t["test"] != test:
                        continue
                    conn.execute("INSERT OR REPLACE INTO referenzen (test, modell, wert, gesetzt) VALUES (?, ?, ?, ?)",
                                 (t["test"], m["modell"], t["mittel"], time.strftime("%Y-%m-%d %H:%M")))
                    count += 1
            conn.commit()
        finally:
            conn.close()
    return count


def auto_reference(min_count: int = 3) -> None:
    """Hat ein Modell für einen Test noch keine Referenz, gelten die ersten Messungen als Ausgangswert."""
    with _LOCK:
        conn = connect()
        try:
            rows = conn.execute("SELECT test, modell, COUNT(*) n FROM messungen WHERE modell IS NOT NULL "
                                "GROUP BY test, modell HAVING n >= ?", (min_count,)).fetchall()
            for r in rows:
                if conn.execute("SELECT 1 FROM referenzen WHERE test = ? AND modell = ?", (r[0], r[1])).fetchone():
                    continue
                first = [x[0] for x in conn.execute("SELECT wert FROM messungen WHERE test = ? AND modell = ? "
                                                    "ORDER BY zeit LIMIT ?", (r[0], r[1], min_count))]
                conn.execute("INSERT INTO referenzen (test, modell, wert, gesetzt) VALUES (?, ?, ?, ?)",
                             (r[0], r[1], sum(first) / len(first), time.strftime("%Y-%m-%d %H:%M") + " (automatisch)"))
            conn.commit()
        finally:
            conn.close()


def history(test: str, model: str | None = None, limit: int = 200) -> list:
    with _LOCK:
        conn = connect()
        try:
            sql = "SELECT zeit, quelle, aufgabe, modell, wert, welt, lauf_id, serie FROM messungen WHERE test = ?"
            params: list = [test]
            if model:
                sql += " AND modell = ?"
                params.append(model)
            rows = conn.execute(sql + " ORDER BY zeit DESC LIMIT ?", (*params, limit)).fetchall()
        finally:
            conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- Serien (Prüfstand, Vergleich)

def series_start(art: str, titel: str, welt: str | None = None) -> str:
    sid = f"{art[:1]}{int(time.time() * 1000)}"
    with _LOCK:
        conn = connect()
        try:
            conn.execute("INSERT INTO serien (id, art, titel, welt) VALUES (?, ?, ?, ?)", (sid, art, titel, welt))
            conn.commit()
        finally:
            conn.close()
    return sid


def series_finish(sid: str, ergebnis: dict | None, fehler: str | None = None) -> None:
    with _LOCK:
        conn = connect()
        try:
            conn.execute("UPDATE serien SET status = ?, ergebnis = ?, fehler = ? WHERE id = ?",
                         ("fehler" if fehler else "fertig", json.dumps(ergebnis, ensure_ascii=False) if ergebnis else None,
                          fehler, sid))
            conn.commit()
        finally:
            conn.close()


def series_update(sid: str, ergebnis: dict) -> None:
    with _LOCK:
        conn = connect()
        try:
            conn.execute("UPDATE serien SET ergebnis = ? WHERE id = ?", (json.dumps(ergebnis, ensure_ascii=False), sid))
            conn.commit()
        finally:
            conn.close()


def get_series(sid: str) -> dict:
    with _LOCK:
        conn = connect()
        try:
            row = conn.execute("SELECT * FROM serien WHERE id = ?", (sid,)).fetchone()
        finally:
            conn.close()
    if row is None:
        raise LookupError("Serie nicht gefunden.")
    out = dict(row)
    out["ergebnis"] = json.loads(out["ergebnis"]) if out.get("ergebnis") else None
    return out


# ---------------------------------------------------------------- Messungen per Code (kostenlos, wiederholbar)

_SPEAKER = re.compile(r"^\s*\[[^\]\n]{1,60}\]\s*", re.M)
_WORD = re.compile(r"[\wäöüÄÖÜß]+")
_SENT = re.compile(r"[^.!?…]+[.!?…]+")
STOP = set("der die das und oder aber ein eine einer eines einem einen dem den des im in am an auf aus bei mit nach von "
           "vor zu zum zur ist sind war waren wird werden hat haben hatte nicht auch noch nur sich sie er es wir ihr "
           "man als wie so dass sein seine ihre ihren ihrem ihm ihn mir mich dir dich was wer wo".split())
FLOSKELN = ("irgendwie", "irgendetwas", "irgendwas", "irgendwo", "irgendwann", "eine art", "gewissermaßen",
            "in gewisser weise", "auf eine weise", "auf seltsame weise", "unbeschreiblich", "undefinierbar",
            "seltsam", "merkwürdig", "als ob", "als wäre", "es war, als", "ein gefühl von", "etwas in ihr",
            "etwas in ihm", "man könnte sagen", "schwer zu sagen", "kaum zu beschreiben", "auf eine art")


def plain(text: str) -> str:
    return _SPEAKER.sub("", text or "")


def words(text: str) -> list:
    return [w.lower() for w in _WORD.findall(plain(text))]


def shingles(text: str, n: int, skip_stop: bool = False) -> set:
    ws = [w for w in words(text) if not (skip_stop and w in STOP)]
    return {tuple(ws[i:i + n]) for i in range(max(0, len(ws) - n + 1))}


def spoiler_share(secrets: list, text: str, canaries: tuple = ()) -> tuple:
    """(Anteil, Treffer): Wie viele 4-Wort-Bruchstücke (ohne Füllwörter) der Geheimnisse stehen im Text?
    Kanarien (eindeutige Testwörter) zählen bei Vorkommen sofort als 1."""
    low = (text or "").lower()
    hits = [c for c in canaries if c and c.lower() in low]
    if hits:
        return 1.0, hits
    body = shingles(text, 4, True)
    worst, found = 0.0, []
    for secret in secrets:
        sh = shingles(secret, 4, True)
        if len(sh) < 2:
            continue
        common = sh & body
        share = len(common) / len(sh)
        if share > worst:
            worst = share
        if common:
            found.append(" ".join(next(iter(common))))
    return round(worst, 3), found[:5]


def repetition(text: str, previous: list) -> float:
    mine = shingles(text, 5)
    if not mine or not previous:
        return 0.0
    old = set()
    for p in previous:
        old |= shingles(p, 5)
    return round(len(mine & old) / len(mine), 3)


def concreteness(text: str, names: list) -> dict:
    ws = words(text)
    n = max(1, len(ws))
    low = " " + " ".join(ws) + " "
    plain_low = plain(text).lower()
    refs = sum(low.count(" " + " ".join(words(name)) + " ") for name in names if name and len(name) >= 3)
    flos = sum(plain_low.count(f) for f in FLOSKELN)
    sample = ws[:2000]
    ttr = len(set(sample)) / max(1, len(sample))
    per_k = lambda v: v * 1000 / n  # noqa: E731
    score = 5 + min(3.0, per_k(refs) / 5) - min(4.0, per_k(flos) / 2) + max(-2.0, min(2.0, (ttr - 0.45) * 10))
    return {"wert": round(max(0.0, min(10.0, score)), 1), "bezuege_je_1000": round(per_k(refs), 1),
            "floskeln_je_1000": round(per_k(flos), 1), "wortvielfalt": round(ttr, 2)}


def style_values(text: str) -> dict:
    body = plain(text)
    sentences = [s for s in _SENT.findall(body) if _WORD.search(s)]
    ws = [len(_WORD.findall(s)) for s in sentences] or [0]
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    dialog = [ln for ln in lines if ln.lstrip().startswith("[") and not re.match(r"^\s*\[(erzähler|erzaehler|erzählerin)\]",
                                                                                 ln, re.I)]
    quotes = len(re.findall(r"[„\"»]", body))
    share = len(dialog) / len(lines) if lines and any(ln.lstrip().startswith("[") for ln in lines) \
        else min(1.0, quotes / max(1, len(sentences)))
    tokens = _WORD.findall(body)
    paras = [len(_WORD.findall(_SPEAKER.sub("", ln))) for ln in lines if _WORD.search(_SPEAKER.sub("", ln))]
    return {"satzlaenge": round(sum(ws) / len(ws), 1), "dialoganteil": round(share, 2),
            "wortlaenge": round(sum(len(t) for t in tokens) / max(1, len(tokens)), 2),
            "absatzlaenge": round(sum(paras) / max(1, len(paras)), 1)}


def style_deviation(text: str, reference: str) -> float | None:
    if not reference or len(words(reference)) < 150:
        return None
    a, b = style_values(text), style_values(reference)
    d1 = abs(a["satzlaenge"] - b["satzlaenge"]) / max(1.0, b["satzlaenge"])
    d2 = abs(a["dialoganteil"] - b["dialoganteil"])
    return round(100 * (d1 + d2) / 2, 1)


def editor_damage(before: str, after: str, names: list) -> float:
    wb, wa = len(words(before)), len(words(after))
    loss = max(0.0, 1 - wa / max(1, wb))
    present = [n for n in names if n and len(n) >= 3 and n.lower() in before.lower()]
    lost = [n for n in present if n.lower() not in after.lower()]
    return round(max(loss, len(lost) / len(present) if present else 0.0), 3)
