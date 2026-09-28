"""Eval seti: her prompt değişikliğinden sonra çalıştırın, puanlar bir önceki çalıştırmayla karşılaştırılır.

  python evals/run_evals.py            # hepsi
  python evals/run_evals.py mail       # sadece mail
  python evals/run_evals.py prompt --only kod-excel-ozet
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.config import load_config  # noqa: E402
from engine.llm import GeminiLLM  # noqa: E402
from engine.mail.pipeline import MailPipeline, MailRequest  # noqa: E402
from engine.prompt.pipeline import PromptPipeline, PromptRequest  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except Exception:
        pass


class MailJudgement(BaseModel):
    directness: int
    rhythm: int
    trust: int
    authenticity: int
    density: int
    tone_match: int
    recipient_fit: int
    fidelity: int
    language_quality: int
    language_errors: list[str]
    ai_suspect: bool
    ai_suspect_reason: str


class PromptJudgement(BaseModel):
    fidelity: int
    target_fit: int
    detail_fit: int
    usefulness: int
    missing: list[str]
    invented: list[str]


def _cases(name: str, only: str | None) -> list[dict]:
    rows = [json.loads(line) for line in (HERE / name).read_text(encoding="utf-8").splitlines() if line.strip()]
    wanted = set(only.split(",")) if only else None
    return [r for r in rows if not wanted or r["id"] in wanted]


def eval_mail(case: dict, cfg, llm) -> dict:
    start = time.perf_counter()
    req = MailRequest(context=case["context"], lang=case["lang"], tone=case["tone"], recipient=case["recipient"],
                      length=case["length"], thread=case.get("thread", ""))
    res = MailPipeline(llm, cfg).run(req)
    seconds = round(time.perf_counter() - start, 1)
    request = json.dumps({k: v for k, v in case.items() if k != "id"}, ensure_ascii=False, indent=1)
    j = llm.generate(tier="quality", system=(HERE / "judge_mail.md").read_text(encoding="utf-8"),
                     user=f"<request>\n{request}\n</request>\n\n<email>\n{res.text}\n</email>", schema=MailJudgement)
    slop = j.directness + j.rhythm + j.trust + j.authenticity + j.density
    return {
        "id": case["id"], "seconds": seconds, "text": res.text,
        "hard_warnings": [w.as_hint() for w in res.warnings if w.hard],
        "slop_score": slop, "judge": j.model_dump(),
        "pipeline_first_score": res.scores.total if res.scores else None,
    }


def eval_prompt(case: dict, cfg, llm) -> dict:
    start = time.perf_counter()
    req = PromptRequest(idea=case["idea"], task_type=case["task_type"], target=case["target"],
                        detail=case["detail"], lang=case["lang"])
    pipe = PromptPipeline(llm, cfg)
    res = pipe.run(req, ask=None)
    seconds = round(time.perf_counter() - start, 1)
    asked = bool(res.analysis.needs_clarification and res.analysis.high_unknowns())
    blocks = (f"<idea>\n{case['idea']}\n</idea>\n<options>{json.dumps({k: case[k] for k in ('task_type', 'target', 'detail', 'lang')})}</options>\n"
              f"<assumptions>\n" + "\n".join(res.assumptions) + f"\n</assumptions>\n<prompt>\n{res.prompt}\n</prompt>")
    j = llm.generate(tier="quality", system=(HERE / "judge_prompt.md").read_text(encoding="utf-8"), user=blocks, schema=PromptJudgement)
    return {
        "id": case["id"], "seconds": seconds, "prompt": res.prompt, "understood": res.understood,
        "assumptions": res.assumptions, "asked_questions": asked,
        "questions": [u.question for u in res.analysis.high_unknowns()],
        "question_expectation_met": asked == bool(case.get("expect_questions", False)),
        "missing_literals": pipe.missing_literals(res.analysis, res.prompt, "tr"),
        "judge": j.model_dump(),
    }


def _summary(kind: str, rows: list[dict]) -> dict:
    ok = [r for r in rows if "error" not in r]
    if not ok:
        return {"cases": len(rows), "errors": len(rows)}
    avg = lambda f: round(statistics.mean(f(r) for r in ok), 2)  # noqa: E731
    s = {"cases": len(rows), "errors": len(rows) - len(ok), "avg_seconds": avg(lambda r: r["seconds"])}
    if kind == "mail":
        s |= {
            "slop_score_/50": avg(lambda r: r["slop_score"]),
            "fidelity": avg(lambda r: r["judge"]["fidelity"]),
            "tone_match": avg(lambda r: r["judge"]["tone_match"]),
            "language_quality": avg(lambda r: r["judge"]["language_quality"]),
            "ai_suspect_rate": avg(lambda r: 1 if r["judge"]["ai_suspect"] else 0),
            "cases_with_hard_warnings": sum(1 for r in ok if r["hard_warnings"]),
        }
    else:
        s |= {
            "fidelity": avg(lambda r: r["judge"]["fidelity"]),
            "target_fit": avg(lambda r: r["judge"]["target_fit"]),
            "detail_fit": avg(lambda r: r["judge"]["detail_fit"]),
            "usefulness": avg(lambda r: r["judge"]["usefulness"]),
            "question_expectation_met": avg(lambda r: 1 if r["question_expectation_met"] else 0),
            "cases_missing_literals": sum(1 for r in ok if r["missing_literals"]),
        }
    return s


def _previous() -> dict | None:
    if not RESULTS.exists():
        return None
    files = sorted(RESULTS.glob("*.json"))
    return json.loads(files[-1].read_text(encoding="utf-8")) if files else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", nargs="?", choices=["mail", "prompt", "all"], default="all")
    ap.add_argument("--only", help="virgülle ayrılmış vaka id leri")
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    cfg = load_config()
    llm = GeminiLLM(cfg)
    prev = _previous()
    out: dict = {"models": cfg.models, "summary": {}, "results": {}}

    jobs = []
    if args.kind in ("mail", "all"):
        jobs.append(("mail", _cases("mail_cases.jsonl", args.only), eval_mail))
    if args.kind in ("prompt", "all"):
        jobs.append(("prompt", _cases("prompt_cases.jsonl", args.only), eval_prompt))

    for kind, cases, fn in jobs:
        def safe(case, fn=fn):
            try:
                return fn(case, cfg, llm)
            except Exception as e:  # tek vaka hatası tüm eval'i durdurmasın
                return {"id": case["id"], "error": str(e)}

        with ThreadPoolExecutor(args.workers) as ex:
            rows = list(ex.map(safe, cases))
        out["results"][kind] = rows
        out["summary"][kind] = _summary(kind, rows)

    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    for kind, s in out["summary"].items():
        print(f"\n== {kind} ==")
        before = (prev or {}).get("summary", {}).get(kind, {})
        for k, v in s.items():
            delta = ""
            if isinstance(v, (int, float)) and isinstance(before.get(k), (int, float)):
                d = v - before[k]
                delta = f"  ({'+' if d >= 0 else ''}{d:.2f})"
            print(f"  {k:28} {v}{delta}")
    print(f"\nAyrıntılar: {path}")


if __name__ == "__main__":
    main()
