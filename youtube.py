"""Go live on YouTube from the phone when OBS is signed in to a YouTube account.

In that mode OBS won't start streaming until a broadcast is set up in its "YouTube Broadcast Setup" dialog on the
PC, and obs-websocket has no request for it. Two cases:

- A broadcast is already set up (someone used Manage Broadcast on the PC: created one, or picked a scheduled one).
  OBS then streams to it with a plain StartStream, so the phone just starts. OBS doesn't report this state, so a
  watcher here remembers the broadcast id of the last stream: setting up a broadcast puts a new broadcast_id in
  OBS's stream settings, so a different id that hasn't streamed yet means one is waiting. OBS forgets a set-up
  broadcast when it restarts, so the watcher starts afresh then.
- Otherwise the phone asks OBS's questions, and go_live() fills in the dialog: youtube.ps1 opens it with OBS's
  Manage Broadcast button, checks it, and clicks "Create broadcast and start streaming" (Windows UI Automation).
  Its drop-down lists can't be set from outside OBS, but OBS pre-fills the dialog from its remembered YouTube
  settings. So go_live() puts the phone's answers there for the moment the dialog opens, then puts back exactly
  what was saved before: the details people keep in OBS stay as they wrote them.
"""
import json
import os
import subprocess
import threading
import time

import autofix  # its minimal obs-websocket client
import paths

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = paths.data("youtube.log")
STATE_FILE = paths.data("youtube_state.json")  # survives a server restart while OBS keeps running
NO_WINDOW = 0x08000000
_lock = threading.Lock()

# The phone sends OBS's stored values; the dialog shows these English names (checked by youtube.ps1).
PRIVACY = {"public": "Public", "unlisted": "Unlisted", "private": "Private"}
LATENCY = {"normal": "Normal", "low": "Low", "ultraLow": "Ultra low"}
CATEGORY = {"17": "Sports", "19": "Travel and Events", "20": "Gaming", "22": "People and blogs", "23": "Comedy",
            "24": "Entertainment", "25": "News and Politics", "26": "How-to and Style", "27": "Education",
            "28": "Science and Technology", "29": "Non-profits and Activism"}
# Remembered settings that go_live() changes for a moment, and puts back afterwards.
PARAMS = ("Title", "Description", "Privacy", "CategoryID", "Latency", "MadeForKids", "DVR", "ScheduleForLater",
          "RememberSettings")


def log(line):
    """Keep the last 200 lines: what each Go live asked for and what happened (the phone only shows the outcome)."""
    try:
        old = open(LOG, encoding="utf-8").read().splitlines()[-199:] if os.path.exists(LOG) else []
        with open(LOG, "w", encoding="utf-8") as f:
            f.write("\n".join(old + [time.strftime("%Y-%m-%d %H:%M:%S  ") + line]) + "\n")
    except OSError:
        pass


def connect():
    with open(autofix.WS_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    pw = cfg.get("server_password", "") if cfg.get("auth_required", True) else ""
    return autofix.OBS("127.0.0.1", int(cfg.get("server_port", 4455)), pw, timeout=10)


def obs_pid():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq obs64.exe", "/NH", "/FO", "CSV"], capture_output=True,
                         text=True, timeout=10, creationflags=NO_WINDOW).stdout
    for line in out.splitlines():
        cols = [c.strip('"') for c in line.split('","')]
        if len(cols) > 1 and cols[0].lower().lstrip('"') == "obs64.exe":
            return cols[1]
    return None


# ---- is a broadcast set up and waiting? ---------------------------------------------------------------------
WATCH = {"id": None, "used": None, "live": False, "at": 0.0}


def _broadcast_id(obs):
    return (obs.call("GetStreamServiceSettings").get("streamServiceSettings") or {}).get("broadcast_id") or None


def _save(pid, used):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"obsPid": pid, "used": used}, f)
    except OSError:
        pass


def _watch():
    while True:
        obs = None
        try:
            obs, pid = connect(), obs_pid()
            try:
                saved = json.load(open(STATE_FILE, encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            cur = _broadcast_id(obs)
            # Same OBS run as before a server restart: keep what we knew. A new OBS run has nothing set up yet,
            # whatever id its settings still hold.
            used = saved.get("used") if pid and saved.get("obsPid") == pid else cur
            _save(pid, used)
            while True:
                cur = _broadcast_id(obs)
                live = bool(obs.call("GetStreamStatus").get("outputActive"))
                if live and cur != used:
                    used = cur
                    _save(pid, used)
                WATCH.update(id=cur, used=used, live=live, at=time.time())
                time.sleep(3)
        except Exception:  # OBS closed or restarting: start again once it's back
            WATCH.update(id=None, at=0.0)
        finally:
            if obs:
                obs.close()
        time.sleep(5)


def broadcast_ready():
    w = WATCH
    return bool(w["id"]) and w["id"] != w["used"] and not w["live"] and time.time() - w["at"] < 15


def start():
    if os.name == "nt":
        threading.Thread(target=_watch, name="youtube", daemon=True).start()


# ---- fill in OBS's dialog ------------------------------------------------------------------------------------
def go_live(form):
    """form: title, description, privacy, category (id), latency (OBS's stored values), kids, dvr; dryRun to fill in
    and check the dialog, then cancel it (testing). Returns {ok, error}."""
    if os.name != "nt":
        return {"ok": False, "error": "Only works with OBS on Windows."}
    priv, cat, lat = str(form.get("privacy")), str(form.get("category")), str(form.get("latency"))
    if priv not in PRIVACY or cat not in CATEGORY or lat not in LATENCY:
        return {"ok": False, "error": "Unknown privacy, category or latency."}
    title = str(form.get("title") or "").strip()
    if not title:
        return {"ok": False, "error": "The title can't be empty."}
    if not _lock.acquire(blocking=False):
        return {"ok": False, "error": "Already setting up the broadcast."}
    want = {"title": title, "description": str(form.get("description") or ""), "privacy": PRIVACY[priv],
            "category": CATEGORY[cat], "latency": LATENCY[lat], "kids": bool(form.get("kids")), "dvr": bool(form.get("dvr"))}
    obs, saved, res, err = None, None, None, ""
    try:
        try:
            obs = connect()
            get = lambda n: obs.call("GetProfileParameter", {"parameterCategory": "YouTube", "parameterName": n}).get("parameterValue")
            saved = {n: get(n) for n in PARAMS}
            for n, v in {"Title": title, "Description": want["description"], "Privacy": priv, "CategoryID": cat,
                         "Latency": lat, "MadeForKids": str(want["kids"]).lower(), "DVR": str(want["dvr"]).lower(),
                         "ScheduleForLater": "false", "RememberSettings": "true"}.items():
                obs.call("SetProfileParameter", {"parameterCategory": "YouTube", "parameterName": n, "parameterValue": v})
        except Exception as e:
            res = {"ok": False, "error": f"Couldn't reach OBS: {e}"}
        if not res:
            env = dict(os.environ, OBS_REMOTE_YOUTUBE=json.dumps(want))
            try:
                r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                    "-File", os.path.join(HERE, "youtube.ps1")] + (["-DryRun"] if form.get("dryRun") else []),
                                   env=env, capture_output=True, timeout=90, creationflags=NO_WINDOW)
                out = r.stdout.decode("ascii", "replace").strip().splitlines()
                err = r.stderr.decode("utf-8", "replace").strip()
                try:
                    res = json.loads(out[-1])
                except (IndexError, ValueError):
                    res = {"ok": False, "error": "Couldn't work OBS's YouTube dialog: " + (err.splitlines()[0] if err else "no answer")}
            except subprocess.TimeoutExpired:
                res = {"ok": False, "error": "OBS didn't respond. Check the PC."}
    finally:
        restored = ""
        if obs and saved is not None:  # put back what people saved in OBS, whatever happened above
            try:
                for n, v in saved.items():
                    obs.call("SetProfileParameter", {"parameterCategory": "YouTube", "parameterName": n, "parameterValue": v})
            except Exception as e:
                restored = f"  (couldn't restore OBS's saved YouTube details: {e}; they were {json.dumps(saved, ensure_ascii=False)})"
        if obs:
            obs.close()
        _lock.release()
    log(("dry run " if form.get("dryRun") else "") + json.dumps({**want, "result": res}, ensure_ascii=False) + restored
        + (("\n    " + err.replace("\n", "\n    ")) if err else ""))
    return res
