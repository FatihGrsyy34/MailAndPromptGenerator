"""Klasik Outlook'un (Office) Gönderilmiş Öğeler klasöründen kullanıcının kendi yazdığı mailleri çeker.
Yerel Outlook profilini COM ile okur: şifre/oturum gerekmez, mailler bilgisayardan dışarı çıkmaz.
Sonuç user_data/style_samples/outlook_sent.txt dosyasına "---" ile ayrılmış olarak yazılır."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from ..text import word_count

OL_FOLDER_SENT = 5
OL_MAIL_ITEM = 43

# Yanıt/iletme zincirinin başladığı satırlar: bundan sonrası kullanıcının yazdığı metin değildir
_CHAIN = re.compile(
    r"^\s*(From|Kimden|Gönderen|Sent|Gönderildi|-----\s*(Original Message|Özgün İleti|İlk İleti)|_{10,}|"
    r"On .{5,80} wrote:|.{5,80} tarihinde .{0,80} yazdı:)",
    re.I,
)
_NOISE = [
    (re.compile(r"\[cid:[^\]]*\]"), ""),  # gömülü resim kalıntısı
    (re.compile(r"<mailto:[^>]*>"), ""),
    (re.compile(r"<https?://[^>]*>"), ""),
    (re.compile(r"[ \t]+\n"), "\n"),
    (re.compile(r"\n{3,}"), "\n\n"),
]
# Otomatik/şablon mailler (rapor çıktıları vb.) kullanıcının üslubunu yansıtmaz
_SKIP_BODY = re.compile(r"Yasal Uyarı:|yatırım tavsiyesi değildir|This is an automated|Bu otomatik bir|"
                        r"sizinle bir dosya paylaştı|invited you to|size bir görev atadı|Microsoft 365'e abone|use of Microsoft 365", re.I)
_SKIP_SUBJECT = re.compile(r"^(Accepted|Declined|Tentative|Kabul edildi|Reddedildi|Belirsiz|Otomatik yanıt|Automatic reply)\b", re.I)


def own_text(body: str) -> str:
    lines = []
    for line in body.replace("\r\n", "\n").split("\n"):
        if _CHAIN.match(line):
            break
        lines.append(line)
    text = "\n".join(lines)
    for rx, rep in _NOISE:
        text = rx.sub(rep, text)
    return text.strip()


def fetch_sent(limit: int = 60, months: int = 12, min_words: int = 15) -> list[dict]:
    import win32com.client

    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    items = ns.GetDefaultFolder(OL_FOLDER_SENT).Items
    items.Sort("[SentOn]", True)
    since = dt.datetime.now() - dt.timedelta(days=30 * months)
    out, seen = [], set()
    for item in items:
        if len(out) >= limit:
            break
        try:
            if item.Class != OL_MAIL_ITEM:
                continue
            sent_on = item.SentOn
            if sent_on.replace(tzinfo=None) < since:
                break  # sıralı olduğu için daha eskisine bakmaya gerek yok
            subject = item.Subject or ""
            if _SKIP_SUBJECT.match(subject):
                continue
            text = own_text(item.Body or "")
        except Exception:
            continue
        key = text[:200]
        if word_count(text) < min_words or key in seen or _SKIP_BODY.search(text):
            continue  # sadece iletilmiş/boş mailler ve tekrarlar atlanır
        seen.add(key)
        out.append({"text": text, "subject": subject, "sent_on": sent_on.strftime("%Y-%m-%d"),
                    "to_count": item.Recipients.Count})
    return out


def import_to(folder: Path, limit: int = 60, months: int = 12) -> tuple[Path, list[dict]]:
    mails = fetch_sent(limit=limit, months=months)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "outlook_sent.txt"
    path.write_text("\n\n---\n\n".join(m["text"] for m in mails) + "\n", encoding="utf-8")
    return path, mails
