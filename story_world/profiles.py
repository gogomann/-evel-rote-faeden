"""Menschen und Erzählprofile – kein Login, nur „wer bedient gerade?“.

Ein kurzes Interview mit indirekten Fragen erfasst Habitus, Stil und innere Motivation; die KI verdichtet daraus ein
Erzählprofil (keine Diagnosen, nur Erzählhaltung) und stellt gezielte Nachfragen. Das Profil fließt in Planer, Autor,
Lektor und Prüfer ein, damit die Geschichten sich lesen wie aus der Feder dieses Menschen.

Speicherort: story_world.profiles.json im Projektordner (oder STORY_PROFILES), Dateirechte 0600, per .gitignore
ausgeschlossen. Entfernte Profile wandern ins Archiv statt gelöscht zu werden.
"""

from __future__ import annotations

import json
import re
import os
import threading
import time
import uuid
from pathlib import Path

from . import llm, providers

ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.RLock()

# Fragen bewusst indirekt: Wie jemand erzählt, zeigt sich eher in Beispielen und Stilproben als in Selbstauskünften.
QUESTIONS = [
    {"id": "name", "frage": "Wie heißt du – oder wie sollen wir dich nennen?", "art": "kurz"},
    {"id": "fuer_wen", "frage": "Für wen sind die Geschichten? Nur für dich, für zwei, für Kinder (welches Alter)?",
     "art": "kurz"},
    {"id": "lieblingsgeschichte", "frage": "Erzähl von einer Geschichte – Buch, Film, Hörspiel –, die dich nicht "
     "losgelassen hat. Was genau hat dich daran gepackt?", "art": "lang"},
    {"id": "abendgefuehl", "frage": "Wenn du abends eine Geschichte hörst: Soll sie dich eher beruhigen, fordern, "
     "zum Lachen bringen, gruseln – oder etwas ganz anderes?", "art": "lang"},
    {"id": "genres", "frage": "Welche Genres magst du, welche gar nicht? (z. B. Science-Fiction, Krimi, Horror, Fantasy, "
     "Drama, Komödie, Märchen, Grusel für Kinder)", "art": "lang"},
    {"id": "wohlfuehlort", "frage": "Beschreib in zwei, drei Sätzen einen Ort, an dem du dich wohlfühlst – so, wie es "
     "dir in den Sinn kommt. (Hier zählt auch, WIE du schreibst.)", "art": "lang"},
    {"id": "konflikt", "frage": "Ein Gespräch kippt in Streit. Was machst du normalerweise – vermitteln, klar Kante "
     "zeigen, abwarten, mit Humor entschärfen, gehen?", "art": "lang"},
    {"id": "figur", "frage": "Welche Rolle hättest du in einer Raumschiff-Crew am liebsten – Anführerin, Tüftler, "
     "Beobachterin, Heilerin, Zweifler, jemand ganz anderes? Und warum?", "art": "lang"},
    {"id": "humor", "frage": "Was bringt dich zum Lachen? Trocken, albern, schwarz, Situationskomik, eher wenig?",
     "art": "lang"},
    {"id": "gedanken", "frage": "Worüber denkst du in letzter Zeit öfter nach – im Kleinen oder im Großen?", "art": "lang"},
    {"id": "tabus", "frage": "Was soll in deinen Geschichten nie passieren?", "art": "lang"},
    {"id": "stilprobe", "frage": "Und zum Schluss: Schreib den ersten Satz einer Geschichte, wie du sie beginnen würdest.",
     "art": "lang"},
]

PROFILE_FIELDS = [
    ("zusammenfassung", "Kurzporträt als Erzähler:in"),
    ("stimme", "Erzählstimme"),
    ("satzbau", "Satzbau und Rhythmus"),
    ("wortwahl", "Wortwahl"),
    ("tempo", "Tempo und Spannung"),
    ("humor", "Humor"),
    ("perspektive", "Lieblingsperspektiven und Figuren"),
    ("motive", "Wiederkehrende Motive und Themen"),
    ("werte", "Werte, die durchscheinen"),
    ("innere_motivation", "Innere Motivation (was selten benannt wird)"),
    ("genres", "Genres: mag / mag nicht"),
    ("tabus", "Tabus"),
    ("publikum", "Für wen"),
]

PROFILE_PROMPT = """Du bist eine einfühlsame Lektorin. Aus den Interview-Antworten eines Menschen erstellst du sein ERZÄHLPROFIL:
wie Geschichten klingen müssen, damit sie wie aus seiner Feder wirken. Lies auch zwischen den Zeilen – Stil der Antworten,
Wortwahl, Satzlänge, was jemand betont oder auslässt. Formuliere als Erzählhaltung, niemals als Diagnose oder Bewertung
der Person. Keine Gesundheits- oder Persönlichkeitsetiketten. Deutsch, konkret, als Schreibanweisung nutzbar.

Antworte NUR mit JSON:
{
  "profil": {""" + ", ".join(f'"{k}": "…"' for k, _ in PROFILE_FIELDS) + """},
  "nachfragen": ["bis zu 3 kurze Fragen, nur wo etwas Wichtiges unklar ist – sonst leere Liste"]
}"""


class ProfileError(RuntimeError):
    pass


# ---------------------------------------------------------------- Speicher

def path() -> Path:
    return Path(os.environ.get("STORY_PROFILES", ROOT / "story_world.profiles.json"))


def _load() -> dict:
    with _LOCK:
        file = path()
        if not file.exists():
            return {"profiles": [], "archiv": []}
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except ValueError:
            file.rename(file.with_suffix(f".defekt-{int(time.time())}.json"))
            return {"profiles": [], "archiv": []}
        data.setdefault("profiles", [])
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


def list_profiles() -> dict:
    data = _load()
    items = sorted(data["profiles"], key=lambda p: p.get("last_used") or "", reverse=True)
    return {"profiles": [_public(p) for p in items], "archiv": [_public(p) for p in data["archiv"]]}


def _public(p: dict) -> dict:
    return {k: v for k, v in p.items()}


def get(pid: str | None) -> dict | None:
    if not pid:
        return None
    return next((p for p in _load()["profiles"] if p["id"] == pid), None)


def create(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ProfileError("Bitte einen Namen angeben.")
    profile = {"id": "u_" + uuid.uuid4().hex[:8], "name": name, "created": _now(), "last_used": _now(),
               "status": "interview", "antworten": {"name": name}, "nachfragen": [], "profil": {}}
    with _LOCK:
        data = _load()
        data["profiles"].append(profile)
        _save(data)
    return profile


def _update(pid: str, fn) -> dict:
    with _LOCK:
        data = _load()
        for p in data["profiles"]:
            if p["id"] == pid:
                fn(p)
                _save(data)
                return p
    raise LookupError("Profil nicht gefunden.")


def touch(pid: str) -> dict:
    return _update(pid, lambda p: p.update(last_used=_now()))


def save_answers(pid: str, answers: dict) -> dict:
    allowed = {q["id"] for q in QUESTIONS}

    def apply(p):
        for key, value in answers.items():
            if key in allowed and isinstance(value, str):
                p["antworten"][key] = value.strip()[:4000]
        if answers.get("name", "").strip():
            p["name"] = answers["name"].strip()[:80]
    return _update(pid, apply)


def save_followups(pid: str, replies: list) -> dict:
    def apply(p):
        for item in p.get("nachfragen", []):
            for reply in replies:
                if reply.get("frage") == item.get("frage") and isinstance(reply.get("antwort"), str):
                    item["antwort"] = reply["antwort"].strip()[:4000]
    return _update(pid, apply)


def edit_profile(pid: str, fields: dict) -> dict:
    allowed = {k for k, _ in PROFILE_FIELDS}

    def apply(p):
        for key, value in fields.items():
            if key in allowed and isinstance(value, str):
                p["profil"][key] = value.strip()[:3000]
        p["status"] = "fertig" if p["profil"] else p["status"]
        p["bearbeitet"] = _now()
    return _update(pid, apply)


def archive(pid: str) -> None:
    with _LOCK:
        data = _load()
        moved = [p for p in data["profiles"] if p["id"] == pid]
        if not moved:
            raise LookupError("Profil nicht gefunden.")
        moved[0]["archiviert_am"] = _now()
        data["profiles"] = [p for p in data["profiles"] if p["id"] != pid]
        data["archiv"].append(moved[0])
        _save(data)


def restore(pid: str) -> None:
    with _LOCK:
        data = _load()
        moved = [p for p in data["archiv"] if p["id"] == pid]
        if not moved:
            raise LookupError("Archiviertes Profil nicht gefunden.")
        moved[0].pop("archiviert_am", None)
        data["archiv"] = [p for p in data["archiv"] if p["id"] != pid]
        data["profiles"].append(moved[0])
        _save(data)


# ---------------------------------------------------------------- Texte als Basis

TEXT_LIMIT = 2_000_000  # Zeichen je Text


def text_dir(pid: str) -> Path:
    base = Path(os.environ.get("STORY_PROFILE_TEXTS", ROOT / "profile_texte"))
    folder = base / pid
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def _text_file(pid: str, tid: str) -> Path:
    if not (tid.startswith("t_") and tid[2:].isalnum()):
        raise LookupError("Text nicht gefunden.")
    return text_dir(pid) / f"{tid}.txt"


def add_text(pid: str, titel: str, text: str, quelle: str = "", stil: bool = True) -> dict:
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise ProfileError("Der Text ist leer.")
    if len(text) > TEXT_LIMIT:
        raise ProfileError(f"Text zu lang (höchstens {TEXT_LIMIT:,} Zeichen).".replace(",", "."))
    if get(pid) is None:
        raise LookupError("Profil nicht gefunden.")
    tid = "t_" + uuid.uuid4().hex[:8]
    file = _text_file(pid, tid)
    fd = os.open(str(file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    meta = {"id": tid, "titel": (titel or "").strip()[:120] or text.splitlines()[0][:80], "quelle": (quelle or "")[:200],
            "zeichen": len(text), "woerter": len(text.split()), "erstellt": _now(), "stil": bool(stil), "eingelesen": []}
    _update(pid, lambda p: p.setdefault("texte", []).append(meta))
    return meta


def read_text(pid: str, tid: str) -> str:
    file = _text_file(pid, tid)
    if not file.exists():
        raise LookupError("Text nicht gefunden.")
    return file.read_text(encoding="utf-8")


def update_text(pid: str, tid: str, changes: dict) -> dict:
    def apply(p):
        for t in p.get("texte", []):
            if t["id"] == tid:
                if isinstance(changes.get("titel"), str) and changes["titel"].strip():
                    t["titel"] = changes["titel"].strip()[:120]
                if "stil" in changes:
                    t["stil"] = bool(changes["stil"])
                return
        raise LookupError("Text nicht gefunden.")
    return _update(pid, apply)


def note_import(pid: str, tid: str, welt: str, teile: int) -> None:
    def apply(p):
        for t in p.get("texte", []):
            if t["id"] == tid:
                t.setdefault("eingelesen", []).append({"welt": welt, "am": _now(), "teile": teile})
    try:
        _update(pid, apply)
    except LookupError:
        pass


def archive_text(pid: str, tid: str, back: bool = False) -> dict:
    """Nichts wird gelöscht: Text wandert ins Archiv des Profils (Datei bleibt liegen)."""
    src, dst = ("texte_archiv", "texte") if back else ("texte", "texte_archiv")

    def apply(p):
        item = next((t for t in p.get(src, []) if t["id"] == tid), None)
        if item is None:
            raise LookupError("Text nicht gefunden.")
        p[src] = [t for t in p[src] if t["id"] != tid]
        if back:
            item.pop("archiviert_am", None)
        else:
            item["archiviert_am"] = _now()
        p.setdefault(dst, []).append(item)
    return _update(pid, apply)


def split_text(text: str, size: int = 12000) -> list:
    """Teilt an Absätzen (notfalls Sätzen) in Abschnitte von höchstens etwa `size` Zeichen."""
    parts, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        while len(para) > size:
            cut = max(para.rfind(". ", 0, size), para.rfind("\n", 0, size))
            cut = cut + 1 if cut > size // 2 else size
            pieces = [para[:cut].strip(), para[cut:].strip()]
            if current:
                parts.append(current)
                current = ""
            parts.append(pieces[0])
            para = pieces[1]
        if current and len(current) + len(para) + 2 > size:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def style_samples(p: dict, budget: int = 12000) -> str:
    """Auszüge aus den als Stilprobe markierten Texten (Anfang und Mitte), zusammen höchstens `budget` Zeichen."""
    texts = [t for t in p.get("texte", []) if t.get("stil")]
    if not texts:
        return ""
    share = max(1500, budget // len(texts))
    out = []
    for t in texts[:8]:
        try:
            body = read_text(p["id"], t["id"])
        except LookupError:
            continue
        half = share // 2
        sample = body[:half] + ("\n[…]\n" + body[len(body) // 2: len(body) // 2 + half] if len(body) > share else "")
        out.append(f"TEXTPROBE „{t['titel']}“:\n{sample.strip()}")
    return "\n\n".join(out)[:budget + 2000]


# ---------------------------------------------------------------- KI-Auswertung

def analyze(pid: str) -> dict:
    """Verdichtet Antworten (und beantwortete Nachfragen) zu einem Erzählprofil."""
    p = get(pid)
    if p is None:
        raise LookupError("Profil nicht gefunden.")
    answered = [q for q in QUESTIONS if p["antworten"].get(q["id"])]
    samples = style_samples(p)
    if len(answered) < 4 and not samples:
        raise ProfileError("Bitte mindestens vier Fragen beantworten oder einen eigenen Text als Stilprobe hinterlegen.")
    lines = [f"FRAGE: {q['frage']}\nANTWORT: {p['antworten'][q['id']]}" for q in answered]
    lines += [f"NACHFRAGE: {n['frage']}\nANTWORT: {n['antwort']}" for n in p.get("nachfragen", []) if n.get("antwort")]
    if samples:
        lines.append("EIGENE TEXTE DES MENSCHEN (Stil, Rhythmus, Wortwahl und Motive daraus ableiten – den Inhalt nicht "
                     "nacherzählen):\n\n" + samples)
    messages = [{"role": "system", "content": PROFILE_PROMPT},
                {"role": "user", "content": "\n\n".join(lines)}]
    try:
        text, used = providers.complete(messages, "profil", json_mode=True, max_tokens=3000, temperature=0.4)
    except providers.ProviderError as exc:
        raise ProfileError(str(exc))
    data = llm._extract_json(text)
    profile = data.get("profil") if isinstance(data, dict) else None
    if not isinstance(profile, dict) or not profile.get("stimme"):
        raise ProfileError("Die KI hat kein brauchbares Profil geliefert – bitte erneut versuchen.")
    asked = {n["frage"] for n in p.get("nachfragen", [])}
    new_questions = [q for q in data.get("nachfragen") or [] if isinstance(q, str) and q.strip() and q not in asked][:3]

    def apply(pr):
        pr["profil"] = {k: str(profile.get(k, ""))[:3000] for k, _ in PROFILE_FIELDS if profile.get(k)}
        pr["nachfragen"] = pr.get("nachfragen", []) + [{"frage": q.strip(), "antwort": ""} for q in new_questions]
        pr["status"] = "fertig"
        pr["ausgewertet"] = _now()
        pr["modell"] = used
    return _update(pid, apply)


def style_block(profile: dict | None) -> str:
    """Schreibanweisung aus dem Erzählprofil für Planer, Autor, Lektor und Prüfer."""
    if not profile or not profile.get("profil"):
        return ""
    labels = dict(PROFILE_FIELDS)
    lines = [f"- {labels[k]}: {v}" for k, v in profile["profil"].items() if k in labels and v]
    return (f"ERZÄHLPROFIL von {profile.get('name', 'dem Nutzer')} – die Geschichte soll klingen, als hätte "
            "dieser Mensch sie selbst geschrieben (Stimme, Rhythmus, Humor, Motive), ohne die Weltregeln zu verletzen:\n"
            + "\n".join(lines))
