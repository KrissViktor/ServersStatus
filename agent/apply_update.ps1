param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference = 'Stop'
$job = Get-Content $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
$config = Get-Content $job.config_path -Raw -Encoding UTF8 | ConvertFrom-Json
if (([uri]$config.server_url).Scheme -ne 'https') { throw 'HTTPS required' }
$endpoint = $config.server_url.TrimEnd('/') + '/api/agent-update/' + [uri]::EscapeDataString($config.agent_id) + '/status'
function Report-Status($state, $message) {
    try {
        $body = @{job_id=[int]$job.job_id;status=$state;message=$message} | ConvertTo-Json
        Invoke-RestMethod -Uri $endpoint -Method Post -ContentType 'application/json' -Headers @{Authorization=('Bearer '+$config.token)} -Body $body -MaximumRedirection 0 -TimeoutSec 30 | Out-Null
    } catch { }
}
$exe = Join-Path $env:ProgramFiles 'ServersStatus\ServersStatusService.exe'
$package = Join-Path $PSScriptRoot 'ServersStatusService.exe'
$backup = "$exe.job-$($job.job_id).previous"
try {
    if ((Get-FileHash $package -Algorithm SHA256).Hash.ToLowerInvariant() -ne $job.sha256) { throw 'Checksum mismatch' }
    Stop-Service ServersStatusAgent
    (Get-Service ServersStatusAgent).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(60))
    Copy-Item $exe $backup
    Copy-Item $package $exe -Force
    Start-Service ServersStatusAgent
    (Get-Service ServersStatusAgent).WaitForStatus('Running',[TimeSpan]::FromSeconds(60))
    Start-Sleep -Seconds 5
    if ((Get-Service ServersStatusAgent).Status -ne 'Running') { throw 'Service not running' }
    Report-Status 'running' 'Служба перезапущена; ожидается подтверждение версии'
} catch {
    try {
        Stop-Service ServersStatusAgent -ErrorAction SilentlyContinue
        (Get-Service ServersStatusAgent).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(60))
        if (Test-Path $backup) { Copy-Item $backup $exe -Force }
        Start-Service ServersStatusAgent
        Report-Status 'failed' 'Обновление не выполнено; предыдущая версия восстановлена'
    } catch {
        Report-Status 'failed' 'Обновление и восстановление не завершены; нужна локальная проверка службы'
    }
}
