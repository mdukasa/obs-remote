# OBS Remote

Control OBS Studio and your PTZ cameras from a phone on the same Wi-Fi. No app store, no account: it's a web page you add to your home screen.

<p align="center">
  <img src="https://raw.githubusercontent.com/mdukasa/obs-remote-assets/main/screenshots/live.png" width="270" alt="Live tab: preview and program pictures, TAKE, scenes, stream and recording, audio">
  &nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/mdukasa/obs-remote-assets/main/screenshots/camera.png" width="270" alt="Camera tab: camera picture, direction buttons, zoom, focus, speed and presets">
</p>

- **Live tab:** preview and program pictures, scenes with TAKE, stream and record, mute buttons with sound meters, and a switch for the [Advanced Scene Switcher](https://github.com/WarmUpTill/SceneSwitcher) plugin if you use it.
- **Camera tab:** pan, tilt, zoom and focus, presets with thumbnails, and a red **LIVE** tag when the camera you're moving is on air. Swipe the picture to switch camera.

<sub>Screenshots use made-up pictures, not real camera footage.</sub>

## What you need
- A Windows PC with **OBS Studio 28+**.
- Phones on the **same network** as that PC.
- For the Camera tab: the **[obs-ptz](https://github.com/glikely/obs-ptz/releases) plugin, 1.0 (beta) or newer**. The installer offers to install or update it. Everything else works without it.
- Python 3. The installer offers to install it.

## Install (about 5 minutes)
1. **Download** the [latest release](https://github.com/mdukasa/obs-remote/releases/latest) (*Assets* → **Source code (zip)**) and extract it somewhere permanent, e.g. `C:\OBS Remote`.
2. **Double-click `Install.bat`** and answer its questions. It offers to turn on OBS's WebSocket server and to install obs-ptz, then asks Windows to open the firewall to your local network: click **Yes**.
3. **If you use obs-ptz:** in OBS, *PTZ Controls* dock → settings → **Websocket access** = **Control**.
4. **Scan the QR code** with the phone's camera. It opens the app and signs the phone in to OBS in one go. Then add the page to the home screen.

<p align="center"><img src="https://raw.githubusercontent.com/mdukasa/obs-remote-assets/main/screenshots/installer.png" width="620" alt="The installer: four checks marked OK, then a QR code and the phone address"></p>

It starts by itself whenever the PC signs in. Run `Install.bat` again any time to repair it, or after changing OBS's WebSocket password. To see the QR code later, open `Phone address.html` in the folder.

The QR code contains the OBS WebSocket password, so only show it to people who may control OBS. Phones can also type the password in Settings instead.

Tip: give the OBS PC a **fixed IP address** in your router, so the phone's link never changes.

**Away from the venue's Wi-Fi?** The installer asks whether to set up [Tailscale](https://tailscale.com/) (free; installs it if needed). Say yes and it lets Tailscale through the firewall and offers a second QR code for phones that have the Tailscale app, signed in to the same account. That code is also in `Phone address.html` under **Show the Tailscale code**. To change your answer later, run `Install.bat -Tailscale` or `Install.bat -NoTailscale`.

## Updating
A dot on the ⚙ button means a new version is out. Open Settings and tap **Update**, or **Check for updates**. OBS keeps running and phones reload by themselves.

## Using it
- **Scenes:** in Studio Mode, tap a scene to preview it, then **TAKE**. With Studio Mode off, a tap goes straight to program.
- **Camera:** hold an arrow to move; the middle **■** stops. The camera only moves while your finger is down. You can switch to a joystick in Settings → *Cameras*.
- **Speed:** at 100% the app moves as fast as obs-ptz's own controls. Lower it for finer moves.
- **Presets:** tap to go there, hold to save the current position over it.
- **OBS closed or crashed?** A banner says so, with a **Start OBS** button that opens OBS on the PC again.
- **↻ Refresh Camera:** reconnects a camera whose picture froze or whose control stopped answering, e.g. after a reboot.
- **Listen (optional, off by default):** turn on *Settings → Live tab → Listen on this phone* to hear OBS's monitored sources on the phone, about 0.2 s late. The 🎧 button on each source turns OBS monitoring on or off for it. Monitored sources also play on OBS's monitoring device (OBS *Settings → Audio → Advanced*), so point that at a spare output if it's the hall's speakers.
- **Settings (⚙):** connection and picture quality, Studio Mode, which scenes show, hide the audio section, camera names and which OBS source shows each camera.

## Frozen cameras fix themselves
Some NDI cameras sometimes freeze: OBS keeps showing the last frame and nothing reports a problem. OBS Remote's server on the OBS PC watches your PTZ cameras' NDI pictures. If one shows exactly the same frame for 20 seconds after it was moving, it re-selects the camera in the NDI source, which brings it back.
It never moves a camera or changes scenes, works with no phone open, and you can turn it off in Settings → *Cameras*. Each fix is listed there and saved in `autofix.log`.
Details: [how auto-reconnect works](docs/HOW-IT-WORKS.md#auto-reconnect-of-frozen-ndi-pictures-autofixpy).

## Troubleshooting
| Problem | Fix |
|---|---|
| Page won't open on the phone | Same Wi-Fi as the PC? Run `Install.bat` again and click Yes. Guest Wi-Fi often blocks this. |
| "OBS is closed on the PC" | Tap **Start OBS**. |
| "OBS isn't answering" | OBS is open but its WebSocket server is off. Run `Install.bat` again and let it turn it on, or tick it in OBS → *Tools → WebSocket Server Settings*. |
| "Wrong OBS websocket password" | OBS's password changed. Run `Install.bat` again and rescan the code, or type the new password in Settings. |
| Setup says the server "didn't start" | It names the program using port 8765. Close it, or run `Install.bat -Port 8766`. |
| "OBS has no PTZ control for this app" | Install obs-ptz 1.0 (beta) or newer and set *Websocket access* = *Control*. |
| Camera is very slow even at 100% | Its max speed in the camera's obs-ptz filter in OBS is low. |
| Camera picture frozen | Wait about 20 s for the automatic fix, or press **↻ Refresh Camera**. If it happens often, try turning off *NDI Multicast* in the camera. |
| Camera keeps moving after the phone lost Wi-Fi | Press **■ Stop Moving**, or recall a preset. |

## Uninstall
Double-click `Uninstall.bat`, then delete the folder.

## Security
Anyone who can open the page **and** knows the OBS WebSocket password can control OBS, which is the same access the password already gives. Listen and **Start OBS** also need the password. The firewall only allows the local network, plus your tailnet if you chose Tailscale; don't forward these ports on your router.

How it works inside: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md). Screenshots, full-size demo pictures and the tools that make them: [obs-remote-assets](https://github.com/mdukasa/obs-remote-assets).
