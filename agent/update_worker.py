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

from agent.remote_update import request,endpoint,validate,download,acknowledge,progress

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


class UpdateFailure(RuntimeError):
    def __init__(self,stage,rollback,error_code=None):
        super().__init__('Agent update failed: '+stage+'; rollback='+rollback)
        self.stage=stage;self.rollback=rollback;self.error_code=error_code or stage


def install(package,job,execute=subprocess.run,root=ROOT,report_stage=None):
    current=root/'current';backup=root/('previous-'+str(job['id']))
    stage='prepare';code='prepare';stopped=False
    def notify(phase):
        if report_stage:
            try:report_stage(stage,phase)
            except Exception:pass  # Telemetry cannot change the installation outcome.
    try:
        notify('running')
        if not current.is_dir() or not current.resolve().is_relative_to(root.resolve()):raise ValueError('Unsupported installation directory')
        release=root/'releases'/str(job['id'])
        if release.exists():raise ValueError('Release directory already exists; inspect previous update')
        release.mkdir(parents=True);release.parent.chmod(0o755)
        code='archive_invalid';extract(package,release)
        code='version_mismatch'
        if (release/'agent/VERSION').read_text().strip()!=job['version']:raise ValueError('Package version mismatch')
        code='dependency_changed'
        if (release/'agent/requirements-linux.txt').read_text().strip()!=(current/'agent/requirements-linux.txt').read_text().strip():raise ValueError('Dependency changes require manual installation')
        code='python_invalid'
        if not compileall.compile_dir(release/'agent',quiet=1):raise ValueError('Invalid Python package')
        code='permissions'
        release.chmod(0o755)
        for item in release.rglob('*'):item.chmod(0o755 if item.is_dir() else 0o644)
        code='backup_exists'
        if backup.exists() or backup.is_symlink():raise ValueError('Backup already exists')
        notify('completed')
        stage='stop';notify('running');stopped=True
        execute(['systemctl','stop','serversstatus-agent'],check=True,timeout=60);notify('completed')
        stage='backup';notify('running');current.rename(backup);notify('completed')
        stage='replace';notify('running');current.symlink_to(release,target_is_directory=True);notify('completed')
        stage='start';notify('running');execute(['systemctl','start','serversstatus-agent'],check=True,timeout=60);notify('completed')
        stage='health';notify('running');time.sleep(5)
        execute(['systemctl','is-active','--quiet','serversstatus-agent'],check=True,timeout=10);notify('completed')
        stage='awaiting_version';notify('running')
    except Exception as error:
        rollback='not_needed'
        if stopped:
            try:
                execute(['systemctl','stop','serversstatus-agent'],check=False,timeout=60)
                if backup.exists() or backup.is_symlink():
                    if current.is_symlink():current.unlink()
                    backup.rename(current)
                execute(['systemctl','start','serversstatus-agent'],check=True,timeout=60)
                execute(['systemctl','is-active','--quiet','serversstatus-agent'],check=True,timeout=10)
                rollback='restored'
            except Exception:rollback='failed'
        raise UpdateFailure(stage,rollback,code if stage=='prepare' else stage) from error


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
                acknowledge(config,prior['job_id'],prior['status'],prior['message'],error_code=prior.get('error_code'),stage=prior.get('stage'),rollback=prior.get('rollback'))
                prior['pending']=False;status_file.write_text(json.dumps(prior))
        with request(config,endpoint(config)) as response:
            job=json.loads(response.read(65536)).get('job')
        if not job:return
        validate(job,'linux-source')
        if status_file.exists() and json.loads(status_file.read_text()).get('job_id')==job['id']:return
        acknowledge(config,job['id'],'running','Скачивание Linux-пакета',stage='download',stage_state='running')
        status_file.write_text(json.dumps({'job_id':job['id'],'status':'failed','message':'Предыдущая установка была прервана; проверьте службу перед повтором','pending':True}))
        try:
            package=STATE/'package.tar.gz'
            download(config,job,package)
            progress(config,job['id'],'download','completed')
            progress(config,job['id'],'verify','completed')
            telemetry=[True]
            def report_stage(stage,phase):
                if telemetry[0]:telemetry[0]=progress(config,job['id'],stage,phase)
            install(package,job,report_stage=report_stage)
            result={'job_id':job['id'],'status':'running','message':'Служба перезапущена; ожидается подтверждение версии','pending':True}
        except Exception as error:
            result={'job_id':job['id'],'status':'failed','message':'Установка не завершена; проверьте службу и журнал root-updater','pending':True,'stage':getattr(error,'stage','download'),'error_code':getattr(error,'error_code','download'),'rollback':getattr(error,'rollback','not_needed')}
        status_file.write_text(json.dumps(result))
        acknowledge(config,result['job_id'],result['status'],result['message'],error_code=result.get('error_code'),stage=result.get('stage'),rollback=result.get('rollback'))
        result['pending']=False;status_file.write_text(json.dumps(result))


if __name__=='__main__':main()
