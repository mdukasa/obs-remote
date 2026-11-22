# Adds (or with -Remove, deletes) the inbound firewall rules OBS Remote needs.
# Runs elevated; install.ps1 / uninstall.ps1 call it. Rules only accept the local network, plus Tailscale's
# 100.64.0.0/10 with -Tailscale (only devices in your tailnet can reach those addresses).
param([int]$Port = 8765, [int]$ObsPort = 4455, [switch]$Remove, [switch]$Tailscale)
$ErrorActionPreference = 'Stop'
$from = @('LocalSubnet') + $(if ($Tailscale) { '100.64.0.0/10' } else { @() })
$rules = @{ 'OBS Remote - phone page' = $Port; 'OBS Remote - OBS websocket' = $ObsPort }
foreach ($name in $rules.Keys) {
    Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    if (-not $Remove) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP `
            -LocalPort $rules[$name] -RemoteAddress $from -Profile Any | Out-Null
    }
}
exit 0
