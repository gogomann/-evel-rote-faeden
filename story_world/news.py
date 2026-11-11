"""Nachrichtenquellen (RSS/Atom): Meldungen abrufen und als Impulse der Art „nachricht“ in die Welt geben.

Nur Python-Standardbibliothek. Doppelte Meldungen werden über ihre ID (guid/link) erkannt.
Quellen werden nicht gelöscht, sondern deaktiviert.
"""

from __future__ import annotations

import html
import re
import sqlite3
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from . import providers, service

MAX_BYTES = 3_000_000
ATOM = "{http://www.w3.org/2005/Atom}"


class NewsError(RuntimeError):
    pass


def _clean(text) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse(data: bytes) -> list:
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise NewsError(f"Kein gültiger Feed: {exc}")
    items = []
    for item in root.iter("item"):  # RSS 2.0
        link = (item.findtext("link") or "").strip()
        items.append({"guid": (item.findtext("guid") or link or item.findtext("title") or "").strip(),
                      "title": _clean(item.findtext("title")), "link": link,
                      "published": (item.findtext("pubDate") or "").strip(),
                      "summary": _clean(item.findtext("description"))[:2000]})
    for entry in root.iter(f"{ATOM}entry"):  # Atom
        link_el = entry.find(f"{ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        items.append({"guid": (entry.findtext(f"{ATOM}id") or link).strip(),
                      "title": _clean(entry.findtext(f"{ATOM}title")), "link": link,
                      "published": (entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published") or "").strip(),
                      "summary": _clean(entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content"))[:2000]})
    return [i for i in items if i["guid"] and i["title"]]


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "StoryWorld/1 (Feed-Leser)"})
    try:
        with urllib.request.urlopen(request, timeout=30, context=providers._ssl_context()) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise NewsError(f"Quelle meldet HTTP {exc.code}")
    except (urllib.error.URLError, OSError) as exc:
        raise NewsError(f"Quelle nicht erreichbar: {getattr(exc, 'reason', exc)}")
    if len(data) > MAX_BYTES:
        raise NewsError("Feed ist zu groß.")
    return data


# ---------------------------------------------------------------- Quellen

def add_source(conn: sqlite3.Connection, name: str, url: str) -> int:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise service.ValidationError("Bitte eine Feed-Adresse mit http:// oder https:// angeben.")
    try:
        cur = conn.execute("INSERT INTO news_sources (name, url) VALUES (?, ?)", ((name or url).strip(), url))
    except sqlite3.IntegrityError:
        raise service.ValidationError("Diese Quelle ist schon eingetragen.")
    service.audit(conn, "nutzer", "nachrichtenquelle", detail=url)
    return cur.lastrowid


def toggle_source(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute("UPDATE news_sources SET active = 1 - active WHERE id = ?", (source_id,))


def sources(conn: sqlite3.Connection) -> list:
    return [dict(r) for r in conn.execute("SELECT * FROM news_sources ORDER BY id")]


def items(conn: sqlite3.Connection, limit: int = 50) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT n.id, n.title, n.link, n.published, n.impulse_id, n.fetched_at, s.name AS quelle FROM news_items n "
        "LEFT JOIN news_sources s ON s.id = n.source_id ORDER BY n.id DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------- Abrufen

def fetch_all(conn: sqlite3.Connection, downloader=_download) -> dict:
    """Ruft alle aktiven Quellen ab. Eine kaputte Quelle stoppt die anderen nicht."""
    report = {"neu": 0, "fehler": []}
    for source in conn.execute("SELECT id, name, url FROM news_sources WHERE active = 1").fetchall():
        try:
            entries = parse(downloader(source["url"]))
            for entry in entries:
                cur = conn.execute("INSERT OR IGNORE INTO news_items (source_id, guid, title, link, published, summary) "
                                   "VALUES (?, ?, ?, ?, ?, ?)", (source["id"], entry["guid"], entry["title"],
                                                                entry["link"], entry["published"], entry["summary"]))
                report["neu"] += cur.rowcount
            conn.execute("UPDATE news_sources SET last_fetch = ?, last_error = NULL WHERE id = ?",
                         (time.strftime("%Y-%m-%d %H:%M"), source["id"]))
        except NewsError as exc:
            conn.execute("UPDATE news_sources SET last_fetch = ?, last_error = ? WHERE id = ?",
                         (time.strftime("%Y-%m-%d %H:%M"), str(exc), source["id"]))
            report["fehler"].append(f"{source['name']}: {exc}")
    conn.commit()
    return report


def to_impulses(conn: sqlite3.Connection, count: int | None = None) -> list:
    """Macht aus den neuesten noch unbenutzten Meldungen Impulse der Art „nachricht“."""
    count = int(service.setting(conn, "nachrichten_pro_tag") if count is None else count)
    rows = conn.execute("SELECT n.id, n.title, n.summary, n.link, s.name AS quelle FROM news_items n "
                        "LEFT JOIN news_sources s ON s.id = n.source_id WHERE n.impulse_id IS NULL "
                        "ORDER BY n.id DESC LIMIT ?", (count,)).fetchall()
    created = []
    for row in rows:
        content = f"{row['summary'] or ''}\n\nQuelle: {row['quelle'] or ''} – {row['link'] or ''}".strip()
        impulse_id = service.create_impulse(conn, row["title"][:200], content, "nachricht")
        conn.execute("UPDATE news_items SET impulse_id = ? WHERE id = ?", (impulse_id, row["id"]))
        created.append(impulse_id)
    conn.commit()
    return created
