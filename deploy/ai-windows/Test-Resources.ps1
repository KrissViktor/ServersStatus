#Requires -Version 5.1
$ErrorActionPreference='Stop'
$root=Join-Path $env:TEMP ('AI-resource-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root|Out-Null
$path=Join-Path $root 'settings.xml'
$testState=[pscustomobject]@{Stops=0;Starts=0;FailStart=$false;Service=[pscustomobject]@{Status='Running'}}
$testState.Service|Add-Member -MemberType ScriptMethod -Name WaitForStatus -Value {param($Wanted,$Timeout) if([string]$this.Status -ne [string]$Wanted){throw 'Unexpected service status'}}
# Capture one shared object; $script: inside a called .ps1 refers to that script,
# not this fixture. Closures keep the mocks independent of the caller's scope.
Set-Item Function:Get-Service -Value ({param($Name) if($Name -ne 'ServersStatusAI'){throw 'Wrong service'};return $testState.Service}.GetNewClosure())
Set-Item Function:Stop-Service -Value ({param($Name) if($Name -ne 'ServersStatusAI'){throw 'Wrong service'};$testState.Stops++;$testState.Service.Status='Stopped'}.GetNewClosure())
Set-Item Function:Start-Service -Value ({param($Name) if($Name -ne 'ServersStatusAI'){throw 'Wrong service'};$testState.Starts++;if($testState.FailStart){$testState.FailStart=$false;throw 'Simulated start failure'};$testState.Service.Status='Running'}.GetNewClosure())
function Write-Fixture {
    '<Settings><Executable>C:\engine\llama-server.exe</Executable><Arguments>--model "C:\model file.gguf" --threads 12 --threads-batch 12 --ctx-size 8192 --api-key-file "C:\api-key.txt"</Arguments><CpuPercent>60</CpuPercent><MemoryMB>22528</MemoryMB><ReserveMB>4096</ReserveMB><FutureSetting>keep</FutureSetting></Settings>'|Set-Content -LiteralPath $path -Encoding UTF8
}
try{
    Write-Fixture
    $key=Join-Path $root 'api-key.txt';[IO.File]::WriteAllText($key,'PRIVATE_TEST_KEY')
    & (Join-Path $PSScriptRoot 'Update-AIResources.ps1') -SettingsPath $path
    [xml]$result=Get-Content -LiteralPath $path -Raw
    if($result.Settings.CpuPercent -ne '80' -or $result.Settings.Arguments -notmatch '--threads 16 --threads-batch 16'){throw 'Resource settings were not updated'}
    if($result.Settings.MemoryMB -ne '22528' -or $result.Settings.ReserveMB -ne '4096' -or $result.Settings.FutureSetting -ne 'keep' -or $result.Settings.Arguments -notmatch '--model "C:\\model file.gguf"' -or [IO.File]::ReadAllText($key) -ne 'PRIVATE_TEST_KEY'){throw 'Unrelated settings changed'}
    if($testState.Stops -ne 1 -or $testState.Starts -ne 1){throw 'Wrong restart count'}
    $hash=(Get-FileHash $path).Hash
    & (Join-Path $PSScriptRoot 'Update-AIResources.ps1') -SettingsPath $path
    if((Get-FileHash $path).Hash -ne $hash -or $testState.Stops -ne 1){throw 'Idempotent update restarted or changed configuration'}
    # Existing installations already capped at 80% still need more worker threads.
    Write-Fixture;[xml]$oldConfig=Get-Content -LiteralPath $path -Raw;$oldConfig.Settings.CpuPercent='80';$oldConfig.Save($path)
    $oldStops=$testState.Stops
    & (Join-Path $PSScriptRoot 'Update-AIResources.ps1') -SettingsPath $path
    [xml]$updated=Get-Content -LiteralPath $path -Raw
    if($updated.Settings.Arguments -notmatch '--threads 16 --threads-batch 16' -or $testState.Stops -ne $oldStops+1){throw 'Existing 80% cap prevented thread update'}
    Write-Fixture;$testState.FailStart=$true
    $rejected=$false
    try{& (Join-Path $PSScriptRoot 'Update-AIResources.ps1') -SettingsPath $path}catch{$rejected=$true}
    [xml]$restored=Get-Content -LiteralPath $path -Raw
    if(!$rejected -or $restored.Settings.CpuPercent -ne '60' -or $restored.Settings.Arguments -notmatch '--threads 12 --threads-batch 12' -or $testState.Service.Status -ne 'Running'){throw 'Restart failure did not restore settings/service'}
    Write-Fixture;$testState.Service.Status='Stopped';$oldStarts=$testState.Starts;$oldStops=$testState.Stops
    & (Join-Path $PSScriptRoot 'Update-AIResources.ps1') -SettingsPath $path
    if($testState.Starts -ne $oldStarts -or $testState.Stops -ne $oldStops -or $testState.Service.Status -ne 'Stopped'){throw 'Stopped service was unexpectedly started'}
    $hash=(Get-FileHash $path).Hash;$rejected=$false
    try{& (Join-Path $PSScriptRoot 'Update-AIResources.ps1') -SettingsPath $path -CpuPercent 81}catch{$rejected=$true}
    if(!$rejected -or (Get-FileHash $path).Hash -ne $hash){throw 'Invalid cap was accepted'}
    Write-Host 'Passed: 80%/16 threads, memory/key preservation, backup/restart, idempotence, rollback, stopped-service preservation, invalid cap rejection. No model/network or real services.'
}finally{Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue}
