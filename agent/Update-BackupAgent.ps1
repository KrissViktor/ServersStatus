# Run from an elevated Windows PowerShell on the backup host only.
$ErrorActionPreference = 'Stop'
if ($env:COMPUTERNAME -ne 'WIN-CU629F0N7II') {
    throw 'This backup configuration is only for WIN-CU629F0N7II.'
}
$root = Join-Path $env:ProgramFiles 'ServersStatus'
$data = Join-Path $env:ProgramData 'ServersStatus'
$exe = Join-Path $root 'ServersStatusService.exe'
$configPath = Join-Path $data 'config.json'
$service = Get-Service ServersStatusAgent
$newExe = Join-Path $PSScriptRoot 'ServersStatusService.exe'
$rulesPath = Join-Path $PSScriptRoot 'backups.WIN-CU629F0N7II.json'
if (!(Test-Path $newExe) -or !(Test-Path $configPath)) { throw 'Executable or installed configuration not found.' }
$config = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$rules = Get-Content $rulesPath -Raw -Encoding UTF8 | ConvertFrom-Json
$config | Add-Member -NotePropertyName backups -NotePropertyValue @($rules) -Force
# Both backups stay in directories with the original Windows access permissions.
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
$configBackup = "$configPath.$stamp.previous"
$exeBackup = "$exe.$stamp.previous"
Copy-Item $configPath $configBackup
Stop-Service ServersStatusAgent
$service.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60))
Copy-Item $exe $exeBackup
try {
    Copy-Item $newExe $exe -Force
    [IO.File]::WriteAllText($configPath, ($config | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding($false)))
    Start-Service ServersStatusAgent
    (Get-Service ServersStatusAgent).WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
    Write-Host 'Agent updated. Check the panel after two reporting intervals (about 2 minutes).'
} catch {
    Stop-Service ServersStatusAgent -ErrorAction SilentlyContinue
    Copy-Item $exeBackup $exe -Force
    Copy-Item $configBackup $configPath -Force
    Start-Service ServersStatusAgent
    throw
}
