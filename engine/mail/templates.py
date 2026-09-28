"""Sabit mail şablonları: alanları doldurup birebir metin üretir (Gemini yok). İstenirse pipeline'daki
`adapt_template` ile Gemini, şablonu bozmadan sadece kullanıcının notunu işler."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..checks import Issue
from ..checks.slop import check_format
from ..checks.tr_spelling import check_spelling_tr
from ..resources import load_yaml, render


@dataclass
class Filled:
    template_id: str
    subject: str
    body: str
    warnings: list[Issue]


def load_templates() -> dict:
    return load_yaml("mail_templates")


def list_templates() -> list[dict]:
    """Arayüz için: id, etiket, kaynak ve alanlar (ortak alanlar başta)."""
    data = load_templates()
    common = data.get("common_fields", [])
    return [
        {"id": tid, "label": t["label"], "source": t.get("source", "gercek"), "fields": common + t.get("fields", [])}
        for tid, t in data["templates"].items()
    ]


def _greeting(alici: str) -> str:
    alici = alici.strip().rstrip(",")
    if not alici:
        return "Merhaba,"
    if alici.lower().startswith(("merhaba", "günaydın", "selam", "sayın", "değerli")):
        return alici + ","
    return f"Merhaba {alici},"


def _bullets(value: str) -> str:
    lines = [ln.strip().lstrip("-•*").strip() for ln in value.splitlines() if ln.strip()]
    return "\n".join(f"- {ln}" for ln in lines)


def missing_required(template_id: str, values: dict) -> list[str]:
    t = load_templates()["templates"][template_id]
    return [f["label"] for f in t.get("fields", []) if f.get("required") and not str(values.get(f["key"], "")).strip()]


def fill(template_id: str, values: dict) -> Filled:
    data = load_templates()
    t = data["templates"][template_id]
    fields = data.get("common_fields", []) + t.get("fields", [])
    ctx: dict[str, str] = {}
    for f in fields:
        raw = values.get(f["key"], "")
        if f.get("type") == "bool":
            val = "1" if raw in (True, "1", "true", "on", "evet", 1) else ""
        elif f.get("type") == "list":
            val = _bullets(str(raw or ""))
        else:
            val = str(raw or "").strip()
        ctx[f["key"]] = val
        ctx[f"no_{f['key']}"] = "" if val else "1"
    ctx["selam"] = _greeting(ctx.get("alici", ""))
    ctx["kapanis"] = data.get("closing", "").strip()
    subject = render(t["subject"], **ctx).strip()
    body = render(t["body"], **ctx).strip()
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    # Madde listesi şablonda bilinçli tercih: o uyarıyı atla
    warnings = [i for i in check_spelling_tr(body) + check_format(body) if i.hard and "madde" not in i.message]
    return Filled(template_id, subject, body, warnings)
