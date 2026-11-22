# OBS Remote

Control OBS Studio and your PTZ cameras from a phone on the same Wi-Fi. No app store and no account: it's a web page you add to your home screen.

**Live tab:** preview and program pictures, tap a scene and press TAKE, start/stop the stream and recording, mute buttons with live sound meters. If OBS has the [Advanced Scene Switcher](https://github.com/WarmUpTill/SceneSwitcher) plugin, an **Auto scene switching** switch turns its automatic switching on and off (hide it in Settings if you don't use it).
**Camera tab:** joystick pan/tilt, zoom and focus, presets with thumbnails, and a red LIVE tag on the picture when the camera you're moving is live. Swipe the picture sideways to switch camera. The picture (and the Live tab's Preview/Program) stays in view while you scroll.

## What you need
- A Windows PC running **OBS Studio 28 or newer** (it has the WebSocket server built in).
- Phones on the **same network** as that PC.
- For the Camera tab only: the **[obs-ptz](https://github.com/glikely/obs-ptz/releases) plugin, version 1.0 (beta) or newer**.
  The older stable 0.19.x can't be controlled from outside OBS, so the Camera tab will say so; everything else still works.
- Python 3. The installer offers to install it for you if it's missing.

## Install (about 5 minutes)
1. **In OBS:** *Tools → WebSocket Server Settings* → tick **Enable WebSocket server**. Keep **Enable Authentication** on and note the password (*Show Connect Info*).
2. **If you use obs-ptz:** in the *PTZ Controls* dock open its settings and set **Websocket access** to **Control**.
3. **Download** the latest release: open **[Releases → Latest](https://github.com/mdukasa/obs-remote/releases/latest)** and, under *Assets*, click **Source code (zip)**.
   Extract it somewhere permanent, e.g. `C:\OBS Remote`. Don't run it from the Downloads folder or from inside the ZIP.
   After this you never download it again: the app updates itself (see [Updating](#updating)).
4. **Double-click `Install.bat`.** Windows will ask once for admin permission to open the firewall to your local network. Say **Yes**.
5. The window shows a **QR code**: point the phone's camera at it and tap the link. The address is printed under it too, e.g. `http://192.168.1.50:8765/`.
   To see the code again later, open `Phone address.html` next to `Install.bat`.

The installer checks Python, OBS and obs-ptz, opens the firewall (local network only), starts the server and sets it to start whenever this PC signs in.
Run `Install.bat` again any time to repair it.

## Updating
When a new version is released, a dot appears on the ⚙ button. Open Settings and tap **Update**: it shows what's new, then the OBS PC downloads the release from GitHub and restarts the app's web server. Phones reload by themselves a few seconds later, and OBS itself keeps running.
Copies installed before version 1.1.0 don't have the Update button yet: download the [latest release](https://github.com/mdukasa/obs-remote/releases/latest) once more and extract it over the old folder.
From the command line, `py server.py update` in the folder installs the latest release; then run `Install.bat` to restart it.

## On each phone
1. Join the same Wi-Fi as the OBS PC and open the address.
2. Enter the OBS WebSocket password. The phone remembers it.
3. Add it to the home screen: **iPhone:** Share → *Add to Home Screen*. **Android (Chrome):** ⋮ → *Add to Home screen*.

Tip: give the OBS PC a **fixed IP address** (a DHCP reservation in your router), so the phone's link never changes.

## Using it
- **Scenes:** in Studio Mode, tap a scene to put it in Preview, then press **TAKE**. With Studio Mode off, a tap sends the scene straight to Program. Settings (⚙) → *Live tab* turns Studio Mode on or off and hides scenes you never use.
- **Stream / Record:** these always ask before starting or stopping.
- **Camera:** the joystick goes faster the further you push it. The camera only moves while your finger is down, and stops when you let go, switch apps or lock the phone.
  The **Speed** slider is a share of each camera's top speed, as set in its PTZ filter in OBS.
  **Tap** a preset to go there. **Hold** a preset to save the current position over it (it asks first).
  **↻ Refresh Camera** reconnects the camera when its picture freezes or its PTZ control stops answering, e.g. after the camera rebooted.
  It reconnects both the picture source (NDI, GStreamer, webcam, media…) and the obs-ptz link, and takes a few seconds. It asks first if the camera is on air.
- **Camera names, order and pictures:** Settings (⚙) → *PTZ cameras* lets you give each camera a short name (e.g. show `CAM01-NDI` as `CAM01`)
  and choose which OBS source gives its picture. These are saved in OBS itself, so every phone sees the same. Cameras are listed in name order.
  If a camera's PTZ control is on a source with no picture (e.g. a hidden webcam source), the app automatically uses an active source whose name starts with the same name.
- **Frozen NDI cameras:** fixed automatically. See [Auto-reconnect of frozen cameras](#auto-reconnect-of-frozen-cameras) below.
- **Picture quality:** Settings → Connection → Picture: *Smooth* (25 fps), *Balanced* (10, the default) or *Data saver* (2). Smooth uses about 5 Mbit/s of Wi-Fi.

## Auto-reconnect of frozen cameras
**Why it exists.** Some NDI cameras' pictures stall now and then: OBS keeps showing the last frame as if nothing happened, writes nothing in its log, and the camera's PTZ control keeps working.
On a live stream that can go unnoticed for a long time. The cure is always the same: re-select the camera in the NDI source's properties.
At SMIC (FoMaKo PTZ cameras) this happened within an hour of starting OBS, so OBS Remote now does the re-select for you.

**How it works.** It runs inside OBS Remote's server on the OBS PC, so it works even when no phone has the app open.
1. **What it watches:** only the NDI sources that belong to your PTZ cameras (and the picture chosen for each camera in Settings), and only while that source is in use in OBS. Nothing else is touched.
2. **How it looks:** every 4 seconds it takes a small snapshot of each of those pictures from OBS and compares it with the previous ones. A live camera never gives two identical snapshots in a row, because of tiny sensor noise, even when nothing in the room moves.
3. **When it acts:** the picture was moving (at least 3 different snapshots in the 40 seconds before), then shows *exactly* the same frame for 20 seconds. That's a freeze.
4. **What it does:** it switches the NDI source to "no camera" and straight back, like you would in the source's properties. The picture is back within a second or two.
5. **Safety limits:**
   - At most one reconnect per camera per minute.
   - A picture that has never been seen moving gets one try only. That covers a slide, a camera that's switched off, or a camera that was already frozen when the server started. After that it's left alone until it moves again.
   - It never moves a camera and never changes scenes.

**What you see.** In Settings (⚙) → *Cameras*: a switch to turn it off, which cameras it's watching, and the last fix with how many there were today.
Every fix is also written to `autofix.log` in the OBS Remote folder, with the time, camera and how long the picture had been frozen. The list in Settings is reloaded from that file when OBS Remote restarts, so updates don't wipe it.

**Limits.** A freeze is visible for about 20–25 seconds before it's fixed. It can't help with sources other than NDI (use **↻ Refresh Camera**), or with a camera that's offline.
If the log shows fixes often, the real cause is worth finding: at SMIC, turning off *NDI Multicast* in the cameras' own settings stopped the freezes.

## Troubleshooting
| Problem | Fix |
|---|---|
| Page won't open on the phone | Same Wi-Fi as the PC? Run `Install.bat` again and say Yes to the admin prompt. Guest Wi-Fi networks often block devices from seeing each other. |
| "Can't reach OBS" | Is OBS open, with the WebSocket server enabled? |
| "Wrong OBS websocket password" | Check it in OBS → *Tools → WebSocket Server Settings → Show Connect Info*. |
| Camera tab: "OBS has no PTZ control for this app" | Install obs-ptz 1.0 (beta) or newer and set *Websocket access* = *Control*. |
| Camera moves but the Speed slider seems to do little | The camera's max speed in its obs-ptz filter is low. Raise it there. |
| Camera picture frozen, or the camera shows "not connected" | NDI camera pictures are reconnected automatically after about 20 seconds (Settings → *Cameras*; see [Auto-reconnect](#auto-reconnect-of-frozen-cameras)). Otherwise press **↻ Refresh Camera** on the Camera tab. If NDI pictures freeze often, try turning off *NDI Multicast* in the camera's own settings. |
| A camera keeps moving after the phone dropped off Wi-Fi | Press **■ Stop Moving**, or recall a preset. |

## Uninstall
Double-click `Uninstall.bat`. It stops the server, removes it from startup and removes the firewall rules. Then delete the folder.

## Security
Anyone who can open the page **and** knows the OBS WebSocket password can control OBS. That's no more access than the password already gives.
The firewall rules only accept connections from the local network. Don't forward these ports on your router.

How it works: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).
