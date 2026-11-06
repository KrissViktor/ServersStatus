# Elevated PowerShell. Updates only the binary; preserves configuration and backup rules.
$ErrorActionPreference = 'Stop'
$exe = Join-Path $env:ProgramFiles 'ServersStatus\ServersStatusService.exe'
$newExe = Join-Path $PSScriptRoot 'ServersStatusService.exe'
if (!(Test-Path $exe) -or !(Test-Path $newExe)) { throw 'Installed or new executable not found.' }
$backup = "$exe.$(Get-Date -Format 'yyyyMMddHHmmss').previous"
$service = Get-Service ServersStatusAgent
Stop-Service ServersStatusAgent
$service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
try {
    Copy-Item $exe $backup
    Copy-Item $newExe $exe -Force
    Start-Service ServersStatusAgent
    (Get-Service ServersStatusAgent).WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
    Start-Sleep -Seconds 5
    if ((Get-Service ServersStatusAgent).Status -ne 'Running') { throw 'Updated service stopped unexpectedly.' }
    Write-Host 'Updated. Configuration unchanged. Check new metrics in the panel within 2 minutes.'
} catch {
    $originalError = $_
    Stop-Service ServersStatusAgent -ErrorAction SilentlyContinue
    (Get-Service ServersStatusAgent).WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
    if (Test-Path $backup) { Copy-Item $backup $exe -Force }
    Start-Service ServersStatusAgent
    throw $originalError
}
