"""OBS Remote setup: every check and change setup makes, as plain functions, plus the console setup that uses them.

    python setup/core.py install [--port N] [--skip-firewall] [--skip-startup] [--tailscale | --no-tailscale]
    python setup/core.py status [--port N]    # every check as JSON; changes nothing
    python setup/core.py uninstall
    python setup/core.py panel                 # the setup window / control panel (setup/panel.py)

Install.bat runs setup/install.ps1, which only finds (or installs) Python and then opens the panel
(or, with any switch or -Console, runs "install" here in the console).
The functions return plain dicts and lists, so a setup window can show the same checks. Windows only,
standard library only, Python 3.8+.
"""
import argparse
import concurrent.futures
import ctypes
import datetime
import json
import os
import re
import secrets
import ssl
import string
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes

SETUP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SETUP)
for _p in (ROOT, SETUP):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import paths  # noqa: E402  (the data folder; also moves files older versions left in the program folder)
import qr  # noqa: E402

SERVER = os.path.join(ROOT, "server.py")
DEFAULT_PORT = 8765
NO_WINDOW = 0x08000000
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
APPDATA = os.environ.get("APPDATA", "")
WS_CONFIG = os.path.join(APPDATA, "obs-studio", "plugin_config", "obs-websocket", "config.json")
PTZ_DLLS = [os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), r"obs-studio\plugins\obs-ptz\bin\64bit\obs-ptz.dll"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), r"obs-studio\obs-plugins\64bit\obs-ptz.dll")]
TS_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale")
TS_CLI = os.path.join(TS_DIR, "tailscale.exe")
TS_GUI = os.path.join(TS_DIR, "tailscale-ipn.exe")
RULE_PAGE, RULE_WS = "OBS Remote - phone page", "OBS Remote - OBS websocket"
TS_RANGE = "100.64.0.0"
# Adapters that aren't the phone's Wi-Fi: virtual switches and VPNs, matched on the adapter's name and description.
NOT_LAN = re.compile(r"vEthernet|Hyper-V|VirtualBox|VMware|WSL|Loopback|Bluetooth|Npcap|Docker|Tailscale|WiFiman|ZeroTier|"
                     r"Hamachi|WireGuard|OpenVPN|TAP-Windows|Wintun|NordLynx|ProtonVPN|Fortinet|AnyConnect|GlobalProtect", re.I)


ICON = os.path.join(SETUP, "icon.ico")


def start_menu_shortcut():
    return os.path.join(APPDATA, r"Microsoft\Windows\Start Menu\Programs\OBS Remote.lnk")


def load_settings():
    """What setup chose on this PC (the server's port), kept in the data folder."""
    try:
        with open(paths.data("settings.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(**kw):
    s = load_settings()
    s.update(kw)
    with open(paths.data("settings.json"), "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def saved_port():
    try:
        return int(load_settings().get("port") or DEFAULT_PORT)
    except (TypeError, ValueError):
        return DEFAULT_PORT


def route_mark():
    """The Tailscale route setup added (this PC's LAN address), so a new address replaces it and uninstall removes it."""
    return paths.data("tailscale-route.txt")


# ---- helpers -------------------------------------------------------------------------------------------------

def q(s):
    """A PowerShell single-quoted string."""
    return "'" + str(s).replace("'", "''") + "'"


def powershell(script, timeout=60):
    """Run a PowerShell snippet hidden and return what it printed (UTF-8)."""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
                        "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + script],
                       capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
    return r.stdout.decode("utf-8", "replace").strip()


def ps_json(script, timeout=60):
    try:
        out = powershell(script, timeout)
        return json.loads(out) if out else None
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


def as_list(v):
    """ConvertTo-Json turns a one-item list into the item itself."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def fetch(url, timeout=30, dest=None):
    """GET over HTTPS. Falls back to Windows' curl.exe (Windows certificate store) when Python's TLS can't
    verify the certificate, as server.py does. Returns bytes, or writes them to dest."""
    req = urllib.request.Request(url, headers={"User-Agent": "obs-remote-setup", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise
        r = subprocess.run(["curl.exe", "-fsSL", "--max-time", str(timeout), "-A", "obs-remote-setup", url],
                           capture_output=True, creationflags=NO_WINDOW)
        if r.returncode:
            raise
        data = r.stdout
    if dest:
        with open(dest, "wb") as f:
            f.write(data)
    return data


class Declined(Exception):
    """Someone clicked No on Windows' permission prompt."""


class _SEI(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.ULONG), ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]


def shell_run(file, args=(), admin=False, show=False):
    """Run a program through ShellExecuteEx and wait for it: with admin=True Windows asks for permission first,
    and a program that asks for admin itself (e.g. an Inno Setup installer) gets the prompt too. Returns the exit
    code; raises Declined when the prompt was answered No."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = wintypes.HWND
    # The foreground window (e.g. the setup window) as owner, so Windows shows its permission prompt in front
    # instead of as a flashing taskbar button.
    sei = _SEI(cbSize=ctypes.sizeof(_SEI), fMask=0x40 | 0x100,  # SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
               hwnd=user32.GetForegroundWindow(), lpVerb="runas" if admin else None, lpFile=file, lpParameters=subprocess.list2cmdline(list(args)),
               nShow=1 if show else 0)
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = ctypes.get_last_error()
        if err == 1223:  # ERROR_CANCELLED
            raise Declined()
        raise ctypes.WinError(err)
    if not sei.hProcess:
        return 0
    k32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
    code = wintypes.DWORD()
    k32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    k32.CloseHandle(sei.hProcess)
    return code.value


def check(cid, label, state, detail="", hints=(), **extra):
    """One line of setup's report. state: ok, warn, fail or info."""
    d = {"id": cid, "label": label, "state": state, "detail": detail, "hints": list(hints)}
    d.update(extra)
    return d


# ---- Python --------------------------------------------------------------------------------------------------

def check_python():
    v = sys.version_info
    ok = v >= (3, 8)
    return check("python", "Python", "ok" if ok else "fail", "version %d.%d" % v[:2],
                 [] if ok else ["OBS Remote needs Python 3.8 or newer."], exe=sys.executable)


def pythonw():
    """pythonw.exe next to this Python: runs the server with no window."""
    w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return w if os.path.exists(w) else sys.executable


# ---- OBS -----------------------------------------------------------------------------------------------------

def obs_running():
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH", "/FO", "CSV"],
                       capture_output=True, creationflags=NO_WINDOW)
    return b"obs64.exe" in r.stdout.lower()


def obs_path():
    """Where the running OBS is, so setup can open it again after closing it."""
    return powershell("$p = @(Get-Process obs64 -ErrorAction SilentlyContinue); if ($p.Count) { $p[0].Path }") or None


def open_obs(exe):
    if exe and os.path.exists(exe) and not obs_running():
        subprocess.Popen([exe], cwd=os.path.dirname(exe), creationflags=DETACHED, close_fds=True)
        return True
    return False


def close_obs(timeout=45):
    """Ask OBS to close, like clicking its X (it saves its settings and asks if it's live). True once it's gone.
    False if it's still open: hidden in the tray (no window to close) or waiting for an answer on screen.
    OBS sometimes ignores the first request with nothing in its log (seen with OBS 32.2.2, 2026-11-23), so it asks
    again every 8 s while the window is still there; once OBS is shutting down its window is gone and a repeat does
    nothing. Shutting down itself takes OBS 10-15 s with many cameras."""
    end, asked = time.time() + timeout, 0.0
    while time.time() < end:
        if not obs_running():
            return True
        if time.time() - asked >= 8:
            powershell("Get-Process obs64 -ErrorAction SilentlyContinue | ForEach-Object { [void]$_.CloseMainWindow() }")
            asked = time.time()
        time.sleep(0.5)
    return not obs_running()


def obs_probe(ws, timeout=4):
    """Log in to OBS's WebSocket server like a phone does: OBS's version, whether it's live, and whether obs-ptz
    answers phone control (needs obs-ptz 1.0+ with Websocket access = Control). Never changes anything."""
    import autofix  # its minimal obs-websocket client
    out = {"ok": False, "error": None, "version": None, "streaming": False, "recording": False,
           "ptz": {"ok": False, "count": 0, "error": None}}
    if not ws["enabled"]:
        out["error"] = "WebSocket server is off"
        return out
    obs = None
    try:
        obs = autofix.OBS("127.0.0.1", ws["port"], ws["password"], timeout=timeout)
        out["version"] = obs.call("GetVersion").get("obsVersion")
        out["streaming"] = bool(obs.call("GetStreamStatus").get("outputActive"))
        out["recording"] = bool(obs.call("GetRecordStatus").get("outputActive"))
        out["ok"] = True
        try:
            r = obs.call("CallVendorRequest", {"vendorName": "obs-ptz", "requestType": "ptz_list_devices", "requestData": {}})
            out["ptz"].update(ok=True, count=len((r.get("responseData") or {}).get("devices") or []))
        except RuntimeError as e:
            out["ptz"]["error"] = str(e)
    except Exception as e:
        out["error"] = str(e) or type(e).__name__
    finally:
        if obs:
            obs.close()
    return out


def read_ws():
    """obs-websocket's settings file, or None if OBS never set it up."""
    try:
        with open(WS_CONFIG, encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}


def ws_status():
    cfg = read_ws()
    c = cfg or {}
    auth = bool(c.get("auth_required"))
    return {"config": cfg is not None, "enabled": bool(c.get("server_enabled")),
            "port": int(c.get("server_port") or 4455), "auth": auth,
            "password": str(c.get("server_password") or "") if auth else ""}


def enable_ws():
    """Turn on OBS's WebSocket server in its own settings file (OBS must be closed: it saves its copy on exit).
    Keeps the port and password, and makes a 12-character password if there is none."""
    c = read_ws() or {}
    pw = str(c.get("server_password") or "")
    if not pw:
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    new = {"alerts_enabled": bool(c.get("alerts_enabled")), "auth_required": True, "first_load": False,
           "server_enabled": True, "server_password": pw, "server_port": int(c.get("server_port") or 4455)}
    os.makedirs(os.path.dirname(WS_CONFIG), exist_ok=True)
    with open(WS_CONFIG, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=4)
    return ws_status()


def check_ws(ws, just_on=False):
    if ws["enabled"]:
        return check("ws", "OBS remote control", "ok",
                     "WebSocket server is on (port %d)%s" % (ws["port"], ", just turned on" if just_on else ""),
                     [] if ws["auth"] else ["It has no password, so anyone on this network could control OBS. Consider setting one."])
    return check("ws", "OBS remote control", "warn",
                 "WebSocket server is OFF" if ws["config"] else "OBS's WebSocket server isn't set up yet",
                 ["Phones can't connect until it's on. In OBS: Tools > WebSocket Server Settings > Enable WebSocket server."])


# ---- obs-ptz (the Camera tab needs 1.0 beta or newer: that's when it got websocket control) --------------------

def ptz_status():
    """None when obs-ptz isn't installed, else {dll, version, ok}."""
    dll = next((d for d in PTZ_DLLS if os.path.exists(d)), None)
    if not dll:
        return None
    with open(dll, "rb") as f:
        ok = b"ptz_list_devices" in f.read()
    ver = powershell("(Get-Item -LiteralPath %s).VersionInfo.ProductVersion" % q(dll), 30)
    return {"dll": dll, "version": ver, "ok": ok}


def find_ptz_release():
    """Newest obs-ptz release numbered 1.0 or later (its betas are GitHub pre-releases) with a Windows installer."""
    arch = "arm64" if os.environ.get("PROCESSOR_ARCHITECTURE") == "ARM64" else "x64"
    rels = json.loads(fetch("https://api.github.com/repos/glikely/obs-ptz/releases?per_page=20", 20))
    for r in rels:
        m = re.match(r"v?(\d+)\.", r.get("tag_name") or "")
        if r.get("draft") or not m or int(m.group(1)) < 1:
            continue
        for a in r.get("assets") or []:
            if a["name"].endswith("windows-%s-Installer.exe" % arch):
                return {"tag": r["tag_name"], "url": a["browser_download_url"], "name": a["name"]}
    return None


def install_ptz(rel, say=print):
    """Download and run obs-ptz's installer (Inno Setup, /SILENT shows only a progress bar). OBS must be closed.
    Returns None when it worked, else what went wrong."""
    exe = os.path.join(tempfile.gettempdir(), os.path.basename(rel["name"]))
    say("Downloading obs-ptz %s..." % rel["tag"])
    try:
        fetch(rel["url"], 300, dest=exe)
    except Exception:
        return "The download failed. Get it from https://github.com/glikely/obs-ptz/releases"
    say("Installing. Windows may ask for permission: click Yes.")
    try:
        code = shell_run(exe, ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], show=True)
        return None if code == 0 else "obs-ptz's installer stopped (code %d)." % code
    except Declined:
        return "Permission was declined, so obs-ptz was not installed."
    except OSError as e:
        return "obs-ptz's installer didn't start: %s" % e
    finally:
        try:
            os.remove(exe)
        except OSError:
            pass


def check_ptz(ptz, installed_now=False):
    if not ptz:
        return check("ptz", "PTZ cameras", "info", "obs-ptz not installed (fine if you have no PTZ cameras)")
    if not ptz["ok"]:
        return check("ptz", "PTZ cameras", "warn", "obs-ptz %s is too old for phone control" % ptz["version"],
                     ["Install obs-ptz 1.0 (beta) or newer: https://github.com/glikely/obs-ptz/releases"])
    return check("ptz", "PTZ cameras", "ok", "obs-ptz %s%s; set its Websocket access to Control"
                 % (ptz["version"], " installed" if installed_now else ""))


# ---- Tailscale (optional): phones away from this network ----------------------------------------------------

def ts_json(*args):
    if not os.path.exists(TS_CLI):
        return None
    try:
        r = subprocess.run([TS_CLI] + list(args), capture_output=True, timeout=20, creationflags=NO_WINDOW)
        return json.loads(r.stdout.decode("utf-8", "replace")) if r.stdout.strip() else None
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


def ts_status():
    """What Tailscale on this PC says about itself. ip is set only while it's connected."""
    st = {"installed": os.path.exists(TS_CLI), "running": False, "ip": None, "name": os.environ.get("COMPUTERNAME", "").lower(),
          "key_expiry": None, "routes": [], "peers": []}
    s = ts_json("status", "--json")
    if not s:
        return st
    me = s.get("Self") or {}
    st["running"] = s.get("BackendState") == "Running"
    if st["running"]:
        st["ip"] = next((a for a in me.get("TailscaleIPs") or [] if a.startswith("100.")), None)
    st["name"] = (me.get("DNSName") or "").split(".")[0] or st["name"]
    st["key_expiry"] = me.get("KeyExpiry") or None
    st["routes"] = list(me.get("PrimaryRoutes") or []) + list(me.get("AllowedIPs") or [])
    st["peers"] = [{"name": p.get("HostName"), "ips": list(p.get("TailscaleIPs") or []), "routes": list(p.get("PrimaryRoutes") or []) + list(p.get("AllowedIPs") or [])}
                   for p in (s.get("Peer") or {}).values()]
    return st


def install_tailscale(quiet=False):
    """winget install Tailscale, then open it so the person can sign in. False if it isn't there afterwards.
    quiet: no console window or progress (the setup window)."""
    if not os.path.exists(TS_GUI):
        try:
            subprocess.run(["winget", "install", "--id", "Tailscale.Tailscale", "-e",
                            "--accept-package-agreements", "--accept-source-agreements"],
                           **(dict(capture_output=True, creationflags=NO_WINDOW) if quiet else {}))
        except OSError:
            pass
    if not os.path.exists(TS_GUI):
        return False
    subprocess.Popen([TS_GUI], creationflags=DETACHED, close_fds=True)
    return True


def expiry_text(key_expiry):
    try:
        d = datetime.datetime.strptime(key_expiry[:19], "%Y-%m-%dT%H:%M:%S")
        return "%d %s" % (d.day, d.strftime("%B %Y"))
    except (TypeError, ValueError):
        return "in a few months"


def read_route_mark():
    try:
        with open(route_mark(), encoding="utf-8") as f:
            return f.readline().strip()
    except OSError:
        return ""


def set_route(want, old):
    """Advertise want (e.g. 192.168.1.10/32) in place of old, keeping routes someone else added
    ("tailscale set --advertise-routes" replaces the whole list). Returns None when done, else why not."""
    prefs = ts_json("debug", "prefs")
    if prefs is None:
        return "noread"
    cur = [r for r in prefs.get("AdvertiseRoutes") or [] if r]
    new = [r for r in cur if r not in (old, want)] + ([want] if want else [])
    if sorted(cur) != sorted(new):
        r = subprocess.run([TS_CLI, "set", "--advertise-routes=" + ",".join(new)], capture_output=True, creationflags=NO_WINDOW)
        if r.returncode:
            return "refused"
    if want:
        with open(route_mark(), "w", encoding="ascii") as f:
            f.write(want + "\n")
    elif os.path.exists(route_mark()):
        os.remove(route_mark())
    return None


def route_approved(route, st=None):
    return route in (st or ts_status())["routes"]


def key_expiry_off(st=None):
    return not (st or ts_status())["key_expiry"]


# ---- Windows Firewall ----------------------------------------------------------------------------------------

def firewall_rules():
    """{rule name: {"remote": "LocalSubnet,...", "port": "8765"} or None}"""
    # Through the firewall's COM interface: the same answer as Get-NetFirewallRule in a third of the time.
    script = ("$p = New-Object -ComObject HNetCfg.FwPolicy2; $o = @{}; foreach ($n in %s, %s) { $r = $null; "
              "try { $r = $p.Rules.Item($n) } catch {}; "
              "$o[$n] = if ($r) { @{ remote = \"$($r.RemoteAddresses)\"; port = \"$($r.LocalPorts)\" } } else { $null } }; "
              "ConvertTo-Json -Compress -InputObject $o") % (q(RULE_PAGE), q(RULE_WS))
    return ps_json(script) or {RULE_PAGE: None, RULE_WS: None}


def rules_allow_tailscale(rules):
    r = rules.get(RULE_PAGE)
    return bool(r) and TS_RANGE in r["remote"]


def firewall_ok(rules, port, obs_port, tailscale):
    for name, p in ((RULE_PAGE, port), (RULE_WS, obs_port)):
        r = rules.get(name)
        if not r or str(p) not in r["port"].split(",") or (TS_RANGE in r["remote"]) != bool(tailscale):
            return False
    return True


def apply_firewall(port, obs_port, tailscale, remove=False):
    """Add (or remove) the rules through firewall.ps1, run as admin. Returns its exit code; raises Declined."""
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", os.path.join(SETUP, "firewall.ps1")]
    args += ["-Remove"] if remove else ["-Port", str(port), "-ObsPort", str(obs_port)] + (["-Tailscale"] if tailscale else [])
    return shell_run("powershell", args, admin=True)


# ---- the OBS Remote server -----------------------------------------------------------------------------------

def server_processes(port):
    """Python processes running a server.py, and whatever listens on the port."""
    script = ("$procs = @(Get-CimInstance Win32_Process -Filter \"Name like 'python%%.exe'\" -ErrorAction SilentlyContinue | "
              "Where-Object { $_.CommandLine -like '*server.py*' } | ForEach-Object { @{ pid = [int]$_.ProcessId; cmd = \"$($_.CommandLine)\" } }); "
              "$owner = $null; $c = @(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue) | Select-Object -First 1; "
              "if ($c) { $p = Get-CimInstance Win32_Process -Filter \"ProcessId = $($c.OwningProcess)\" -ErrorAction SilentlyContinue; "
              "$owner = @{ pid = [int]$c.OwningProcess; name = \"$($p.Name)\"; path = \"$($p.ExecutablePath)\"; cmd = \"$($p.CommandLine)\" } }; "
              "ConvertTo-Json -Compress -Depth 4 -InputObject @{ procs = $procs; owner = $owner }") % port
    r = ps_json(script) or {}
    return as_list(r.get("procs")), r.get("owner")


def ask_server_to_quit(port, wait=4):
    """Ask the OBS Remote server on this port to stop by itself (POST /api/quit, 1.11.1+), so its tray icon goes
    too; a killed process leaves a dead icon until the mouse passes over it. True once the port is free."""
    req = urllib.request.Request("http://127.0.0.1:%d/api/quit" % port, data=b"", method="POST",
                                 headers={"X-OBS-Remote": "1"})
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=2).close()
    except Exception:
        return False
    end = time.time() + wait
    while time.time() < end:
        if not test_page(port)[0]:
            return True
        time.sleep(0.2)
    return False


def stop_servers(port):
    """Stop this folder's server, and any other OBS Remote listening on the port (e.g. an older copy in another
    folder: it would stop this one starting). Returns the number of other copies stopped."""
    ask_server_to_quit(port)
    procs, owner = server_processes(port)
    mine = [p["pid"] for p in procs if SERVER.lower() in p["cmd"].lower()]
    others = []
    if owner and owner["pid"] not in mine and owner["name"].lower().startswith("python") and "server.py" in owner["cmd"]:
        others.append(owner["pid"])
    for pid in mine + others:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
    if mine or others:
        time.sleep(0.5)
    return len(others)


def start_server(port):
    """Start pythonw server.py in the background, outside this console."""
    kw = dict(cwd=ROOT, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = [pythonw(), SERVER, str(port)]
    try:
        return subprocess.Popen(cmd, creationflags=DETACHED | 0x01000000, **kw)  # + CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        return subprocess.Popen(cmd, creationflags=DETACHED, **kw)


def startup_shortcut():
    return os.path.join(APPDATA, r"Microsoft\Windows\Start Menu\Programs\Startup\OBS Remote.lnk")


def add_shortcut(lnk, args="", desc=""):
    """A shortcut that runs pythonw with args (no window), with OBS Remote's icon."""
    icon = "$s.IconLocation = %s; " % q(ICON + ",0") if os.path.exists(ICON) else ""
    powershell("$s = (New-Object -ComObject WScript.Shell).CreateShortcut(%s); $s.TargetPath = %s; $s.Arguments = %s; "
               "$s.WorkingDirectory = %s; $s.WindowStyle = 7; $s.Description = %s; %s$s.Save()"
               % (q(lnk), q(pythonw()), q(args), q(ROOT), q(desc), icon))
    return os.path.exists(lnk)


def add_start_menu():
    """Start menu > OBS Remote: opens the setup window / control panel."""
    return add_shortcut(start_menu_shortcut(), '"%s" panel' % os.path.join(SETUP, "core.py"),
                        "OBS Remote: set up, phone QR code and status")


def add_startup(port):
    """A shortcut in the Startup folder, so the server starts whenever this user signs in."""
    return add_shortcut(startup_shortcut(), '"%s" %d' % (SERVER, port), "OBS Remote web server for phones")


def test_page(port):
    """Does the page answer on 127.0.0.1? Asked directly: a system proxy can swallow even local requests.
    Returns (ok, error text)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:%d/" % port, timeout=3) as r:
            return r.status == 200, None
    except Exception as e:
        return False, str(getattr(e, "reason", e))


def wait_for_page(port, proc, seconds=10):
    err = None
    for _ in range(int(seconds * 2)):
        time.sleep(0.5)
        ok, err = test_page(port)
        if ok:
            return True, None
        if proc is not None and proc.poll() is not None:
            break
    return False, err


def why_not_started(port, proc, err):
    """Hints for a server that didn't answer: the program holding the port, or the server's own error."""
    _, owner = server_processes(port)
    if owner and proc is not None and owner["pid"] == proc.pid:
        return ["It's running but didn't answer on http://127.0.0.1:%d/ (%s)." % (port, err),
                "Security software may be blocking it. Try opening that address in a browser on this PC."]
    if owner:
        return ["Port %d is taken by %s (%s)." % (port, owner["name"], owner["path"]),
                "Close that program, or run Install.bat -Port %d." % (port + 1)]
    # It stopped by itself: pythonw has nowhere to print, so run it once more with python and show what it says.
    try:
        r = subprocess.run([sys.executable, SERVER, str(port)], cwd=ROOT, capture_output=True, timeout=15,
                           creationflags=NO_WINDOW, env=dict(os.environ, OBS_REMOTE_NO_TRAY="1"))
        why = [ln for ln in r.stderr.decode("utf-8", "replace").splitlines() if ln.strip()][-3:]
    except subprocess.TimeoutExpired:
        why = []
    return why or ['To see why, run:  "%s" "%s"' % (sys.executable, SERVER)]


def version():
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            return f.readline().strip()
    except OSError:
        return ""


# ---- where phones reach it -----------------------------------------------------------------------------------

class _SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]


class _UNICAST(ctypes.Structure):  # IP_ADAPTER_UNICAST_ADDRESS (the fields up to PrefixOrigin); also fits a gateway entry
    pass


_UNICAST._fields_ = [("Alignment", ctypes.c_ulonglong), ("Next", ctypes.POINTER(_UNICAST)),
                     ("Address", _SOCKET_ADDRESS), ("PrefixOrigin", ctypes.c_int)]


class _ADAPTER(ctypes.Structure):  # IP_ADAPTER_ADDRESSES_LH, up to Ipv4Metric
    pass


_ADAPTER._fields_ = [("Alignment", ctypes.c_ulonglong), ("Next", ctypes.POINTER(_ADAPTER)), ("AdapterName", ctypes.c_char_p),
                     ("FirstUnicastAddress", ctypes.POINTER(_UNICAST)), ("FirstAnycastAddress", ctypes.c_void_p),
                     ("FirstMulticastAddress", ctypes.c_void_p), ("FirstDnsServerAddress", ctypes.c_void_p),
                     ("DnsSuffix", ctypes.c_wchar_p), ("Description", ctypes.c_wchar_p), ("FriendlyName", ctypes.c_wchar_p),
                     ("PhysicalAddress", ctypes.c_ubyte * 8), ("PhysicalAddressLength", ctypes.c_ulong),
                     ("Flags", ctypes.c_ulong), ("Mtu", ctypes.c_ulong), ("IfType", ctypes.c_ulong), ("OperStatus", ctypes.c_int),
                     ("Ipv6IfIndex", ctypes.c_ulong), ("ZoneIndices", ctypes.c_ulong * 16), ("FirstPrefix", ctypes.c_void_p),
                     ("TransmitLinkSpeed", ctypes.c_ulonglong), ("ReceiveLinkSpeed", ctypes.c_ulonglong),
                     ("FirstWinsServerAddress", ctypes.c_void_p), ("FirstGatewayAddress", ctypes.POINTER(_UNICAST)),
                     ("Ipv4Metric", ctypes.c_ulong)]


def _ipv4(sa):
    """The IPv4 address in a SOCKET_ADDRESS (sockaddr_in: family 2, port, then 4 address bytes), else None."""
    if not sa.lpSockaddr or sa.iSockaddrLength < 8:
        return None
    raw = ctypes.string_at(sa.lpSockaddr, 8)
    return "%d.%d.%d.%d" % tuple(raw[4:8]) if raw[0] == 2 else None


def lan_addresses():
    """This PC's local-network IPv4 addresses, best route first: [{alias, ip, dhcp, gateway}]. Virtual adapters and
    VPNs are left out: they aren't the phone's Wi-Fi. Read with GetAdaptersAddresses (instant; PowerShell's
    Get-NetIPAddress takes seconds)."""
    iphlp = ctypes.WinDLL("iphlpapi")
    size = wintypes.ULONG(32768)
    for _ in range(3):
        buf = ctypes.create_string_buffer(size.value)
        # AF_INET, GAA_FLAG_SKIP_ANYCAST | SKIP_MULTICAST | SKIP_DNS_SERVER | INCLUDE_GATEWAYS
        err = iphlp.GetAdaptersAddresses(2, 0x2 | 0x4 | 0x8 | 0x80, None, buf, ctypes.byref(size))
        if err != 111:  # ERROR_BUFFER_OVERFLOW: size now says how much is needed
            break
    if err:
        return []
    out = []
    a = ctypes.cast(buf, ctypes.POINTER(_ADAPTER))
    while a:
        ad = a.contents
        name, desc = ad.FriendlyName or "", ad.Description or ""
        if ad.OperStatus == 1 and not NOT_LAN.search("%s %s" % (name, desc)):  # 1 = IfOperStatusUp
            gw = _ipv4(ad.FirstGatewayAddress.contents.Address) if ad.FirstGatewayAddress else None
            u = ad.FirstUnicastAddress
            while u:
                ip = _ipv4(u.contents.Address)
                # PrefixOrigin 2 = WellKnown (loopback), 3 = Dhcp
                if ip and not ip.startswith(("127.", "169.254.")) and u.contents.PrefixOrigin != 2:
                    out.append({"alias": name, "ip": ip, "dhcp": u.contents.PrefixOrigin == 3, "gateway": gw,
                                "metric": ad.Ipv4Metric})
                u = u.contents.Next
        a = ad.Next
    out.sort(key=lambda x: x["metric"])
    for x in out:
        del x["metric"]
    return out


def page_url(host, port):
    return "http://%s:%d/" % (host, port)


def sign_in_url(host, port, ws):
    """The page address plus the OBS login in the #fragment, which browsers never send to the server. The page
    saves it and removes it from the address bar. Re-run setup after changing OBS's password."""
    login = []
    if ws["password"]:
        login.append("pw=" + urllib.parse.quote(ws["password"], safe=""))
    if ws["port"] != 4455:
        login.append("port=%d" % ws["port"])
    return page_url(host, port) + ("#" + "&".join(login) if login else "")


def remove_phone_pages():
    """Versions before 1.11 wrote the QR codes, with the OBS password, to Phone address.html / .txt in the program
    folder. The setup window shows them now, so those files go."""
    for name in ("Phone address.html", "Phone address.txt"):
        try:
            os.remove(os.path.join(ROOT, name))
        except OSError:
            pass


def phone_codes(lan, ts_ip, port, ws):
    """[{label, url, qr, folded}]: a code per LAN address, plus the PC's own Tailscale address, folded away:
    Tailscale doesn't pass routes on when a PC is shared into another tailnet, so phones there need it."""
    out = [{"label": "On this network (%s)" % a["alias"], "url": page_url(a["ip"], port),
            "qr": sign_in_url(a["ip"], port, ws), "folded": False} for a in lan]
    if ts_ip:
        out.append({"label": "Over Tailscale", "url": page_url(ts_ip, port), "qr": sign_in_url(ts_ip, port, ws), "folded": True})
    return out


# ---- status: every check, no changes ---------------------------------------------------------------------------

def gather(**jobs):
    """Run independent checks at once (most start a PowerShell, about a second each). {name: result}"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {k: ex.submit(f) for k, f in jobs.items()}
        return {k: f.result() for k, f in futs.items()}


def status(port=DEFAULT_PORT):
    ws = ws_status()
    g = gather(ts=ts_status, rules=firewall_rules, lan=lan_addresses, page=lambda: test_page(port),
               ptz=ptz_status, obs=obs_running)
    ts, rules, lan, (ok, err) = g["ts"], g["rules"], g["lan"], g["page"]
    use_ts = rules_allow_tailscale(rules)
    route = read_route_mark()
    return {"version": version(), "python": check_python(), "obs": {"running": g["obs"]}, "ws": ws,
            "ptz": g["ptz"], "tailscale": dict(ts, chosen=use_ts, route=route or None,
                                                   route_approved=bool(route) and route in ts["routes"]),
            "firewall": dict(rules=rules, ok=firewall_ok(rules, port, ws["port"], use_ts)),
            "server": {"port": port, "answering": ok, "error": err, "startup": os.path.exists(startup_shortcut())},
            "lan": lan, "phone_urls": [page_url(a["ip"], port) for a in lan]}


# ---- uninstall -----------------------------------------------------------------------------------------------

def stop_folder():
    """Stop every OBS Remote program running from this folder (the server, a setup window), except this one.
    The installer runs it before replacing files: Windows can't replace a file a program has open."""
    ask_server_to_quit(saved_port())
    script = ("Get-CimInstance Win32_Process -Filter \"Name like 'python%%.exe'\" -ErrorAction SilentlyContinue | "
              "Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains(%s) } | ForEach-Object { $_.ProcessId }"
              % q(ROOT.lower() + os.sep))
    pids = [int(x) for x in powershell(script).split() if x.isdigit() and int(x) != os.getpid()]
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
    return len(pids)


def was_set_up():
    """Has OBS Remote been set up on this PC before, by this copy or another one?"""
    return bool(load_settings()) or os.path.exists(startup_shortcut())


def start_here():
    """After the installer: on a PC where OBS Remote was set up before (by any copy), take over: stop the old server,
    start this one, and point Startup and the Start menu here. On a new PC do nothing; the setup window walks
    through it. Returns 0 when the server answers (or there was nothing to do)."""
    if not was_set_up():
        return 0
    port = saved_port()
    stop_servers(port)
    proc = start_server(port)
    save_settings(port=port)
    gather(menu=add_start_menu, startup=lambda: add_startup(port))
    remove_phone_pages()
    return 0 if wait_for_page(port, proc)[0] else 1


def uninstall(say=print, closing=True):
    stop_folder()
    stop_servers(saved_port())  # also a copy of this folder's server started under another name
    say("Stopped the web server.")
    if os.path.exists(startup_shortcut()):
        os.remove(startup_shortcut())
        say("Removed it from Windows startup.")
    if os.path.exists(start_menu_shortcut()):
        os.remove(start_menu_shortcut())
        say("Removed it from the Start menu.")
    route = read_route_mark()
    if route and os.path.exists(TS_CLI):  # only the route setup added; other advertised routes are kept
        why = set_route("", route)
        if why is None:
            say("Stopped sharing %s over Tailscale." % route)
        elif why == "refused":
            say("Couldn't remove the Tailscale route %s. Run Uninstall.bat as the user signed in to Tailscale." % route)
        else:
            say("Couldn't read Tailscale's settings; the route %s may still be shared." % route)
    rules = firewall_rules()
    if any(rules.values()):
        try:
            apply_firewall(0, 0, False, remove=True)
            say("Removed the firewall rules.")
        except (Declined, OSError):
            say("Admin permission declined; firewall rules 'OBS Remote - ...' were left in place.")
    if closing:  # the setup window says this itself
        say("\nOBS Remote is uninstalled. You can now delete this folder.")
        say("Its logs are in %s; delete that folder too if you don't need them." % paths.DATA)


# ---- the console setup -------------------------------------------------------------------------------------------

class Console:
    COLORS = {"Gray": 37, "DarkGray": 90, "Green": 92, "Yellow": 93, "Red": 91, "Cyan": 96, "White": 97}

    def __init__(self):
        self.tty = sys.stdout.isatty()
        self.color = self.tty and self._enable_vt()
        if not self.tty:
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                pass

    @staticmethod
    def _enable_vt():
        try:
            k32 = ctypes.WinDLL("kernel32")
            h = k32.GetStdHandle(-11)
            mode = wintypes.DWORD()
            return bool(k32.GetConsoleMode(h, ctypes.byref(mode)) and k32.SetConsoleMode(h, mode.value | 4))
        except Exception:
            return False

    def c(self, text, color):
        return "\033[%dm%s\033[0m" % (self.COLORS[color], text) if self.color else text

    def say(self, text="", color="Gray"):
        print(self.c(text, color), flush=True)

    def hint(self, text):
        self.say("              " + text, "Yellow")

    def step(self, n, d):
        """[1/4] Python ................ OK  version 3.12"""
        color = {"ok": "Green", "warn": "Yellow", "fail": "Red", "info": "Gray"}[d["state"]]
        tag = {"ok": " OK ", "warn": "NOTE", "fail": "FAIL", "info": " -- "}[d["state"]]
        num = "[%d/4]" % n if n else "     "
        print("  %s %s %s  %s" % (num, d["label"].ljust(22, "."), self.c(tag, color), d["detail"]), flush=True)
        for h in d["hints"]:
            self.hint(h)

    def ask(self, prompt, default_yes):
        a = input("              %s (%s) " % (prompt, "Y/n" if default_yes else "y/N")).strip().lower()
        return not a.startswith("n") if default_yes else a.startswith("y")

    def qr(self, text):
        """Two QR rows per text line with half blocks, black on white so every phone camera reads it."""
        rows = qr.rows(text)
        for i in range(0, len(rows), 2):
            a, b = rows[i], rows[i + 1] if i + 1 < len(rows) else "0" * len(rows[i])
            line = "".join("\u2588" if x == "1" and y == "1" else "\u2580" if x == "1" else "\u2584" if y == "1" else " "
                           for x, y in zip(a, b))
            print("      " + ("\033[30;107m%s\033[0m" % line if self.color else line), flush=True)

    def wait_enter_or(self, until, done):
        """Print dots every 2 s until done() is true, `until` passes, or Enter is pressed."""
        import msvcrt
        while time.time() < until and not done():
            for _ in range(20):
                if self.tty and msvcrt.kbhit() and msvcrt.getwch() in "\r\n":
                    print(flush=True)
                    return
                time.sleep(0.1)
            print(".", end="", flush=True)
        print(flush=True)


def run_install(args):
    con = Console()
    port = args.port or saved_port()
    if con.tty:
        ctypes.windll.kernel32.SetConsoleTitleW("OBS Remote setup")
        os.system("cls")
    con.say()
    con.say("  OBS Remote setup", "Cyan")
    con.say()

    # ---- 1. Python (install.ps1 found or installed it; this is it running) ----
    py = check_python()
    con.step(1, py)
    if py["state"] == "fail":
        return 1

    # ---- 2. OBS ----
    # Some changes need OBS closed: it keeps its settings and plugins open and saves its own copy on exit.
    # Setup asks once, remembers where OBS was, and opens it again at the end of the OBS steps.
    obs = {"exe": None}

    def close_obs(why):
        if not obs_running():
            return True
        obs["exe"] = obs["exe"] or obs_path()
        con.hint("OBS is open. To %s, save your work and close OBS, then press Enter." % why)
        if input("              (press Enter when OBS is closed, or type s to skip) ").strip().lower().startswith("s"):
            return False
        for _ in range(10):
            if not obs_running():
                return True
            time.sleep(1)
        con.hint("OBS is still open, so this was skipped. Run Install.bat again later.")
        return False

    ws = ws_status()
    just_on = False
    if not ws["enabled"]:
        con.step(2, dict(check_ws(ws), hints=[]))
        if con.ask("Turn it on now?", True) and close_obs("turn it on"):
            ws, just_on = enable_ws(), True
    if ws["enabled"]:
        con.step(2, check_ws(ws, just_on))
    else:
        for h in check_ws(ws)["hints"]:
            con.hint(h)

    ptz = ptz_status()
    installed_now = False

    def get_ptz():
        try:
            rel = find_ptz_release()
        except Exception:
            rel = None
        if not rel:
            con.hint("Couldn't reach GitHub. Get it from https://github.com/glikely/obs-ptz/releases")
            return
        if not close_obs("install obs-ptz"):
            return
        why = install_ptz(rel, say=con.hint)
        if why:
            con.hint(why)

    if not ptz:
        con.step(0, check_ptz(None))
        if con.ask("Do you have PTZ cameras? Install obs-ptz for the Camera tab now?", False):
            get_ptz()
            ptz, installed_now = ptz_status(), True
    elif not ptz["ok"]:
        con.step(0, check_ptz(ptz))
        if con.ask("Update obs-ptz to the newest version now?", True):
            get_ptz()
            ptz, installed_now = ptz_status(), True
    if ptz and (ptz["ok"] or installed_now):
        con.step(0, check_ptz(ptz, installed_now and ptz["ok"]))
    if open_obs(obs["exe"]):
        con.hint("Opened OBS again.")

    # ---- Tailscale (optional) ----
    # Asked once; the answer is kept in the firewall rules (re-run with -Tailscale / -NoTailscale to change).
    ts = ts_status()
    rules = firewall_rules()
    if args.no_tailscale:
        use_ts = False
    elif args.tailscale or rules_allow_tailscale(rules):
        use_ts = True
    elif ts["ip"]:
        use_ts = con.ask("Tailscale is on this PC. Let phones connect over it too, from anywhere?", False)
    else:
        use_ts = con.ask("Optional: set up Tailscale, for phones away from this Wi-Fi?", False)
        if use_ts and install_tailscale():
            con.say("   Sign in to Tailscale: click its icon by the clock (or the window that opens) > Log in.", "Cyan")
            print("   Waiting for Tailscale (up to 3 minutes) ", end="", flush=True)
            con.wait_enter_or(time.time() + 180, lambda: bool(ts_status()["ip"]))
            ts = ts_status()
    if use_ts and not ts["ip"]:
        con.step(0, check("tailscale", "Tailscale", "warn", "not connected yet",
                          ["Sign in to Tailscale on this PC, then run Install.bat again."]))
        use_ts = False
    elif use_ts:
        con.step(0, check("tailscale", "Tailscale", "ok", "phones on your tailnet can connect (%s)" % ts["ip"]))
    elif ts["ip"]:
        con.step(0, check("tailscale", "Tailscale", "info", "not used (run Install.bat -Tailscale to turn on)"))

    # ---- 3. Firewall (needs admin, asks once) ----
    fw_label = "Windows Firewall"
    reach = "phones on this network" + (" and Tailscale" if use_ts else "") + " can connect"
    if args.skip_firewall:
        con.step(3, check("firewall", fw_label, "info", "skipped (-SkipFirewall)"))
    elif firewall_ok(rules, port, ws["port"], use_ts):
        con.step(3, check("firewall", fw_label, "ok", reach))
    else:
        con.say("              Windows will ask for permission next: click Yes.", "Cyan")
        try:
            code = apply_firewall(port, ws["port"], use_ts)
            con.step(3, check("firewall", fw_label, "ok", reach) if code == 0 else
                     check("firewall", fw_label, "warn", "couldn't add the rules (code %d)" % code,
                           ["Phones may not be able to connect. Run Install.bat again to retry."]))
        except Declined:
            con.step(3, check("firewall", fw_label, "warn", "permission was declined",
                              ["Phones may not connect. Run Install.bat again and click Yes."]))
        except OSError as e:
            con.step(3, check("firewall", fw_label, "warn", "couldn't add the rules", [str(e)]))

    # ---- 4. Start now + at every sign-in ----
    if stop_servers(port):
        con.hint("Stopped another OBS Remote that was using port %d." % port)
    proc = start_server(port)
    save_settings(port=port)
    gather(menu=add_start_menu, startup=lambda: args.skip_startup or add_startup(port))
    ok, err = wait_for_page(port, proc)
    if not ok:
        con.step(4, check("server", "OBS Remote server", "fail", "didn't start", why_not_started(port, proc, err)))
        return 1
    ver = version()
    con.step(4, check("server", "OBS Remote server", "ok", "running" + (" (version %s)" % ver if ver else "")
                      + ("" if args.skip_startup else ", starts with Windows")))

    # ---- 5. Where phones can reach it ----
    lan = lan_addresses()

    # Tailscale route: the PC shares its own LAN address (a /32: just this PC) with the tailnet, so a phone with
    # Tailscale on reaches the SAME http://LAN-IP:port/ from anywhere: one QR code, one home-screen icon, one saved
    # login. Tailscale needs it approved once in its admin console (automatic with an autoApprovers policy).
    old = read_route_mark()
    route, route_ok, dup = None, False, None
    if os.path.exists(TS_CLI) and lan and (use_ts or old):
        want = "%s/32" % lan[0]["ip"] if use_ts else ""
        # Another device already sharing this address (e.g. another venue's OBS PC with the same LAN IP)? Tailscale
        # would send phones to only one of them, and both venues' phones would share one icon and login.
        if want:
            dup = next((p for p in ts_status()["peers"] if want in p["routes"]), None)
            if dup:
                con.step(0, check("route", "Tailscale route", "warn", "'%s' already shares %s on your tailnet" % (dup["name"], want),
                                  ["Two PCs with the same address can't both work over Tailscale. Give this PC a different fixed IP",
                                   "in your router (or change the other one), then run Install.bat again."]))
                want = ""
        why = set_route(want, old)
        if why is None:
            if want:
                route = want
            elif old and not dup:
                con.step(0, check("route", "Tailscale route", "info", "removed (%s)" % old))
        elif why == "refused":
            con.step(0, check("route", "Tailscale route", "warn", "Tailscale didn't accept the change",
                              ["Run Install.bat as the Windows user who signed in to Tailscale on this PC."]))
        else:
            con.step(0, check("route", "Tailscale route", "warn", "couldn't read Tailscale's settings",
                              ["Is Tailscale running? Then run Install.bat again."]))

    # Key expiry: Tailscale signs a PC out after ~6 months unless "Disable key expiry" is set on it in the admin
    # console. One visit to this PC's page there covers both that and approving the route; setup waits for both.
    st = ts_status()
    if route:
        route_ok = route_approved(route, st)
    key_ok = not (use_ts and ts["ip"] and os.path.exists(TS_CLI)) or key_expiry_off(st)
    if route and route_ok:
        con.step(0, check("route", "Tailscale route", "ok", "the same address works over Tailscale (%s)" % route))
    if use_ts and ts["ip"] and key_ok:
        con.step(0, check("expiry", "Tailscale key expiry", "ok", "off: this PC stays signed in to Tailscale"))
    if (route and not route_ok) or not key_ok:
        expires = expiry_text(st["key_expiry"])
        if not key_ok:
            con.step(0, check("expiry", "Tailscale key expiry", "warn", "on: this PC drops off Tailscale on " + expires))
        if route and not route_ok:
            con.step(0, check("route", "Tailscale route", "warn", "needs approving once in Tailscale"))
        con.hint("In the page that opens (sign in if asked), on '%s' click Machine settings, then:" % st["name"])
        if not key_ok:
            con.hint("  - Disable key expiry   (so phones can still reach this PC in six months)")
        if route and not route_ok:
            con.hint("  - Edit route settings > tick %s > Save   (so the same code works over Tailscale)" % route)
        os.startfile("https://login.tailscale.com/admin/machines/%s" % ts["ip"])
        print("              Waiting (up to 5 minutes, press Enter to skip) ", end="", flush=True)
        state = {"route": route_ok, "key": key_ok}

        def both():
            s = ts_status()
            state["route"] = state["route"] or (bool(route) and route_approved(route, s))
            state["key"] = state["key"] or key_expiry_off(s)
            return (state["route"] or not route) and state["key"]
        con.wait_enter_or(time.time() + 300, both)
        route_ok, key_ok = state["route"], state["key"]
        if route:
            con.step(0, check("route", "Tailscale route", "ok", "approved: the same address works over Tailscale") if route_ok else
                     check("route", "Tailscale route", "warn", "not approved yet",
                           ["Until it is, phones away from here need the separate Tailscale code. Run Install.bat again to check."]))
        con.step(0, check("expiry", "Tailscale key expiry", "ok", "off: this PC stays signed in to Tailscale") if key_ok else
                 check("expiry", "Tailscale key expiry", "warn",
                       "still on: on %s this PC drops off Tailscale until someone signs in again" % expires,
                       ["Run Install.bat again any time to finish this."]))

    remove_phone_pages()
    con.say()
    con.say("  ALL DONE!", "Green")
    if not lan:
        con.say("   This PC has no local network connection right now, so phones can't reach it yet.", "Yellow")
        con.say("   Connect it to the network, then run Install.bat again.", "Yellow")
    else:
        con.say("  On each phone, on the same Wi-Fi as this PC, scan this code. It opens OBS Remote signed in:")
        con.say()
        con.qr(sign_in_url(lan[0]["ip"], port, ws))
        con.say("        " + page_url(lan[0]["ip"], port), "White")
        for a in lan[1:]:
            con.say("        also: %s   (%s)" % (page_url(a["ip"], port), a["alias"]), "DarkGray")
        con.say("  Then add it to the home screen. iPhone: Share > Add to Home Screen. Android: menu > Add to Home screen.", "DarkGray")
        if route_ok:
            con.say("  Phones with Tailscale on can use this same code and icon from anywhere.", "Cyan")
            if lan[0]["dhcp"]:
                con.say("  Give this PC a fixed IP address in your router (%s): the code and the Tailscale route both use it."
                        % lan[0]["ip"], "Yellow")
        elif use_ts:
            con.say()
            if con.ask("Show the Tailscale code too, for phones away from this Wi-Fi?", False):
                con.say("  Over Tailscale (the phone needs the Tailscale app, signed in to the same account):")
                con.qr(sign_in_url(ts["ip"], port, ws))
                con.say("        " + page_url(ts["ip"], port), "White")

    con.say()
    con.say("  To see the code%s again, open OBS Remote from the Start menu.%s" % ("s" if use_ts and not route_ok else "",
            " The code contains the OBS password: only show it to people who may control OBS." if ws["password"] else ""))
    if not (route_ok and lan and lan[0]["dhcp"]):
        con.say("  Tip: give this PC a fixed IP address in your router, so the code never changes.", "DarkGray")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="core.py", description="OBS Remote setup")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install", help="set up or repair OBS Remote on this PC (asks questions)")
    i.add_argument("--port", type=int, default=None, help="default: the port chosen before, else %d" % DEFAULT_PORT)
    i.add_argument("--skip-firewall", action="store_true")
    i.add_argument("--skip-startup", action="store_true")
    g = i.add_mutually_exclusive_group()
    g.add_argument("--tailscale", action="store_true")
    g.add_argument("--no-tailscale", action="store_true")
    s = sub.add_parser("status", help="print every check as JSON; changes nothing")
    s.add_argument("--port", type=int, default=None)
    sub.add_parser("uninstall", help="stop OBS Remote and remove it from startup, Tailscale and the firewall")
    p = sub.add_parser("panel", help="open the setup window / control panel")
    p.add_argument("--no-window", action="store_true", help="print its address instead of opening a window")
    sub.add_parser("start", help="(installer) if this PC was set up before, run the server from this folder")
    sub.add_parser("stop", help="(installer) stop this folder's server and setup window")
    args = ap.parse_args(argv)
    if args.cmd == "start":
        return start_here()
    if args.cmd == "stop":
        stop_folder()
        return 0
    if args.cmd == "panel":
        import panel
        return panel.main(open_it=not args.no_window)
    try:
        if args.cmd == "install":
            return run_install(args)
        if args.cmd == "status":
            st = status(args.port or saved_port())
            if st["ws"]["password"]:
                st["ws"]["password"] = "(set)"  # this is for reading; the console may be on a shared screen
            print(json.dumps(st, indent=2))
            return 0
        uninstall()
        return 0
    except (KeyboardInterrupt, EOFError):
        print("\nSetup stopped.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
