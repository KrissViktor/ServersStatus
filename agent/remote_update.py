"""Download only an assigned package from the configured HTTPS panel."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request

MAX_PACKAGE=200*1024**2
_WINDOWS_HELPERS={}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('Redirects are not allowed for agent updates')


def request(config,path,data=None,timeout=45):
    base=config['server_url'].rstrip('/')
    parsed=urllib.parse.urlsplit(base)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Invalid panel address')
    headers={'Authorization':'Bearer '+config['token']}
    if data is not None:
        headers['Content-Type']='application/json'
    call=urllib.request.Request(base+path,headers=headers,data=json.dumps(data,ensure_ascii=False).encode('utf-8') if data is not None else None)
    return urllib.request.build_opener(NoRedirect()).open(call,timeout=timeout)


def endpoint(config):
    return '/api/agent-update/'+urllib.parse.quote(config['agent_id'],safe='')


def acknowledge(config,job,status,message,error_code=None):
    body={'job_id':job,'status':status,'message':message}
    if error_code:body['error_code']=error_code
    with request(config,endpoint(config)+'/status',body) as response:
        response.read(4096)


def validate(job,platform):
    if not isinstance(job,dict) or not isinstance(job.get('id'),int) or job['id']<1:
        raise ValueError('Invalid update job')
    if job.get('platform')!=platform or not re.fullmatch(r'[a-f0-9]{64}',str(job.get('sha256',''))):
        raise ValueError('Invalid package platform or checksum')
    if not isinstance(job.get('size'),int) or not 1<=job['size']<=MAX_PACKAGE:
        raise ValueError('Invalid package size')
    if job.get('download_url'):
        from agent.github_releases import validate_manifest
        validate_manifest({**job,'schema':1},platform)
    return job


def download(config,job,destination):
    destination=Path(destination)
    temporary=destination.with_suffix('.partial')
    digest=hashlib.sha256();size=0
    try:
        if job.get('download_url'):
            from agent.github_releases import open_public
            source=open_public(job['download_url'])
        else:
            source=request(config,endpoint(config)+'/'+str(job['id'])+'/package')
        with source as response,temporary.open('wb') as file:
            while True:
                chunk=response.read(128*1024)
                if not chunk:break
                size+=len(chunk)
                if size>job['size'] or size>MAX_PACKAGE:raise ValueError('Package too large')
                digest.update(chunk);file.write(chunk)
        if size!=job['size'] or digest.hexdigest()!=job['sha256']:
            raise ValueError('Package checksum mismatch')
        temporary.replace(destination)
    finally:
        if temporary.exists():temporary.unlink()


def enabled():
    if os.name=='nt':
        expected=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'ServersStatus'/'ServersStatusService.exe'
        return getattr(sys,'frozen',False) and Path(sys.executable).resolve()==expected.resolve()
    return sys.platform.startswith('linux') and Path('/etc/serversstatus-agent/update.json').is_file()


def launch_windows(config,config_path,job):
    validate(job,'windows-x64')
    folder=Path(config_path).parent/'updates'/str(job['id'])
    folder.mkdir(parents=True,exist_ok=True)
    marker=folder/'requested'
    if marker.exists():
        child=_WINDOWS_HELPERS.get(job['id'])
        if child is not None and child.poll() not in (None,0):
            acknowledge(config,job['id'],'failed','PowerShell helper exited before installation',error_code='helper_startup')
        return
    acknowledge(config,job['id'],'running','Скачивание проверенного пакета')
    stage='download'
    try:
        package=folder/'ServersStatusService.exe'
        download(config,job,package)
        stage='helper_missing'
        script=Path(__file__).with_name('apply_update.ps1')
        target=folder/'apply_update.ps1'
        target.write_bytes(script.read_bytes())
        manifest=folder/'manifest.json'
        manifest.write_text(json.dumps({'job_id':job['id'],'sha256':job['sha256'],'config_path':str(Path(config_path).resolve())}),encoding='utf-8')
        stage='helper_launch'
        powershell=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        # Preserve failures that occur before the script can create update.log.
        with (folder/'helper-launch.log').open('ab') as launch_log:
            child=subprocess.Popen([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(target),'-Manifest',str(manifest)],
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True,stdin=subprocess.DEVNULL,stdout=launch_log,stderr=subprocess.STDOUT)
        _WINDOWS_HELPERS[job['id']]=child
        stage='helper_startup'
        try:
            code=child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        else:
            if code!=0:raise RuntimeError('PowerShell helper failed before installation')
        marker.write_text('launched')
    except Exception as error:
        logging.error('Agent update failed: stage=%s exception=%s winerror=%s',stage,type(error).__name__,getattr(error,'winerror',None))
        acknowledge(config,job['id'],'failed','Не удалось подготовить обновление; служба не заменена',error_code=stage)
        raise
