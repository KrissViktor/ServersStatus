#Requires -Version 5.1
$ErrorActionPreference='Stop'
$root=Join-Path $env:TEMP ('AI-connect-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root|Out-Null
@'
using System;using System.IO;
class FakeTailscale {
 static int Main(string[] args){string root=Environment.GetEnvironmentVariable("SS_AI_CONNECT_TEST"),cmd=String.Join(" ",args);File.AppendAllText(Path.Combine(root,"calls"),cmd+"\n");
 if(cmd=="status --json")Console.WriteLine(File.ReadAllText(Path.Combine(root,"status.json")));
 else if(cmd=="serve status --json")Console.WriteLine(File.ReadAllText(Path.Combine(root,"serve.json")));
 else if(cmd=="set --unattended=true"||cmd=="serve --bg --https=8443 http://127.0.0.1:8091")Console.WriteLine("ok");
 else return 9;return 0;
 }
}
'@ | Set-Content "$root\Fake.cs"
$csc="$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /platform:x64 /target:exe "/out:$root\tailscale.exe" "$root\Fake.cs"
if($LASTEXITCODE){throw 'Fake Tailscale compilation failed'}
function Invoke-RestMethod {param($Uri,$TimeoutSec) if($Uri -ne 'http://127.0.0.1:8091/health'){throw 'Unexpected request'};return @{status='ok'}}
$env:SS_AI_CONNECT_TEST=$root
try{
 '{"BackendState":"Running","Self":{"DNSName":"backup.test-tail.ts.net."}}' | Set-Content "$root\status.json"
 '{}' | Set-Content "$root\serve.json"
 & "$PSScriptRoot\Connect-AI.ps1" -TailscalePath "$root\tailscale.exe" -AllowOtherComputer
 $calls=Get-Content "$root\calls" -Raw
 if($calls -notmatch 'set --unattended=true' -or $calls -notmatch 'serve --bg --https=8443 http://127.0.0.1:8091' -or $calls -match 'funnel|reset'){throw 'Unexpected Tailscale mutations'}
 # Already configured private endpoint is repeatable.
 '{"TCP":{"8443":{"HTTPS":true}},"Web":{"backup.test-tail.ts.net:8443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8091"}}}}}' | Set-Content "$root\serve.json"
 & "$PSScriptRoot\Connect-AI.ps1" -TailscalePath "$root\tailscale.exe" -AllowOtherComputer
 foreach($bad in @('{"TCP":{"8443":{"TCPForward":"localhost:9999"}}}', '{"AllowFunnel":{"backup.test-tail.ts.net:8443":true}}')){
  $bad | Set-Content "$root\serve.json";Clear-Content "$root\calls";$failed=$false
  try{& "$PSScriptRoot\Connect-AI.ps1" -TailscalePath "$root\tailscale.exe" -AllowOtherComputer}catch{$failed=$true}
  if(!$failed -or (Get-Content "$root\calls" -Raw) -match 'set --|serve --bg'){throw 'Conflicting/public configuration was modified'}
 }
 '{"BackendState":"NeedsLogin"}' | Set-Content "$root\status.json";$failed=$false
 try{& "$PSScriptRoot\Connect-AI.ps1" -TailscalePath "$root\tailscale.exe" -AllowOtherComputer}catch{$failed=$true}
 if(!$failed){throw 'Not-logged-in client accepted'}
}finally{Remove-Item Env:\SS_AI_CONNECT_TEST -ErrorAction SilentlyContinue}
Write-Host 'Passed: private Serve to loopback, unattended mode, idempotent config, collision/Funnel/login rejection. Fake CLI only; no real VPN/network/settings changed.'
