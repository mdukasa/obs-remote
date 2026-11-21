# OBS Remote

Control OBS Studio and your PTZ cameras from a phone on the same Wi-Fi. No app store and no account: it's a web page you add to your home screen.

**Live tab:** preview and program pictures, tap a scene and press TAKE, start/stop the stream and recording, mute buttons with live sound meters.
**Camera tab:** joystick pan/tilt, zoom and focus, presets with thumbnails, and a red ON AIR warning when the camera you're moving is live.

## What you need
- A Windows PC running **OBS Studio 28 or newer** (it has the WebSocket server built in).
- Phones on the **same network** as that PC.
- For the Camera tab only: the **[obs-ptz](https://github.com/glikely/obs-ptz/releases) plugin, version 1.0 (beta) or newer**.
  The older stable 0.19.x can't be controlled from outside OBS, so the Camera tab will say so; everything else still works.
- Python 3. The installer offers to install it for you if it's missing.

## Install (about 5 minutes)
1. **In OBS:** *Tools → WebSocket Server Settings* → tick **Enable WebSocket server**. Keep **Enable Authentication** on and note the password (*Show Connect Info*).
2. **If you use obs-ptz:** in the *PTZ Controls* dock open its settings and set **Websocket access** to **Control**.
3. **Download** this project: the green **Code** button → **Download ZIP**. Extract it somewhere permanent, e.g. `C:\OBS Remote`.
   (Don't run it from the Downloads folder or inside the ZIP.)
4. **Double-click `Install.bat`.** Windows will ask once for admin permission to open the firewall to your local network. Say **Yes**.
5. The window shows the address to open, e.g. `http://192.168.1.50:8765/`. It's also saved in `Phone address.txt`.

The installer checks Python, OBS and obs-ptz, opens the firewall (local network only), starts the server and sets it to start whenever this PC signs in.
Run `Install.bat` again any time to repair or update.

## On each phone
1. Join the same Wi-Fi as the OBS PC and open the address.
2. Enter the OBS WebSocket password. The phone remembers it.
3. Add it to the home screen: **iPhone:** Share → *Add to Home Screen*. **Android (Chrome):** ⋮ → *Add to Home screen*.

Tip: give the OBS PC a **fixed IP address** (a DHCP reservation in your router), so the phone's link never changes.

## Using it
- **Scenes:** in Studio Mode, tap a scene to put it in Preview, then press **TAKE**. Settings (⚙) can make taps go straight to Program, and can hide scenes you never use.
- **Stream / Record:** these always ask before starting or stopping.
- **Camera:** the joystick goes faster the further you push it. The camera only moves while your finger is down, and stops when you let go, switch apps or lock the phone.
  The **Speed** slider is a share of each camera's top speed, as set in its PTZ filter in OBS.
  **Tap** a preset to go there. **Hold** a preset to save the current position over it (it asks first).
  **↻ Refresh Camera** reconnects the camera when its picture freezes or its PTZ control stops answering, e.g. after the camera rebooted.
  It reconnects both the picture source (NDI, GStreamer, webcam, media…) and the obs-ptz link, and takes a few seconds. It asks first if the camera is on air.
- **Camera names, order and pictures:** Settings (⚙) → *PTZ cameras* lets you give each camera a short name (e.g. show `CAM01-NDI` as `CAM01`)
  and choose which OBS source gives its picture. These are saved in OBS itself, so every phone sees the same. Cameras are listed in name order.
  If a camera's PTZ control is on a source with no picture (e.g. a hidden webcam source), the app automatically uses an active source whose name starts with the same name.
- **Picture quality:** Settings → Picture: *Smooth* (25 fps), *Balanced* (10) or *Data saver* (2). Smooth uses about 5 Mbit/s of Wi-Fi.

## Troubleshooting
| Problem | Fix |
|---|---|
| Page won't open on the phone | Same Wi-Fi as the PC? Run `Install.bat` again and say Yes to the admin prompt. Guest Wi-Fi networks often block devices from seeing each other. |
| "Can't reach OBS" | Is OBS open, with the WebSocket server enabled? |
| "Wrong OBS websocket password" | Check it in OBS → *Tools → WebSocket Server Settings → Show Connect Info*. |
| Camera tab: "OBS has no PTZ control for this app" | Install obs-ptz 1.0 (beta) or newer and set *Websocket access* = *Control*. |
| Camera moves but the Speed slider seems to do little | The camera's max speed in its obs-ptz filter is low. Raise it there. |
| Camera picture frozen, or the camera shows "not connected" | Press **↻ Refresh Camera** on the Camera tab. If NDI pictures freeze often, try turning off *NDI Multicast* in the camera's own settings. |
| A camera keeps moving after the phone dropped off Wi-Fi | Press **■ Stop Moving**, or recall a preset. |

## Uninstall
Double-click `Uninstall.bat`. It stops the server, removes it from startup and removes the firewall rules. Then delete the folder.

## Security
Anyone who can open the page **and** knows the OBS WebSocket password can control OBS. That's no more access than the password already gives.
The firewall rules only accept connections from the local network. Don't forward these ports on your router.

How it works: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md).
