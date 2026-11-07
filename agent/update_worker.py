"""Root-only Linux update helper; its panel credentials are root-owned."""
import compileall
import fcntl
import json
import os
from pathlib import Path,PurePosixPath
import shutil
import subprocess
import tarfile
import time

from agent.remote_update import request,endpoint,validate,download,acknowledge

ROOT=Path('/opt/serversstatus-agent')
STATE=Path('/var/lib/serversstatus-agent-updater')


def extract(package,destination):
    size=0
    with tarfile.open(package,'r:gz') as archive:
        for member in archive:
            name=PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or member.issym() or member.islnk():
                raise ValueError('Unsafe archive member')
            if member.isdir():continue
            if not member.isfile():raise ValueError('Unsupported archive member')
            if name.parts[:1]!=('agent',):continue
            if len(name.parts)!=2 or not (name.suffix=='.py' or name.name in ('VERSION','requirements-linux.txt')):
                continue
            size+=member.size
            if size>50*1024**2:raise ValueError('Unpacked package too large')
            target=destination.joinpath(*name.parts)
            target.parent.mkdir(parents=True,exist_ok=True)
            with archive.extractfile(member) as source,target.open('wb') as out:
                shutil.copyfileobj(source,out)
    if not (destination/'agent/client.py').is_file():raise ValueError('Missing agent code')


def install(package,job,execute=subprocess.run,root=ROOT):
    current=root/'current'
    if not current.is_dir() or not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsupported installation directory')
    release=root/'releases'/str(job['id'])
    if release.exists():raise ValueError('Release directory already exists; inspect previous update')
    release.mkdir(parents=True)
    release.parent.chmod(0o755)
    extract(package,release)
    if (release/'agent/VERSION').read_text().strip()!=job['version']:
        raise ValueError('Package version mismatch')
    if (release/'agent/requirements-linux.txt').read_text().strip()!=(current/'agent/requirements-linux.txt').read_text().strip():
        raise ValueError('Dependency changes require manual installation')
    if not compileall.compile_dir(release/'agent',quiet=1):raise ValueError('Invalid Python package')
    # Service runs without root; root updater uses a restrictive umask.
    release.chmod(0o755)
    for item in release.rglob('*'):
        item.chmod(0o755 if item.is_dir() else 0o644)
    backup=root/('previous-'+str(job['id']))
    if backup.exists() or backup.is_symlink():raise ValueError('Backup already exists')
    execute(['systemctl','stop','serversstatus-agent'],check=True,timeout=60)
    try:
        current.rename(backup)
        current.symlink_to(release,target_is_directory=True)
        execute(['systemctl','start','serversstatus-agent'],check=True,timeout=60)
        time.sleep(5)
        execute(['systemctl','is-active','--quiet','serversstatus-agent'],check=True,timeout=10)
    except Exception:
        execute(['systemctl','stop','serversstatus-agent'],check=False,timeout=60)
        if backup.exists() or backup.is_symlink():
            if current.is_symlink():current.unlink()
            backup.rename(current)
        execute(['systemctl','start','serversstatus-agent'],check=True,timeout=60)
        raise


def main():
    if os.geteuid()!=0:raise SystemExit('Updater must run as root')
    config_path=Path('/etc/serversstatus-agent/update.json')
    stat=config_path.stat()
    if stat.st_uid!=0 or stat.st_mode&0o077:raise SystemExit('Update config must be root-owned mode 600')
    config=json.loads(config_path.read_text(encoding='utf-8-sig'))
    STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (STATE/'worker.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        status_file=STATE/'result.json'
        if status_file.exists():
            prior=json.loads(status_file.read_text())
            if prior.get('pending'):
                acknowledge(config,prior['job_id'],prior['status'],prior['message'])
                prior['pending']=False;status_file.write_text(json.dumps(prior))
        with request(config,endpoint(config)) as response:
            job=json.loads(response.read(65536)).get('job')
        if not job:return
        validate(job,'linux-source')
        if status_file.exists() and json.loads(status_file.read_text()).get('job_id')==job['id']:return
        acknowledge(config,job['id'],'running','Скачивание Linux-пакета')
        status_file.write_text(json.dumps({'job_id':job['id'],'status':'failed','message':'Предыдущая установка была прервана; проверьте службу перед повтором','pending':True}))
        try:
            package=STATE/'package.tar.gz'
            download(config,job,package)
            install(package,job)
            result={'job_id':job['id'],'status':'running','message':'Служба перезапущена; ожидается подтверждение версии','pending':True}
        except Exception:
            result={'job_id':job['id'],'status':'failed','message':'Установка не завершена; проверьте службу и журнал root-updater','pending':True}
        status_file.write_text(json.dumps(result))
        acknowledge(config,result['job_id'],result['status'],result['message'])
        result['pending']=False;status_file.write_text(json.dumps(result))


if __name__=='__main__':main()
