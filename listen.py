"""Listen on the phone: stream OBS's audio monitoring device to the app (Windows only, standard library).

OBS plays every source set to "Monitor Only" or "Monitor and Output" on its monitoring device
(Settings > Audio > Advanced). This module records that device with WASAPI loopback, turns it into
24 kHz mono 16-bit PCM and hands it to each phone that's listening. Capture runs only while at least
one phone listens.
"""
import array
import base64
import ctypes
import hashlib
import json
import queue
import struct
import threading
import time
import uuid
from ctypes import POINTER, byref, c_int, c_int64, c_uint32, c_void_p, c_wchar_p

import autofix

RATE = 24000      # what the phone gets: 24 kHz mono s16le, 48 KB/s
CHUNK = 960       # 40 ms per piece sent to a phone
LOCK = threading.Lock()
LISTENERS = set()  # one queue per phone
STATE = {"device": None, "error": None}


class GUID(ctypes.Structure):
    _fields_ = [("b", ctypes.c_ubyte * 16)]


def guid(s):
    g = GUID()
    ctypes.memmove(byref(g), uuid.UUID(s).bytes_le, 16)
    return g


CLSID_MMDeviceEnumerator = guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioClient = guid("1CB9AD4C-DBFA-4C32-B178-C2F568A703B2")
IID_IAudioCaptureClient = guid("C8ADBD64-E71E-48A0-A4DE-185C395CD317")
CLSCTX_ALL = 0x17
LOOPBACK = 0x00020000
SILENT = 0x2


def vcall(obj, index, argtypes=(), *args, restype=ctypes.HRESULT):
    """Call method number `index` of a COM object's vtable. HRESULT failures raise OSError."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])(obj, *args)


def release(obj):
    if obj and obj.value:
        vcall(obj, 2, restype=ctypes.c_ulong)


class Loopback:
    """WASAPI loopback recording of one render device ("default" = Windows' default playback device)."""

    def __init__(self, device_id):
        self.ole = ctypes.OleDLL("ole32")
        self.ole.CoInitializeEx(None, 0)  # multithreaded apartment for this thread
        self.enum, self.dev, self.client, self.cap = c_void_p(), c_void_p(), c_void_p(), c_void_p()
        try:
            self.ole.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                                      byref(IID_IMMDeviceEnumerator), byref(self.enum))
            if not device_id or device_id == "default":
                vcall(self.enum, 4, (c_int, c_int, POINTER(c_void_p)), 0, 0, byref(self.dev))  # eRender, eConsole
            else:
                vcall(self.enum, 5, (c_wchar_p, POINTER(c_void_p)), device_id, byref(self.dev))
            vcall(self.dev, 3, (POINTER(GUID), c_uint32, c_void_p, POINTER(c_void_p)),
                  byref(IID_IAudioClient), CLSCTX_ALL, None, byref(self.client))
            fmt = c_void_p()
            vcall(self.client, 8, (POINTER(c_void_p),), byref(fmt))  # GetMixFormat
            try:
                raw = ctypes.string_at(fmt, 40)
                tag, self.channels, self.rate, _, self.align, bits = struct.unpack_from("<HHIIHH", raw)
                sub = struct.unpack_from("<I", raw, 24)[0] if tag == 0xFFFE else tag
                self.kind = "f" if sub == 3 and bits == 32 else {16: "h", 32: "i"}.get(bits) if sub == 1 else None
                if not self.kind:
                    raise OSError(f"unsupported sound format (tag {sub}, {bits} bit)")
                vcall(self.client, 3, (c_int, c_uint32, c_int64, c_int64, c_void_p, c_void_p),
                      0, LOOPBACK, 2_000_000, 0, fmt, None)  # shared mode, 200 ms buffer
            finally:
                self.ole.CoTaskMemFree(fmt)
            vcall(self.client, 14, (POINTER(GUID), POINTER(c_void_p)), byref(IID_IAudioCaptureClient), byref(self.cap))
            vcall(self.client, 10)  # Start
        except Exception:
            self.close()
            raise
        self.pos = 0.0  # resampler position, carried between packets
        self.step = self.rate / RATE

    def read(self):
        """Everything recorded since the last call, as 24 kHz mono floats. Empty while nothing plays."""
        out = []
        size, data, frames, flags = c_uint32(), c_void_p(), c_uint32(), c_uint32()
        while True:
            vcall(self.cap, 5, (POINTER(c_uint32),), byref(size))  # GetNextPacketSize
            if not size.value:
                return out
            vcall(self.cap, 3, (POINTER(c_void_p), POINTER(c_uint32), POINTER(c_uint32), c_void_p, c_void_p),
                  byref(data), byref(frames), byref(flags), None, None)
            n = frames.value
            try:
                if flags.value & SILENT or not data.value:
                    mono = [0.0] * n
                else:
                    a = array.array(self.kind, ctypes.string_at(data, n * self.align))
                    scale = {"f": 1.0, "h": 1 / 32768, "i": 1 / 2147483648}[self.kind]
                    ch = self.channels
                    if ch == 1:
                        mono = [v * scale for v in a]
                    else:  # average the first two channels
                        mono = [(l + r) * 0.5 * scale for l, r in zip(a[0::ch], a[1::ch])]
            finally:
                vcall(self.cap, 4, (c_uint32,), n)  # ReleaseBuffer
            # resample by averaging each output sample's span (a plain box filter: fine for monitoring)
            p, step, m = self.pos, self.step, len(mono)
            while p + step <= m:
                i, j = int(p), int(p + step)
                seg = mono[i:j] or [mono[i]]
                out.append(sum(seg) / len(seg))
                p += step
            self.pos = p - m

    def close(self):
        if self.client.value:
            try:
                vcall(self.client, 11)  # Stop
            except OSError:
                pass
        for o in (self.cap, self.client, self.dev, self.enum):
            release(o)
        self.cap = self.client = self.dev = self.enum = c_void_p()


def obs_password():
    with open(autofix.WS_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg, (cfg.get("server_password", "") if cfg.get("auth_required", True) else None)


def key_ok(key):
    """The page sends base64(sha256("obs-remote-listen:" + OBS websocket password)), so only people who know
    the password can listen, and the password itself never crosses the network."""
    try:
        _, pw = obs_password()
    except OSError:
        return False
    if pw is None:
        return True
    want = base64.b64encode(hashlib.sha256(("obs-remote-listen:" + pw).encode()).digest()).decode()
    return bool(key) and key == want


def monitoring_device():
    """OBS's monitoring device (id, name) from the current profile, asked over obs-websocket."""
    cfg, pw = obs_password()
    obs = autofix.OBS("127.0.0.1", int(cfg.get("server_port", 4455)), pw or "")
    try:
        get = lambda n: obs.call("GetProfileParameter", {"parameterCategory": "Audio", "parameterName": n})
        dev_id = get("MonitoringDeviceId").get("parameterValue") or "default"
        name = get("MonitoringDeviceName").get("parameterValue") or "Default"
        return dev_id, name
    finally:
        obs.close()


def pump():
    """Capture thread: runs while anyone listens, fans 40 ms pieces out to every listener."""
    cap = None
    try:
        dev_id, STATE["device"] = monitoring_device()
        cap = Loopback(dev_id)
        STATE["error"] = None
        buf, start, sent = [], time.monotonic(), 0
        while True:
            with LOCK:
                if not LISTENERS:
                    return
            buf += cap.read()
            # While nothing plays, loopback delivers nothing: fill with silence so phones keep a steady clock.
            due = int((time.monotonic() - start) * RATE)
            if sent + len(buf) < due - CHUNK * 3:
                buf += [0.0] * (due - CHUNK - sent - len(buf))
            while len(buf) >= CHUNK:
                piece, buf = buf[:CHUNK], buf[CHUNK:]
                pcm = array.array("h", (max(-32768, min(32767, int(v * 32767))) for v in piece)).tobytes()
                sent += CHUNK
                with LOCK:
                    for q in LISTENERS:
                        try:
                            q.put_nowait(pcm)
                        except queue.Full:  # a phone that can't keep up skips audio rather than lagging
                            pass
            time.sleep(0.01)
    except Exception as e:
        STATE["error"] = str(e) or type(e).__name__
        with LOCK:
            for q in LISTENERS:
                q.put_nowait(None)
    finally:
        if cap:
            cap.close()
        with LOCK:
            STATE["thread"] = None
            if LISTENERS and not STATE["error"]:  # someone joined while we were stopping
                start_pump()


def start_pump():
    if not STATE.get("thread"):
        STATE["thread"] = threading.Thread(target=pump, daemon=True)
        STATE["thread"].start()


def subscribe():
    q = queue.Queue(maxsize=25)  # 1 s
    with LOCK:
        LISTENERS.add(q)
        STATE["error"] = None
        start_pump()
    return q


def unsubscribe(q):
    with LOCK:
        LISTENERS.discard(q)
