"""Projektstatus live aus den Markdown-Checklisten lesen."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = (
    ("Umsetzungsplan", "PLAN.md"),
)
EXPECTED_DOCS = ("README.md", "WELT_REGELN.md", "ERZAEHLREGELN.md", "ZEIT_UND_STRAENGE.md", "PIPELINE.md",
                 "DATENMODELL.md", "HOERBUCH.md", "OFFENE_PUNKTE.md")
ITEM = re.compile(r"^\s*[-*]\s+\[( |x|X)\]\s+(.*)$")
HEADING = re.compile(r"^(#{2,4})\s+(.*)$")


def _clean(text: str) -> str:
    return re.sub(r"\*\*|`", "", text).strip()


def parse(text: str) -> list:
    sections, current = [], None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            current = {"titel": _clean(heading.group(2)), "items": []}
            sections.append(current)
            continue
        item = ITEM.match(line)
        if item:
            if current is None:
                current = {"titel": "Allgemein", "items": []}
                sections.append(current)
            body = item.group(2)
            state = "erledigt" if item.group(1).lower() == "x" else ("teilweise" if "Teilweise" in body else "offen")
            current["items"].append({"text": _clean(body), "status": state})
    return [s for s in sections if s["items"]]


def project_status(root: Path = ROOT) -> dict:
    out = []
    for label, rel in SOURCES:
        path = root / rel
        if not path.exists():
            continue
        sections = parse(path.read_text(encoding="utf-8"))
        items = [i for s in sections for i in s["items"]]
        out.append({
            "quelle": label, "datei": rel, "abschnitte": sections,
            "erledigt": sum(1 for i in items if i["status"] == "erledigt"),
            "teilweise": sum(1 for i in items if i["status"] == "teilweise"),
            "gesamt": len(items),
        })
    missing = [name for name in EXPECTED_DOCS if not (root / name).exists()]
    return {"quellen": out, "fehlende_dateien": missing}
