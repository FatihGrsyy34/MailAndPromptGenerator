"""Deterministik TDK yazım kontrolleri. Bilerek temkinli: yanlış alarm vermektense bazı hataları LLM
yazım denetimine bırakıyoruz. Buradaki bulgular yazım denetimi adımına ipucu olarak gider."""
from __future__ import annotations

import re

from ..text import tr_lower
from . import Issue

# Bitişik/ayrı yazım ve sık yapılan hatalar (küçük harfli biçim → doğru biçim)
_MISSPELLINGS = {
    "herşey": "her şey",
    "herşeyi": "her şeyi",
    "herşeyin": "her şeyin",
    "birşey": "bir şey",
    "birşeyi": "bir şeyi",
    "hiçbirşey": "hiçbir şey",
    "birsürü": "bir sürü",
    "hergün": "her gün",
    "herzaman": "her zaman",
    "hiçbirzaman": "hiçbir zaman",
    "birgün": "bir gün",
    "birkere": "bir kere",
    "birdaha": "bir daha",
    "yada": "ya da",
    "yinede": "yine de",
    "şuan": "şu an",
    "şuanda": "şu anda",
    "malesef": "maalesef",
    "herkez": "herkes",
    "yanlız": "yalnız",
    "yalnış": "yanlış",
    "orjinal": "orijinal",
    "süpriz": "sürpriz",
    "tabiki": "tabii ki",
    "ardarda": "art arda",
    "sağol": "sağ ol",
    "sağolun": "sağ olun",
    "çünki": "çünkü",
    "halbu ki": "halbuki",
    "tşk": "teşekkürler",
    "tşkler": "teşekkürler",
    "slm": "selam",
    "mrb": "merhaba",
}
_MULTI = {
    "tabi ki": "tabii ki",
    "bir çok": "birçok",
    "hiç bir": "hiçbir",
    "her hangi": "herhangi",
    "bir kaç": "birkaç",
    "direk olarak": "doğrudan",
}

# Soru eki "mi" ayrı yazılır: "geliyor musunuz", "uygun mu"
_MI_SUFFIX = r"(mu|mü|mı|mi)(sunuz|sünüz|sınız|siniz|sun|sün|sın|sin|yım|yim|yum|yüm|yız|yiz|yuz|yüz|dur|dür|dır|dir)?"
_MI_JOINED = re.compile(
    r"\b(\w+(?:yor|abilir|ebilir|acak|ecek|mış|miş|muş|müş)|var|yok|uygun|müsait|mümkün|tamam|doğru|olur|değil|hazır)"
    + _MI_SUFFIX + r"\b"
)
# Bağlaç "ki" ayrı yazılır: "diyor ki", "öyle ki"
_KI_JOINED = re.compile(
    r"\b(diyor|dedi|öyle|şöyle|böyle|düşünüyorum|biliyorum|umarım|görüyorum|anlaşılan|sanıyorum|zannediyorum|inanıyorum)ki\b"
)
_EN_THOUSANDS = re.compile(r"\b\d{1,3},\d{3}(?!\d)")
_EN_DECIMAL = re.compile(r"\b\d+\.\d{1,2}\s?(milyon|milyar|bin|tl|puan|kat)\b")
_EN_PERCENT = re.compile(r"\b\d+(?:[.,]\d+)?\s?%")
_HALA = re.compile(r"\bhala\b")
_KAR = re.compile(r"\bkar(\s(marjı|oranı|payı|zarar)|lılık|lı\b|ını\b)")
_TITLE_NO_APOS = re.compile(r"\b(Bey|Hanım)(e|a|i|ı|in|ın|den|dan|ten|tan|le|la|dir|dır)\b")
_LANG_APOS = re.compile(r"\b(Türkçe|İngilizce|Almanca|Fransızca|İspanyolca|Rusça|Arapça)['’]")
_GREETING = re.compile(r"^(Merhaba|Sayın|Değerli|Selam|Günaydın|İyi günler)\b[^,\n!]*$")


def check_spelling_tr(text: str, proper_nouns: list[str] | None = None) -> list[Issue]:
    issues: list[Issue] = []
    low = tr_lower(text)
    same_len = len(low) == len(text)

    def span(m: re.Match) -> str:
        return text[m.start() : m.end()] if same_len else m.group(0)

    for wrong, right in _MISSPELLINGS.items():
        for m in re.finditer(rf"\b{re.escape(wrong)}\b", low):
            issues.append(Issue("spelling", "yazım hatası", span(m), right))
    for wrong, right in _MULTI.items():
        for m in re.finditer(rf"\b{re.escape(wrong)}\b", low):
            issues.append(Issue("spelling", "yazım hatası", span(m), right))

    for m in _MI_JOINED.finditer(low):
        issues.append(Issue("spelling", 'soru eki "mi" ayrı yazılır', span(m), f"{m.group(1)} {m.group(2)}{m.group(3) or ''}"))
    for m in _KI_JOINED.finditer(low):
        issues.append(Issue("spelling", 'bağlaç "ki" ayrı yazılır', span(m), f"{m.group(1)} ki"))

    for m in _EN_THOUSANDS.finditer(text):
        issues.append(Issue("spelling", "binlik ayracı Türkçede noktadır", m.group(0), m.group(0).replace(",", ".")))
    for m in _EN_DECIMAL.finditer(low):
        issues.append(Issue("spelling", "ondalık ayracı Türkçede virgüldür", span(m), hard=False))
    for m in _EN_PERCENT.finditer(text):
        issues.append(Issue("spelling", 'yüzde işareti sayıdan önce yazılır ("%50")', m.group(0)))
    for m in _HALA.finditer(low):
        issues.append(Issue("spelling", '"hâlâ" (still) kastediliyorsa şapkalı yazılır', span(m), "hâlâ", hard=False))
    for m in _KAR.finditer(low):
        issues.append(Issue("spelling", '"kâr" (profit) şapkalı yazılır', span(m), hard=False))

    for m in _TITLE_NO_APOS.finditer(text):
        issues.append(Issue("spelling", "unvandan sonra gelen ek kesmeyle ayrılır", m.group(0), f"{m.group(1)}'{m.group(2)}"))
    for m in _LANG_APOS.finditer(text):
        issues.append(Issue("spelling", "dil adlarına gelen ekler kesmeyle ayrılmaz", m.group(0) + "…", m.group(1)))
    for noun in proper_nouns or []:
        if len(noun) < 3:
            continue
        for m in re.finditer(rf"\b{re.escape(noun)}(?!['’])([a-zçğıöşü]{{1,6}})\b", text):
            issues.append(Issue("spelling", "özel ada gelen ek kesmeyle ayrılır", m.group(0), f"{noun}'{m.group(1)}"))

    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if _GREETING.match(first) and len(first.split()) <= 5:
        issues.append(Issue("spelling", "hitaptan sonra virgül konur", first, first + ","))
    return issues
