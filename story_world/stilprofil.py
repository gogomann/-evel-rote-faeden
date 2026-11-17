"""Stil-Fingerabdruck – messbarer Schreibstil eines Autors, nur per Code (keine KI, keine Zusatzpakete).

Aus Texten eines Autors (eigene Texte, ein Buch des Vorbilds oder eine freigegebene Probe) entsteht ein Fingerabdruck:
je Merkmal (Satzlänge, Rhythmus, Dialoganteil, Erzählzeit, Perspektive, Satzzeichen, Wortwahl …) der typische Wert
UND die normale Schwankung innerhalb dieses Autors. Dazu kommt die Häufigkeit der kleinen Wörter („und“, „doch“,
„noch“ …), an denen Autoren sich zuverlässig unterscheiden (Burrows' Delta), und ein Wortschatz für Auffälligkeiten.

Eine neue Folge wird dagegen gehalten: Jedes Merkmal bekommt ein Urteil („passt“ / „auffällig“ / „deutlich anders“)
in Alltagssprache, dazu eine Gesamtzahl 0–100 (Stil-Treue) und Wörter, die die Folge auffällig oft benutzt, das
Vorbild aber kaum (typische KI-Lieblingswörter). So sieht der Mensch, WO der Stil kippt, und kann eingreifen.

Der Originaltext verlässt dabei nie den Rechner und geht nie an eine KI – gespeichert und weitergegeben werden nur
Kennzahlen.
"""

from __future__ import annotations

import math
import re
import time

_SPEAKER_LINE = re.compile(r"^\s*\[([^\]\n]{1,60})\]\s*", re.M)
_NARRATOR = re.compile(r"^(erzähler|erzaehler|erzählerin|erzaehlerin|sprecher|narrator)$", re.I)
_QUOTE = re.compile(r"„[^“”\"\n]{0,3000}?[“”\"]|»[^«\n]{0,3000}?«|«[^»\n]{0,3000}?»|\"[^\"\n]{1,3000}?\"|“[^”\n]{0,3000}?”"
                    r"|‚[^‘’\n]{0,600}?[‘’]")
_WORD = re.compile(r"[A-Za-zÄÖÜäöüßÀ-ÿ]+(?:-[A-Za-zÄÖÜäöüßÀ-ÿ]+)*")
_SENT_END = re.compile(r"(?<=[.!?…])[\"“”«»‘’)]*\s+|\n{2,}")
_ABBR = re.compile(r"\b(?:z|u|d|bzw|ca|etc|Dr|Mr|Mrs|Ms|Nr|St|vgl|bzw|usw|Prof|Hr|Fr)\.\s", re.I)

# Häufige deutsche Funktionswörter – inhaltsarm, aber je Autor sehr stabil verteilt (Grundlage für Burrows' Delta).
FUNKTIONSWOERTER = tuple("""der die das den dem des ein eine einen einem einer eines und oder aber doch denn sondern
nicht kein keine keinen auch noch schon nur so wie als wenn dass ob weil da dann nun ja mit von zu zum zur bei nach aus
auf an in im am um für über unter vor hinter durch gegen ohne bis seit er sie es ich du wir ihr man sich ihm ihn ihre
ihren ihrem sein seine seinen seinem mir mich dir dich uns was wer wo hier dort jetzt immer wieder sehr mehr etwas
einmal hatte war ist sind waren wurde wird hat haben kann konnte musste würde sollte einfach gar eben wohl fast kaum
selbst ganz alles nichts""".split())

_PAST = set("""war waren warst wart hatte hatten hattest wurde wurden wurdest konnte konnten musste mussten sollte sollten
wollte wollten durfte durften mochte sagte sagten fragte fragten ging gingen kam kamen sah sahen stand standen saß saßen
lag lagen nahm nahmen gab gaben hielt hielten blieb blieben fand fanden dachte dachten wusste wussten machte machten
ließ ließen sprach sprachen rief riefen lief liefen zog zogen trat traten schien schienen fühlte fühlten hörte hörten
legte legten stellte stellten öffnete öffnete drehte drehten schaute schauten blickte blickten nickte nickten lachte
lächelte schwieg schwiegen""".split())
_PRESENT = set("""ist sind bist seid hat habe haben hast habt wird werden wirst kann können muss müssen soll sollen will
wollen darf dürfen mag sagt sagen fragt fragen geht gehen kommt kommen sieht sehen steht stehen sitzt sitzen liegt liegen
nimmt nehmen gibt geben hält halten bleibt bleiben findet finden denkt denken weiß wissen macht machen lässt lassen
spricht sprechen ruft rufen läuft laufen zieht ziehen tritt treten scheint scheinen fühlt fühlen hört hören legt legen
stellt stellen öffnet dreht drehen schaut schauen blickt blicken nickt nicken lacht lächelt schweigt schweigen""".split())
_ICH = {"ich", "mich", "mir", "mein", "meine", "meinen", "meinem", "meiner", "meines"}

# Spracherkennung über häufige Wörter, die es nur in einer der Sprachen gibt
_SPRACH_WOERTER = {
    "de": set("und der die das nicht ist ich sie er es zu den mit sich auf ein eine dem des war auch noch".split()),
    "en": set("the and of to was he that his her you with had for on is not they but at she it".split()),
}
SPRACH_NAMEN = {"de": "Deutsch", "en": "Englisch"}
# Merkmale, die zwischen Sprachen vergleichbar sind (Satzbau, Rhythmus, Dialog, Satzzeichen). Wortlänge, Wortvielfalt,
# Kommas (deutsche Kommaregeln), Erzählzeit, Perspektive und die kleinen Wörter hängen an der Sprache selbst.
SPRACHFREI = {"satzlaenge", "satz_streuung", "kurze_saetze", "lange_saetze", "dialoganteil", "ausruf", "frage",
              "gedankenstrich", "doppelpunkt", "auslassung"}


def sprache_von(rates: dict) -> str | None:
    """rates: Wort → Häufigkeit (Anzahl oder je 1000). „de“, „en“ oder None, wenn nicht eindeutig."""
    score = {lang: sum(rates.get(w, 0) for w in ws) for lang, ws in _SPRACH_WOERTER.items()}
    best = max(score, key=score.get)
    rest = sum(v for k, v in score.items() if k != best)
    return best if score[best] > 0 and score[best] >= 3 * rest else None


def fp_sprache(fp: dict | None) -> str | None:
    """Sprache eines Fingerabdrucks; ältere ohne Feld werden aus dem gespeicherten Wortschatz bestimmt."""
    if not fp:
        return None
    return fp.get("sprache") or sprache_von(fp.get("wortschatz") or {})

CHUNK_WORDS = 1500        # Abschnittsgröße für die Schwankung innerhalb des Autors
MIN_WORDS = 150           # darunter keine Messung
SAFE_WORDS = 600          # darunter nur eingeschränkt aussagekräftig
VOCAB_SIZE = 3000

# id, Bezeichnung, Gewicht, typische relative Schwankung (falls nur eine Probe da ist), absolute Mindest-Schwankung,
# Format, Wort für „mehr“, Wort für „weniger“
MERKMALE = [
    ("satzlaenge", "Satzlänge Ø (Wörter)", 1.0, 0.18, 1.0, "{:.1f}", "längere Sätze", "kürzere Sätze"),
    ("satz_streuung", "Rhythmus (Wechsel kurz/lang)", 1.0, 0.22, 1.0, "{:.1f}", "unruhigerer Rhythmus, mehr Wechsel",
     "gleichförmigerer Rhythmus"),
    ("kurze_saetze", "Sehr kurze Sätze (bis 5 Wörter)", 1.0, 0.35, 0.04, "{:.0%}", "mehr sehr kurze Sätze",
     "weniger sehr kurze Sätze"),
    ("lange_saetze", "Lange Sätze (ab 25 Wörter)", 0.7, 0.4, 0.03, "{:.0%}", "mehr lange Sätze", "weniger lange Sätze"),
    ("komma", "Kommas je Satz (Verschachtelung)", 1.0, 0.25, 0.15, "{:.2f}", "stärker verschachtelt",
     "schlichter gebaut"),
    ("dialoganteil", "Dialoganteil (Wörter in wörtlicher Rede)", 1.0, 0.35, 0.06, "{:.0%}", "mehr Dialog",
     "weniger Dialog"),
    ("wortlaenge", "Wortlänge Ø (Buchstaben)", 1.0, 0.05, 0.08, "{:.2f}", "längere, schwerere Wörter",
     "kürzere, einfachere Wörter"),
    ("wortvielfalt", "Wortvielfalt (verschiedene Wörter je 300)", 0.8, 0.06, 0.015, "{:.2f}", "abwechslungsreicherer Wortschatz",
     "mehr Wortwiederholungen"),
    ("praeteritum", "Erzählzeit: Anteil Vergangenheit", 1.2, 0.08, 0.06, "{:.0%}", "mehr Vergangenheit (Präteritum)",
     "mehr Gegenwart (Präsens)"),
    ("ich_anteil", "Ich-Perspektive im Erzähltext (je 1000 Wörter)", 1.2, 0.4, 3.0, "{:.1f}", "mehr Ich-Erzählung",
     "weniger Ich-Erzählung"),
    ("ausruf", "Ausrufezeichen je 1000 Wörter", 0.5, 0.6, 0.8, "{:.1f}", "mehr Ausrufezeichen", "weniger Ausrufezeichen"),
    ("frage", "Fragezeichen je 1000 Wörter", 0.5, 0.5, 1.0, "{:.1f}", "mehr Fragen", "weniger Fragen"),
    ("gedankenstrich", "Gedankenstriche je 1000 Wörter", 0.5, 0.6, 0.8, "{:.1f}", "mehr Gedankenstriche",
     "weniger Gedankenstriche"),
    ("doppelpunkt", "Semikolon & Doppelpunkt je 1000 Wörter", 0.4, 0.6, 0.8, "{:.1f}", "mehr Semikolons/Doppelpunkte",
     "weniger Semikolons/Doppelpunkte"),
    ("auslassung", "Auslassungspunkte je 1000 Wörter", 0.4, 0.7, 0.6, "{:.1f}", "mehr Auslassungspunkte (…)",
     "weniger Auslassungspunkte"),
]
_SPEC = {m[0]: m for m in MERKMALE}
DELTA = ("wortwahl", "Autorensignatur: kleine Wörter (und, doch, noch …)", 2.0)

GRENZE_AUFFAELLIG = 2.0   # |z| ab hier „auffällig“
GRENZE_STARK = 3.0        # |z| ab hier „deutlich anders“
SCORE_PASST = 70
SCORE_STARK = 50


# ---------------------------------------------------------------- Zerlegen

def _split(text: str) -> tuple:
    """(Erzähltext, wörtliche Rede, Absätze) – Hörbuchformat ([Sprecher] je Absatz) und Buchformat (Anführungszeichen)."""
    text = (text or "").replace("\r\n", "\n")
    narration, dialog, paragraphs = [], [], []
    tagged = bool(_SPEAKER_LINE.search(text))
    for para in re.split(r"\n\s*\n|\n(?=\s*\[)", text):
        para = para.strip()
        if not para:
            continue
        m = _SPEAKER_LINE.match(para) if tagged else None
        body = para[m.end():] if m else para
        paragraphs.append(body)
        if m and not _NARRATOR.match(m.group(1).strip()):
            dialog.append(body)
            continue
        quotes = [q.group(0) for q in _QUOTE.finditer(body)]
        dialog.extend(quotes)
        narration.append(_QUOTE.sub(" ", body) if quotes else body)
    return "\n\n".join(narration), "\n".join(dialog), paragraphs


def _sentences(text: str) -> list:
    clean = _ABBR.sub(lambda m: m.group(0).replace(".", "·"), text)
    return [s for s in _SENT_END.split(clean) if s and _WORD.search(s)]


def words(text: str) -> list:
    return [w.lower() for w in _WORD.findall(text or "")]


def _mattr(ws: list, window: int = 300) -> float:
    if len(ws) <= window:
        return len(set(ws)) / max(1, len(ws))
    step = max(1, (len(ws) - window) // 40)
    vals = [len(set(ws[i:i + window])) / window for i in range(0, len(ws) - window + 1, step)]
    return sum(vals) / len(vals)


# ---------------------------------------------------------------- Messen

def messen(text: str) -> dict | None:
    """Alle Merkmale eines Textes. None, wenn er zu kurz ist."""
    narration, dialog, paragraphs = _split(text)
    body = "\n\n".join(paragraphs)
    ws = words(body)
    n = len(ws)
    if n < MIN_WORDS:
        return None
    sents = _sentences(body)
    lens = [len(_WORD.findall(s)) for s in sents] or [n]
    mean = sum(lens) / len(lens)
    std = math.sqrt(sum((x - mean) ** 2 for x in lens) / len(lens))
    nw = words(narration)
    past = sum(1 for w in nw if w in _PAST)
    pres = sum(1 for w in nw if w in _PRESENT)
    per_k = lambda c: c * 1000 / n  # noqa: E731
    counts: dict = {}
    for w in ws:
        counts[w] = counts.get(w, 0) + 1
    return {
        "woerter": n,
        "satzlaenge": mean,
        "satz_streuung": std,
        "kurze_saetze": sum(1 for x in lens if x <= 5) / len(lens),
        "lange_saetze": sum(1 for x in lens if x >= 25) / len(lens),
        "komma": body.count(",") / len(lens),
        "dialoganteil": len(words(dialog)) / n,
        "wortlaenge": sum(len(w) for w in ws) / n,
        "wortvielfalt": _mattr(ws),
        "praeteritum": past / (past + pres) if past + pres >= 5 else None,
        "ich_anteil": sum(1 for w in nw if w in _ICH) * 1000 / max(1, len(nw)) if nw else None,
        "ausruf": per_k(body.count("!")),
        "frage": per_k(body.count("?")),
        "gedankenstrich": per_k(len(re.findall(r"[–—]|\s-\s", body))),
        "doppelpunkt": per_k(body.count(";") + body.count(":")),
        "auslassung": per_k(body.count("…") + body.count("...")),
        "_fw": {w: counts.get(w, 0) * 1000 / n for w in FUNKTIONSWOERTER},
        "_counts": counts,
        "sprache": sprache_von(counts),
    }


def _chunks(text: str, size: int = CHUNK_WORDS) -> list:
    """Teilt an Absätzen in Stücke von etwa `size` Wörtern (für die Schwankung innerhalb des Autors)."""
    out, cur, count = [], [], 0
    for para in re.split(r"\n\s*\n|\n(?=\s*\[)", (text or "").replace("\r\n", "\n")):
        if not para.strip():
            continue
        cur.append(para)
        count += len(_WORD.findall(para))
        if count >= size:
            out.append("\n\n".join(cur))
            cur, count = [], 0
    if cur and (count >= size // 2 or not out):
        out.append("\n\n".join(cur))
    elif cur:
        out[-1] += "\n\n" + "\n\n".join(cur)
    return out


def _stats(values: list) -> tuple:
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None
    mean = sum(vals) / len(vals)
    std = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else None
    return mean, std


def _spread(key: str, mean: float, std: float | None, chunks: int) -> float:
    _, _, _, rel, floor, *_ = _SPEC[key]
    guess = max(abs(mean) * rel, floor)
    if std is None or chunks < 4:
        return guess
    return max(std, floor, abs(mean) * rel * 0.35)


def fingerabdruck(text: str, quelle: str = "", titel: str = "") -> dict | None:
    """Stil-Fingerabdruck aus einem (gern langen) Text. None, wenn der Text zu kurz ist."""
    whole = messen(text)
    if whole is None:
        return None
    parts = [m for m in (messen(c) for c in _chunks(text)) if m]
    if len(parts) < 2:
        parts = [whole]
    werte = {}
    for key, *_ in MERKMALE:
        mean, std = _stats([p[key] for p in parts])
        if whole[key] is not None:
            mean = whole[key]
        if mean is None:
            continue
        werte[key] = {"mittel": round(mean, 4), "streuung": round(_spread(key, mean, std, len(parts)), 4)}
    fw = {}
    few = len(parts) < 4
    for w in FUNKTIONSWOERTER:
        mean, std = _stats([p["_fw"][w] for p in parts])
        mean = whole["_fw"][w]
        spread = max(std or 0.0, 0.25 + mean * 0.15)
        if few:  # kurze Basis (z. B. Probe): Zufallsschwankung der Zählung einrechnen
            spread = max(spread, math.sqrt(max(mean, 0.5) * 1000 / whole["woerter"]))
        fw[w] = {"mittel": round(mean, 3), "streuung": round(spread, 3)}
    # Wie weit liegen die eigenen Abschnitte des Autors von seinem Profil entfernt? → Maßstab für „normal“
    own = [_delta(p["_fw"], fw) for p in parts] if len(parts) >= 4 else []
    d_mean, d_std = _stats(own)
    total = whole["woerter"]
    vocab = sorted(whole["_counts"].items(), key=lambda kv: -kv[1])[:VOCAB_SIZE]
    return {"version": 1, "quelle": quelle, "titel": titel, "sprache": whole["sprache"], "woerter": total, "abschnitte": len(parts),
            "erstellt": time.strftime("%Y-%m-%d %H:%M"), "werte": werte, "funktionswoerter": fw,
            "delta": {"mittel": round(d_mean, 3) if d_mean is not None else 0.75,
                      "streuung": round(max(d_std or 0.0, 0.08), 3) if d_std is not None else 0.25},
            "wortschatz": {w: round(c * 1000 / total, 3) for w, c in vocab if c >= 2}}


def _delta(fw_rates: dict, fw_profile: dict) -> float:
    """Burrows' Delta: mittlere Abweichung der Funktionswort-Häufigkeiten in Einheiten der Autor-Schwankung."""
    zs = [abs(fw_rates.get(w, 0.0) - s["mittel"]) / s["streuung"] for w, s in fw_profile.items()
          if s["mittel"] >= 0.5 or fw_rates.get(w, 0.0) >= 0.5]
    return sum(zs) / len(zs) if zs else 0.0


# ---------------------------------------------------------------- Vergleichen

def _fmt(key: str, value) -> str:
    if value is None:
        return "–"
    fmt = _SPEC[key][5] if key in _SPEC else "{:.2f}"
    return fmt.format(value).replace(".", ",")


def _span(key: str, mean: float, spread: float) -> str:
    """Normale Spanne des Vorbilds (± 2 Schwankungen), Anteile auf 0–100 % begrenzt."""
    lo, hi = max(0.0, mean - 2 * spread), mean + 2 * spread
    if "%" in _SPEC[key][5]:
        hi = min(1.0, hi)
    return f"{_fmt(key, lo)} – {_fmt(key, hi)}"


def _verdict(z: float) -> str:
    a = abs(z)
    return "stark" if a >= GRENZE_STARK else "auffaellig" if a >= GRENZE_AUFFAELLIG else "passt"


def vergleichen(text: str, fp: dict | None, namen: list | None = None) -> dict | None:
    """Hält einen Text gegen einen Fingerabdruck. Ergebnis ist für Menschen lesbar (Sätze, Ampel, Werte)."""
    if not fp or not fp.get("werte"):
        return None
    m = messen(text)
    if m is None:
        return {"wert": None, "urteil": "zu_kurz", "satz": "Text zu kurz für einen Stil-Abgleich.", "merkmale": [],
                "auffaellige_woerter": [], "quelle": fp.get("quelle")}
    rows, weighted, weights, skipped = [], 0.0, 0.0, []
    ref_lang = fp_sprache(fp)
    fremd = bool(m["sprache"] and ref_lang and m["sprache"] != ref_lang)  # z. B. deutsche Folge gegen englisches Buch
    # Lange Texte schwanken weniger als die 1500-Wörter-Abschnitte des Vorbilds → Spanne etwas enger (höchstens halb).
    shrink = max(0.5, math.sqrt(CHUNK_WORDS / m["woerter"])) if m["woerter"] > CHUNK_WORDS and fp.get("abschnitte", 0) >= 4 else 1.0
    for key, label, weight, *_rest in MERKMALE:
        ref = fp["werte"].get(key)
        mine = m.get(key)
        if not ref or mine is None:
            continue
        if fremd and key not in SPRACHFREI:
            skipped.append(label.split(" (")[0])
            continue
        z = (mine - ref["mittel"]) / (ref["streuung"] * shrink) if ref["streuung"] else 0.0
        more, less = _rest[-2], _rest[-1]
        verdict = _verdict(z)
        rows.append({"id": key, "label": label, "folge": round(mine, 4), "vorbild": ref["mittel"],
                     "folge_text": _fmt(key, mine), "vorbild_text": _fmt(key, ref["mittel"]),
                     "spanne_text": _span(key, ref["mittel"], ref["streuung"] * shrink),
                     "z": round(z, 2), "urteil": verdict,
                     "satz": ("im Rahmen des Vorbilds" if verdict == "passt" else
                              f"{more if z > 0 else less} als das Vorbild")})
        weighted += weight * min(abs(z), 4.0)
        weights += weight
    zd = 0.0
    if fremd:
        skipped.append("kleine Wörter")
    else:
        zd, weighted, weights = _signatur(m, fp, rows, weighted, weights)
    score = round(100 * (1 - (weighted / weights) / 4)) if weights else None
    odd = [] if fremd else auffaellige_woerter(m["_counts"], m["woerter"], fp, namen or [])
    return _bericht(m, fp, rows, score, odd, zd, skipped, ref_lang)


def _signatur(m: dict, fp: dict, rows: list, weighted: float, weights: float) -> tuple:
    """Autorensignatur (kleine Wörter) als eigene Zeile; nur bei gleicher Sprache sinnvoll."""
    d = _delta(m["_fw"], fp.get("funktionswoerter") or {})
    dref = dict(fp.get("delta") or {"mittel": 0.75, "streuung": 0.25})
    if m["woerter"] < CHUNK_WORDS:  # kurze Texte streuen bei den kleinen Wörtern stärker – Erwartung anheben
        factor = (CHUNK_WORDS / m["woerter"]) ** 0.5
        dref = {"mittel": dref["mittel"] * factor, "streuung": dref["streuung"] * factor}
    zd = max(0.0, (d - dref["mittel"]) / max(dref["streuung"], 0.05))
    verdict = _verdict(zd)
    top = _fw_outliers(m["_fw"], fp.get("funktionswoerter") or {})
    rows.append({"id": DELTA[0], "label": DELTA[1], "folge": round(d, 3), "vorbild": dref["mittel"],
                 "folge_text": f"{d:.2f}".replace(".", ","), "vorbild_text": f"{dref['mittel']:.2f}".replace(".", ","),
                 "spanne_text": f"bis {dref['mittel'] + 2 * dref['streuung']:.2f}".replace(".", ","),
                 "z": round(zd, 2), "urteil": verdict, "signatur": True,
                 "satz": "Verteilung der kleinen Wörter wie beim Vorbild" if verdict == "passt"
                 else "andere „kleine Wörter“ als das Vorbild – " + ", ".join(top)})
    weighted += DELTA[2] * min(zd, 4.0)
    weights += DELTA[2]
    return zd, weighted, weights


def _bericht(m: dict, fp: dict, rows: list, score, odd: list, zd: float, skipped: list, ref_lang: str | None) -> dict:
    strong = [r for r in rows if r["urteil"] == "stark"]
    key_strong = [r for r in strong if r["id"] in ("praeteritum", "ich_anteil", "dialoganteil", "satzlaenge")]
    if score is None:
        urteil = "unklar"
    elif score < SCORE_STARK or len(strong) >= 3 or key_strong:
        urteil = "stark"
    elif score < SCORE_PASST or strong or sum(1 for r in rows if r["urteil"] == "auffaellig") >= 3:
        urteil = "auffaellig"
    else:
        urteil = "passt"
    out_of = [r for r in rows if r["urteil"] != "passt"]
    out_of.sort(key=lambda r: -abs(r["z"]))
    satz = {"passt": "Klingt wie das Vorbild.",
            "auffaellig": "Weicht in einzelnen Punkten ab: ",
            "stark": "Weicht deutlich vom Vorbild ab: ",
            "unklar": "Kein Urteil möglich."}[urteil]
    if urteil in ("auffaellig", "stark"):
        satz += "; ".join(r["satz"] for r in out_of[:3]) + "."
    if skipped:
        satz += (f" Hinweis: Das Vorbild ist {SPRACH_NAMEN.get(ref_lang, ref_lang)}, die Folge "
                 f"{SPRACH_NAMEN.get(m['sprache'], m['sprache'])} – verglichen werden nur Satzbau, Rhythmus, Dialog und "
                 f"Satzzeichen; nicht vergleichbar: {', '.join(skipped)}.")
    if m["woerter"] < SAFE_WORDS:
        satz += f" (Nur {m['woerter']} Wörter – Aussage unsicher.)"
    return {"wert": score, "urteil": urteil, "satz": satz, "merkmale": rows, "auffaellige_woerter": odd,
            "signatur_z": round(zd, 2), "sprache": m["sprache"], "vorbild_sprache": ref_lang,
            "nicht_verglichen": skipped,
            "woerter": m["woerter"], "quelle": fp.get("quelle"), "titel": fp.get("titel"),
            "vorbild_woerter": fp.get("woerter"), "gemessen": time.strftime("%Y-%m-%d %H:%M")}


def _fw_outliers(rates: dict, profile: dict, n: int = 3) -> list:
    scored = []
    for w, s in profile.items():
        if s["mittel"] < 0.5 and rates.get(w, 0.0) < 0.5:
            continue
        z = (rates.get(w, 0.0) - s["mittel"]) / s["streuung"]
        scored.append((abs(z), f"„{w}“ {'häufiger' if z > 0 else 'seltener'}"))
    scored.sort(reverse=True)
    return [t for _, t in scored[:n]]


def auffaellige_woerter(counts: dict, total: int, fp: dict, namen: list, n: int = 8) -> list:
    """Wörter, die der Text auffällig oft benutzt, das Vorbild aber kaum – z. B. KI-Lieblingswörter."""
    vocab = fp.get("wortschatz") or {}
    if (fp.get("woerter") or 0) < 5000 or not vocab or total < SAFE_WORDS:
        return []
    floor = min(vocab.values()) if vocab else 0.01
    skip = set()
    for name in namen:
        skip.update(words(name))
    out = []
    for w, c in counts.items():
        if c < 3 or len(w) < 4 or w in skip or w in FUNKTIONSWOERTER:
            continue
        rate = c * 1000 / total
        ref = vocab.get(w, min(floor, 0.05) / 2)  # nicht im gespeicherten Wortschatz = beim Vorbild sehr selten
        if rate >= 0.6 and rate >= 6 * ref:
            out.append({"wort": w, "anzahl": c, "je_1000": round(rate, 2), "vorbild_je_1000": round(vocab.get(w, 0.0), 3),
                        "faktor": round(rate / max(ref, 1e-6))})
    out.sort(key=lambda x: (-x["je_1000"]))
    return out[:n]


def anhalten(bericht: dict | None) -> bool:
    return bool(bericht) and bericht.get("urteil") == "stark"


# ---------------------------------------------------------------- Erkennen: Wessen Stil ist das?

def erkennen(text: str, kandidaten: list) -> dict:
    """kandidaten: [(id, name, fingerabdruck)] → Rangliste, beste Übereinstimmung zuerst."""
    m = messen(text)
    if m is None:
        return {"woerter": len(words(text)), "rangliste": [], "satz": f"Bitte mindestens {MIN_WORDS} Wörter einfügen."}
    ranking = []
    for cid, name, fp in kandidaten:
        rep = vergleichen(text, fp)
        if not rep or rep.get("wert") is None:
            continue
        ranking.append({"id": cid, "name": name, "wert": rep["wert"], "urteil": rep["urteil"], "satz": rep["satz"],
                        "signatur_z": rep["signatur_z"], "basis_woerter": fp.get("woerter") or 0,
                        "sicher": (fp.get("woerter") or 0) >= 5000,
                        "quelle": fp.get("quelle"), "abweichungen": [r["label"] for r in rep["merkmale"]
                                                                       if r["urteil"] != "passt"][:4]})
    ranking.sort(key=lambda r: (-r["wert"], r["signatur_z"]))
    if not ranking:
        satz = "Noch keine Stimme mit Fingerabdruck – erst Texte oder eine Probe als Maßstab hinterlegen."
    else:
        best = ranking[0]
        gap = best["wert"] - (ranking[1]["wert"] if len(ranking) > 1 else 0)
        sicher = "eindeutig" if best["wert"] >= SCORE_PASST and gap >= 10 else "am ehesten" if best["wert"] >= SCORE_STARK \
            else "keiner passt gut – am nächsten"
        satz = f"Klingt {sicher} nach „{best['name']}“ ({best['wert']}/100)."
        if not best["sicher"]:
            satz += (f" Vorsicht: Der Maßstab dieser Stimme beruht nur auf {best['basis_woerter']} Wörtern "
                     "(z. B. einer Probe) – mit eigenen Texten oder einem Buch als Referenz wird es verlässlich.")
    if m["woerter"] < SAFE_WORDS:
        satz += f" Nur {m['woerter']} Wörter – mit mehr Text wird die Erkennung sicherer."
    return {"woerter": m["woerter"], "rangliste": ranking, "satz": satz}


# ---------------------------------------------------------------- Für Menschen und für die Schreib-KI

def tabelle(fp: dict | None) -> list:
    """Fingerabdruck als Tabelle: Merkmal, typischer Wert, normale Spanne."""
    if not fp:
        return []
    rows = []
    for key, label, *_ in MERKMALE:
        v = (fp.get("werte") or {}).get(key)
        if not v:
            continue
        rows.append({"id": key, "label": label, "wert": _fmt(key, v["mittel"]), "spanne": _span(key, v["mittel"], v["streuung"])})
    lang = fp_sprache(fp)
    if lang and lang != "de":
        rows.append({"id": "sprache", "label": "Sprache des Vorbilds", "wert": SPRACH_NAMEN.get(lang, lang),
                     "spanne": "Wortlänge, Wortvielfalt, Kommas und kleine Wörter gelten nur für diese Sprache"})
        return rows
    fw = fp.get("funktionswoerter") or {}
    top = sorted(fw.items(), key=lambda kv: -kv[1]["mittel"])[:12]
    rows.append({"id": "wortwahl", "label": "Häufigste kleine Wörter (je 1000)",
                 "wert": ", ".join(f"{w} {s['mittel']:.0f}" for w, s in top), "spanne": ""})
    return rows


def kurz(fp: dict | None) -> dict | None:
    """Kurzform ohne Wortschatz – für Oberfläche, Protokoll und Export-Übersicht."""
    if not fp:
        return None
    return {k: fp.get(k) for k in ("quelle", "titel", "woerter", "abschnitte", "erstellt")}


def _de(x: float, digits: int) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def ziele(fp: dict | None, sprache: str = "de") -> str:
    """Messbare Stilziele in Worten – für Planer, Autor und Lektor (nur Zahlen, nie Originaltext).
    Ist das Vorbild in einer anderen Sprache als die Folge (sprache), entfallen die sprachabhängigen Ziele."""
    if not fp or not fp.get("werte"):
        return ""
    lang = fp_sprache(fp)
    fremd = bool(lang and sprache and lang != sprache)
    v = {k: x["mittel"] for k, x in fp["werte"].items() if not fremd or k in SPRACHFREI}
    pct = lambda x: f"{round(100 * x)} %"  # noqa: E731
    lines = []
    if "satzlaenge" in v:
        lo, hi = max(2, round(v["satzlaenge"] - (v.get("satz_streuung") or 4))), round(v["satzlaenge"] + (v.get("satz_streuung") or 4))
        lines.append(f"- Sätze: im Schnitt {v['satzlaenge']:.0f} Wörter, meist zwischen {lo} und {hi}"
                     + (f"; etwa {pct(v['kurze_saetze'])} sehr kurze Sätze (bis 5 Wörter)" if "kurze_saetze" in v else "")
                     + (f", etwa {pct(v['lange_saetze'])} lange (ab 25 Wörter)" if "lange_saetze" in v else "") + ".")
    if "komma" in v:
        lines.append(f"- Satzbau: Ø {_de(v['komma'], 1)} Kommas je Satz ("
                     + ("eher schlicht, wenig Nebensätze" if v["komma"] < 0.8 else "deutlich verschachtelt"
                        if v["komma"] > 1.6 else "mäßig verschachtelt") + ").")
    if "dialoganteil" in v:
        lines.append(f"- Dialog: etwa {pct(v['dialoganteil'])} der Wörter sind wörtliche Rede.")
    if v.get("praeteritum") is not None:
        p = v["praeteritum"]
        lines.append("- Erzählzeit: " + ("Präteritum (Vergangenheit) – nicht ins Präsens rutschen." if p >= 0.7 else
                                        "Präsens (Gegenwart) – nicht ins Präteritum rutschen." if p <= 0.3 else
                                        "gemischt Präteritum und Präsens."))
    if v.get("ich_anteil") is not None:
        lines.append("- Perspektive: " + ("Ich-Erzähler." if v["ich_anteil"] >= 12 else
                                         "Erzähler in der dritten Person (im Erzähltext kaum „ich“)." if v["ich_anteil"] < 4
                                         else "überwiegend dritte Person, gelegentlich Ich-Passagen."))
    if "wortlaenge" in v:
        lines.append(f"- Wörter: Ø {_de(v['wortlaenge'], 1)} Buchstaben ("
                     + ("einfach, alltagsnah" if v["wortlaenge"] < 5.0 else "gehoben, viele lange Wörter"
                        if v["wortlaenge"] > 5.6 else "normal") + ").")
    marks = []
    for key, name in (("ausruf", "Ausrufezeichen"), ("frage", "Fragezeichen"), ("gedankenstrich", "Gedankenstriche"),
                      ("doppelpunkt", "Semikolon/Doppelpunkt"), ("auslassung", "Auslassungspunkte")):
        if key in v:
            word = "kaum" if v[key] < 0.5 else "selten" if v[key] < 2 else "regelmäßig" if v[key] < 6 else "häufig"
            marks.append(f"{name} {word} (~{v[key]:.1f} je 1000 Wörter)".replace(".", ","))
    if marks:
        lines.append("- Satzzeichen: " + "; ".join(marks) + ".")
    src = f"„{fp['titel']}“" if fp.get("titel") else (fp.get("quelle") or "dem Vorbild")
    count = f"{fp.get('woerter', 0):,}".replace(",", ".")
    if fremd:
        lines.append(f"- Das Vorbild ist {SPRACH_NAMEN.get(lang, lang)}: Wortwahl, Wortlänge und Kommasetzung nicht "
                     "übertragen, sondern so schreiben, wie es im Deutschen natürlich klingt (Erzählzeit und Perspektive "
                     "sind aus dem Vorbild hier nicht messbar).")
    head = (f"MESSBARE STILZIELE (Fingerabdruck aus {src}, {count} Wörter gemessen – "
            "diese Werte werden nach dem Schreiben nachgemessen):")
    return head + "\n" + "\n".join(lines)
