# OBS Remote - uninstaller. Run it through Uninstall.bat. Leaves the folder itself in place.
# setup\core.py does the work; without Python (so no server can be running) it only removes the
# startup shortcut and the firewall rules.
# Keep this file ASCII-only (Windows PowerShell 5.1).
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\python.ps1"
$py = Find-Python
if ($py) { & $py "$PSScriptRoot\core.py" uninstall; exit $LASTEXITCODE }

$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'OBS Remote.lnk'
if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Removed it from Windows startup." }
if (Get-NetFirewallRule -DisplayName 'OBS Remote*' -ErrorAction SilentlyContinue) {
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\firewall.ps1`"", '-Remove')
        Write-Host "Removed the firewall rules."
    } catch { Write-Host "Admin permission declined; firewall rules 'OBS Remote - ...' were left in place." }
}
if ((Test-Path "$env:LOCALAPPDATA\OBS Remote\tailscale-route.txt") -or (Test-Path "$PSScriptRoot\tailscale-route.txt")) {
    Write-Host "Python wasn't found, so this PC's address is still shared over Tailscale (remove it in Tailscale's admin page)."
}
Write-Host "`nOBS Remote is uninstalled. You can now delete this folder."
