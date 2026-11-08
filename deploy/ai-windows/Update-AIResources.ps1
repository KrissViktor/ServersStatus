#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [ValidateRange(1,80)][int]$CpuPercent=80,
    [ValidateRange(1,20)][int]$Threads=16,
    [string]$SettingsPath='C:\ProgramData\ServersStatusAI\settings.xml'
)
$ErrorActionPreference='Stop'
$settings=New-Object System.Xml.XmlDocument
$settings.XmlResolver=$null
$settings.Load($SettingsPath)
$cpu=$settings.SelectSingleNode('/Settings/CpuPercent')
$argsNode=$settings.SelectSingleNode('/Settings/Arguments')
if(!$cpu -or !$argsNode){throw 'Invalid AI settings: CpuPercent or Arguments is missing'}
$arguments=$argsNode.InnerText
foreach($flag in @('--threads','--threads-batch')){
    $pattern='(?<!\S)'+[regex]::Escape($flag)+'(?:\s+|=)\d+(?=\s|$)'
    $matchesForFlag=[regex]::Matches($arguments,$pattern)
    if($matchesForFlag.Count -gt 1){throw ('Repeated '+$flag+' option; review settings before updating')}
    if($matchesForFlag.Count -eq 1){$arguments=[regex]::Replace($arguments,$pattern,($flag+' '+$Threads))}
    else{$arguments=$arguments.TrimEnd()+' '+$flag+' '+$Threads}
}
if($cpu.InnerText -eq [string]$CpuPercent -and $arguments -eq $argsNode.InnerText){
    Write-Host ('Already configured: CPU cap '+$CpuPercent+'%; threads '+$Threads+'. No restart needed.');return
}
$service=Get-Service -Name ServersStatusAI -ErrorAction Stop
if($service.Status -notin @('Running','Stopped')){throw 'Service is transitioning; wait before updating'}
$wasRunning=$service.Status -eq 'Running'
$backup=$SettingsPath+'.resources-'+[DateTime]::UtcNow.ToString('yyyyMMddHHmmssfff')+'-'+[Guid]::NewGuid().ToString('N')+'.bak'
$temp=$SettingsPath+'.'+[Guid]::NewGuid().ToString('N')+'.tmp'
$stopped=$false;$applied=$false
try{
    $cpu.InnerText=[string]$CpuPercent;$argsNode.InnerText=$arguments
    $settings.Save($temp)
    if($wasRunning){Stop-Service -Name ServersStatusAI -ErrorAction Stop;$service.WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30));$stopped=$true}
    [IO.File]::Replace($temp,$SettingsPath,$backup);$applied=$true
    if($wasRunning){Start-Service -Name ServersStatusAI -ErrorAction Stop;(Get-Service -Name ServersStatusAI).WaitForStatus('Running',[TimeSpan]::FromSeconds(30))}
}catch{
    $failure=$_
    if($applied){
        try{
            if($wasRunning){Stop-Service -Name ServersStatusAI -ErrorAction SilentlyContinue;(Get-Service -Name ServersStatusAI).WaitForStatus('Stopped',[TimeSpan]::FromSeconds(30))}
            [IO.File]::Copy($backup,$temp,$true);[IO.File]::Replace($temp,$SettingsPath,[NullString]::Value)
            Write-Warning 'Previous settings restored.'
        }catch{Write-Warning ('Automatic restore failed. Backup: '+$backup)}
    }
    if($wasRunning -and $stopped){try{Start-Service -Name ServersStatusAI -ErrorAction Stop}catch{Write-Warning 'Could not restart the service; check Get-Service ServersStatusAI.'}}
    throw $failure
}finally{if(Test-Path -LiteralPath $temp){Remove-Item -LiteralPath $temp -Force}}
Write-Host ('Configured: CPU cap '+$CpuPercent+'%; generation/batch threads '+$Threads+'.')
Write-Host ('Settings backup: '+$backup)
if($wasRunning){Write-Host 'Model is reloading; allow several minutes. Check logs\service.log and Test-AI.ps1.'}
else{Write-Host 'Service was stopped and remains stopped; settings apply on its next start.'}
Write-Host 'A CPU cap is a ceiling, not guaranteed usage or speed. More threads can be memory-bandwidth limited.'
