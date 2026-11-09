$ErrorActionPreference='Stop'
$scriptFile=Join-Path $PSScriptRoot '../agent/install_sensor_driver.ps1'
# Use real CLR methods to avoid ScriptMethod's dependency on the calling
# script scope across Windows PowerShell 5.1 and PowerShell 7.
Add-Type -TypeDefinition @'
public sealed class SensorDriverTestProcess {
    public int ExitCode { get; set; }
    public bool HasExited { get; set; }
    public bool TimedOut { get; set; }
    public bool Killed { get; private set; }
    public bool Disposed { get; private set; }
    public bool WaitForExit(int milliseconds) {
        if (milliseconds != 60000) throw new System.Exception("Unexpected wait");
        return !TimedOut;
    }
    public void Kill() { Killed = true; HasExited = true; }
    public void Dispose() { Disposed = true; }
}
'@
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
    $process=New-Object SensorDriverTestProcess
    $process.ExitCode=$script:code
    $process.HasExited=(!$script:timeout)
    $process.TimedOut=$script:timeout
    $script:mockProcess=$process
    return $process
}
foreach($case in @('installed','bad-hash','bad-signature','success','failed','timeout','unconfirmed')) {
    $script:installed=($case -eq 'installed');$script:hash=$correctHash;$script:signature='Valid'
    $script:confirm=($case -eq 'success');$script:code=0;$script:timeout=($case -eq 'timeout')
    $script:started=0;$script:mockProcess=$null
    if($case -eq 'bad-hash'){$script:hash='bad'}
    if($case -eq 'bad-signature'){$script:signature='NotTrusted'}
    if($case -eq 'failed'){$script:code=1}
    $failed=$false;$failureDetail=''
    try { . $scriptFile } catch { $failed=$true;$failureDetail=($_ | Out-String) }
    if($failed -ne ($case -notin @('installed','success'))) { throw "Wrong result: $case`n$failureDetail" }
    if($case -in @('installed','bad-hash','bad-signature')) {
        if($script:started){throw "Installer should not run: $case"}
    } else {
        if($script:started -ne 1 -or !$script:mockProcess.Disposed){throw "Missing cleanup: $case"}
    }
    if(($null -ne $script:mockProcess -and $script:mockProcess.Killed) -ne ($case -eq 'timeout')){throw "Wrong timeout cleanup: $case"}
    Write-Output "PASS $case"
}
