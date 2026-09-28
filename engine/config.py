from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYRING_SERVICE = "PromptGenerator"
KEYRING_USER = "gemini_api_key"


@dataclass
class Config:
    models: dict = field(default_factory=dict)
    user: dict = field(default_factory=dict)
    mail: dict = field(default_factory=dict)
    prompt: dict = field(default_factory=dict)
    hotkey: dict = field(default_factory=dict)
    paths: dict = field(default_factory=dict)

    @property
    def user_data(self) -> Path:
        p = Path(self.paths.get("user_data", "user_data"))
        return p if p.is_absolute() else ROOT / p

    def model(self, tier: str) -> str:
        return self.models[tier]

    def thinking(self, tier: str) -> str:
        return self.models.get(f"{tier}_thinking", "") or ""


def load_config(path: Path | None = None) -> Config:
    path = path or ROOT / "config.toml"
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return Config(**{k: data.get(k, {}) for k in Config.__dataclass_fields__})


def get_api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        return key
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def set_api_key(key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
