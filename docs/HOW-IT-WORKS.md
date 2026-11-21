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
The page subscribes to `InputVolumeMeters` (about 20 per second, about 9 KB/s) only while the Live tab is on screen, by re-identifying with op 3.
Inputs are listed when their type can have audio. Browser sources are only listed when *Control audio via OBS* (`reroute_audio`) is ticked, as in OBS's own mixer.

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

## Setup scripts
- `setup/install.ps1` finds Python 3.8+ (or offers `winget install Python.Python.3.12`) and reads OBS's websocket config.
  It detects whether obs-ptz has websocket support by looking for `ptz_list_devices` in the DLL, then opens the firewall.
  It starts `pythonw server.py` and adds a Startup shortcut.
  Switches: `-Port`, `-SkipFirewall`, `-SkipStartup`.
- `setup/firewall.ps1` runs elevated. It adds two inbound TCP rules (page port and OBS websocket port), limited to `RemoteAddress LocalSubnet`, or removes them with `-Remove`.
- `setup/uninstall.ps1` stops the server, removes the shortcut and removes the rules.
