"""Windows açılışında başlatma: Başlangıç klasörüne kısayol koyar/kaldırır (kayıt defterine dokunmaz)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "PromptGenerator.lnk"


def _startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _pythonw() -> Path:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def is_enabled() -> bool:
    return (_startup_dir() / NAME).exists()


def enable() -> None:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortcut(str(_startup_dir() / NAME))
    link.TargetPath = str(_pythonw())
    link.Arguments = "-m app.main"
    link.WorkingDirectory = str(ROOT)
    link.Description = "PromptGenerator (Ctrl+Space ile mail ve prompt)"
    link.Save()


def disable() -> None:
    (_startup_dir() / NAME).unlink(missing_ok=True)


def toggle() -> bool:
    if is_enabled():
        disable()
    else:
        enable()
    return is_enabled()
