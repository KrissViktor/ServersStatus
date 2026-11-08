$ErrorActionPreference='Stop'
$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__'))|ConvertFrom-Json
Add-Type -TypeDefinition @'
using System;using System.Runtime.InteropServices;
public class RdpWts {
[StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] public struct Info {
public uint State,SessionId,IncomingBytes,OutgoingBytes,IncomingFrames,OutgoingFrames,IncomingCompressedBytes,OutgoingCompressedBytes;
[MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)] public string Station;
[MarshalAs(UnmanagedType.ByValTStr,SizeConst=17)] public string Domain;
[MarshalAs(UnmanagedType.ByValTStr,SizeConst=21)] public string User;
public long ConnectTime,DisconnectTime,LastInputTime,LogonTime,CurrentTime;}
[DllImport("wtsapi32.dll",EntryPoint="WTSQuerySessionInformationW",SetLastError=true)] public static extern bool Query(IntPtr s,int id,int c,out IntPtr p,out int n);
[DllImport("wtsapi32.dll")] public static extern void WTSFreeMemory(IntPtr p);
[DllImport("wtsapi32.dll",SetLastError=true)] public static extern bool WTSDisconnectSession(IntPtr s,int id,bool wait);
[DllImport("wtsapi32.dll",SetLastError=true)] public static extern bool WTSLogoffSession(IntPtr s,int id,bool wait);
}
'@
$ptr=[IntPtr]::Zero;$n=0
if(![RdpWts]::Query([IntPtr]::Zero,$p.session_id,24,[ref]$ptr,[ref]$n)){throw 'Cannot query RDP session'}
try {
if($n -lt [Runtime.InteropServices.Marshal]::SizeOf([type][RdpWts+Info])){throw 'Incomplete RDP session information'}
$i=[Runtime.InteropServices.Marshal]::PtrToStructure($ptr,[type][RdpWts+Info])
} finally {[RdpWts]::WTSFreeMemory($ptr)}
if($i.SessionId -ne $p.session_id -or ($i.State -ne 0 -and $i.State -ne 4) -or ![string]::Equals($i.User,$p.username,[StringComparison]::OrdinalIgnoreCase) -or ![string]::Equals($i.Domain,$p.domain,[StringComparison]::OrdinalIgnoreCase) -or [Math]::Abs($i.LogonTime/1e7-11644473600-[double]$p.logon_at) -gt 0.01){throw 'RDP session changed; refresh the panel'}
if(![RdpWts]::Query([IntPtr]::Zero,$p.session_id,16,[ref]$ptr,[ref]$n)){throw 'Cannot query RDP protocol'}
try {if($n -lt 2 -or [Runtime.InteropServices.Marshal]::ReadInt16($ptr) -ne 2){throw 'Only RDP sessions are allowed'}} finally {[RdpWts]::WTSFreeMemory($ptr)}
if($p.action -eq 'disconnect'){
if($i.State -ne 0){throw 'RDP session is already disconnected'}
$ok=[RdpWts]::WTSDisconnectSession([IntPtr]::Zero,$p.session_id,$false)
} elseif($p.action -eq 'logoff'){$ok=[RdpWts]::WTSLogoffSession([IntPtr]::Zero,$p.session_id,$false)} else {throw 'Unsupported RDP action'}
if(!$ok){throw ('Windows rejected RDP action; error '+[Runtime.InteropServices.Marshal]::GetLastWin32Error())}
Write-Output ('Windows accepted RDP '+$p.action+' for session '+$p.session_id+'. Check the next agent report.')
