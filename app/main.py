"""Masaüstü kabuk: arka planda çalışır, kısayola basınca pencereyi imlecin yanında açar.

Çalıştırma:  .venv\\Scripts\\pythonw.exe -m app.main   (ya da PromptGenerator.cmd)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

from app import autostart, winapi  # noqa: E402
from app.bridge import WIDTH, Api  # noqa: E402
from engine.config import load_config  # noqa: E402

WEB = ROOT / "app" / "web" / "index.html"
LOG = ROOT / "user_data" / "app.log"


def log(*parts) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > 1_000_000:  # 1 MB'ı geçerse baştan başla
            LOG.write_text("", encoding="utf-8")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")
    except Exception:
        pass


class Shell:
    def __init__(self):
        self.cfg = load_config()
        combo = self.cfg.hotkey.get("combo", "ctrl+space")
        self.combos = [combo] + [c for c in ("ctrl+shift+space", "ctrl+alt+space") if c != combo]
        self.hotkey_label = combo
        self.captured = ""
        self.prev_hwnd = 0
        self.hwnd = 0
        self.visible = False
        self.height = 300
        self.shown_at = 0.0
        self.ready = threading.Event()
        self.api = Api(self)
        self.window = webview.create_window(
            "PromptGenerator", url=str(WEB), js_api=self.api,
            width=WIDTH, height=self.height, frameless=True, easy_drag=False, on_top=True,
            hidden=True, resizable=False, shadow=True, background_color="#111213", focus=True,
        )
        self.window.events.loaded += self._on_loaded
        self.hotkeys = winapi.HotkeyLoop(self.combos, self.on_hotkey)

    # ---------- pencere ----------
    def _on_loaded(self):
        try:
            self.hwnd = int(self.window.native.Handle.ToInt64())
            winapi.style_window(self.hwnd, dark=True)
            winapi.hide_from_taskbar(self.hwnd)
            # Pencere dışına tıklanınca gizlen (komut paleti davranışı)
            self.window.native.Deactivate += lambda sender, args: self._on_deactivate()
        except Exception as e:
            log("style error", e)
        if self.visible is False:
            self.window.hide()  # bir şey erken gösterdiyse gizli başla
        self.ready.set()

    def _on_deactivate(self) -> None:
        # Gösterimden hemen sonraki geçici odak değişimlerini yok say
        if self.visible and time.time() - self.shown_at > 0.4:
            log("deactivate → hide")
            self.window.hide()
            self.visible = False

    def js(self, code: str) -> None:
        try:
            self.window.evaluate_js(code)
        except Exception as e:
            log("js error", e)

    def resize(self, height: int) -> None:
        height = max(160, min(height, 900))
        if abs(height - self.height) < 2:
            return
        self.height = height
        if self.hwnd:
            winapi.resize_window(self.hwnd, WIDTH, height)  # pywebview resize gizli pencereyi gösteriyor

    def hide(self, restore_focus: bool) -> None:
        log("hide", "restore" if restore_focus else "")
        self.window.hide()
        self.visible = False
        if restore_focus and self.prev_hwnd:
            winapi.force_foreground(self.prev_hwnd)

    def show_at_caret(self) -> None:
        x, y = winapi.anchor_point(self.prev_hwnd)
        scale = winapi.scale_for(x, y)
        px, py = winapi.place_near(x, y, int(WIDTH * scale), int(max(self.height, 420) * scale))
        self.shown_at = time.time()
        self.visible = True
        self.window.move(int(px / scale), int(py / scale))
        self.window.show()
        if self.hwnd:
            winapi.force_foreground(self.hwnd)
        self.js("window.focus(); document.body.focus();")

    # ---------- kısayol ----------
    def on_hotkey(self) -> None:
        if not self.ready.is_set():
            return
        fg = winapi.foreground()
        if self.visible and fg == self.hwnd:
            self.js("window.resetForShow && window.resetForShow('', null, true)")
            return self.hide(restore_focus=True)
        self.prev_hwnd = fg
        self.captured = winapi.copy_selection() if fg and fg != self.hwnd else ""
        log("hotkey", "captured", len(self.captured))
        self.js(f"window.resetForShow && window.resetForShow({json.dumps(self.captured)})")
        self.show_at_caret()

    # ---------- tepsi ----------
    def tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw

            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle((4, 4, 60, 60), radius=16, fill=(113, 112, 255, 255))
            d.polygon([(20, 22), (32, 32), (20, 42)], fill=(255, 255, 255, 255))
            d.rectangle((34, 40, 46, 44), fill=(255, 255, 255, 255))

            def open_(icon, item):
                self.prev_hwnd = winapi.foreground()
                self.captured = ""
                self.js("window.resetForShow && window.resetForShow('')")
                self.show_at_caret()

            def quit_(icon, item):
                icon.stop()
                self.hotkeys.stop()
                self.window.destroy()

            def toggle_autostart(icon, item):
                try:
                    autostart.toggle()
                except Exception as e:
                    log("autostart error", e)

            def open_folder(icon, item):
                os.startfile(str(ROOT))

            menu = pystray.Menu(
                pystray.MenuItem(lambda item: f"Aç ({self.hotkey_label})", open_, default=True),
                pystray.MenuItem("Windows açılışında başlat", toggle_autostart, checked=lambda item: autostart.is_enabled()),
                pystray.MenuItem("Ayarlar klasörünü aç", open_folder),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Çıkış", quit_),
            )
            pystray.Icon("PromptGenerator", img, "PromptGenerator", menu).run_detached()
        except Exception as e:
            log("tray error", e)

    # ---------- başlangıç ----------
    def background(self) -> None:
        self.ready.wait(20)
        self.tray()
        def run_hotkeys():
            try:
                self.hotkeys.run()
            except Exception as e:
                log("hotkey error", e)

        threading.Thread(target=run_hotkeys, daemon=True).start()
        time.sleep(0.3)
        if self.hotkeys.active_combo:
            self.hotkey_label = self.hotkeys.active_combo
            log("hotkey registered", self.hotkey_label)


def main() -> None:
    winapi.set_dpi_aware()
    if not winapi.single_instance():
        print("PromptGenerator zaten çalışıyor.")
        return
    shell = Shell()
    webview.start(shell.background, gui="edgechromium", debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
