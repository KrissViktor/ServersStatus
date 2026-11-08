#Requires -Version 5.1
#Requires -RunAsAdministrator
param([switch]$AllowOtherComputer)
$ErrorActionPreference='Stop'
if(!$AllowOtherComputer -and $env:COMPUTERNAME -ne 'WIN-CU629F0N7II'){throw 'Run on Backup / WIN-CU629F0N7II'}
$root='C:\ProgramData\ServersStatusAI\tunnel'
$keygen="$env:WINDIR\System32\OpenSSH\ssh-keygen.exe"
if(!(Test-Path $keygen)){throw 'Install OpenSSH Client: Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0'}
New-Item -ItemType Directory -Force -Path $root | Out-Null
& icacls.exe $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
if($LASTEXITCODE){throw 'Could not protect SSH key directory'}
$key="$root\id_ed25519"
if(!(Test-Path $key)){
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$keygen;$start.Arguments='-t ed25519 -f "'+$key+'" -N "" -C "ServersStatusAI-windows-02"'
    $start.UseShellExecute=$false;$start.CreateNoWindow=$true
    $process=[Diagnostics.Process]::Start($start);$process.WaitForExit();$code=$process.ExitCode;$process.Dispose()
    if($code){throw 'SSH key generation failed'}
}
if(!(Test-Path ($key+'.pub'))){throw 'Private key exists but public file is missing; do not overwrite the private key'}
Write-Host 'Copy ONLY this PUBLIC key to Raspberry Pi; keep id_ed25519 private:'
Get-Content ($key+'.pub')
