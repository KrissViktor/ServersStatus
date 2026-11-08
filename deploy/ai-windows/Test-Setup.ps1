#Requires -Version 5.1
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'Setup-Helpers.ps1')
$root=Join-Path $env:TEMP ('AI-setup-test-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $root | Out-Null
$source=Join-Path $root 'source.gguf';$target=Join-Path $root 'model.gguf'
[IO.File]::WriteAllText($source,'verified model test fixture')
$hash=(Get-FileHash $source -Algorithm SHA256).Hash
$script:downloads=0
function Invoke-WebRequest {param([switch]$UseBasicParsing,$Uri,$OutFile) $script:downloads++;Copy-Item $source $OutFile -Force}
Get-VerifiedDownload -Uri 'https://example.invalid/model' -Path $target -Sha256 $hash
Get-VerifiedDownload -Uri 'https://example.invalid/model' -Path $target -Sha256 $hash
if($script:downloads -ne 1){throw 'A valid cached model was downloaded again'}
[IO.File]::WriteAllText($target,'damaged model')
Get-VerifiedDownload -Uri 'https://example.invalid/model' -Path $target -Sha256 $hash
if($script:downloads -ne 2 -or !(Test-VerifiedFile $target $hash)){throw 'Damaged cache was reused'}
$failed=$false
try{Get-VerifiedDownload -Uri 'https://example.invalid/model' -Path $target -Sha256 ('0'*64)}catch{$failed=$true}
if(!$failed -or !(Test-VerifiedFile $target $hash)){throw 'Mismatching download replaced the verified target'}
@'
using System;
class Engine {
 static int Main(){string code=Environment.GetEnvironmentVariable("SS_AI_TEST_EXIT");
 if(!String.IsNullOrEmpty(code)){Console.Error.WriteLine("native test diagnostic");return Int32.Parse(code);}
 Console.WriteLine("--api-key-file --load-mode --reasoning");Console.Error.WriteLine("build info");return 0;
 }
}
'@ | Set-Content "$root\Engine.cs"
$csc="$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
& $csc /nologo /platform:x64 /target:exe "/out:$root\engine.exe" "$root\Engine.cs"
if($LASTEXITCODE){throw 'Fake engine compilation failed'}
try{
 $global:LASTEXITCODE=42
 $help=Get-EngineHelp -Executable "$root\engine.exe" -LogPath "$root\check.log"
 if($help -notmatch '--api-key-file' -or $help -notmatch 'build info'){throw 'Help stdout/stderr was not captured'}
 foreach($case in @(@('-1073741515','C0000135'),@('-1073741795','C000001D'),@('1','00000001'))){
  $env:SS_AI_TEST_EXIT=$case[0];$failed=$false
  try{Get-EngineHelp -Executable "$root\engine.exe" -LogPath "$root\check.log"|Out-Null}catch{$failed=$true;if($_.Exception.Message -notmatch $case[1]){throw 'Wrong startup error classification'}}
  if(!$failed -or (Get-Content "$root\check.log" -Raw) -notmatch 'native test diagnostic'){throw 'Failure details were lost'}
 }
}finally{Remove-Item Env:\SS_AI_TEST_EXIT -ErrorAction SilentlyContinue}
Write-Host 'Passed: verified-cache reuse, damaged cache rejection, failed download preservation, real exit codes, DLL/CPU failure classification and diagnostic logs. No network or model download.'
