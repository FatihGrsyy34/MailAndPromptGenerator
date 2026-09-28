"""LLM'siz, anında çalışan "AI kokusu" kontrolleri. Bulunan her sorun hedefli bir düzeltme turuna girdi olur."""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from functools import lru_cache

from ..resources import load_lines
from ..text import fold, sentences, word_count
from . import Issue


@dataclass(frozen=True)
class _Pattern:
    rx: re.Pattern
    label: str
    suggestion: str
    soft: bool


@lru_cache(maxsize=None)
def banned_patterns(lang: str) -> tuple[_Pattern, ...]:
    out = []
    for line in load_lines(f"banned_{lang}.txt"):
        soft = line.startswith("~")
        line = line.lstrip("~").strip()
        phrase, _, suggestion = line.partition(" => ")
        phrase = phrase.strip()
        if phrase.startswith("re:"):
            rx = re.compile(phrase[3:])
            label = phrase[3:]
        else:
            # Başta kelime sınırı; sonda Türkçe ekler için serbest ("çekinmeyin" → "çekinmeyiniz")
            rx = re.compile(r"(?<!\w)" + re.escape(fold(phrase, lang)))
            label = phrase
        out.append(_Pattern(rx, label, suggestion.strip(), soft))
    return tuple(out)


def banned_phrase_list(lang: str, limit: int | None = None) -> str:
    """Promptlara eklenecek okunur liste (sadece sert, regex olmayan ifadeler)."""
    items = [p.label for p in banned_patterns(lang) if not p.soft and not p.label.startswith("\\")]
    items = [i for i in items if not any(c in i for c in "\\[]()|?")]
    return "; ".join(f'"{i}"' for i in items[:limit])


def _normalize(s: str) -> str:
    return s.replace("’", "'").replace("‘", "'")


def check_banned(text: str, lang: str) -> list[Issue]:
    norm = _normalize(text)
    folded = fold(norm, lang)
    same_len = len(folded) == len(norm)
    issues: list[Issue] = []
    for p in banned_patterns(lang):
        for m in p.rx.finditer(folded):
            span = norm[m.start() : m.end()] if same_len else m.group(0)
            issues.append(Issue("banned", "yapay kokan ifade", span, p.suggestion, hard=not p.soft))
    soft = [i for i in issues if not i.hard]
    if len(soft) >= 2:
        for i in soft:
            i.hard = True
    return issues


_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF]")
_BULLET = re.compile(r"^\s*([-•*▪●]|\d+[.)])\s+", re.M)


def check_format(body: str) -> list[Issue]:
    issues: list[Issue] = []
    if "—" in body:
        issues.append(Issue("format", "uzun tire (—) kullanılmış; virgül, nokta ya da parantez kullanın", "—"))
    if re.search(r"\s–\s", body):
        issues.append(Issue("format", "cümle içinde tire (–) kullanılmış; virgül ya da nokta kullanın", "–"))
    if ";" in body:
        issues.append(Issue("format", "noktalı virgül kullanılmış; iki cümleye bölün", ";"))
    if "**" in body or "__" in body or re.search(r"^\s*#", body, re.M):
        issues.append(Issue("format", "markdown biçimlendirme (kalın/başlık) var; düz metin yazın"))
    if _EMOJI.search(body):
        issues.append(Issue("format", "emoji kullanılmış", _EMOJI.search(body).group(0)))
    if _BULLET.search(body) and word_count(body) < 150:
        issues.append(Issue("format", "kısa mailde madde işareti; paragraf olarak yazın"))
    if body.count("!") > 1:
        issues.append(Issue("format", "birden fazla ünlem işareti", "!", hard=False))
    return issues


_TR_TRANSITIONS = re.compile(r"^(ayrıca|bununla birlikte|öte yandan|buna ek olarak|bunun yanı sıra|ek olarak)\b")
_EN_TRANSITIONS = re.compile(r"^(additionally|furthermore|moreover|in addition)\b")
_TR_MEKTEDIR = re.compile(r"(mekte|makta)(dır|dir|dur|dür)(lar|ler)?\W*$")


def check_rhythm(body: str, lang: str) -> list[Issue]:
    sents = sentences(body)
    issues: list[Issue] = []
    if not sents:
        return issues
    lengths = [word_count(s) for s in sents]
    if len(sents) >= 5:
        mean = statistics.mean(lengths)
        cv = statistics.pstdev(lengths) / mean if mean else 0
        if cv < 0.3:
            issues.append(Issue("rhythm", f"cümle uzunlukları çok tekdüze (değişkenlik {cv:.2f})", hard=False))

    openers = [fold(s, lang).split()[0].strip(",.") for s in sents if s.split()]
    for a, b, s in zip(openers, openers[1:], sents[1:]):
        if a == b and len(a) > 2:
            issues.append(Issue("rhythm", "art arda iki cümle aynı kelimeyle başlıyor", s[:60]))
    for w in set(openers):
        if openers.count(w) >= 3 and len(w) > 2:
            issues.append(Issue("rhythm", f'üç ya da daha fazla cümle "{w}" ile başlıyor', w))

    rx = _TR_TRANSITIONS if lang == "tr" else _EN_TRANSITIONS
    trans = [s for s in sents if rx.match(fold(s, lang))]
    if len(trans) >= 2:
        issues.append(Issue("rhythm", "cümleler kalıp geçiş kelimeleriyle başlıyor (Ayrıca/Öte yandan…)", trans[1][:60]))

    if lang == "tr":
        mek = [s for s in sents if _TR_MEKTEDIR.search(fold(s, lang))]
        if len(mek) >= 2 and len(mek) / len(sents) >= 0.35:
            issues.append(Issue("rhythm", '"-mektedir/-maktadır" ile biten cümle çok fazla; konuşma diline yakın çekim kullanın', mek[0][-40:]))
    return issues


def check_etiquette(body: str, lang: str) -> list[Issue]:
    issues: list[Issue] = []
    if lang == "tr":
        m = re.search(r"\bSayın\s+[A-ZÇĞİÖŞÜ][\wçğıöşü]+\s+(Bey|Hanım)\b", body)
        if m:
            issues.append(Issue("etiquette", 'unvan yığılması: "Sayın" ile "Bey/Hanım" birlikte kullanılmaz', m.group(0),
                                '"Sayın Ad Soyad" ya da "Ad Bey/Hanım"'))
    return issues


def check_subject(subject: str, lang: str) -> list[Issue]:
    words = [w for w in subject.split() if w[:1].isalpha()]
    if lang == "tr" and len(words) >= 3 and all(w[0].isupper() for w in words):
        return [Issue("format", "konu satırında her kelime büyük harfle başlıyor; sadece ilk kelime ve özel adlar büyük yazılır", subject, hard=False)]
    return []


def check_mail(subject: str, body: str, lang: str) -> list[Issue]:
    return (
        check_banned(f"{subject}\n{body}", lang)
        + check_format(body)
        + check_rhythm(body, lang)
        + check_etiquette(body, lang)
    )
