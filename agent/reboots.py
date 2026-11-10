"""Read-only, cached Windows System event evidence for boots and shutdowns."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

_lock=threading.Lock()
_busy=False
_next=0
_cached={'status':'checking','events':[],'checked_at':None}
SCRIPT=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$events=@()
try {
  $events=@(Get-WinEvent -FilterHashtable @{LogName='System';Id=1074,41,6008,6005,6006,12;StartTime=(Get-Date).AddDays(-30)} -MaxEvents 100 -ErrorAction Stop)
} catch {
  if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') {throw}
}
$items=@($events | Where-Object {
  ($_.Id -eq 1074 -and $_.ProviderName -eq 'User32') -or
  ($_.Id -eq 41 -and $_.ProviderName -eq 'Microsoft-Windows-Kernel-Power') -or
  ($_.Id -in 6008,6005,6006 -and $_.ProviderName -eq 'EventLog') -or
  ($_.Id -eq 12 -and $_.ProviderName -eq 'Microsoft-Windows-Kernel-General')
} | Select-Object -First 12 | ForEach-Object {
  $xml=[xml]$_.ToXml();$reason='';$process=''
  foreach($d in $xml.Event.EventData.Data) {
    if($d.Name -eq 'param4') {$reason=[string]$d.'#text'}
    if($d.Name -eq 'param1') {$process=[string]$d.'#text'}
  }
  $kind=switch($_.Id){1074 {'planned'} 41 {'unexpected'} 6008 {'unexpected'} 6005 {'boot'} 6006 {'shutdown'} 12 {'boot'}}
  $message=[string]$_.Message
  if($message.Length -gt 350) {$message=$message.Substring(0,350)}
  @{event_id=[int]$_.Id;record_id=[long]$_.RecordId;at=([DateTimeOffset]::new($_.TimeCreated.ToUniversalTime()).ToUnixTimeSeconds());source=$_.ProviderName;kind=$kind;message=$message;reason_code=$reason;process=$process}
})
@{events=$items}|ConvertTo-Json -Depth 4 -Compress
'''


def sanitize(data):
    if not isinstance(data,dict) or not isinstance(data.get('events'),list):raise ValueError('Invalid event inventory')
    events=[]
    providers={1074:'User32',41:'Microsoft-Windows-Kernel-Power',6008:'EventLog',6005:'EventLog',6006:'EventLog',12:'Microsoft-Windows-Kernel-General'}
    kinds={1074:'planned',41:'unexpected',6008:'unexpected',6005:'boot',6006:'shutdown',12:'boot'}
    for row in data['events'][:12]:
        if not isinstance(row,dict):continue
        code=row.get('event_id');at=row.get('at');record=row.get('record_id')
        if code not in providers or row.get('source')!=providers[code] or not isinstance(at,(int,float)) or not 0<=at<=time.time()+300 or not isinstance(record,int) or record<0:continue
        kind=kinds[code]
        if code==1074:
            try:
                reason=int(str(row.get('reason_code') or ''),0)
                if reason & 0xFFFF0000 == 0x80020000 and reason & 0xFFFF in (3,16,17,18):kind='update'
            except ValueError:pass
        events.append({'event_id':code,'record_id':record,'at':at,'source':providers[code],'kind':kind,
                       **{key:' '.join(str(row.get(key) or '').replace('\x00','').split())[:limit] for key,limit in [('message',350),('reason_code',80),('process',160)]}})
    return {'status':'available','events':events,'checked_at':time.time()}


def probe():
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-Command',SCRIPT],capture_output=True,encoding='utf-8-sig',errors='replace',timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('System event log is unavailable')
    return sanitize(json.loads(result.stdout))


def _refresh():
    global _cached,_busy
    try:data=probe()
    except (OSError,RuntimeError,ValueError,TypeError,subprocess.SubprocessError):data={'status':'unavailable','events':[],'checked_at':time.time()}
    with _lock:_cached=data;_busy=False


def inventory():
    global _next,_busy
    if os.name!='nt':return None
    with _lock:
        if time.monotonic()>=_next and not _busy:
            _next=time.monotonic()+900;_busy=True
            threading.Thread(target=_refresh,daemon=True).start()
        return dict(_cached)
