# How OBS Remote works

```
phone browser ──http :8765──▶ server.py (the page, plus a few /api/ calls)
      │
      └──────ws :4455──▶ obs-websocket (built into OBS) ──CallVendorRequest "obs-ptz"──▶ obs-ptz plugin ──▶ cameras
```

- `server.py` is a Python standard-library web server. It serves `www/` with `Cache-Control: no-store`, so phones always get the latest page.
  Everything else the page needs from the OBS PC goes through small `/api/` calls: updates, auto-fix status, mixer-hidden sources, Listen and Start OBS.
  OBS itself is controlled by the phone directly over obs-websocket.
  Port: first argument, else `OBS_REMOTE_PORT`, else 8765.
  On Windows it binds without `SO_REUSEADDR`, which there would let it share a port another program already listens on (that program then gets the requests). It also checks that nothing answers on 127.0.0.1 first, and otherwise exits saying the port is taken.
- `www/index.html` is the whole app: no build step and no external downloads. It speaks obs-websocket v5 directly.
- A plain `http://` LAN page has no `crypto.subtle`, so the page has its own SHA-256 for the websocket login.
- The password is stored in the phone browser's local storage.
- **Sign-in link:** the installer's QR code opens `http://PC:8765/#pw=PASSWORD` (percent-encoded; `&port=N` when OBS's websocket isn't on 4455).
  The page saves that like a typed-in login, then removes it from the address bar with `history.replaceState`, so a home-screen icon doesn't carry it.
  Browsers never send the `#` part to the server, so it isn't in any request or log.
- **Local or Tailscale:** `GET /api/net` returns `{tailscale: true}` when the request came from a Tailscale address (`100.64.0.0/10` or `fd7a:115c:a1e0::/48`), or from this PC's own LAN address, which is how traffic through the installer's route arrives (a phone on the real LAN never has it). A browser on the PC itself opening its LAN address also arrives from that address; then a program on the PC owns the other end of the connection, which `local_client` finds in Windows' TCP table (`GetExtendedTcpTable` with owning process), so it counts as local. Routed traffic has no local socket behind it (or one owned by Tailscale). The page asks on every (re)connect and shows *OBS · via Tailscale* in the header and *via Tailscale* under Settings → Connection. Nothing else changes: with the installer's route the address is the same either way.
- **Home screen:** `manifest.webmanifest` (PNG icons at 192/512, a maskable one, `apple-touch-icon.png` for iPhones) and `sw.js`, a service worker that caches nothing.
  iPhones add it as a full-screen app from plain http. Chrome and Edge only offer *Install app* on https or localhost; at `http://192.168…` they make a shortcut that opens in the browser.
  The icon PNGs are drawn from `icon.svg`; redraw them if it changes.

## Pictures
Monitors call `GetSourceScreenshot` back to back, with one request in flight per monitor, so slow Wi-Fi lowers the frame rate instead of adding delay.
In testing a frame cost OBS about 8 ms, and 25 fps caused no skipped render frames.
The Switcher's preview and program use 480 px JPEGs; the Camera tab uses 640 px. The rate follows Settings → *Picture* (25, 10 or 2 fps), and nothing is fetched on the Audio tab.

**Scene keys** show 192 px screenshots of each scene. They're taken one at a time while the Switcher is open, and again just after a scene is tapped. The program and preview keys reuse the monitor pictures (at most twice a second) instead of asking again.

**Favourite scenes** are saved in OBS with `SetPersistentData` (profile realm, slot `obs-remote.favourites`, `{collection name: [scene, …]}`), so every phone shows the same keys. With none starred, every scene is a key. Renaming a scene collection starts it with no favourites.

**CUT** sets OBS's Cut transition (`GetSceneTransitionList`, kind `cut_transition`), sends `TriggerStudioModeTransition`, then puts the chosen transition back. **TAKE** uses the chosen transition as it is.

## Audio meters
The page subscribes to `InputVolumeMeters` (about 20 per second, about 9 KB/s) once, at login, and ignores them while the Audio tab isn't on screen.
It never changes subscriptions with op 3 (Reidentify). obs-websocket 5.x (checked on 5.7.4) counts meter listeners with a plain counter.
A Reidentify that's processed while the same connection closes is subtracted twice, which happens when a phone locks right after hiding the page.
The count then stays one too low. Once it's low enough, OBS stops sending levels to *every* client, including OBS Remote on other phones, until OBS restarts.
Before 1.6.2 the page re-identified on every tab switch and every time it was hidden, so busy installs hit this after a few days.
Each channel comes as `[magnitude, peak, input peak]`. For a muted source obs-websocket zeroes the first two but not the input peak (before the fader). So, like OBS's mixer, a muted row shows input peak × fader (`GetInputVolume`, `InputVolumeChanged`), greyed out.
Inputs are listed when their type can have audio. Browser sources are only listed when *Control audio via OBS* (`reroute_audio`) is ticked, as in OBS's own mixer.

## Start OBS from the phone
When the page can't connect to OBS, it asks `GET /api/obs` every 3 s (`{running, starting, closing, stuckFor, forceAfter, canStart}`, from `server.obs_state()`) and shows a banner:
- *OBS is closed on the PC*, with **Start OBS**, when `obs64.exe` isn't running.
- *Starting OBS…*, when an `obs64.exe` is less than a minute old (`GetProcessTimes`).
- *OBS is closing…*, then after 15 s *OBS is stuck closing* with **Start OBS**, when every `obs64.exe` is older than that, none has a visible window (`EnumWindows`) and nothing listens on OBS's WebSocket port (from obs-websocket's `config.json`). OBS 32.2.2 has been seen to sit like that for 4½ minutes after its window closed, waiting for WebSocket clients to finish closing. The port check keeps an OBS minimised to the tray (no window, still answering) from counting.
- *OBS isn't answering*, when it runs with a window but its WebSocket server is off.

**Start OBS** sends `POST /api/obs/start` with `X-OBS-Remote: 1` and the same `X-OBS-Remote-Key` as Listen, so only phones that know the OBS password can start it.
For a stuck copy the phone asks first and sends `{"force": true}`. The server checks again that every OBS process is still stuck, for at least 15 s, ends them with `taskkill /F`, waits until they've gone, and then starts OBS as usual. A working OBS is never ended this way.
The server finds `obs64.exe` from OBS's installer entry (`HKLM\SOFTWARE\OBS Studio`) or the usual folder. Before starting it, it deletes leftover `%APPDATA%\obs-studio\.sentinel\run_*` files. OBS 32 writes one per run and removes it on a clean exit; one left over makes the next start stop at *OBS Studio Crash Detected… Run in Safe Mode?* until someone clicks. (OBS 32 ignores the old `--disable-shutdown-check`, which is still passed for older versions.)
It starts OBS from its own folder and refuses (409) if OBS is already running (and not stuck).
OBS opens on the desktop of whoever is signed in, because the server runs in that session.

## Going live on YouTube (`youtube.py`, `youtube.ps1`)
When OBS is signed in to a YouTube account (no stream key), it won't stream until a broadcast is set up in its *YouTube Broadcast Setup* dialog on the PC, and obs-websocket has no request for that.
- **Broadcast already set up** (someone used *Manage Broadcast* on the PC to create one or pick a scheduled one): **Go live** just asks "Start the stream?" and sends `StartStream`, which goes live to it.
  OBS doesn't report this state, so a watcher thread in `youtube.py` keeps an obs-websocket connection and polls `GetStreamServiceSettings` every 3 s. Setting up a broadcast puts a new `broadcast_id` there; the id of the last stream is remembered (`youtube_state.json` in the data folder).
  A different id that hasn't streamed yet = a broadcast is waiting (`GET /api/youtube` → `{ready}`).
  OBS forgets a set-up broadcast when it restarts, so when OBS's process id changes the watcher counts the current id as used.
- **Detection:** the stream service is YouTube, profile parameter `Auth/Type` is YouTube and `YouTube/ChannelName` is set. Otherwise **Go live** just sends `StartStream`.
  Not "no stream key": after a broadcast OBS keeps that broadcast's key (and `broadcast_id`) in the stream settings. If OBS turns out to have no *Manage Broadcast* button, `youtube.ps1` answers `noAccount` and the phone just starts the stream.
  If OBS's *No Broadcast Configured* message is open (someone pressed Start Streaming without a broadcast), `youtube.ps1` uses its *Manage Broadcast* button.
- **The form** starts from OBS's remembered settings: profile parameters in category `YouTube` (`Title`, `Description`, `Privacy` public/unlisted/private, `CategoryID` YouTube's numbers, `Latency` normal/low/ultraLow, `MadeForKids`, `DVR`, `ChannelName`).
- **Go live** sends the answers to `POST /api/youtube/golive` (same headers as Start OBS). The server reads OBS's saved YouTube settings, puts the answers there (`SetProfileParameter`, plus `RememberSettings=true` and `ScheduleForLater=false`) so OBS pre-fills its dialog with them, runs `youtube.ps1`, then puts back exactly what was saved, whatever happened.
  The details people keep in OBS stay as they wrote them, and *Remember these settings* in the dialog is left as it is.
- **`youtube.ps1`** uses Windows UI Automation (built into Windows; no extra software):
  1. clicks OBS's *Manage Broadcast* button;
  2. checks the dialog shows the phone's answers, and sets the text boxes and tick boxes if not;
  3. clicks *Create broadcast and start streaming*;
  4. waits for the dialog to close, or reports OBS's error message.
  Drop-down lists can't be changed from outside Qt, so if one disagrees (checked only when OBS is in English) it cancels instead and says so.
  It searches inside OBS's main window: an open drop-down list hides the dialog from a desktop-wide search.
- `youtube.ps1 -DryRun` (or `dryRun: true` in the request) fills in and checks the dialog, then cancels it, for testing without going live.

## Listen on the phone (`listen.py`)
The Audio tab always has a **Listen** button, and each source a headphone button. Nothing plays, and the server records nothing, until someone taps **Listen**.
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
- **Picture source:** the PTZ filter's source is used if it's producing video (`GetSourceActive`). Otherwise the app uses the first active video input whose name starts with it. ON AIR is shown if either source is in the program.
- **Names and order:** cameras show their OBS source names, sorted with numeric collation. Names and picture overrides saved by versions before 1.12 (`SetPersistentData`, profile realm, slot `obs-remote.cameras`, `{names:{source:name}, pictures:{source:input}}`) are still honoured, but the app no longer edits them.
- **Move and Presets** are two faces of one panel under the picture; the phone remembers the last one (`localStorage`). The camera name pill follows a swipe on the picture part of the way, then finishes the slide (or springs back) when the finger lifts.
- **Refresh camera:** reconnects the picture source and the PTZ link. The picture source depends on its kind:
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
- **History:** each fix (or failed reconnect) is appended to `autofix.log` (in the data folder, see *Data folder*) as `YYYY-MM-DD HH:MM:SS  source  what`.
  `events` keeps the last 20 in memory and is refilled from the end of `autofix.log` at startup (`load_history()`), so restarts and self-updates don't empty it.
  It lives outside the program folder, so updates never touch it. (Its old name in the program folder is still in the updater's KEEP list and `.gitignore`, for copies that haven't moved it yet.)
- **Cost:** one 320 px JPEG screenshot per watched source every 4 s, about 8 ms of OBS time each. Nothing is sent over the network: OBS and the watcher are on the same PC.
- `OBS_REMOTE_OBS_HOST` points the watcher at another PC (testing only).

### Timeline of a freeze
```
t=0     picture stops changing (OBS keeps showing the last frame)
t=4-20  snapshots identical; the 3 different frames in the 40 s before prove it was live
t~20    reconnect: ndi_source_name "" -> 0.8 s -> original name; logged
t~22    picture live again; that camera isn't touched again for 60 s
```

## Tray icon (`tray.py`)
`server.py` shows an icon in the notification area from a thread with its own hidden window and message loop (ctypes: `Shell_NotifyIconW`, legacy callback messages). `OBS_REMOTE_NO_TRAY=1` turns it off (setup's diagnostic run of the server uses that).
- **Picture:** drawn in code at the small-icon size Windows asks for (`SM_CXSMICON`), from the same shapes as `www/icon.svg`, 4x4 supersampled, plus a status dot: green while autofix's websocket client is logged in to OBS (`autofix.STATE["running"]`), amber otherwise. Made into an icon with `CreateIconFromResourceEx` (32-bit BGRA DIB).
- **Every 3 s** (`WM_TIMER`) it refreshes the dot and the tooltip: version, OBS connected or not, phones seen in the last 2 minutes (`PHONES`), and a newer version if a phone's update check already found one. It never asks GitHub itself.
- **Click:** opens the setup window (`core.py panel`). **Right-click menu:** status lines, *Open OBS Remote*, *Start OBS* (when OBS is closed), *Notify me of camera fixes and updates* (a tick, kept as `tray_notify` in `settings.json`), *Restart OBS Remote* (the same `RESTART` path as an update), *Stop until next sign-in*.
- **Notifications** (balloons, no sound) only for what happens while it runs: a new autofix event, or a newer version appearing.
- **No dead icons:** Windows keeps an icon whose process was killed until the mouse passes over it. So the server removes its icon whenever it stops normally, and setup and the installer ask it to stop with `POST /api/quit` (127.0.0.1 only, `X-OBS-Remote` header) before killing anything (`core.ask_server_to_quit`). It re-adds the icon when Explorer restarts (`TaskbarCreated`).

## Data folder (`paths.py`)
Logs and saved state (`autofix.log`, `youtube.log`, `youtube_state.json`, `tailscale-route.txt`) live in `%LOCALAPPDATA%\OBS Remote` (or `OBS_REMOTE_DATA` if set), apart from the program files, so updates and a future installer never have to step around them.
`paths.data(name)` gives a file's path there. Importing `paths` moves files an older version left in the program folder (`setup/tailscale-route.txt` included); a file already in the data folder wins.
`settings.json` there keeps the server's port, so the setup window and `Install.bat -Console` reuse it.
Versions before 1.11 wrote the QR codes, with the OBS password, to `Phone address.txt` / `.html` in the program folder; setup now deletes those (the setup window shows the codes instead).

## Setup scripts
All of setup's checks and changes are Python functions in `setup/core.py`; each check returns a dict (`id, label, state: ok|warn|fail|info, detail, hints`), so a setup window can show the same checks as the console.
- `Install.bat` → `setup/install.ps1`, which only finds Python 3.8+ (`setup/python.ps1`, `Find-Python`, shared with the uninstaller) or offers `winget install Python.Python.3.12`.
  Then it opens the setup window (`pythonw core.py panel`) and exits with code 10, which tells `Install.bat` to close its console without `pause`.
  With `-Console` or any other switch it runs `core.py install` in the console instead, passing the switches on (`-Port` → `--port`, `-SkipFirewall` → `--skip-firewall`, `-SkipStartup` → `--skip-startup`, `-Tailscale` / `-NoTailscale`).
- `python setup/core.py status [--port N]` prints every check as JSON (password masked) and changes nothing.
- `Uninstall.bat` → `setup/uninstall.ps1` → `core.py uninstall`. Without Python it removes only the Startup shortcut and the firewall rules.
- LAN addresses (with the router's address) come from `GetAdaptersAddresses` through ctypes, instantly. PowerShell is still used for the firewall rules (through the firewall's COM object, `HNetCfg.FwPolicy2`, ~2 s, a third of `Get-NetFirewallRule`'s time), process command lines (`Get-CimInstance`), obs-ptz's file version and the shortcuts. Independent checks run in parallel (`core.gather`), so `status` takes about 2 s.
- Admin steps (firewall rules, obs-ptz's installer) go through `ShellExecuteEx` (`core.shell_run`, verb `runas` for the firewall), which raises `Declined` when the permission prompt is answered No (error 1223).
- The server starts as `pythonw server.py PORT`, detached and out of the console's job, so closing the setup window doesn't stop it.

## Setup window (`setup/panel.py`, `setup/panel.html`)
`core.py panel` (Start menu → **OBS Remote**, or `Install.bat`) serves a one-page app to this PC only and opens it as an app window (`--app=URL`) in the default browser if that's Chrome-like (Chrome, Edge, Brave, Vivaldi, Chromium), else in Edge, else Chrome, else as a tab in the default browser. Edge is skipped when something takes over its launches: a `Debugger` for `msedge.exe` in Image File Execution Options (or one of its filter subkeys), or an installed MSEdgeRedirect. Starting Edge then runs that tool instead and no window appears (seen 2026-11-24).
- **Who can reach it:** it listens on `127.0.0.1` at a random port. Every request needs the random token from the window's address (`?t=`, sent back as `X-Token`), and the `Host` header must be `127.0.0.1:port` or `localhost:port`, so a web page can't reach it through DNS rebinding. Responses send `X-Frame-Options: DENY` and a CSP. The OBS password only goes to the window, which shows it masked.
- **One at a time:** `panel.json` in the data folder holds `{port, token, pid}`. Opening it again finds the running one with `/api/ping` and opens a window on it. It exits ~75 s after its last request (the window asks every 10 s), never during an action, and removes `panel.json`.
- **Checks:** `GET /api/status` gathers everything in parallel. Firewall rules, addresses and obs-ptz's version are cached for 1-5 minutes and re-read after any change or with *Check again* (`?fresh=1`). It also logs in to OBS like a phone (`core.obs_probe`, autofix's websocket client): OBS's version, whether it's streaming or recording, and whether obs-ptz answers `ptz_list_devices`, which confirms *Websocket access = Control* and counts the cameras. And it asks the server which phones used the app (`GET /api/phones`, answered only to 127.0.0.1; `server.py` notes the address of every `/api/` request, and `/api/net`'s Tailscale answer).
- **Actions:** `POST /api/action {name}` runs one at a time in a background thread; the window shows its progress lines from `GET /api/job` and the result. `ws_on`, `ptz`: close OBS with `CloseMainWindow` (as if its X were clicked, so it saves and asks if needed), change, then open OBS again. Both refuse while OBS is streaming or recording.
  OBS sometimes ignores the first close request without logging anything (seen with OBS 32.2.2), so `core.close_obs` asks again every 8 s, for up to 45 s; shutting down takes OBS 10-15 s with several NDI cameras.
  obs-websocket reads its `config.json` only at startup and doesn't write it back on exit (checked 2026-11-23), so turning it on means writing the file and restarting OBS. `firewall`, `ts_on`/`ts_off` (firewall + route), `ts_install`, `ts_open`, `ts_admin`, `server` (restart + Startup and Start menu shortcuts), `uninstall`. Windows' permission prompt gets the window in front as its owner (`GetForegroundWindow`), so it doesn't open behind it as a flashing taskbar button.
- **Layout:** until the three needed steps (remote control, firewall, server starting with Windows) are done, the window lists them first with the next one outlined, and greys out the QR code. Once they are, the QR code comes first, then the status, then the optional parts (obs-ptz, Tailscale). Errors from actions land in `panel.log` in the data folder.

## Console setup
`core.py install` goes through these steps in order:
1. **Python:** reports the Python that runs it (install.ps1 found or installed it).
2. **OBS WebSocket server:** reads obs-websocket's `config.json`. If the server is off, or OBS never set it up, it offers to turn it on.
   It sets `server_enabled`, `auth_required` and `first_load: false`, keeping the existing port and password or making a 12-character password.
3. **obs-ptz:** detects websocket support by looking for `ptz_list_devices` in the DLL.
   If obs-ptz is missing (asks, default No) or too old (asks, default Yes), it can install the newest obs-ptz release numbered 1.0 or later, betas included, from GitHub (`*-windows-x64-Installer.exe`, or arm64).
   That's an Inno Setup installer, run with `/SILENT /SUPPRESSMSGBOXES /NORESTART /SP-`; Windows asks for admin permission.
   Steps 2 and 3 need OBS closed: OBS saves its own copy of the settings on exit, and keeps the plugin file open. Setup asks once, then opens OBS again from the same path.
4. **Tailscale (optional):** if the PC has Tailscale, it asks whether phones may connect over it; if not, it offers to install it (`winget install Tailscale.Tailscale`) and waits up to 3 minutes for the sign-in.
   It doesn't ask again once the firewall rules include Tailscale's range. `-Tailscale` / `-NoTailscale` change the answer.
5. **Firewall:** runs `firewall.ps1` elevated whenever the rules are missing or don't match the Tailscale choice.
6. **Server:** stops this folder's old server, and any other OBS Remote listening on the same port (e.g. a copy in another folder). It starts `pythonw server.py` and adds a Startup shortcut.
   It then checks the page on 127.0.0.1, bypassing any proxy. If there's no answer, it says why: the program holding the port, or the server's own error.
7. **Phone address:** finds this PC's local-network IPv4 addresses, best route first.
   Virtual adapters (Hyper-V, WSL, VirtualBox, VMware, Docker) and VPNs (Tailscale, ZeroTier, WireGuard, …) are skipped, matched on the adapter name and description.
   It prints a QR code for the first address, with the OBS login in the link (see *Sign-in link*). The setup window shows the same codes.
   Re-run setup after changing OBS's websocket password, or the codes sign phones in with the old one.
8. **Tailscale route** (with Tailscale chosen; runs inside step 7, once the LAN address is known): the PC advertises its own LAN address as a subnet route, `tailscale set --advertise-routes=<LAN IP>/32`.
   A phone with Tailscale on (iPhone and Android accept subnet routes by default) then reaches the *same* `http://LAN-IP:port/` from anywhere: one QR code, one home-screen icon, one saved login (localStorage belongs to the address).
   Tailscale rewrites the source of routed traffic to the PC's own LAN address (seen at SMIC), so Windows Firewall sees it as `LocalSubnet` and the normal rules let it in. Tested on Windows 11 with an Android phone on mobile data (MMIC) and from another site's PC (SMIC).
   `--advertise-routes` replaces the whole list, so setup reads the current one from `tailscale debug prefs` and keeps routes it didn't add. The route it added is kept in `tailscale-route.txt` in the data folder, so a new LAN IP replaces the old route, and `-NoTailscale` or `Uninstall.bat` removes it.
   Tailscale needs the route approved once. Setup checks `tailscale status --json` (`Self.PrimaryRoutes` / `AllowedIPs`); if it isn't approved, it opens `login.tailscale.com/admin/machines/<100.x IP>` and checks every 2 s for up to 5 minutes (Enter skips).
   A tailnet policy with `"autoApprovers": {"routes": {"192.168.0.0/16": ["user@example.com"]}}` approves it instantly, with no page.
   Until it's approved, setup falls back to a second code for the PC's 100.x address, offered in the console. The setup window always has it, folded away: Tailscale doesn't pass routes on when a PC is shared into another tailnet, so phones there can only use the 100.x address.
   **Duplicate address:** if another device in the tailnet already shares the same `/32` (`Peer[].PrimaryRoutes`/`AllowedIPs` in `tailscale status --json`), e.g. another venue's PC with the same LAN IP, setup warns, names it, and doesn't share this PC's address: Tailscale would send phones to only one of them, and both venues would share one icon and login.
   **Key expiry:** Tailscale signs a PC out after about 6 months unless *Disable key expiry* is set on it. Setup reads `Self.KeyExpiry` (absent once disabled), shows the date, and asks for it on the same admin-page visit as the route; it waits for both. Only the admin console or Tailscale's API can change it, and an API key on every venue PC would be able to change the whole tailnet, so setup doesn't do it itself.
   The PC's LAN address then matters twice (code and route), so setup asks for a DHCP reservation when the address came from DHCP.

Notes:
- `setup/qr.py` is a standard-library QR encoder: byte mode, error correction level M, versions 1-10 (up to 213 bytes).
  `--rows URL` prints the matrix as 0/1 lines, which the installer draws in the console with half-block characters, black on white.
  `svg()` draws the setup window's codes. It was checked by decoding hundreds of random URLs with OpenCV.
- The `.ps1` files must stay ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
  The console QR is drawn by `core.py` (half blocks, black on white via ANSI colours, which it turns on with `SetConsoleMode`).
- Firewall rules count as right only when their ports match too, so `Install.bat -Port 8766` updates them.
- `setup/firewall.ps1` runs elevated. It adds two inbound TCP rules (page port and OBS websocket port), limited to `RemoteAddress LocalSubnet`, or removes them with `-Remove`.
  With `-Tailscale` (when Tailscale was chosen) they also allow `100.64.0.0/10`, which only devices in the tailnet can reach. A Tailscale address is a /32, so `LocalSubnet` alone never covers other tailnet devices.
  The installer re-runs it whenever the rules don't match the Tailscale choice.
- `core.py uninstall` stops the server, removes the shortcut, removes the Tailscale route setup added (other routes stay) and removes the rules.

## Installer (`installer/`)
`OBS-Remote-Setup-<version>.exe` is an Inno Setup 6 installer (`installer/obs-remote.iss`), built by `installer/build.py`, which the GitHub Action `.github/workflows/installer.yml` runs for every published release and attaches to it (it checks the tag matches `VERSION`).
- **Code signing (SignPath Foundation, free for open source):** the workflow signs only when the repository has the variable `SIGNPATH_ORGANIZATION_ID` (with `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_SIGNING_POLICY_SLUG`, optionally `SIGNPATH_ARTIFACT_CONFIGURATION_SLUG`) and the secret `SIGNPATH_API_TOKEN`. It uploads the unsigned Setup.exe as a GitHub artifact, `signpath/github-action-submit-signing-request@v3` submits it and waits up to 2 hours for the manual approval SignPath Foundation requires, then checks the signature is valid before attaching it. The artifact configuration to paste into signpath.io is `installer/signpath-artifact-configuration.xml`. The installer's file details (product name *OBS Remote*, numeric version, copyright) come from `obs-remote.iss`; SignPath enforces the product name. The README's *Code signing policy*, *Privacy* and *What setup changes on the PC* sections are SignPath Foundation's conditions; signed releases must also carry their attribution line.
- **Python comes with it:** Python's official embeddable package (pinned version and SHA-256 in `build.py`; its programs are signed by the Python Software Foundation) goes in `runtime/`.
  That Python only searches the paths in its `._pth` file, not the script's folder, so `build.py` adds `..` (the program folder) there.
- **Program files:** what `git ls-files` has (tracked and untracked-but-not-ignored, so a local build matches the working tree), minus `.github`, `installer`, `docs`, `Install.bat`, `Uninstall.bat`.
- **Per user, no admin:** `PrivilegesRequired=lowest`, into `%LOCALAPPDATA%\Programs\OBS Remote`; only the firewall step asks for admin, from the setup window. Unsigned, so a downloaded Setup.exe gets SmartScreen's *Windows protected your PC* (More info → Run anyway). One started by the in-app updater has no download mark, so it doesn't.
- **After installing**, `core.py start`: on a PC set up before (`settings.json` or the Startup shortcut exists, from any copy) it stops the old server (`stop_servers` also stops another copy on the port), starts this one, and points the Startup and Start menu shortcuts here. On a new PC it does nothing, and the setup window opens.
- **Before replacing files** (`PrepareToInstall`), `core.py stop` stops every python process whose command line contains this folder (server, setup window), except itself. `[InstallDelete]` removes `runtime/` so a new Python replaces the old one cleanly.
- **Uninstall** (Apps list, or the setup window's *Uninstall*, which starts `unins000.exe` on an installed copy): `[UninstallRun]` runs `core.py uninstall` (server, shortcuts, Tailscale route, firewall rules: one admin prompt), then the whole folder is deleted. The data folder stays.
- **Updates:** `server.py` sees an installed copy (`runtime/pythonw.exe` and `unins000.exe` next to it, `INSTALLED`). Its Update downloads the release's `OBS-Remote-Setup-*.exe` asset and starts it detached with `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=<data>\update.log`, then answers the phone without restarting itself: the installer stops it and `core.py start` starts the new one (about 15 s; the phone waits up to 90 s). If the release has no installer yet (the Action takes a few minutes), it says to try again shortly.
- Tested 2026-11-23 on Windows 11: silent install taking over a dev-folder setup, setup window and OBS login on the bundled Python, in-app update test1 → test2 (13 s, Apps list updated, data kept), uninstall (folder, Apps entry, shortcuts, rules, route removed; data kept).

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
- `POST /api/update` (on a downloaded folder; an installed copy runs the installer, see *Installer*) needs the header `X-OBS-Remote: 1`. A cross-site page can't send it without a CORS preflight, which the server never allows.
  It re-reads the latest release, downloads that tag's ZIP from codeload.github.com, checks that it is OBS Remote, and copies it over the folder, never outside it.
  It never touches `Phone address.txt`.
  Then it stops serving, and the main program starts a fresh `server.py`, which retries the port for up to 10 s.
  The relaunch must happen in the main program: from a worker thread it gets killed when the program ends.
- Downloads go through Python's TLS first. If certificate verification fails, they fall back to Windows' `curl.exe`, which uses the Windows certificate store.
  This was seen with GitHub's newer Let's Encrypt chain, which Python couldn't complete.
- `python server.py update [tag]` does the same from the command line and exits. Run `Install.bat` afterwards to restart the server.
- The page checks `/api/version` when it loads, when Settings opens and every 6 hours. When the server reports an update, it shows a dot on ⋮ and on its Settings item.
- Before 1.2.0, copies followed the `VERSION` file on `main` instead. A 1.1.x copy therefore moves to 1.2.0 when `main` says 1.2.0, and follows releases from then on.

## README screenshots
The pictures in the README are made, not photographed: a drawn venue and a pretend OBS, so no real venue or people appear.
They, the full-size venue pictures and the tools that make them live in [mdukasa/obs-remote-assets](https://github.com/mdukasa/obs-remote-assets), which also explains how to re-make them after a UI change.
