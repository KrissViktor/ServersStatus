# Validate PowerShell 5.1 syntax, Win32 layout and identity guards without
# disconnecting or logging off any real Windows session.
$ErrorActionPreference='Stop'
$source=Get-Content (Join-Path $PSScriptRoot '../server/rdp_command.ps1') -Raw -Encoding UTF8
$tokens=$null;$parseErrors=$null
$null=[Management.Automation.Language.Parser]::ParseInput($source,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw ($parseErrors|Out-String)}
$pattern="(?s)Add-Type -TypeDefinition @'\r?\n(.*?)\r?\n'@"
$match=[regex]::Match($source,$pattern)
if(!$match.Success){throw 'Native type definition not found'}
$native=$match.Groups[1].Value
Add-Type -TypeDefinition $native
if([Runtime.InteropServices.Marshal]::SizeOf([type][RdpWts+Info]) -ne 216){throw 'Unexpected WTSINFO ABI size'}
foreach($name in @('Query','WTSDisconnectSession','WTSLogoffSession','WTSFreeMemory')){
 if(!$([type][RdpWts]).GetMethod($name)){throw ('Missing native method '+$name)}
}
# Compile the same WTSINFO type with mock API methods for guard tests.
$mock=$native.Replace('class RdpWts','class RdpMock')
$mock=[regex]::Replace($mock,'(?m)^\[DllImport[^\r\n]*(\r?\n|$)','')
$methods=@'
public static Info Snapshot;
public static short Protocol=2;
public static int Disconnects,Logoffs;
public static bool ShortInfo=false;
public static bool Query(IntPtr server,int id,int kind,out IntPtr ptr,out int length){
 if(kind==24){length=Marshal.SizeOf(typeof(Info));ptr=Marshal.AllocHGlobal(length);Marshal.StructureToPtr(Snapshot,ptr,false);if(ShortInfo)length=1;return true;}
 length=2;ptr=Marshal.AllocHGlobal(2);Marshal.WriteInt16(ptr,Protocol);return true;}
public static void WTSFreeMemory(IntPtr ptr){Marshal.FreeHGlobal(ptr);}
public static bool WTSDisconnectSession(IntPtr server,int id,bool wait){Disconnects++;return true;}
public static bool WTSLogoffSession(IntPtr server,int id,bool wait){Logoffs++;return true;}
'@
$mock=$mock.Substring(0,$mock.LastIndexOf('}'))+$methods+'}'
Add-Type -TypeDefinition $mock
$body=[regex]::Replace($source,$pattern,'').Replace('RdpWts','RdpMock')
function Run-Case([string]$action,[bool]$expected,[string]$change){
 $snapshot=New-Object 'RdpMock+Info'
 $snapshot.State=0;$snapshot.SessionId=12;$snapshot.Station='RDP-Tcp#1';$snapshot.Domain='DOMAIN';$snapshot.User='test-user'
 $snapshot.LogonTime=[long]((1794000000.0+11644473600.0)*1e7)
 [RdpMock]::Protocol=2;[RdpMock]::Disconnects=0;[RdpMock]::Logoffs=0;[RdpMock]::ShortInfo=$false
 switch($change){
  'disconnected'{$snapshot.State=4}
  'new-user'{$snapshot.User='different-user'}
  'new-logon'{$snapshot.LogonTime+=100000000}
  'console'{[RdpMock]::Protocol=0}
  'short'{[RdpMock]::ShortInfo=$true}
 }
 [RdpMock]::Snapshot=$snapshot
 $payload=@{action=$action;session_id=12;username='test-user';domain='DOMAIN';logon_at=1794000000.0}|ConvertTo-Json -Compress
 $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload))
 $script=$body.Replace('__PAYLOAD__',$encoded)
 $succeeded=$false
 try {$null=& ([scriptblock]::Create($script));$succeeded=$true} catch {Write-Host ('Case '+$action+'/'+$change+': '+$_.Exception.Message)}
 $calls=[RdpMock]::Disconnects+[RdpMock]::Logoffs
 if($succeeded -ne $expected -or ($expected -and $calls -ne 1) -or (!$expected -and $calls -ne 0)){throw ('RDP guard case failed: '+$action+'/'+$change)}
 if($expected -and $action -eq 'disconnect' -and [RdpMock]::Disconnects -ne 1){throw 'Incorrect disconnect dispatch'}
 if($expected -and $action -eq 'logoff' -and [RdpMock]::Logoffs -ne 1){throw 'Incorrect logoff dispatch'}
}
Run-Case 'disconnect' $true ''
Run-Case 'logoff' $true 'disconnected'
Run-Case 'disconnect' $false 'disconnected'
Run-Case 'disconnect' $false 'new-user'
Run-Case 'logoff' $false 'new-logon'
Run-Case 'disconnect' $false 'console'
Run-Case 'logoff' $false 'short'
Run-Case 'unsupported' $false ''
Write-Host 'PowerShell syntax, native WTSINFO layout and 8 isolated RDP action cases passed.'
