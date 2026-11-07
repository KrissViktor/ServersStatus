# Run in Windows PowerShell 5.1. All service/process commands are replaced by fixtures.
$ErrorActionPreference='Stop'
$originalProgramFiles=$env:ProgramFiles
$temporary=Join-Path ([IO.Path]::GetTempPath()) ('serversstatus-helper-'+[guid]::NewGuid().ToString('N'))
$sourceHelper=Join-Path $PSScriptRoot '..\agent\apply_update.ps1'
New-Item -ItemType Directory -Path $temporary | Out-Null
$helper=Join-Path $temporary 'apply_update.ps1'
[IO.File]::Copy($sourceHelper,$helper)
$global:SSUpdateTest_status='Running';$global:SSUpdateTest_stopCalls=0;$global:SSUpdateTest_processCalls=0;$global:SSUpdateTest_startCalls=0;$global:SSUpdateTest_failStart=$false;$global:SSUpdateTest_lock=$null
function Get-Service {
    $service=New-Object PSObject -Property @{Status=$global:SSUpdateTest_status}
    $service | Add-Member ScriptMethod WaitForStatus {param($state,$timeout)}
    return $service
}
function Stop-Service {$global:SSUpdateTest_stopCalls++;$global:SSUpdateTest_status='Stopped'}
function Start-Service {
    $global:SSUpdateTest_startCalls++
    if ($global:SSUpdateTest_failStart -and $global:SSUpdateTest_startCalls -eq 1) {throw 'Simulated startup failure'}
    $global:SSUpdateTest_status='Running'
}
function Get-Process {
    $global:SSUpdateTest_processCalls++
    if ($global:SSUpdateTest_processCalls -lt 3) {return (New-Object PSObject -Property @{Path=$global:SSUpdateTest_target})}
    if ($global:SSUpdateTest_lock) {$global:SSUpdateTest_lock.Dispose();$global:SSUpdateTest_lock=$null}
    return @()
}
try {
    $env:ProgramFiles=$temporary
    New-Item -ItemType Directory -Path (Join-Path $temporary 'ServersStatus') | Out-Null
    $global:SSUpdateTest_target=Join-Path $temporary 'ServersStatus\ServersStatusService.exe'
    $package=Join-Path $temporary 'new.exe'
    [IO.File]::WriteAllText($package,'NEW')
    $hash=(Get-FileHash $package -Algorithm SHA256).Hash
    # SCM says Stopped but a parent process still holds the file. The helper must wait.
    [IO.File]::WriteAllText($global:SSUpdateTest_target,'OLD')
    $global:SSUpdateTest_lock=[IO.File]::Open($global:SSUpdateTest_target,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    & $helper -Package $package -Sha256 $hash
    if ([IO.File]::ReadAllText($global:SSUpdateTest_target) -ne 'NEW' -or $global:SSUpdateTest_processCalls -lt 3) {throw 'Did not wait for the locked executable'}
    if ($global:SSUpdateTest_status -ne 'Running') {throw 'Service not restarted'}
    # Startup failure must recover the original file.
    Start-Sleep -Milliseconds 10
    [IO.File]::WriteAllText($global:SSUpdateTest_target,'OLD')
    $global:SSUpdateTest_failStart=$true;$global:SSUpdateTest_startCalls=0
    $caught=$false
    try {& $helper -Package $package -Sha256 $hash} catch {$caught=$true}
    if (-not $caught -or [IO.File]::ReadAllText($global:SSUpdateTest_target) -ne 'OLD' -or $global:SSUpdateTest_status -ne 'Running') {throw 'Rollback did not restore the old executable'}
    # A corrupt package must not stop the current service.
    $global:SSUpdateTest_stopCalls=0
    try {& $helper -Package $package -Sha256 ('0'*64)} catch {}
    if ($global:SSUpdateTest_stopCalls -ne 0) {throw 'Checksum rejection stopped a healthy service'}
    Write-Host 'Windows helper: locked file wait, replacement, rollback and checksum rejection passed.'
} finally {
    if ($global:SSUpdateTest_lock) {$global:SSUpdateTest_lock.Dispose()}
    $env:ProgramFiles=$originalProgramFiles
    Remove-Item $temporary -Recurse -Force
}
