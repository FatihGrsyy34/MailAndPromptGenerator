"""JS ↔ Python köprüsü. pywebview bu sınıfın alt çizgisiz metodlarını `window.pywebview.api` olarak açar.
Nesneleri alt çizgili alanlarda tutuyoruz ki pywebview onları JS'e serileştirmeye çalışmasın."""
from __future__ import annotations

import json
import threading
import time

from engine.config import load_config
from engine.resources import load_yaml

from . import winapi

WIDTH = 640 + 2  # pencere genişliği (mantıksal piksel); +2 DWM kenarı için


def _short(label: str) -> str:
    return label.split(" / ")[0].split(" (")[0]


class Api:
    def __init__(self, shell):
        self._shell = shell  # main.Shell: pencere, önceki odak vs.
        self._cfg = load_config()
        self._mail = None
        self._prompt = None
        self._llm = None
        self._last_mail_req = None
        self._last_mail_res = None
        self._p_req = None
        self._p_analysis = None
        self._p_answers: dict = {}
        self._lock = threading.Lock()

    # ---------- yardımcılar ----------
    def _progress(self, text: str) -> None:
        self._shell.js(f"window.onProgress && window.onProgress({json.dumps(text)})")

    def _engine(self):
        with self._lock:
            if self._llm is None:
                from engine.llm import GeminiLLM
                from engine.mail.pipeline import MailPipeline
                from engine.prompt.pipeline import PromptPipeline

                self._llm = GeminiLLM(self._cfg)
                self._mail = MailPipeline(self._llm, self._cfg)
                self._prompt = PromptPipeline(self._llm, self._cfg)
                self._mail.on_step = self._progress
                self._prompt.on_step = self._progress
        return self._mail, self._prompt

    def _prefs_path(self):
        return self._cfg.user_data / "ui_state.json"

    # ---------- JS'in çağırdıkları ----------
    def init(self):
        tones = load_yaml("tones")
        opts = load_yaml("prompt_options")
        options = {
            "tone": [[k, _short(v["label"])] for k, v in tones["tones"].items()],
            "recipient": [[k, _short(v["label"])] for k, v in tones["recipients"].items()],
            "length": [[k, v["label"]] for k, v in tones["lengths"].items()],
            "lang": [["tr", "TR"], ["en", "EN"]],
            "task": [[k, _short(v["label"])] for k, v in opts["task_types"].items()],
            "target": [[k, _short(v["label"])] for k, v in opts["targets"].items()],
            "detail": [[k, v["label"]] for k, v in opts["details"].items()],
            "plang": [["tr", "TR"], ["en", "EN"]],
        }
        m, p = self._cfg.mail, self._cfg.prompt
        defaults = {"tone": m["default_tone"], "recipient": m["default_recipient"], "length": m["default_length"],
                    "lang": m["default_lang"], "target": p["default_target"], "detail": p["default_detail"],
                    "plang": p["default_lang"]}
        try:
            defaults.update(json.loads(self._prefs_path().read_text(encoding="utf-8")))
        except Exception:
            pass
        from engine.mail.templates import list_templates

        return {"options": options, "defaults": defaults, "captured": self._shell.captured,
                "hotkey": self._shell.hotkey_label, "templates": list_templates()}

    def save_prefs(self, sel):
        try:
            self._prefs_path().parent.mkdir(parents=True, exist_ok=True)
            self._prefs_path().write_text(json.dumps(sel, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def generate_mail(self, p):
        from engine.mail.pipeline import MailRequest

        mail, _ = self._engine()
        if p.get("revision"):
            if not self._last_mail_req:
                raise RuntimeError("Düzeltilecek bir mail yok")
            req = self._last_mail_req
            req.revision, req.previous = p["revision"], self._last_mail_res
        else:
            req = MailRequest(context=p["context"], lang=p["lang"], tone=p["tone"], recipient=p["recipient"],
                              length=p["length"], thread=p.get("thread", "") if p.get("reply") else "")
        res = mail.run(req)
        self._last_mail_req, self._last_mail_res = req, res
        return {
            "subject": res.subject, "body": res.body, "placeholders": res.placeholders, "notes": res.notes,
            "score": res.scores.total if res.scores else None,
            "warnings": [{"kind": w.kind, "message": w.message, "span": w.span, "hard": w.hard} for w in res.warnings],
        }

    @staticmethod
    def _warnings(ws):
        return [{"kind": w.kind, "message": w.message, "span": w.span, "hard": w.hard} for w in ws]

    def fix_text(self, p):
        """Seçili metni düzeltir: level 'yazim' (sadece yazım/noktalama) ya da 'iyilestir'."""
        mail, _ = self._engine()
        text = (p.get("text") or self._shell.captured or "").strip()
        if not text:
            raise RuntimeError("Düzeltilecek metin yok. Metni seçip Ctrl+Space'e basın.")
        r = mail.fix_text(text, level=p.get("level", "iyilestir"), tone=p.get("tone", ""), note=p.get("note", ""),
                          recipient=p.get("recipient", ""))  # dil metinden otomatik algılanır
        return {"subject": "", "body": r.body, "warnings": self._warnings(r.warnings), "notes": r.notes}

    def template_fill(self, p):
        """Birebir doldurma: Gemini'ye gitmez, anında döner."""
        from engine.mail.templates import fill, missing_required

        missing = missing_required(p["id"], p.get("values") or {})
        if missing:
            raise RuntimeError("Zorunlu alan eksik: " + ", ".join(missing))
        f = fill(p["id"], p.get("values") or {})
        return {"subject": f.subject, "body": f.body, "warnings": self._warnings(f.warnings), "notes": ""}

    def template_adapt(self, p):
        from engine.mail.templates import fill, load_templates

        mail, _ = self._engine()
        f = fill(p["id"], p.get("values") or {})
        label = load_templates()["templates"][p["id"]]["label"]
        r = mail.adapt_template(label, f.subject, f.body, p.get("note", ""))
        return {"subject": r.subject, "body": r.body, "warnings": self._warnings(r.warnings), "notes": r.notes}

    def _prompt_result(self, r):
        return {"prompt": r.prompt, "understood": r.understood, "assumptions": r.assumptions}

    def prompt_start(self, p):
        from engine.prompt.pipeline import PromptRequest

        _, prompt = self._engine()
        self._p_req = PromptRequest(idea=p["idea"], task_type=p["task_type"], target=p["target"],
                                    detail=p["detail"], lang=p["lang"])
        self._p_answers = {}
        self._p_analysis = prompt.analyze(self._p_req)
        qs = self._p_analysis.high_unknowns()
        if self._p_analysis.needs_clarification and qs:
            return {"questions": [{"question": q.question, "options": q.options, "default": q.default_assumption} for q in qs]}
        return self._prompt_result(prompt.generate(self._p_req, self._p_analysis))

    def prompt_finish(self, p):
        _, prompt = self._engine()
        self._p_answers = {k: v for k, v in (p.get("answers") or {}).items() if v}
        return self._prompt_result(prompt.generate(self._p_req, self._p_analysis, self._p_answers))

    def prompt_regenerate(self, p):
        _, prompt = self._engine()
        return self._prompt_result(prompt.generate(self._p_req, self._p_analysis, self._p_answers, assumptions=p.get("assumptions")))

    def paste(self, text):
        self._shell.hide(restore_focus=True)
        time.sleep(0.06)
        winapi.paste_text(text)
        return True

    def copy(self, text):
        winapi.set_clipboard_text(text)
        return True

    def close(self):
        self._shell.hide(restore_focus=True)
        return True

    def start_drag(self):
        self._shell.start_drag()
        return True

    def resize(self, height):
        self._shell.resize(int(height))
        return True
