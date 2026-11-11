"""Text aus hochgeladenen Dateien holen – nur Standardbibliothek.

Unterstützt: .txt, .md, .html/.htm, .docx, .odt, .epub, .rtf (grob) und .pdf, falls `pdftotext` installiert ist.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

FORMATS = (".txt", ".md", ".markdown", ".html", ".htm", ".xhtml", ".docx", ".odt", ".epub", ".rtf", ".pdf")


class ImportError_(ValueError):
    pass


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = data.decode(enc)
            if enc != "utf-16" or text.count("\x00") == 0:
                return text
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n\n" if tag != "br" else "\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(markup: str) -> str:
    parser = _HTMLText()
    parser.feed(markup)
    return "".join(parser.out)


def _docx(data: bytes) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    paras = []
    for p in root.iter(ns + "p"):
        parts = []
        for el in p.iter():
            if el.tag == ns + "t" and el.text:
                parts.append(el.text)
            elif el.tag == ns + "tab":
                parts.append("\t")
            elif el.tag in (ns + "br", ns + "cr"):
                parts.append("\n")
        paras.append("".join(parts))
    return "\n\n".join(paras)


def _odt(data: bytes) -> str:
    ns = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    with zipfile.ZipFile(BytesIO(data)) as z:
        root = ET.fromstring(z.read("content.xml"))
    return "\n\n".join("".join(el.itertext()) for el in root.iter() if el.tag in (ns + "p", ns + "h"))


def _epub(data: bytes) -> str:
    with zipfile.ZipFile(BytesIO(data)) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        opf_path = next(el.get("full-path") for el in container.iter() if el.tag.endswith("rootfile"))
        opf = ET.fromstring(z.read(opf_path))
        base = PurePosixPath(opf_path).parent
        manifest = {el.get("id"): el.get("href") for el in opf.iter() if el.tag.endswith("item")}
        order = [el.get("idref") for el in opf.iter() if el.tag.endswith("itemref")]
        chapters = []
        for idref in order:
            href = manifest.get(idref)
            if not href:
                continue
            name = str(base / href) if str(base) != "." else href
            try:
                chapters.append(html_text(_decode(z.read(name))))
            except KeyError:
                continue
    return "\n\n".join(chapters)


_RTF_SKIP = ("fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer", "listtable", "listoverridetable",
             "expandedcolortbl", "*")


def _rtf(data: bytes) -> str:
    tool = shutil.which("textutil")  # macOS: zuverlässig
    if tool:
        with tempfile.TemporaryDirectory() as tmp:
            src = f"{tmp}/in.rtf"
            with open(src, "wb") as fh:
                fh.write(data)
            result = subprocess.run([tool, "-convert", "txt", "-stdout", src], capture_output=True, timeout=60)
        if result.returncode == 0:
            return result.stdout.decode("utf-8", "replace")
    raw = _decode(data)
    out, i, depth, skip_at = [], 0, 0, None
    while i < len(raw):
        c = raw[i]
        if c == "{":
            depth += 1
            m = re.match(r"\{\\(\*|[a-z]+)", raw[i:])
            if skip_at is None and m and m.group(1) in _RTF_SKIP:
                skip_at = depth
            i += 1
        elif c == "}":
            if skip_at == depth:
                skip_at = None
            depth -= 1
            i += 1
        elif c == "\\":
            m = re.match(r"\\(?:'([0-9a-fA-F]{2})|([a-zA-Z]+)(-?\d+)? ?|(.))", raw[i:])
            if skip_at is None:
                if m.group(1):
                    out.append(bytes([int(m.group(1), 16)]).decode("cp1252"))
                elif m.group(2) in ("par", "line"):
                    out.append("\n")
                elif m.group(2) == "tab":
                    out.append("\t")
                elif m.group(4) in ("\\", "{", "}"):
                    out.append(m.group(4))
            i += len(m.group(0))
        else:
            if skip_at is None and c not in "\r\n":
                out.append(c)
            i += 1
    return "".join(out)


def _pdf(data: bytes) -> str:
    tool = shutil.which("pdftotext")
    if not tool:
        raise ImportError_("PDF kann ohne „pdftotext“ (Mac: brew install poppler, Windows: poppler-Paket) nicht gelesen werden – "
                           "bitte den Text kopieren und einfügen.")
    with tempfile.TemporaryDirectory() as tmp:  # eigene Datei statt offener NamedTemporaryFile (Windows sperrt diese)
        src = f"{tmp}/in.pdf"
        with open(src, "wb") as fh:
            fh.write(data)
        result = subprocess.run([tool, "-layout", "-enc", "UTF-8", src, "-"], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise ImportError_("PDF konnte nicht gelesen werden.")
    return result.stdout.decode("utf-8", "replace")


def extract(filename: str, data: bytes) -> str:
    """Gibt den reinen Text einer Datei zurück (Absätze durch Leerzeilen getrennt)."""
    ext = PurePosixPath((filename or "").lower()).suffix
    if ext not in FORMATS:
        raise ImportError_(f"Dateiformat {ext or '(ohne Endung)'} wird nicht unterstützt. Möglich: {', '.join(FORMATS)}")
    try:
        if ext in (".txt", ".md", ".markdown"):
            text = _decode(data)
        elif ext in (".html", ".htm", ".xhtml"):
            text = html_text(_decode(data))
        elif ext == ".docx":
            text = _docx(data)
        elif ext == ".odt":
            text = _odt(data)
        elif ext == ".epub":
            text = _epub(data)
        elif ext == ".rtf":
            text = _rtf(data)
        else:
            text = _pdf(data)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, StopIteration) as exc:
        raise ImportError_(f"Datei konnte nicht gelesen werden ({type(exc).__name__}).")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
