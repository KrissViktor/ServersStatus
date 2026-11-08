"""Read-only, bounded full Windows/systemd service inventory, uploaded once a minute."""
import json
import logging
import os
import subprocess
import threading
import time
from urllib.parse import quote
import psutil
from .remote_update import request

PROPERTIES=['Id','Names','Description','LoadState','ActiveState','SubState','UnitFileState','UnitFilePreset','Type','MainPID','ControlPID','User','Group','DynamicUser','ExecStart','ExecStop','FragmentPath','DropInPaths','WorkingDirectory','Restart','NRestarts','Result','ExecMainCode','ExecMainStatus','ActiveEnterTimestamp','InactiveEnterTimestamp','ExecMainStartTimestamp','ExecMainExitTimestamp','StateChangeTimestamp','MemoryCurrent','MemoryMax','CPUUsageNSec','TasksCurrent','ControlGroup','Requires','Wants','After','FreezerState']
_lock=threading.Lock();_busy=False;_next=0
MAX_BYTES=1900000


def compact(items,platform,total=None,unreadable=0,partial=False):
    result=[];used=0;seen=set()
    for entry in items:
        if entry['name'] in seen:continue
        seen.add(entry['name'])
        length=len(json.dumps(entry,ensure_ascii=False).encode('utf-8'))+2
        if len(result)>=5000 or used+length>MAX_BYTES:partial=True;continue
        result.append(entry);used+=length
    return {'status':'available','platform':platform,'items':result,'total':total if total is not None else len(seen),'unreadable':unreadable,'truncated':partial}


def windows(services=None):
    try:source=services if services is not None else psutil.win_service_iter()
    except (OSError,psutil.Error):return {'status':'unavailable','platform':'windows','items':[]}
    items=[];unreadable=0;total=0
    api=manager=None
    if services is None:
        try:
            import win32service as api
            manager=api.OpenSCManager(None,None,api.SC_MANAGER_CONNECT)
        except Exception:api=manager=None
    try:
        for service in source:
            total+=1
            try:
                fields=service.as_dict();name=fields.get('name') or service.name()
                description=getattr(service,'description',None)
                if callable(description):
                    try:fields['description']=description()
                    except (OSError,psutil.Error):pass
                if manager is not None:
                    handle=None
                    try:
                        handle=api.OpenService(manager,name,api.SERVICE_QUERY_CONFIG)
                        config=api.QueryServiceConfig(handle)
                        for key,value in zip(('service_type','config_start_type','error_control','config_binary_path','load_order_group','tag_id','dependencies','config_account','config_display_name'),config):fields[key]='; '.join(value) if isinstance(value,(list,tuple)) else value
                    except Exception:pass
                    finally:
                        if handle is not None:api.CloseServiceHandle(handle)
                details={str(k)[:100]:(str(v)[:4096] if v is not None else '') for k,v in fields.items() if k not in ('name','display_name','status')}
                items.append({'name':str(name)[:255],'display_name':str(fields.get('display_name') or name)[:512],'status':str(fields.get('status') or 'unavailable')[:64],'details':details})
            except (OSError,psutil.Error):
                unreadable+=1
                try:name=service.name()
                except Exception:continue
                items.append({'name':str(name)[:255],'display_name':str(name)[:512],'status':'unavailable','details':{'error':'Недостаточно прав или служба исчезла при чтении'}})
    except (OSError,psutil.Error):
        if manager is not None:api.CloseServiceHandle(manager)
        return compact(items,'windows',total,unreadable,True) if items else {'status':'unavailable','platform':'windows','items':[]}
    if manager is not None:api.CloseServiceHandle(manager)
    return compact(items,'windows',total,unreadable)


def linux(execute=subprocess.run):
    names=set();partial=False
    for command in [ ['systemctl','list-unit-files','--type=service','--no-legend','--no-pager'], ['systemctl','list-units','--type=service','--all','--plain','--no-legend','--no-pager'] ]:
        try:
            result=execute(command,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=8)
            if result.returncode:partial=True;continue
            names.update(line.split()[0] for line in result.stdout.splitlines() if line.split() and line.split()[0].endswith('.service') and not line.split()[0].startswith('-') and len(line.split()[0])<=255)
        except (OSError,subprocess.SubprocessError):partial=True
    if not names:return {'status':'unavailable' if partial else 'available','platform':'linux','items':[],'total':0}
    total=len(names);ordered=sorted(names)[:5000];items=[];unreadable=0
    for offset in range(0,len(ordered),100):
        batch=ordered[offset:offset+100];found={}
        try:
            result=execute(['systemctl','show','--no-pager','--all','--property='+','.join(PROPERTIES),'--',*batch],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=10)
            if result.returncode:partial=True
            for block in result.stdout.strip().split('\n\n'):
                fields=dict(line.split('=',1) for line in block.splitlines() if '=' in line)
                if fields.get('Id'):
                    for alias in [fields['Id']]+fields.get('Names','').split():found[alias]=fields
        except (OSError,subprocess.SubprocessError):partial=True
        for name in batch:
            fields=found.get(name)
            if fields is None:unreadable+=1;items.append({'name':name,'display_name':name,'status':'unavailable','details':{}});continue
            active=fields.get('ActiveState','');state={'active':'running','inactive':'stopped','failed':'failed','activating':'start_pending','deactivating':'stop_pending','reloading':'reloading'}.get(active,'unavailable')
            if fields.get('FreezerState')=='frozen':state='paused'
            if fields.get('LoadState') in ('not-found','error'):state='unavailable'
            details={key:str(value)[:4096] for key,value in fields.items() if key in PROPERTIES and key not in ('Id','Description')}
            items.append({'name':name,'display_name':fields.get('Description',name)[:512],'status':state,'details':details})
    return compact(items,'linux',total,unreadable,partial or total>len(ordered))


def collect():return windows() if os.name=='nt' else linux()


def handle(config=None,sink=None):
    global _busy,_next
    now=time.monotonic()
    with _lock:
        if _busy or now<_next:return
        _busy=True;_next=now+60
    def worker():
        global _busy,_next
        try:
            payload=collect()
            if sink is not None:sink(payload)
            else:
                with request(config,'/api/processes/'+quote(config['agent_id'],safe='')+'/services',payload) as response:response.read(4096)
        except Exception:
            logging.warning('Не удалось собрать или отправить список служб; повтор в следующем цикле обновления служб')
        finally:
            with _lock:_busy=False
    threading.Thread(target=worker,daemon=True).start()
