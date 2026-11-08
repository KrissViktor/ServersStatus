#Requires -Version 5.1
$ErrorActionPreference='Stop'
$root='C:\ProgramData\ServersStatusAI\tunnel'
$config=Get-Content "$root\connection.json" -Raw | ConvertFrom-Json
$mutex=New-Object Threading.Mutex($false,'Global\ServersStatusAI-Tunnel')
if(!$mutex.WaitOne(0)){exit 0}
function Write-TunnelLog([string]$Text){
    $path="$root\tunnel.log"
    if((Test-Path $path) -and (Get-Item $path).Length -gt 5MB){Remove-Item ($path+'.1') -ErrorAction SilentlyContinue;Move-Item $path ($path+'.1') -Force}
    [IO.File]::AppendAllText($path,([DateTime]::UtcNow.ToString('o')+' '+$Text+"`r`n"),(New-Object Text.UTF8Encoding($false)))
}
try{
    while($true){
        $process=$null
        try{
            $start=New-Object Diagnostics.ProcessStartInfo
            $start.FileName="$env:WINDIR\System32\OpenSSH\ssh.exe"
            $start.Arguments='-N -T -p '+[int]$config.Port+' -i "'+$root+'\id_ed25519" -o "UserKnownHostsFile='+$root+'\known_hosts" -o GlobalKnownHostsFile=NUL -o StrictHostKeyChecking=yes -o UpdateHostKeys=no -o IdentitiesOnly=yes -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o ConnectTimeout=15 -o LogLevel=ERROR -R 127.0.0.1:18091:127.0.0.1:8091 serversstatus-ai-tunnel@'+$config.Host
            $start.UseShellExecute=$false;$start.CreateNoWindow=$true;$start.RedirectStandardOutput=$true;$start.RedirectStandardError=$true
            $process=[Diagnostics.Process]::Start($start)
            $stdout=$process.StandardOutput.ReadToEndAsync();$stderr=$process.StandardError.ReadToEndAsync()
            Write-TunnelLog 'SSH client started; check localhost:18091/health on Raspberry Pi to confirm forwarding'
            $process.WaitForExit()
            Write-TunnelLog ('SSH exited '+$process.ExitCode+' '+$stdout.Result+' '+$stderr.Result)
        }catch{Write-TunnelLog ('SSH error: '+$_.Exception.Message)}
        finally{if($process){if(!$process.HasExited){$process.Kill()};$process.Dispose()}}
        Start-Sleep -Seconds 10
    }
}finally{$mutex.ReleaseMutex();$mutex.Dispose()}
