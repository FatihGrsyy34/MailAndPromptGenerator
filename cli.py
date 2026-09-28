"""Motoru terminalden denemek için. Örnekler:

  pg setkey
  pg models
  pg mail "Ahmet Bey'e yarınki demo toplantısını perşembe 14.00'e ertelememiz gerektiğini yaz" --tone kibar --to musteri
  pg mail "teşekkür et, cuma'ya kadar dönüş yapacağımızı söyle" --reply-file gelen.txt
  pg prompt "excel'deki satış verilerinden aylık özet çıkaran python scripti" --type kod --target chatgpt
  pg style build
  pg check taslak.txt --lang tr
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from pathlib import Path

from engine.config import load_config, set_api_key
from engine.resources import load_yaml

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stdin, "reconfigure"):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _llm(cfg):
    from engine.llm import GeminiLLM

    return GeminiLLM(cfg)


def _read(value: str | None) -> str:
    if not value:
        return ""
    if value == "-":
        return sys.stdin.read()
    return Path(value).read_text(encoding="utf-8")


def _print_trace(trace: list[dict]) -> None:
    print("\n--- iz ---", file=sys.stderr)
    for step in trace:
        print(json.dumps(step, ensure_ascii=False), file=sys.stderr)


def cmd_mail(args, cfg) -> None:
    from engine.mail.pipeline import MailPipeline, MailRequest

    req = MailRequest(
        context=args.context or _read(args.context_file),
        lang=args.lang or cfg.mail["default_lang"],
        tone=args.tone or cfg.mail["default_tone"],
        recipient=args.to or cfg.mail["default_recipient"],
        length=args.length or cfg.mail["default_length"],
        thread=_read(args.reply_file),
    )
    pipe = MailPipeline(_llm(cfg), cfg)
    result = pipe.run(req)
    while True:
        print("\n" + result.text + "\n")
        if result.placeholders:
            print(f"Doldurulacak yerler: {', '.join(result.placeholders)}")
        if result.notes:
            print(f"Not: {result.notes}")
        if result.warnings:
            print("Uyarılar:\n" + "\n".join(w.as_hint() for w in result.warnings))
        if args.trace:
            _print_trace(result.trace)
        if not sys.stdin.isatty() or args.no_interactive:
            break
        rev = input("\nDüzeltme isteği (örn. 'daha kısa', 'daha resmi'; boş = bitir): ").strip()
        if not rev:
            break
        req.revision, req.previous = rev, result
        result = pipe.run(req)


def _ask_terminal(questions):
    answers = {}
    print("\nNetleştirmem gereken birkaç nokta var (boş bırakırsan varsayımla devam ederim):")
    for q in questions:
        print(f"\n? {q.question}")
        for i, opt in enumerate(q.options, 1):
            print(f"  {i}) {opt}")
        print(f"  (varsayım: {q.default_assumption})")
        raw = input("> ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(q.options):
            raw = q.options[int(raw) - 1]
        if raw:
            answers[q.question] = raw
    return answers


def cmd_prompt(args, cfg) -> None:
    from engine.prompt.pipeline import PromptPipeline, PromptRequest

    req = PromptRequest(
        idea=args.idea or _read(args.idea_file),
        task_type=args.type,
        target=args.target or cfg.prompt["default_target"],
        detail=args.detail or cfg.prompt["default_detail"],
        lang=args.lang or cfg.prompt["default_lang"],
    )
    pipe = PromptPipeline(_llm(cfg), cfg)
    interactive = sys.stdin.isatty() and not args.no_interactive
    result = pipe.run(req, ask=_ask_terminal if interactive else None)
    while True:
        print(f"\nAnladığım: {result.understood}\n")
        print("=" * 60 + "\n" + result.prompt + "\n" + "=" * 60)
        if result.assumptions:
            print("Varsayımlar:")
            for i, a in enumerate(result.assumptions, 1):
                print(f"  {i}. {a}")
        if args.trace:
            _print_trace(result.trace)
        if not interactive:
            break
        edit = input("\nVarsayım düzelt (örn. '2: hedef kitle yeni başlayanlar', '-1' = 1'i sil; boş = bitir): ").strip()
        if not edit:
            break
        assumptions = list(result.assumptions)
        if edit.startswith("-") and edit[1:].isdigit():
            idx = int(edit[1:]) - 1
            if 0 <= idx < len(assumptions):
                assumptions.pop(idx)
        elif ":" in edit and edit.split(":", 1)[0].strip().isdigit():
            idx, text = edit.split(":", 1)
            idx = int(idx) - 1
            if 0 <= idx < len(assumptions):
                assumptions[idx] = text.strip()
            else:
                assumptions.append(text.strip())
        else:
            assumptions.append(edit)
        result = pipe.generate(req, result.analysis, assumptions=assumptions)


def cmd_style(args, cfg) -> None:
    from engine.mail.style_profile import StyleStore, load_samples

    store = StyleStore(cfg.user_data)
    if args.action == "import-outlook":
        from collections import Counter

        from engine.mail.outlook_import import import_to
        from engine.mail.style_profile import detect_lang

        print(f"Outlook Gönderilmiş Öğeler okunuyor (en fazla {args.count} mail, son {args.months} ay)…")
        path, mails = import_to(store.samples_dir, limit=args.count, months=args.months)
        langs = Counter(detect_lang(m["text"]) for m in mails)
        words = sorted(len(m["text"].split()) for m in mails)
        print(f"{len(mails)} mail kaydedildi: {path}")
        if mails:
            print(f"Dil: {dict(langs)} | kelime (en az/ortanca/en çok): {words[0]}/{words[len(words)//2]}/{words[-1]}"
                  f" | tarih aralığı: {mails[-1]['sent_on']} – {mails[0]['sent_on']}")
        print("Dosyayı açıp paylaşmak istemediğiniz mailleri silebilirsiniz. Sonra: pg style build")
        return
    if args.action == "build":
        n = len(load_samples(store.samples_dir))
        print(f"DİKKAT: {min(n, 40)} örnek mail profil çıkarmak için Gemini'ye gönderilecek (ücretsiz kademede Google içerikleri"
              " ürün geliştirme için kullanabilir). Elle hazırlanmış user_data/style_profile.md varsa zaten o kullanılır.")
        if input("Devam edilsin mi? (e/h): ").strip().lower() not in ("e", "evet", "y", "yes"):
            return
        print(f"{n} örnek mail bulundu ({store.samples_dir}). Profil çıkarılıyor…")
        store.build(_llm(cfg))
        print(store.profile_text())
    else:
        print(store.profile_text() or f"Profil yok. Örnekleri {store.samples_dir} klasörüne koyup `pg style build` çalıştırın.")


def cmd_check(args, cfg) -> None:
    from engine.checks.slop import check_mail
    from engine.checks.tr_spelling import check_spelling_tr

    text = _read(args.file)
    issues = check_mail("", text, args.lang)
    if args.lang == "tr":
        issues += check_spelling_tr(text, [cfg.user.get("company", "")])
    print("\n".join(i.as_hint() for i in issues) or "Sorun bulunamadı.")


# Eski biçim "AIza..." (39 karakter); yeni biçimler nokta içerebilir ve daha uzun olabilir.
_KEY_RE = re.compile(r"^[A-Za-z0-9_.\-]{30,200}$")


def _clipboard_text() -> str:
    try:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT) or ""
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return ""


def cmd_setkey(cfg) -> None:
    # Gizli girişte Ctrl+V bazı terminallerde metni değil ^V karakterini (0x16) gönderiyor;
    # bu yüzden kontrol karakterlerini atıp, geçersizse panodaki anahtarı kullanıyoruz.
    print("Anahtarı panoya kopyaladıysanız sadece Enter'a basın; ya da yapıştırıp Enter'a basın.")
    typed = "".join(c for c in getpass.getpass("Gemini API anahtarı: ") if c.isprintable()).strip()
    key = typed if _KEY_RE.match(typed) else _clipboard_text().strip()
    if not _KEY_RE.match(key):
        sys.exit("Geçerli bir anahtar bulunamadı. Anahtarı Google AI Studio'dan kopyalayıp `pg setkey` çalıştırın, sonra sadece Enter'a basın.")
    source = "yazılan" if key == typed else "panodaki"
    from engine.llm import GeminiLLM

    try:
        count = len(GeminiLLM(cfg, api_key=key).list_models())
    except Exception as e:
        sys.exit(f"Anahtar ({source}, {len(key)} karakter) Gemini tarafından kabul edilmedi: {str(e)[:200]}")
    set_api_key(key)
    print(f"Kaydedildi ({source} anahtar, {len(key)} karakter). Gemini'ye bağlandı, {count} model erişilebilir.")


def main(argv: list[str] | None = None) -> None:
    cfg = load_config()
    opts = load_yaml("prompt_options")
    tones = load_yaml("tones")
    ap = argparse.ArgumentParser(prog="pg", description="Mail ve prompt üretici")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("mail", help="mail üret")
    m.add_argument("context", nargs="?", help="ne yazılacağı (kısa bağlam)")
    m.add_argument("--context-file")
    m.add_argument("--reply-file", help="yanıtlanacak gelen mail (dosya ya da - = stdin)")
    m.add_argument("--lang", choices=["tr", "en"])
    m.add_argument("--tone", choices=list(tones["tones"]))
    m.add_argument("--to", choices=list(tones["recipients"]), help="alıcı türü")
    m.add_argument("--length", choices=list(tones["lengths"]))
    m.add_argument("--trace", action="store_true", help="adım adım izi göster")
    m.add_argument("--no-interactive", action="store_true")

    p = sub.add_parser("prompt", help="prompt üret")
    p.add_argument("idea", nargs="?", help="ne istediğin")
    p.add_argument("--idea-file")
    p.add_argument("--type", choices=list(opts["task_types"]), default="genel")
    p.add_argument("--target", choices=list(opts["targets"]))
    p.add_argument("--detail", choices=list(opts["details"]))
    p.add_argument("--lang", choices=["tr", "en"], help="promptun dili")
    p.add_argument("--trace", action="store_true")
    p.add_argument("--no-interactive", action="store_true")

    s = sub.add_parser("style", help="stil profili")
    s.add_argument("action", choices=["import-outlook", "build", "show"])
    s.add_argument("--count", type=int, default=60, help="import-outlook: en fazla kaç mail")
    s.add_argument("--months", type=int, default=12, help="import-outlook: son kaç ay")

    c = sub.add_parser("check", help="metni otomatik kontrollerden geçir (LLM'siz)")
    c.add_argument("file", help="dosya ya da - (stdin)")
    c.add_argument("--lang", choices=["tr", "en"], default="tr")

    sub.add_parser("setkey", help="Gemini API anahtarını kaydet")
    sub.add_parser("models", help="erişilebilen Gemini modellerini listele")

    args = ap.parse_args(argv)
    if args.cmd == "setkey":
        cmd_setkey(cfg)
    elif args.cmd == "models":
        print("\n".join(_llm(cfg).list_models()))
    elif args.cmd == "mail":
        cmd_mail(args, cfg)
    elif args.cmd == "prompt":
        cmd_prompt(args, cfg)
    elif args.cmd == "style":
        cmd_style(args, cfg)
    elif args.cmd == "check":
        cmd_check(args, cfg)


if __name__ == "__main__":
    from engine.llm import LLMError

    try:
        main()
    except LLMError as e:
        sys.exit(f"Hata: {e}")
    except KeyboardInterrupt:
        sys.exit(130)
