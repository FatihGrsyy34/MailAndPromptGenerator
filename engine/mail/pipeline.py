"""Mail üretim hattı: taslak → humanize/eleştiri (+ kod kontrolleri) → yazım denetimi → son kontrol."""
from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..checks import Issue, hints
from ..checks.slop import banned_phrase_list, check_mail
from ..checks.tr_spelling import check_spelling_tr
from ..config import Config
from ..llm import LLMLike
from ..resources import load_prompt, load_yaml, render
from ..text import word_count
from .style_profile import StyleStore

LANG_NAMES = {"tr": "Turkish", "en": "English"}
_TR_DAYS = ("pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar",
            "ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık")


def _keep_lowercase_days(before: str, after: str) -> str:
    """Yazım denetimi modelleri tarih bildirmeyen gün/ay adlarını büyütmeye meyilli (TDK'ya aykırı): geri al.
    Sadece cümle ortasındaki, önünde rakam olmayan (yani tarih olmayan) kullanımlara dokunur."""
    for day in _TR_DAYS:
        cap = day[0].upper() + day[1:]
        if re.search(rf"\b{day}\b", before) and cap in after:
            after = re.sub(rf"(?<=[a-zçğıöşü,] ){cap}\b", day, after)
    return after


def _fix_day_case(body: str) -> str:
    """TDK: belirli bir tarih bildirmeyen gün/ay adları cümle içinde küçük yazılır ("ağustos verileri", "cuma sabahı").
    Cümle başına ve rakamla/yılla birlikte gelen tarihlere ("14 Ekim", "Ekim 2026") dokunmaz."""
    def repl(m: re.Match) -> str:
        before = body[max(0, m.start() - 24) : m.start()]
        if re.search(r"\d{1,4}\s+(\w+\s+)?$", before):  # "14 Ekim Salı", "2026 Ekim"
            return m.group(0)
        return m.group(0).lower()

    names = "|".join(d[0].upper() + d[1:] for d in _TR_DAYS)
    return re.sub(rf"(?<=[a-zçğıöşü,] )({names})\b(?! \d{{4}})", repl, body)


def _format_cleanup(text: str) -> str:
    """Model düzeltme turlarında temizleyemezse biçim kalıntılarını kodla giderir."""
    text = re.sub(r"\s*—\s*", ", ", text)
    text = re.sub(r"\s+–\s+", ", ", text)
    text = re.sub(r"\s*;\s*", ", ", text)
    text = text.replace("**", "").replace("__", "")
    return text


def _closing_line(body: str, signature: str) -> str:
    lines = [ln.strip() for ln in body.rstrip().splitlines() if ln.strip()]
    if len(lines) >= 2 and lines[-1] == signature and lines[-2].endswith(","):
        return lines[-2]
    return ""


def _ensure_closing(before: str, after: str, signature: str) -> str:
    """Düzenleme adımı kapanış satırını ("İyi çalışmalar,") silerse geri koyar."""
    closing = _closing_line(before, signature)
    if closing and not _closing_line(after, signature) and after.rstrip().endswith(signature):
        head = after.rstrip()[: -len(signature)].rstrip()
        return f"{head}\n\n{closing}\n{signature}"
    return after


def _tidy_signature(body: str, signature: str) -> str:
    """Kapanış satırı ile imza arasındaki boş satırı kaldırır."""
    body = body.rstrip()
    if signature and body.endswith(signature):
        head = body[: -len(signature)].rstrip()
        body = f"{head}\n{signature}"
    return body


# ---------- şemalar ----------
class Draft(BaseModel):
    subject: str
    body: str
    placeholders: list[str]
    notes: str


class Scores(BaseModel):
    directness: int
    rhythm: int
    trust: int
    authenticity: int
    density: int

    @property
    def total(self) -> int:
        return self.directness + self.rhythm + self.trust + self.authenticity + self.density


class Humanized(BaseModel):
    scores: Scores
    problems: list[str]
    subject: str
    body: str


class Change(BaseModel):
    from_text: str = ""
    to_text: str = ""
    reason: str = ""


class Proofread(BaseModel):
    subject: str
    body: str
    changes: list[Change]


# ---------- istek / sonuç ----------
@dataclass
class MailRequest:
    context: str
    lang: str = "tr"
    tone: str = "normal"
    recipient: str = "meslektas"
    length: str = "orta"
    thread: str = ""  # yanıt yazılıyorsa gelen mail
    revision: str = ""  # "daha kısa yap" gibi düzeltme isteği
    previous: "MailResult | None" = None


@dataclass
class MailResult:
    subject: str
    body: str
    placeholders: list[str] = field(default_factory=list)
    notes: str = ""
    warnings: list[Issue] = field(default_factory=list)
    scores: Scores | None = None
    trace: list[dict] = field(default_factory=list)

    @property
    def text(self) -> str:
        return f"Konu: {self.subject}\n\n{self.body}" if self.subject else self.body


class MailPipeline:
    def __init__(self, llm: LLMLike, config: Config, style: StyleStore | None = None):
        self.llm = llm
        self.config = config
        self.style = style if style is not None else StyleStore(config.user_data)
        self.data = load_yaml("tones")
        self.on_step = lambda text: None  # arayüz ilerleme göstersin diye

    # ---- yardımcılar ----
    def _cards(self, req: MailRequest) -> dict:
        tone = self.data["tones"][req.tone]
        recipient = self.data["recipients"][req.recipient]
        length = self.data["lengths"][req.length]
        lang = req.lang
        return {
            "tone_label": tone["label_en"],
            "tone_card": tone["card"].strip(),
            "greetings": " / ".join(tone[f"greeting_{lang}"]),
            "closings": " / ".join(tone[f"closings_{lang}"]),
            "recipient_label": recipient["label_en"],
            "recipient_card": recipient["card"].strip(),
            "length_card": length["card"],
            "language_name": LANG_NAMES[lang],
        }

    def _sender(self) -> str:
        u = self.config.user
        name = u.get("name") or "the sender"
        extra = ", ".join(x for x in (u.get("title"), u.get("company")) if x)
        return f"{name} ({extra})" if extra else name

    def _signature(self) -> str:
        """Boş dönerse mail isimsiz biter (imzayı Outlook ekliyor)."""
        u = self.config.user
        if not u.get("sign_with_name", False):
            return ""
        return u.get("name") or "[Adınız]"

    def _checks(self, subject: str, body: str, lang: str) -> list[Issue]:
        issues = check_mail(subject, body, lang)
        if lang == "tr":
            nouns = [self.config.user.get("company", "")]
            issues += check_spelling_tr(body, nouns) + [
                i for i in check_spelling_tr(subject, nouns) if "hitap" not in i.message
            ]
        return issues

    def _length_issue(self, body: str, req: MailRequest) -> list[Issue]:
        spec = self.data["lengths"][req.length]
        n = word_count(body)
        if n < spec["min_words"] * 0.7 or n > spec["max_words"] * 1.3:
            return [Issue("length", f"uzunluk hedefin dışında ({n} kelime, hedef {spec['min_words']}-{spec['max_words']})", hard=False)]
        return []

    @staticmethod
    def _step(trace: list, name: str, start: float, **extra) -> None:
        trace.append({"step": name, "seconds": round(time.perf_counter() - start, 2), **extra})

    # ---- adımlar ----
    def draft(self, req: MailRequest, trace: list) -> Draft:
        self.on_step("Düzeltiliyor" if req.revision else "Taslak yazılıyor")
        t = time.perf_counter()
        cards = self._cards(req)
        k = int(self.config.mail.get("style_examples", 4))
        examples = self.style.similar(self.llm, req.context + "\n" + req.thread, req.lang, k)
        system = render(
            load_prompt("mail_draft"),
            sender=self._sender(),
            signature=self._signature(),
            no_signature=not self._signature(),
            mode_text="reply to the email in <thread>" if req.thread else "new email",
            lang_guide=load_prompt(f"mail_lang_{req.lang}"),
            style_profile=self.style.profile_text(),
            examples="\n\n".join(f"<example>\n{e}\n</example>" for e in examples),
            banned=banned_phrase_list(req.lang, limit=40),
            **cards,
        )
        parts = [f"<context>\n{req.context.strip()}\n</context>"]
        if req.thread.strip():
            parts.append(f"<thread>\n{req.thread.strip()}\n</thread>")
        if req.revision and req.previous:
            parts.append(f"<previous_version>\nSubject: {req.previous.subject}\n\n{req.previous.body}\n</previous_version>")
            parts.append(
                f"<revision_request>\n{req.revision}\n</revision_request>\n"
                "Rewrite the previous version applying only this change. Keep everything else the same."
            )
        result = self.llm.generate(tier="quality", system=system, user="\n\n".join(parts), schema=Draft)
        self._step(trace, "draft", t, examples=len(examples))
        return result

    def humanize(self, req: MailRequest, subject: str, body: str, issues: list[Issue], trace: list) -> Humanized:
        self.on_step("İnsansılaştırılıyor")
        t = time.perf_counter()
        cards = self._cards(req)
        system = render(
            load_prompt("mail_humanize"),
            sender=self._sender(),
            banned=banned_phrase_list(req.lang, limit=60),
            issues=hints([i for i in issues if i.hard]),
            **cards,
        )
        user = f"<context>\n{req.context.strip()}\n</context>\n\n<draft>\nSubject: {subject}\n\n{body}\n</draft>"
        result = self.llm.generate(tier="quality", system=system, user=user, schema=Humanized)
        self._step(trace, "humanize", t, score=result.scores.total, problems=result.problems)
        return result

    def proofread(self, req: MailRequest, subject: str, body: str, issues: list[Issue], trace: list,
                  min_ratio: float = 0.85) -> tuple[str, str]:
        self.on_step("Yazım kontrolü")
        t = time.perf_counter()
        spelling = [i for i in issues if i.kind == "spelling"]
        system = render(load_prompt(f"mail_proofread_{req.lang}"), hints=hints(spelling))
        user = f"<email>\nSubject: {subject}\n\n{body}\n</email>"
        result = self.llm.generate(tier="fast", system=system, user=user, schema=Proofread)
        # Yazım denetimi sadece hata düzeltmeli; metni yeniden yazdıysa reddet
        ratio = difflib.SequenceMatcher(None, body, result.body).ratio()
        # Kelime düzeyinde de bak: çok hatalı kısa metinde karakter oranı düşer ama kelime sırası aynı kalır
        words_ratio = difflib.SequenceMatcher(None, body.split(), result.body.split()).ratio()
        same_len = 0.9 <= word_count(result.body) / max(1, word_count(body)) <= 1.15
        accepted = same_len and (ratio >= min_ratio or (ratio >= 0.7 and words_ratio >= 0.5))
        self._step(trace, "proofread", t, similarity=round(ratio, 3), accepted=accepted,
                   changes=[f"{c.from_text} → {c.to_text}" for c in result.changes])
        if not accepted:
            return subject, body
        new_body = _keep_lowercase_days(body, result.body) if req.lang == "tr" else result.body
        return (result.subject if subject else subject), new_body

    # ---- seçili metni düzeltme ----
    def fix_text(self, text: str, level: str = "iyilestir", tone: str = "", note: str = "", lang: str = "",
                 recipient: str = "") -> MailResult:
        """Kullanıcının kendi yazdığı metni düzeltir.
        level="yazim": sadece yazım/noktalama (kelimelere dokunmaz); "iyilestir": dili akıcı ve profesyonel yapar."""
        from .style_profile import detect_lang

        trace: list[dict] = []
        lang = lang or detect_lang(text)
        req = MailRequest(context=text, lang=lang)
        body = text.strip()
        if level != "yazim":
            self.on_step("Metin iyileştiriliyor")
            t = time.perf_counter()
            tone_data = self.data["tones"].get(tone) if tone else None
            rec = self.data["recipients"].get(recipient) if recipient else None
            system = render(
                load_prompt("mail_fix"), sender=self._sender(), language_name=LANG_NAMES[lang],
                lang_tr=lang == "tr", tone_label=tone_data["label_en"] if tone_data else "",
                tone_card=tone_data["card"].strip() if tone_data else "", no_tone_card=not tone_data,
                banned=banned_phrase_list(lang, limit=40), style_profile=self.style.profile_text(),
                recipient_label=rec["label_en"] if rec else "", recipient_card=rec["card"].strip() if rec else "",
            )
            user = f"<text>\n{body}\n</text>\n\n<note>\n{note.strip()}\n</note>"
            d = self.llm.generate(tier="quality", system=system, user=user, schema=Draft)
            self._step(trace, "fix", t)
            body = _format_cleanup(d.body.strip())
            notes = d.notes
        else:
            notes = ""
        issues = self._checks("", body, lang)
        _, fixed = self.proofread(req, "", body, issues, trace, min_ratio=0.7 if level == "yazim" else 0.85)
        fixed = _format_cleanup(fixed)
        if lang == "tr":
            fixed = _fix_day_case(fixed)
        if level == "yazim":
            changes = [c for s in trace if s.get("step") == "proofread" for c in s.get("changes", [])]
            notes = f"{len(changes)} yazım/noktalama düzeltmesi" if changes else "Yazım ve noktalama hatası bulunamadı"
        final = [i for i in self._checks("", fixed, lang) if "madde" not in i.message]
        return MailResult(subject="", body=fixed, notes=notes, warnings=final, trace=trace)

    # ---- şablon uyarlama ----
    def adapt_template(self, label: str, subject: str, body: str, note: str, lang: str = "tr") -> MailResult:
        """Sabit şablonu (kullanıcının kendi metni) Gemini ile sadece nota göre uyarlar; humanize gerekmez."""
        trace: list[dict] = []
        self.on_step("Şablon uyarlanıyor")
        t = time.perf_counter()
        system = render(load_prompt("mail_template_adapt"), sender=self._sender(), template_label=label,
                        language_name=LANG_NAMES[lang])
        user = f"<template>\nSubject: {subject}\n\n{body}\n</template>\n\n<note>\n{note.strip()}\n</note>"
        d = self.llm.generate(tier="quality", system=system, user=user, schema=Draft)
        self._step(trace, "adapt", t)
        new_subject = d.subject.strip() or subject
        new_body = _ensure_closing(body, _format_cleanup(d.body.strip()), self._signature())
        closing = [ln for ln in body.rstrip().splitlines()[-2:] if ln.strip()]
        if closing and closing[-1] not in new_body:  # model kapanışı düşürdüyse şablondakini geri koy
            new_body = new_body.rstrip() + "\n\n" + "\n".join(closing)
        req = MailRequest(context=note or body, lang=lang)
        issues = self._checks(new_subject, new_body, lang)
        new_subject, new_body = self.proofread(req, new_subject, new_body, issues, trace)
        new_body = _format_cleanup(new_body)
        if lang == "tr":
            new_body = _fix_day_case(new_body)
        final = [i for i in self._checks(new_subject, new_body, lang) if "madde" not in i.message]
        return MailResult(subject=new_subject, body=new_body, notes=d.notes, warnings=final, trace=trace)

    # ---- ana akış ----
    def run(self, req: MailRequest) -> MailResult:
        trace: list[dict] = []
        d = self.draft(req, trace)
        subject, body = d.subject.strip(), d.body.strip()
        if req.thread and not req.revision:
            subject = ""

        issues = self._checks(subject, body, req.lang)
        trace.append({"step": "checks:draft", "issues": [i.as_hint() for i in issues]})

        scores = None
        max_rounds = int(self.config.mail.get("max_humanize_rounds", 2))
        fast = bool(self.config.mail.get("fast_mode", False))
        hard = [i for i in issues if i.hard and i.kind != "spelling"]
        if not (fast and not hard):
            for round_no in range(max_rounds):
                h = self.humanize(req, subject, body, issues, trace)
                if scores is None:
                    scores = h.scores
                subject = h.subject.strip() if subject else subject
                body = _ensure_closing(body, h.body.strip(), self._signature())
                issues = self._checks(subject, body, req.lang)
                trace.append({"step": f"checks:humanize{round_no + 1}", "issues": [i.as_hint() for i in issues]})
                if not [i for i in issues if i.hard and i.kind != "spelling"]:
                    break

        body = _format_cleanup(body)
        subject, body = self.proofread(req, subject, body, issues, trace)
        body = _tidy_signature(_format_cleanup(body), self._signature())
        if req.lang == "tr":
            body = _fix_day_case(body)
        final = self._checks(subject, body, req.lang) + self._length_issue(body, req)
        trace.append({"step": "checks:final", "issues": [i.as_hint() for i in final]})
        return MailResult(
            subject=subject,
            body=body,
            placeholders=d.placeholders,
            notes=d.notes,
            warnings=final,
            scores=scores,
            trace=trace,
        )
