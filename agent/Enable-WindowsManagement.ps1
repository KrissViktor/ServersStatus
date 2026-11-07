param([switch]$Disable)
$ErrorActionPreference='Stop'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'Run PowerShell as administrator'}
$path=Join-Path $env:ProgramData 'ServersStatus\config.json'
$config=Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
$config | Add-Member -NotePropertyName allow_windows_management -NotePropertyValue (-not $Disable.IsPresent) -Force
Copy-Item $path "$path.before-management" -Force
$temporary="$path.$([guid]::NewGuid().ToString('N')).tmp"
try {
    [System.IO.File]::WriteAllText($temporary,($config | ConvertTo-Json -Depth 30),(New-Object System.Text.UTF8Encoding($false)))
    Move-Item $temporary $path -Force
} finally {if (Test-Path $temporary) {Remove-Item $temporary -Force}}
Restart-Service ServersStatusAgent
Write-Host 'Windows management setting saved. The agent service has restarted.'
