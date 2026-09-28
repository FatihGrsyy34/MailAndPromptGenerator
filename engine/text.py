from __future__ import annotations

import re

_TR_UPPER = str.maketrans({"I": "ı", "İ": "i"})
_SENT_END = re.compile(r"(?<=[.!?…])\s+(?=[\"'“‘(]?[A-ZÇĞİÖŞÜ0-9])")
_WORD = re.compile(r"[\wçğıöşüÇĞİÖŞÜâîûÂÎÛ'’-]+", re.U)


def tr_lower(s: str) -> str:
    """Türkçe doğru küçük harf: I→ı, İ→i (Python'un lower()'ı İ'yi 'i̇' yapar)."""
    return s.translate(_TR_UPPER).lower()


def fold(s: str, lang: str) -> str:
    return tr_lower(s) if lang == "tr" else s.lower()


def words(s: str) -> list[str]:
    return _WORD.findall(s)


def word_count(s: str) -> int:
    return len(words(s))


def prose_lines(body: str) -> list[str]:
    """Hitap, kapanış ve imza gibi kısa satırları ayıklayıp asıl metin satırlarını döndürür."""
    return [ln.strip() for ln in body.splitlines() if word_count(ln) >= 5]


def sentences(body: str) -> list[str]:
    out: list[str] = []
    for line in prose_lines(body):
        out.extend(s.strip() for s in _SENT_END.split(line) if s.strip())
    return out
