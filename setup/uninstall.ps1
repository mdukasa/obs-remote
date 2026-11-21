# OBS Remote - uninstaller. Run it through Uninstall.bat. Leaves the folder itself in place.
$ErrorActionPreference = 'Continue'
$root   = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root 'server.py'

Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
    Where-Object { $_.CommandLine -like "*$server*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Stopped the web server."

$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'OBS Remote.lnk'
if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Removed it from Windows startup." }

if (Get-NetFirewallRule -DisplayName 'OBS Remote*' -ErrorAction SilentlyContinue) {
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\firewall.ps1`"", '-Remove')
        Write-Host "Removed the firewall rules."
    } catch { Write-Host "Admin permission declined; firewall rules 'OBS Remote - ...' were left in place." }
}
Write-Host "`nOBS Remote is uninstalled. You can now delete this folder."
