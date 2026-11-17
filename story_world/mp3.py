"""MP3-Export mit ID3-Tags für Vertonungen (macOS-Vertonung in audio.py, TTS-Server in tts.py).

Kodiert wird mit `lame` oder `ffmpeg` (das erste, das gefunden wird). Die ID3v2.3-Tags schreibt dieses Modul selbst
(nur Python-Standardbibliothek), damit sie unabhängig vom Encoder immer gleich aussehen. Ohne Encoder bleibt es beim
bisherigen Format (WAV bzw. M4A). Vorhandene MP3s werden nicht überschrieben, sondern nach _alt verschoben.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import struct
import subprocess
import time
import wave
from pathlib import Path

BITRATE = 128  # kbit/s
APP = "Evel • Rote Fäden"
_EXTRA_PATHS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")  # .command-Start hat oft kein Homebrew im PATH


class MP3Error(RuntimeError):
    pass


def encoder() -> tuple | None:
    """(Art, Pfad) des ersten verfügbaren Encoders oder None."""
    search = os.pathsep.join([os.environ.get("PATH", ""), *_EXTRA_PATHS])
    for name in ("lame", "ffmpeg"):
        found = shutil.which(name, path=search)
        if found:
            return name, found
    return None


def available() -> bool:
    return encoder() is not None


# ---------------------------------------------------------------- ID3v2.3

def _syncsafe(n: int) -> bytes:
    return bytes(((n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F))


def _utf16(text: str) -> bytes:
    return "﻿".encode("utf-16-le") + text.encode("utf-16-le")


def _frame(fid: str, data: bytes) -> bytes:
    return fid.encode("ascii") + struct.pack(">I", len(data)) + b"\x00\x00" + data


def _text_frame(fid: str, text: str) -> bytes:
    return _frame(fid, b"\x01" + _utf16(text) + b"\x00\x00")


TEXT_FRAMES = {
    "titel": "TIT2", "interpret": "TPE1", "album_interpret": "TPE2", "album": "TALB", "track": "TRCK",
    "jahr": "TYER", "genre": "TCON", "gruppe": "TIT1", "komponist": "TCOM", "sprache": "TLAN",
    "encoder": "TSSE", "laenge_ms": "TLEN", "copyright": "TCOP",
}


def id3v23(tags: dict, cover: bytes | None = None, cover_mime: str = "image/png", padding: int = 512) -> bytes:
    """ID3v2.3-Kopf aus tags (Schlüssel siehe TEXT_FRAMES, dazu „kommentar“). Leere Werte werden ausgelassen."""
    frames = b""
    for key, fid in TEXT_FRAMES.items():
        value = tags.get(key)
        if value not in (None, ""):
            frames += _text_frame(fid, str(value))
    if tags.get("kommentar"):
        frames += _frame("COMM", b"\x01" + b"deu" + _utf16("") + b"\x00\x00" + _utf16(str(tags["kommentar"])))
    if cover:
        frames += _frame("APIC", b"\x00" + cover_mime.encode("ascii") + b"\x00" + b"\x03" + b"\x00" + cover)
    body = frames + b"\x00" * padding
    return b"ID3\x03\x00\x00" + _syncsafe(len(body)) + body


def strip_tags(data: bytes) -> bytes:
    """Vorhandene ID3v2- (vorn) und ID3v1-Tags (hinten) entfernen."""
    while data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
        data = data[10 + size + (10 if data[5] & 0x10 else 0):]
    if len(data) >= 128 and data[-128:-125] == b"TAG":
        data = data[:-128]
    return data


def read_tags(path: Path) -> dict:
    """Textframes eines ID3v2.3-Kopfs lesen (für Tests und Kontrolle): {Frame-ID: Text}."""
    data = Path(path).read_bytes()
    if data[:3] != b"ID3":
        return {}
    size = (data[6] << 21) | (data[7] << 14) | (data[8] << 7) | data[9]
    pos, end, out = 10, 10 + size, {}
    while pos + 10 <= end and data[pos:pos + 4].strip(b"\x00"):
        fid = data[pos:pos + 4].decode("ascii")
        length = struct.unpack(">I", data[pos + 4:pos + 8])[0]
        body = data[pos + 10:pos + 10 + length]
        if fid.startswith("T") and body[:1] == b"\x01":
            out[fid] = body[1:].decode("utf-16").rstrip("\x00")
        elif fid == "COMM" and body[:1] == b"\x01":
            rest = body[4:].decode("utf-16-le", "replace")
            out[fid] = rest.split("\x00", 1)[-1].lstrip("﻿").rstrip("\x00")
        else:
            out[fid] = body
        pos += 10 + length
    return out


# ---------------------------------------------------------------- Kodieren

def _set_aside(path: Path) -> None:
    if path.exists():
        old = path.parent / "_alt"
        old.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(path.stat().st_mtime))
        path.replace(old / f"{path.stem}_{stamp}{path.suffix}")


def wav_length_ms(wav: Path) -> int:
    with wave.open(str(wav), "rb") as w:
        return int(1000 * w.getnframes() / (w.getframerate() or 1))


def from_wav(wav: Path, target: Path, tags: dict, cover: bytes | None = None, bitrate: int = BITRATE) -> Path:
    """WAV → MP3 mit ID3-Tags. Eine vorhandene Zieldatei wird nach _alt verschoben."""
    found = encoder()
    if found is None:
        raise MP3Error("Für MP3 wird „lame“ oder „ffmpeg“ gebraucht (z. B. brew install lame).")
    kind, exe = found
    raw = target.with_suffix(".roh.mp3")
    if kind == "lame":
        cmd = [exe, "--silent", "-b", str(bitrate), str(wav), str(raw)]
    else:
        cmd = [exe, "-nostdin", "-loglevel", "error", "-y", "-i", str(wav), "-map_metadata", "-1",
               "-codec:a", "libmp3lame", "-b:a", f"{bitrate}k", "-id3v2_version", "0", "-write_id3v1", "0", str(raw)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0 or not raw.exists():
            raise MP3Error(f"{kind} meldet einen Fehler: {(result.stderr or '').strip()[:300]}")
        tags = dict(tags)
        tags.setdefault("laenge_ms", wav_length_ms(wav))
        partial = target.with_suffix(".teil.mp3")
        partial.write_bytes(id3v23(tags, cover) + strip_tags(raw.read_bytes()))
    finally:
        raw.unlink(missing_ok=True)  # nur das untagte Zwischenergebnis dieses Laufs
    _set_aside(target)
    partial.replace(target)
    return target


# ---------------------------------------------------------------- Tags einer Folge

def episode_tags(conn: sqlite3.Connection, ep: dict, speakers=(), mode: str = "hoerspiel") -> dict:
    """Tags aus Folge und Welt: Titel, Album = Welt (– Strang), Track = Folgennummer, Interpret = Stimmen."""
    from . import __version__
    row = conn.execute("SELECT value FROM world_meta WHERE key = 'name'").fetchone()
    world = (row[0] if row else "") or ""
    title = ep.get("title") or ""
    if ep.get("form") != "geschichte":
        title = f"Folge {ep['release_nr']}: {title}".rstrip(": ")
    strang = ep.get("strang") or ""
    names = []
    for name in speakers:
        if name and name not in names:
            names.append(str(name))
    return {
        "titel": title,
        "album": f"{world} – {strang}" if world and strang else (world or strang or APP),
        "album_interpret": world or APP,
        "interpret": ", ".join(names) or APP,
        "komponist": APP,
        "track": ep.get("release_nr") or "",
        "jahr": time.strftime("%Y"),
        "genre": "Hörbuch" if mode == "hoerbuch" else "Hörspiel",
        "gruppe": ep.get("genre") or "",
        "sprache": "deu",
        "kommentar": ep.get("summary") or "",
        "encoder": f"{APP} {__version__}",
    }
