from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Issue:
    kind: str  # "banned", "format", "rhythm", "spelling", "etiquette"
    message: str
    span: str = ""
    suggestion: str = ""
    hard: bool = True  # hard = düzeltme turu tetikler; soft = sadece uyarı

    def as_hint(self) -> str:
        s = f"- [{self.kind}] {self.message}"
        if self.span:
            s += f' → "{self.span}"'
        if self.suggestion:
            s += f" (öneri: {self.suggestion})"
        return s


def hints(issues: list[Issue]) -> str:
    return "\n".join(i.as_hint() for i in issues)
