"""OBS Remote: a tiny web server for the phone control page.

The page talks straight to obs-websocket (normally port 4455) on this PC. This server hands out the
files in www/, installs updates, runs the frozen-camera watcher (autofix.py) and, for phones that turn
on Listen, streams OBS's monitoring device (listen.py). Python standard library only.

    python server.py            # serves on port 8765
    python server.py 9000       # another port
    python server.py update     # install the latest GitHub release into this folder, then exit
    python server.py update v1.3.0-beta1   # install a specific release or tag (e.g. a pre-release to test)
"""
import functools
import http.server
import io
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

import autofix
import listen
import youtube

UPDATE_ONLY = len(sys.argv) > 1 and sys.argv[1].lower() == "update"
UPDATE_TAG = sys.argv[2] if UPDATE_ONLY and len(sys.argv) > 2 else None
PORT = int(sys.argv[1]) if len(sys.argv) > 1 and not UPDATE_ONLY else int(os.environ.get("OBS_REMOTE_PORT", "8765"))
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "www")

# Updates come only from this repository's GitHub Releases, over HTTPS. Pushing to main ships nothing:
# installed copies only move when a release is published (pre-releases and drafts are skipped).
REPO = "mdukasa/obs-remote"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/tags/"  # + tag
API_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "obs-remote"}
KEEP = {"Phone address.txt", "Phone address.html", "autofix.log", "youtube.log"}  # local files an update never touches
_latest = {"at": 0.0, "release": None}


def fetch(url, timeout, headers=None):
    """GET a URL. Python's own TLS can fail on Windows when a site's certificate chain needs an intermediate that
    Windows would fetch by itself (seen with GitHub's Let's Encrypt chain), so fall back to Windows' curl.exe,
    which uses the Windows certificate store."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
            return r.read()
    except OSError as e:
        if os.name != "nt" or "CERTIFICATE" not in str(e).upper():
            raise
    curl = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "curl.exe")
    hdrs = [x for k, v in (headers or {}).items() for x in ("-H", f"{k}: {v}")]
    p = subprocess.run([curl, "-fsSL", "--max-time", str(timeout)] + hdrs + [url], capture_output=True,
                       creationflags=0x08000000)  # CREATE_NO_WINDOW: no console flash under pythonw
    if p.returncode:
        raise OSError(p.stderr.decode("utf-8", "replace").strip() or f"curl exit {p.returncode}")
    return p.stdout


def local_version():
    try:
        with open(os.path.join(HERE, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "0"


def vtuple(v):
    try:
        return tuple(int(x) for x in v.lstrip("vV").split("."))
    except (AttributeError, ValueError):
        return (0,)


def latest_release(fresh=False):
    """{tag, version, notes, url} of the newest published release, cached for 10 minutes.
    None if GitHub can't be reached or nothing has been released."""
    if fresh or time.time() - _latest["at"] > 600 or _latest["release"] is None:
        try:
            r = json.loads(fetch(LATEST_URL, 10, API_HEADERS))
            _latest["release"] = {"tag": r["tag_name"], "version": r["tag_name"].lstrip("vV"),
                                  "notes": (r.get("body") or "").strip()[:2000], "url": r.get("html_url")}
        except (OSError, ValueError, KeyError, TypeError):
            _latest["release"] = None
        _latest["at"] = time.time()
    return _latest["release"]


def update_blocker():
    """Why this copy can't update itself, or None."""
    if os.path.isdir(os.path.join(HERE, ".git")):
        return "This copy is a git checkout. Update it with git pull."
    return None


def install_update(tag=None):
    """Download a release (default: the latest) and copy it over this folder. Returns the new version."""
    if not tag:
        rel = latest_release(fresh=True)
        if not rel:
            raise RuntimeError("Couldn't find a release on GitHub.")
        tag = rel["tag"]
    data = fetch(ZIP_URL + tag, 60)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    top = names[0].split("/")[0] + "/"  # GitHub zips have one top folder, e.g. obs-remote-1.2.0/
    if not all(n.startswith(top) for n in names) or top + "server.py" not in names or top + "www/index.html" not in names:
        raise RuntimeError("The download doesn't look like OBS Remote.")
    new_version = z.read(top + "VERSION").decode("utf-8").strip() if top + "VERSION" in names else tag.lstrip("vV")
    for n in names:
        rel = n[len(top):]
        if not rel or rel in KEEP or rel.startswith(".git/"):
            continue
        dest = os.path.normpath(os.path.join(HERE, rel))
        if not dest.startswith(HERE + os.sep):
            continue  # never write outside this folder
        if n.endswith("/"):
            os.makedirs(dest, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".new"
        with z.open(n) as src, open(tmp, "wb") as out:
            shutil.copyfileobj(src, out)
        os.replace(tmp, dest)
    return new_version


SCENES_DIR = os.path.join(os.environ.get("APPDATA", ""), "obs-studio", "basic", "scenes")
_mixer = {}  # path -> (mtime, collection name, hidden source names)


def mixer_hidden(collection):
    """Audio sources hidden in OBS's Audio Mixer (right-click > Hide) in this scene collection.
    obs-websocket doesn't expose that flag; OBS keeps it in the scene collection file as the source's
    private_settings.mixer_hidden. The file is rewritten whenever OBS saves the collection."""
    try:
        files = [os.path.join(SCENES_DIR, f) for f in os.listdir(SCENES_DIR) if f.lower().endswith(".json")]
    except OSError:
        return []
    for path in files:
        try:
            mtime = os.path.getmtime(path)
            if path not in _mixer or _mixer[path][0] != mtime:
                with open(path, encoding="utf-8") as f:
                    d = json.load(f)
                names = [s.get("name") for s in d.get("sources", [])
                         if (s.get("private_settings") or {}).get("mixer_hidden")]
                _mixer[path] = (mtime, d.get("name"), names)
            if _mixer[path][1] == collection:
                return _mixer[path][2]
        except (OSError, ValueError, AttributeError):
            continue
    return []


RESTART = threading.Event()


# ---- start OBS from the phone (when it's closed or has crashed) ----------------------------------------
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def obs_running():
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH", "/FO", "CSV"], capture_output=True,
                             text=True, timeout=10, creationflags=NO_WINDOW).stdout
        return "obs64.exe" in out.lower()
    except (OSError, subprocess.SubprocessError):
        return None


def obs_exe():
    """obs64.exe, from OBS's installer entry in the registry, else the usual folder."""
    if os.name != "nt":
        return None
    dirs = []
    try:
        import winreg
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio", 0, winreg.KEY_READ | view) as k:
                    dirs.append(winreg.QueryValueEx(k, "")[0])
            except OSError:
                pass
    except ImportError:
        pass
    dirs += [os.path.join(os.environ.get(v, ""), "obs-studio") for v in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")]
    for d in dirs:
        exe = os.path.join(d, "bin", "64bit", "obs64.exe")
        if d and os.path.isfile(exe):
            return exe
    return None


def clear_crash_markers():
    """OBS 32 writes %APPDATA%/obs-studio/.sentinel/run_<id> while it runs and deletes it on a clean exit. A file
    left there makes the next start ask "OBS Studio Crash Detected - Run in Safe Mode?", and waits for a click
    nobody at the PC may give. Only called while OBS isn't running, so any such file is from a crash."""
    d = os.path.join(os.environ.get("APPDATA", ""), "obs-studio", ".sentinel")
    try:
        for name in os.listdir(d):
            if name.startswith("run_"):
                try:
                    os.remove(os.path.join(d, name))
                except OSError:
                    pass
    except OSError:
        pass


def start_obs():
    exe = obs_exe()
    if not exe:
        raise OSError("OBS isn't installed in the usual place on this PC")
    clear_crash_markers()
    # Run from its own folder, as its shortcut does. --disable-shutdown-check did the same job before OBS 32
    # (which ignores it); kept for older OBS versions.
    subprocess.Popen([exe, "--disable-shutdown-check"], cwd=os.path.dirname(exe), close_fds=True,
                     creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def restart_later(srv):
    """Stop serving; the main program then starts the new server.py (see the bottom of this file).
    The relaunch must not happen in this thread: once serve_forever() returns the program ends, which would kill it."""
    def go():
        time.sleep(0.5)  # let the reply reach the phone
        RESTART.set()
        srv.shutdown()
    threading.Thread(target=go).start()


def relaunch():
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")] + sys.argv[1:], cwd=HERE,
                     creationflags=flags, close_fds=True)


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".webmanifest": "application/manifest+json", ".svg": "image/svg+xml"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/version":
            # ?fresh=1 is the app's "Check for updates" button. GitHub allows 60 unauthenticated requests an
            # hour, so a fresh check still reuses an answer that is under 15 seconds old.
            fresh = "fresh=1" in self.path and time.time() - _latest["at"] > 15
            rel, cur = latest_release(fresh), local_version()
            return self.send_json(200, {"version": cur, "latest": rel and rel["version"],
                                        "notes": rel and rel["notes"], "url": rel and rel["url"],
                                        "update": bool(rel) and vtuple(rel["version"]) > vtuple(cur),
                                        "blocked": update_blocker()})
        if self.path.split("?")[0] == "/api/autofix":
            return self.send_json(200, {**autofix.STATE, "events": list(autofix.EVENTS)})
        if self.path.split("?")[0] == "/api/mixer-hidden":
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            return self.send_json(200, {"hidden": mixer_hidden((q.get("collection") or [""])[0])})
        if self.path.split("?")[0] == "/api/obs":
            return self.send_json(200, {"running": obs_running(), "canStart": bool(obs_exe())})
        if self.path.split("?")[0] == "/api/listen-state":
            dev = listen.STATE["device"]
            if not dev and os.name == "nt":
                try:
                    dev = listen.STATE["device"] = listen.monitoring_device()[1]
                except Exception:
                    pass
            return self.send_json(200, {"device": dev, "error": listen.STATE["error"],
                                        "listeners": len(listen.LISTENERS), "supported": os.name == "nt"})
        if self.path.split("?")[0] == "/api/listen":
            return self.listen()
        return super().do_GET()

    def listen(self):
        """Stream OBS's monitoring device as raw 24 kHz mono s16le until the phone stops (see listen.py)."""
        if os.name != "nt":
            return self.send_json(501, {"error": "Listening needs Windows"})
        if not listen.key_ok(self.headers.get("X-OBS-Remote-Key")):
            return self.send_json(403, {"error": "Wrong OBS websocket password"})
        q = listen.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.close_connection = True
            while True:
                try:
                    pcm = q.get(timeout=5)
                except queue.Empty:
                    break
                if pcm is None:  # capture failed; the phone reads why from /api/listen-state
                    break
                self.wfile.write(pcm)
                self.wfile.flush()
        except OSError:  # the phone went away
            pass
        finally:
            listen.unsubscribe(q)

    def do_POST(self):
        # The custom header can't be sent cross-site without a CORS preflight, which this server never allows,
        # so only the app's own page can start an update or OBS.
        if self.headers.get("X-OBS-Remote") != "1":
            return self.send_json(403, {"error": "Not allowed"})
        if self.path == "/api/obs/start":
            # Starting OBS needs the same key as Listen: proof the phone knows OBS's websocket password.
            if not listen.key_ok(self.headers.get("X-OBS-Remote-Key")):
                return self.send_json(403, {"error": "Wrong OBS websocket password"})
            if obs_running():
                return self.send_json(409, {"error": "OBS is already running"})
            try:
                start_obs()
            except OSError as e:
                return self.send_json(500, {"error": str(e)})
            return self.send_json(200, {"ok": True})
        if self.path == "/api/youtube/golive":
            # Fills in OBS's YouTube Broadcast Setup dialog on this PC (youtube.py). Same key as Start OBS.
            if not listen.key_ok(self.headers.get("X-OBS-Remote-Key")):
                return self.send_json(403, {"error": "Wrong OBS websocket password"})
            try:
                form = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 20000)) or b"{}")
            except ValueError:
                return self.send_json(400, {"error": "Bad request"})
            r = youtube.go_live(form if isinstance(form, dict) else {})
            return self.send_json(200 if r.get("ok") else 409, r)
        if self.path != "/api/update":
            return self.send_json(403, {"error": "Not allowed"})
        why = update_blocker()
        if why:
            return self.send_json(409, {"error": why})
        try:
            v = install_update()
        except Exception as e:  # report any failure to the phone; the old files stay unless replaced
            return self.send_json(500, {"error": f"Update failed: {e}"})
        _latest["at"] = 0
        self.send_json(200, {"ok": True, "version": v})
        restart_later(self.server)

    def log_message(self, fmt, *args):  # quiet: one line per page load only
        if self.path in ("/", "/index.html") and sys.stderr:
            sys.stderr.write("%s  %s\n" % (self.address_string(), fmt % args))


def lan_ips():
    """This PC's LAN addresses, best guess first."""
    ips = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # UDP connect sends nothing; it only picks the outgoing interface
        ips.append(s.getsockname()[0])
    except OSError:
        pass
    finally:
        s.close()
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if ip not in ips and not ip.startswith(("127.", "169.254.")):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


if __name__ == "__main__" and UPDATE_ONLY:
    why = update_blocker()
    if why:
        sys.exit(why)
    print(f"Updating OBS Remote {local_version()} from GitHub {UPDATE_TAG or 'latest release'}...")
    print(f"Now at version {install_update(UPDATE_TAG)}. Run Install.bat to restart it.")
    sys.exit(0)

class Server(http.server.ThreadingHTTPServer):
    # http.server turns on SO_REUSEADDR. On Windows that lets this server share a port another program already
    # listens on, and that program then gets the requests (seen: a stray Python script answering 501 on 8765).
    # Without it, Windows refuses a taken port, and the error below says so.
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False


def port_taken():
    """Is something already answering on this port? (Catches a program bound to 127.0.0.1 only.)"""
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    srv, err = None, None
    for attempt in range(20):  # after an update the old copy may still be letting go of the port
        try:
            if port_taken():
                raise OSError("another program is answering on it")
            srv = Server(("0.0.0.0", PORT), functools.partial(Handler, directory=ROOT))
            break
        except OSError as e:
            err = e
            time.sleep(0.5)
    if srv is None:
        sys.exit(f"Can't use port {PORT}: {err}. Close the program using it, or run Install.bat -Port 8766.")
    autofix.start()
    if sys.stdout:
        print("OBS Remote is running. On your phone (same Wi-Fi), open:")
        for ip in lan_ips():
            print(f"    http://{ip}:{PORT}/")
        print("Press Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    srv.server_close()
    if RESTART.is_set():
        relaunch()
