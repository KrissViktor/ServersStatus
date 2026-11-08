#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$EngineTag = 'latest',
    [string]$ModelPath,
    [ValidatePattern('^[a-fA-F0-9]{64}$')][string]$ModelSha256,
    [ValidateRange(1,80)][int]$CpuPercent = 80,
    [ValidateRange(10,25)][int]$MemoryGB = 22,
    [ValidateRange(4,16)][int]$ReserveGB = 4,
    [ValidateRange(1,20)][int]$Threads = 12,
    [switch]$AllowOtherComputer
)
$ErrorActionPreference='Stop'
$root='C:\ProgramData\ServersStatusAI'
if(Get-NetTCPConnection -LocalPort 8091 -State Listen -ErrorAction SilentlyContinue){throw 'TCP port 8091 is already in use'}
if (!$AllowOtherComputer -and $env:COMPUTERNAME -ne 'WIN-CU629F0N7II') { throw 'Prepared for WIN-CU629F0N7II (windows-02). Use -AllowOtherComputer only intentionally.' }
if (Get-Service ServersStatusAI -ErrorAction SilentlyContinue) { throw 'Service already installed. Stop it and review existing settings; installation will not overwrite them.' }
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$ProgressPreference='SilentlyContinue'
New-Item -ItemType Directory -Force -Path $root,"$root\engine","$root\models","$root\logs" | Out-Null
# Account SIDs work on localized Windows. Service can read binaries/model/key,
# but only Administrators and SYSTEM may change code or settings.
& icacls.exe $root /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' '*S-1-5-19:(OI)(CI)RX' | Out-Null
if ($LASTEXITCODE) { throw 'Failed to restrict installation ACL' }
& icacls.exe "$root\logs" /grant:r '*S-1-5-19:(OI)(CI)M' | Out-Null
if ($LASTEXITCODE) { throw 'Failed to configure log ACL' }
$requiredDisk=if($ModelPath){(Get-Item -LiteralPath $ModelPath).Length+2GB}else{30GB}
if((Get-PSDrive C).Free -lt $requiredDisk){throw 'Not enough free space on C: for model download/copy and merge. Need up to 30 GB.'}
$headers=@{'User-Agent'='ServersStatus-AI-installer';'Accept'='application/vnd.github+json'}
$releaseUrl=if($EngineTag -eq 'latest'){'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest'}else{'https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/'+[Uri]::EscapeDataString($EngineTag)}
Write-Host 'Reading official llama.cpp release metadata...'
$release=Invoke-RestMethod -Uri $releaseUrl -Headers $headers
. (Join-Path $PSScriptRoot 'Release-Helpers.ps1')
$resolved=Resolve-CpuRelease -Release $release -Headers $headers
$release=$resolved.release
$asset=$resolved.asset
if($asset.browser_download_url -notlike 'https://github.com/ggml-org/llama.cpp/releases/download/*' -or $asset.digest -notmatch '^sha256:([a-fA-F0-9]{64})$'){throw 'Release lacks a SHA256 digest or has an unexpected download URL; refusing unverified executable'}
$engineHash=$Matches[1].ToLowerInvariant()
$zip="$root\engine.zip"
Write-Host ('Downloading CPU engine '+$release.tag_name+'...')
Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile ($zip+'.part')
if((Get-FileHash ($zip+'.part') -Algorithm SHA256).Hash.ToLowerInvariant() -ne $engineHash){throw 'Engine SHA256 mismatch'}
Move-Item ($zip+'.part') $zip -Force
# Reject archive traversal before extraction.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=[IO.Compression.ZipFile]::OpenRead($zip)
try{foreach($entry in $archive.Entries){$target=[IO.Path]::GetFullPath((Join-Path "$root\engine" $entry.FullName));if(!$target.StartsWith("$root\engine\",[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe ZIP path'}}}finally{$archive.Dispose()}
Expand-Archive -LiteralPath $zip -DestinationPath "$root\engine" -Force
$engines=@(Get-ChildItem "$root\engine" -Filter llama-server.exe -Recurse)
if($engines.Count -ne 1){throw 'Could not locate exactly one llama-server.exe'}
$engine=$engines[0].FullName
if($ModelPath){
    if(!$ModelSha256){throw 'Local GGUF requires -ModelSha256 from its trusted publisher'}
    $model=Get-Item -LiteralPath $ModelPath
    if($model.Extension -ne '.gguf'){throw 'Expected a GGUF model'}
    if((Get-FileHash $model.FullName -Algorithm SHA256).Hash -ne $ModelSha256){throw 'Model SHA256 mismatch'}
    Copy-Item -LiteralPath $model.FullName -Destination "$root\models\model.gguf" -Force
    $modelHash=$ModelSha256.ToLowerInvariant();$modelRevision='local-verified'
}else{
    Write-Host 'Reading official Qwen3-14B GGUF metadata...'
    $meta=Invoke-RestMethod -Uri 'https://huggingface.co/api/models/Qwen/Qwen3-14B-GGUF?blobs=true'
    if($meta.sha -notmatch '^[a-f0-9]{40}$'){throw 'Invalid model revision'}
    $files=@($meta.siblings | Where-Object { $_.rfilename -match '(^|/)qwen3-14b-q4_k_m\.gguf$' })
    $split=$false
    if(!$files.Count){$files=@($meta.siblings | Where-Object { $_.rfilename -match '(^|/)qwen3-14b-q4_k_m-\d{5}-of-\d{5}\.gguf$' } | Sort-Object rfilename);$split=$true}
    if(!$files.Count -or (!$split -and $files.Count -ne 1)){throw 'No unambiguous Q4_K_M GGUF found. Use -ModelPath -ModelSha256.'}
    if($split){
        $expected=0;$index=1
        foreach($file in $files){
            if($file.rfilename -notmatch '-(\d{5})-of-(\d{5})\.gguf$'){throw 'Invalid shard name'}
            if([int]$Matches[1] -ne $index -or ($expected -and $expected -ne [int]$Matches[2])){throw 'Incomplete model shards'}
            $expected=[int]$Matches[2];$index++
        }
        if($files.Count -ne $expected){throw 'Incomplete model shards'}
    }
    New-Item -ItemType Directory -Force -Path "$root\models\parts" | Out-Null
    $parts=@();$modelRevision=$meta.sha
    foreach($file in $files){
        if($file.lfs.sha256 -notmatch '^[a-fA-F0-9]{64}$'){throw 'Model file lacks trusted LFS SHA256'}
        $modelUrl='https://huggingface.co/Qwen/Qwen3-14B-GGUF/resolve/'+$meta.sha+'/'+(($file.rfilename.Split('/') | ForEach-Object {[Uri]::EscapeDataString($_)}) -join '/')+'?download=true'
        $target=Join-Path "$root\models\parts" ([IO.Path]::GetFileName($file.rfilename))
        Write-Host ('Downloading '+$file.rfilename+' (~'+[Math]::Round($file.lfs.size/1GB,1)+' GB)...')
        Invoke-WebRequest -UseBasicParsing -Uri $modelUrl -OutFile ($target+'.part')
        if((Get-FileHash ($target+'.part') -Algorithm SHA256).Hash -ne $file.lfs.sha256){throw 'Model SHA256 mismatch'}
        Move-Item ($target+'.part') $target -Force;$parts+=$target
    }
    if($split){
        $mergers=@(Get-ChildItem "$root\engine" -Filter llama-gguf-split.exe -Recurse)
        if($mergers.Count -ne 1){throw 'Verified shards downloaded, but engine has no GGUF merge tool. Use a single-file -ModelPath.'}
        $previousPreference=$ErrorActionPreference
        try{$ErrorActionPreference='Continue'; & $mergers[0].FullName --merge $parts[0] "$root\models\model.gguf"; $mergeExit=$LASTEXITCODE}finally{$ErrorActionPreference=$previousPreference}
        if($mergeExit){throw 'GGUF merge failed'}
    }else{Move-Item $parts[0] "$root\models\model.gguf" -Force}
    $modelHash=(Get-FileHash "$root\models\model.gguf" -Algorithm SHA256).Hash.ToLowerInvariant()
    # Input shards were verified before merging; record each trusted input hash.
    @($files | Select-Object rfilename,@{Name='sha256';Expression={$_.lfs.sha256}}) | ConvertTo-Json | Set-Content "$root\model-inputs.json" -Encoding UTF8

}
$previousPreference=$ErrorActionPreference
try{$ErrorActionPreference='Continue';$help=(& $engine --help 2>&1 | Out-String);$helpExit=$LASTEXITCODE}finally{$ErrorActionPreference=$previousPreference}
if($helpExit){throw 'Engine could not run --help. Check CPU compatibility and Microsoft VC++ x64 runtime.'}
$load=if($help -match '--load-mode'){'--load-mode none'}elseif($help -match '--no-mmap'){'--no-mmap'}else{throw 'Engine has no supported non-mmap mode; cannot apply the intended memory accounting'}
if($help -notmatch '--api-key-file'){throw 'Engine lacks API-key-file support'}
$reasoning=if($help -match '--reasoning '){'--reasoning off'}elseif($help -match '--chat-template-kwargs'){'--chat-template-kwargs "{\"enable_thinking\":false}"'}else{throw 'Engine lacks supported thinking configuration'}
$rng=[Security.Cryptography.RandomNumberGenerator]::Create();$bytes=New-Object byte[] 32;$rng.GetBytes($bytes);$rng.Dispose()
$key=[Convert]::ToBase64String($bytes)
[IO.File]::WriteAllText("$root\api-key.txt",$key,(New-Object Text.UTF8Encoding($false)))
$arguments='--model "'+$root+'\models\model.gguf" --host 127.0.0.1 --port 8091 --api-key-file "'+$root+'\api-key.txt" --ctx-size 8192 --parallel 1 --alias serversstatus-local --n-predict 512 --threads '+$Threads+' --threads-batch '+$Threads+' --n-gpu-layers 0 '+$load+' '+$reasoning+' --no-webui'
$settings=New-Object Xml.XmlDocument
$node=$settings.CreateElement('Settings');$settings.AppendChild($node)|Out-Null
foreach($pair in @(@('Executable',$engine),@('Arguments',$arguments),@('WorkingDirectory',$root),@('CpuPercent',$CpuPercent),@('MemoryMB',($MemoryGB*1024)),@('ReserveMB',($ReserveGB*1024)))){$element=$settings.CreateElement($pair[0]);$element.InnerText=[string]$pair[1];$node.AppendChild($element)|Out-Null}
$settings.Save("$root\settings.xml")
$csc="$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if(!(Test-Path $csc)){throw '.NET Framework 4.x C# compiler not found'}
& $csc /nologo /platform:x64 /target:exe "/out:$root\ServersStatusAI.exe" /reference:System.ServiceProcess.dll (Join-Path $PSScriptRoot 'AIService.cs')
if($LASTEXITCODE){throw 'Service compilation failed'}
Copy-Item (Join-Path $PSScriptRoot '*-AI.ps1') -Destination $root -Exclude Install-AI.ps1 -Force
@{engine_tag=$release.tag_name;engine_sha256=$engineHash;model_revision=$modelRevision;model_sha256=$modelHash;agent='windows-02';installed_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content "$root\versions.json" -Encoding UTF8
& sc.exe create ServersStatusAI binPath= ('"'+$root+'\ServersStatusAI.exe"') start= auto obj= 'NT AUTHORITY\LocalService' DisplayName= 'ServersStatus local AI (windows-02)' | Out-Null
if($LASTEXITCODE){throw 'Failed to register Windows service'}
& sc.exe failure ServersStatusAI reset= 3600 actions= restart/30000/restart/60000/restart/300000 | Out-Null
if($LASTEXITCODE){throw 'Failed to configure service recovery'}
& sc.exe failureflag ServersStatusAI 1 | Out-Null
Start-Service ServersStatusAI
Write-Host 'Installed. Loading can take several minutes. API: http://127.0.0.1:8091. Run Test-AI.ps1 for a local test.'
Write-Host 'No firewall rule was added. No portal/agent credentials were changed. API key remains in api-key.txt; do not send it in chat.'
