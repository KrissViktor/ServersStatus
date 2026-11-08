"""Opt-in, bounded remote commands with streaming output and line input under the agent's own account."""
import base64
import getpass
import json
import os
from pathlib import Path
import signal
import queue
import subprocess
import threading
import time
from urllib.parse import quote
from .remote_update import request

OUTPUT_LIMIT=16384
_lock=threading.Lock()
_busy=False


class ControlChannel(queue.Queue):
    def __init__(self):
        super().__init__(maxsize=8)
        self.cancelled=threading.Event()
    def put_nowait(self,item):
        if item.get('action')=='cancel':self.cancelled.set()
        else:super().put_nowait(item)


def info(config):
    try:
        if os.name=='nt':
            import win32api
            identity=win32api.GetUserName()
        else:identity=getpass.getuser()
    except Exception:identity='Не определён'
    return {'interactive_input':True,'streaming':True,'enabled':config.get('allow_remote_console') is True,'shell':'powershell' if os.name=='nt' else 'bash','identity':identity[:255]}


def execute(command,timeout,cwd,progress=None,controls=None):
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
            else:chunk=stream.read1(4096)
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
            script="[Console]::InputEncoding=New-Object Text.UTF8Encoding($false);$null=[Console]::ReadLine();[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false);$OutputEncoding=[Console]::OutputEncoding;$ErrorActionPreference='Stop';function global:Read-Host {param([string]$Prompt,[switch]$AsSecureString) if ($AsSecureString) {throw 'Secure input requires a terminal and is not supported'};if ($Prompt) {[Console]::Write($Prompt+': ');[Console]::Out.Flush()};[Console]::ReadLine()};try {\n"+command+"\nif ($LASTEXITCODE -is [int]) {exit $LASTEXITCODE}\n} catch {Write-Output $_.Exception.Message;exit 1}"
            args=[shell,'-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()]
            process=subprocess.Popen(args,cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            win32job.AssignProcessToJobObject(job,process._handle)
        else:
            process=subprocess.Popen(['/bin/bash','--noprofile','--norc','-c',command],cwd=cwd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        if os.name!='nt':os.set_blocking(process.stdout.fileno(),False)
        reader=threading.Thread(target=consume,args=(process.stdout,),daemon=True);reader.start()
        if os.name=='nt':process.stdin.write(b'go\n');process.stdin.flush()
        if controls is None:process.stdin.close()
        writer=None
        if controls is not None:
            if os.name!='nt':os.set_blocking(process.stdin.fileno(),False)
            def write_input():
                while not finished.is_set():
                    try:control=controls.get(timeout=.1)
                    except queue.Empty:continue
                    try:
                        if control['action']=='eof':process.stdin.close();return
                        payload=(control.get('text','')[:1024]+'\n').encode('utf-8')
                        while payload and not finished.is_set() and not controls.cancelled.is_set():
                            try:payload=payload[os.write(process.stdin.fileno(),payload):]
                            except BlockingIOError:finished.wait(.05)
                    except (BrokenPipeError,OSError,ValueError):return
            writer=threading.Thread(target=write_input,daemon=True);writer.start()
        timed_out=False;cancelled=False;exit_code=None;deadline=time.monotonic()+timeout
        next_progress=0;last_output=None
        while True:
            if controls is not None and controls.cancelled.is_set():cancelled=True;break
            remaining=deadline-time.monotonic()
            if remaining<=0:timed_out=True;break
            now=time.monotonic()
            if progress is not None and now>=next_progress:
                current=bytes(output).decode('utf-8',errors='replace')
                if (current,truncated)!=last_output:
                    progress({'status':'running','output':current,'exit_code':None,'truncated':truncated})
                    last_output=(current,truncated)
                next_progress=now+.5
            try:
                exit_code=process.wait(timeout=min(.1,remaining));break
            except subprocess.TimeoutExpired:pass
        # A command cannot leave background descendants running after its result.
        if os.name=='nt':
            win32api.CloseHandle(job);job=None
        else:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        process.wait(timeout=10);finished.set();reader.join(timeout=5)
        if writer is not None:writer.join(timeout=5)
        return {'status':'cancelled' if cancelled else 'timeout' if timed_out else 'succeeded' if exit_code==0 else 'failed','exit_code':exit_code,'output':output.decode('utf-8',errors='replace'),'truncated':truncated}
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
        updates=queue.Queue(maxsize=1);inputs=ControlChannel();upload_done=threading.Event()
        def uploader():
            cursor=0
            while not upload_done.is_set():
                try:
                    with request(config,endpoint(config)+'/'+str(job['id'])+'/controls?after='+str(cursor),timeout=3) as response:
                        received=json.loads(response.read(32768)).get('controls',[])
                    for control in received:
                        if control.get('id',0)<=cursor:continue
                        if control.get('action') not in ('stdin','eof','cancel') or not isinstance(control.get('text',''),str):continue
                        try:inputs.put_nowait(control)
                        except queue.Full:break
                        cursor=control['id']
                except Exception:pass
                try:value=updates.get(timeout=.3)
                except queue.Empty:continue
                try:
                    with request(config,endpoint(config)+'/status',value,timeout=3) as response:response.read(4096)
                except Exception:pass
        sender=threading.Thread(target=uploader,daemon=True);sender.start()
        def progress(value):
            payload={'id':job['id'],**value,'progress':True}
            try:updates.put_nowait(payload)
            except queue.Full:
                try:updates.get_nowait()
                except queue.Empty:pass
                try:updates.put_nowait(payload)
                except queue.Full:pass
        try:state.update(execute(job['command'],job['timeout'],str(Path(config_path).parent),progress=progress,controls=inputs))
        except Exception:state.update(status='failed',output='Не удалось запустить или завершить процесс команды. Проверьте права службы.',exit_code=None)
        finally:upload_done.set()
        save(path,state);ack(config,state);state['pending']=False;save(path,state)
    except Exception:pass
    finally:
        with _lock:_busy=False
