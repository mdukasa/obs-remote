# OBS Remote - installer for Windows. Run it through Install.bat.
# Safe to run again: it repairs or updates an existing install.
param([int]$Port = 8765, [switch]$SkipFirewall, [switch]$SkipStartup)
$ErrorActionPreference = 'Stop'
$root   = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root 'server.py'

function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Ok($t)   { Say "  [OK]   $t" Green }
function Warn($t) { Say "  [!]    $t" Yellow }
function Fail($t) { Say "  [X]    $t" Red }

Say "`nOBS Remote setup`n================`n" Cyan

# 1. Python ------------------------------------------------------------------
function Find-Python {
    $cands = @()
    foreach ($cmd in 'py', 'python') {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c -and $c.Source -notmatch 'WindowsApps') {
            try {
                $args2 = @(); if ($cmd -eq 'py') { $args2 = @('-3') }
                $exe = & $c.Source @args2 -c "import sys;print(sys.executable)" 2>$null
                if ($LASTEXITCODE -eq 0 -and $exe) { $cands += $exe.Trim() }
            } catch {}
        }
    }
    $cands += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe", "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object FullName
    foreach ($p in $cands) {
        if (Test-Path $p) {
            $v = & $p -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($v -and [version]$v -ge [version]'3.8') { return $p }
        }
    }
    return $null
}

Say "Checking for Python..."
$py = Find-Python
if (-not $py) {
    Warn "Python 3 is not installed. It's free and only needed to run the small web server."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        $a = Read-Host "  Install Python 3.12 now with winget? (Y/n)"
        if ($a -notmatch '^[nN]') {
            & winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
            $py = Find-Python
        }
    }
    if (-not $py) {
        Fail "Install Python 3 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run Install.bat again."
        exit 1
    }
}
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
Ok "Python: $py"

# 2. OBS websocket -----------------------------------------------------------
Say "`nChecking OBS..."
$obsPort = 4455
$wsCfg = Join-Path $env:APPDATA 'obs-studio\plugin_config\obs-websocket\config.json'
if (Test-Path $wsCfg) {
    $ws = Get-Content $wsCfg -Raw | ConvertFrom-Json
    if ($ws.server_port) { $obsPort = [int]$ws.server_port }
    if ($ws.server_enabled) { Ok "OBS WebSocket server is enabled (port $obsPort)." }
    else { Warn "OBS WebSocket server is OFF. In OBS: Tools > WebSocket Server Settings > tick 'Enable WebSocket server'." }
    if ($ws.server_enabled -and -not $ws.auth_required) { Warn "OBS WebSocket has no password. Anyone on the network could control OBS; consider setting one." }
} else {
    Warn "Couldn't find OBS WebSocket settings. Open OBS once, then Tools > WebSocket Server Settings > 'Enable WebSocket server'."
}

# obs-ptz: the Camera tab needs a build with websocket control (1.0 beta or newer)
$ptzDll = @("$env:ProgramData\obs-studio\plugins\obs-ptz\bin\64bit\obs-ptz.dll",
            "$env:ProgramFiles\obs-studio\obs-plugins\64bit\obs-ptz.dll") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ptzDll) {
    Say "  [i]    obs-ptz plugin not found. That's fine if you have no PTZ cameras: the Camera tab will just be empty." Gray
} else {
    $bytes = [IO.File]::ReadAllBytes($ptzDll)
    $txt = [Text.Encoding]::ASCII.GetString($bytes)
    $ver = (Get-Item $ptzDll).VersionInfo.ProductVersion
    if ($txt.Contains('ptz_list_devices')) { Ok "obs-ptz $ver has websocket control. In OBS: PTZ Controls dock > Settings > Websocket access = 'Control'." }
    else { Warn "obs-ptz $ver has NO websocket control, so the Camera tab won't work. Install obs-ptz 1.0 (beta) or newer: https://github.com/glikely/obs-ptz/releases" }
}

# 3. Firewall (needs admin, asks once) ------------------------------------------
Say "`nChecking Windows Firewall..."
function Test-Rule($name) { [bool](Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) }
$need = (-not $SkipFirewall) -and (-not (Test-Rule 'OBS Remote - phone page') -or -not (Test-Rule 'OBS Remote - OBS websocket'))
if ($need) {
    Say "  Windows will ask for permission to let phones on this network reach OBS Remote and OBS."
    try {
        $p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\firewall.ps1`"", '-Port', $Port, '-ObsPort', $obsPort)
        if ($p.ExitCode -eq 0) { Ok "Firewall opened for ports $Port and $obsPort (local network only)." }
        else { Warn "The firewall step failed (code $($p.ExitCode)). Phones may not be able to connect." }
    } catch {
        Warn "Admin permission was declined. Phones may not be able to connect until the firewall allows ports $Port and $obsPort."
    }
} elseif ($SkipFirewall) { Say '  [i]    Skipped (-SkipFirewall).' } else { Ok "Firewall rules already in place." }

# 4. Start now + at every login ------------------------------------------------
Say "`nStarting OBS Remote..."
Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$server*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Process -FilePath $pyw -ArgumentList "`"$server`"", $Port -WorkingDirectory $root -WindowStyle Hidden

if (-not $SkipStartup) {
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'OBS Remote.lnk'
$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = "`"$server`" $Port"
$s.WorkingDirectory = $root
$s.WindowStyle = 7
$s.Description = 'OBS Remote web server for phones'
$s.Save()
Ok "Starts automatically when you sign in to Windows."
}

Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
    if ($r.StatusCode -eq 200) { Ok "Web server is running." }
} catch { Fail "The web server didn't start. Try running:  `"$py`" `"$server`"  to see the error." ; exit 1 }

# 5. Tell the user where to go -------------------------------------------------
$ips = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' -and $_.InterfaceAlias -notmatch 'vEthernet|Loopback|VirtualBox|VMware|WSL|Tailscale|ZeroTier' } |
    Sort-Object InterfaceMetric | Select-Object -ExpandProperty IPAddress
$urls = @($ips | ForEach-Object { "http://${_}:$Port/" })
$urls | Set-Content (Join-Path $root 'Phone address.txt') -Encoding UTF8

Say "`nDone! On a phone connected to the same Wi-Fi, open:" Cyan
foreach ($u in $urls) { Say "    $u" White }
Say @"

Then:
  - Enter the OBS WebSocket password (OBS > Tools > WebSocket Server Settings > Show Connect Info).
  - Add it to your home screen (iPhone: Share > Add to Home Screen; Android: menu > Add to Home screen).
  - Tip: give this PC a fixed IP address in your router so the link never changes.
The address is also saved in 'Phone address.txt' next to Install.bat.
"@
exit 0
