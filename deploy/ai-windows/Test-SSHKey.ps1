#Requires -Version 5.1
#Requires -RunAsAdministrator
param([switch]$SystemProbe)
$ErrorActionPreference='Stop'
$root='C:\ProgramData\ServersStatusAI\tunnel'
if($SystemProbe){
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName="$env:WINDIR\System32\OpenSSH\ssh-keygen.exe";$start.Arguments='-y -f "'+$root+'\id_ed25519"'
    $start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
    $process=[Diagnostics.Process]::Start($start);$out=$process.StandardOutput.ReadToEndAsync();$err=$process.StandardError.ReadToEndAsync()
    if(!$process.WaitForExit(15000)){$process.Kill();throw 'SYSTEM key probe timed out'}
    @{identity=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value;code=$process.ExitCode;public=$out.Result;error=$err.Result}|ConvertTo-Json|Set-Content "$root\system-probe.json" -Encoding UTF8
    $process.Dispose();exit 0
}
& "$PSScriptRoot\New-AITunnelKey.ps1" -AllowOtherComputer
$first=(Get-FileHash "$root\id_ed25519" -Algorithm SHA256).Hash
# Reproduce a key created by a different individual user, with an extra explicit ACE.
& icacls.exe "$root\id_ed25519" /grant '*S-1-5-19:R' | Out-Null
if($LASTEXITCODE){throw 'Could not prepare insecure test ACL'}
& icacls.exe "$root\id_ed25519" /setowner ('*'+[Security.Principal.WindowsIdentity]::GetCurrent().User.Value) | Out-Null
if($LASTEXITCODE){throw 'Could not prepare test owner'}
& "$PSScriptRoot\New-AITunnelKey.ps1" -AllowOtherComputer
if((Get-FileHash "$root\id_ed25519" -Algorithm SHA256).Hash -ne $first){throw 'Existing SSH key was replaced'}
$key=Get-Content "$root\id_ed25519.pub" -Raw
if($key -notmatch '^ssh-ed25519 '){throw 'Missing public key'}
foreach($path in @($root,"$root\id_ed25519")){
 $acl=Get-Acl $path
 foreach($rule in $acl.GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])){if($rule.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')){throw 'Unexpected key access permissions'}}
}
if((Get-Acl "$root\id_ed25519").GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544'){throw 'Private key owner was not repaired'}
$taskName='AI-KeyProbe-'+[Guid]::NewGuid().ToString('N')
try{
 Remove-Item "$root\system-probe.json" -ErrorAction SilentlyContinue
 $action=New-ScheduledTaskAction -Execute "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -SystemProbe')
 $principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
 Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal | Out-Null
 Start-ScheduledTask -TaskName $taskName
 for($i=0;$i -lt 180 -and !(Test-Path "$root\system-probe.json");$i++){Start-Sleep -Milliseconds 250}
 if(!(Test-Path "$root\system-probe.json")){throw 'SYSTEM key read did not complete'}
 $probe=Get-Content "$root\system-probe.json" -Raw|ConvertFrom-Json
 if($probe.identity -ne 'S-1-5-18' -or $probe.code -ne 0){throw ('SYSTEM could not read private key: '+$probe.error)}
 $actual=($probe.public.Trim() -split '\s+')[0..1] -join ' '
 $expected=($key.Trim() -split '\s+')[0..1] -join ' '
 if($actual -ne $expected){throw 'SYSTEM public key does not match original key'}
}finally{Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue;Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue}
Write-Host 'Passed: real Windows keygen, repair individual owner/explicit insecure ACL, unchanged key, SYSTEM scheduled-task private-key read and matching public key. No SSH network connections.'
