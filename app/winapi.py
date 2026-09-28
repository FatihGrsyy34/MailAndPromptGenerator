"""Windows tesisatı: global kısayol, ön plandaki pencere, pano, tuş gönderme, imleç konumu.
Hepsi ctypes/pywin32 ile; ek bir hook kütüphanesi yok (RegisterHotKey en güvenilir yol)."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)

# ---------- imzalar (64-bit'te HWND kırpılmasın diye) ----------
u32.GetForegroundWindow.restype = wintypes.HWND
u32.SetForegroundWindow.argtypes = [wintypes.HWND]
u32.BringWindowToTop.argtypes = [wintypes.HWND]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
u32.GetWindowThreadProcessId.restype = wintypes.DWORD
u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
u32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.GetAsyncKeyState.argtypes = [ctypes.c_int]
u32.GetAsyncKeyState.restype = ctypes.c_short
u32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
u32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
u32.MonitorFromPoint.restype = wintypes.HANDLE
u32.GetClipboardSequenceNumber.restype = wintypes.DWORD
u32.IsWindow.argtypes = [wintypes.HWND]
u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u32.IsIconic.argtypes = [wintypes.HWND]
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
k32.CreateMutexW.restype = wintypes.HANDLE

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
VK = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "insert": 0x2D, **{f"f{i}": 0x6F + i for i in range(1, 13)}}
VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN, VK_SPACE = 0x11, 0x10, 0x12, 0x5B, 0x5C, 0x20


def set_dpi_aware() -> None:
    try:
        u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    except Exception:
        pass


def set_app_id(app_id: str) -> None:
    """Görev çubuğu penceresini pythonw.exe'ye değil bu uygulama kimliğine bağlar (kendi ikonu görünür)."""
    try:
        ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(app_id))
    except Exception:
        pass


def single_instance(name: str = "PromptGenerator.SingleInstance") -> bool:
    k32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


# ---------- kısayol ----------
def parse_hotkey(combo: str) -> tuple[int, int]:
    mods, vk = MOD_NOREPEAT, None
    for part in combo.lower().replace(" ", "").split("+"):
        if part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part == "shift":
            mods |= MOD_SHIFT
        elif part == "alt":
            mods |= MOD_ALT
        elif part == "win":
            mods |= MOD_WIN
        elif part in VK:
            vk = VK[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            raise ValueError(f"Tanınmayan tuş: {part}")
    if vk is None:
        raise ValueError(f"Kısayolda ana tuş yok: {combo}")
    return mods, vk


class HotkeyLoop:
    """Kendi thread'inde çalışır; WM_HOTKEY gelince callback çağrılır."""

    def __init__(self, combos: list[str], on_fire):
        self.combos = combos
        self.on_fire = on_fire
        self.thread_id = 0
        self.active_combo: str | None = None

    def run(self) -> None:
        self.thread_id = k32.GetCurrentThreadId()
        for combo in self.combos:
            mods, vk = parse_hotkey(combo)
            if u32.RegisterHotKey(None, 1, mods, vk):
                self.active_combo = combo
                break
        if not self.active_combo:
            raise OSError(f"Kısayol alınamadı (başka bir uygulama kullanıyor olabilir): {', '.join(self.combos)}")
        msg = wintypes.MSG()
        try:
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.on_fire()
                    except Exception as e:  # kısayol döngüsü asla ölmesin
                        print("hotkey handler error:", e)
        finally:
            u32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        if self.thread_id:
            u32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


# ---------- tuş gönderme ----------
class _KI(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ki", _KI), ("_pad", ctypes.c_ubyte * 8)]


KEYEVENTF_KEYUP = 0x2


def _send(*events: tuple[int, bool]) -> None:
    arr = (_INPUT * len(events))(*[_INPUT(1, _KI(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)) for vk, up in events])
    u32.SendInput(len(events), arr, ctypes.sizeof(_INPUT))


def wait_modifiers_released(timeout: float = 0.6) -> None:
    """Kısayola basan kullanıcı Ctrl/Space'i hâlâ basılı tutuyor olabilir; bırakmasını bekle, olmazsa bırak."""
    keys = (VK_CONTROL, VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN, VK_SPACE)
    end = time.time() + timeout
    while time.time() < end:
        if not any(u32.GetAsyncKeyState(k) & 0x8000 for k in keys):
            return
        time.sleep(0.02)
    for k in keys:
        if k != VK_MENU and u32.GetAsyncKeyState(k) & 0x8000:  # tek başına Alt bırakmak menüyü açar
            _send((k, True))


def chord(letter: str) -> None:
    vk = ord(letter.upper())
    _send((VK_CONTROL, False), (vk, False), (vk, True), (VK_CONTROL, True))


# ---------- pencere odağı ----------
def foreground() -> int:
    return u32.GetForegroundWindow() or 0


def force_foreground(hwnd: int) -> bool:
    if not hwnd or not u32.IsWindow(hwnd):
        return False
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    fg = u32.GetForegroundWindow()
    tgt = u32.GetWindowThreadProcessId(fg, None)
    me = k32.GetCurrentThreadId()
    attached = bool(tgt and tgt != me and u32.AttachThreadInput(me, tgt, True))
    try:
        u32.SetForegroundWindow(hwnd)
        u32.BringWindowToTop(hwnd)
    finally:
        if attached:
            u32.AttachThreadInput(me, tgt, False)
    for _ in range(30):
        if u32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.01)
    return u32.GetForegroundWindow() == hwnd


# ---------- pano ----------
def _open_clipboard(retries: int = 10) -> bool:
    import win32clipboard

    for _ in range(retries):
        try:
            win32clipboard.OpenClipboard()
            return True
        except Exception:
            time.sleep(0.03)
    return False


def get_clipboard_text() -> str | None:
    import win32clipboard

    if not _open_clipboard():
        return None
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
        return None
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard_text(text: str | None, private: bool = False) -> None:
    """private=True: Win+V geçmişine ve bulut senkronuna düşmesin (geçici metinler için)."""
    import win32clipboard

    if not _open_clipboard():
        return
    try:
        win32clipboard.EmptyClipboard()
        if text is not None:
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
            if private:
                for fmt in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory"):
                    f = win32clipboard.RegisterClipboardFormat(fmt)
                    win32clipboard.SetClipboardData(f, b"\x00\x00\x00\x00")
    finally:
        win32clipboard.CloseClipboard()


def start_copy() -> tuple[str | None, int]:
    """Aktif uygulamaya Ctrl+C gönderir ve hemen döner; sonucu finish_copy bekler (pencere bu arada açılabilir)."""
    saved = get_clipboard_text()
    before = u32.GetClipboardSequenceNumber()
    wait_modifiers_released()
    chord("c")
    return saved, before


def finish_copy(saved: str | None, before: int, timeout: float = 0.3) -> str:
    """Pano değiştiyse seçili metni döndürür (değişmediyse seçim yok) ve panoyu eski haline getirir."""
    end = time.time() + timeout
    while time.time() < end:
        if u32.GetClipboardSequenceNumber() != before:
            time.sleep(0.03)
            text = get_clipboard_text() or ""
            set_clipboard_text(saved)
            return text.strip()
        time.sleep(0.01)
    return ""


def copy_selection(timeout: float = 0.3) -> str:
    saved, before = start_copy()
    return finish_copy(saved, before, timeout)


def paste_text(text: str, restore_delay: float = 0.5) -> None:
    saved = get_clipboard_text()
    set_clipboard_text(text, private=True)
    wait_modifiers_released()
    time.sleep(0.03)
    chord("v")
    time.sleep(restore_delay)
    set_clipboard_text(saved)


# ---------- konum ----------
class _GTI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND), ("hwndCapture", wintypes.HWND),
                ("hwndMenuOwner", wintypes.HWND), ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def anchor_point(hwnd: int) -> tuple[int, int]:
    """Metin imlecinin (caret) ekran konumu; bulunamazsa fare konumu. Fiziksel piksel."""
    pt = wintypes.POINT()
    gti = _GTI(cbSize=ctypes.sizeof(_GTI))
    tid = u32.GetWindowThreadProcessId(hwnd, None) if hwnd else 0
    if tid and u32.GetGUIThreadInfo(tid, ctypes.byref(gti)) and gti.hwndCaret:
        pt.x, pt.y = gti.rcCaret.left, gti.rcCaret.bottom
        u32.ClientToScreen(gti.hwndCaret, ctypes.byref(pt))
        if pt.x or pt.y:
            return pt.x, pt.y
    u32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def work_area(x: int, y: int) -> tuple[int, int, int, int]:
    mon = u32.MonitorFromPoint(wintypes.POINT(x, y), 2)  # MONITOR_DEFAULTTONEAREST
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    u32.GetMonitorInfoW(mon, ctypes.byref(mi))
    r = mi.rcWork
    return r.left, r.top, r.right, r.bottom


def scale_for(x: int, y: int) -> float:
    try:
        shcore = ctypes.WinDLL("shcore")
        mon = u32.MonitorFromPoint(wintypes.POINT(x, y), 2)
        dx, dy = wintypes.UINT(), wintypes.UINT()
        shcore.GetDpiForMonitor(mon, 0, ctypes.byref(dx), ctypes.byref(dy))
        return dx.value / 96.0
    except Exception:
        return 1.0


def place_near(x: int, y: int, w: int, h: int) -> tuple[int, int]:
    """Pencereyi imlecin hemen altına, ekrana sığacak şekilde yerleştir (fiziksel piksel)."""
    left, top, right, bottom = work_area(x, y)
    px, py = x - 24, y + 12
    if py + h > bottom:
        py = max(top, y - h - 16)
    px = min(max(left + 8, px), right - w - 8)
    py = min(max(top + 8, py), bottom - h - 8)
    return px, py


# ---------- pencere boyutu / görev çubuğu ----------
SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x2, 0x4, 0x10, 0x20
GWL_EXSTYLE, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = -20, 0x80, 0x40000


def window_scale(hwnd: int) -> float:
    try:
        return u32.GetDpiForWindow(wintypes.HWND(hwnd)) / 96.0 or 1.0
    except Exception:
        return 1.0


def resize_window(hwnd: int, width: int, height: int) -> None:
    """Pencereyi GÖSTERMEDEN boyutlandırır (pywebview'in resize'ı SWP_SHOWWINDOW kullanıp gizli pencereyi açıyor)."""
    s = window_scale(hwnd)
    u32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, int(width * s), int(height * s),
                     SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)


def hide_from_taskbar(hwnd: int) -> None:
    """Görev çubuğunda ve Alt+Tab'da görünmesin (tepsi ikonu yeterli)."""
    h = wintypes.HWND(hwnd)
    ex = u32.GetWindowLongW(h, GWL_EXSTYLE)
    u32.SetWindowLongW(h, GWL_EXSTYLE, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
    u32.SetWindowPos(h, None, 0, 0, 0, 0, SWP_NOMOVE | 0x1 | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)


def begin_native_drag(hwnd: int) -> None:
    """Fare basılıyken pencerenin Windows'un kendi taşıma döngüsüne girmesini sağlar (başlık çubuğundan tutmak gibi)."""
    pt = wintypes.POINT()
    u32.GetCursorPos(ctypes.byref(pt))
    u32.ReleaseCapture()
    lparam = (pt.y & 0xFFFF) << 16 | (pt.x & 0xFFFF)
    u32.PostMessageW(wintypes.HWND(hwnd), 0x00A1, 2, lparam)  # WM_NCLBUTTONDOWN, HTCAPTION


def trim_memory() -> None:
    """Boştaki sürecin çalışma kümesini Windows'a geri verir (sayfalar gerektiğinde bellekten hızla geri gelir)."""
    try:
        ctypes.WinDLL("psapi").EmptyWorkingSet(k32.GetCurrentProcess())
    except Exception:
        pass


# ---------- DWM görünüm ----------
def style_window(hwnd: int, dark: bool = True) -> None:
    dwm = ctypes.WinDLL("dwmapi")
    for attr, val in ((20, 1 if dark else 0), (33, 2)):  # DWMWA_USE_IMMERSIVE_DARK_MODE, DWMWA_WINDOW_CORNER_PREFERENCE=ROUND
        v = ctypes.c_int(val)
        dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
