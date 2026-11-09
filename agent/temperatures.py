"""Available temperatures: Linux hwmon, bundled Windows helper and WMI fallback."""
import json
import math
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
import psutil

_lock=threading.Lock()
_busy=False
_next=0
_cached={'status':'checking','items':[],'sampled_at':None}
_native_state=None
_driver_attempted=False


def value(number):
    try:
        result=float(number)
        return round(result,1) if math.isfinite(result) and -100<=result<=200 else None
    except (ValueError,TypeError,OverflowError):return None


def sanitize(rows):
    items=[];seen=set()
    for row in rows[:512]:
        if not isinstance(row,dict):continue
        identifier=str(row.get('id') or '')[:255]
        if not identifier or identifier in seen:continue
        seen.add(identifier)
        item={k:str(row.get(k) or '')[:limit] for k,limit in [('label',255),('device',255),('component',80),('source',80)]}
        item.update(id=identifier,current=value(row.get('current')),high=value(row.get('high')),critical=value(row.get('critical')))
        items.append(item)
    return items


def linux_sensors():
    method=getattr(psutil,'sensors_temperatures',None)
    if method is None:return {'status':'unsupported','items':[],'sampled_at':time.time()}
    rows=[]
    try:
        for provider,sensors in (method(fahrenheit=False) or {}).items():
            for index,sensor in enumerate(sensors):
                rows.append({'id':str(provider)+':'+str(index),'label':sensor.label or 'Датчик '+str(index),'device':provider,'source':'Linux hwmon','component':'','current':sensor.current,'high':sensor.high,'critical':sensor.critical})
                if len(rows)>=512:break
            if len(rows)>=512:break
        items=sanitize(rows)
        return {'status':'available' if items else 'unavailable','items':items,'sampled_at':time.time()}
    except (OSError,RuntimeError,NotImplementedError,ValueError,TypeError,AttributeError,psutil.Error):return {'status':'unavailable','items':[],'sampled_at':time.time()}


def bundle_self_test():
    """Check the extracted helper/runtime without touching hardware or drivers."""
    root=Path(__file__).with_name('hardware-monitor-bin')
    for path in (root/'ServersStatusHardwareMonitor.exe',root/'LibreHardwareMonitorLib.dll',root/'PawnIO_setup.exe',Path(__file__).with_name('install_sensor_driver.ps1')):
        if not path.is_file():raise RuntimeError('Hardware bundle is incomplete')
    result=subprocess.run([str(root/'ServersStatusHardwareMonitor.exe'),'--self-test'],
        cwd=str(root),capture_output=True,timeout=20,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode or result.stdout.strip()!=b'[]':raise RuntimeError('Hardware bundle runtime failed')


def ensure_sensor_driver():
    global _driver_attempted
    if _driver_attempted:return
    _driver_attempted=True
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
            '-File',str(Path(__file__).with_name('install_sensor_driver.ps1'))],capture_output=True,
            timeout=80,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        logging.info('Temperature driver setup: %s', 'ready' if result.returncode==0 else 'failed; see Windows driver policy or existing installation')
        if result.returncode:logging.warning('Temperature driver setup details: %s',result.stderr.decode('utf-8',errors='replace')[-1500:])
    except Exception:
        logging.warning('Temperature driver setup unavailable; continuing without driver installation')


def native_probe():
    """Only execute the helper shipped with this agent, never search PATH or download."""
    helper=Path(__file__).with_name('hardware-monitor-bin')/'ServersStatusHardwareMonitor.exe'
    if os.environ.get('STATUS_AGENT_HARDWARE_TEMPERATURES','1')=='0' or not helper.is_file():return None
    ensure_sensor_driver()
    result=subprocess.run([str(helper)],cwd=str(helper.parent),capture_output=True,
        encoding='utf-8-sig',errors='replace',timeout=15,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Built-in hardware probe failed')
    if len(result.stdout)>1024*1024:raise ValueError('Sensor response too large')
    rows=json.loads(result.stdout)
    if not isinstance(rows,list):raise ValueError('Invalid sensor response')
    items=sanitize(rows)
    return items if any(item['current'] is not None for item in items) else None


def windows_probe():
    global _native_state
    try:
        items=native_probe()
        state='available' if items else 'unavailable'
    except Exception:
        items=None;state='failed'
    if state!=_native_state:
        logging.info('Built-in temperature sensors: %s%s',state,
            '; using WMI fallback' if not items else '')
        _native_state=state
    if items:return {'status':'available','items':items,'sampled_at':time.time()}

    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('temperature_sensors.ps1'))],capture_output=True,encoding='utf-8-sig',errors='replace',timeout=9,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Temperature probe failed')
    if len(result.stdout)>1024*1024:raise ValueError('Sensor response too large')
    rows=json.loads(result.stdout)
    if not isinstance(rows,list):raise ValueError('Invalid sensor response')
    items=sanitize(rows)
    return {'status':'available' if items else 'unavailable','items':items,'sampled_at':time.time()}


def collect_temperatures():
    if os.name!='nt':return linux_sensors()
    global _busy,_next,_cached
    def refresh():
        global _busy,_cached
        try:result=windows_probe()
        except Exception:result={'status':'unavailable','items':[],'sampled_at':time.time()}
        with _lock:_cached=result;_busy=False
    with _lock:
        now=time.time()
        if now>=_next and not _busy:
            _busy=True;_next=now+10
            try:threading.Thread(target=refresh,daemon=True).start()
            except RuntimeError:_busy=False;_cached={'status':'unavailable','items':[],'sampled_at':now}
        result=dict(_cached)
    if result.get('sampled_at') and now-result['sampled_at']>120:return {'status':'unavailable','items':[],'sampled_at':result['sampled_at']}
    return result
