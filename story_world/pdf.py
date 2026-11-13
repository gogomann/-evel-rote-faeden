"""Schlichter PDF-Export für Folgen – nur Python-Standardbibliothek.

Nutzt die PDF-Standardschriften (Times, Helvetica) mit WinAnsi-Kodierung; damit sind deutsche Umlaute, „Anführungen“,
Gedanken- und Auslassungsstriche abgedeckt, ohne Schriften einzubetten. Seiten A4, Blocksatz, Seitenzahlen.
"""

from __future__ import annotations

import time
import zlib

# Zeichenbreiten in 1/1000 em je WinAnsi-Code (0–255), aus den Adobe-Standardmetriken
_WIDTHS = {
    "Times-Roman": (
    761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761,
    761, 761, 761, 761, 761, 761, 761, 761, 761, 250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333,
    250, 278, 500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 278, 278, 564, 564, 564, 444, 921, 722, 667, 667, 722,
    611, 556, 722, 722, 333, 389, 722, 611, 889, 722, 722, 556, 722, 667, 556, 611, 722, 722, 944, 722, 722, 611, 333,
    278, 333, 469, 500, 333, 444, 500, 444, 500, 444, 333, 500, 500, 278, 278, 500, 278, 778, 500, 500, 500, 500, 333,
    389, 278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541, 761, 500, 0, 333, 500, 444, 1000, 500, 500, 333, 1000,
    556, 333, 889, 0, 611, 0, 0, 333, 333, 444, 444, 350, 500, 1000, 333, 980, 389, 333, 722, 0, 444, 722, 250, 333,
    500, 500, 500, 500, 200, 500, 333, 760, 276, 500, 564, 333, 760, 333, 400, 564, 300, 300, 333, 500, 453, 250, 333,
    300, 310, 500, 750, 750, 750, 444, 722, 722, 722, 722, 722, 722, 889, 667, 611, 611, 611, 611, 333, 333, 333, 333,
    722, 722, 722, 722, 722, 722, 722, 564, 722, 722, 722, 722, 722, 722, 556, 500, 444, 444, 444, 444, 444, 444, 667,
    444, 444, 444, 444, 444, 278, 278, 278, 278, 500, 500, 500, 500, 500, 500, 500, 564, 500, 500, 500, 500, 500, 500,
    500, 500,
),
    "Times-Bold": (
    761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761,
    761, 761, 761, 761, 761, 761, 761, 761, 761, 250, 333, 555, 500, 500, 1000, 833, 278, 333, 333, 500, 570, 250, 333,
    250, 278, 500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 333, 333, 570, 570, 570, 500, 930, 722, 667, 722, 722,
    667, 611, 778, 778, 389, 500, 778, 667, 944, 722, 778, 611, 778, 722, 556, 667, 722, 722, 1000, 722, 722, 667, 333,
    278, 333, 581, 500, 333, 500, 556, 444, 556, 444, 333, 500, 556, 278, 333, 556, 278, 833, 556, 500, 556, 556, 444,
    389, 333, 556, 500, 722, 500, 500, 444, 394, 220, 394, 520, 761, 500, 0, 333, 500, 500, 1000, 500, 500, 333, 1000,
    556, 333, 1000, 0, 667, 0, 0, 333, 333, 500, 500, 350, 500, 1000, 333, 1000, 389, 333, 722, 0, 444, 722, 250, 333,
    500, 500, 500, 500, 220, 500, 333, 747, 300, 500, 570, 333, 747, 333, 400, 570, 300, 300, 333, 556, 540, 250, 333,
    300, 330, 500, 750, 750, 750, 500, 722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 389, 389, 389, 389,
    722, 722, 778, 778, 778, 778, 778, 570, 778, 722, 722, 722, 722, 722, 611, 556, 500, 500, 500, 500, 500, 500, 722,
    444, 444, 444, 444, 444, 278, 278, 278, 278, 500, 556, 500, 500, 500, 500, 500, 570, 500, 556, 556, 556, 556, 500,
    556, 500,
),
    "Helvetica-Bold": (
    761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761, 761,
    761, 761, 761, 761, 761, 761, 761, 761, 761, 278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333,
    278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722,
    667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333,
    278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389,
    556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 761, 556, 0, 278, 556, 500, 1000, 556, 556, 333, 1000,
    667, 333, 1000, 0, 611, 0, 0, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 0, 500, 667, 278, 333,
    556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 611, 556, 278, 333,
    333, 365, 556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
    722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889,
    556, 556, 556, 556, 556, 278, 278, 278, 278, 611, 611, 611, 611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556,
    611, 556,
),
}
_FONTS = {"R": "Times-Roman", "B": "Times-Bold", "H": "Helvetica-Bold"}
_FALLBACK = {"\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2212": "-", "\u2192": "->", "\u2190": "<-", "\u00a0": " ",
             "\u202f": " ", "\u2009": " ", "\u200b": "", "\u2032": "'", "\u2033": '"', "\u2264": "<=", "\u2265": ">="}

PAGE_W, PAGE_H = 595.28, 841.89  # A4
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 72, 72, 70
TEXT_W = PAGE_W - 2 * MARGIN_X


def _encode(text: str) -> bytes:
    out = bytearray()
    for ch in text:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            out += _FALLBACK.get(ch, "?").encode("cp1252", "replace")
    return bytes(out)


def _width(data: bytes, font: str, size: float) -> float:
    w = _WIDTHS[_FONTS[font]]
    return sum(w[b] for b in data) * size / 1000


def _pdf_string(data: bytes) -> bytes:
    return b"(" + data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def _wrap(text: str, font: str, size: float, width: float) -> list:
    """Bricht in Zeilen um; liefert Listen von Wörtern (bytes)."""
    space = _width(b" ", font, size)
    lines, line, used = [], [], 0.0
    for word in (_encode(w) for w in text.split()):
        w = _width(word, font, size)
        if line and used + space + w > width:
            lines.append(line)
            line, used = [], 0.0
        while not line and w > width and len(word) > 1:  # überlanges Wort hart trennen
            cut = len(word)
            while cut > 1 and _width(word[:cut], font, size) > width:
                cut -= 1
            lines.append([word[:cut]])
            word = word[cut:]
            w = _width(word, font, size)
        used = used + space + w if line else w
        line.append(word)
    if line:
        lines.append(line)
    return lines


class _Doc:
    def __init__(self, footer: str):
        self.pages, self.ops, self.y, self.footer = [], [], 0.0, footer
        self.new_page()

    def new_page(self):
        if self.ops:
            self.pages.append(self.ops)
        self.ops, self.y = [], PAGE_H - MARGIN_TOP

    def need(self, height: float):
        if self.y - height < MARGIN_BOTTOM:
            self.new_page()

    def text(self, x: float, y: float, data: bytes, font: str, size: float, gray: float = 0.0, word_space: float = 0.0):
        self.ops.append(b"BT %.3f g /%s %.2f Tf %.3f Tw %.2f %.2f Td %s Tj ET" % (
            gray, font.encode(), size, word_space, x, y, _pdf_string(data)))

    def line(self, x1: float, y1: float, x2: float, y2: float, gray: float = 0.75, width: float = 1.2):
        self.ops.append(b"%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (gray, width, x1, y1, x2, y2))

    def paragraph(self, text: str, font: str = "R", size: float = 11.0, leading: float = 15.5, indent: float = 0.0,
                  gray: float = 0.0, justify: bool = True, after: float = 7.0, rule: bool = False):
        width = TEXT_W - indent
        space = _width(b" ", font, size)
        lines = _wrap(text, font, size, width)
        for i, words in enumerate(lines):
            self.need(leading)
            last = i == len(lines) - 1
            gap = 0.0
            if justify and not last and len(words) > 1:
                natural = sum(_width(w, font, size) for w in words) + space * (len(words) - 1)
                gap = max(0.0, (width - natural) / (len(words) - 1))
                if gap > space * 3:  # zu große Lücken (sehr lange Wörter): lieber linksbündig
                    gap = 0.0
            self.y -= leading
            if rule:
                self.line(MARGIN_X + indent - 9, self.y - 3, MARGIN_X + indent - 9, self.y + leading - 3)
            self.text(MARGIN_X + indent, self.y, b" ".join(words), font, size, gray, gap)
        self.y -= after

    def finish(self, title: str) -> bytes:
        self.pages.append(self.ops)
        total = len(self.pages)
        objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None]
        fonts = {key: len(objects) + i + 1 for i, key in enumerate(_FONTS)}
        for name in _FONTS.values():
            objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /%s /Encoding /WinAnsiEncoding >>" % name.encode())
        font_res = b" ".join(b"/%s %d 0 R" % (k.encode(), n) for k, n in fonts.items())
        kids = []
        for nr, ops in enumerate(self.pages, 1):
            foot = _encode(f"{self.footer} · {nr}/{total}")
            ops = ops + [b"BT 0.45 g /R 8.5 Tf 0 Tw %.2f %.2f Td %s Tj ET" % (
                (PAGE_W - _width(foot, "R", 8.5)) / 2, MARGIN_BOTTOM - 30, _pdf_string(foot))]
            stream = zlib.compress(b"\n".join(ops))
            objects.append(b"<< /Length %d /Filter /FlateDecode >>\nstream\n%s\nendstream" % (len(stream), stream))
            objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << %s >> >> "
                           b"/Contents %d 0 R >>" % (PAGE_W, PAGE_H, font_res, len(objects)))
            kids.append(len(objects))
        objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), total)
        info = b"<< /Title %s /Producer (Evel - Rote Faeden) /CreationDate (D:%s) >>" % (
            _pdf_string(_encode(title)), time.strftime("%Y%m%d%H%M%S").encode())
        objects.append(info)
        out, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), []
        for i, body in enumerate(objects, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
        out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
        out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(objects) + 1, len(objects), xref)
        return bytes(out)


def episode_pdf(episode: dict, brand: str = "Evel • Rote Fäden") -> bytes:
    """Folge (wie episodes.get_episode) als PDF: Kopf, Erzähltext, Dialoge mit Sprechername."""
    nr, title = episode.get("release_nr"), episode.get("title") or "Folge"
    label = "Geschichte" if episode.get("form") == "geschichte" else f"Folge {nr}"
    doc = _Doc(f"{brand} · {label}: {title}")
    doc.paragraph(brand.upper(), font="H", size=8.5, leading=12, gray=0.45, justify=False, after=18)
    doc.paragraph(label, font="H", size=11, leading=14, gray=0.35, justify=False, after=4)
    doc.paragraph(title, font="B", size=22, leading=27, justify=False, after=8)
    meta = [x for x in (episode.get("strang") and f"Strang: {episode['strang']}", episode.get("genre"),
                        episode.get("age_rating"), episode.get("minuten") and f"ca. {episode['minuten']} Minuten") if x]
    if meta:
        doc.paragraph(" · ".join(meta), size=9.5, leading=13, gray=0.4, justify=False, after=4)
    doc.y -= 10
    doc.line(MARGIN_X, doc.y, PAGE_W - MARGIN_X, doc.y, gray=0.8, width=0.6)
    doc.y -= 14
    for seg in episode.get("segmente") or []:
        if seg.get("typ") == "narrator":
            doc.paragraph(seg["text"])
        else:
            doc.need(15.5 + 12)
            doc.paragraph(str(seg.get("sprecher") or "").upper(), font="H", size=7.5, leading=10, indent=14, gray=0.45,
                          justify=False, after=0)
            doc.paragraph(seg["text"], indent=14, rule=True)
    return doc.finish(f"{label}: {title}")
