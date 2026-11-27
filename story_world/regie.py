"""Hörspiel-Regie: Sprechstil und Geräusch-Tags – je Absatz und innerhalb eines Absatzes – für TTS-Server, die das
können (Libra-TTS).

Die KI (Aufgabe „regie“) liest die Absätze einer Folge und legt je Absatz fest:
- stil: Anfangsstil (warm, sad, whispering …) oder keiner (neutral),
- text: derselbe Wortlaut mit Geräusch-Tags (<sigh>, <laugh>, <short pause> …) und Stilwechseln mitten im Absatz
  ([documentary] vor Zahlen und Erklärungen, [warm] zurück zum Persönlichen, [neutral] = ohne Stil). Menschen sprechen
  je nach Inhalt anders – jeder Teil geht mit seinem eigenen Stil an den Server.
Tempo: Die KI setzt keins (normal) – der Stil bringt sein Tempo mit. Nur ein von Hand gesetztes „slow“/„fast“ geht
als „pace“ an den Server. Tempi aus Regie-Fassungen vor Version 2 (von der KI gesetzt) werden ignoriert.

Bei der KI wird der Wortlaut geprüft: Ohne Tags und Stilwechsel (und ohne Leerraum) muss exakt der Originaltext
herauskommen, sonst gilt der Originaltext. Von Hand darf der Sprechtext auch anders formuliert sein (Wörter anpassen,
Satz umbauen, damit es gesprochen gut klingt) – das gilt nur fürs Hörspiel; Folgentext, Anzeige und Kanon bleiben
im Original. Unbekannte Tags fliegen raus, je Stufe gibt es eine Obergrenze an Gefühls-Tags je Absatz.
Atmen setzt der Code selbst (atmen), damit es nicht von der KI abhängt: regelmäßig nach genug gesprochenem Text und vor
sehr langen Sätzen ein <breath> (bei Angst/Aufregung einmal <heavy breath>) – so klingt die Stimme nach einem Menschen.

Takes je Absatz: Jeder Absatz lässt sich einzeln sprechen, anhören und neu aufnehmen (take_neu). Ein Take ist ein Seed –
gleicher Text + anderer Seed = andere Aufnahme. „takes“ merkt alle Seeds eines Absatzes, „take“ den gewählten; jeder Take
bleibt hörbar und wählbar. Erst das Zusammenfügen (tts.render) baut aus den gewählten Takes die MP3 – alles, was schon
gesprochen wurde, kommt dabei aus dem Zwischenspeicher.

Gespeichert wird die Regie je Folge in world_meta („tts.regie.<id>“); der Folgentext bleibt unberührt – Kanon,
Anzeige, Vorlesen im Browser und macOS-Vertonung sehen keine Tags. Ändert sich der Folgentext oder die Stufe, entsteht
die Regie beim nächsten Vertonen neu (die alte liegt unter „tts.regie.<id>.vorher“). Von Hand bearbeitete Regie bleibt,
solange der Text gleich ist. Stufen je Folge: aus, dezent (Standard), lebendig.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time

from . import episodes, runs, service

STILE = ["warm", "cheerful", "excited", "sad", "frightened", "calm", "serious", "wry", "tender", "whispering",
         "dramatic", "documentary"]
TEMPI = ["slow", "fast"]  # nur von Hand gesetzt; die KI setzt kein Tempo
TAGS = ["<laugh>", "<chuckle>", "<giggle>", "<snicker>", "<sigh>", "<gasp>", "<breath>", "<heavy breath>", "<exhales>",
        "<phew>", "<short pause>", "<long pause>", "<cough>", "<throat-clearing>", "<sneeze>", "<yawn>", "<sob>", "<cry>",
        "<whimper>", "<groan>", "<tsk>", "<shout>"]
NEUTRAL = "neutral"
STUFEN = {"aus": "Aus – neutral vorlesen", "dezent": "Dezent – Stimmung, selten Geräusche",
          "lebendig": "Lebendig – mehr Gefühl und Geräusche"}
STANDARD_STUFE = "dezent"
MAX_TAGS = {"dezent": 1, "lebendig": 3, "hand": 12}  # Gefühls-Tags je Absatz; Atem-Tags zählen nicht mit
ATEM_TAGS = ("<breath>", "<heavy breath>", "<exhales>")
# Atmer nach so vielen gesprochenen Zeichen seit dem letzten Atmer bzw. vor Sätzen ab dieser Länge
ATEM = {"dezent": {"zeichen": 220, "lang": 150, "auftakt": None},
        "lebendig": {"zeichen": 150, "lang": 120, "auftakt": 240}}
BATCH_SEGMENTS = 30
BATCH_CHARS = 7000
VERSION = 2

_TAG = re.compile(r"<[^<>\n]{1,40}>")
_MARK = re.compile(r"\[([a-z][a-z-]{1,24})\]")
_PROTECTED = re.compile("([0-9a-f]+)")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_SAVE_LOCK = threading.Lock()


class RegieError(RuntimeError):
    pass


def _caps_default() -> dict:
    return {"stile": list(STILE), "tempi": list(TEMPI), "tags": list(TAGS)}


# ---------------------------------------------------------------- Fähigkeiten der Server

def faehig(server: dict | None) -> dict | None:
    """Stile und Tags, die der Server kann (aus „Prüfen & Stimmen laden“), sonst None."""
    if not server:
        return None
    info = server.get("regie") or {}
    if info.get("stile") or info.get("tags"):
        return {"stile": list(info.get("stile") or []), "tempi": list(info.get("tempi") or TEMPI),
                "tags": list(info.get("tags") or [])}
    if server.get("preset") == "libra":
        return _caps_default()
    return None


def vereinigen(caps: list) -> dict | None:
    caps = [c for c in caps if c]
    if not caps:
        return None
    out = {"stile": [], "tempi": [], "tags": []}
    for c in caps:
        for key in out:
            out[key] += [x for x in c.get(key, []) if x not in out[key]]
    return out


# ---------------------------------------------------------------- Text

def _names(stile=None) -> set:
    return set(stile or STILE) | {NEUTRAL}


def _strip(text: str, stile=None) -> str:
    names = _names(stile)
    text = _MARK.sub(lambda m: " " if m.group(1) in names else m.group(0), text or "")
    return _TAG.sub(" ", text)


def ohne_tags(text: str, stile=None) -> str:
    """Anzeigefassung: ohne Geräusch-Tags und Stilwechsel."""
    return " ".join(_strip(text, stile).split())


def _bare(text: str, stile=None) -> str:
    return re.sub(r"\s+", "", _strip(text, stile))


def bereinigen(text: str | None, original: str, tags: list, max_tags: int, stile=None,
               wortlaut_frei: bool = False) -> str | None:
    """Nur erlaubte Tags (höchstens max_tags Gefühls-Tags) und bekannte Stilwechsel; Wortlaut unverändert (KI) oder frei
    (von Hand, wortlaut_frei). None = gleich dem Original (Originaltext nutzen)."""
    if not text or not str(text).strip():
        return None
    allowed = {t.lower() for t in tags}
    names = _names(stile)
    count = found = 0

    def keep_tag(match):
        nonlocal count, found
        tag = re.sub(r"\s+", " ", match.group(0).lower())
        if tag not in allowed:
            return " "
        if tag not in ATEM_TAGS:
            if count >= max_tags:
                return " "
            count += 1
        found += 1
        return f" {tag} "

    def keep_mark(match):
        nonlocal found
        if match.group(1) not in names:
            return match.group(0)
        found += 1
        return f" [{match.group(1)}] "

    cleaned = _MARK.sub(keep_mark, _TAG.sub(keep_tag, str(text)))
    reworded = _bare(cleaned, stile) != _bare(original, stile)
    if reworded and not wortlaut_frei:
        return None
    cleaned = " ".join(cleaned.split())
    cleaned = re.sub(r"(<[^<>]+>) ([,.;:!?…])", r"\1\2", cleaned)
    cleaned = re.sub(r"(?:\[[a-z-]+\] )+(\[[a-z-]+\])", r"\1", cleaned)  # mehrere Wechsel hintereinander: der letzte gilt
    cleaned = re.sub(r"\s*\[[a-z-]+\]$", "", cleaned)                   # Wechsel ganz am Ende: wirkungslos
    return cleaned if found or reworded else None


def umformuliert(entry_text: str | None, original: str, stile=None) -> bool:
    """Weicht die Sprechfassung im Wortlaut vom Folgentext ab (von Hand umformuliert)?"""
    return bool(entry_text) and _bare(entry_text, stile) != _bare(original, stile)


def teile(text: str, start: str | None, stile=None) -> list:
    """Text an Stilwechseln zerlegen: [(Teiltext mit Tags, Stil oder None)]; gleiche Stile hintereinander zusammen."""
    names = _names(stile)
    parts, current, pos = [], start if start in set(stile or STILE) else None, 0
    for match in _MARK.finditer(text or ""):
        name = match.group(1)
        if name not in names:
            continue
        chunk = text[pos:match.start()].strip()
        if chunk:
            parts.append([chunk, current])
        current = None if name == NEUTRAL else name
        pos = match.end()
    rest = (text or "")[pos:].strip()
    if rest:
        parts.append([rest, current])
    merged: list = []
    for chunk, stil in parts:
        if merged and merged[-1][1] == stil:
            merged[-1][0] += " " + chunk
        else:
            merged.append([chunk, stil])
    return [(c, s) for c, s in merged]


def atmen(text: str, stufe: str, tags: list, stil: str | None = None) -> str:
    """Atmer einsetzen: vor einem Satz, wenn seit dem letzten Atmer (oder Tag, oder Absatzbeginn) genug gesprochen wurde,
    und vor sehr langen Sätzen; bei „lebendig“ auch zu Beginn langer Absätze. Nie direkt neben einem anderen Tag."""
    rule = ATEM.get(stufe)
    allowed = {t.lower() for t in tags}
    if not rule or "<breath>" not in allowed or not (text or "").strip():
        return text
    breath = "<heavy breath>" if stil in ("frightened", "excited") and "<heavy breath>" in allowed else "<breath>"
    sentences = _SENTENCE.split(" ".join(text.split()))
    total = len(ohne_tags(text))
    out, since = [], 0
    for index, sentence in enumerate(sentences):
        plain = len(ohne_tags(sentence))
        body = _MARK.sub("", sentence).lstrip()
        near_tag = body.startswith("<") or (out and out[-1].endswith(">"))
        if index == 0:
            due = bool(rule["auftakt"]) and total >= rule["auftakt"]
        else:
            due = since >= rule["zeichen"] or plain >= rule["lang"]
        if due and not near_tag:
            marks = re.match(r"^((?:\[[a-z-]+\]\s*)*)", sentence).group(1)  # Atmer nach einem Stilwechsel
            sentence = f"{marks}{breath} {sentence[len(marks):]}"
            breath = "<breath>"  # schweres Atmen höchstens einmal je Absatz
            since = 0
        if _TAG.search(sentence):  # jeder Tag ist eine Atempause: ab dem letzten Tag neu zählen
            since = len(ohne_tags(_TAG.split(sentence)[-1]))
        else:
            since += plain
        out.append(sentence)
    return " ".join(out)


def schuetzen(text: str) -> str:
    """Tags vor Lexikon und Zerlegen in Platzhalter ohne Leerzeichen packen."""
    return _TAG.sub(lambda m: "" + m.group(0).encode("utf-8").hex() + "", text)


def zurueck(text: str) -> str:
    return _PROTECTED.sub(lambda m: bytes.fromhex(m.group(1)).decode("utf-8", "replace"), text)


# ---------------------------------------------------------------- Speichern

def _key(episode_id: int) -> str:
    return f"tts.regie.{int(episode_id)}"


def text_hash(segments: list) -> str:
    return hashlib.sha1(json.dumps([[s["sprecher"], s["text"]] for s in segments], ensure_ascii=False)
                        .encode("utf-8")).hexdigest()


def lesen(conn: sqlite3.Connection, episode_id: int) -> dict | None:
    row = conn.execute("SELECT value FROM world_meta WHERE key = ?", (_key(episode_id),)).fetchone()
    try:
        data = json.loads(row[0]) if row and row[0] else None
    except ValueError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get("segmente"), list) else None


def gueltig(conn: sqlite3.Connection, episode_id: int, segments: list | None = None) -> dict | None:
    """Regie, die zum aktuellen Folgentext passt (sonst None)."""
    data = lesen(conn, episode_id)
    if data is None:
        return None
    segments = segments if segments is not None else episodes.get_episode(conn, episode_id)["segmente"]
    if data.get("hash") != text_hash(segments) or len(data["segmente"]) != len(segments):
        return None
    return data


def _speichern(conn: sqlite3.Connection, episode_id: int, data: dict) -> dict:
    old = conn.execute("SELECT value FROM world_meta WHERE key = ?", (_key(episode_id),)).fetchone()
    if old and old[0]:
        service.set_meta(conn, _key(episode_id) + ".vorher", old[0])  # nichts löschen: letzte Fassung aufheben
    service.set_meta(conn, _key(episode_id), json.dumps(data, ensure_ascii=False))
    conn.commit()
    return data


def _hand_tempo(data: dict | None) -> bool:
    """Ab Version 2 stammt ein Tempo immer von Hand; ältere Fassungen hatten KI-Tempi (werden ignoriert)."""
    return bool(data) and int(data.get("version") or 1) >= 2


def _neutral(segments: list) -> dict:
    return {"version": VERSION, "hash": text_hash(segments), "stufe": None, "modell": "", "fehler": 0,
            "erstellt": time.strftime("%Y-%m-%d %H:%M"), "bearbeitet": False,
            "segmente": [{"stil": None, "text": None} for _ in segments]}


# ---------------------------------------------------------------- KI

SYSTEM = """Du bist Regisseur:in eines deutschen Hörspiels. Eine Sprachsynthese liest die Absätze vor. Für jeden Absatz
legst du fest, WIE er gesprochen wird – du schreibst nichts um.

Menschen ändern ihre Sprechweise mit dem Inhalt: Begrüßung und Persönliches klingen warm, Zahlen, Daten, Messwerte und
technische Erklärungen sachlich-dokumentarisch, danach geht es zurück ins Persönliche. Genau das bildest du ab.

Pro Absatz:
- "stil": Stil, mit dem der Absatz beginnt – einer aus STILE oder null (neutral). Erzähler:in meist null, "calm",
  "serious", "documentary" oder bei Spannung "dramatic"; Figuren nach Gefühl der Szene (Angst → "frightened",
  Trauer → "sad", Freude → "cheerful"/"excited", Zärtlichkeit → "tender", Ironie → "wry", Heimlichkeit → "whispering").
- "text": NUR wenn du etwas einfügst – dann exakt derselbe Wortlaut, Zeichen für Zeichen, mit
  • Stilwechseln [stil] direkt vor dem Satz, ab dem sich die Sprechweise ändert (z. B. "[documentary]" vor Zahlen
    oder einer Erklärung, "[warm]" zurück; "[neutral]" = ohne Stil). Nur Stile aus STILE oder neutral.
  • Geräusch-Tags aus TAGS an passenden Stellen (<sigh> vor einem resignierten Satz, <laugh> nach einem Witz,
    <short pause> vor einer Pointe).
  Kein Wort ändern, ergänzen, kürzen oder umstellen. Ohne Einfügungen: "text" weglassen.
- KEIN Tempo – der Stil bringt sein Tempo mit.
- Erzähler:in bekommt höchstens <short pause> oder <long pause>; Lachen, Seufzen, Schluchzen usw. nur in
  Figurenrede, und nur, wo die Szene es trägt (steht im Text „seufzte“, darf die Figur seufzen).
- Normales Atmen (<breath>) setzt das Programm selbst regelmäßig ein – du nicht. Setze Atem-Tags nur, wo die Szene
  hörbares Atmen verlangt: <heavy breath> nach Rennen oder bei Angst, <exhales> bei Erleichterung oder Erschöpfung.
STUFE "dezent": sparsam – Stilwechsel nur bei deutlichem Inhaltswechsel, höchstens ein Geräusch je Absatz, selten.
STUFE "lebendig": ausdrucksstark, aber nie übertrieben – höchstens drei Geräusche je Absatz.

Antworte AUSSCHLIESSLICH mit JSON:
{"absaetze": [{"nr": 1, "stil": null}, {"nr": 2, "stil": "warm", "text": "Hallo, schön dich zu sehen. [documentary] Die Station hat 42 Decks. [warm] <laugh> Du wirst dich verlaufen."}]}
Jeder Absatz der Anfrage kommt genau einmal vor (gleiche "nr")."""


def _batches(segments: list) -> list:
    out, current, size = [], [], 0
    for index, seg in enumerate(segments):
        if current and (len(current) >= BATCH_SEGMENTS or size + len(seg["text"]) > BATCH_CHARS):
            out.append(current)
            current, size = [], 0
        current.append(index)
        size += len(seg["text"])
    if current:
        out.append(current)
    return out


def _messages(ep: dict, indices: list, stufe: str, caps: dict) -> list:
    segments = ep["segmente"]
    before = segments[max(0, indices[0] - 2):indices[0]]
    request = {
        "folge": ep.get("title") or "", "stufe": stufe, "STILE": caps["stile"], "TAGS": caps["tags"],
        "davor": [f"[{s['sprecher']}] {s['text'][:300]}" for s in before],
        "absaetze": [{"nr": i + 1, "sprecher": segments[i]["sprecher"],
                      "art": "erzaehler" if segments[i]["typ"] == "narrator" else "figur", "text": segments[i]["text"]}
                     for i in indices],
    }
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False, indent=1)}]


def _uebernehmen(payload: dict, ep: dict, indices: list, stufe: str, caps: dict, out: list) -> int:
    items = payload.get("absaetze") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise RegieError("Antwort ohne „absaetze“.")
    wanted = set(indices)
    taken = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("nr")) - 1
        except (TypeError, ValueError):
            continue
        if index not in wanted:
            continue
        stil = item.get("stil") if item.get("stil") in caps["stile"] else None
        text = bereinigen(item.get("text"), ep["segmente"][index]["text"], caps["tags"], MAX_TAGS.get(stufe, 1),
                          caps["stile"])
        out[index].update(stil=stil, text=text)
        taken += 1
    return taken


def erzeugen(conn: sqlite3.Connection, episode_id: int, stufe: str = STANDARD_STUFE, caps: dict | None = None,
             job_id: int | None = None, complete=None) -> dict:
    """Regie für die ganze Folge von der KI holen (Aufgabe „regie“), prüfen, Atmer setzen und speichern.
    complete(messages, aufgabe, run) → (payload, modell) ist für Tests austauschbar."""
    if stufe not in STUFEN or stufe == "aus":
        raise RegieError("Regie ist für diese Folge ausgeschaltet.")
    if complete is None:
        from .llm import complete
    caps = caps or _caps_default()
    ep = episodes.get_episode(conn, episode_id)
    segments = ep["segmente"]
    if not segments:
        raise RegieError("Die Folge enthält keinen Text.")
    out = [{"stil": None, "text": None} for _ in segments]
    previous = gueltig(conn, episode_id, segments)
    for entry, old in zip(out, (previous or {}).get("segmente") or []):  # Takes und eigene Tempi bleiben erhalten
        if old.get("take"):
            entry["take"] = old["take"]
        if old.get("tempo") and _hand_tempo(previous):
            entry["tempo"] = old["tempo"]
    batches = _batches(segments)
    conn.commit()  # Protokoll schreibt über eine eigene Verbindung
    run = runs.Run(conn, "Hörspiel-Regie", f"Folge {ep['release_nr']}: {ep['title'] or ''}", "regie",
                   f"Sprechstil, Stilwechsel und Geräusche für {len(segments)} Absätze festlegen (Stufe {stufe}, "
                   f"{len(batches)} Abschnitt{'e' if len(batches) != 1 else ''})", job_id=job_id)
    used, errors = set(), []
    try:
        for number, indices in enumerate(batches, 1):
            run.step(f"Abschnitt {number}/{len(batches)}: Absätze {indices[0] + 1}–{indices[-1] + 1}",
                     5 + int(85 * (number - 1) / len(batches)))
            try:
                payload, model = complete(_messages(ep, indices, stufe, caps), "regie", run)
                taken = _uebernehmen(payload, ep, indices, stufe, caps, out)
                used.add(model)
                run.step(f"Abschnitt {number}: {taken}/{len(indices)} Absätze übernommen", None,
                         "ok" if taken else "warnung")
            except Exception as exc:  # ein Abschnitt darf scheitern – er bleibt neutral
                errors.append(str(exc)[:300])
                run.step(f"Abschnitt {number} bleibt neutral: {exc}", None, "fehler")
        if len(errors) == len(batches):
            raise RegieError("Regie fehlgeschlagen: " + errors[-1])
        breaths = 0
        for index, entry in enumerate(out):  # Atmen setzt der Code – unabhängig von der KI
            base = entry["text"] or segments[index]["text"]
            spoken = atmen(base, stufe, caps["tags"], entry["stil"])
            breaths += sum(spoken.count(t) - base.count(t) for t in ("<breath>", "<heavy breath>"))
            entry["text"] = spoken if entry["text"] or spoken != base else None
        run.step(f"Atmen: {breaths} Atmer eingesetzt", 95)
        data = {"version": VERSION, "hash": text_hash(segments), "stufe": stufe, "bearbeitet": False,
                "modell": ", ".join(sorted(used)), "erstellt": time.strftime("%Y-%m-%d %H:%M"),
                "fehler": len(errors), "segmente": out}
        _speichern(conn, episode_id, data)
        summary = _zaehlen(out, caps["stile"])
        run.step(f"Regie gespeichert: {summary['stile']} Absätze mit Stil, {summary['wechsel']} Stilwechsel, "
                 f"{summary['geraeusche']} Geräusche", 100, "ok")
        run.finish("fertig")
        return data
    except Exception as exc:
        run.step(f"Abgebrochen: {exc}", None, "fehler")
        run.finish("fehler", error=str(exc)[:1000])
        raise


def sicherstellen(conn: sqlite3.Connection, episode_id: int, stufe: str, caps: dict, job_id: int | None = None,
                  log=None, complete=None) -> dict | None:
    """Beim Vertonen: passende Regie nutzen oder neu erstellen. Fehler → None (dann neutral vertonen)."""
    log = log or (lambda *a, **k: None)
    if stufe == "aus" or not caps:
        return None
    data = gueltig(conn, episode_id)
    if data and (data.get("bearbeitet") or data.get("stufe") in (stufe, None)):  # None: nur Takes, keine KI-Regie
        return data
    try:
        return erzeugen(conn, episode_id, stufe, caps, job_id=job_id, complete=complete)
    except Exception as exc:
        log(f"Regie übersprungen, Folge wird neutral vertont: {exc}")
        return None


# ---------------------------------------------------------------- Von Hand

def setzen(conn: sqlite3.Connection, episode_id: int, changes: list, caps: dict | None = None) -> dict:
    """Regie von Hand ändern: [{nr, stil, text}] (text mit Tags und [stil]-Wechseln; gleich dem Original = keine
    Regie). Fehlt eine Regie, wird eine neutrale angelegt."""
    with _SAVE_LOCK:  # Autospeichern: mehrere Zellen kurz nacheinander dürfen sich nicht überschreiben
        return _setzen(conn, episode_id, changes, caps)


def _setzen(conn: sqlite3.Connection, episode_id: int, changes: list, caps: dict | None) -> dict:
    caps = caps or _caps_default()
    segments = episodes.get_episode(conn, episode_id)["segmente"]
    data = gueltig(conn, episode_id, segments) or _neutral(segments)
    if not _hand_tempo(data):  # alte KI-Tempi verwerfen
        for entry in data["segmente"]:
            entry.pop("tempo", None)
        data["version"] = VERSION
    for change in changes or []:
        try:
            index = int(change.get("nr")) - 1
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Absatznummer fehlt.")
        if not 0 <= index < len(segments):
            raise ValueError(f"Absatz {index + 1} gibt es nicht.")
        entry = data["segmente"][index]
        if "tempo" in change:
            tempo = change["tempo"] or None
            if tempo and tempo not in caps["tempi"]:
                raise ValueError(f"Unbekanntes Tempo „{tempo}“.")
            entry["tempo"] = tempo
        if "stil" in change:
            stil = change["stil"] or None
            if stil and stil not in caps["stile"]:
                raise ValueError(f"Unbekannter Stil „{stil}“.")
            entry["stil"] = stil
        if "text" in change:
            text = (change["text"] or "").strip()
            original = segments[index]["text"]
            unknown = sorted({t for t in _TAG.findall(text) if t.lower() not in {x.lower() for x in caps["tags"]}})
            if unknown:
                raise ValueError(f"Absatz {index + 1}: unbekannte Geräusche {' '.join(unknown)}.")
            names = _names(caps["stile"])
            marks = sorted({m for m in re.findall(r"\[([^\[\]\s]{2,25})\]", text)
                            if m not in names and f"[{m}]" not in original})
            if marks:
                raise ValueError(f"Absatz {index + 1}: unbekannter Stilwechsel {' '.join(f'[{m}]' for m in marks)}.")
            entry["text"] = bereinigen(text, original, caps["tags"], MAX_TAGS["hand"], caps["stile"], wortlaut_frei=True)
    data["bearbeitet"] = True
    data["stufe"] = data.get("stufe") or "hand"
    data["bearbeitet_am"] = time.strftime("%Y-%m-%d %H:%M")
    return _speichern(conn, episode_id, data)


def _take_entry(conn: sqlite3.Connection, episode_id: int, nr: int) -> tuple:
    segments = episodes.get_episode(conn, episode_id)["segmente"]
    if not 1 <= int(nr) <= len(segments):
        raise ValueError(f"Absatz {nr} gibt es nicht.")
    data = gueltig(conn, episode_id, segments) or _neutral(segments)
    entry = data["segmente"][int(nr) - 1]
    entry.setdefault("takes", sorted({0, int(entry.get("take") or 0)}))
    return data, entry


def take_neu(conn: sqlite3.Connection, episode_id: int, nr: int) -> int:
    """Neuen Take (Seed) für einen Absatz anlegen und wählen. Liefert den Seed."""
    with _SAVE_LOCK:
        data, entry = _take_entry(conn, episode_id, nr)
        seed = max(entry["takes"]) + 1
        entry["takes"].append(seed)
        entry["take"] = seed
        _speichern(conn, episode_id, data)
        return seed


def take_waehlen(conn: sqlite3.Connection, episode_id: int, nr: int, seed: int) -> None:
    """Einen vorhandenen Take für das Zusammenfügen wählen."""
    with _SAVE_LOCK:
        data, entry = _take_entry(conn, episode_id, nr)
        if int(seed) not in entry["takes"]:
            raise ValueError(f"Absatz {nr}: Take {int(seed) + 1} gibt es nicht.")
        entry["take"] = int(seed)
        _speichern(conn, episode_id, data)


def takes(data: dict | None, index: int) -> tuple:
    """(gewählter Seed, alle Seeds) eines Absatzes."""
    entry = (data["segmente"][index] if data and index < len(data.get("segmente") or []) else None) or {}
    chosen = int(entry.get("take") or 0)
    return chosen, sorted(set(entry.get("takes") or []) | {0, chosen})


# ---------------------------------------------------------------- Vertonung und Export

def teile_fuer_segment(data: dict | None, index: int, server: dict, original: str, nur_take: bool = False,
                       take: int | None = None) -> list:
    """[(Sprechtext, Zusatzfelder)] für einen Absatz – nur, was dieser Server kann. Stilwechsel ergeben mehrere Teile.
    nur_take: Regie ist aus, aber der gewählte Take gilt trotzdem (nur Seed). take: anderen als den gewählten Take."""
    caps = faehig(server)
    entry = (data["segmente"][index] if data and index < len(data.get("segmente") or []) else None) or {}
    if not caps:
        return [(original, {})]
    take = int(entry.get("take") or 0) if take is None else int(take)
    seed = {"seed": take} if take else {}
    if nur_take or not data:
        return [(original, dict(seed))]
    tempo = entry.get("tempo") if _hand_tempo(data) and entry.get("tempo") in caps["tempi"] else None
    if tempo:
        seed["pace"] = tempo  # von Hand gesetzt – gilt für alle Teile des Absatzes
    allowed = {t.lower() for t in caps["tags"]}
    text = entry.get("text") or original
    out = []
    for chunk, stil in teile(text, entry.get("stil"), caps["stile"]):
        chunk = " ".join(_TAG.sub(lambda m: m.group(0) if m.group(0).lower() in allowed else " ", chunk).split())
        if not chunk:
            continue
        extra = {"style": stil} if stil in caps["stile"] else {}
        out.append((chunk, {**extra, **seed}))
    return out or [(original, dict(seed))]


def sprechfassung(parts: list, original: str | None = None) -> dict:
    """Für JSON: Text mit Geräusch-Tags (ohne Stilwechsel-Marken), Anfangsstil und – bei Wechseln – die Teile.
    Von Hand umformuliert: zusätzlich „originaltext“ (der lesbare Folgentext)."""
    out = {"text": " ".join(p[0] for p in parts), "stil": parts[0][1].get("style") if parts else None}
    if original is not None and _bare(out["text"]) != _bare(original):
        out["originaltext"] = original
    if parts and parts[0][1].get("pace"):
        out["tempo"] = parts[0][1]["pace"]
    if len(parts) > 1:
        out["teile"] = [{"text": t, "stil": e.get("style")} for t, e in parts]
    return out


def _zaehlen(entries: list, stile=None) -> dict:
    texts = [e.get("text") or "" for e in entries]
    names = _names(stile)
    return {"stile": sum(1 for e in entries if e.get("stil")),
            "wechsel": sum(sum(1 for m in _MARK.findall(t) if m in names) for t in texts),
            "geraeusche": sum(len(_TAG.findall(t)) for t in texts),
            "atmer": sum(sum(1 for t in _TAG.findall(x) if t in ATEM_TAGS) for x in texts),
            "takes": sum(1 for e in entries if e.get("take"))}


def ansicht(conn: sqlite3.Connection, episode_id: int, caps: dict | None) -> dict:
    """Für die Oberfläche: je Absatz Original, Anfangsstil, Sprechtext (immer gefüllt), Take."""
    ep = episodes.get_episode(conn, episode_id)
    data = gueltig(conn, episode_id, ep["segmente"])
    stored = lesen(conn, episode_id)
    caps = caps or _caps_default()
    rows = []
    for index, seg in enumerate(ep["segmente"]):
        entry = (data["segmente"][index] if data else None) or {}
        rows.append({"nr": index + 1, "sprecher": seg["sprecher"], "typ": seg["typ"], "text": seg["text"],
                     "stil": entry.get("stil"), "tempo": entry.get("tempo") if _hand_tempo(data) else None,
                     "sprechtext": entry.get("text") or seg["text"],
                     "umformuliert": umformuliert(entry.get("text"), seg["text"], caps and caps.get("stile")),
                     "take": takes(data, index)[0], "takes": takes(data, index)[1]})
    return {"segmente": rows, "stile": caps["stile"], "tempi": caps.get("tempi") or TEMPI, "tags": caps["tags"],
            "vorhanden": bool(data), "veraltet": bool(stored and not data),
            **({k: data.get(k) for k in ("stufe", "modell", "erstellt", "bearbeitet", "bearbeitet_am", "fehler")}
               if data else {})}


def zusammenfassung(conn: sqlite3.Connection, episode_id: int) -> dict:
    data = gueltig(conn, episode_id)
    stored = lesen(conn, episode_id)
    if not data:
        return {"vorhanden": False, "veraltet": bool(stored)}
    return {"vorhanden": True, "stufe": data.get("stufe"), "modell": data.get("modell"), "erstellt": data.get("erstellt"),
            "bearbeitet": bool(data.get("bearbeitet")), **_zaehlen(data["segmente"])}
