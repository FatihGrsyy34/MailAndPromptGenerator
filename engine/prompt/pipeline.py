"""Prompt üretim hattı: analiz → (gerekirse soru) → üretim → doğrulama (+1 onarım)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel

from ..config import Config
from ..llm import LLMLike
from ..resources import load_prompt, load_yaml, render
from ..text import fold

LANG_NAMES = {"tr": "Turkish", "en": "English"}


class Unknown(BaseModel):
    question: str
    why: str
    impact: str  # high | medium | low
    options: list[str]
    default_assumption: str


class Analysis(BaseModel):
    understood: str
    goal: str
    deliverable: str
    audience: str
    verbatim_constraints: list[str]
    literals: list[str]
    implied_needs: list[str]
    unknowns: list[Unknown]
    needs_clarification: bool

    def high_unknowns(self) -> list[Unknown]:
        return [u for u in self.unknowns if u.impact == "high"][:3]


class Generated(BaseModel):
    prompt: str
    understood: str
    assumptions: list[str]


class Review(BaseModel):
    missing_constraints: list[str]
    invented_requirements: list[str]
    format_ok: bool
    detail_ok: bool
    contradictions: list[str]
    self_contained: bool
    verdict: str  # pass | fix
    fix_instructions: list[str]


@dataclass
class PromptRequest:
    idea: str
    task_type: str = "genel"
    target: str = "genel"
    detail: str = "detayli"
    lang: str = "tr"


@dataclass
class PromptResult:
    prompt: str
    understood: str
    assumptions: list[str]
    analysis: Analysis
    review: Review | None = None
    trace: list[dict] = field(default_factory=list)


# Soruları kullanıcıya soran fonksiyon: sorular → {soru: cevap}. Cevaplanmayan soru varsayımla geçer.
AnswerFn = Callable[[list[Unknown]], dict[str, str]]


class PromptPipeline:
    def __init__(self, llm: LLMLike, config: Config):
        self.llm = llm
        self.config = config
        self.opts = load_yaml("prompt_options")
        self.on_step = lambda text: None  # arayüz ilerleme göstersin diye

    def _lang(self, req: PromptRequest) -> str:
        # Midjourney İngilizce promptlarla çok daha iyi çalışır
        return "en" if req.target == "midjourney" else req.lang

    def _options_block(self, req: PromptRequest) -> str:
        return (
            "<options>\n"
            f"task_type: {self.opts['task_types'][req.task_type]['label']}\n"
            f"target: {self.opts['targets'][req.target]['label']}\n"
            f"detail: {self.opts['details'][req.detail]['label']}\n"
            f"output_language: {LANG_NAMES[self._lang(req)]}\n"
            "</options>"
        )

    def analyze(self, req: PromptRequest, trace: list | None = None) -> Analysis:
        self.on_step("İsteğin analiz ediliyor")
        t = time.perf_counter()
        user = f"<idea>\n{req.idea.strip()}\n</idea>\n\n{self._options_block(req)}"
        # Neyin belirsiz olduğuna karar vermek sadakatin temeli: güçlü modelle
        a = self.llm.generate(tier="quality", system=load_prompt("prompt_analyze"), user=user, schema=Analysis)
        if trace is not None:
            trace.append({"step": "analyze", "seconds": round(time.perf_counter() - t, 2),
                          "high_unknowns": [u.question for u in a.high_unknowns()]})
        return a

    @staticmethod
    def default_assumptions(analysis: Analysis, answers: dict[str, str]) -> list[str]:
        # Kritik (high) sorular cevapsız kalırsa tahmin yürütülmez; üretimde yer tutucu kullanılır
        return [u.default_assumption for u in analysis.unknowns
                if u.question not in answers and u.default_assumption and u.impact != "high"]

    @staticmethod
    def unresolved(analysis: Analysis, answers: dict[str, str]) -> list[str]:
        return [u.question for u in analysis.high_unknowns() if u.question not in answers]

    def _context_blocks(self, req: PromptRequest, analysis: Analysis, answers: dict[str, str], assumptions: list[str]) -> str:
        intent = analysis.model_dump(exclude={"unknowns", "needs_clarification"})
        ans = "\n".join(f"- {q} → {a}" for q, a in answers.items()) or "(none)"
        asm = "\n".join(f"- {a}" for a in assumptions) or "(none)"
        unres = "\n".join(f"- {q}" for q in self.unresolved(analysis, answers))
        return (
            (f"<unresolved>\n{unres}\n</unresolved>\n\n" if unres else "")
            + f"<idea>\n{req.idea.strip()}\n</idea>\n\n"
            f"<intent>\n{json.dumps(intent, ensure_ascii=False, indent=1)}\n</intent>\n\n"
            f"<answers>\n{ans}\n</answers>\n\n<assumptions>\n{asm}\n</assumptions>\n\n"
            f"{self._options_block(req)}"
        )

    def _generate_once(self, req: PromptRequest, blocks: str, feedback: str) -> Generated:
        target = self.opts["targets"][req.target]
        template = load_prompt(f"templates/{self.opts['task_types'][req.task_type]['template']}")
        system = render(
            load_prompt("prompt_generate"),
            target_format=target["format"].strip(),
            template=template.strip(),
            budget=self.opts["details"][req.detail]["budget"],
            language_name=LANG_NAMES[self._lang(req)],
            feedback=feedback,
        )
        return self.llm.generate(tier="quality", system=system, user=blocks, schema=Generated)

    def _review(self, req: PromptRequest, blocks: str, prompt: str) -> Review:
        system = render(
            load_prompt("prompt_verify"),
            target_label=self.opts["targets"][req.target]["label"],
            detail_label=self.opts["details"][req.detail]["label"],
        )
        # Doğrulama sadakatin bekçisi: güçlü modelle çalışır (kullanıcının önceliği "tam istediğim olsun")
        tier = "fast" if req.target == "midjourney" else "quality"  # kısa görsel promptta hızlı model yeterli
        return self.llm.generate(tier=tier, system=system, user=f"{blocks}\n\n<prompt>\n{prompt}\n</prompt>", schema=Review)

    @staticmethod
    def missing_literals(analysis: Analysis, prompt: str, lang: str) -> list[str]:
        p = fold(prompt, lang)
        return [lit for lit in analysis.literals if lit.strip() and fold(lit.strip(), lang) not in p]

    def generate(
        self,
        req: PromptRequest,
        analysis: Analysis,
        answers: dict[str, str] | None = None,
        assumptions: list[str] | None = None,
        trace: list | None = None,
    ) -> PromptResult:
        trace = trace if trace is not None else []
        answers = answers or {}
        if assumptions is None:
            assumptions = self.default_assumptions(analysis, answers)
        blocks = self._context_blocks(req, analysis, answers, assumptions)
        lang = self._lang(req)

        self.on_step("Prompt yazılıyor")
        t = time.perf_counter()
        gen = self._generate_once(req, blocks, feedback="")
        trace.append({"step": "generate", "seconds": round(time.perf_counter() - t, 2)})

        self.on_step("İstekle karşılaştırılıyor")
        t = time.perf_counter()
        review = self._review(req, blocks, gen.prompt)
        missing = self.missing_literals(analysis, gen.prompt, lang)
        trace.append({"step": "verify", "seconds": round(time.perf_counter() - t, 2), "verdict": review.verdict,
                      "missing_literals": missing})

        if review.verdict != "pass" or missing:
            feedback = list(review.fix_instructions)
            feedback += [f"Missing constraint: {m}" for m in review.missing_constraints]
            feedback += [f"Remove or list as assumption (user did not ask for it): {r}" for r in review.invented_requirements]
            feedback += [f"Resolve contradiction: {c}" for c in review.contradictions]
            feedback += [f'This literal must appear exactly: "{m}"' for m in missing]
            self.on_step("Eksikler düzeltiliyor")
            t = time.perf_counter()
            gen = self._generate_once(req, blocks, feedback="\n".join(f"- {f}" for f in dict.fromkeys(feedback)))
            trace.append({"step": "repair", "seconds": round(time.perf_counter() - t, 2),
                          "missing_literals_after": self.missing_literals(analysis, gen.prompt, lang)})

        return PromptResult(
            prompt=gen.prompt.strip(),
            understood=gen.understood,
            assumptions=gen.assumptions,
            analysis=analysis,
            review=review,
            trace=trace,
        )

    def run(self, req: PromptRequest, ask: AnswerFn | None = None) -> PromptResult:
        trace: list[dict] = []
        analysis = self.analyze(req, trace)
        answers: dict[str, str] = {}
        questions = analysis.high_unknowns()
        if analysis.needs_clarification and questions and ask is not None:
            answers = {q: a for q, a in ask(questions).items() if a}
        return self.generate(req, analysis, answers, trace=trace)
