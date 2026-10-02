"""Ton ve uydurma kontrolü (gerçek Gemini, ~8 çağrı). Ton/selam/kapanış talimatları değişince çalıştırın.

  python evals/tone_check.py

Kontrol edilenler:
  - Düzelt (iyileştir) modunda Resmi ve Samimi çıktılar gerçekten farklı mı?
  - Bağlamda olmayan isim selama girmiş mi? ("Merhaba Ahmet Bey," gibi)
  - Metinde olmayan nezaket cümlesi eklenmiş mi? ("çok seviniriz", "şimdiden teşekkür")
  - Kim ne yapıyor korunmuş mu? (alıcı gönderecekse mail "paylaşıyorum/ekte" dememeli)
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402
from engine.llm import GeminiLLM  # noqa: E402
from engine.mail.pipeline import MailPipeline, MailRequest  # noqa: E402

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

TEXT = ("Sisteme giriş bilgilerini e-posta ile iletebilirsiniz. Şu an bir sorun yok ama güvenlik için "
        "proje tesliminde şifrenizi değiştirmenizi rica edeceğiz.")
ADDED = ["çok sevin", "şimdiden teşekkür", "desteğiniz için"]
REVERSED = ["paylaşıyorum", "ekte", "iletiyorum", "gönderiyorum"]


def greeting(body: str) -> str:
    return next((ln.strip() for ln in body.splitlines() if ln.strip()), "")


def problems(body: str) -> list[str]:
    low = body.lower()
    out = []
    g = greeting(body)
    if re.search(r"\b(bey|hanım)\b", g.lower()) or "[" in g:
        out.append(f"uydurma isim/kalıp selamda: {g!r}")
    out += [f"metinde olmayan ekleme: {p!r}" for p in ADDED if p in low]
    out += [f"kim ne yapıyor değişmiş: {p!r}" for p in REVERSED if re.search(rf"\b{p}", low)]
    tail = [ln.strip() for ln in body.strip().splitlines() if ln.strip()][-3:]
    if sum(ln.endswith(",") and len(ln.split()) <= 4 for ln in tail[-2:]) > 1:
        out.append(f"üst üste iki kapanış: {tail[-2:]}")
    g_words = set(re.findall(r"\w+", g.lower()))
    if tail and {"kolay", "gelsin"} <= g_words and "kolay gelsin" in tail[-1].lower():
        out.append("selam ve kapanış aynı ifadeyi tekrar ediyor")
    return out


def main() -> int:
    cfg = load_config()
    mail = MailPipeline(GeminiLLM(cfg), cfg)
    bodies, failed = {}, 0
    for mode, tone in [("fix", "normal"), ("fix", "resmi"), ("fix", "samimi"), ("new", "resmi"), ("new", "samimi")]:
        if mode == "fix":
            r = mail.fix_text(TEXT, level="iyilestir", tone=tone, recipient="musteri")
        else:
            r = mail.run(MailRequest(context=TEXT, lang="tr", tone=tone, recipient="musteri", length="kisa"))
        bodies[(mode, tone)] = r.body
        issues = problems(r.body)
        failed += bool(issues)
        print(f"\n=== {mode} / {tone} {'OK' if not issues else 'SORUN'}\n{r.body}")
        for i in issues:
            print("  !", i)
    sim = difflib.SequenceMatcher(None, bodies[("fix", "resmi")], bodies[("fix", "samimi")]).ratio()
    print(f"\nDüzelt modunda Resmi ↔ Samimi benzerliği: {sim:.2f} (0.90 üstü = ton etkisiz)")
    failed += sim > 0.9
    print("SONUÇ:", "geçti" if not failed else f"{failed} sorun")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
