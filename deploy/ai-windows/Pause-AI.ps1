#Requires -Version 5.1
#Requires -RunAsAdministrator
param([ValidateRange(1,1440)][int]$Minutes=120)
$ErrorActionPreference='Stop'
$root='C:\ProgramData\ServersStatusAI'
if(!(Test-Path "$root\settings.xml")){throw 'AI is not installed'}
$until=[DateTimeOffset]::UtcNow.AddMinutes($Minutes).ToUnixTimeSeconds()
[IO.File]::WriteAllText("$root\pause-until.txt",[string]$until)
Write-Host "Pause requested for $Minutes minutes. Model unloads within a few seconds; pending requests can fail. Run Resume-AI.ps1 after the backup."
