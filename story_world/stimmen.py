"""Stimmen – der virtuelle Autor, der eine Folge schreibt.

Eine Stimme hat ein Vorbild: einen bekannten Autor („schreibt wie Stanisław Lem“), einen Menschen mit eigenen Texten
(„schreibt wie Ralf“, Basis: seine Texte aus dem Erzählprofil) oder eine freie Beschreibung. Die KI verdichtet das Vorbild
zu einem Stil-Steckbrief; Regler und Hinweise justieren ihn. Eine freigegebene Probe dient als Anker und als messbarer
Maßstab. Derselbe Maßstab geht an Planer, Autor, Lektor (schreiben danach) und Prüfer (prüft dagegen); die
Qualitätsmessung vergleicht mit den eigenen Texten bzw. der freigegebenen Probe.

Fremde Autoren: nur Stilbeschreibung, nie Originaltext als Vorlage. Eigene Texte: kurze Auszüge als Stilanker.

Speicherort: story_world.stimmen.json im Projektordner (oder STORY_VOICES), Dateirechte 0600, per .gitignore
ausgeschlossen. Nichts wird gelöscht – entfernte Stimmen wandern ins Archiv.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from . import llm, profiles, providers, quality

ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.RLock()

ARTEN = {"autor": "Wie ein Autor (Vorbild)", "mensch": "Wie ein Mensch (eigene Texte)", "frei": "Freie Beschreibung"}

FIELDS = [
    ("kurz", "In einem Satz"),
    ("stimme", "Erzählstimme & Haltung"),
    ("satzbau", "Satzbau & Rhythmus"),
    ("wortwahl", "Wortwahl & Register"),
    ("bilder", "Bildsprache & Beschreibung"),
    ("tempo", "Tempo & Spannung"),
    ("dialog", "Dialoge"),
    ("humor", "Humor & Ironie"),
    ("perspektive", "Perspektive & Nähe zu den Figuren"),
    ("motive", "Themen & Motive"),
    ("vermeiden", "Was diese Stimme nie tut"),
]

# Regler: -2 … +2, 0 = wie das Vorbild
SLIDERS = [
    ("satzlaenge", "Satzlänge", "deutlich kürzer", "kürzer", "länger", "deutlich länger"),
    ("bildhaft", "Bildsprache", "viel sachlicher", "sachlicher", "bildreicher", "sehr bildreich"),
    ("dialog", "Dialoganteil", "kaum Dialog", "weniger Dialog", "mehr Dialog", "überwiegend Dialog"),
    ("humor", "Humor", "ganz ernst", "ernster", "verspielter", "deutlich humorvoll"),
    ("tempo", "Tempo", "sehr ruhig", "ruhiger", "zügiger", "rasant"),
    ("naehe", "Nähe zum Vorbild", "nur leicht angelehnt", "lose angelehnt", "eng am Vorbild", "so nah wie möglich"),
]

ANALYZE_AUTHOR = """Du bist Literaturwissenschaftlerin und Lektorin. Beschreibe den Schreibstil von {vorbild} als
STIL-STECKBRIEF für einen Autor, der neue, eigene Geschichten in genau diesem Stil schreiben soll (deutschsprachige
Hörbuchreihe, Science-Fiction-Welt). Nur Stilmerkmale: Stimme, Satzbau, Wortwahl, Bildsprache, Tempo, Dialog, Humor,
Perspektive, typische Themen. Keine Zitate, keine Handlung oder Figuren aus seinen Werken, keine Titel nachahmen.
Konkret und als Schreibanweisung formuliert („Lange, verschachtelte Sätze mit …“), nicht als Lobrede.
{extra}
Antworte NUR mit JSON: {{"steckbrief": {{{fields}}}}}"""

ANALYZE_TEXTS = """Du bist Lektorin. Aus den Textproben eines Menschen erstellst du den STIL-STECKBRIEF seiner Erzählstimme:
wie neue Geschichten klingen müssen, damit sie wie aus seiner Feder wirken. Achte auf Satzlänge und Rhythmus, Wortwahl,
Bildsprache, Dialogführung, Humor, Perspektive und wiederkehrende Motive – mit Beispielen aus der Art (nicht wörtlich
abschreiben). Keine Aussagen über die Person, nur über das Schreiben. Konkret, als Schreibanweisung formuliert.
{extra}
Antworte NUR mit JSON: {{"steckbrief": {{{fields}}}}}"""

ANALYZE_FREE = """Du bist Lektorin. Aus der Beschreibung eines gewünschten Erzählstils machst du einen vollständigen
STIL-STECKBRIEF, als Schreibanweisung formuliert und konkret.
{extra}
Antworte NUR mit JSON: {{"steckbrief": {{{fields}}}}}"""

PROBE_TASK = """Schreibe einen PROBEABSATZ von etwa {woerter} Wörtern, der diese Stimme zeigt: eine kleine, abgeschlossene
Alltagsszene in der unten beschriebenen Welt, eine Figur mit Name, Gefühl, Lage und Ort, ein kurzer Wortwechsel.
Format wie in der Hörbuchreihe: jeder Absatz beginnt mit [Erzähler] oder [Name der Figur]. Antworte nur mit dem Text.

WELT: {welt}"""


class VoiceError(RuntimeError):
    pass


# ---------------------------------------------------------------- Speicher

def path() -> Path:
    return Path(os.environ.get("STORY_VOICES", ROOT / "story_world.stimmen.json"))


def _load() -> dict:
    with _LOCK:
        file = path()
        if not file.exists():
            return {"stimmen": [], "archiv": []}
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except ValueError:
            file.rename(file.with_suffix(f".defekt-{int(time.time())}.json"))
            return {"stimmen": [], "archiv": []}
        data.setdefault("stimmen", [])
        data.setdefault("archiv", [])
        return data


def _save(data: dict) -> None:
    with _LOCK:
        file = path()
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, file)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def list_voices() -> dict:
    data = _load()
    return {"stimmen": sorted(data["stimmen"], key=lambda v: v.get("name", "").lower()), "archiv": data["archiv"],
            "arten": ARTEN, "felder": [{"id": k, "label": v} for k, v in FIELDS],
            "regler": [{"id": s[0], "label": s[1], "stufen": list(s[2:])} for s in SLIDERS]}


def get(vid: str | None) -> dict | None:
    if not vid:
        return None
    return next((v for v in _load()["stimmen"] if v["id"] == vid), None)


def _clean_texts(pid: str | None, tids) -> list:
    if not pid or not isinstance(tids, list):
        return []
    p = profiles.get(pid)
    known = {t["id"] for t in (p or {}).get("texte", []) if not t.get("fremd")}
    return [t for t in tids if isinstance(t, str) and t in known]


def create(data: dict) -> dict:
    name = str(data.get("name") or "").strip()[:80]
    art = data.get("art") if data.get("art") in ARTEN else "frei"
    vorbild = str(data.get("vorbild") or "").strip()[:120]
    if art == "autor" and not vorbild:
        raise VoiceError("Bitte den Autor angeben, an dem sich die Stimme orientiert.")
    profil_id = str(data.get("profil_id") or "") or None
    if art == "mensch":
        p = profiles.get(profil_id)
        if p is None:
            raise VoiceError("Bitte den Menschen wählen, dessen Texte die Basis sind.")
        vorbild = vorbild or p.get("name", "")
    if not name:
        name = f"Wie {vorbild}" if vorbild else "Neue Stimme"
    voice = {"id": "v_" + uuid.uuid4().hex[:8], "name": name, "art": art, "vorbild": vorbild, "profil_id": profil_id,
             "texte": _clean_texts(profil_id, data.get("texte")) if art == "mensch" else [], "beschreibung": str(data.get("beschreibung") or "")[:4000],
             "steckbrief": {}, "regler": {s[0]: 0 for s in SLIDERS}, "hinweise": "", "probe": None, "messwerte": None,
             "created": _now(), "bearbeitet": _now()}
    if art == "mensch" and not voice["texte"]:
        voice["texte"] = [t["id"] for t in (profiles.get(profil_id) or {}).get("texte", [])
                          if t.get("stil") and not t.get("fremd")]
    with _LOCK:
        data_all = _load()
        data_all["stimmen"].append(voice)
        _save(data_all)
    if art == "mensch":
        voice = _update(voice["id"], _measure_texts)
    return voice


def _update(vid: str, fn) -> dict:
    with _LOCK:
        data = _load()
        for v in data["stimmen"]:
            if v["id"] == vid:
                fn(v)
                _save(data)
                return v
    raise LookupError("Stimme nicht gefunden.")


def edit(vid: str, changes: dict) -> dict:
    """Name, Steckbrief, Regler, Hinweise, Beschreibung, Textauswahl – alles, was du von Hand änderst."""
    fields = {k for k, _ in FIELDS}
    sliders = {s[0] for s in SLIDERS}

    def apply(v):
        if isinstance(changes.get("name"), str) and changes["name"].strip():
            v["name"] = changes["name"].strip()[:80]
        if isinstance(changes.get("vorbild"), str) and v["art"] == "autor" and changes["vorbild"].strip():
            v["vorbild"] = changes["vorbild"].strip()[:120]
        if isinstance(changes.get("beschreibung"), str):
            v["beschreibung"] = changes["beschreibung"].strip()[:4000]
        if isinstance(changes.get("hinweise"), str):
            v["hinweise"] = changes["hinweise"].strip()[:3000]
        for key, value in (changes.get("steckbrief") or {}).items():
            if key in fields and isinstance(value, str):
                v.setdefault("steckbrief", {})[key] = value.strip()[:2000]
        for key, value in (changes.get("regler") or {}).items():
            if key in sliders:
                try:
                    v.setdefault("regler", {})[key] = max(-2, min(2, int(value)))
                except (TypeError, ValueError):
                    pass
        if "texte" in changes and v["art"] == "mensch":
            v["texte"] = _clean_texts(v.get("profil_id"), changes.get("texte"))
            _measure_texts(v)
        v["bearbeitet"] = _now()
    return _update(vid, apply)


def archive(vid: str, back: bool = False) -> None:
    src, dst = ("archiv", "stimmen") if back else ("stimmen", "archiv")
    with _LOCK:
        data = _load()
        moved = [v for v in data[src] if v["id"] == vid]
        if not moved:
            raise LookupError("Stimme nicht gefunden.")
        if back:
            moved[0].pop("archiviert_am", None)
        else:
            moved[0]["archiviert_am"] = _now()
        data[src] = [v for v in data[src] if v["id"] != vid]
        data[dst].append(moved[0])
        _save(data)


# ---------------------------------------------------------------- Texte, Messwerte, Anker

HIDDEN_OPEN, HIDDEN_CLOSE = "⟦verborgen⟧", "⟦/verborgen⟧"
_HIDDEN_RE = re.compile(re.escape(HIDDEN_OPEN) + r".*?" + re.escape(HIDDEN_CLOSE), re.S)


def redact(text: str) -> str:
    """Auszüge aus verborgenen Texten (anderer Autor) für die Anzeige unkenntlich machen."""
    if not text or HIDDEN_OPEN not in text:
        return text
    return _HIDDEN_RE.sub("[🔒 Auszug aus Texten eines anderen Autors – verborgen]", text)


def _hidden(v: dict) -> bool:
    return bool((v.get("basis") or {}).get("verborgen"))


def _texts(v: dict, budget: int) -> str:
    """Auszüge aus den gewählten eigenen Texten – lokal, sonst aus der mitgebrachten Basis (Welt-Import)."""
    local = _local_texts(v, budget)
    if local:
        return local
    return ((v.get("basis") or {}).get("referenz") or "")[:budget]


def _local_texts(v: dict, budget: int) -> str:
    if v.get("art") != "mensch":
        return ""
    p = profiles.get(v.get("profil_id"))
    if not p:
        return ""
    chosen = set(v.get("texte") or [])
    sub = dict(p, texte=[dict(t, stil=True) for t in p.get("texte", []) if t["id"] in chosen])
    return profiles.style_samples(sub, budget)


def _measure_texts(v: dict) -> None:
    sample = _texts(v, 60000)
    if sample and len(quality.words(sample)) >= 150:
        v["messwerte"] = dict(quality.style_values(sample), quelle="eigene Texte")
    elif (v.get("messwerte") or {}).get("quelle") == "eigene Texte":
        v["messwerte"] = None  # Basis weg (z. B. Text als fremd markiert) → kein veralteter Maßstab


def refresh_owner(pid: str) -> None:
    """Nach Änderungen an den Texten eines Menschen (z. B. „fremd“) die Maßstäbe seiner Stimmen neu messen."""
    with _LOCK:
        data = _load()
        for v in data["stimmen"]:
            if v.get("art") == "mensch" and v.get("profil_id") == pid:
                v["texte"] = _clean_texts(pid, v.get("texte"))
                _measure_texts(v)
        _save(data)


def reference_text(v: dict | None) -> str:
    """Messbarer Maßstab: eigene Texte, sonst die freigegebene Probe."""
    if not v:
        return ""
    sample = _texts(v, 40000)
    if sample:
        return sample
    probe = v.get("probe") or {}
    return probe.get("text", "") if probe.get("freigegeben") else ""


def anchors(v: dict, budget: int = 4500) -> str:
    """Kurze Stilanker für den Autor: eigene Textauszüge und/oder die freigegebene Probe – nie fremder Originaltext."""
    parts = []
    own = _local_texts(v, budget) or ((v.get("basis") or {}).get("anker") or "")[:budget]
    if own:
        parts.append(f"{HIDDEN_OPEN}{own}{HIDDEN_CLOSE}" if _hidden(v) and not _local_texts(v, 200) else own)
    probe = v.get("probe") or {}
    if probe.get("freigegeben") and probe.get("text"):
        parts.append("FREIGEGEBENE PROBE DIESER STIMME:\n" + probe["text"][:2500])
    return "\n\n".join(parts)[:budget + 2600]


# ---------------------------------------------------------------- Blöcke für die Rollen

def _vorbild_satz(v: dict) -> str:
    if v.get("art") == "autor":
        return f"Du schreibst wie {v['vorbild']} – im Stil, nicht im Inhalt: keine Figuren, Orte oder Sätze aus seinen Werken."
    if v.get("art") == "mensch":
        return f"Du schreibst wie {v['vorbild'] or 'dieser Mensch'} – so, als hätte er/sie diese Folge selbst geschrieben."
    return "Du schreibst in der unten beschriebenen Stimme."


def _slider_lines(v: dict) -> list:
    out = []
    for key, label, *steps in SLIDERS:
        value = int((v.get("regler") or {}).get(key, 0))
        if value:
            word = steps[{-2: 0, -1: 1, 1: 2, 2: 3}[value]]
            out.append(f"- {label}: {word}" + ("" if key == "naehe" else " (gegenüber dem Vorbild)"))
    return out


def brief(v: dict) -> str:
    labels = dict(FIELDS)
    lines = [f"- {labels[k]}: {val}" for k, val in (v.get("steckbrief") or {}).items() if k in labels and val]
    if not lines and v.get("beschreibung"):
        lines = [f"- Beschreibung: {v['beschreibung']}"]
    return "\n".join(lines)


def writer_block(v: dict | None) -> str:
    """Für Planer, Autor und Lektor: so klingt diese Folge."""
    if not v:
        return ""
    parts = [f"STIMME „{v['name']}“ (virtueller Autor dieser Folge). {_vorbild_satz(v)}",
             "STIL-STECKBRIEF:\n" + (brief(v) or "- (noch kein Steckbrief – orientiere dich am Vorbild)")]
    sliders = _slider_lines(v)
    if sliders:
        parts.append("JUSTIERUNG (gegenüber dem Vorbild):\n" + "\n".join(sliders))
    if v.get("hinweise"):
        parts.append("HINWEISE DES MENSCHEN ZUR STIMME (verbindlich):\n" + v["hinweise"])
    anchor = anchors(v)
    if anchor:
        parts.append("STILANKER – so klingt diese Stimme (Ton, Rhythmus, Satzbau übernehmen; Inhalt NICHT übernehmen, "
                     "nichts wörtlich abschreiben):\n" + anchor)
    parts.append("Rangfolge: Weltregeln, Kanon, Dramaturgie (Anfang · Mitte · Ende), Altersfreigabe und das Hörbuchformat "
                 "([Sprecher] je Absatz) gehen vor. Innerhalb davon klingt alles nach dieser Stimme.")
    return "\n\n".join(parts)


def checker_block(v: dict | None) -> str:
    """Für den Prüfer: woran der Stil gemessen wird."""
    if not v:
        return ""
    parts = [f"STIL-MASSSTAB: Stimme „{v['name']}“. {_vorbild_satz(v)}", "STIL-STECKBRIEF:\n" + (brief(v) or "-")]
    sliders = _slider_lines(v)
    if sliders:
        parts.append("JUSTIERUNG:\n" + "\n".join(sliders))
    if v.get("hinweise"):
        parts.append("HINWEISE DES MENSCHEN:\n" + v["hinweise"])
    m = v.get("messwerte")
    if m:
        parts.append(f"MESSWERTE DES MASSSTABS ({m.get('quelle', '')}): Satzlänge Ø {m.get('satzlaenge')} Wörter, "
                     f"Dialoganteil {m.get('dialoganteil')}, Wortlänge Ø {m.get('wortlaenge')} Buchstaben, "
                     f"Absatzlänge Ø {m.get('absatzlaenge')} Wörter.")
    parts.append("Weicht die Folge deutlich von dieser Stimme ab, melde es mit Kategorie „Stil“ in der Beschreibung "
                 "(„Stil: …“), Schwere „niedrig“ oder „mittel“, und gib als Korrektur an, was der Lektor ändern soll.")
    return "\n\n".join(parts)


def summary(v: dict | None) -> dict | None:
    """Kurzform für Protokoll und Nachvollzug."""
    if not v:
        return None
    return {"id": v["id"], "name": v["name"], "art": v["art"], "vorbild": v.get("vorbild"),
            "regler": {k: x for k, x in (v.get("regler") or {}).items() if x},
            "probe_freigegeben": bool((v.get("probe") or {}).get("freigegeben")), "messwerte": v.get("messwerte"),
            "steckbrief_kurz": (v.get("steckbrief") or {}).get("kurz")}


# ---------------------------------------------------------------- KI: Steckbrief und Probe

def _fields_schema() -> str:
    return ", ".join(f'"{k}": "…"' for k, _ in FIELDS)


def analyze(vid: str) -> dict:
    v = get(vid)
    if v is None:
        raise LookupError("Stimme nicht gefunden.")
    extra = ""
    if v.get("beschreibung"):
        extra += f"Ergänzende Beschreibung des Menschen: {v['beschreibung']}\n"
    if v.get("hinweise"):
        extra += f"Hinweise des Menschen: {v['hinweise']}\n"
    if v["art"] == "autor":
        system = ANALYZE_AUTHOR.format(vorbild=v["vorbild"], extra=extra, fields=_fields_schema())
        user = f"Vorbild: {v['vorbild']}"
    elif v["art"] == "mensch":
        sample = _texts(v, 20000)
        if not sample:
            raise VoiceError("Keine Texte gewählt – bitte unter „Basis“ mindestens einen eigenen Text auswählen.")
        system = ANALYZE_TEXTS.format(extra=extra, fields=_fields_schema())
        user = "TEXTPROBEN:\n\n" + sample
    else:
        if not v.get("beschreibung"):
            raise VoiceError("Bitte zuerst beschreiben, wie die Stimme klingen soll.")
        system = ANALYZE_FREE.format(extra=extra, fields=_fields_schema())
        user = "Gewünschter Stil: " + v["beschreibung"]
    try:
        text, used = providers.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                        "profil", json_mode=True, max_tokens=3000, temperature=0.4)
    except providers.ProviderError as exc:
        raise VoiceError(str(exc))
    data = llm._extract_json(text)
    brief_data = data.get("steckbrief") if isinstance(data, dict) else None
    if not isinstance(brief_data, dict) or not brief_data.get("satzbau"):
        raise VoiceError("Die KI hat keinen brauchbaren Steckbrief geliefert – bitte erneut versuchen.")

    def apply(x):
        x["steckbrief"] = {k: str(brief_data.get(k, ""))[:2000] for k, _ in FIELDS if brief_data.get(k)}
        x["ausgewertet"] = _now()
        x["modell"] = used
    return _update(vid, apply)


def probe(vid: str, welt: str = "", woerter: int = 220) -> dict:
    """Schreibt einen kurzen Probeabsatz in dieser Stimme (noch nicht freigegeben)."""
    v = get(vid)
    if v is None:
        raise LookupError("Stimme nicht gefunden.")
    messages = [{"role": "system", "content": writer_block(v)},
                {"role": "user", "content": PROBE_TASK.format(woerter=max(80, min(600, int(woerter))),
                                                               welt=welt or "eine Science-Fiction-Welt, 350 Jahre in der Zukunft")}]
    try:
        text, used = providers.complete(messages, "autor", json_mode=False, max_tokens=2000)
    except providers.ProviderError as exc:
        raise VoiceError(str(exc))
    text = (text or "").strip()
    if len(text.split()) < 40:
        raise VoiceError("Die Probe ist zu kurz geraten – bitte erneut versuchen.")

    def apply(x):
        old = x.get("probe")
        if old and old.get("text"):
            x.setdefault("proben_archiv", []).append(old)
            x["proben_archiv"] = x["proben_archiv"][-10:]
        x["probe"] = {"text": text, "modell": used, "am": _now(), "freigegeben": False,
                      "regler": dict(x.get("regler") or {})}
    return _update(vid, apply)


def approve_probe(vid: str, ok: bool = True) -> dict:
    def apply(x):
        p = x.get("probe")
        if not p or not p.get("text"):
            raise VoiceError("Es gibt noch keine Probe.")
        p["freigegeben"] = bool(ok)
        p["freigegeben_am"] = _now() if ok else None
        if x["art"] != "mensch" and ok:
            x["messwerte"] = dict(quality.style_values(p["text"]), quelle="freigegebene Probe")
        elif x["art"] != "mensch":
            x["messwerte"] = None
    return _update(vid, apply)


# ---------------------------------------------------------------- Welche Stimme gilt?

def dangling(conn, stimme_id: str | None, thread_id: int | None) -> list:
    """Verweise auf Stimmen, die es auf diesem Rechner nicht (mehr) gibt – z. B. Welt ohne Stimmen umgezogen."""
    refs = [("Folge", stimme_id)]
    try:
        if thread_id:
            row = conn.execute("SELECT stimme_id FROM threads WHERE id = ?", (thread_id,)).fetchone()
            refs.append(("Geschichte", row[0] if row else None))
        from . import service
        refs.append(("Welt", service.setting(conn, "stimme")))
    except Exception:  # noqa: BLE001
        pass
    return [(src, vid) for src, vid in refs if vid and not get(vid)]


def resolve(conn, stimme_id: str | None, thread_id: int | None) -> tuple:
    """(Stimme oder None, Quelle) – Folge vor Geschichte vor Welt."""
    if stimme_id:
        v = get(stimme_id)
        if v:
            return v, "Folge"
    if thread_id:
        try:
            row = conn.execute("SELECT stimme_id FROM threads WHERE id = ?", (thread_id,)).fetchone()
        except Exception:  # noqa: BLE001 – ältere Datenbank
            row = None
        if row and row[0] and get(row[0]):
            return get(row[0]), "Geschichte"
    from . import service
    try:
        world = service.setting(conn, "stimme")
    except Exception:  # noqa: BLE001
        world = ""
    if world and get(world):
        return get(world), "Welt"
    return None, None


# ---------------------------------------------------------------- Austausch (Export/Import)

def public(v: dict) -> dict:
    """Für die Oberfläche: Basis aus verborgenen Texten nur als Kennzahlen, nie als Text."""
    out = dict(v)
    basis = v.get("basis")
    if basis:
        out["basis"] = {k: basis.get(k) for k in ("owner", "owner_name", "verborgen", "quelle", "importiert")}
        out["basis"]["anker_zeichen"] = len(basis.get("anker") or "")
        out["basis"]["referenz_zeichen"] = len(basis.get("referenz") or "")
        if not basis.get("verborgen"):
            out["basis"]["anker"] = basis.get("anker")
    return out


def export_copy(v: dict) -> dict:
    """Stimme für einen Welt-Export: alles, was zum Weiterschreiben nötig ist – bei „mensch“ statt der vollständigen
    Texte nur Stilanker und Maßstab-Auszug (Basis)."""
    out = json.loads(json.dumps(v))
    if v.get("art") == "mensch":
        old = v.get("basis") or {}
        p = profiles.get(v.get("profil_id"))
        out["basis"] = {"owner": old.get("owner") or v.get("profil_id"),
                        "owner_name": old.get("owner_name") or (p or {}).get("name") or v.get("vorbild"),
                        "anker": _local_texts(v, 4500) or old.get("anker") or "",
                        "referenz": _local_texts(v, 40000) or old.get("referenz") or "",
                        "verborgen": bool(old.get("verborgen"))}
        if not out["basis"]["referenz"] and (out.get("messwerte") or {}).get("quelle") == "eigene Texte":
            out["messwerte"] = None  # kein Text mehr als Basis → kein Maßstab mitgeben, der nicht belegt ist
    return out


def import_voice(v: dict, local_profiles: set, quelle: str) -> str:
    """Nimmt eine Stimme aus einem Export auf. Rückgabe: „vorhanden“, „neu“ oder „neu (verborgen)“.
    Basis-Texte sind nur sichtbar, wenn ihr Besitzer (Profil-ID) auf diesem Rechner existiert."""
    if not isinstance(v, dict) or not str(v.get("id", "")).startswith("v_"):
        return "ungültig"
    with _LOCK:
        data = _load()
        if any(x["id"] == v["id"] for x in data["stimmen"] + data["archiv"]):
            return "vorhanden"
        item = json.loads(json.dumps(v))
        state = "neu"
        if item.get("basis"):
            item["basis"]["verborgen"] = item["basis"].get("owner") not in local_profiles
            item["basis"]["quelle"] = quelle
            item["basis"]["importiert"] = _now()
            if item["basis"]["verborgen"]:
                state = "neu (Basis verborgen)"
        data["stimmen"].append(item)
        _save(data)
    return state


FILE_FORMAT = "evel-stimmen"


def export_file(ids=None) -> dict:
    """Schreibstil-Export als JSON-Datei: gewählte Stimmen (ohne ids: alle aktiven) wie im Welt-Export – bei „mensch“
    nur Stilanker und Maßstab-Auszug, nie die vollständigen Texte. Probe-Audio bleibt auf diesem Rechner."""
    from . import __version__
    data = _load()
    pool = data["stimmen"] + data["archiv"]
    chosen = [v for v in pool if v["id"] in set(ids)] if ids else list(data["stimmen"])
    if ids and len(chosen) != len(set(ids)):
        raise VoiceError("Mindestens eine gewählte Stimme gibt es nicht (mehr).")
    if not chosen:
        raise VoiceError("Keine Stimme zum Exportieren.")
    voices = []
    for v in chosen:
        out = export_copy(v)
        if isinstance(out.get("probe"), dict):
            out["probe"].pop("audio", None)
        out.pop("archiviert_am", None)
        voices.append(out)
    return {"format": FILE_FORMAT, "version": 1, "programm": __version__, "exportiert": _now(), "stimmen": voices}


def _same(a: dict, b: dict) -> bool:
    keys = ("art", "vorbild", "beschreibung", "steckbrief", "regler", "hinweise")
    return all(a.get(k) == b.get(k) for k in keys) and (a.get("probe") or {}).get("text") == (b.get("probe") or {}).get("text")


def _free_name(name: str, taken: set) -> str:
    """„Leise“ → „Leise 2“, „Leise 3“ … – erste freie Ziffer."""
    base = re.sub(r"\s+\d+$", "", name).strip() or name
    n = 2
    while f"{base} {n}".lower() in taken:
        n += 1
    return f"{base} {n}"


def import_file(payload: dict, local_profiles: set) -> dict:
    """Schreibstil-Import. Vorhandene Stimmen werden nie überschrieben: Ist dieselbe Stimme schon unverändert da,
    passiert nichts. Sonst kommt sie neu dazu – ist ihr Name oder ihre Kennung schon vergeben, mit neuer Kennung und
    einer Ziffer am Namen („Leise 2“). Probe-Audio gehört zum Rechner (Welt, TTS-Stimme) und wird dort neu erzeugt."""
    if not isinstance(payload, dict) or payload.get("format") != FILE_FORMAT or not isinstance(payload.get("stimmen"), list):
        raise VoiceError("Das ist keine Schreibstil-Exportdatei (evel-stimmen).")
    report = {"neu": [], "umbenannt": [], "vorhanden": [], "ids": [], "verborgen": 0, "ungueltig": 0}
    for v in payload["stimmen"]:
        if not isinstance(v, dict) or not str(v.get("id", "")).startswith("v_") or not str(v.get("name", "")).strip():
            report["ungueltig"] += 1
            continue
        pool = all_raw()["stimmen"] + all_raw()["archiv"]
        same_id = next((x for x in pool if x["id"] == v["id"]), None)
        if same_id is not None and _same(same_id, v) and same_id.get("name") == v.get("name"):
            report["vorhanden"].append(same_id["name"])
            report["ids"].append(same_id["id"])
            continue
        item = json.loads(json.dumps(v))
        item["name"] = str(item["name"]).strip()[:80]
        taken = {str(x.get("name", "")).strip().lower() for x in pool}
        if same_id is not None:
            item["id"] = "v_" + uuid.uuid4().hex[:8]
        if item["name"].lower() in taken:
            item["name"] = _free_name(item["name"], taken)
            report["umbenannt"].append({"alt": v["name"], "neu": item["name"]})
        else:
            report["neu"].append(item["name"])
        if isinstance(item.get("probe"), dict):
            item["probe"].pop("audio", None)
        item["bearbeitet"] = _now()
        state = import_voice(item, local_profiles, "Schreibstil-Import")
        if state == "ungültig":
            report["ungueltig"] += 1
            continue
        report["ids"].append(item["id"])
        if "verborgen" in state:
            report["verborgen"] += 1
    return report


def all_raw() -> dict:
    return _load()


def unhide_owner(pid: str) -> int:
    """Der Besitzer ist jetzt auf diesem Rechner (Autor-Import): seine Basis-Texte werden wieder sichtbar."""
    count = 0
    with _LOCK:
        data = _load()
        for v in data["stimmen"] + data["archiv"]:
            basis = v.get("basis")
            if basis and basis.get("verborgen") and basis.get("owner") == pid:
                basis["verborgen"] = False
                count += 1
        if count:
            _save(data)
    return count


# ---------------------------------------------------------------- Probe anhören (TTS, eine Stimme)

def probe_audio_path(vid: str) -> Path:
    from . import worlds
    if not (vid.startswith("v_") and vid[2:].isalnum()):
        raise LookupError("Stimme nicht gefunden.")
    return worlds.worlds_dir() / "audio" / "_stimmen" / vid / "probe.wav"


def _probe_hash(text: str) -> str:
    import hashlib
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def probe_audio(vid: str, ref: str, words: list | None = None, speak=None) -> dict:
    """Probe als Hörbuch mit einer Stimme vertonen (TTS-Server). Sprecher-Marken [Name] werden nicht vorgelesen."""
    from . import episodes, tts
    v = get(vid)
    if v is None:
        raise LookupError("Stimme nicht gefunden.")
    text = (v.get("probe") or {}).get("text") or ""
    if not text.strip():
        raise VoiceError("Es gibt noch keine Probe zum Vorlesen.")
    if not ref:
        raise VoiceError("Bitte eine Vorlese-Stimme wählen (oder in der Welt eine Erzähler-Stimme besetzen).")
    segments = [seg["text"] for seg in episodes.parse_segments(text)] or [text]
    try:
        info = tts.speak_single(segments, ref, probe_audio_path(vid), words, speak)
    except (tts.TTSError, ValueError) as exc:
        raise VoiceError(str(exc))

    def apply(x):
        if x.get("probe"):
            x["probe"]["audio"] = dict(info, ref=ref, text=_probe_hash(text), am=_now())
    return _update(vid, apply)


def probe_audio_current(v: dict) -> bool:
    p = v.get("probe") or {}
    return bool(p.get("audio")) and p["audio"].get("text") == _probe_hash(p.get("text") or "") \
        and probe_audio_path(v["id"]).exists()
