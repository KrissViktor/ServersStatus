# One-time bootstrap for agents carrying the old EXE replacement helper.
$ErrorActionPreference='Stop'
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {throw 'Run PowerShell as administrator'}
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$root=Join-Path $env:ProgramData 'ServersStatus'
if (-not (Test-Path (Join-Path $root 'config.json'))) {throw 'Existing agent configuration not found'}
$folder=Join-Path $root ('repair-'+(Get-Date -Format 'yyyyMMddHHmmssfff'))
New-Item -ItemType Directory -Path $folder | Out-Null
$base='https://github.com/KrissViktor/ServersStatus/releases/download/'
$release=Invoke-RestMethod -Uri ($base+'agents-stable/update-windows.json') -TimeoutSec 60
if ($release.schema -ne 1 -or $release.platform -ne 'windows-x64' -or $release.version -notmatch '^[a-f0-9]{12}$' -or $release.sha256 -notmatch '^[a-f0-9]{64}$') {throw 'Invalid Windows release manifest'}
if ($release.updater_protocol -ne 2) {throw 'Fixed Windows build is not published yet. Wait for a successful new Windows workflow, then retry.'}
$expected=$base+'agent-windows-'+$release.version+'/ServersStatusService.exe'
if ($release.download_url -cne $expected -or $release.size -lt 1 -or $release.size -gt 209715200) {throw 'Invalid release package address or size'}
$package=Join-Path $folder 'ServersStatusService.exe'
Invoke-WebRequest -UseBasicParsing -Uri $expected -OutFile $package -TimeoutSec 300
if ((Get-Item $package).Length -ne $release.size -or (Get-FileHash $package -Algorithm SHA256).Hash.ToLowerInvariant() -cne $release.sha256) {throw 'Package checksum or size mismatch. Installed service was not changed.'}
$helper=Join-Path $folder 'apply_update.ps1'
# This is code from the same trusted public repository, explicitly invoked by the administrator.
Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/KrissViktor/ServersStatus/main/agent/apply_update.ps1' -OutFile $helper -TimeoutSec 60
& $helper -Package $package -Sha256 $release.sha256
Write-Host ('Agent updated to '+$release.version+'. Configuration preserved. Log: '+(Join-Path $folder 'update.log'))
