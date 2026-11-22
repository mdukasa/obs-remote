# OBS Remote - installer for Windows. Run it through Install.bat.
# Safe to run again: it repairs or updates an existing install.
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
param([int]$Port = 8765, [switch]$SkipFirewall, [switch]$SkipStartup, [switch]$Tailscale, [switch]$NoTailscale)
$ErrorActionPreference = 'Stop'
$root   = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root 'server.py'
try { $Host.UI.RawUI.WindowTitle = 'OBS Remote setup' } catch {}

# ---- look ------------------------------------------------------------------------------
function Say($t = '', $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Rule { Say ('  ' + ('-' * 66)) DarkGray }
# One line per check:  [1/4] Python ................ OK  3.12
function Step($n, $label, $state, $detail) {
    $color = @{ OK = 'Green'; WARN = 'Yellow'; FAIL = 'Red'; INFO = 'Gray' }[$state]
    $tag   = @{ OK = ' OK '; WARN = 'NOTE'; FAIL = 'FAIL'; INFO = ' -- ' }[$state]
    $num   = if ($n) { "[$n/4]" } else { '     ' }
    Write-Host ("  {0} {1} " -f $num, $label.PadRight(22, '.')) -NoNewline
    Write-Host $tag -ForegroundColor $color -NoNewline
    Write-Host "  $detail"
}
function Hint($t) { Say "              $t" Yellow }

Clear-Host
Say
Say '  OBS Remote setup' Cyan
Say

# ---- 1. Python ---------------------------------------------------------------------------
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

$py = Find-Python
if (-not $py) {
    Step 1 'Python' WARN 'not installed yet'
    Hint "Python is free. OBS Remote only uses it to run its small web server."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        $a = Read-Host '              Install it now? (Y/n)'
        if ($a -notmatch '^[nN]') {
            & winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
            $py = Find-Python
        }
    }
    if (-not $py) {
        Step 1 'Python' FAIL 'still missing'
        Hint "Install Python 3 from https://www.python.org/downloads/"
        Hint "(tick 'Add python.exe to PATH'), then double-click Install.bat again."
        exit 1
    }
}
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }
Step 1 'Python' OK ((& $py -c "import sys;print('version %d.%d' % sys.version_info[:2])") 2>$null)

# ---- 2. OBS --------------------------------------------------------------------------------
# Some changes need OBS closed: it keeps its settings and plugins open and saves its own copy on exit.
# Setup asks once, remembers where OBS was, and opens it again at the end of the OBS steps.
$script:obsExe = $null
function Close-Obs($why) {
    $o = @(Get-Process obs64 -ErrorAction SilentlyContinue)
    if (-not $o.Count) { return $true }
    if (-not $script:obsExe) { try { $script:obsExe = $o[0].Path } catch {} }
    Hint "OBS is open. To $why, save your work and close OBS, then press Enter."
    if ((Read-Host '              (press Enter when OBS is closed, or type s to skip)') -match '^[sS]') { return $false }
    foreach ($i in 1..10) { if (-not @(Get-Process obs64 -ErrorAction SilentlyContinue).Count) { return $true }; Start-Sleep 1 }
    Hint 'OBS is still open, so this was skipped. Run Install.bat again later.'
    return $false
}
function Open-ObsAgain {
    if ($script:obsExe -and (Test-Path $script:obsExe) -and -not @(Get-Process obs64 -ErrorAction SilentlyContinue).Count) {
        Start-Process $script:obsExe -WorkingDirectory (Split-Path $script:obsExe)
        Hint 'Opened OBS again.'
    }
}
function Write-Utf8($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false)) }

$obsPort = 4455
$obsPw = ''   # goes into the phone QR code, so one scan opens the app AND signs in
$wsCfg = Join-Path $env:APPDATA 'obs-studio\plugin_config\obs-websocket\config.json'
$ws = if (Test-Path $wsCfg) { Get-Content $wsCfg -Raw | ConvertFrom-Json } else { $null }
if (-not ($ws -and $ws.server_enabled)) {
    Step 2 'OBS remote control' WARN $(if ($ws) { 'WebSocket server is OFF' } else { "OBS's WebSocket server isn't set up yet" })
    if ((Read-Host '              Turn it on now? (Y/n)') -notmatch '^[nN]' -and (Close-Obs 'turn it on')) {
        # obs-websocket's own settings file. Keep its port and password; make a password if there is none.
        if (-not $ws) { $ws = [pscustomobject]@{} }
        $pw = if ($ws.server_password) { [string]$ws.server_password } else {
            $b = New-Object byte[] 12; (New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($b)
            ([Convert]::ToBase64String($b) -replace '[+/=]', '').Substring(0, 12) }
        $new = [ordered]@{ alerts_enabled = [bool]$ws.alerts_enabled; auth_required = $true; first_load = $false
                           server_enabled = $true; server_password = $pw
                           server_port = $(if ($ws.server_port) { [int]$ws.server_port } else { 4455 }) }
        New-Item -ItemType Directory -Force (Split-Path $wsCfg) | Out-Null
        Write-Utf8 $wsCfg ($new | ConvertTo-Json)
        $ws = Get-Content $wsCfg -Raw | ConvertFrom-Json
        $turnedOn = $true
    }
}
if ($ws) {
    if ($ws.server_port) { $obsPort = [int]$ws.server_port }
    if ($ws.auth_required -and $ws.server_password) { $obsPw = [string]$ws.server_password }
}
if ($ws -and $ws.server_enabled) {
    Step 2 'OBS remote control' OK ("WebSocket server is on (port $obsPort)" + $(if ($turnedOn) { ', just turned on' }))
    if (-not $ws.auth_required) { Hint "It has no password, so anyone on this network could control OBS. Consider setting one." }
} else {
    Hint "Phones can't connect until it's on. In OBS: Tools > WebSocket Server Settings > Enable WebSocket server."
}

# obs-ptz: the Camera tab needs a build with websocket control (1.0 beta or newer)
function Get-Ptz {  # -> $null (not installed), or @{Dll; Version; Ok}
    $dll = @("$env:ProgramData\obs-studio\plugins\obs-ptz\bin\64bit\obs-ptz.dll",
             "$env:ProgramFiles\obs-studio\obs-plugins\64bit\obs-ptz.dll") | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $dll) { return $null }
    $txt = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($dll))
    @{ Dll = $dll; Version = (Get-Item $dll).VersionInfo.ProductVersion; Ok = $txt.Contains('ptz_list_devices') }
}
# Newest obs-ptz release with websocket control (1.0 or later; its betas are GitHub pre-releases).
function Find-PtzRelease {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
    $rels = Invoke-RestMethod 'https://api.github.com/repos/glikely/obs-ptz/releases?per_page=20' -Headers @{ 'User-Agent' = 'obs-remote-setup' } -TimeoutSec 20
    foreach ($r in $rels) {
        if ($r.draft -or $r.tag_name -notmatch '^v?(\d+)\.') { continue }
        if ([int]$Matches[1] -lt 1) { continue }
        $a = $r.assets | Where-Object { $_.name -like "*windows-$arch-Installer.exe" } | Select-Object -First 1
        if ($a) { return @{ Tag = $r.tag_name; Url = $a.browser_download_url; Name = $a.name } }
    }
    return $null
}
function Install-Ptz {
    try { $rel = Find-PtzRelease } catch { $rel = $null }
    if (-not $rel) { Hint "Couldn't reach GitHub. Get it from https://github.com/glikely/obs-ptz/releases"; return }
    # OBS keeps the plugin file open, so it has to be closed while obs-ptz is installed.
    if (-not (Close-Obs 'install obs-ptz')) { return }
    $exe = Join-Path $env:TEMP $rel.Name
    Say "              Downloading obs-ptz $($rel.Tag)..."
    try { Invoke-WebRequest $rel.Url -OutFile $exe -UseBasicParsing -TimeoutSec 300 }
    catch { Hint "The download failed. Get it from https://github.com/glikely/obs-ptz/releases"; return }
    Say '              Installing. Windows may ask for permission: click Yes.' Cyan
    try {
        # Inno Setup installer: /SILENT shows only a progress bar; it puts the plugin where OBS looks for it.
        $p = Start-Process $exe -ArgumentList '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-' -Wait -PassThru
        if ($p.ExitCode -ne 0) { Hint "obs-ptz's installer stopped (code $($p.ExitCode))." }
    } catch { Hint 'Permission was declined, so obs-ptz was not installed.' }
    Remove-Item $exe -ErrorAction SilentlyContinue
}

$ptz = Get-Ptz
if (-not $ptz) {
    Step 0 'PTZ cameras' INFO 'obs-ptz not installed (fine if you have no PTZ cameras)'
    if ((Read-Host '              Do you have PTZ cameras? Install obs-ptz for the Camera tab now? (y/N)') -match '^[yY]') { Install-Ptz; $ptz = Get-Ptz }
} elseif (-not $ptz.Ok) {
    Step 0 'PTZ cameras' WARN "obs-ptz $($ptz.Version) is too old for phone control"
    if ((Read-Host '              Update obs-ptz to the newest version now? (Y/n)') -notmatch '^[nN]') { Install-Ptz; $ptz = Get-Ptz }
} else { $ptz.Shown = $true }
# The phone needs obs-ptz's "Websocket access" set to Control; setup can't read that, so it says so once.
if ($ptz -and $ptz.Ok) { Step 0 'PTZ cameras' OK "obs-ptz $($ptz.Version)$(if (-not $ptz.Shown) { ' installed' }); set its Websocket access to Control" }
elseif ($ptz -and -not $ptz.Shown) { Hint "Install obs-ptz 1.0 (beta) or newer: https://github.com/glikely/obs-ptz/releases" }
Open-ObsAgain  # if setup had OBS closed for the WebSocket server or obs-ptz

# ---- Tailscale (optional): reach OBS Remote from phones away from this network --------------------------
# Tailscale is a free VPN: phones with its app, signed in to the same account (tailnet), reach this PC from
# anywhere. Asked once; the answer is kept in the firewall rules (re-run with -Tailscale / -NoTailscale to change).
function Get-TailscaleIP {
    $ip = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {
        $_.IPAddress -like '100.*' -and
        "$($_.InterfaceAlias) $((Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue).InterfaceDescription)" -match 'Tailscale' })
    if ($ip.Count) { $ip[0].IPAddress } else { $null }
}
function Test-TsRule {  # do the existing rules already let Tailscale in?
    $r = @(Get-NetFirewallRule -DisplayName 'OBS Remote - phone page' -ErrorAction SilentlyContinue)
    $r.Count -and ((($r[0] | Get-NetFirewallAddressFilter).RemoteAddress -join ',') -like '*100.64.0.0*')
}
$tsIP = Get-TailscaleIP
$tsExe = "$env:ProgramFiles\Tailscale\tailscale-ipn.exe"
if ($NoTailscale) { $useTs = $false }
elseif ($Tailscale -or (Test-TsRule)) { $useTs = $true }
else {
    if ($tsIP) {
        $useTs = (Read-Host '        Tailscale is on this PC. Let phones connect over it too, from anywhere? (y/N)') -match '^[yY]'
    } else {
        $useTs = (Read-Host '        Optional: set up Tailscale, for phones away from this Wi-Fi? (y/N)') -match '^[yY]'
        if ($useTs) {
            if (-not (Test-Path $tsExe) -and (Get-Command winget -ErrorAction SilentlyContinue)) {
                & winget install --id Tailscale.Tailscale -e --accept-package-agreements --accept-source-agreements
            }
            if (Test-Path $tsExe) {
                Start-Process $tsExe -ErrorAction SilentlyContinue
                Say '   Sign in to Tailscale: click its icon by the clock (or the window that opens) > Log in.' Cyan
                Write-Host '   Waiting for Tailscale (up to 3 minutes) ' -NoNewline
                foreach ($i in 1..90) { $tsIP = Get-TailscaleIP; if ($tsIP) { break }; Write-Host '.' -NoNewline; Start-Sleep 2 }
                Say
            }
        }
    }
}
if ($useTs -and -not $tsIP) {
    Step 0 'Tailscale' WARN 'not connected yet'
    Hint 'Sign in to Tailscale on this PC, then run Install.bat again.'
    $useTs = $false
} elseif ($useTs) { Step 0 'Tailscale' OK "phones on your tailnet can connect ($tsIP)" }
elseif ($tsIP) { Step 0 'Tailscale' INFO 'not used (run Install.bat -Tailscale to turn on)' }

# ---- 3. Firewall (needs admin, asks once) ----------------------------------------------------
# With Tailscale chosen, the rules also let in its 100.64.0.0/10 addresses (devices in the same tailnet).
function Test-Rule($name) {
    $r = @(Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)
    if (-not $r.Count) { return $false }
    return (((($r[0] | Get-NetFirewallAddressFilter).RemoteAddress -join ',') -like '*100.64.0.0*') -eq [bool]$useTs)
}
$need = (-not $SkipFirewall) -and (-not (Test-Rule 'OBS Remote - phone page') -or -not (Test-Rule 'OBS Remote - OBS websocket'))
if ($need) {
    Say '              Windows will ask for permission next: click Yes.' Cyan
    # Build the list first: written inline after -ArgumentList, "+ ..." would become stray extra arguments.
    $fwArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\firewall.ps1`"", '-Port', $Port, '-ObsPort', $obsPort)
    if ($useTs) { $fwArgs += '-Tailscale' }
    try {
        $p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList $fwArgs
        if ($p.ExitCode -eq 0) { Step 3 'Windows Firewall' OK ('phones on this network' + $(if ($useTs) { ' and Tailscale' }) + ' can connect') }
        else { Step 3 'Windows Firewall' WARN "couldn't add the rules (code $($p.ExitCode))"; Hint 'Phones may not be able to connect. Run Install.bat again to retry.' }
    } catch {
        # 1223 = the person clicked No on Windows' permission prompt; anything else is a real error, so show it
        if ($_.Exception.NativeErrorCode -eq 1223 -or "$($_.Exception.Message)" -match 'cancel') {
            Step 3 'Windows Firewall' WARN 'permission was declined'
            Hint 'Phones may not connect. Run Install.bat again and click Yes.'
        } else {
            Step 3 'Windows Firewall' WARN "couldn't add the rules"
            Hint "$($_.Exception.Message)"
        }
    }
} elseif ($SkipFirewall) { Step 3 'Windows Firewall' INFO 'skipped (-SkipFirewall)' }
else { Step 3 'Windows Firewall' OK ('phones on this network' + $(if ($useTs) { ' and Tailscale' }) + ' can connect') }

# ---- 4. Start now + at every sign-in ------------------------------------------------------------
Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$server*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
# Another OBS Remote (e.g. an older copy in a different folder) on the same port would stop this one starting.
foreach ($c in @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $($c.OwningProcess)" -ErrorAction SilentlyContinue
    if ($proc -and $proc.Name -like 'python*' -and $proc.CommandLine -like '*server.py*') {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        Hint "Stopped another OBS Remote that was using port $Port."
        Start-Sleep -Milliseconds 500
    }
}
$srvProc = Start-Process -FilePath $pyw -ArgumentList "`"$server`"", $Port -WorkingDirectory $root -WindowStyle Hidden -PassThru

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
}
# Ask the page directly, never through a proxy (a system proxy can swallow requests even to 127.0.0.1).
function Test-Page {
    try {
        $rq = [Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/"); $rq.Proxy = $null; $rq.Timeout = 3000
        $rs = $rq.GetResponse(); $ok = [int]$rs.StatusCode -eq 200; $rs.Close()
        $script:pageErr = $null; return $ok
    } catch { $script:pageErr = $_.Exception.InnerException.Message; if (-not $script:pageErr) { $script:pageErr = $_.Exception.Message }; return $false }
}
$running = $false
foreach ($i in 1..20) {
    Start-Sleep -Milliseconds 500
    $running = Test-Page
    if ($running -or $srvProc.HasExited) { break }
}
if (-not $running) {
    Step 4 'OBS Remote server' FAIL "didn't start"
    $owner = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) | Select-Object -First 1 |
        ForEach-Object { Get-CimInstance Win32_Process -Filter "ProcessId = $($_.OwningProcess)" -ErrorAction SilentlyContinue }
    if ($owner -and $owner.ProcessId -eq $srvProc.Id) {
        # it's running and holds the port, but doesn't answer
        Hint "It's running but didn't answer on http://127.0.0.1:$Port/ ($script:pageErr)."
        Hint 'Security software may be blocking it. Try opening that address in a browser on this PC.'
    } elseif ($owner) {
        Hint "Port $Port is taken by $($owner.Name) ($($owner.ExecutablePath))."
        Hint "Close that program, or run Install.bat -Port 8766."
    } else {
        # it stopped by itself: pythonw has nowhere to print, so run it once more with python and show what it says
        $log = Join-Path $env:TEMP 'obs-remote-start.txt'
        $t = Start-Process $py -ArgumentList "`"$server`"", $Port -WorkingDirectory $root -WindowStyle Hidden -PassThru `
            -RedirectStandardError $log -RedirectStandardOutput "$log.out"
        if (-not $t.WaitForExit(15000)) { Stop-Process -Id $t.Id -Force -ErrorAction SilentlyContinue }
        $why = @(Get-Content $log -ErrorAction SilentlyContinue | Where-Object { $_.Trim() }) | Select-Object -Last 3
        if ($why) { $why | ForEach-Object { Hint $_ } } else { Hint "To see why, run:  `"$py`" `"$server`"" }
    }
    exit 1
}
$ver = (Get-Content (Join-Path $root 'VERSION') -ErrorAction SilentlyContinue | Select-Object -First 1)
Step 4 'OBS Remote server' OK ("running" + $(if ($ver) { " (version $ver)" }) + $(if (-not $SkipStartup) { ', starts with Windows' }))

# ---- 5. Where phones can reach it ----------------------------------------------------------------
# This PC's local-network IPv4 addresses, best route first. Virtual adapters (Hyper-V, WSL, VirtualBox,
# VMware...) and VPNs (Tailscale, ZeroTier, WireGuard...) are left out: they aren't the phone's Wi-Fi.
$lan = @(@(foreach ($ip in Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue) {
    if ($ip.IPAddress -match '^(127\.|169\.254\.)' -or $ip.PrefixOrigin -eq 'WellKnown') { continue }
    $ad = Get-NetAdapter -InterfaceIndex $ip.InterfaceIndex -ErrorAction SilentlyContinue
    if ($ad -and $ad.Status -ne 'Up') { continue }
    if ("$($ip.InterfaceAlias) $($ad.InterfaceDescription)" -match
        'vEthernet|Hyper-V|VirtualBox|VMware|WSL|Loopback|Bluetooth|Npcap|Docker|Tailscale|WiFiman|ZeroTier|Hamachi|WireGuard|OpenVPN|TAP-Windows|Wintun|NordLynx|ProtonVPN|Fortinet|AnyConnect|GlobalProtect') { continue }
    $metric = (Get-NetIPInterface -InterfaceIndex $ip.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).InterfaceMetric
    [pscustomobject]@{ Alias = $ip.InterfaceAlias; IP = $ip.IPAddress; Metric = [int]$metric; Dhcp = $ip.PrefixOrigin -eq 'Dhcp' }
}) | Sort-Object Metric)
$url = { param($h) "http://${h}:$Port/" }
# The login rides in the #fragment, which browsers never send to the server. The page saves it and removes it
# from the address bar (www/index.html, "sign-in link"). Re-run Install.bat after changing OBS's password.
$login = @()
if ($obsPw) { $login += 'pw=' + [uri]::EscapeDataString($obsPw) }
if ($obsPort -ne 4455) { $login += "port=$obsPort" }
$signIn = { param($h) (& $url $h) + $(if ($login.Count) { '#' + ($login -join '&') } else { '' }) }

# ---- Tailscale route: the local address works over Tailscale too -----------------------------------
# The PC advertises its own LAN address to the tailnet as a subnet route (a /32: just this PC, nothing else on the
# network). A phone with Tailscale on then reaches the SAME http://LAN-IP:port/ from anywhere, so everyone uses one
# QR code, one home-screen icon and one saved login, and Tailscale can be added to a phone later without redoing it.
# Tailscale needs the route approved once in its admin console (automatic if the tailnet policy has autoApprovers);
# setup opens that page and carries on by itself as soon as it's approved.
$tsCli = "$env:ProgramFiles\Tailscale\tailscale.exe"
$routeMark = Join-Path $PSScriptRoot 'tailscale-route.txt'   # the route setup added, so a new IP replaces it
function Get-TsJson($what) { try { ((& $tsCli @what 2>$null) -join "`n") | ConvertFrom-Json } catch { $null } }
function Test-TsApproved($route) {
    $s = Get-TsJson @('status', '--json')
    $s -and ((@($s.Self.PrimaryRoutes) -contains $route) -or (@($s.Self.AllowedIPs) -contains $route))
}
$oldRoute = if (Test-Path $routeMark) { "$(Get-Content $routeMark -TotalCount 1)".Trim() } else { '' }
$tsRoute = $null; $routeOk = $false
if ((Test-Path $tsCli) -and $lan.Count -and ($useTs -or $oldRoute)) {
    $want = if ($useTs) { "$($lan[0].IP)/32" } else { '' }
    $prefs = Get-TsJson @('debug', 'prefs')
    if ($prefs) {
        # "tailscale set --advertise-routes" replaces the whole list, so keep any routes someone else added
        $cur = @($prefs.AdvertiseRoutes | Where-Object { $_ })
        $new = @($cur | Where-Object { $_ -ne $oldRoute -and $_ -ne $want }) + @($want | Where-Object { $_ })
        $same = (@($cur | Sort-Object) -join ',') -eq (@($new | Sort-Object) -join ',')
        if (-not $same) { & $tsCli set "--advertise-routes=$($new -join ',')" 2>&1 | Out-Null }
        if ($same -or $LASTEXITCODE -eq 0) {
            if ($want) { Set-Content $routeMark $want -Encoding ASCII; $tsRoute = $want }
            elseif (Test-Path $routeMark) { Remove-Item $routeMark; Step 0 'Tailscale route' INFO "removed ($oldRoute)" }
        } else {
            Step 0 'Tailscale route' WARN "Tailscale didn't accept the change"
            Hint 'Run Install.bat as the Windows user who signed in to Tailscale on this PC.'
        }
    } else { Step 0 'Tailscale route' WARN "couldn't read Tailscale's settings"; Hint 'Is Tailscale running? Then run Install.bat again.' }
}
if ($tsRoute) {
    $routeOk = Test-TsApproved $tsRoute
    if ($routeOk) { Step 0 'Tailscale route' OK "the same address works over Tailscale ($tsRoute)" }
    else {
        $tsName = (Get-TsJson @('status', '--json')).Self.DNSName -replace '\..*$', ''
        if (-not $tsName) { $tsName = $env:COMPUTERNAME.ToLower() }
        Step 0 'Tailscale route' WARN 'needs approving once in Tailscale'
        Hint "So the same code works over Tailscale, approve this PC's route. In the page that opens:"
        Hint "sign in if asked, then on '$tsName': Machine settings > Edit route settings > tick $tsRoute > Save."
        Start-Process "https://login.tailscale.com/admin/machines/$tsIP" -ErrorAction SilentlyContinue
        Write-Host '              Waiting for it (up to 5 minutes, press Enter to skip) ' -NoNewline
        $until = (Get-Date).AddMinutes(5)
        while ((Get-Date) -lt $until) {
            if (Test-TsApproved $tsRoute) { $routeOk = $true; break }
            try { if ([Console]::KeyAvailable -and [Console]::ReadKey($true).Key -eq 'Enter') { break } } catch {}
            Write-Host '.' -NoNewline; Start-Sleep 2
        }
        Say
        if ($routeOk) { Step 0 'Tailscale route' OK 'approved: the same address works over Tailscale' }
        else {
            Step 0 'Tailscale route' WARN 'not approved yet'
            Hint 'Until it is, phones away from here need the separate Tailscale code. Run Install.bat again to check.'
        }
    }
}

# QR code in the console: qr.py gives rows of 0/1, two rows per text line using half blocks,
# black on white so every phone camera reads it.
function Show-QR($text) {
    $rows = @(& $py "$PSScriptRoot\qr.py" --rows $text 2>$null)
    if ($LASTEXITCODE -ne 0 -or $rows.Count -lt 10) { return }
    $up = [char]0x2580; $dn = [char]0x2584; $full = [char]0x2588
    for ($i = 0; $i -lt $rows.Count; $i += 2) {
        $a = $rows[$i]; $b = if ($i + 1 -lt $rows.Count) { $rows[$i + 1] } else { '0' * $a.Length }
        $sb = New-Object System.Text.StringBuilder
        for ($k = 0; $k -lt $a.Length; $k++) {
            $t = $a[$k] -eq '1'; $u = $b[$k] -eq '1'
            [void]$sb.Append($(if ($t -and $u) { $full } elseif ($t) { $up } elseif ($u) { $dn } else { ' ' }))
        }
        Write-Host '      ' -NoNewline
        Write-Host $sb.ToString() -ForegroundColor Black -BackgroundColor White
    }
}

$page = @()   # label|url pairs for Phone address.html
Say
Say '  ALL DONE!' Green
if ($lan.Count -eq 0) {
    Say '   This PC has no local network connection right now, so phones can''t reach it yet.' Yellow
    Say '   Connect it to the network, then run Install.bat again.' Yellow
} else {
    $main = & $url $lan[0].IP
    Say "  On each phone, on the same Wi-Fi as this PC, scan this code. It opens OBS Remote signed in:"
    Say
    Show-QR (& $signIn $lan[0].IP)
    Say "        $main" White
    foreach ($n in $lan | Select-Object -Skip 1) { Say "        also: $(& $url $n.IP)   ($($n.Alias))" DarkGray }
    Say "  Then add it to the home screen. iPhone: Share > Add to Home Screen. Android: menu > Add to Home screen." DarkGray
    foreach ($n in $lan) { $page += "On this network ($($n.Alias))|$(& $url $n.IP)|$(& $signIn $n.IP)" }
    if ($routeOk) {
        Say "  Phones with Tailscale on can use this same code and icon from anywhere." Cyan
        if ($lan[0].Dhcp) { Say "  Give this PC a fixed IP address in your router ($($lan[0].IP)): the code and the Tailscale route both use it." Yellow }
    } elseif ($useTs) {
        # Route not approved yet: a second code, for the PC's Tailscale address.
        # "?" = folded away on the page until asked for: it only works on phones signed in to the same tailnet
        $page += "?Over Tailscale|$(& $url $tsIP)|$(& $signIn $tsIP)"
        Say
        if ((Read-Host '  Show the Tailscale code too, for phones away from this Wi-Fi? (y/N)') -match '^[yY]') {
            Say '  Over Tailscale (the phone needs the Tailscale app, signed in to the same account):'
            Show-QR (& $signIn $tsIP)
            Say "        $(& $url $tsIP)" White
        }
    }
}

# Save the addresses: a text file, and a page with big QR codes to open any time.
$page | ForEach-Object { $_.Split('|')[1] } | Set-Content (Join-Path $root 'Phone address.txt') -Encoding UTF8
if ($page.Count) { & $py "$PSScriptRoot\qr.py" --html (Join-Path $root 'Phone address.html') @page 2>$null }

Say
Say ("  'Phone address.html' shows the code" + $(if ($useTs -and -not $routeOk) { 's' }) + " again." +
     $(if ($obsPw) { ' It contains the OBS password: only show it to people who may control OBS.' }))
if (-not ($routeOk -and $lan[0].Dhcp)) { Say '  Tip: give this PC a fixed IP address in your router, so the code never changes.' DarkGray }
exit 0
