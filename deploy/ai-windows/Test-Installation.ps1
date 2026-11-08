# CI smoke test: no model downloads, network listeners or real AI inference.
#Requires -Version 5.1
#Requires -RunAsAdministrator
$ErrorActionPreference='Stop'
$root=Join-Path $env:ProgramData ('ServersStatus-AI-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root,"$root\logs" | Out-Null
& icacls.exe $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-19:(OI)(CI)RX' | Out-Null
if($LASTEXITCODE){throw 'Root ACL failed'}
& icacls.exe "$root\logs" /grant:r '*S-1-5-19:(OI)(CI)M' | Out-Null
if($LASTEXITCODE){throw 'Log ACL failed'}
$csc="$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
foreach($file in Get-ChildItem $PSScriptRoot -Filter '*.ps1'){
 $tokens=$null;$errors=$null;[Management.Automation.Language.Parser]::ParseFile($file.FullName,[ref]$tokens,[ref]$errors)|Out-Null
 if($errors){throw ($file.Name+': '+($errors | Out-String))}
}
& $csc /nologo /target:exe "/out:$root\service.exe" /reference:System.ServiceProcess.dll "$PSScriptRoot\AIService.cs"
if($LASTEXITCODE){throw 'Service did not compile'}
@'
using System;using System.Threading;
class FakeModel {static void Main(){Console.WriteLine("fake-model-started");while(true)Thread.Sleep(100);}}
'@ | Set-Content "$root\Fake.cs"
& $csc /nologo /target:exe "/out:$root\fake.exe" "$root\Fake.cs"
if($LASTEXITCODE){throw 'Fake engine did not compile'}
$xml=New-Object Xml.XmlDocument;$xml.AppendChild($xml.CreateElement('Settings'))|Out-Null
foreach($pair in @(@('Executable',"$root\fake.exe"),@('Arguments',''),@('WorkingDirectory',$root),@('CpuPercent',80),@('MemoryMB',256),@('ReserveMB',0))){$e=$xml.CreateElement($pair[0]);$e.InnerText=[string]$pair[1];$xml.DocumentElement.AppendChild($e)|Out-Null}
$xml.Save("$root\settings.xml")
function Wait-Until([scriptblock]$Condition){for($i=0;$i -lt 80;$i++){if(& $Condition){return};Start-Sleep -Milliseconds 250};throw 'Condition timed out'}
try{
 & sc.exe create ServersStatusAI binPath= ('"'+$root+'\service.exe"') start= demand obj= 'NT AUTHORITY\LocalService' | Out-Null
 if($LASTEXITCODE){throw 'Could not register test service'}
 Start-Service ServersStatusAI
 Wait-Until {Test-Path "$root\logs\service.log"}
 Wait-Until {(Get-Content "$root\logs\service.log" -Raw) -match 'fake-model-started'}
 $child=Get-CimInstance Win32_Process -Filter "Name='fake.exe'" | Where-Object {$_.ExecutablePath -eq "$root\fake.exe"}
 if(!$child){throw 'Child engine did not run'}
 $childId=$child.ProcessId
 [IO.File]::WriteAllText("$root\pause-until.txt",[string]([DateTimeOffset]::UtcNow.AddMinutes(5).ToUnixTimeSeconds()))
 Wait-Until {!(Get-Process -Id $childId -ErrorAction SilentlyContinue)}
 Remove-Item "$root\pause-until.txt"
 Wait-Until {(Get-Content "$root\logs\service.log" -Raw | Select-String 'fake-model-started' -AllMatches).Matches.Count -ge 2}
 Stop-Service ServersStatusAI
 Wait-Until {!(@(Get-CimInstance Win32_Process -Filter "Name='fake.exe'" | Where-Object {$_.ExecutablePath -eq "$root\fake.exe"}).Count)}
 Write-Host 'Passed: PS5.1 syntax, C# compilation, service start, bounded child launch, pause unload, resume, stop cleanup.'
}finally{
 Stop-Service ServersStatusAI -ErrorAction SilentlyContinue
 & sc.exe delete ServersStatusAI | Out-Null
 if(Test-Path "$root\logs\service.log"){Get-Content "$root\logs\service.log" -Tail 30}
}
