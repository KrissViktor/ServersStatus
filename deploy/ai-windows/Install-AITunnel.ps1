#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
 [ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9.-]*$')][string]$ServerHost='panel.vikserver.ru',
 [ValidateRange(1,65535)][int]$ServerPort=2222,
 [Parameter(Mandatory=$true)][ValidatePattern('^ssh-ed25519 [A-Za-z0-9+/]+={0,2}$')][string]$HostKey
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'SSHKey-Helpers.ps1')
if($env:COMPUTERNAME -ne 'WIN-CU629F0N7II'){throw 'Run on Backup / WIN-CU629F0N7II'}
$root='C:\ProgramData\ServersStatusAI\tunnel'
if(!(Test-Path "$root\id_ed25519")){throw 'Run New-AITunnelKey.ps1 and authorize its public key on Raspberry Pi first'}
if(!(Test-Path "$env:WINDIR\System32\OpenSSH\ssh.exe")){throw 'OpenSSH Client not installed'}
Protect-AITunnelKey -Path "$root\id_ed25519"
# Host key must be copied from the trusted Raspi console, not accepted blindly from the network.
[IO.File]::WriteAllText("$root\known_hosts",('['+$ServerHost+']:'+$ServerPort+' '+$HostKey+"`n"),(New-Object Text.UTF8Encoding($false)))
& "$env:WINDIR\System32\OpenSSH\ssh-keygen.exe" -lf "$root\known_hosts"
if($LASTEXITCODE){throw 'Invalid pinned host key'}
@{Host=$ServerHost;Port=$ServerPort} | ConvertTo-Json | Set-Content "$root\connection.json" -Encoding UTF8
Copy-Item "$PSScriptRoot\Run-AITunnel.ps1" "$root\Run-AITunnel.ps1" -Force
$taskName='ServersStatusAI-Tunnel'
$old=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if($old -and @($old.Actions | Where-Object {$_.Arguments -notlike '*\ServersStatusAI\tunnel\Run-AITunnel.ps1*'}).Count){throw 'Existing task does not belong to this installer'}
if($old){Stop-ScheduledTask -TaskName $taskName}
$action=New-ScheduledTaskAction -Execute "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -File "'+$root+'\Run-AITunnel.ps1"')
$trigger=New-ScheduledTaskTrigger -AtStartup
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host 'Tunnel task started. On Raspberry Pi: curl --fail http://127.0.0.1:18091/health'
Write-Host 'If not available, inspect C:\ProgramData\ServersStatusAI\tunnel\tunnel.log. No public model port was opened.'
