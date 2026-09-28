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
ICON = ROOT / "app" / "assets" / "app.ico"
TRAY_ICON = ROOT / "app" / "assets" / "tray.png"
APP_NAME = "MailPrompt Asistan"
APP_ID = "Cognera.MailPromptAsistan"  # görev çubuğu bu kimlikle gruplar, Python ikonu yerine uygulamanınki görünür
STARTED = time.time()
TRIM_AFTER = 30.0  # saniye: gizlendikten bu kadar sonra boştaki belleği Windows'a geri ver
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
            APP_NAME, url=str(WEB), js_api=self.api,
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
            self._set_icon()
            self._enable_native_drag()
            # Başka pencereye geçince gizlenmez; sadece "her zaman üstte" kalkar ki diğer pencerelerin arkasına geçsin
            self.window.native.Deactivate += lambda sender, args: self._on_deactivate()
        except Exception as e:
            log("style error", e)
        if self.visible is False:
            self.window.hide()  # bir şey erken gösterdiyse gizli başla
        self.ready.set()

    def _set_icon(self) -> None:
        """Pencere/görev çubuğu/Alt+Tab ikonu: Python yerine uygulamanın kendi ikonu."""
        from System import Action
        from System.Drawing import Icon

        form = self.window.native
        if ICON.exists():
            form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(ICON)))))

    def _set_topmost(self, on: bool) -> None:
        from System import Action

        form = self.window.native
        form.BeginInvoke(Action(lambda: setattr(form, "TopMost", on)))

    def _enable_native_drag(self) -> None:
        from System import Action

        form = self.window.native
        form.Invoke(Action(lambda: setattr(form, "MaximizeBox", False)))  # başlığa çift tıklayınca tam ekran olmasın

    def start_drag(self) -> None:
        """Arayüzde üst/alt çubuğa basılınca çağrılır: Windows'a 'başlık çubuğu tutuldu' der, sürüklemeyi Windows yapar
        (WebView2 içindeki fare olayları pencereyi kendi başına taşıyamıyor)."""
        from System import Action

        def run():
            winapi.begin_native_drag(self.hwnd)

        self.window.native.BeginInvoke(Action(run))

    def _on_deactivate(self) -> None:
        # Alt+Tab ya da başka pencereye tıklama: pencere kapanmaz, yazılanlar kaybolmaz; sadece öne çıkmayı bırakır.
        # Görev çubuğundan, Alt+Tab'dan ya da tekrar Ctrl+Space ile geri gelinir; kapatmak için Esc.
        if self.visible and time.time() - self.shown_at > 0.4:
            self._set_topmost(False)

    # ---------- gizliyken kaynak tasarrufu ----------
    def _webview_idle(self, idle: bool) -> None:
        """Gizliyken WebView2'yi düşük bellek moduna alıp askıya alır; gösterirken geri uyandırır."""
        try:
            from System import Action

            wv = self.window.native.browser.webview

            def run():
                core = wv.CoreWebView2
                if core is None:
                    return
                from Microsoft.Web.WebView2.Core import CoreWebView2MemoryUsageTargetLevel as Level

                if idle:
                    core.MemoryUsageTargetLevel = Level.Low
                    core.TrySuspendAsync()
                else:
                    if core.IsSuspended:
                        core.Resume()
                    core.MemoryUsageTargetLevel = Level.Normal

            self.window.native.Invoke(Action(run))
        except Exception as e:
            log("webview idle error", e)

    def _schedule_idle(self, delay: float = 30.0) -> None:
        def later():
            if not self.visible:
                self._webview_idle(True)

        def trim():
            if not self.visible:
                winapi.trim_memory()

        for d, fn in ((delay, later), (TRIM_AFTER, trim)):
            t = threading.Timer(d, fn)
            t.daemon = True
            t.start()

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
        # Bir sonraki açılış anında olsun diye arayüzü şimdi, pencere gizliyken ilk ekrana döndür
        threading.Thread(target=self.js, args=("window.resetForShow && window.resetForShow('')",), daemon=True).start()
        self._schedule_idle()

    def show_at_caret(self) -> None:
        """Pencereyi imlecin yanında gösterir. JS beklenmez: odak ve açılış animasyonu sonradan tetiklenir."""
        x, y = winapi.anchor_point(self.prev_hwnd)
        scale = winapi.scale_for(x, y)
        px, py = winapi.place_near(x, y, int(WIDTH * scale), int(max(self.height, 420) * scale))
        self.shown_at = time.time()
        self.visible = True
        self._set_topmost(True)
        self.window.move(int(px / scale), int(py / scale))
        self.window.show()
        if self.hwnd:
            winapi.force_foreground(self.hwnd)

    # ---------- kısayol ----------
    def on_hotkey(self) -> None:
        if not self.ready.is_set():
            return
        fg = winapi.foreground()
        if self.visible and fg != self.hwnd:
            # açık ama arkada kalmış: sıfırlamadan öne getir
            self._set_topmost(True)
            winapi.force_foreground(self.hwnd)
            self.js("window.focus()")
            return
        if self.visible and fg == self.hwnd:
            return self.hide(restore_focus=True)
        t0 = time.perf_counter()
        if self.api._llm is None:
            # Gemini motorunu (≈1 sn) kullanıcı seçenekleri seçerken arka planda yükle; boştayken bellekte tutma
            threading.Thread(target=self._prewarm, daemon=True).start()
        self.prev_hwnd = fg
        self._webview_idle(False)  # askıdaysa uyandır
        copying = None
        if fg and fg != self.hwnd:
            copying = winapi.start_copy()  # Ctrl+C hedef uygulamaya gitsin...
            time.sleep(0.04)  # ...tuşlar hedefe ulaşmadan odağı çalmayalım
        t1 = time.perf_counter()
        self.captured = ""
        self.show_at_caret()  # seçim beklenmeden pencere hemen açılır
        t2 = time.perf_counter()
        threading.Thread(target=self._after_show, args=(copying, t0, t1, t2), daemon=True).start()

    def _after_show(self, copying, t0: float, t1: float, t2: float) -> None:
        self.js("window.onShown && window.onShown()")
        t3 = time.perf_counter()
        if copying:
            self.captured = winapi.finish_copy(*copying)
            if self.captured:
                self.js(f"window.setCaptured && window.setCaptured({json.dumps(self.captured)})")
        log(f"hotkey captured={len(self.captured)} copy_send={1000*(t1-t0):.0f}ms visible={1000*(t2-t0):.0f}ms "
            f"ui_ready={1000*(t3-t0):.0f}ms capture_done={1000*(time.perf_counter()-t0):.0f}ms")

    # ---------- tepsi ----------
    def tray(self) -> None:
        try:
            import pystray
            from PIL import Image, ImageDraw

            if TRAY_ICON.exists():
                img = Image.open(TRAY_ICON)
            else:
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                d = ImageDraw.Draw(img)
                d.rounded_rectangle((4, 4, 60, 60), radius=16, fill=(113, 112, 255, 255))

            def open_(icon, item):
                self.prev_hwnd = winapi.foreground()
                self.captured = ""
                self._webview_idle(False)
                self.show_at_caret()
                self.js("window.onShown && window.onShown()")

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
            pystray.Icon("MailPromptAsistan", img, APP_NAME, menu).run_detached()
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
            log(f"hotkey registered {self.hotkey_label} (açılış {time.time() - STARTED:.1f} sn)")
        self._schedule_idle(3.0)  # açılıştan sonra motoru hemen askıya al

    def _prewarm(self) -> None:
        try:
            t = time.perf_counter()
            self.api._engine()
            log(f"motor ön yüklendi ({time.perf_counter() - t:.1f} sn)")
        except Exception as e:  # anahtar yoksa vb.: ilk kullanımda kullanıcıya gösterilir
            log("prewarm skipped", e)


def _install_crash_logging() -> None:
    """pythonw'de konsol yok: beklenmeyen hatalar sessizce kaybolmasın, app.log'a yazılsın."""
    import traceback

    def hook(exc_type, exc, tb):
        log("CRASH", "".join(traceback.format_exception(exc_type, exc, tb))[-2000:])

    sys.excepthook = hook
    threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)


def main() -> None:
    _install_crash_logging()
    # WebView2'nin arka plan ağ trafiği, bileşen güncelleme ve yedek süreç gibi gereksiz işlerini kapat
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", " ".join([
        "--disable-background-networking", "--disable-component-update", "--disable-sync",
        "--no-first-run", "--disable-features=SpareRendererForSitePerProcess,msEdgeSidebarV2,msWebOOUI",
        "--renderer-process-limit=1",
    ]))
    winapi.set_dpi_aware()
    winapi.set_app_id(APP_ID)
    if not winapi.single_instance():
        print("PromptGenerator zaten çalışıyor.")
        return
    shell = Shell()
    webview.start(shell.background, gui="edgechromium", debug="--debug" in sys.argv)


if __name__ == "__main__":
    main()
