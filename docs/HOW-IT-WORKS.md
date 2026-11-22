# How OBS Remote works

```
phone browser ──http :8765──▶ server.py (static files only)
      │
      └──────ws :4455──▶ obs-websocket (built into OBS) ──CallVendorRequest "obs-ptz"──▶ obs-ptz plugin ──▶ cameras
```

- `server.py` is a Python standard-library web server that only serves `www/`, with `Cache-Control: no-store` so phones always get the latest page.
  Port: first argument, else `OBS_REMOTE_PORT`, else 8765.
- `www/index.html` is the whole app: no build step and no external downloads. It speaks obs-websocket v5 directly.
- A plain `http://` LAN page has no `crypto.subtle`, so the page has its own SHA-256 for the websocket login.
- The password is stored in the phone browser's local storage.

## Pictures
Monitors call `GetSourceScreenshot` back to back, with one request in flight per monitor, so slow Wi-Fi lowers the frame rate instead of adding delay.
In testing a frame cost OBS about 8 ms, and 25 fps caused no skipped render frames.
The Live tab uses 480 px JPEGs; the Camera tab uses 640 px.

## Audio meters
The page subscribes to `InputVolumeMeters` (about 20 per second, about 9 KB/s) once, at login, and ignores them while the Live tab isn't on screen.
It never changes subscriptions with op 3 (Reidentify). obs-websocket 5.x (checked on 5.7.4) counts meter listeners with a plain counter.
A Reidentify that's processed while the same connection closes is subtracted twice, which happens when a phone locks right after hiding the page.
The count then stays one too low. Once it's low enough, OBS stops sending levels to *every* client, including OBS Remote on other phones, until OBS restarts.
Before 1.6.2 the page re-identified on every tab switch and every time it was hidden, so busy installs hit this after a few days.
Inputs are listed when their type can have audio. Browser sources are only listed when *Control audio via OBS* (`reroute_audio`) is ticked, as in OBS's own mixer.

## Listen on the phone (`listen.py`)
Off unless *Settings → Live tab → Listen on this phone* is on, which is saved per phone.
obs-websocket can't send sound, so the server on the OBS PC records it instead:
- **What you hear:** OBS's audio monitoring device (OBS *Settings → Audio → Advanced → Monitoring Device*), read with `GetProfileParameter`.
  Only sources set to *Monitor Only* or *Monitor and Output* play there.
  The headphone button on each audio row switches a source between *Monitor Off* and *Monitor and Output* (`SetInputAudioMonitorType`), for everyone.
  Monitored sources also play out of that device on the OBS PC. If it's the hall's speakers, pick a spare output in OBS first.
  Anything else Windows plays on that device is heard too.
- **Recording:** WASAPI loopback of that device through `ctypes` (no installs), then mixed to mono and resampled to 24 kHz 16-bit: 48 KB/s per phone.
  It only runs while at least one phone listens. While nothing plays, loopback delivers nothing, so the server sends silence to keep phones' timing steady.
- **Stream:** `GET /api/listen` sends raw PCM over a plain HTTP response until the phone stops.
  It needs the header `X-OBS-Remote-Key` = base64(SHA-256(`obs-remote-listen:` + OBS websocket password)), checked against OBS's own websocket config, so the password never crosses the network.
  `GET /api/listen-state` reports the device name and the last error.
- **Phone:** Web Audio (works on plain `http://`) schedules each 40 ms piece about 150 ms ahead and skips ahead if the delay grows past 600 ms.
  On iPhone, `navigator.audioSession.type = "playback"` lets it play with the silent switch on (iOS 17+).
- Don't listen on the OBS PC itself when the monitoring device is its default output: the page would record its own playback.

## PTZ (obs-ptz websocket vendor API)
Requests used: `ptz_list_devices`, `ptz_get_state`, `ptz_move`, `ptz_stop`, `ptz_preset_get_list`, `ptz_preset_recall`,
`ptz_preset_save`, `ptz_preset_capture_thumbnail`, `ptz_preset_get_thumbnail`, `ptz_request_state`. Events used: `ptz_state_changed`, `ptz_preset_*`.

| obs-ptz | Camera tab |
|---|---|
| 0.19.x stable and older | No websocket API. OBS replies 600 "No vendor was found", and the tab explains this. |
| 0.20.0-pre5 to pre8 | Works. No preset thumbnails. Speed caps come from `pantilt_speed_max`. |
| 1.0.0 betas / master | Full support, with per-axis caps `pan_speed_max` / `tilt_speed_max`. |

- **Speed:** obs-ptz *clamps* each move to the camera's max speed (PTZ filter settings) rather than scaling it.
  The app reads those caps with `GetSourceFilterList` and scales into them, so the whole Speed slider is useful.
- **Joystick:** speed comes from how far the knob is pushed. Direction is stretched to a square, so diagonals get full speed on the leading axis.
  Pushes within about 11° of straight snap to a pure pan or tilt.
- **Picture source:** the PTZ filter's source is used if it's producing video (`GetSourceActive`). Otherwise the app uses the first active video input whose name starts with it, unless overridden in Settings. ON AIR is shown if either source is in the program.
- **Names and order:** display names and picture overrides are stored in OBS with `SetPersistentData` (profile realm, slot `obs-remote.cameras`, `{names:{source:name}, pictures:{source:input}}`), so all phones share them. Devices are sorted by display name with numeric collation.
- **Refresh Camera (↻):** reconnects the picture source and the PTZ link. The picture source depends on its kind:
  - NDI: `ndi_source_name` is set to empty and then back, which rebuilds the receiver.
  - Media and VLC: restart.
  - Browser: refresh.
  - `dshow`: Deactivate, then Activate.
  - Anything else (e.g. obs-gstreamer): its own settings are re-applied, which makes OBS call the source's `update()`.

  For PTZ, the text connection fields of the obs-ptz filter (`host`/`address`, or a serial `port`) are set to a dummy value for 2.5 s and then restored.
  obs-ptz doesn't reconnect by itself after a camera reboots. In testing, switching back after less than 1 s never reconnected; 1.5 s and longer always did.
  If the link isn't back within 5 s, it retries once with a 4 s gap.
- **Safety:** moves only run while a finger is down. Release, `pointercancel`, `visibilitychange`, `blur` and `pagehide` all send `ptz_stop`.
- **Presets:** shown when they have a thumbnail or are local, else the first 16. Hikvision's built-in special presets (Call/Set/Start…) are hidden.

## Auto-reconnect of frozen NDI pictures (`autofix.py`)
At SMIC, FoMaKo NDI|HX cameras into DistroAV 6.1.1 / NDI 6.3.2 sometimes stalled: OBS kept showing the last frame and logged nothing.
The PTZ link stayed connected, and re-selecting the NDI source fixed it every time.
`server.py` starts a thread that does this re-select by itself:
- It connects to obs-websocket on 127.0.0.1 with a small built-in websocket client, using the port and password from OBS's own `obs-websocket/config.json`.
- **Sources watched:** NDI inputs that carry an obs-ptz camera, plus pictures chosen for those cameras in the app. Only while they're active or showing.
- **Frozen means:**
  - The picture showed at least 3 different frames in the 40 s before, then exactly the same frame for 20 s.
  - Checked every 4 s with a 320 px, quality-90 screenshot. At that size live frames always differ; smaller or lower-quality shots of a still, noise-reduced scene sometimes repeat.
- **The fix:** `ndi_source_name` is set to empty, then back. At most once a minute per source.
  A source not seen moving, e.g. already frozen when the server started, gets one try. If it then stays still (a slide, a camera that's off), it's left alone until it moves again.
- **On/off:** persistent data slot `obs-remote.settings` `{autofix}` (profile realm), default on.
  Saved in OBS, so it's the same for every phone. The watcher re-reads it on every round, so switching it off takes effect within 4 s.
- **Status:** `GET /api/autofix` returns `{running, enabled, error, watching, events}`, and Settings shows it.
  `running`/`error` come from the connection loop: if OBS is closed or the password is wrong, the thread retries every 15 s and reports why.
- **History:** each fix (or failed reconnect) is appended to `autofix.log` as `YYYY-MM-DD HH:MM:SS  source  what`.
  `events` keeps the last 20 in memory and is refilled from the end of `autofix.log` at startup (`load_history()`), so restarts and self-updates don't empty it.
  `autofix.log` is in the updater's KEEP list and `.gitignore`.
- **Cost:** one 320 px JPEG screenshot per watched source every 4 s, about 8 ms of OBS time each. Nothing is sent over the network: OBS and the watcher are on the same PC.
- `OBS_REMOTE_OBS_HOST` points the watcher at another PC (testing only).

### Timeline of a freeze
```
t=0     picture stops changing (OBS keeps showing the last frame)
t=4-20  snapshots identical; the 3 different frames in the 40 s before prove it was live
t~20    reconnect: ndi_source_name "" -> 0.8 s -> original name; logged
t~22    picture live again; that camera isn't touched again for 60 s
```

## Setup scripts
- `setup/install.ps1` finds Python 3.8+ (or offers `winget install Python.Python.3.12`) and reads OBS's websocket config.
  It detects whether obs-ptz has websocket support by looking for `ptz_list_devices` in the DLL, then opens the firewall.
  It starts `pythonw server.py` and adds a Startup shortcut.
  Then it finds this PC's local-network IPv4 addresses, best route first.
  Virtual adapters (Hyper-V, WSL, VirtualBox, VMware, Docker) and VPNs (Tailscale, ZeroTier, WireGuard, …) are skipped, matched on the adapter name and description.
  It prints a QR code for the first address and writes `Phone address.txt` and `Phone address.html`. An update never touches these files.
- `setup/qr.py` is a standard-library QR encoder: byte mode, error correction level M, versions 1-10 (up to 213 bytes).
  `--rows URL` prints the matrix as 0/1 lines, which the installer draws in the console with half-block characters, black on white.
  `--html` writes the page with SVG codes. It was checked by decoding hundreds of random URLs with OpenCV.
- `install.ps1` must stay ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page. That's why the block characters are built with `[char]`.
  Switches: `-Port`, `-SkipFirewall`, `-SkipStartup`.
- `setup/firewall.ps1` runs elevated. It adds two inbound TCP rules (page port and OBS websocket port), limited to `RemoteAddress LocalSubnet`, or removes them with `-Remove`.
- `setup/uninstall.ps1` stops the server, removes the shortcut and removes the rules.

## Updates (GitHub Releases)
Installed copies follow the repo's **published releases**, like OBS does. Pushing to `main` ships nothing.

**To release:** bump `VERSION` (e.g. `1.2.1`), commit and push, then publish a release whose tag matches, with notes:
```
gh release create v1.2.1 --title "OBS Remote 1.2.1" --notes "What changed, in a line or two."
```
The notes show on the phone's Update prompt. A release created with `--prerelease`, or as a draft, is ignored by the Update button.
To test one on a single PC, run `py server.py update v1.3.0-beta1`.

- `GET /api/version` returns `{version, latest, notes, url, update, blocked}`.
  `latest` and `notes` come from `api.github.com/repos/mdukasa/obs-remote/releases/latest`, cached for 10 minutes.
  That's at most 6 calls an hour, well under GitHub's limit of 60 an hour without an account.
  `blocked` is set when the folder is a git checkout, because those update with `git pull`.
- `POST /api/update` needs the header `X-OBS-Remote: 1`. A cross-site page can't send it without a CORS preflight, which the server never allows.
  It re-reads the latest release, downloads that tag's ZIP from codeload.github.com, checks that it is OBS Remote, and copies it over the folder, never outside it.
  It never touches `Phone address.txt`.
  Then it stops serving, and the main program starts a fresh `server.py`, which retries the port for up to 10 s.
  The relaunch must happen in the main program: from a worker thread it gets killed when the program ends.
- Downloads go through Python's TLS first. If certificate verification fails, they fall back to Windows' `curl.exe`, which uses the Windows certificate store.
  This was seen with GitHub's newer Let's Encrypt chain, which Python couldn't complete.
- `python server.py update [tag]` does the same from the command line and exits. Run `Install.bat` afterwards to restart the server.
- The page checks `/api/version` when it loads, when Settings opens and every 6 hours. When the server reports an update, it shows a dot on ⚙.
- Before 1.2.0, copies followed the `VERSION` file on `main` instead. A 1.1.x copy therefore moves to 1.2.0 when `main` says 1.2.0, and follows releases from then on.

## README screenshots
The pictures in the README are made, not photographed: a drawn venue and a pretend OBS, so no real venue or people appear.
They, the full-size venue pictures and the tools that make them live in [mdukasa/obs-remote-assets](https://github.com/mdukasa/obs-remote-assets), which also explains how to re-make them after a UI change.
