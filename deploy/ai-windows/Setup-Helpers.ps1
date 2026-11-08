#Requires -Version 5.1
function Test-VerifiedFile {
    param([string]$Path,[string]$Sha256)
    if($Sha256 -notmatch '^[a-fA-F0-9]{64}$'){throw 'Invalid trusted SHA256'}
    return (Test-Path -LiteralPath $Path -PathType Leaf) -and ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Sha256)
}
function Get-VerifiedDownload {
    param([string]$Uri,[string]$Path,[string]$Sha256,[long]$Size=0)
    if(Test-VerifiedFile -Path $Path -Sha256 $Sha256){Write-Host ('Using verified cached file: '+[IO.Path]::GetFileName($Path));return}
    $drive=[IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path)).TrimEnd('\').TrimEnd(':')
    if($Size -gt 0 -and (Get-PSDrive $drive).Free -lt ($Size+512MB)){throw ('Not enough disk space to download '+[IO.Path]::GetFileName($Path))}
    Write-Host ('Downloading '+[IO.Path]::GetFileName($Path)+'...')
    Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile ($Path+'.part')
    if(!(Test-VerifiedFile -Path ($Path+'.part') -Sha256 $Sha256)){throw 'Downloaded file SHA256 mismatch'}
    Move-Item -LiteralPath ($Path+'.part') -Destination $Path -Force
}
function Get-EngineHelp {
    param([string]$Executable,[string]$LogPath)
    $start=New-Object Diagnostics.ProcessStartInfo
    $start.FileName=$Executable;$start.Arguments='--help';$start.WorkingDirectory=[IO.Path]::GetDirectoryName($Executable)
    $start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
    $process=New-Object Diagnostics.Process;$process.StartInfo=$start
    try{
        if(!$process.Start()){throw 'Could not start engine'}
        $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
        if(!$process.WaitForExit(30000)){$process.Kill();throw 'Engine --help timed out'}
        $exitCode=$process.ExitCode
        $help=$stdout.Result+"`n"+$stderr.Result
        $hex=[BitConverter]::ToUInt32([BitConverter]::GetBytes([int]$exitCode),0).ToString('X8')
        $record='Executable: '+$Executable+"`r`nExit: "+$exitCode+' (0x'+$hex+")`r`n"+$help
        [IO.File]::WriteAllText($LogPath,$record.Substring(0,[Math]::Min($record.Length,131072)),(New-Object Text.UTF8Encoding($false)))
        if($exitCode -ne 0){
            $reason=switch($hex){
                'C0000135' {'Missing DLL dependency. Install Microsoft Visual C++ Redistributable x64: https://aka.ms/vs/17/release/vc_redist.x64.exe. If already installed, check engine DLL files.'}
                'C000001D' {'Unsupported CPU instruction. Check CPU/virtualization AVX support and the selected CPU build.'}
                'C000007B' {'Invalid executable/DLL architecture or damaged dependency. Use Windows x64 runtime and CPU x64 files.'}
                'C0000142' {'DLL initialization failed. Check Windows application events and runtime installation.'}
                default {'Engine returned an error; inspect engine-check.log for stdout/stderr.'}
            }
            throw ('Engine check failed: '+$exitCode+' (0x'+$hex+'). '+$reason+' Log: '+$LogPath)
        }
        if($help -notmatch '--api-key-file'){throw ('Engine help does not contain required API options. Log: '+$LogPath)}
        return $help
    }finally{$process.Dispose()}
}
