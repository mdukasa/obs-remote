"""OBS Remote's setup window and control panel:  python setup/core.py panel  (Start menu > OBS Remote).

A small web page for this PC only. It listens on 127.0.0.1 at a random port, every request needs a random token
(in the window's address), and the Host header must be 127.0.0.1, so no other device, and no web page using DNS
tricks, can reach it. It opens in an Edge app window (else the default browser). Every check and change comes
from core.py; changes run one at a time in the background while the page shows their progress.
One panel at a time: opening it again brings up the same one. It exits about a minute after its window closes.
"""
import http.server
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import urllib.request

import core
import paths
import qr

PAGE = os.path.join(core.SETUP, "panel.html")
ICON_SVG = os.path.join(core.ROOT, "www", "icon.svg")
INSTANCE = paths.data("panel.json")  # {port, token, pid} of the panel that's open
TOKEN = secrets.token_urlsafe(24)
IDLE_EXIT = 75  # seconds without a request from the window (it asks every 10 s)
LOG = paths.data("panel.log")
_seen = {"t": time.time()}
_cache = {}
_lock = threading.Lock()
JOB = {"name": None, "running": False, "lines": [], "ok": None, "error": None, "done": None, "seq": 0}


def log(text):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text))
    except OSError:
        pass


def cached(name, fn, ttl):
    """Checks that rarely change (firewall rules, addresses, obs-ptz's version) are re-read at most every ttl s,
    or right after a change (forget())."""
    v = _cache.get(name)
    if v and time.time() - v[0] < ttl:
        return v[1]
    r = fn()
    _cache[name] = (time.time(), r)
    return r


def forget():
    _cache.clear()


def local_get(port, path, timeout=2):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://127.0.0.1:%d%s" % (port, path), timeout=timeout) as r:
        return json.loads(r.read())


def phones(port):
    try:
        return local_get(port, "/api/phones").get("phones") or []
    except Exception:
        return []


# ---- status ------------------------------------------------------------------------------------------------------

def status():
    port = core.saved_port()
    ws = core.ws_status()
    g = core.gather(ts=core.ts_status,
                    rules=lambda: cached("rules", core.firewall_rules, 120),
                    lan=lambda: cached("lan", core.lan_addresses, 60),
                    ptz=lambda: cached("ptz", core.ptz_status, 300),
                    page=lambda: core.test_page(port),
                    running=core.obs_running,
                    probe=lambda: core.obs_probe(ws, timeout=3),
                    phones=lambda: phones(port))
    ts, rules, lan = g["ts"], g["rules"], g["lan"]
    chosen = core.rules_allow_tailscale(rules)
    route = core.read_route_mark()
    want = "%s/32" % lan[0]["ip"] if lan else None
    dup = next((p["name"] for p in ts["peers"] if want and want in p["routes"]), None)
    page_ok, page_err = g["page"]
    lan_ips = {a["ip"] for a in lan}
    for p in g["phones"]:
        p["here"] = p["ip"] in lan_ips  # this PC's own address: a browser here (or Tailscale's route, if p["tailscale"])
        # Straight to this PC's 100.x address, a phone comes from its own Tailscale address, so it has a name.
        # Through the LAN-address route, Tailscale hands it over from this PC's address, so it hasn't.
        p["name"] = next((q["name"] for q in ts["peers"] if p["ip"] in q["ips"]), None)
    codes = core.phone_codes(lan, ts["ip"] if chosen else None, port, ws)
    for c in codes:
        c["svg"] = qr.svg(c.pop("qr"), scale=7, logo=True)  # the app icon in the middle
    with _lock:
        job = dict(JOB, lines=list(JOB["lines"]))
    return {
        "version": core.version(), "port": port, "folder": core.ROOT, "data": paths.DATA,
        "obs": dict(g["probe"], running=g["running"]),
        "ws": {k: ws[k] for k in ("config", "enabled", "port", "auth")}, "password": ws["password"],
        "ptz": g["ptz"],
        "ts": {"installed": ts["installed"], "running": ts["running"], "ip": ts["ip"], "name": ts["name"],
               "chosen": chosen, "route": route or None, "want": want,
               "route_ok": bool(route) and route in ts["routes"],
               "stale": chosen and bool(want) and route != want and not dup, "dup": dup if chosen else None,
               "key_off": not ts["key_expiry"], "expires": core.expiry_text(ts["key_expiry"])},
        "firewall": {"ok": core.firewall_ok(rules, port, ws["port"], chosen), "exists": any(rules.values())},
        "server": {"answering": page_ok, "error": page_err, "startup": os.path.exists(core.startup_shortcut()),
                   "startmenu": os.path.exists(core.start_menu_shortcut())},
        "lan": lan, "codes": codes, "phones": g["phones"], "job": job,
    }


# ---- actions (one at a time, in the background) ------------------------------------------------------------------

class Failed(Exception):
    """An action stopped; the message says why and what to do."""


def say(text):
    with _lock:
        JOB["lines"].append(text)


def start_job(name, fn):
    with _lock:
        if JOB["running"]:
            return False
        JOB.update(name=name, running=True, lines=[], ok=None, error=None, done=None, seq=JOB["seq"] + 1)

    def run():
        try:
            JOB["done"] = fn() or "Done."
            JOB["ok"] = True
        except Failed as e:
            JOB.update(ok=False, error=str(e))
        except core.Declined:
            JOB.update(ok=False, error="Windows asked for permission and No was clicked, so nothing changed. Try again and click Yes.")
        except Exception as e:
            log("%s failed:\n%s" % (name, traceback.format_exc()))
            JOB.update(ok=False, error="Something went wrong: %s" % (str(e) or type(e).__name__))
        finally:
            forget()
            with _lock:
                JOB["running"] = False
    threading.Thread(target=run, daemon=True).start()
    return True


def with_obs_closed(what, fn):
    """Changes to OBS's settings and plugins need OBS closed: close it the normal way, run fn, open OBS again.
    Refuses while OBS is streaming or recording."""
    if not core.obs_running():
        return fn()
    p = core.obs_probe(core.ws_status())
    if p["streaming"] or p["recording"]:
        raise Failed("OBS is %s right now. %s needs OBS closed for a moment, so try again when you've finished."
                     % ("streaming" if p["streaming"] else "recording", what))
    exe = core.obs_path()
    say("Closing OBS...")
    if not core.close_obs():
        raise Failed("OBS didn't close. It may be asking something on screen, or be hidden in the tray. "
                     "Close OBS yourself, then try again.")
    try:
        return fn()
    finally:
        if core.open_obs(exe):
            say("Opened OBS again.")


def act_ws_on():
    def go():
        say("Turning on OBS's WebSocket server...")
        core.enable_ws()
    with_obs_closed("Turning on remote control", go)
    return "OBS remote control is on."


def act_ptz():
    say("Looking for the newest obs-ptz...")
    try:
        rel = core.find_ptz_release()
    except Exception:
        rel = None
    if not rel:
        raise Failed("Couldn't reach GitHub. Get obs-ptz from https://github.com/glikely/obs-ptz/releases")

    def go():
        why = core.install_ptz(rel, say=say)
        if why:
            raise Failed(why)
    with_obs_closed("Installing obs-ptz", go)
    return ("obs-ptz %s is installed. In OBS, open the PTZ Controls dock's settings and set Websocket access to Control."
            % rel["tag"])


def act_ts_install():
    say("Installing Tailscale. Windows may ask for permission: click Yes.")
    if not core.install_tailscale(quiet=True):
        raise Failed("Tailscale didn't install. Get it from https://tailscale.com/download, then come back here.")
    return "Tailscale is open: sign in with its window, or its icon by the clock."


def act_ts_open():
    if not os.path.exists(core.TS_GUI):
        raise Failed("Tailscale isn't installed.")
    subprocess.Popen([core.TS_GUI], creationflags=core.DETACHED, close_fds=True)
    return "Tailscale is open: sign in with its window, or its icon by the clock."


def act_ts_admin():
    st = core.ts_status()
    os.startfile("https://login.tailscale.com/admin/machines/%s" % (st["ip"] or ""))
    return ("In the Tailscale page (sign in if asked), on '%s' click Machine settings, then Edit route settings > "
            "tick the address > Save, and Disable key expiry. This window notices by itself." % st["name"])


def act_ts_use(on):
    port, ws, st = core.saved_port(), core.ws_status(), core.ts_status()
    if on and not st["ip"]:
        raise Failed("Sign in to Tailscale on this PC first.")
    say("Windows will ask for permission to update the firewall: click Yes.")
    code = core.apply_firewall(port, ws["port"], on)
    if code:
        raise Failed("Couldn't update the firewall (code %d)." % code)
    lan, old = core.lan_addresses(), core.read_route_mark()
    want = "%s/32" % lan[0]["ip"] if on and lan else ""
    dup = next((p["name"] for p in st["peers"] if want and want in p["routes"]), None)
    if dup:
        want = ""
    if os.path.exists(core.TS_CLI) and (want or old):
        say("Sharing this PC's address with your tailnet..." if want else "Stopping sharing this PC's address...")
        why = core.set_route(want, old)
        if why == "refused":
            raise Failed("Tailscale didn't accept the change. Open this window as the Windows user who signed in to Tailscale.")
        if why:
            raise Failed("Couldn't read Tailscale's settings. Is Tailscale running?")
    if not on:
        return "Phones can no longer connect over Tailscale."
    if dup:
        raise Failed("'%s' already shares this address on your tailnet. Two PCs with the same address can't both work "
                     "over Tailscale: give this PC a different fixed IP in your router (or change the other one)." % dup)
    st = core.ts_status()
    if (want and want not in st["routes"]) or st["key_expiry"]:
        return act_ts_admin()
    return "Phones with Tailscale can use the same code from anywhere."


def act_firewall():
    port, ws = core.saved_port(), core.ws_status()
    say("Windows will ask for permission: click Yes.")
    ts = core.rules_allow_tailscale(core.firewall_rules())
    code = core.apply_firewall(port, ws["port"], ts)
    if code:
        raise Failed("Couldn't add the firewall rules (code %d)." % code)
    return "Phones on this network%s can connect." % (" and on your tailnet" if ts else "")


def act_server():
    port = core.saved_port()
    say("Starting OBS Remote's server...")
    others = core.stop_servers(port)
    if others:
        say("Stopped another OBS Remote that was using port %d." % port)
    proc = core.start_server(port)
    core.save_settings(port=port)
    core.gather(menu=core.add_start_menu, startup=lambda: core.add_startup(port))
    core.remove_phone_pages()
    ok, err = core.wait_for_page(port, proc)
    if not ok:
        raise Failed(" ".join(core.why_not_started(port, proc, err)))
    return "OBS Remote is running, and starts whenever this PC signs in."


def act_uninstall():
    unins = os.path.join(core.ROOT, "unins000.exe")
    if os.path.exists(unins) and os.path.exists(os.path.join(core.ROOT, "runtime")):
        # Installed with Setup.exe: Windows' own uninstaller, so it leaves the Apps list too. It runs core.py
        # uninstall (which also closes this window) and then deletes the folder.
        subprocess.Popen([unins], creationflags=core.DETACHED, close_fds=True)
        return "Windows' uninstaller for OBS Remote is open: confirm there. This window closes by itself."
    core.uninstall(say=say, closing=False)
    return ("OBS Remote is uninstalled. You can close this window and delete the program folder. Its logs are in %s."
            % paths.DATA)


ACTIONS = {
    "ws_on": ("Turning on OBS remote control", act_ws_on),
    "ptz": ("Installing obs-ptz", act_ptz),
    "ts_install": ("Installing Tailscale", act_ts_install),
    "ts_open": ("Opening Tailscale", act_ts_open),
    "ts_admin": ("Opening Tailscale's admin page", act_ts_admin),
    "ts_on": ("Setting up Tailscale", lambda: act_ts_use(True)),
    "ts_off": ("Turning off Tailscale", lambda: act_ts_use(False)),
    "firewall": ("Opening the firewall to phones", act_firewall),
    "server": ("Starting OBS Remote", act_server),
    "uninstall": ("Uninstalling OBS Remote", act_uninstall),
}


# ---- the web server ----------------------------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def reply(self, code, body, ctype="application/json"):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; "
                         "script-src 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        """Only this PC (the socket is 127.0.0.1-only), only with Host 127.0.0.1:port (no DNS rebinding), and only
        with the token."""
        port = self.server.server_address[1]
        if self.headers.get("Host") not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
            return False
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        tok = self.headers.get("X-Token") or (q.get("t") or [""])[0]
        return secrets.compare_digest(tok, TOKEN)

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/icon.svg":
            with open(ICON_SVG, "rb") as f:
                return self.reply(200, f.read(), "image/svg+xml")
        if not self.allowed():
            return self.reply(403, {"error": "Not allowed"})
        _seen["t"] = time.time()
        if path in ("/", "/index.html"):
            with open(PAGE, "rb") as f:
                return self.reply(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/ping":
            return self.reply(200, {"ok": True})
        if path == "/api/status":
            if "fresh=1" in self.path:
                forget()
            try:
                return self.reply(200, status())
            except Exception as e:
                log("status failed:\n" + traceback.format_exc())
                return self.reply(500, {"error": str(e)})
        if path == "/api/job":
            with _lock:
                return self.reply(200, dict(JOB, lines=list(JOB["lines"])))
        self.reply(404, {"error": "Not found"})

    def do_POST(self):
        if not self.allowed():
            return self.reply(403, {"error": "Not allowed"})
        _seen["t"] = time.time()
        if urllib.parse.urlsplit(self.path).path != "/api/action":
            return self.reply(404, {"error": "Not found"})
        try:
            name = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 1000)) or b"{}").get("name")
        except ValueError:
            name = None
        if name not in ACTIONS:
            return self.reply(400, {"error": "Unknown action"})
        label, fn = ACTIONS[name]
        if not start_job(label, fn):
            return self.reply(409, {"error": "Something else is still running."})
        self.reply(200, {"ok": True})


# Browsers that open a page as an app window (no tabs or address bar) with --app=URL.
APP_BROWSERS = {"msedge.exe", "chrome.exe", "brave.exe", "vivaldi.exe", "chromium.exe", "thorium.exe"}


def _reg(root, path, name=None):
    """A registry value (name=None: the default value), or None."""
    import winreg
    try:
        with winreg.OpenKey(root, path) as k:
            return winreg.QueryValueEx(k, name or "")[0]
    except OSError:
        return None


def edge_redirected():
    """Is something taking over launches of msedge.exe? Tools like MSEdgeRedirect set a "Debugger" for it in
    Image File Execution Options (on the key or one of its filter subkeys), so starting Edge runs them instead and
    an --app window never appears (seen 2026-11-24). Its other mode watches for Edge from a background program, so
    an installed MSEdgeRedirect counts too."""
    import winreg
    ifeo = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\msedge.exe"
    for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ifeo, 0, winreg.KEY_READ | view) as k:
                keys = [k]
                i = 0
                while True:
                    try:
                        keys.append(winreg.OpenKey(k, winreg.EnumKey(k, i)))
                    except OSError:
                        break
                    i += 1
                for key in keys:
                    try:
                        if winreg.QueryValueEx(key, "Debugger")[0]:
                            return True
                    except OSError:
                        pass
        except OSError:
            pass
    return any(os.path.exists(os.path.join(base, "MSEdgeRedirect", "MSEdgeRedirect.exe"))
               for base in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                            os.environ.get("LOCALAPPDATA", ""), os.environ.get("APPDATA", "")) if base)


def default_browser():
    """The program the user picked to open web links, or None."""
    import re
    import winreg
    prog = _reg(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice", "ProgId")
    cmd = prog and (_reg(winreg.HKEY_CURRENT_USER, r"Software\Classes\%s\shell\open\command" % prog)
                    or _reg(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Classes\%s\shell\open\command" % prog))
    m = cmd and re.match(r'\s*"([^"]+)"|\s*(\S+)', cmd)
    exe = m and (m.group(1) or m.group(2))
    return exe if exe and os.path.exists(exe) else None


def find_browser():
    """A browser to open the setup window as an app window: the user's default browser if it can, else Edge (unless
    something redirects it), else Chrome. None: just open the page in the default browser."""
    redirected = edge_redirected()
    ok = lambda p: p and os.path.basename(p).lower() in APP_BROWSERS and not (
        redirected and os.path.basename(p).lower() == "msedge.exe")
    d = default_browser()
    if ok(d):
        return d
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            p = os.path.join(base or "", rel)
            if base and os.path.exists(p) and ok(p):
                return p
    return None


def open_window(url):
    """An app window (no tabs or address bar) if a suitable browser is there, else a tab in the default browser."""
    b = find_browser()
    if b:
        subprocess.Popen([b, "--app=" + url, "--window-size=880,980"], creationflags=core.DETACHED, close_fds=True)
    else:
        os.startfile(url)


def code_time():
    """When this copy's program files last changed (an update, or an edit in a dev folder)."""
    return max(os.path.getmtime(os.path.join(core.SETUP, n)) for n in ("panel.py", "core.py", "qr.py"))


def running_instance():
    """The URL of a panel that's already open, or None. A panel started before its program files last changed (an
    update replaced them) is stopped instead, so the new code runs: a running Python keeps the old code loaded."""
    try:
        with open(INSTANCE, encoding="utf-8") as f:
            inst = json.load(f)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request("http://127.0.0.1:%d/api/ping" % inst["port"], headers={"X-Token": inst["token"]})
        with opener.open(req, timeout=2) as r:
            if r.status != 200:
                return None
        if inst.get("root") != core.ROOT or inst.get("started", 0) < code_time():
            stop_instance(inst)
            return None
        return "http://127.0.0.1:%d/?t=%s" % (inst["port"], inst["token"])
    except Exception:
        pass
    return None


def stop_instance(inst=None):
    """Stop the open panel by the process id it wrote down (its command line may hold only a relative path)."""
    try:
        if inst is None:
            with open(INSTANCE, encoding="utf-8") as f:
                inst = json.load(f)
        pid = int(inst["pid"])
        if pid != os.getpid():
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=core.NO_WINDOW)
    except (OSError, ValueError, KeyError, TypeError):
        pass


def main(open_it=True):
    if sys.stderr is None:  # pythonw: keep errors in the log
        sys.stderr = open(LOG, "a", encoding="utf-8")
    url = running_instance()
    if url:
        if open_it:
            open_window(url)
        else:
            print(url, flush=True)
        return 0
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    with open(INSTANCE, "w", encoding="utf-8") as f:
        json.dump({"port": port, "token": TOKEN, "pid": os.getpid(), "root": core.ROOT, "started": time.time()}, f)
    url = "http://127.0.0.1:%d/?t=%s" % (port, TOKEN)

    def idle():
        while True:
            time.sleep(5)
            if not JOB["running"] and time.time() - _seen["t"] > IDLE_EXIT:
                srv.shutdown()
                return
    threading.Thread(target=idle, daemon=True).start()
    if open_it:
        open_window(url)
    else:
        print(url, flush=True)
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
        try:
            with open(INSTANCE, encoding="utf-8") as f:
                mine = json.load(f).get("pid") == os.getpid()
            if mine:  # (not while it's open: Windows can't delete an open file)
                os.remove(INSTANCE)
        except (OSError, ValueError):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(open_it="--no-window" not in sys.argv))
