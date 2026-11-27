"""Text front end: what the model reads for each language.

Libra reads ordinary written text (numbers, dates, units and symbols included), so most languages pass through as
written. Three steps cover what written text alone gets wrong:

  en  names, brands and loanwords from a curated lexicon, and abbreviations said letter by letter, become /IPA/
      hints the model was trained to read: "Porsche" -> /pˈɔɹʃə/, "NIH" -> /ˌɛnˌaɪˈeɪtʃ/
  ja  kanji and numbers become their hiragana reading (pyopenjtalk): a kanji's reading depends on the word
  zh  rare multi-character tokens are read character by character

Long text is split at sentence ends into utterances of at most ``MAX_SECONDS`` of speech. With language "auto" each
sentence is read in the language of its script (``language_runs``), so one text can mix languages.
"""
from __future__ import annotations

import json
import re
import unicodedata
import warnings
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .config import Config
from .prompt import Tokenizer

MAX_SECONDS = 20.0

# ------------------------------------------------------------------------------------------------ English
ARPA_IPA = {"AA": "ɑ", "AE": "æ", "AH": "ʌ", "AO": "ɔ", "AW": "aʊ", "AY": "aɪ", "EH": "ɛ", "ER": "ɜɹ", "EY": "eɪ",
            "IH": "ɪ", "IY": "i", "OW": "oʊ", "OY": "ɔɪ", "UH": "ʊ", "UW": "u",
            "B": "b", "CH": "tʃ", "D": "d", "DH": "ð", "F": "f", "G": "g", "HH": "h", "JH": "dʒ", "K": "k", "L": "l",
            "M": "m", "N": "n", "NG": "ŋ", "P": "p", "R": "ɹ", "S": "s", "SH": "ʃ", "T": "t", "TH": "θ", "V": "v",
            "W": "w", "Y": "j", "Z": "z", "ZH": "ʒ"}
UNSTRESSED = {"AH": "ə", "ER": "əɹ"}
STRESS = {"1": "ˈ", "2": "ˌ", "0": ""}
VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
LETTER_ARPA = {"A": "EY", "B": "B IY", "C": "S IY", "D": "D IY", "E": "IY", "F": "EH F", "G": "JH IY", "H": "EY CH",
               "I": "AY", "J": "JH EY", "K": "K EY", "L": "EH L", "M": "EH M", "N": "EH N", "O": "OW", "P": "P IY",
               "Q": "K Y UW", "R": "AA R", "S": "EH S", "T": "T IY", "U": "Y UW", "V": "V IY", "W": "D AH B AH L Y UW",
               "X": "EH K S", "Y": "W AY", "Z": "Z IY"}
LEX_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")  # letters of any script: Dvořák, Hermès, d'Alene
LEX_GAP = re.compile(r"[ \-‐]")  # between the words of a multi-word entry: Yves Saint Laurent, Coca-Cola
ACRONYM = re.compile(r"([A-Z]{2,6})((?:['’]?s)?)")
TAG = re.compile(r"<[^<>]{1,40}>")


def outside_tags(text: str, fn: Callable[[str], str]) -> str:
    """``fn`` applied to the text between inline tags (<laugh>, <short pause>, ...); the tags as written."""
    out, p = [], 0
    for m in TAG.finditer(text):
        out += [fn(text[p:m.start()]), m.group(0)]
        p = m.end()
    return "".join(out + [fn(text[p:])])


def arpa_to_ipa(pron: str) -> str:
    """ARPAbet -> the hint IPA: one symbol per phone, the stress mark right before the stressed vowel."""
    out = []
    for ph in pron.split():
        base, st = ph.rstrip("012"), ph[len(ph.rstrip("012")):]
        out.append(STRESS.get(st, "") + (UNSTRESSED[base] if st == "0" and base in UNSTRESSED else ARPA_IPA[base]))
    return "".join(out)


def spell_arpa(letters: str, suffix: str = "") -> str:
    """ARPAbet of an abbreviation said letter by letter (the last letter stressed); a plural / possessive s ends in Z."""
    out = []
    for i, c in enumerate(letters):
        ph = LETTER_ARPA[c].split()
        v = next(j for j, x in enumerate(ph) if x in VOWELS)
        out += [x + ("1" if i == len(letters) - 1 and j == v else "2" if j == v else "0") if x in VOWELS else x
                for j, x in enumerate(ph)]
    return " ".join(out + (["Z"] if suffix else []))


def fold(word: str) -> str:
    return unicodedata.normalize("NFKD", word.replace("’", "'")).encode("ascii", "ignore").decode().lower()


class EnglishLexicon:
    """Whole-word matches, longest entry first; case and accents folded unless an entry is marked ``exact`` (Visa,
    Puma: also common words). A trailing 's adds the plural ending; a one-word entry may be said as several words
    (WWII). Abbreviations from the letter list are hinted where they are written in capitals in mixed-case text."""

    def __init__(self, lexicon: str, acronyms: str):
        self.acronyms = {l.strip() for l in open(acronyms, encoding="utf-8") if l.strip() and not l.startswith("#")}
        self.acronyms -= {"TTS"}
        self.entries: Dict[tuple, List[List[str]]] = {}
        for line in open(lexicon, encoding="utf-8"):
            if not line.strip() or line.startswith("#"):
                continue
            name, arpa, case = line.rstrip("\n").split("\t")[:3]
            words = LEX_WORD.findall(name)
            key = ("exact",) + tuple(words) if case == "exact" else tuple(fold(w) for w in words)
            self.entries[key] = [p.split() for p in arpa.split("|")]
        self.longest = max(len(k) for k in self.entries)

    def spelled(self, word: str, text: str) -> Optional[List[str]]:
        m = ACRONYM.fullmatch(word)
        if not m or m.group(1) not in self.acronyms:
            return None
        letters = [c for c in text if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.5:  # a heading or shouting: as written
            return None
        return [arpa_to_ipa(spell_arpa(m.group(1), m.group(2)))]

    def lookup(self, words: Sequence[str]) -> Optional[List[str]]:
        tries = [(list(words), None)]
        if re.search(r"['’]s$", words[-1]):
            tries.append((list(words[:-1]) + [words[-1][:-2]], "s"))
        for ws, suffix in tries:
            prons = self.entries.get(("exact",) + tuple(ws)) or self.entries.get(tuple(fold(w) for w in ws))
            if prons:
                prons = [list(p) for p in prons]
                if suffix:
                    last = prons[-1][-1].rstrip("012")
                    prons[-1] += ["IH0", "Z"] if last in ("S", "Z", "SH", "ZH", "CH", "JH") else \
                        (["S"] if last in ("P", "T", "K", "F", "TH") else ["Z"])
                return [arpa_to_ipa(" ".join(p)) for p in prons]
        return None

    def apply(self, text: str) -> str:
        return outside_tags(text, self._apply)

    def _apply(self, text: str) -> str:
        text = re.sub(r"\blibra(\s+)tts\b", r"Libra\1TTS", text, flags=re.I)
        text = re.sub(r"\btts\b", "TTS", text, flags=re.I)
        toks, out, pos, i = list(LEX_WORD.finditer(text)), [], 0, 0
        while i < len(toks):
            for n in range(min(self.longest, len(toks) - i), 0, -1):
                seq = toks[i:i + n]
                if all(LEX_GAP.fullmatch(text[a.end():b.start()]) for a, b in zip(seq, seq[1:])):
                    ipa = self.lookup([t.group(0) for t in seq]) or (
                        self.spelled(seq[0].group(0), text) if n == 1 else None)
                    if ipa:
                        break
            else:
                i += 1
                continue
            out.append(text[pos:seq[0].start()])
            if len(seq) == 1:
                out.append(" ".join("/" + p + "/" for p in ipa))
            else:
                for j, (t, p) in enumerate(zip(seq, ipa)):
                    out += ([text[seq[j - 1].end():t.start()]] if j else []) + ["/" + p + "/"]
            pos, i = seq[-1].end(), i + n
        return "".join(out + [text[pos:]])


# ------------------------------------------------------------------------------------------------ Japanese
NUM = re.compile(r"[０-９．]+")
HALF = {c: c - 0xFEE0 for c in list(range(0xFF10, 0xFF1A)) + list(range(0xFF21, 0xFF3B)) + list(range(0xFF41, 0xFF5B))}
HAN = re.compile(r"[㐀-鿿豈-﫿々]")
# runs handed to OpenJTalk: Japanese script, digits and the punctuation between them (Latin text stays as written)
JA_RUN = re.compile(r"[぀-ヿㇰ-ㇿ㐀-鿿豈-﫿々〆〇ー0-9０-９.．,，、。・「」『』（）！？〜…%％]+")


def _hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def _reading(read: str, pron: str) -> str:
    """The dictionary reading unless the spoken one differs beyond long-vowel marks (counters: 三本 -> さんぼん)."""
    pron = pron.replace("’", "")
    if len(read) == len(pron) and all(r == p or p == "ー" for r, p in zip(read, pron)):
        return read
    return pron


def _kana_run(run: str) -> str:
    import pyopenjtalk
    nf = lambda x: unicodedata.normalize("NFKC", x)  # noqa: E731
    out, p = [], 0
    for n in pyopenjtalk.run_frontend(run):
        s = n["string"]
        orig = run[p:p + len(s)] if p >= 0 and nf(run[p:p + len(s)]) == nf(s) else None
        p = p + len(s) if orig is not None else -1
        if (HAN.search(s) or NUM.fullmatch(s)) and n["read"] not in ("", "*", "、"):
            out.append(_hira(_reading(n["read"], n["pron"])))
        else:
            out.append(orig if orig is not None else s.translate(HALF))
    return "".join(out)


def _kana_long(run: str, limit: int = 300) -> str:
    out = []
    while run:  # OpenJTalk fails on very long runs: pieces of <= limit characters, cut after 。！？ or 、
        k = len(run) if len(run) <= limit else max(run.rfind(c, 0, limit) for c in "。！？、") + 1 or limit
        out.append(_kana_run(run[:k]))
        run = run[k:]
    return "".join(out)


def to_kana(text: str) -> str:
    """Every kanji or number word as its reading in hiragana; kana, punctuation, Latin text and tags as written."""
    def seg(t):
        return JA_RUN.sub(lambda m: _kana_long(m.group(0)) if HAN.search(m.group(0)) or re.search(r"[0-9０-９]", m.group(0))
                          else m.group(0), t)
    return outside_tags(text, seg)


# ------------------------------------------------------------------------------------------------ Chinese
def is_han_multichar(s: str) -> bool:
    return len(s) > 1 and all("一" <= c <= "鿿" for c in s)


class ChineseSplit:
    def __init__(self, path: str, tok: Tokenizer):
        self.rare, self.tok, self._pieces = frozenset(json.load(open(path))["ids"]), tok, {}

    def __call__(self, ids: Sequence[int]) -> List[int]:
        """Template ids with every rare multi-character token of the text part replaced by its characters."""
        a, out = list(ids), []
        for t in a[3:-5]:
            if t in self.rare:
                if t not in self._pieces:
                    s = self.tok.token_text(t)
                    self._pieces[t] = [i for c in s for i in self.tok.piece_ids(c)] if is_han_multichar(s) else None
                if self._pieces[t] is not None:
                    out += self._pieces[t]
                    continue
            out.append(t)
        return a[:3] + out + a[-5:]


# ------------------------------------------------------------------------------------------------ languages, splitting
SCRIPTS = [("ja", re.compile(r"[぀-ヿ]")), ("ko", re.compile(r"[가-힯ᄀ-ᇿ]")), ("zh", HAN),
           ("hi", re.compile(r"[ऀ-ॣ०-ॿ]")), ("pa", re.compile(r"[਀-੿]")), ("bn", re.compile(r"[ঀ-৿]")),
           ("ur", re.compile(r"[ٹڈڑںےۓہھ]")), ("ar", re.compile(r"[؀-ۿ]")), ("ru", re.compile(r"[Ѐ-ӿ]"))]
ABBREV = {"mr", "mrs", "ms", "dr", "st", "prof", "sr", "jr", "vs", "etc", "e.g", "i.e", "no", "fig", "vol", "mt", "approx"}
SENT = re.compile(r".+?(?:[.!?…]+[\"'”’)\]]*(?=\s|$)|[。！？؟।॥]+[」』”’)）]*|$)", re.S)


def detect_language(text: str) -> str:
    """By script; Latin-script text counts as English (pass the language for de, fr, es, it, pt, id)."""
    for lang, rx in SCRIPTS:
        if rx.search(text):
            return lang
    return "en"


def _abbrev_end(s: str) -> bool:
    """A period that does not end a sentence: "Dr.", "J.", "e.g.", "U.S."."""
    if not s.endswith("."):
        return False
    w = s.rsplit(None, 1)[-1][:-1]
    return (len(w) == 1 and w.isupper()) or w.lower() in ABBREV or \
        ("." in w and all(len(x) == 1 for x in w.split(".")))


def sentences(text: str) -> List[str]:
    out: List[str] = []
    for m in SENT.finditer(text.strip()):
        s = m.group(0).strip()
        if s and out and _abbrev_end(out[-1]):
            out[-1] += " " + s
        elif s:
            out.append(s)
    return out


LATIN = re.compile(r"[A-Za-zÀ-ɏ]")


def sentence_language(s: str, ja: bool = False, ur: bool = False) -> Optional[str]:
    """One sentence's language: the script most of its letters are in (Latin = English), None without letters. Han is
    Japanese in a sentence with kana or when ``ja`` (the text has kana elsewhere), else Chinese; Arabic script is Urdu
    when ``ur`` (the text has letters only Urdu uses)."""
    sc = dict(SCRIPTS)
    n = {lang: len(sc[lang].findall(s)) for lang in ("ko", "hi", "pa", "bn", "ar", "ru")}
    kana = len(sc["ja"].findall(s))
    n["ja" if kana or ja else "zh"] = kana + len(HAN.findall(s))
    n["en"] = len(LATIN.findall(s))
    lang = max(n, key=n.get)
    if not n[lang]:
        return None
    return "ur" if lang == "ar" and ur else lang


def language_runs(text: str) -> List[Tuple[str, str]]:
    """Text read with language "auto" as (language, text) runs: each line split into sentences, each sentence in its
    own language (sentence_language), neighbours in the same language joined. A sentence without letters stays with
    the one before it. Text in one language is one run, as written."""
    sc = dict(SCRIPTS)
    ja, ur = bool(sc["ja"].search(text)), bool(sc["ur"].search(text))
    runs: List[list] = []
    lead: List[str] = []
    for line in text.splitlines():
        for s in sentences(line):
            lang = sentence_language(s, ja, ur)
            if lang is None and not runs:
                lead.append(s)
            elif runs and lang in (None, runs[-1][0]):
                runs[-1][1].append(s)
            else:
                runs.append([lang, lead + [s]])
                lead = []
    if len(runs) <= 1:
        return [(runs[0][0] if runs else detect_language(text), text)] if text.strip() else []
    return [(lang, ("" if lang in ("ja", "zh") else " ").join(p)) for lang, p in runs]


def _pieces(s: str, budget: int) -> List[str]:
    """A sentence longer than the budget, cut at clause punctuation, else between words."""
    if len(s) <= budget:
        return [s]
    parts = [p for p in re.split(r"(?<=[,;:，、；：])\s*", s) if p]
    if len(parts) == 1:
        words = s.split(" ") if " " in s else list(s)
        joiner = " " if " " in s else ""
        parts, cur = [], ""
        for w in words:
            if cur and len(cur) + len(w) + 1 > budget:
                parts.append(cur)
                cur = w
            else:
                cur = cur + joiner + w if cur else w
        return parts + ([cur] if cur else [])
    out = []
    for p in parts:
        out += _pieces(p, budget) if len(p) > budget else [p]
    return out


def split_utterances(text: str, chars_per_second: float, max_seconds: float = MAX_SECONDS) -> List[str]:
    budget = max(20, int(chars_per_second * max_seconds))
    units = [p for s in sentences(text) for p in _pieces(s, budget)]
    out, cur = [], ""
    for u in units:
        sep = "" if re.match(r"[぀-ヿ㐀-鿿]", u) else " "
        if cur and len(cur) + len(sep) + len(u) > budget:
            out.append(cur)
            cur = u
        else:
            cur = cur + sep + u if cur else u
    return out + ([cur] if cur else [])


class FrontEnd:
    def __init__(self, cfg: Config, tok: Tokenizer):
        self.cfg, self.tok = cfg, tok
        self.en = EnglishLexicon(cfg.file("frontend", "en_lexicon.tsv"), cfg.file("frontend", "en_acronyms.txt"))
        self.zh = ChineseSplit(cfg.file("frontend", "zh_rare_tokens.json"), tok)
        self._kana: Optional[Callable[[str], str]] = None

    def kana(self, text: str) -> str:
        if self._kana is None:
            try:
                import pyopenjtalk  # noqa: F401
                self._kana = to_kana
            except ImportError:
                warnings.warn("pyopenjtalk is not installed (pip install 'libra-tts[ja]'): Japanese is read as "
                              "written, with more kanji misreadings", stacklevel=2)
                self._kana = lambda s: s
        return self._kana(text)

    def utterances(self, text: str, lang: str) -> List[str]:
        """The text split into utterances, each as the model reads it."""
        cps = self.cfg.language(lang)["chars_per_second"]
        unknown = {t for t in TAG.findall(text) if t not in self.cfg.tags}
        if unknown:
            warnings.warn(f"tags the model was not trained on: {' '.join(sorted(unknown))} (known: "
                          f"{' '.join(self.cfg.tags)})", stacklevel=3)
        text = re.sub(r"(<[^<>]{1,40}>)(?=\S)", r"\1 ", text)  # a tag is a word of its own, as in training
        out = []
        for u in split_utterances(" ".join(text.split()) if lang not in ("ja", "zh") else text.strip(), cps):
            out.append(self.en.apply(u) if lang == "en" else self.kana(u) if lang == "ja" else u)
        return out

    def encode(self, utterance: str, lang: str) -> List[int]:
        ids = self.tok.encode(utterance)
        return self.zh(ids) if lang == "zh" else ids
