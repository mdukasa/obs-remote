"""OBS Remote: a tiny web server for the phone control page.

The page talks straight to obs-websocket (normally port 4455) on this PC, so this
server only hands out the files in www/. Python standard library only.

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
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

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
KEEP = {"Phone address.txt"}  # local files an update never touches
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


RESTART = threading.Event()


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
            rel, cur = latest_release(), local_version()
            return self.send_json(200, {"version": cur, "latest": rel and rel["version"],
                                        "notes": rel and rel["notes"], "url": rel and rel["url"],
                                        "update": bool(rel) and vtuple(rel["version"]) > vtuple(cur),
                                        "blocked": update_blocker()})
        return super().do_GET()

    def do_POST(self):
        # The custom header can't be sent cross-site without a CORS preflight, which this server never allows,
        # so only the app's own page can start an update.
        if self.path != "/api/update" or self.headers.get("X-OBS-Remote") != "1":
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

if __name__ == "__main__":
    srv = None
    for attempt in range(20):  # after an update the old copy may still be letting go of the port
        try:
            srv = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), functools.partial(Handler, directory=ROOT))
            break
        except OSError as e:
            err = e
            time.sleep(0.5)
    if srv is None:
        sys.exit(f"Can't use port {PORT} ({err}). Is OBS Remote already running?")
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
