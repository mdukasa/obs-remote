"""Go live on YouTube from the phone when OBS is signed in to a YouTube account.

In that mode OBS won't start streaming until someone fills in its "YouTube Broadcast Setup" dialog on the PC,
and obs-websocket has no request for it. The phone saves its form as OBS's remembered YouTube settings
(SetProfileParameter, category YouTube), then asks this server to go live: youtube.ps1 opens the dialog with
OBS's Manage Broadcast button, checks it shows those settings, and clicks "Create broadcast and start streaming",
using Windows UI Automation (no extra software). Setups with a stream key never need this.
"""
import json
import os
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
_lock = threading.Lock()
LOG = os.path.join(HERE, "youtube.log")


def log(line):
    """Keep the last 200 lines: what each Go live asked for and what happened (the phone only shows the outcome)."""
    try:
        old = open(LOG, encoding="utf-8").read().splitlines()[-199:] if os.path.exists(LOG) else []
        with open(LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(old + [time.strftime("%Y-%m-%d %H:%M:%S  ") + line]) + "\n")
    except OSError:
        pass


def go_live(form):
    """form: title, description, privacy, category, latency (OBS's English names), kids, dvr; dryRun to fill in and
    check the dialog, then cancel it (testing). Returns {ok, error}."""
    if os.name != "nt":
        return {"ok": False, "error": "Only works with OBS on Windows."}
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "Already setting up the broadcast."}
    try:
        want = {k: form.get(k) for k in ("title", "description", "privacy", "category", "latency")}
        want = {k: str(v or "") for k, v in want.items()}
        want.update(kids=bool(form.get("kids")), dvr=bool(form.get("dvr")))
        env = dict(os.environ, OBS_REMOTE_YOUTUBE=json.dumps(want))
        try:
            r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                "-File", os.path.join(HERE, "youtube.ps1")] + (["-DryRun"] if form.get("dryRun") else []), env=env, capture_output=True,
                               timeout=90, creationflags=0x08000000)  # CREATE_NO_WINDOW
        except subprocess.TimeoutExpired:
            log("timed out after 90 s")
            return {"ok": False, "error": "OBS didn't respond. Check the PC."}
        out = r.stdout.decode("ascii", "replace").strip().splitlines()
        err = r.stderr.decode("utf-8", "replace").strip()
        try:
            res = json.loads(out[-1])
        except (IndexError, ValueError):
            res = {"ok": False, "error": "Couldn't work OBS's YouTube dialog: " + (err.splitlines()[0] if err else "no answer")}
        log(("dry run " if form.get("dryRun") else "") + json.dumps({**want, "result": res}, ensure_ascii=False)
            + (("\n    " + err.replace("\n", "\n    ")) if err else ""))
        return res
    finally:
        _lock.release()
