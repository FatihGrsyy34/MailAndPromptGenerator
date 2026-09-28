"""Kullanıcının gönderdiği gerçek maillerden yazım profili çıkarır ve yeni mail için en benzer örnekleri bulur.

Örnekler user_data/style_samples/ altına konur: .txt/.md dosyasında birden fazla mail varsa aralarına
"---" satırı koyun; .eml dosyaları doğrudan okunur."""
from __future__ import annotations

import email
import hashlib
import json
import math
import re
import statistics
from email import policy
from pathlib import Path

from pydantic import BaseModel

from ..llm import LLMLike
from ..resources import load_prompt
from ..text import sentences, tr_lower, word_count

_SEPARATOR = re.compile(r"^\s*(?:-{3,}|={3,})\s*$", re.M)
_QUOTE_START = re.compile(
    r"^(>|-{2,}\s*(Original Message|Özgün İleti|İlk İleti)|From:|Kimden:|Gönderen:|On .+ wrote:|.+ tarihinde .+ yazdı:)",
    re.I,
)
_TR_HINT = re.compile(r"[çğışöüÇĞİŞÖÜ]|\b(ve|bir|için|merhaba|teşekkür|rica)\b", re.I)


class RecipientHabit(BaseModel):
    recipient_type: str
    examples: list[str]


class StyleProfile(BaseModel):
    summary: str
    greetings: list[RecipientHabit]
    closings: list[RecipientHabit]
    signature: str
    address_form: str
    common_phrases: list[str]
    punctuation_habits: str
    formatting_habits: str
    avoid: list[str]


def detect_lang(text: str) -> str:
    return "tr" if len(_TR_HINT.findall(text)) >= 3 else "en"


def _strip_quoted(text: str) -> str:
    out = []
    for line in text.splitlines():
        if _QUOTE_START.match(line.strip()):
            break
        out.append(line)
    return "\n".join(out).strip()


def _read_eml(path: Path) -> str:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    part = msg.get_body(preferencelist=("plain",))
    return part.get_content() if part else ""


def load_samples(folder: Path) -> list[dict]:
    samples = []
    if not folder.exists():
        return samples
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() == ".eml":
            chunks = [_read_eml(path)]
        elif path.suffix.lower() in {".txt", ".md"}:
            chunks = _SEPARATOR.split(path.read_text(encoding="utf-8", errors="replace"))
            chunks = [c for c in chunks if c and not _SEPARATOR.fullmatch(c)]
        else:
            continue
        for chunk in chunks:
            text = _strip_quoted(chunk)
            if word_count(text) >= 12:
                samples.append({"text": text, "lang": detect_lang(text), "source": path.name})
    return samples


def _stats(samples: list[dict]) -> dict:
    sent_lengths = [word_count(s) for smp in samples for s in sentences(smp["text"])]
    bodies = [word_count(smp["text"]) for smp in samples]
    return {
        "sample_count": len(samples),
        "languages": sorted({s["lang"] for s in samples}),
        "avg_sentence_words": round(statistics.mean(sent_lengths), 1) if sent_lengths else None,
        "avg_email_words": round(statistics.mean(bodies)) if bodies else None,
    }


class StyleStore:
    def __init__(self, user_data: Path):
        self.dir = user_data
        self.samples_dir = user_data / "style_samples"
        self.profile_path = user_data / "style_profile.json"
        self.index_path = user_data / "style_index.json"

    # ---- profil ----
    def build(self, llm: LLMLike, max_samples: int = 40) -> dict:
        samples = load_samples(self.samples_dir)
        if not samples:
            raise FileNotFoundError(f"Örnek mail bulunamadı: {self.samples_dir}")
        picked = samples[:max_samples]
        user = "\n\n".join(f"<sample lang=\"{s['lang']}\">\n{s['text'][:1800]}\n</sample>" for s in picked)
        profile = llm.generate(tier="quality", system=load_prompt("style_analyze"), user=user, schema=StyleProfile)
        data = {"profile": profile.model_dump(), "stats": _stats(samples)}
        self.dir.mkdir(parents=True, exist_ok=True)
        self.profile_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._build_index(llm, samples)
        return data

    def load(self) -> dict | None:
        if not self.profile_path.exists():
            return None
        return json.loads(self.profile_path.read_text(encoding="utf-8"))

    def profile_text(self) -> str:
        # Elle yazılmış/düzenlenmiş profil varsa o kullanılır (mailler hiçbir servise gönderilmeden hazırlanabilir)
        md = self.dir / "style_profile.md"
        if md.exists():
            return md.read_text(encoding="utf-8").strip()
        data = self.load()
        if not data:
            return ""
        p, st = data["profile"], data["stats"]
        lines = [p["summary"]]
        if st.get("avg_sentence_words"):
            lines.append(f"Average sentence length: {st['avg_sentence_words']} words; average email: {st['avg_email_words']} words.")
        for key, title in (("greetings", "Greetings"), ("closings", "Closings")):
            for h in p[key]:
                lines.append(f"{title} ({h['recipient_type']}): " + " | ".join(h["examples"]))
        if p.get("signature"):
            lines.append(f"Signature: {p['signature']}")
        lines.append(f"Address form: {p['address_form']}")
        if p.get("common_phrases"):
            lines.append("Phrases they use: " + " | ".join(p["common_phrases"]))
        lines.append(f"Punctuation: {p['punctuation_habits']}")
        lines.append(f"Formatting: {p['formatting_habits']}")
        if p.get("avoid"):
            lines.append("Never does: " + " | ".join(p["avoid"]))
        return "\n".join(lines)

    # ---- benzer örnek bulma ----
    def _build_index(self, llm: LLMLike, samples: list[dict]) -> None:
        try:
            vecs = llm.embed([s["text"][:2000] for s in samples])
        except Exception:
            vecs = [None] * len(samples)
        index = [
            {"hash": hashlib.sha1(s["text"].encode()).hexdigest()[:12], "lang": s["lang"], "text": s["text"], "vec": v}
            for s, v in zip(samples, vecs)
        ]
        self.index_path.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")

    def similar(self, llm: LLMLike | None, query: str, lang: str, k: int) -> list[str]:
        if k <= 0 or not self.index_path.exists():
            return []
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        pool = [e for e in index if e["lang"] == lang] or index
        qvec = None
        if llm is not None and all(e["vec"] for e in pool):
            try:
                qvec = llm.embed([query[:2000]])[0]
            except Exception:
                qvec = None
        if qvec is not None:
            scored = [(_cosine(qvec, e["vec"]), e["text"]) for e in pool]
        else:
            q = set(tr_lower(query).split())
            scored = [(len(q & set(tr_lower(e["text"]).split())), e["text"]) for e in pool]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:k]]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
