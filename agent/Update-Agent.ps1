# Elevated PowerShell. Configuration and backup settings are preserved.
$ErrorActionPreference='Stop'
$newExe=Join-Path $PSScriptRoot 'ServersStatusService.exe'
$helper=Join-Path $PSScriptRoot 'apply_update.ps1'
if (-not (Test-Path $newExe) -or -not (Test-Path $helper)) {throw 'Extract the complete new Windows artifact, including apply_update.ps1.'}
$hash=(Get-FileHash -LiteralPath $newExe -Algorithm SHA256).Hash
& $helper -Package $newExe -Sha256 $hash
Write-Host 'Agent updated. Check its version in the panel. See update.log for details.'
