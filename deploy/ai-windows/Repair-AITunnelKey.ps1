#Requires -Version 5.1
#Requires -RunAsAdministrator
$ErrorActionPreference='Stop'
if($env:COMPUTERNAME -ne 'WIN-CU629F0N7II'){throw 'Run on Backup / WIN-CU629F0N7II'}
. (Join-Path $PSScriptRoot 'SSHKey-Helpers.ps1')
$task=Get-ScheduledTask -TaskName ServersStatusAI-Tunnel -ErrorAction SilentlyContinue
if($task){Stop-ScheduledTask -TaskName ServersStatusAI-Tunnel}
Protect-AITunnelKey -Path 'C:\ProgramData\ServersStatusAI\tunnel\id_ed25519'
if($task){Start-ScheduledTask -TaskName ServersStatusAI-Tunnel}
Write-Host 'Private-key owner and ACL repaired for SYSTEM. Existing key bytes and Raspi authorization are unchanged.'
