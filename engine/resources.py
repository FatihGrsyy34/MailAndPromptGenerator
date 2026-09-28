"""Prompt şablonları ve veri dosyaları. Promptlar .md dosyası olarak durur ki kod değişmeden düzenlenebilsin."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

ENGINE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = ENGINE_DIR / "prompts"
DATA_DIR = ENGINE_DIR / "data"

_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
# {{#if name}} ... {{/if}} bloğu: değişken boşsa blok tamamen düşer
_IF = re.compile(r"\{\{#if (\w+)\}\}(.*?)\{\{/if\}\}", re.S)


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    return yaml.safe_load((DATA_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_lines(name: str) -> tuple[str, ...]:
    """Satır başına bir öğe; boş satırlar ve # yorumları atlanır."""
    out = []
    for line in (DATA_DIR / name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return tuple(out)


def render(template: str, /, **values) -> str:
    """{{name}} yer tutucularını doldurur. str.format değil, çünkü promptlarda süslü parantez bol."""

    def _if(m: re.Match) -> str:
        return m.group(2) if values.get(m.group(1)) else ""

    text = _IF.sub(_if, template)

    def _var(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"Şablon değişkeni eksik: {key}")
        return str(values[key])

    text = _VAR.sub(_var, text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"
