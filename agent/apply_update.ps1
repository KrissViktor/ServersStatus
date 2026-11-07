param(
    [string]$Manifest,
    [string]$Package,
    [string]$Sha256
)
$ErrorActionPreference='Stop'
$log=Join-Path $PSScriptRoot 'update.log'
function Write-UpdateLog($text) {
    try {Add-Content -Path $log -Value ((Get-Date).ToUniversalTime().ToString('o')+' '+$text) -Encoding UTF8} catch {}
}
Write-UpdateLog 'Helper entered; reading startup parameters.'
$job=$null;$config=$null
try {
    if ($Manifest) {
        $job=Get-Content $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
        $config=Get-Content $job.config_path -Raw -Encoding UTF8 | ConvertFrom-Json
        if (([uri]$config.server_url).Scheme -ne 'https') {throw 'HTTPS required'}
        $Package=Join-Path $PSScriptRoot 'ServersStatusService.exe'
        $Sha256=$job.sha256
    }
    if (-not $Package -or $Sha256 -notmatch '^[a-fA-F0-9]{64}$') {throw 'Package and SHA256 are required'}
} catch {
    # Do not write raw config parser errors; they may contain credentials.
    Write-UpdateLog 'Startup validation failed. Verify manifest/config JSON and package parameters locally.'
    throw 'Updater startup validation failed. See update.log; do not share configuration contents.'
}
$exe=Join-Path $env:ProgramFiles 'ServersStatus\ServersStatusService.exe'
$identifier=if ($job) {$job.job_id} else {Get-Date -Format 'yyyyMMddHHmmssfff'}
$backup="$exe.job-$identifier.previous"
$stage='verify';$replacementAttempted=$false;$stopped=$false;$backupReady=$false

function Report-Status($state,$code,$rollback='not_needed') {
    if (-not $job) {return}
    try {
        $endpoint=$config.server_url.TrimEnd('/')+'/api/agent-update/'+[uri]::EscapeDataString($config.agent_id)+'/status'
        $body=@{job_id=[int]$job.job_id;status=$state;error_code=$code;rollback=$rollback} | ConvertTo-Json
        Invoke-RestMethod -Uri $endpoint -Method Post -ContentType 'application/json; charset=utf-8' -Headers @{Authorization=('Bearer '+$config.token)} -Body ([Text.Encoding]::UTF8.GetBytes($body)) -MaximumRedirection 0 -TimeoutSec 30 | Out-Null
    } catch {Write-UpdateLog 'Status delivery failed; check panel connectivity.'}
}
function Stop-Agent {
    $service=Get-Service ServersStatusAgent
    if ($service.Status -ne 'Stopped') {Stop-Service ServersStatusAgent}
    (Get-Service ServersStatusAgent).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(90))
}
function Wait-ExecutableReleased($path) {
    # SCM STOPPED can precede exit of the PyInstaller onefile parent bootloader.
    $deadline=[DateTime]::UtcNow.AddSeconds(90)
    do {
        $mapped=@(Get-Process -Name ServersStatusService -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq $path})
        if ($mapped.Count -eq 0) {
            if (-not (Test-Path -LiteralPath $path)) {return}
            try {
                $handle=[IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
                $handle.Dispose()
                return
            } catch { }
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Executable still in use or not writable after waiting 90 seconds'
}
function Copy-WithRetry($source,$destination) {
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    do {
        try {Copy-Item -LiteralPath $source -Destination $destination -Force;return}
        catch {if ([DateTime]::UtcNow -ge $deadline) {throw};Start-Sleep -Milliseconds 500}
    } while ($true)
}
try {
    Write-UpdateLog 'Begin update; stage=verify'
    if ((Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256.ToLowerInvariant()) {throw 'Checksum mismatch'}
    if (-not (Test-Path -LiteralPath $exe)) {throw 'Installed service executable not found'}
    $stage='stop';Write-UpdateLog 'stage=stop';$stopped=$true;Stop-Agent
    $stage='wait_exit';Write-UpdateLog 'stage=wait_exit';Wait-ExecutableReleased $exe
    $stage='backup';Write-UpdateLog 'stage=backup';Copy-WithRetry $exe $backup;$backupReady=$true
    $stage='replace';Write-UpdateLog 'stage=replace';$replacementAttempted=$true;Copy-WithRetry $Package $exe
    if ((Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Sha256.ToLowerInvariant()) {throw 'Installed executable checksum mismatch'}
    $stage='start';Write-UpdateLog 'stage=start';Start-Service ServersStatusAgent
    (Get-Service ServersStatusAgent).WaitForStatus('Running',[TimeSpan]::FromSeconds(60))
    $stage='health';Start-Sleep -Seconds 5
    if ((Get-Service ServersStatusAgent).Status -ne 'Running') {throw 'Updated service stopped unexpectedly'}
    Write-UpdateLog 'Service running; waiting for version telemetry confirmation.'
    Report-Status 'running' 'awaiting_version'
} catch {
    $failure=$stage
    Write-UpdateLog ('Failed stage='+$stage+'; '+$_.Exception.Message)
    $rollback='not_needed'
    try {
        if ($replacementAttempted -and $backupReady) {
            Stop-Agent;Wait-ExecutableReleased $exe
            Copy-WithRetry $backup $exe
            $rollback='restored'
        }
        if ($stopped -and (Get-Service ServersStatusAgent).Status -ne 'Running') {
            Start-Service ServersStatusAgent
            (Get-Service ServersStatusAgent).WaitForStatus('Running',[TimeSpan]::FromSeconds(60))
        }
    } catch {
        $rollback='failed';Write-UpdateLog ('Recovery failed; '+$_.Exception.Message)
    }
    Write-UpdateLog ('Final result=failed; stage='+$failure+'; rollback='+$rollback)
    Report-Status 'failed' $failure $rollback
    if (-not $job) {throw ('Agent update failed at '+$failure+'; recovery='+$rollback+'. See '+$log)}
}
