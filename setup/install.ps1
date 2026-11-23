# OBS Remote - installer for Windows. Run it through Install.bat. Safe to run again: it repairs or updates.
# This part only finds Python (or offers to install it), then opens the setup window (setup\panel.py).
# With -Console, or any of the other switches, setup runs in this console instead (setup\core.py install).
# Keep this file ASCII-only: Windows PowerShell 5.1 reads BOM-less scripts in the ANSI code page.
param([int]$Port = 0, [switch]$SkipFirewall, [switch]$SkipStartup, [switch]$Tailscale, [switch]$NoTailscale, [switch]$Console)
$ErrorActionPreference = 'Stop'
try { $Host.UI.RawUI.WindowTitle = 'OBS Remote setup' } catch {}
. "$PSScriptRoot\python.ps1"

$py = Find-Python
if (-not $py) {
    Write-Host
    Write-Host '  OBS Remote setup' -ForegroundColor Cyan
    Write-Host
    Write-Host '  [1/4] Python ................ ' -NoNewline; Write-Host 'NOTE' -ForegroundColor Yellow -NoNewline; Write-Host '  not installed yet'
    Write-Host '              Python is free. OBS Remote only uses it to run its small web server.' -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        if ((Read-Host '              Install it now? (Y/n)') -notmatch '^[nN]') {
            & winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
            $py = Find-Python
        }
    }
    if (-not $py) {
        Write-Host '  [1/4] Python ................ ' -NoNewline; Write-Host 'FAIL' -ForegroundColor Red -NoNewline; Write-Host '  still missing'
        Write-Host '              Install Python 3 from https://www.python.org/downloads/' -ForegroundColor Yellow
        Write-Host "              (tick 'Add python.exe to PATH'), then double-click Install.bat again." -ForegroundColor Yellow
        exit 1
    }
}

if (-not ($Console -or $Port -or $SkipFirewall -or $SkipStartup -or $Tailscale -or $NoTailscale)) {
    $pyw = Join-Path (Split-Path $py) 'pythonw.exe'
    if (-not (Test-Path $pyw)) { $pyw = $py }
    Start-Process -FilePath $pyw -ArgumentList "`"$PSScriptRoot\core.py`"", 'panel'
    Write-Host '  OBS Remote setup is opening in its own window.' -ForegroundColor Cyan
    Write-Host '  Later, open it from the Start menu: OBS Remote.' -ForegroundColor DarkGray
    exit 10  # Install.bat closes this console without waiting
}

$a = @("$PSScriptRoot\core.py", 'install')
if ($Port)         { $a += '--port', $Port }  # else the port setup chose before
if ($SkipFirewall) { $a += '--skip-firewall' }
if ($SkipStartup)  { $a += '--skip-startup' }
if ($Tailscale)    { $a += '--tailscale' }
if ($NoTailscale)  { $a += '--no-tailscale' }
& $py @a
exit $LASTEXITCODE
