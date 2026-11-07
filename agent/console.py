"""Opt-in, bounded, noninteractive remote commands under the agent's own account."""
import base64
import getpass
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
from urllib.parse import quote
from .remote_update import request

OUTPUT_LIMIT=16384
_lock=threading.Lock()
_busy=False


def info(config):
    try:
        if os.name=='nt':
            import win32api
            identity=win32api.GetUserName()
        else:identity=getpass.getuser()
    except Exception:identity='Не определён'
    return {'enabled':config.get('allow_remote_console') is True,'shell':'powershell' if os.name=='nt' else 'bash','identity':identity[:255]}


def execute(command,timeout,cwd):
    output=bytearray();truncated=False;job=None;process=None
    finished=threading.Event()
    def consume(stream):
        nonlocal truncated
        while True:
            if os.name!='nt':
                try:chunk=os.read(stream.fileno(),4096)
                except BlockingIOError:
                    if finished.is_set():break
                    finished.wait(.05)
                    continue
            else:chunk=stream.read(4096)
            if not chunk:break
            remaining=OUTPUT_LIMIT-len(output)
            output.extend(chunk[:max(0,remaining)])
            if len(chunk)>remaining:truncated=True
    try:
        if os.name=='nt':
            import win32job,win32api
            # pywin32 requires a string even for an unnamed Job Object.
            job=win32job.CreateJobObject(None,'')
            limits=win32job.QueryInformationJobObject(job,win32job.JobObjectExtendedLimitInformation)
            limits['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(job,win32job.JobObjectExtendedLimitInformation,limits)
            shell=str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')
            # Wait for the parent to assign the job before executing any user command.
            script="$null=[Console]::ReadLine();[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);$OutputEncoding=[Console]::OutputEncoding;$ErrorActionPreference='Stop';try {\n"+command+"\nif ($LASTEXITCODE -is [int]) {exit $LASTEXITCODE}\n} catch {Write-Output $_.Exception.Message;exit 1}"
            args=[shell,'-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()]
            process=subprocess.Popen(args,cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            win32job.AssignProcessToJobObject(job,process._handle)
        else:
            process=subprocess.Popen(['/bin/bash','--noprofile','--norc','-c',command],cwd=cwd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        if os.name!='nt':os.set_blocking(process.stdout.fileno(),False)
        reader=threading.Thread(target=consume,args=(process.stdout,),daemon=True);reader.start()
        if os.name=='nt':process.stdin.write(b'go\n');process.stdin.close()
        timed_out=False
        try:exit_code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:timed_out=True;exit_code=None
        # A command cannot leave background descendants running after its result.
        if os.name=='nt':
            win32api.CloseHandle(job);job=None
        else:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        process.wait(timeout=10);finished.set();reader.join(timeout=5)
        return {'status':'timeout' if timed_out else 'succeeded' if exit_code==0 else 'failed','exit_code':exit_code,'output':output.decode('utf-8',errors='replace'),'truncated':truncated}
    finally:
        if job is not None:
            import win32api
            win32api.CloseHandle(job)
        if process is not None:
            if process.poll() is None:
                if os.name!='nt':
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                else:process.kill()
                process.wait(timeout=10)
            if process.stdin and not process.stdin.closed:process.stdin.close()
            if process.stdout:process.stdout.close()


def endpoint(config):return '/api/console/'+quote(config['agent_id'],safe='')


def ack(config,data):
    with request(config,endpoint(config)+'/status',data) as response:response.read(4096)


def save(path,data):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data),encoding='utf-8');temporary.replace(path)


def handle(config,config_path):
    global _busy
    if config.get('allow_remote_console') is not True:return
    with _lock:
        if _busy:return
        _busy=True
    threading.Thread(target=worker,args=(config,config_path),daemon=True).start()


def worker(config,config_path):
    global _busy
    path=Path(str(config_path)+'.console-job.json')
    try:
        prior=json.loads(path.read_text()) if path.exists() else None
        if prior and prior.get('pending'):
            if prior['status']=='running':prior.update(status='uncertain',output='',exit_code=None,truncated=False)
            ack(config,prior);prior['pending']=False;save(path,prior)
        with request(config,endpoint(config)) as response:job=json.loads(response.read(32768)).get('job')
        if not isinstance(job,dict) or type(job.get('id')) is not int or job['id']<1:return
        if prior and job['id']<=prior['id']:return
        if type(job.get('timeout')) is not int or not 1<=job['timeout']<=60 or not isinstance(job.get('command'),str) or not 1<=len(job['command'])<=4000 or job.get('expires',0)<time.time():return
        state={'id':job['id'],'status':'running','exit_code':None,'output':'','truncated':False,'pending':True}
        save(path,state);ack(config,state)  # An expired/refused acceptance must never execute.
        try:state.update(execute(job['command'],job['timeout'],str(Path(config_path).parent)))
        except Exception:state.update(status='failed',output='Не удалось запустить или завершить процесс команды. Проверьте права службы.',exit_code=None)
        save(path,state);ack(config,state);state['pending']=False;save(path,state)
    except Exception:pass
    finally:
        with _lock:_busy=False
