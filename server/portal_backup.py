"""Local SQLite online backups, verified before being recorded as successful."""
from datetime import datetime,timezone
from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

SCHEMA='''CREATE TABLE IF NOT EXISTS portal_backup_runs(id INTEGER PRIMARY KEY,started REAL NOT NULL,finished REAL,status TEXT NOT NULL,path TEXT,bytes INTEGER,sha256 TEXT,error TEXT);
CREATE INDEX IF NOT EXISTS portal_backup_runs_time ON portal_backup_runs(started);
CREATE TABLE IF NOT EXISTS portal_task_state(name TEXT PRIMARY KEY,checked REAL NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL);'''


def note(c,name,status='ok',detail='',now=None):
    c.execute('CREATE TABLE IF NOT EXISTS portal_task_state(name TEXT PRIMARY KEY,checked REAL NOT NULL,status TEXT NOT NULL,detail TEXT NOT NULL)')
    c.execute('INSERT INTO portal_task_state VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET checked=excluded.checked,status=excluded.status,detail=excluded.detail',(name,time.time() if now is None else now,status,detail[:300]))


def begin(db,now=None):
    now=time.time() if now is None else now
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM portal_backup_runs WHERE status='running' AND started>?",(now-600,)).fetchone():return None
        c.execute("UPDATE portal_backup_runs SET status='failed',finished=?,error='Процесс прерван или превысил время ожидания' WHERE status='running'",(now,))
        return c.execute("INSERT INTO portal_backup_runs(started,status) VALUES (?,'running')",(now,)).lastrowid


def execute(db,db_path,run_id,directory=None):
    partial=None
    try:
        source=Path(db_path).resolve()
        if not source.is_file():raise FileNotFoundError('Database file missing')
        folder=Path(directory or os.environ.get('STATUS_BACKUP_DIR') or source.parent/'backups')
        folder.mkdir(parents=True,exist_ok=True,mode=0o700)
        filename='serversstatus-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.sqlite3'
        target=folder/filename;partial=folder/(filename+'.partial')
        fd=os.open(partial,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        deadline=time.monotonic()+300
        def progress(status,remaining,total):
            if time.monotonic()>deadline:raise TimeoutError('Backup deadline exceeded')
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True,timeout=10)) as src:
            dest=sqlite3.connect(str(partial),timeout=10)
            try:
                src.backup(dest,pages=256,progress=progress,sleep=.05)
                dest.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
                if dest.execute('PRAGMA quick_check').fetchall()!=[('ok',)]:raise ValueError('Backup integrity check failed')
            finally:dest.close()
        digest=hashlib.sha256()
        with partial.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                if time.monotonic()>deadline:raise TimeoutError('Backup verification deadline exceeded')
                digest.update(chunk)
            os.fsync(stream.fileno())
        partial.replace(target);partial=None
        with db() as c:c.execute("UPDATE portal_backup_runs SET status='succeeded',finished=?,path=?,bytes=?,sha256=?,error=NULL WHERE id=?",(time.time(),str(target.resolve()),target.stat().st_size,digest.hexdigest(),run_id))
        return True
    except Exception as error:
        with db() as c:c.execute("UPDATE portal_backup_runs SET status='failed',finished=?,error=? WHERE id=?",(time.time(),'Не удалось создать или проверить копию ('+type(error).__name__+'). Проверьте свободное место и права каталога.',run_id))
        return False
    finally:
        if partial is not None:
            try:partial.unlink(missing_ok=True)
            except OSError:pass


def launch(db,db_path):
    run=begin(db)
    if run is None:return False
    try:threading.Thread(target=execute,args=(db,db_path,run),daemon=True).start()
    except Exception:
        with db() as c:c.execute("UPDATE portal_backup_runs SET status='failed',finished=?,error='Не удалось запустить резервное копирование' WHERE id=?",(time.time(),run))
        raise
    return True


def main():
    import argparse
    from .app import db,DB
    parser=argparse.ArgumentParser(description='Create a verified local SQLite backup')
    parser.add_argument('--directory',help='Destination directory; default STATUS_BACKUP_DIR or backups next to database')
    args=parser.parse_args();run=begin(db)
    if run is None:raise SystemExit('Резервное копирование уже выполняется')
    if not execute(db,DB,run,args.directory):raise SystemExit('Резервная копия не создана. Состояние сохранено в портале.')
    print('Резервная копия создана и проверена; результат доступен в контроле портала.')


if __name__=='__main__':main()
