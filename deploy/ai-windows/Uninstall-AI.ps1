#Requires -Version 5.1
#Requires -RunAsAdministrator
$ErrorActionPreference='Stop'
$service=Get-Service ServersStatusAI -ErrorAction SilentlyContinue
if($service){Stop-Service ServersStatusAI -ErrorAction Stop; & sc.exe delete ServersStatusAI; if($LASTEXITCODE){throw 'Service removal failed'}}
Write-Host 'Service removed. Model, settings, key and logs are preserved in C:\ProgramData\ServersStatusAI.'
