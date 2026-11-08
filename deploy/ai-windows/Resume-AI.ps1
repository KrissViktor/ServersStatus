#Requires -Version 5.1
#Requires -RunAsAdministrator
$ErrorActionPreference='Stop'
Remove-Item 'C:\ProgramData\ServersStatusAI\pause-until.txt' -ErrorAction SilentlyContinue
Write-Host 'Resume requested. The model starts when enough RAM is available.'
