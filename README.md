# OBS Remote

Control OBS Studio and your PTZ cameras from a phone on the same Wi-Fi. No app store, no account: it's a web page you add to your home screen.

<p align="center">
  <img src="https://raw.githubusercontent.com/mdukasa/obs-remote-assets/main/screenshots/live.png" width="270" alt="Switcher: preview and program pictures, CUT and TAKE, scene keys with thumbnails, Go live and Record">
  &nbsp;&nbsp;
  <img src="https://raw.githubusercontent.com/mdukasa/obs-remote-assets/main/screenshots/camera.png" width="270" alt="Camera: camera picture, Move and Presets, direction buttons, zoom, focus and speed">
</p>

- **Switcher:** preview and program pictures, **CUT** and **TAKE**, and your scenes as keys with small pictures. Red always means on air, green means preview.
- **Go live and Record** sit at the top of every screen. While they run they turn into red timecodes; stopping takes a one-second hold, so a stray tap can't end the service.
- **Going live on YouTube:** if OBS is signed in to your YouTube account, **Go live** asks for the title, description, privacy and the rest of OBS's *YouTube Broadcast Setup* questions on the phone, then fills that window in on the PC for you. Your saved details in OBS stay as they are. If a broadcast is already set up in OBS (**Manage Broadcast** on the PC), or OBS uses a stream key, it just starts.
- **Camera:** pan, tilt, zoom and focus, presets with thumbnails, and an **ON AIR** tag when the camera you're moving is in the program. Swipe the picture to switch camera.
- **Audio:** mute buttons with sound meters, and **Listen** to hear OBS on the phone.

<sub>Screenshots use made-up pictures, not real camera footage.</sub>

## What you need
- A Windows PC with **OBS Studio 28+**.
- Phones on the **same network** as that PC.
- For the Camera tab: the **[obs-ptz](https://github.com/glikely/obs-ptz/releases) plugin, 1.0 (beta) or newer**. The installer offers to install or update it. Everything else works without it.

## Install (about 5 minutes)
1. **Download** `OBS-Remote-Setup-….exe` from the [latest release](https://github.com/mdukasa/obs-remote/releases/latest) (*Assets*) and run it. It installs for your Windows user only (no admin needed) and brings everything it needs, Python included.
   Windows may say *Windows protected your PC*, because the installer isn't signed: click **More info** → **Run anyway**.
2. **The setup window opens** at the end (later: Start menu → **OBS Remote**). Work down its list: turn on OBS's remote control, **Allow phones** through the firewall (Windows asks for permission: click **Yes**) and start OBS Remote. It can also install obs-ptz and set up Tailscale.
3. **If you use obs-ptz:** in OBS, *PTZ Controls* dock → settings → **Websocket access** = **Control**. The setup window says how many cameras phones can control, so you can see it worked.
4. **Scan the QR code** in the setup window with the phone's camera. It opens the app and signs the phone in to OBS in one go. Then add the page to the home screen: on an iPhone, Safari's Share button → **Add to Home Screen** (it then opens full screen like an app); on Android, Chrome's ⋮ menu → **Add to home screen** (a shortcut that opens in Chrome, since phones only fully install apps from https pages).

<p align="center"><img src="https://raw.githubusercontent.com/mdukasa/obs-remote-assets/main/screenshots/installer.png" width="620" alt="The setup window: Ready, the QR code for phones, the phones that used it lately, and every check green"></p>

It starts by itself whenever the PC signs in. To see the QR code again, check that everything is working, or fix something, open **OBS Remote** from the Start menu (or double-click `Install.bat` again). It also lists the phones that used the app in the last hour.

**Without the installer:** download *Source code (zip)* instead, extract it somewhere permanent, and double-click `Install.bat` (it offers to install Python if needed). `Install.bat -Console` asks the same questions in a console (so do the switches below, like `-Port 8766`). If you later run the installer, it takes over from that folder.

The QR code contains the OBS WebSocket password, so only show it to people who may control OBS. Phones can also type it in Settings → *Connection* → *Enter the details by hand* instead.

Tip: give the OBS PC a **fixed IP address** in your router, so the phone's link never changes.

**Away from the venue's Wi-Fi?** The setup window can set up [Tailscale](https://tailscale.com/) (free; it installs it if needed). Then the same QR code and home-screen icon also work from anywhere, on phones with the Tailscale app signed in to the same account: set everyone up locally, and add Tailscale to a phone whenever it's needed. Setup opens Tailscale's admin page once so you can approve this PC's address (*Machine settings* → *Edit route settings* → tick it → *Save*) and turn off key expiry (*Machine settings* → *Disable key expiry*, or the PC drops off Tailscale after about 6 months); the window ticks both off by itself as soon as you do. Give the PC a fixed IP address in your router. **Stop using Tailscale** undoes it.

## Updating
A dot on the ⋮ button means a new version is out. Open ⋮ → **Settings** and tap **Update**, or **Check now** under *About*. OBS keeps running and phones reload by themselves. An installed copy updates by running the new installer quietly, so Windows' Apps list shows the new version too.

## Using it
- **Scenes:** in Studio Mode, tap a scene to preview it, then **TAKE** (OBS's transition) or **CUT**. With Studio Mode off, a tap goes straight to program.
- **Lots of scenes?** Every scene is a key until you tap **Pick favourites** and star some. Then only starred scenes are keys, plus whatever is on air or in preview, and the last key, **All scenes**, opens the full list with search. Stars are saved in OBS, so every phone shows the same keys.
- **Go live / Record:** tap either to open the stream and recording sheet. Starting asks first; to stop, hold the button for a second.
- **Camera:** switch between **Move** and **Presets** under the picture. Hold an arrow to move; the middle **■** stops. The camera only moves while your finger is down. You can switch to a joystick in ⋮ → Settings → *Camera controls*. Swiping up and down over the controls scrolls without moving the camera.
- **Speed:** at 100% the app moves as fast as obs-ptz's own controls. Lower it for finer moves.
- **Presets:** tap to go there, hold to save the current position over it. **Show all** lists presets without a picture too.
- **OBS closed or crashed?** A banner says so, with a **Start OBS** button that opens OBS on the PC again. If OBS gets stuck while closing (its window has gone but it never quits), the banner says so and, after 15 seconds, **Start OBS** ends the stuck copy and starts OBS again.
- **⋮ menu:** CPU, frame rate and dropped frames, the [Advanced Scene Switcher](https://github.com/WarmUpTill/SceneSwitcher) switch if OBS has that plugin, **Refresh camera** on the Camera tab, and Settings.
- **Refresh camera:** reconnects a camera whose picture froze or whose control stopped answering, e.g. after a reboot.
- **Listen:** tap **Listen** on the Audio tab to hear OBS's monitored sources on the phone, about 0.2 s late; tap again to stop. It's silent until you tap it. The 🎧 button on each source turns OBS monitoring on or off for it. Monitored sources also play on OBS's monitoring device (OBS *Settings → Audio → Advanced*), so point that at a spare output if it's the hall's speakers.
- **On the OBS PC:** OBS Remote's icon sits by the clock (Windows may tuck it under the ^ arrow; drag it out to keep it in view). Green dot: connected to OBS; amber: not. Hover for how many phones are using it, click to open the setup window and QR code, right-click to start OBS, restart or stop OBS Remote, or turn on notifications when a frozen camera is fixed or an update is out.
- **Settings (⋮ → Settings):** *Connection* (which PC; scan the setup window's code to change it), *This phone* (picture quality, buttons or joystick), and *OBS*, which changes OBS for every phone (Studio Mode, fixing frozen cameras). Changes apply straight away.

## Frozen cameras fix themselves
Some NDI cameras sometimes freeze: OBS keeps showing the last frame and nothing reports a problem. OBS Remote's server on the OBS PC watches your PTZ cameras' NDI pictures. If one shows exactly the same frame for 20 seconds after it was moving, it re-selects the camera in the NDI source, which brings it back.
It never moves a camera or changes scenes, works with no phone open, and you can turn it off in Settings → *OBS*. Each fix is listed there and saved in `autofix.log` in `%LOCALAPPDATA%\OBS Remote`.
Details: [how auto-reconnect works](docs/HOW-IT-WORKS.md#auto-reconnect-of-frozen-ndi-pictures-autofixpy).

## Troubleshooting
| Problem | Fix |
|---|---|
| Page won't open on the phone | Same Wi-Fi as the PC? Open OBS Remote from the Start menu and fix anything it marks. Guest Wi-Fi often blocks this. |
| "OBS is closed on the PC" | Tap **Start OBS**. |
| "OBS is stuck closing" | Its window has gone but it never finished quitting. Tap **Start OBS**: it ends the stuck copy and starts OBS again. |
| "OBS isn't answering" | OBS is open but its WebSocket server is off. Open OBS Remote from the Start menu and turn it on, or tick it in OBS → *Tools → WebSocket Server Settings*. |
| "Wrong OBS websocket password" | OBS's password changed. Open OBS Remote from the Start menu and rescan its code, or type the new password on the *Connection* page the app opens. |
| Setup says the server "didn't start" | It names the program using port 8765. Close it, or run `Install.bat -Port 8766` (the window then uses that port too). |
| "OBS has no PTZ control for this app" | Install obs-ptz 1.0 (beta) or newer and set *Websocket access* = *Control*. |
| Camera is very slow even at 100% | Its max speed in the camera's obs-ptz filter in OBS is low. |
| Camera picture frozen | Wait about 20 s for the automatic fix, or press **Refresh camera**. If it happens often, try turning off *NDI Multicast* in the camera. |
| "Couldn't go live" (YouTube) | The message says why. OBS's YouTube window may be waiting on the PC: finish it there. Nothing goes live until it's filled in. |
| Camera keeps moving after the phone lost Wi-Fi | Press the middle **■** (or **Stop** next to the joystick), or recall a preset. |

## Uninstall
Windows Settings → *Apps* → **OBS Remote** → Uninstall (or, in the setup window, *More* → **Uninstall**). Without the installer: double-click `Uninstall.bat`, then delete the folder. Logs are kept in `%LOCALAPPDATA%\OBS Remote`; delete that folder too if you don't need them.

## Security
Anyone who can open the page **and** knows the OBS WebSocket password can control OBS, which is the same access the password already gives. Listen, **Start OBS** and going live on YouTube also need the password. The firewall only allows the local network, plus your tailnet if you chose Tailscale; don't forward these ports on your router.

## What setup changes on the PC
Each change is shown in the setup window, and the ones marked *asks first* happen only when you press its button. Uninstalling undoes them.
- **OBS:** turns on OBS's WebSocket server, keeping its port and password, or making a password if there is none (*asks first*; OBS closes and opens again). Can install or update the [obs-ptz](https://github.com/glikely/obs-ptz) plugin (*asks first*).
- **Windows Firewall:** two inbound rules named *OBS Remote - …* for the app's port (8765) and OBS's WebSocket port (4455), open only to the local network, plus your tailnet if you chose Tailscale (*asks first*; Windows asks for permission).
- **Startup and Start menu:** an *OBS Remote* shortcut in each, so the app's small web server starts when you sign in.
- **Tailscale** (only if you set it up): installs Tailscale if needed, and shares this PC's own LAN address (a single address, nothing else on the network) with your tailnet.
- **Files:** the program in `%LOCALAPPDATA%\Programs\OBS Remote` (or the folder you extracted), logs and settings in `%LOCALAPPDATA%\OBS Remote`.

## Privacy
OBS Remote has no accounts, analytics or tracking, and sends nothing about you or your venue anywhere. Phones talk only to the OBS PC. The OBS PC connects to the internet only:
- to **check for updates**: it asks GitHub (`api.github.com`) for this project's latest release when a phone opens the app or Settings, at most every 10 minutes; GitHub sees the PC's IP address, as with any visit to GitHub;
- when you ask it to: **Update**, **Install obs-ptz** (from GitHub), **Set up Tailscale** (winget), and the Tailscale admin page it opens in your browser.
Going live on YouTube goes through OBS's own YouTube connection. Tailscale, OBS, obs-ptz and YouTube have their own privacy policies.

## Code signing policy
The Windows installer (`OBS-Remote-Setup-*.exe`) is built from this repository by a [GitHub Action](.github/workflows/installer.yml) for each release.
It is to be signed through SignPath Foundation's free code signing for open-source projects; until that's in place the installer is unsigned.
- Committers and reviewers: [mdukasa](https://github.com/mdukasa). Changes from anyone else come as pull requests and are reviewed before they're merged.
- Approvers: [mdukasa](https://github.com/mdukasa) approves each signing request.

## License
[MIT](LICENSE). Bundled: Python ([PSF License](https://docs.python.org/3/license.html)) in the installer.

How it works inside: [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md). Screenshots, full-size demo pictures and the tools that make them: [obs-remote-assets](https://github.com/mdukasa/obs-remote-assets).
