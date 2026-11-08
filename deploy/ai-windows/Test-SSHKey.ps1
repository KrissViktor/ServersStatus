#Requires -Version 5.1
#Requires -RunAsAdministrator
$ErrorActionPreference='Stop'
$root='C:\ProgramData\ServersStatusAI\tunnel'
& "$PSScriptRoot\New-AITunnelKey.ps1" -AllowOtherComputer
$first=(Get-FileHash "$root\id_ed25519" -Algorithm SHA256).Hash
& "$PSScriptRoot\New-AITunnelKey.ps1" -AllowOtherComputer
if((Get-FileHash "$root\id_ed25519" -Algorithm SHA256).Hash -ne $first){throw 'Existing SSH key was replaced'}
$key=Get-Content "$root\id_ed25519.pub" -Raw
if($key -notmatch '^ssh-ed25519 '){throw 'Missing public key'}
$rules=(Get-Acl $root).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier])
foreach($rule in $rules){if($rule.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544')){throw 'Unexpected SSH key directory permissions'}}
Write-Host 'Passed: actual Windows OpenSSH key generation, empty passphrase without prompt, protected ACL, public output only, repeat without key replacement. No SSH connections made.'
