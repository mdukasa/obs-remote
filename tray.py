"""OBS Remote's icon by the clock (Windows notification area), run by server.py in its own thread.

- The icon is the app's ring-and-dot, drawn here at the size Windows asks for, with a status dot: green while the
  server is logged in to OBS, amber while it isn't (OBS closed, WebSocket server off, wrong password).
- Hovering shows a summary: "OBS Remote 1.11.0 / OBS connected / 2 phones".
- Click: opens the setup window. Right-click: a menu (open, Start OBS, notifications, restart, stop).
- Notifications are off unless ticked in the menu (kept as "tray_notify" in settings.json in the data folder):
  a frozen camera fixed by autofix, and a new version out.
Plain ctypes, standard library only. Turned off with OBS_REMOTE_NO_TRAY=1.
"""
import ctypes
import json
import os
import threading
import time
from ctypes import wintypes

import paths

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_TIMER, WM_NULL, WM_USER = 0x2, 0x10, 0x111, 0x113, 0x0, 0x400
WM_LBUTTONUP, WM_RBUTTONUP = 0x202, 0x205
WM_TRAY = WM_USER + 20
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO, NIF_SHOWTIP = 0x1, 0x2, 0x4, 0x10, 0x80
NIIF_INFO, NIIF_NOSOUND = 0x1, 0x10
MF_STRING, MF_GRAYED, MF_CHECKED, MF_SEPARATOR = 0x0, 0x1, 0x8, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
CMD_OPEN, CMD_START_OBS, CMD_NOTIFY, CMD_RESTART, CMD_STOP = 1, 2, 3, 4, 5


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort), ("d", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR)]


def _api():
    u, s, k = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("shell32"), ctypes.WinDLL("kernel32")
    H, P = wintypes.HANDLE, ctypes.c_void_p
    sig = {
        (u, "DefWindowProcW"): ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], LRESULT),
        (u, "RegisterClassW"): ([ctypes.POINTER(WNDCLASSW)], wintypes.ATOM),
        (u, "CreateWindowExW"): ([wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                  wintypes.HINSTANCE, P], wintypes.HWND),
        (u, "DestroyWindow"): ([wintypes.HWND], wintypes.BOOL),
        (u, "GetMessageW"): ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        (u, "TranslateMessage"): ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        (u, "DispatchMessageW"): ([ctypes.POINTER(wintypes.MSG)], LRESULT),
        (u, "PostMessageW"): ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL),
        (u, "PostQuitMessage"): ([ctypes.c_int], None),
        (u, "SetTimer"): ([wintypes.HWND, ctypes.c_size_t, wintypes.UINT, P], ctypes.c_size_t),
        (u, "RegisterWindowMessageW"): ([wintypes.LPCWSTR], wintypes.UINT),
        (u, "CreatePopupMenu"): ([], wintypes.HMENU),
        (u, "AppendMenuW"): ([wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR], wintypes.BOOL),
        (u, "TrackPopupMenu"): ([wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 wintypes.HWND, P], ctypes.c_int),
        (u, "DestroyMenu"): ([wintypes.HMENU], wintypes.BOOL),
        (u, "GetCursorPos"): ([ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        (u, "SetForegroundWindow"): ([wintypes.HWND], wintypes.BOOL),
        (u, "GetSystemMetrics"): ([ctypes.c_int], ctypes.c_int),
        (u, "CreateIconFromResourceEx"): ([P, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD, ctypes.c_int,
                                           ctypes.c_int, wintypes.UINT], wintypes.HICON),
        (u, "DestroyIcon"): ([wintypes.HICON], wintypes.BOOL),
        (s, "Shell_NotifyIconW"): ([wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)], wintypes.BOOL),
        (k, "GetModuleHandleW"): ([wintypes.LPCWSTR], wintypes.HMODULE),
    }
    for (dll, name), (args, res) in sig.items():
        f = getattr(dll, name)
        f.argtypes, f.restype = args, res
    return u, s, k


# ---- drawing the icon ------------------------------------------------------------------------------------------

BG, BLUE, RED, GREY = (14, 17, 22), (47, 129, 247), (229, 72, 77), (201, 209, 217)
GREEN, AMBER = (46, 160, 67), (210, 153, 34)


def draw(size, status):
    """The app icon (www/icon.svg: dark rounded square, blue ring, red centre, grey ticks) at size x size, plus a
    status dot at the bottom right. Rows of (r, g, b, a), anti-aliased by 4x4 supersampling."""
    def colour_at(x, y):  # x, y in the SVG's 0..512 space
        dx, dy = x - 256, y - 256
        d = (dx * dx + dy * dy) ** 0.5
        if status:  # status dot: dark outline, then the colour
            sx, sy = x - 404, y - 404
            sd = (sx * sx + sy * sy) ** 0.5
            if sd <= 92:
                return status if sd <= 70 else BG
        if d <= 58:
            return RED
        if abs(d - 150) <= 14 + 512 / size / 2:  # keep the ring at least ~1 px wide when small
            return BLUE
        if (abs(dx) <= 12 + 256 / size and (70 <= y <= 130 or 382 <= y <= 442)) or \
           (abs(dy) <= 12 + 256 / size and (70 <= x <= 130 or 382 <= x <= 442)):
            return GREY
        cx, cy = min(max(x, 112), 400), min(max(y, 112), 400)  # rounded square, corner radius 112
        if (x - cx) ** 2 + (y - cy) ** 2 <= 112 ** 2:
            return BG
        return None

    n, scale, rows = 4, 512.0 / size, []
    for py in range(size):
        row = []
        for px in range(size):
            r = g = b = a = 0
            for sy in range(n):
                for sx in range(n):
                    c = colour_at((px + (sx + 0.5) / n) * scale, (py + (sy + 0.5) / n) * scale)
                    if c:
                        r, g, b, a = r + c[0], g + c[1], b + c[2], a + 1
            row.append((r // a, g // a, b // a, a * 255 // (n * n)) if a else (0, 0, 0, 0))
        rows.append(row)
    return rows


def icon_resource(rows):
    """An icon resource (BITMAPINFOHEADER + 32-bit BGRA bottom-up + 1-bit AND mask) for CreateIconFromResourceEx."""
    import struct
    size = len(rows)
    head = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    pix = b"".join(bytes((b, g, r, a)) for row in reversed(rows) for (r, g, b, a) in row)
    mask = b"\0" * (((size + 31) // 32) * 4 * size)
    return head + pix + mask


# ---- settings ---------------------------------------------------------------------------------------------------

def _settings():
    try:
        with open(paths.data("settings.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(**kw):
    s = _settings()
    s.update(kw)
    with open(paths.data("settings.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


# ---- the icon ---------------------------------------------------------------------------------------------------

class Tray:
    """hooks: state() -> {version, obs, phones, update, events}; open_panel(); start_obs(); obs_running();
    restart(); stop(). All but state() are called from the tray's own thread."""

    def __init__(self, hooks):
        self.hooks = hooks
        self.hwnd = None
        self.ready = threading.Event()
        self.icons = {}
        self.shown = {"status": None, "tip": None}
        self.seen = {"events": None, "update": None}

    def start(self):
        threading.Thread(target=self._run, name="tray", daemon=True).start()
        self.ready.wait(5)
        return self

    def close(self):
        """Remove the icon (otherwise Windows keeps a dead one until the mouse passes over it)."""
        if self.hwnd:
            self.u.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
            for _ in range(20):
                if not self.hwnd:
                    break
                time.sleep(0.05)

    # -- inside the tray thread --
    def _run(self):
        try:
            self.u, self.s, k = _api()
            self._proc = WNDPROC(self._wndproc)  # kept: Windows calls it for as long as the window lives
            cls = WNDCLASSW(lpfnWndProc=self._proc, hInstance=k.GetModuleHandleW(None), lpszClassName="OBSRemoteTray")
            self.u.RegisterClassW(ctypes.byref(cls))
            self.hwnd = self.u.CreateWindowExW(0, "OBSRemoteTray", "OBS Remote", 0, 0, 0, 0, 0, None, None,
                                               cls.hInstance, None)
            self.taskbar_created = self.u.RegisterWindowMessageW("TaskbarCreated")  # Explorer restarted
            self.size = self.u.GetSystemMetrics(49) or 16  # SM_CXSMICON
            self._notify(NIM_ADD)
            self.u.SetTimer(self.hwnd, 1, 3000, None)
        finally:
            self.ready.set()
        msg = wintypes.MSG()
        while self.u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            self.u.TranslateMessage(ctypes.byref(msg))
            self.u.DispatchMessageW(ctypes.byref(msg))

    def _icon(self, status):
        if status not in self.icons:
            res = icon_resource(draw(self.size, {"ok": GREEN, "warn": AMBER}[status]))
            buf = ctypes.create_string_buffer(res, len(res))
            self.icons[status] = self.u.CreateIconFromResourceEx(buf, len(res), True, 0x00030000, self.size, self.size, 0)
        return self.icons[status]

    def _notify(self, op, info=None):
        st = self.hooks["state"]()
        status = "ok" if st["obs"] else "warn"
        lines = ["OBS Remote %s" % st["version"], "OBS connected" if st["obs"] else "OBS not connected"]
        if st["phones"]:
            lines.append("%d phone%s" % (st["phones"], "" if st["phones"] == 1 else "s"))
        if st["update"]:
            lines.append("Version %s is out" % st["update"])
        tip = "\n".join(lines)[:127]
        if op == NIM_MODIFY and not info and (status, tip) == (self.shown["status"], self.shown["tip"]):
            return
        nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1,
                              uFlags=NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP, uCallbackMessage=WM_TRAY,
                              hIcon=self._icon(status), szTip=tip)
        if info:
            nid.uFlags |= NIF_INFO
            nid.szInfoTitle, nid.szInfo = info[0][:63], info[1][:255]
            nid.dwInfoFlags = NIIF_INFO | NIIF_NOSOUND
        self.s.Shell_NotifyIconW(op, ctypes.byref(nid))
        self.shown.update(status=status, tip=tip)

    def _tick(self):
        """Every 3 s: refresh the icon and summary; with notifications on, say when something new happened
        (never for what was already there when the server started)."""
        st = self.hooks["state"]()
        last, update, info = (st["events"][-1] if st["events"] else None), st["update"] or "", None
        if self.seen.get("started") and _settings().get("tray_notify"):
            if last and last is not self.seen["events"]:
                info = ("Camera picture fixed", "%s: %s" % (last["source"], last["what"]))
            elif update and update != self.seen["update"]:
                info = ("OBS Remote %s is out" % update, "Tap Update in the app's Settings.")
        self.seen.update(started=True, events=last, update=update)
        self._notify(NIM_MODIFY, info)

    def _menu(self):
        st = self.hooks["state"]()
        m = self.u.CreatePopupMenu()
        add = lambda flags, cmd, text: self.u.AppendMenuW(m, flags, cmd, text)
        add(MF_STRING | MF_GRAYED, 0, "OBS Remote %s" % st["version"])
        add(MF_STRING | MF_GRAYED, 0, ("OBS connected" if st["obs"] else "OBS not connected") +
            (" · %d phone%s" % (st["phones"], "" if st["phones"] == 1 else "s") if st["phones"] else ""))
        add(MF_SEPARATOR, 0, None)
        add(MF_STRING, CMD_OPEN, "Open OBS Remote (QR code, status)")
        if not self.hooks["obs_running"]():
            add(MF_STRING, CMD_START_OBS, "Start OBS")
        add(MF_STRING | (MF_CHECKED if _settings().get("tray_notify") else 0), CMD_NOTIFY,
            "Notify me of camera fixes and updates")
        add(MF_SEPARATOR, 0, None)
        add(MF_STRING, CMD_RESTART, "Restart OBS Remote")
        add(MF_STRING, CMD_STOP, "Stop until next sign-in")
        pt = wintypes.POINT()
        self.u.GetCursorPos(ctypes.byref(pt))
        self.u.SetForegroundWindow(self.hwnd)  # so the menu closes when clicking elsewhere
        cmd = self.u.TrackPopupMenu(m, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, self.hwnd, None)
        self.u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        self.u.DestroyMenu(m)
        return cmd

    def _do(self, cmd):
        if cmd == CMD_OPEN:
            self.hooks["open_panel"]()
        elif cmd == CMD_START_OBS:
            self.hooks["start_obs"]()
        elif cmd == CMD_NOTIFY:
            _save(tray_notify=not _settings().get("tray_notify"))
        elif cmd == CMD_RESTART:
            self.hooks["restart"]()
        elif cmd == CMD_STOP:
            self.hooks["stop"]()

    def _wndproc(self, hwnd, msg, wp, lp):
        try:
            if msg == WM_TRAY:
                if lp == WM_LBUTTONUP:
                    self.hooks["open_panel"]()
                elif lp == WM_RBUTTONUP:
                    self._do(self._menu())
                return 0
            if msg == WM_TIMER:
                self._tick()
                return 0
            if msg == self.taskbar_created:
                self._notify(NIM_ADD)
                return 0
            if msg == WM_CLOSE:
                self._remove()
                self.u.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                self.u.PostQuitMessage(0)
                self.hwnd = None
                return 0
        except Exception:  # never let an error escape into Windows' message loop
            pass
        return self.u.DefWindowProcW(hwnd, msg, wp, lp)

    def _remove(self):
        nid = NOTIFYICONDATAW(cbSize=ctypes.sizeof(NOTIFYICONDATAW), hWnd=self.hwnd, uID=1)
        self.s.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
        for h in self.icons.values():
            self.u.DestroyIcon(h)
        self.icons.clear()


def start(hooks):
    """Show the icon (Windows only; not with OBS_REMOTE_NO_TRAY=1). Returns the Tray, or None."""
    if os.name != "nt" or os.environ.get("OBS_REMOTE_NO_TRAY") == "1":
        return None
    try:
        return Tray(hooks).start()
    except Exception:
        return None
