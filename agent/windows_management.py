"""Narrow Windows Update and restart operations; no arbitrary remote shell."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from .remote_update import request
from urllib.parse import quote

_lock=threading.Lock()
_info={'status':'checking','history':[],'hotfixes':[]}
_next=0
_refreshing=False
_worker=False


def powershell(action,timeout=45):
    executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(executable),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_suffix('.ps1')),'-Action',action],capture_output=True,timeout=timeout,encoding='utf-8-sig',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('Windows Update operation failed; inspect Windows logs')
    return json.loads(result.stdout)


def reboot_state(registry=None):
    if registry is None:
        import winreg as registry
    reasons=[];unknown=False
    for path,label in [(r'SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending','Обслуживание компонентов Windows'),(r'SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired','Windows Update')]:
        try:
            with registry.OpenKey(registry.HKEY_LOCAL_MACHINE,path,0,registry.KEY_READ|registry.KEY_WOW64_64KEY):reasons.append(label)
        except FileNotFoundError:pass
        except OSError:unknown=True
    try:
        with registry.OpenKey(registry.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\Session Manager',0,registry.KEY_READ|registry.KEY_WOW64_64KEY) as key:
            value,_=registry.QueryValueEx(key,'PendingFileRenameOperations')
            if value:reasons.append('Ожидающие операции с файлами')
    except FileNotFoundError:pass
    except OSError:unknown=True
    return {'reboot_required':True if reasons else None if unknown else False,'reboot_reasons':reasons,'reboot_checked_at':time.time()}


def _refresh():
    global _info,_refreshing
    try:
        data=powershell('info')
        data.update(status='available' if 'available' in (data.get('history_status'),data.get('hotfix_status')) else 'unavailable',checked_at=time.time())
    except Exception:data={'status':'unavailable','history':[],'hotfixes':[],'checked_at':time.time()}
    with _lock:_info=data;_refreshing=False


def inventory(config):
    global _next,_refreshing
    if os.name!='nt':return None
    now=time.monotonic()
    with _lock:
        if now>=_next and not _refreshing:
            _next=now+900;_refreshing=True
            threading.Thread(target=_refresh,daemon=True).start()
        data=dict(_info)
    try:data.update(reboot_state())
    except Exception:data.update(reboot_required=None,reboot_reasons=[],reboot_checked_at=time.time())
    data['management_enabled']=config.get('allow_windows_management') is True
    return data


def endpoint(config):return '/api/windows/'+quote(config['agent_id'],safe='')


def acknowledge(config,result):
    with request(config,endpoint(config)+'/status',result) as response:response.read(4096)


def execute(action):
    if action=='scan':return powershell('scan',timeout=900)
    if action=='install':return powershell('install',timeout=7200)
    shutdown=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/shutdown.exe'
    if action=='reboot':args=['/r','/t','300','/d','p:2:17','/c','ServersStatus: planned restart in 5 minutes. Save your work.']
    elif action=='cancel_reboot':args=['/a']
    else:raise ValueError('Unsupported Windows action')
    subprocess.run([str(shutdown),*args],check=True,capture_output=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    return {}


def _save(path,value):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(path)


def handle(config,config_path):
    """One daemon worker, with durable at-most-once execution across restarts."""
    global _worker
    if os.name!='nt' or config.get('allow_windows_management') is not True:return
    with _lock:
        if _worker:return
        _worker=True
    threading.Thread(target=_handle,args=(config,config_path),daemon=True).start()


def _handle(config,config_path):
    global _worker,_next
    path=Path(str(config_path)+'.windows-command.json')
    try:
        if path.exists():
            prior=json.loads(path.read_text())
            if prior.get('pending'):
                if prior['status']=='running':prior.update(status='uncertain',result={})
                acknowledge(config,prior)
                prior['pending']=False;_save(path,prior)
        with request(config,endpoint(config)) as response:job=json.loads(response.read(16384)).get('job')
        if not job:return
        if path.exists() and job['id']<=json.loads(path.read_text()).get('id',0):return
        if job.get('action') not in ('scan','install','reboot','cancel_reboot') or type(job.get('id')) is not int or job.get('expires',0)<time.time():return
        result={'id':job['id'],'status':'running','result':{},'pending':True}
        _save(path,result)  # Never execute a command again after a service or power interruption.
        acknowledge(config,result)
        try:
            output=execute(job['action'])
            result.update(status='failed' if job['action']=='install' and output.get('failed',0)>0 else 'succeeded',result=output)
        except subprocess.TimeoutExpired:result.update(status='uncertain',result={})
        except Exception:result.update(status='failed',result={})
        _next=0
        _save(path,result);acknowledge(config,result)
        result['pending']=False;_save(path,result)
    except Exception:pass
    finally:
        with _lock:_worker=False
