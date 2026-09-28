"""Windows açılışında başlatma: Başlangıç klasörüne kısayol koyar/kaldırır (kayıt defterine dokunmaz)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "MailPrompt Asistanı.lnk"
OLD_NAMES = ("PromptGenerator.lnk", "MailPrompt Asistan.lnk")
ICON = ROOT / "app" / "assets" / "app.ico"


def _startup_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _pythonw() -> Path:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def is_enabled() -> bool:
    return (_startup_dir() / NAME).exists() or any((_startup_dir() / n).exists() for n in OLD_NAMES)


def enable() -> None:
    import win32com.client

    shell = win32com.client.Dispatch("WScript.Shell")
    link = shell.CreateShortcut(str(_startup_dir() / NAME))
    link.TargetPath = str(_pythonw())
    link.Arguments = "-m app.main"
    link.WorkingDirectory = str(ROOT)
    link.Description = "MailPrompt Asistanı (Ctrl+Space ile mail ve prompt)"
    if ICON.exists():
        link.IconLocation = str(ICON)
    link.Save()
    for n in OLD_NAMES:  # eski adlı kısayol kalmasın
        (_startup_dir() / n).unlink(missing_ok=True)


def disable() -> None:
    for n in (NAME, *OLD_NAMES):
        (_startup_dir() / n).unlink(missing_ok=True)


def toggle() -> bool:
    if is_enabled():
        disable()
    else:
        enable()
    return is_enabled()
