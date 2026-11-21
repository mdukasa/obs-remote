# Adds (or with -Remove, deletes) the inbound firewall rules OBS Remote needs.
# Runs elevated; install.ps1 / uninstall.ps1 call it. Rules only accept the local network.
param([int]$Port = 8765, [int]$ObsPort = 4455, [switch]$Remove)
$ErrorActionPreference = 'Stop'
$rules = @{ 'OBS Remote - phone page' = $Port; 'OBS Remote - OBS websocket' = $ObsPort }
foreach ($name in $rules.Keys) {
    Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if (-not $Remove) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP `
            -LocalPort $rules[$name] -RemoteAddress LocalSubnet -Profile Any | Out-Null
    }
}
exit 0
