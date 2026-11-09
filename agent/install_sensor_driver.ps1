#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
# Used only by the elevated service's background temperature worker.
if (Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO') { return }
$setup = Join-Path $PSScriptRoot 'hardware-monitor-bin\PawnIO_setup.exe'
$expected = 'a3a46226c5e2824f4cdd42be0eecbabfc672c86f7889710f5ab1e6ad385b47a0'
if ((Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) { throw 'PawnIO package hash mismatch' }
if ((Get-AuthenticodeSignature -LiteralPath $setup).Status -ne 'Valid') { throw 'PawnIO signature not trusted' }
$process = Start-Process -FilePath $setup -ArgumentList '-install','-silent' -PassThru -WindowStyle Hidden
try {
    if (!$process.WaitForExit(60000)) { throw 'PawnIO installation timed out' }
    if ($process.ExitCode -ne 0) { throw "PawnIO installation failed: $($process.ExitCode)" }
    if (!(Test-Path 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PawnIO')) { throw 'PawnIO installation not confirmed' }
} finally {
    if (!$process.HasExited) { $process.Kill() }
    $process.Dispose()
}
