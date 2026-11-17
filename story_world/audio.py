"""Hörbuch-Ausgabe: Folgen mit Systemstimmen vertonen.

macOS: `say` (deutsche Stimmen) erzeugt je Absatz eine WAV-Datei, die hier mit kurzen Pausen zusammengefügt und – wenn
`lame`/`ffmpeg` vorhanden ist – als .mp3 mit ID3-Tags (mp3.py), sonst mit `afconvert` als .m4a gespeichert wird. Feste Stimme für den Erzähler, je Figur eine eigene Stimme
(Figur → „Stimme (Hörbuch)“ oder automatisch reihum). Das Aussprache-Lexikon wird vor dem Sprechen angewandt.
Für andere TTS-Systeme gibt es den Export als segmentiertes JSON (export_json).
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import tempfile
import wave
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from . import episodes, mp3, runs, service, worlds

PAUSE_SAME = 0.45      # Sekunden zwischen Absätzen derselben Stimme
PAUSE_CHANGE = 0.3     # Sekunden bei Sprecherwechsel


class AudioError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("say") is not None


def voices() -> list:
    if not available():
        return []
    try:
        out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    result = []
    for line in out.splitlines():
        match = re.match(r"^(.+?)\s+([a-z]{2,3}[_-][A-Za-z0-9]+)\s+#", line)
        if match:
            result.append({"name": match.group(1).strip(), "lang": match.group(2)})
    return result


def german(all_voices: list) -> list:
    return [v["name"] for v in all_voices if v["lang"].lower().startswith("de")]


def lexicon(conn: sqlite3.Connection) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT term, spoken, variants, ignore_case, language, ipa FROM pronunciations ORDER BY length(term) DESC")]


# Platzhalter für SSML-Einträge: übersteht Zerlegen (keine Leer-/Satzzeichen) und XML-Escaping, Inhalt als Hex-JSON
_TOKEN = re.compile("\uE000([0-9a-f]+)\uE001")
_LOCALES = {"en": "en-US", "ja": "ja-JP", "zh": "zh-CN", "sv": "sv-SE", "da": "da-DK", "cs": "cs-CZ", "ko": "ko-KR",
            "el": "el-GR", "uk": "uk-UA", "nb": "nb-NO", "hi": "hi-IN", "ar": "ar-SA", "he": "he-IL", "pt": "pt-PT"}


def _forms(entry: dict) -> list:
    variants = [v.strip() for v in re.split(r"[,;\n]", entry.get("variants") or "")]
    return sorted({f for f in [entry["term"], *variants] if f}, key=len, reverse=True)


def _pattern(entry: dict) -> re.Pattern:
    alternatives = "|".join(re.escape(f) for f in _forms(entry))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE if entry.get("ignore_case") else 0)


def locale(language: str | None) -> str | None:
    """„en“ → „en-US“, „en-gb“ → „en-GB“; Ungültiges → None."""
    lang = (language or "").strip().replace("_", "-")
    if re.fullmatch(r"[A-Za-z]{2,3}", lang):
        lang = lang.lower()
        return _LOCALES.get(lang, f"{lang}-{lang.upper()}")
    match = re.fullmatch(r"([A-Za-z]{2,3})-([A-Za-z]{2,4})", lang)
    return f"{match.group(1).lower()}-{match.group(2).upper()}" if match else None


def apply_lexicon(text: str, entries: list, ssml: bool = False) -> str:
    """Wörter durch ihre Sprechfassung ersetzen. ssml=True: Einträge mit Sprache/IPA werden zu Platzhaltern,
    die to_ssml() nach dem Zerlegen in <lang>/<phoneme> umsetzt."""
    for entry in entries:
        if ssml and (entry.get("ipa") or locale(entry.get("language"))):
            def repl(match, e=entry):
                data = [match.group(0), e["spoken"], e.get("ipa") or "", e.get("language") or ""]
                return "\uE000" + json.dumps(data, ensure_ascii=False).encode("utf-8").hex() + "\uE001"
        else:
            def repl(match, e=entry):
                return e["spoken"]
        text = _pattern(entry).sub(repl, text)
    return text


def _markup(hexdata: str, allow_lang: bool) -> str:
    try:
        original, spoken, ipa, language = json.loads(bytes.fromhex(hexdata).decode("utf-8"))
    except (ValueError, TypeError):
        return ""
    lang = locale(language) if allow_lang else None
    if ipa:
        inner = f"<phoneme alphabet='ipa' ph='{xml_escape(ipa, {chr(39): '&apos;', chr(34): '&quot;'})}'>" \
                f"{xml_escape(original)}</phoneme>"
    elif lang:
        inner = xml_escape(original)
    else:
        return xml_escape(spoken)
    return f"<lang xml:lang='{lang}'>{inner}</lang>" if lang else inner


def to_ssml(text: str, allow_lang: bool = True) -> str:
    """Text XML-escapen und Platzhalter aus apply_lexicon(ssml=True) in SSML umsetzen.
    allow_lang=False: ohne <lang> (Stimme kann keinen Sprachwechsel) – IPA bleibt, sonst die Sprechfassung."""
    out, pos = [], 0
    for match in _TOKEN.finditer(text):
        out.append(xml_escape(text[pos:match.start()]))
        out.append(_markup(match.group(1), allow_lang))
        pos = match.end()
    out.append(xml_escape(text[pos:]))
    return re.sub("[\uE000\uE001]", "", "".join(out))


def has_ssml(text: str) -> bool:
    return bool(_TOKEN.search(text or ""))


def assign_voices(conn: sqlite3.Connection, segments: list, available_voices: list) -> dict:
    """Erzähler: Einstellung oder erste Stimme. Figuren: hinterlegte Stimme, sonst reihum aus den übrigen."""
    narrator = service.setting(conn, "erzaehler_stimme") or (available_voices[0] if available_voices else "")
    if available_voices and narrator not in available_voices:
        narrator = available_voices[0]
    configured = {r[0].lower(): r[1] for r in conn.execute("SELECT name, voice_id FROM characters WHERE voice_id IS NOT NULL")}
    others = [v for v in available_voices if v != narrator] or available_voices
    mapping, turn = {episodes.NARRATOR: narrator}, 0
    for seg in segments:
        speaker = seg["sprecher"]
        if speaker in mapping:
            continue
        if seg["typ"] == "narrator":
            mapping[speaker] = narrator
        elif configured.get(speaker.lower()) in available_voices:
            mapping[speaker] = configured[speaker.lower()]
        else:
            mapping[speaker] = others[turn % len(others)] if others else narrator
            turn += 1
    return mapping


def _say(text: str, voice: str, rate: int, target: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        source = fh.name
    try:
        cmd = ["say", "-r", str(rate), "--data-format=LEI16@22050", "-o", str(target), "-f", source]
        if voice:
            cmd[1:1] = ["-v", voice]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise AudioError(f"say meldet einen Fehler: {result.stderr.strip()[:300]}")
    finally:
        Path(source).unlink(missing_ok=True)


def _concat(parts: list, target: Path) -> None:
    """WAV-Teile (gleiches Format) mit Pausen zu einer Datei verbinden."""
    with wave.open(str(parts[0][0]), "rb") as first:
        params = first.getparams()
    frame_bytes = params.sampwidth * params.nchannels
    with wave.open(str(target), "wb") as out:
        out.setparams(params)
        for path, pause in parts:
            with wave.open(str(path), "rb") as part:
                out.writeframes(part.readframes(part.getnframes()))
            out.writeframes(b"\x00" * int(params.framerate * pause) * frame_bytes)


def output_dir(slug: str) -> Path:
    path = worlds.worlds_dir() / "audio" / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def render(conn: sqlite3.Connection, slug: str, episode_id: int, synth=None, voice_list: list | None = None,
           job_id: int | None = None) -> Path:
    """Vertont eine Folge. synth/voice_list sind für Tests austauschbar."""
    if synth is None:
        if not available():
            raise AudioError("Vertonung braucht den macOS-Befehl „say“. Alternativ: Export als JSON für ein anderes TTS.")
        synth = _say
    ep = episodes.get_episode(conn, episode_id)
    segments = ep["segmente"]
    if not segments:
        raise AudioError("Die Folge enthält keinen Text.")
    names = voice_list if voice_list is not None else german(voices())
    mapping = assign_voices(conn, segments, names)
    rate = int(service.setting(conn, "sprechtempo"))
    words = lexicon(conn)
    conn.commit()  # Protokoll schreibt über eine eigene Verbindung
    run = runs.Run(conn, "Hörbuch", f"Folge {ep['release_nr']}: {ep['title'] or ''}", "audio",
                   f"Folge {ep['release_nr']} vertonen – {len(segments)} Absätze, Tempo {rate} Wörter/Minute",
                   job_id=job_id)
    try:
        run.step("Stimmen: " + ", ".join(f"{k} → {v or 'Standard'}" for k, v in mapping.items()), 3)
        with tempfile.TemporaryDirectory() as tmp:
            parts, previous = [], None
            intro = (f"{ep['title'] or ''}." if ep.get("form") == "geschichte"
                     else f"Folge {ep['release_nr']}. {ep['title'] or ''}.")
            items = [{"sprecher": episodes.NARRATOR, "typ": "narrator", "text": intro}] + segments
            for index, seg in enumerate(items):
                path = Path(tmp) / f"{index:05d}.wav"
                synth(apply_lexicon(seg["text"], words), mapping.get(seg["sprecher"], mapping[episodes.NARRATOR]), rate, path)
                parts.append((path, PAUSE_SAME if seg["sprecher"] == previous else PAUSE_CHANGE))
                previous = seg["sprecher"]
                if index % max(1, len(items) // 20) == 0:
                    run.step(f"{index + 1}/{len(items)} Absätze gesprochen", 5 + int(85 * (index + 1) / len(items)))
            safe = re.sub(r"[^A-Za-z0-9ÄÖÜäöüß_-]+", "_", ep["title"] or "Folge").strip("_")
            target = output_dir(slug) / f"Folge_{ep['release_nr']:03d}_{safe}"
            wav = target.with_suffix(".wav")
            _concat(parts, wav)
            run.step("Teile zusammengefügt", 92)
        final = wav
        if mp3.available():
            speakers = [mapping[episodes.NARRATOR]] + [v for k, v in mapping.items() if k != episodes.NARRATOR]
            final = mp3.from_wav(wav, target.with_suffix(".mp3"), mp3.episode_tags(conn, ep, speakers, "hoerspiel"))
            run.step("MP3 mit ID3-Tags gespeichert", 96)
        elif shutil.which("afconvert"):
            m4a = target.with_suffix(".m4a")
            result = subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", str(wav), str(m4a)],
                                    capture_output=True, text=True, timeout=1800)
            if result.returncode == 0 and m4a.exists():
                final = m4a
        if final != wav:
            # WAV nicht löschen, sondern beiseitelegen (Quarantäne statt Löschen)
            quarantine = output_dir(slug) / "_wav"
            quarantine.mkdir(exist_ok=True)
            wav.replace(quarantine / wav.name)
        relative = str(final.relative_to(worlds.worlds_dir()))
        conn.execute("UPDATE episodes SET audio_path = ? WHERE id = ?", (relative, episode_id))
        conn.commit()
        run.step(f"Hörbuch gespeichert: {relative}", 100, "ok")
        run.finish("fertig")
        return final
    except Exception as exc:
        try:
            conn.commit()
        except sqlite3.Error:
            pass
        run.step(f"Abgebrochen: {exc}", None, "fehler")
        run.finish("fehler", error=str(exc)[:1000])
        raise


DEFAULT_LANG = "de-DE"


def export_json(conn: sqlite3.Connection, episode_id: int, voice_list: list | None = None) -> dict:
    """Segmentiertes JSON (HOERBUCH.md) für externe TTS- oder Studio-Produktion.

    Sind eigene TTS-Server eingerichtet (tts.py), kommen Server, Stimmen und Modus aus deren Besetzung.
    Sonst Stimmen wie beim Hörbuch (macOS): hinterlegte Stimme (Einstellung/Figur) hat Vorrang – auch wenn sie keine macOS-Stimme ist
    (z. B. ElevenLabs-ID) –, sonst die automatische Zuordnung. Sprache je Segment aus der Stimme, sonst DEFAULT_LANG.
    voice_list ist für Tests austauschbar (Liste von Namen oder {name, lang}).
    """
    from . import tts
    ep = episodes.get_episode(conn, episode_id)
    if tts.servers():
        # Eigene TTS-Server eingerichtet: Besetzung und Modus (Hörspiel/Hörbuch) aus der TTS-Einrichtung
        p = tts.plan(conn, episode_id)
        first = next((p["sprecher"][s["sprecher"]] for s in p["segmente"] if s["typ"] == "narrator"),
                     next(iter(p["sprecher"].values()), {}))
        return {
            "folge": ep["release_nr"], "titel": ep["title"], "typ": ep["type"], "minuten": ep["minuten"],
            "quelle": "tts-server", "modus": p["modus"], "sprache": first.get("sprache") or DEFAULT_LANG,
            "erzaehler_stimme": first.get("stimme"), "server": p["server"], "sprecher": p["sprecher"],
            "fehlt": p["fehlt"], "segmente": p["segmente"], "aussprache": lexicon(conn),
        }
    segments = ep["segmente"]
    pool = voices() if voice_list is None else [v if isinstance(v, dict) else {"name": v, "lang": ""} for v in voice_list]
    if voice_list is None:
        pool = [v for v in pool if v["lang"].lower().startswith("de")]
    lang_of = {v["name"]: v["lang"].replace("_", "-") for v in pool if v.get("lang")}
    mapping = assign_voices(conn, segments, [v["name"] for v in pool])
    configured = {r[0].lower(): r[1] for r in conn.execute("SELECT name, voice_id FROM characters WHERE voice_id IS NOT NULL AND voice_id != ''")}
    narrator = service.setting(conn, "erzaehler_stimme") or mapping.get(episodes.NARRATOR) or None

    def voice_for(seg: dict):
        if seg["typ"] == "narrator":
            return narrator
        return configured.get(seg["sprecher"].lower()) or mapping.get(seg["sprecher"]) or None

    out = []
    for seg in segments:
        voice = voice_for(seg)
        out.append(dict(seg, stimme=voice, sprache=lang_of.get(voice, DEFAULT_LANG)))
    sprecher = {}
    for seg in out:
        sprecher.setdefault(seg["sprecher"], {"stimme": seg["stimme"], "sprache": seg["sprache"]})
    return {
        "folge": ep["release_nr"], "titel": ep["title"], "typ": ep["type"], "minuten": ep["minuten"],
        "quelle": "macos", "modus": "hoerspiel", "sprache": lang_of.get(narrator, DEFAULT_LANG),
        "sprechtempo": int(service.setting(conn, "sprechtempo") or 150),
        "erzaehler_stimme": narrator,
        "sprecher": sprecher,
        "segmente": out,
        "aussprache": lexicon(conn),
    }


def audio_file(conn: sqlite3.Connection, episode_id: int) -> Path:
    row = conn.execute("SELECT audio_path FROM episodes WHERE id = ?", (episode_id,)).fetchone()
    if not row or not row[0]:
        raise LookupError("Für diese Folge gibt es noch kein Hörbuch.")
    path = (worlds.worlds_dir() / row[0]).resolve()
    if worlds.worlds_dir().resolve() not in path.parents or not path.exists():
        raise LookupError("Hörbuch-Datei nicht gefunden.")
    return path
