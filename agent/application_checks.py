"""Opt-in application response checks, bounded and executed off the metrics loop."""
import concurrent.futures
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

_lock=threading.Lock();_busy=False;_next=0;_cached={'enabled':False,'revision':0,'items':[],'checked_at':None}


def validate_rules(rules):
    if not isinstance(rules,list) or len(rules)>6:raise ValueError('Максимум 6 проверок')
    found=set();clean=[]
    for rule in rules:
        if not isinstance(rule,dict) or set(rule)-{'id','name','kind','target','port','contains','database'}:raise ValueError('Неизвестные поля проверки')
        r={key:str(rule.get(key) or '').strip() for key in ('id','name','kind','target','contains','database')}
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,40}',r['id']) or r['id'] in found:raise ValueError('ID проверок должны быть уникальными')
        if not 1<=len(r['name'])<=100 or r['kind'] not in ('http','tcp','sql') or not 1<=len(r['target'])<=500 or len(r['contains'])>200 or len(r['database'])>128:raise ValueError('Недопустимая проверка')
        if any(ord(ch)<32 for ch in r['target']):raise ValueError('Недопустимый адрес')
        port=rule.get('port',0)
        if type(port) is not int or not 0<=port<=65535:raise ValueError('Недопустимый порт')
        r['port']=port
        if r['kind']=='http':
            url=urllib.parse.urlsplit(r['target'])
            try:valid_port=url.port
            except ValueError:raise ValueError('Недопустимый порт URL') from None
            if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.fragment:raise ValueError('Нужен HTTP(S) URL без пароля и фрагмента')
            if url.query:raise ValueError('Для проверки используйте URL без параметров и секретов')
        else:
            if not port or not re.fullmatch(r'[a-zA-Z0-9_.:\-]{1,255}',r['target']):raise ValueError('Нужны имя узла и порт')
        found.add(r['id']);clean.append(r)
    return clean


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


SQL_SCRIPT=r'''
$ErrorActionPreference='Stop'
$r=[Console]::In.ReadToEnd()|ConvertFrom-Json
$b=New-Object System.Data.SqlClient.SqlConnectionStringBuilder
$b.DataSource='tcp:'+$r.target+','+$r.port
$b.InitialCatalog=if($r.database){$r.database}else{'master'}
$b.IntegratedSecurity=$true;$b.ConnectTimeout=3;$b.Encrypt=$true;$b.TrustServerCertificate=$false
$c=New-Object System.Data.SqlClient.SqlConnection($b.ConnectionString)
try{$c.Open();$q=$c.CreateCommand();$q.CommandTimeout=3;$q.CommandText='SELECT 1';if($q.ExecuteScalar() -ne 1){exit 2}}finally{$c.Dispose()}
'''


def check(rule):
    started=time.monotonic();state='ok';message='Отвечает'
    try:
        if rule['kind']=='tcp':
            with socket.create_connection((rule['target'],rule['port']),timeout=3):pass
            message='Порт доступен; работа приложения не проверяется'
        elif rule['kind']=='http':
            # Ignore proxy environment for a check that must originate on this agent.
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
            with opener.open(urllib.request.Request(rule['target'],headers={'User-Agent':'ServersStatus-HealthCheck'}),timeout=3) as response:
                if response.status!=200:raise ValueError('unexpected status')
                if rule['contains']:
                    body=bytearray();deadline=time.monotonic()+3
                    while len(body)<65536 and time.monotonic()<deadline:
                        chunk=response.read1(min(4096,65536-len(body)))
                        if not chunk:break
                        body.extend(chunk)
                        if rule['contains'] in body.decode('utf-8',errors='replace'):break
                    if rule['contains'] not in body.decode('utf-8',errors='replace'):raise ValueError('response did not match')
            message='HTTP 200'+(' · содержимое подтверждено' if rule['contains'] else '')
        elif os.name!='nt':state='unsupported';message='SQL-проверка требует Windows и встроенную аутентификацию'
        else:
            executable=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
            subprocess.run([str(executable),'-NoProfile','-NonInteractive','-Command',SQL_SCRIPT],input=json.dumps(rule),capture_output=True,encoding='utf-8',timeout=8,check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            message='SELECT 1 выполнен'
    except Exception:
        state='failed';message='Нет ожидаемого ответа: проверьте приложение, сеть, права и сертификат'
    return {'id':rule['id'],'name':rule['name'],'kind':rule['kind'],'status':state,'message':message,'latency_ms':round((time.monotonic()-started)*1000,1)}


def _refresh(rules,revision):
    global _busy,_cached
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:items=list(pool.map(check,rules))
        data={'enabled':True,'revision':revision,'items':items,'checked_at':time.time()}
    finally:
        with _lock:
            if 'data' in locals():_cached=data
            _busy=False


def inventory(config):
    global _next,_busy,_cached
    enabled=config.get('allow_application_checks') is True
    if not enabled:return {'enabled':False,'revision':config.get('_checks_revision',0),'items':[],'checked_at':None}
    try:rules=validate_rules(config.get('application_checks',[]))
    except ValueError:return {'enabled':True,'revision':0,'items':[],'checked_at':None}
    revision=config.get('_checks_revision',0)
    with _lock:
        if (time.monotonic()>=_next or revision!=_cached['revision']) and not _busy:
            _next=time.monotonic()+60;_busy=True
            threading.Thread(target=_refresh,args=(rules,revision),daemon=True).start()
        return dict(_cached)


def load_cache(path):
    try:
        value=json.loads(Path(path).read_text(encoding='utf-8'))
        if type(value.get('revision')) is not int or value['revision']<0:raise ValueError('revision')
        return {'revision':value['revision'],'checks':validate_rules(value['checks'])}
    except (OSError,ValueError,TypeError,KeyError):return None


def save_cache(path,value):
    if not isinstance(value,dict) or type(value.get('revision')) is not int or value['revision']<0:raise ValueError('revision')
    data={'revision':value['revision'],'checks':validate_rules(value.get('checks'))}
    temp=Path(str(path)+'.new');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(path)
    return data
