#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param([string]$TailscalePath="$env:ProgramFiles\Tailscale\tailscale.exe",[switch]$AllowOtherComputer)
$ErrorActionPreference='Stop'
if(!$AllowOtherComputer -and $env:COMPUTERNAME -ne 'WIN-CU629F0N7II'){throw 'Run on Backup: WIN-CU629F0N7II / windows-02'}
if(!(Test-Path -LiteralPath $TailscalePath -PathType Leaf)){throw 'Install official Tailscale for Windows and sign in to the same tailnet as Raspberry Pi first.'}
$statusText=& $TailscalePath status --json
if($LASTEXITCODE){throw 'Could not read Tailscale status'}
$status=($statusText -join "`n") | ConvertFrom-Json
if($status.BackendState -ne 'Running'){throw 'Sign in to Tailscale on Backup first'}
$dns=([string]$status.Self.DNSName).TrimEnd('.')
if($dns -notmatch '^[a-zA-Z0-9][a-zA-Z0-9.-]*\.ts\.net$'){throw 'No Tailscale DNS name. Enable MagicDNS in tailnet DNS settings.'}
$endpoint=$dns+':8443'
$serveText=& $TailscalePath serve status --json
if($LASTEXITCODE){throw 'Could not inspect existing Tailscale Serve config'}
$config=($serveText -join "`n") | ConvertFrom-Json
if($config.AllowFunnel -and @($config.AllowFunnel.PSObject.Properties | Where-Object {$_.Value -eq $true}).Count){throw 'Funnel is enabled on this machine. Review it before configuring the private AI endpoint.'}
$existing=$null
if($config.TCP){$existing=$config.TCP.PSObject.Properties['8443']}
if($existing){
    $web=$null
    if($config.Web){$web=$config.Web.PSObject.Properties[$endpoint]}
    if(!$web -or !$web.Value.Handlers -or !$web.Value.Handlers.PSObject.Properties['/'] -or $web.Value.Handlers.PSObject.Properties['/'].Value.Proxy -ne 'http://127.0.0.1:8091'){
        throw 'Tailscale port 8443 is already used by another configuration; it was not changed.'
    }
}
try{$health=Invoke-RestMethod -Uri 'http://127.0.0.1:8091/health' -TimeoutSec 10}catch{throw 'Local model is unavailable/loading/paused. Check ServersStatusAI and service.log first.'}
if($health.status -ne 'ok'){throw 'Local model is not ready'}
# Persist after Windows logout. No exit node, subnet routing, public Funnel or firewall changes.
& $TailscalePath set --unattended=true
if($LASTEXITCODE){throw 'Could not enable unattended Tailscale on Windows'}
& $TailscalePath serve --bg --https=8443 http://127.0.0.1:8091
if($LASTEXITCODE){throw 'Serve was not enabled. Follow the Tailscale HTTPS approval link if displayed, then rerun this script.'}
Write-Host ''
Write-Host ('Private AI URL: https://'+$endpoint)
Write-Host 'On Raspberry Pi, test this URL with /health. Keep api-key.txt private; it is required for chat requests.'
