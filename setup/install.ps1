# OBS Remote - installer for Windows. Run it through Install.bat.
# Safe to run again: it repairs or updates an existing install.
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
param([int]$Port = 8765, [switch]$SkipFirewall, [switch]$SkipStartup)
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
Say '  ================' Cyan
Say '  Sets up the phone remote for OBS on this PC. It takes about a minute.'
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
$obsPort = 4455
$wsCfg = Join-Path $env:APPDATA 'obs-studio\plugin_config\obs-websocket\config.json'
if (Test-Path $wsCfg) {
    $ws = Get-Content $wsCfg -Raw | ConvertFrom-Json
    if ($ws.server_port) { $obsPort = [int]$ws.server_port }
    if ($ws.server_enabled) {
        Step 2 'OBS remote control' OK "WebSocket server is on (port $obsPort)"
        if (-not $ws.auth_required) { Hint "It has no password, so anyone on this network could control OBS. Consider setting one." }
    } else {
        Step 2 'OBS remote control' WARN 'WebSocket server is OFF'
        Hint "In OBS: Tools > WebSocket Server Settings > tick 'Enable WebSocket server'."
    }
} else {
    Step 2 'OBS remote control' WARN "couldn't find OBS's settings"
    Hint "Open OBS once, then Tools > WebSocket Server Settings > tick 'Enable WebSocket server'."
}

# obs-ptz: the Camera tab needs a build with websocket control (1.0 beta or newer)
$ptzDll = @("$env:ProgramData\obs-studio\plugins\obs-ptz\bin\64bit\obs-ptz.dll",
            "$env:ProgramFiles\obs-studio\obs-plugins\64bit\obs-ptz.dll") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ptzDll) {
    Step 0 'PTZ cameras' INFO 'obs-ptz not installed (fine if you have no PTZ cameras)'
} else {
    $txt = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($ptzDll))
    $ver = (Get-Item $ptzDll).VersionInfo.ProductVersion
    if ($txt.Contains('ptz_list_devices')) {
        Step 0 'PTZ cameras' OK "obs-ptz $ver"
        Hint "In OBS: PTZ Controls dock > Settings > Websocket access = 'Control'."
    } else {
        Step 0 'PTZ cameras' WARN "obs-ptz $ver is too old for phone control"
        Hint "Install obs-ptz 1.0 (beta) or newer: https://github.com/glikely/obs-ptz/releases"
    }
}

# ---- 3. Firewall (needs admin, asks once) ----------------------------------------------------
function Test-Rule($name) { [bool](Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue) }
$need = (-not $SkipFirewall) -and (-not (Test-Rule 'OBS Remote - phone page') -or -not (Test-Rule 'OBS Remote - OBS websocket'))
if ($need) {
    Say '              Windows will now ask for permission to let phones on this network connect. Click Yes.' Cyan
    try {
        $p = Start-Process powershell -Verb RunAs -Wait -PassThru -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\firewall.ps1`"", '-Port', $Port, '-ObsPort', $obsPort)
        if ($p.ExitCode -eq 0) { Step 3 'Windows Firewall' OK 'phones on this network can connect' }
        else { Step 3 'Windows Firewall' WARN "couldn't add the rules (code $($p.ExitCode))"; Hint 'Phones may not be able to connect. Run Install.bat again to retry.' }
    } catch {
        Step 3 'Windows Firewall' WARN 'permission was declined'
        Hint "Phones may not connect until ports $Port and $obsPort are allowed. Run Install.bat again and click Yes."
    }
} elseif ($SkipFirewall) { Step 3 'Windows Firewall' INFO 'skipped (-SkipFirewall)' }
else { Step 3 'Windows Firewall' OK 'phones on this network can connect' }

# ---- 4. Start now + at every sign-in ------------------------------------------------------------
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
}
$running = $false
foreach ($i in 1..10) {
    Start-Sleep -Milliseconds 500
    try { $running = (Invoke-WebRequest "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch {}
    if ($running) { break }
}
if (-not $running) {
    Step 4 'OBS Remote server' FAIL "didn't start"
    Hint "To see why, run:  `"$py`" `"$server`""
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
    [pscustomobject]@{ Alias = $ip.InterfaceAlias; IP = $ip.IPAddress; Metric = [int]$metric }
}) | Sort-Object Metric)
$url = { param($h) "http://${h}:$Port/" }

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
Rule
Say '   ALL DONE!  Now on each phone:' Green
Rule
if ($lan.Count -eq 0) {
    Say '   This PC has no local network connection right now, so phones can''t reach it yet.' Yellow
    Say '   Connect it to the network, then run Install.bat again.' Yellow
} else {
    $main = & $url $lan[0].IP
    Say "   1. Connect the phone to the same Wi-Fi network as this PC."
    Say "   2. Point the phone's camera at this code and tap the link:"
    Say
    Show-QR $main
    Say
    Say "        $main" White
    foreach ($n in $lan | Select-Object -Skip 1) { Say "        also: $(& $url $n.IP)   ($($n.Alias))" DarkGray }
    Say
    Say "   3. Enter the OBS WebSocket password."
    Say "      It's in OBS: Tools > WebSocket Server Settings > Show Connect Info." DarkGray
    Say "   4. Add it to the home screen, so it opens like an app."
    Say "      iPhone: Share > Add to Home Screen.   Android: menu > Add to Home screen." DarkGray
    foreach ($n in $lan) { $page += "On this network ($($n.Alias))|$(& $url $n.IP)" }
}

# Save the addresses: a text file, and a page with big QR codes to open any time.
$page | ForEach-Object { $_.Split('|')[1] } | Set-Content (Join-Path $root 'Phone address.txt') -Encoding UTF8
if ($page.Count) { & $py "$PSScriptRoot\qr.py" --html (Join-Path $root 'Phone address.html') @page 2>$null }

Say
Rule
Say "   To see this code again, open 'Phone address.html' next to Install.bat."
Say "   Tip: give this PC a fixed IP address in your router, so the code never changes." DarkGray
Say
exit 0
