$ErrorActionPreference='Stop'
$scriptFile=Join-Path $PSScriptRoot '../agent/install_sensor_driver.ps1'
$correctHash='a3a46226c5e2824f4cdd42be0eecbabfc672c86f7889710f5ab1e6ad385b47a0'
function Test-Path { param($Path) return $script:installed }
function Get-FileHash { param($LiteralPath,$Algorithm) [pscustomobject]@{Hash=$script:hash} }
function Get-AuthenticodeSignature { param($LiteralPath) [pscustomobject]@{Status=$script:signature} }
function Start-Process {
    param($FilePath,$ArgumentList,[switch]$PassThru,$WindowStyle)
    if (($ArgumentList -join ' ') -ne '-install -silent') { throw 'Unexpected installer flags' }
    if ($FilePath -notlike '*hardware-monitor-bin*PawnIO_setup.exe') { throw 'Unexpected installer path' }
    $script:started++
    if ($script:confirm) { $script:installed=$true }
    $process=[pscustomobject]@{ExitCode=$script:code;HasExited=(!$script:timeout)}
    $process | Add-Member ScriptMethod WaitForExit { param($milliseconds) if ($milliseconds -ne 60000) { throw 'Unexpected wait' }; return !$script:timeout }
    $process | Add-Member ScriptMethod Kill { $script:killed=$true }
    $process | Add-Member ScriptMethod Dispose { $script:disposed=$true }
    return $process
}
foreach($case in @('installed','bad-hash','bad-signature','success','failed','timeout','unconfirmed')) {
    $script:installed=($case -eq 'installed');$script:hash=$correctHash;$script:signature='Valid'
    $script:confirm=($case -eq 'success');$script:code=0;$script:timeout=($case -eq 'timeout')
    $script:started=0;$script:killed=$false;$script:disposed=$false
    if($case -eq 'bad-hash'){$script:hash='bad'}
    if($case -eq 'bad-signature'){$script:signature='NotTrusted'}
    if($case -eq 'failed'){$script:code=1}
    $failed=$false
    try { . $scriptFile } catch { $failed=$true }
    if($failed -ne ($case -notin @('installed','success'))) { throw "Wrong result: $case" }
    if($case -in @('installed','bad-hash','bad-signature')) {
        if($script:started){throw "Installer should not run: $case"}
    } else {
        if($script:started -ne 1 -or !$script:disposed){throw "Missing cleanup: $case"}
    }
    if($script:killed -ne ($case -eq 'timeout')){throw "Wrong timeout cleanup: $case"}
    Write-Output "PASS $case"
}
