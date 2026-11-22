# OBS Remote - uninstaller. Run it through Uninstall.bat. Leaves the folder itself in place.
$ErrorActionPreference = 'Continue'
$root   = Split-Path -Parent $PSScriptRoot
$server = Join-Path $root 'server.py'

Get-CimInstance Win32_Process -Filter "Name like 'python%.exe'" |
    Where-Object { $_.CommandLine -like "*$server*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "Stopped the web server."

$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'OBS Remote.lnk'
if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Removed it from Windows startup." }

# The Tailscale route setup added (this PC's LAN address); other advertised routes are kept.
$routeMark = Join-Path $PSScriptRoot 'tailscale-route.txt'
$tsCli = "$env:ProgramFiles\Tailscale\tailscale.exe"
if ((Test-Path $routeMark) -and (Test-Path $tsCli)) {
    $route = "$(Get-Content $routeMark -TotalCount 1)".Trim()
    try {
        $prefs = ((& $tsCli debug prefs 2>$null) -join "`n") | ConvertFrom-Json
        $keep = @($prefs.AdvertiseRoutes | Where-Object { $_ -and $_ -ne $route })
        & $tsCli set "--advertise-routes=$($keep -join ',')" 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Remove-Item $routeMark; Write-Host "Stopped sharing $route over Tailscale." }
        else { Write-Host "Couldn't remove the Tailscale route $route. Run Uninstall.bat as the user signed in to Tailscale." }
    } catch { Write-Host "Couldn't read Tailscale's settings; the route $route may still be shared." }
}

if (Get-NetFirewallRule -DisplayName 'OBS Remote*' -ErrorAction SilentlyContinue) {
    try {
        Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\firewall.ps1`"", '-Remove')
        Write-Host "Removed the firewall rules."
    } catch { Write-Host "Admin permission declined; firewall rules 'OBS Remote - ...' were left in place." }
}
Write-Host "`nOBS Remote is uninstalled. You can now delete this folder."
