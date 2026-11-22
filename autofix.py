"""Auto-reconnect for frozen NDI camera pictures. Started by server.py; Python standard library only.

Some NDI|HX cameras (seen at SMIC with FoMaKo PTZs and DistroAV 6.1.1 / NDI 6.3.2) stall after a while:
OBS keeps showing the last frame, logs nothing, and only re-selecting the NDI source brings it back.
This watches the camera pictures through obs-websocket on this PC and does that re-select by itself.

Which sources: NDI inputs that carry an obs-ptz camera, plus pictures chosen for a camera in the app.
When is it frozen: the picture was moving (live cameras always change a little) and then shows exactly the
same frame for FROZEN_SECS. Something that never moves, like a slide or a switched-off camera, is left alone.
Each fix is logged to autofix.log next to this file and listed in the app's Settings; the list is reloaded from
that file at startup. README.md (Auto-reconnect of frozen cameras) and docs/HOW-IT-WORKS.md explain it in full.
"""
import base64
import collections
import hashlib
import json
import os
import socket
import struct
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, "autofix.log")
WS_CONFIG = os.path.join(os.environ.get("APPDATA", ""), "obs-studio", "plugin_config", "obs-websocket", "config.json")
SETTINGS = {"realm": "OBS_WEBSOCKET_DATA_REALM_PROFILE", "slotName": "obs-remote.settings"}  # {autofix: bool}
CAMERAS = {"realm": "OBS_WEBSOCKET_DATA_REALM_PROFILE", "slotName": "obs-remote.cameras"}   # app's picture choices

INTERVAL = 4        # seconds between checks
FROZEN_SECS = 20    # same frame this long (about 5 checks in a row) = frozen
MOVING_WINDOW = 40  # ...if it showed at least 3 different frames in this many seconds before that
COOLDOWN = 60       # don't touch the same source again within this time

EVENTS = collections.deque(maxlen=20)
STATE = {"running": False, "enabled": True, "error": None, "watching": []}


class OBS:
    """Minimal obs-websocket v5 client (text frames, requests only, no events)."""

    def __init__(self, host, port, password, timeout=15):
        s = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                   "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = s.recv(4096)
            if not chunk:
                raise OSError("OBS closed the connection")
            buf += chunk
        head, _, self.buf = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n")[0] + b" ":
            raise OSError("OBS refused the websocket connection")
        self.s, self.id = s, 0
        auth = self.recv()["d"].get("authentication")
        ident = {"rpcVersion": 1, "eventSubscriptions": 0}
        if auth:
            secret = base64.b64encode(hashlib.sha256((password + auth["salt"]).encode()).digest()).decode()
            ident["authentication"] = base64.b64encode(
                hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
        self.send({"op": 1, "d": ident})
        if self.recv().get("op") != 2:
            raise OSError("OBS didn't accept the login")

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise OSError("OBS closed the connection")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self, op, payload):
        n, mask = len(payload), os.urandom(4)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    def send(self, obj):
        self._frame(1, json.dumps(obj).encode())

    def recv(self):
        data = b""
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0F, b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if op == 8:
                raise OSError("OBS closed the connection")
            if op == 9:  # ping
                self._frame(10, payload)
                continue
            if op == 10:
                continue
            data += payload
            if b0 & 0x80:
                return json.loads(data)

    def call(self, request, data=None):
        self.id += 1
        rid = str(self.id)
        self.send({"op": 6, "d": {"requestType": request, "requestId": rid, "requestData": data or {}}})
        while True:
            m = self.recv()
            if m.get("op") == 7 and m["d"].get("requestId") == rid:
                st = m["d"]["requestStatus"]
                if not st.get("result"):
                    raise RuntimeError(st.get("comment") or f"code {st.get('code')}")
                return m["d"].get("responseData") or {}

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


def note(source, what):
    EVENTS.append({"t": time.time(), "source": source, "what": what})
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {source}  {what}\n")
    except OSError:
        pass


def watched(obs):
    """NDI inputs worth watching: those with an obs-ptz camera, plus app-chosen pictures for those cameras."""
    try:
        devs = obs.call("CallVendorRequest", {"vendorName": "obs-ptz", "requestType": "ptz_list_devices",
                                              "requestData": {}}).get("responseData", {}).get("devices", [])
    except (RuntimeError, KeyError):
        devs = []
    want = {d.get("source") for d in devs}
    try:
        pics = (obs.call("GetPersistentData", CAMERAS).get("slotValue") or {}).get("pictures") or {}
        want |= {pics[s] for s in list(want) if pics.get(s)}
    except RuntimeError:
        pass
    ndi = {i["inputName"] for i in obs.call("GetInputList").get("inputs", []) if i.get("inputKind", "").startswith("ndi_source")}
    return sorted(want & ndi)


def reconnect(obs, source):
    name = obs.call("GetInputSettings", {"inputName": source}).get("inputSettings", {}).get("ndi_source_name")
    if not name:
        return False
    obs.call("SetInputSettings", {"inputName": source, "inputSettings": {"ndi_source_name": ""}})
    time.sleep(0.8)
    obs.call("SetInputSettings", {"inputName": source, "inputSettings": {"ndi_source_name": name}})
    return True


def watch(obs):
    hist, last_fix, last_list, still = {}, {}, 0.0, set()
    sources = []
    while True:
        now = time.time()
        try:
            v = obs.call("GetPersistentData", SETTINGS).get("slotValue") or {}
            STATE["enabled"] = v.get("autofix", True) is not False
        except RuntimeError:
            STATE["enabled"] = True
        if now - last_list > 30:  # cameras rarely change; re-read the list now and then
            sources, last_list = watched(obs), now
        active = []
        for src in sources if STATE["enabled"] else []:
            try:
                act = obs.call("GetSourceActive", {"sourceName": src})
                if not (act.get("videoActive") or act.get("videoShowing")):
                    hist.pop(src, None)
                    continue
                active.append(src)
                img = obs.call("GetSourceScreenshot", {"sourceName": src, "imageFormat": "jpg",
                                                       "imageWidth": 320, "imageCompressionQuality": 90})
            except RuntimeError:
                hist.pop(src, None)
                continue
            # 320 px at quality 90: live frames always differ (sensor and codec noise). Smaller or lower-quality
            # shots of a still, noise-reduced scene sometimes repeat, which would look like a freeze.
            h = hashlib.md5(img.get("imageData", "").encode()).hexdigest()
            samples = hist.setdefault(src, collections.deque(maxlen=40))
            samples.append((now, h))
            if len({x for t, x in samples if t >= now - MOVING_WINDOW}) >= 3:
                still.discard(src)  # really moving again
            stuck = [t for t, x in samples if x != h]
            since = (stuck[-1] if stuck else samples[0][0])  # time of the last different frame
            if now - since < FROZEN_SECS or now - last_fix.get(src, 0) < COOLDOWN:
                continue
            before = {x for t, x in samples if since - MOVING_WINDOW <= t < since}
            if len(before) < 3:
                # Not seen moving (e.g. it was already frozen when the server started): try once. If it's
                # still the same afterwards it's a still picture (slide, camera off): leave it until it moves.
                if src in still:
                    continue
                still.add(src)
            try:
                ok = reconnect(obs, src)
            except RuntimeError as e:
                note(src, f"reconnect failed: {e}")
                ok = False
            if ok:
                note(src, f"picture frozen for {int(now - since)} s, reconnected")
            last_fix[src] = now
            samples.clear()
        STATE["watching"] = active
        time.sleep(INTERVAL)


def run(host=None):
    """Keep watching for the life of the server; reconnect to OBS whenever it restarts."""
    host = host or os.environ.get("OBS_REMOTE_OBS_HOST", "127.0.0.1")
    while True:
        obs = None
        try:
            with open(WS_CONFIG, encoding="utf-8") as f:
                cfg = json.load(f)
            if not cfg.get("server_enabled"):
                raise OSError("OBS WebSocket server is off")
            obs = OBS(host, int(cfg.get("server_port", 4455)),
                      cfg.get("server_password", "") if cfg.get("auth_required", True) else "")
            STATE.update(running=True, error=None)
            watch(obs)
        except Exception as e:  # OBS closed, not installed, wrong password...: wait and try again
            STATE.update(running=False, error=str(e) or type(e).__name__, watching=[])
        finally:
            if obs:
                obs.close()
        time.sleep(15)


def load_history():
    """Fill EVENTS from the end of autofix.log, so the list in Settings survives restarts and updates."""
    try:
        with open(LOG, encoding="utf-8") as f:
            lines = collections.deque(f, maxlen=EVENTS.maxlen)
    except OSError:
        return
    for line in lines:
        parts = line.rstrip("\n").split("  ", 2)  # "2026-11-21 20:31:05  CAM02  picture frozen for 20 s, reconnected"
        if len(parts) != 3:
            continue
        try:
            t = time.mktime(time.strptime(parts[0], "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        EVENTS.append({"t": t, "source": parts[1], "what": parts[2]})


def start():
    load_history()
    threading.Thread(target=run, name="autofix", daemon=True).start()
