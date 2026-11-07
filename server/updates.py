"""Approved local packages and per-agent update jobs."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import parse_qs
from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, StreamingResponse
from .dashboard import page, esc

SCHEMA='''
CREATE TABLE IF NOT EXISTS update_packages (id INTEGER PRIMARY KEY,platform TEXT,version TEXT,sha256 TEXT UNIQUE,size INTEGER,path TEXT);
CREATE TABLE IF NOT EXISTS agent_update_jobs (id INTEGER PRIMARY KEY,agent TEXT,package INTEGER,status TEXT,message TEXT,created REAL,updated REAL);
CREATE INDEX IF NOT EXISTS update_jobs_agent_status ON agent_update_jobs(agent,status,created);
CREATE TABLE IF NOT EXISTS local_host (id INTEGER PRIMARY KEY CHECK(id=1),agent TEXT UNIQUE);
'''
PACKAGE_ROOT=Path(os.environ.get('STATUS_PACKAGES','/var/lib/serversstatus-packages'))


def pending(c,agent):
    now=time.time()
    c.execute("UPDATE agent_update_jobs SET status='failed',message='Нет подтверждения за 15 минут; проверьте службу перед повтором',updated=? WHERE agent=? AND status IN ('queued','running') AND created<?",(now,agent,now-900))
    row=c.execute("SELECT j.id,p.platform,p.version,p.sha256,p.size,g.url AS download_url FROM agent_update_jobs j JOIN update_packages p ON p.id=j.package LEFT JOIN github_packages g ON g.package=p.id WHERE j.agent=? AND j.status IN ('queued','running') ORDER BY j.id DESC LIMIT 1",(agent,)).fetchone()
    return dict(row) if row else None


def confirm(c,agent,data):
    job=pending(c,agent)
    if job and data.agent_version==job['version'] and data.agent_platform==job['platform']:
        c.execute("UPDATE agent_update_jobs SET status='applied',message='Версия подтверждена отчётом агента',updated=? WHERE id=?",(time.time(),job['id']))


def register(app,db,authenticated,csrf_token,digest):
    def authorize(c,agent,request):
        row=c.execute('SELECT token FROM agents WHERE id=?',(agent,)).fetchone()
        if not row or not hmac.compare_digest(row['token'],digest(request.headers.get('authorization','').removeprefix('Bearer '))):
            raise HTTPException(401)

    @app.get('/updates',response_class=HTMLResponse)
    def updates(request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        content='<header class="topbar"><a href="/">← Все серверы</a></header><h1>Обновление агентов</h1><p>Проверьте новые версии на GitHub и назначьте обновление выбранному агенту. Конфигурация и ключ сохраняются. Первое обновление старого агента выполняется вручную.</p>'
        content+=f'<section class="server"><h2>GitHub Releases</h2><p>Публичные сборки KrissViktor/ServersStatus. Установка запускается только по вашей команде.</p><form method="post" action="/updates/github/check"><input type="hidden" name="csrf" value="{esc(csrf_token(request))}"><button>Проверить GitHub</button></form></section>'
        with db() as c:
            packages=c.execute('SELECT * FROM update_packages ORDER BY id DESC').fetchall()
            for row in c.execute('SELECT a.id,r.data FROM agents a LEFT JOIN current_reports r ON r.agent=a.id').fetchall():
                data=json.loads(row['data'] or '{}'); platform=data.get('agent_platform'); agent=row['id']
                active=pending(c,agent)
                content+=f'<section class="server"><h2>{esc(agent)}</h2><p>Версия: {esc(data.get("agent_version") or "старый агент")} · {esc(platform or "платформа неизвестна")}</p>'
                if platform=='portal':
                    content+='<p>Локальный монитор обновляется вместе с кодом портала на Raspberry Pi.</p>'
                elif active:
                    content+='<p>Обновление уже назначено. Обновите страницу для проверки результата.</p>'
                elif 'remote_update_v1' in data.get('features',[]):
                    options=''.join(f'<option value="{p["id"]}">{esc(p["version"])}</option>' for p in packages if p['platform']==platform and p['version']!=data.get('agent_version'))
                    if options:content+=f'<form method="post" action="/updates/{esc(agent)}"><input type="hidden" name="csrf" value="{esc(csrf_token(request))}"><label>Версия<select name="package">{options}</select></label><label class="check"><input type="checkbox" required> Согласен на короткий перезапуск службы агента</label><button>Обновить агент</button></form>'
                    else:content+='<p>Подходящих новых пакетов пока нет.</p>'
                else:content+='<p>Удалённое обновление не включено. Выполните первоначальную настройку по инструкции.</p>'
                for job in c.execute('SELECT j.*,p.version FROM agent_update_jobs j JOIN update_packages p ON p.id=j.package WHERE agent=? ORDER BY j.id DESC LIMIT 5',(agent,)):
                    content+=f'<p>#{job["id"]} → {esc(job["version"])}: {esc({"queued":"В очереди","running":"Установка","applied":"Установлено","failed":"Ошибка"}.get(job["status"],job["status"]))} — {esc(job["message"])}</p>'
                content+='</section>'
        return HTMLResponse(page(content))

    @app.post('/updates/github/check')
    async def check_github(request:Request):
        if not authenticated(request):raise HTTPException(401)
        body=await request.body()
        if len(body)>4096:raise HTTPException(413)
        form=parse_qs(body.decode())
        if not hmac.compare_digest(form.get('csrf',[''])[0].encode(),csrf_token(request).encode()):raise HTTPException(403)
        import asyncio
        from .github_updates import sync
        try:await asyncio.to_thread(sync,db)
        except Exception:
            return HTMLResponse(page('<h1>Не удалось проверить GitHub</h1><p>Проверьте доступ к github.com и наличие успешных опубликованных сборок для Windows и Linux. Каталог не изменён.</p><a href="/updates">Вернуться к обновлениям</a>'),status_code=502)
        return RedirectResponse('/updates',303)

    @app.post('/updates/{agent}')
    async def enqueue(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
        body=await request.body()
        if len(body)>4096:raise HTTPException(413)
        form=parse_qs(body.decode())
        if not hmac.compare_digest(form.get('csrf',[''])[0].encode(),csrf_token(request).encode()):raise HTTPException(403)
        try:package=int(form.get('package',[''])[0])
        except ValueError:raise HTTPException(400)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
            p=c.execute('SELECT * FROM update_packages WHERE id=?',(package,)).fetchone()
            data=json.loads(row['data']) if row else {}
            if not p or not row or time.time()-row['received']>120 or 'remote_update_v1' not in data.get('features',[]) or data.get('agent_platform')!=p['platform'] or data.get('agent_version')==p['version']:
                raise HTTPException(400,'Агент не готов или пакет не подходит')
            if pending(c,agent):raise HTTPException(409,'Уже выполняется обновление')
            if c.execute("SELECT 1 FROM windows_commands WHERE agent=? AND status IN ('queued','running','uncertain')",(agent,)).fetchone():raise HTTPException(409,'Сначала завершите команду управления Windows')
            if c.execute("SELECT 1 FROM console_jobs WHERE agent=? AND status IN ('queued','running','uncertain')",(agent,)).fetchone():raise HTTPException(409,'Сначала завершите команду консоли')
            now=time.time()
            c.execute("INSERT INTO agent_update_jobs(agent,package,status,message,created,updated) VALUES (?,?,'queued','Ожидание агента',?,?)",(agent,package,now,now))
        return RedirectResponse('/updates',303)

    @app.get('/api/agent-update/{agent}')
    def job(agent:str,request:Request):
        with db() as c:
            authorize(c,agent,request)
            return {'job':pending(c,agent)}

    @app.get('/api/agent-update/{agent}/{job_id}/package')
    def package(agent:str,job_id:int,request:Request):
        with db() as c:
            authorize(c,agent,request)
            job=pending(c,agent)
            if not job or job['id']!=job_id:raise HTTPException(404)
            row=c.execute('SELECT path FROM update_packages WHERE sha256=?',(job['sha256'],)).fetchone()
        # No SQLite write lock is held while connecting to GitHub or streaming a binary.
        if job.get('download_url'):
            from agent.github_releases import open_public
            try:source=open_public(job['download_url'])
            except Exception:raise HTTPException(502,'GitHub недоступен')
            def stream():
                size=0
                try:
                    while True:
                        chunk=source.read(128*1024)
                        if not chunk:break
                        size+=len(chunk)
                        if size>job['size']:raise ValueError('Unexpected package size')
                        yield chunk
                    if size!=job['size']:raise ValueError('Incomplete package')
                finally:source.close()
            return StreamingResponse(stream(),media_type='application/octet-stream',headers={'Cache-Control':'no-store'})
        path=Path(row['path']).resolve()
        if not path.is_relative_to(PACKAGE_ROOT.resolve()) or not path.is_file():raise HTTPException(404)
        return FileResponse(path,media_type='application/octet-stream',filename='package')

    @app.post('/api/agent-update/{agent}/status')
    async def status(agent:str,request:Request):
        with db() as c:
            authorize(c,agent,request)
            raw=await request.body()
            if len(raw)>4096:raise HTTPException(413)
            try:data=json.loads(raw)
            except ValueError:raise HTTPException(400)
            if not isinstance(data,dict) or data.get('status') not in ('running','failed') or not isinstance(data.get('job_id'),int):raise HTTPException(400)
            # Never reflect raw exceptions, paths or download URLs from the agent.
            codes={'download':'Не удалось скачать пакет или проверить SHA256',
                   'helper_missing':'В сборке отсутствует помощник установки Windows',
                   'helper_launch':'Не удалось запустить помощник PowerShell',
                   'helper_startup':'PowerShell завершился с ошибкой до установки; проверьте helper-launch.log',
                   'verify':'Проверка файла перед установкой не пройдена',
                   'stop':'Не удалось остановить службу агента',
                   'wait_exit':'EXE остаётся занят процессом или недоступен на запись',
                   'backup':'Не удалось сохранить резервную копию EXE',
                   'replace':'Не удалось заменить EXE или проверить установленный файл',
                   'start':'Не удалось запустить обновлённую службу',
                   'health':'Обновлённая служба остановилась после запуска'}
            message='Установка выполняется; ожидается отчёт новой версии' if data['status']=='running' else codes.get(data.get('error_code') if isinstance(data.get('error_code'),str) else '','Агент сообщил об ошибке установки; проверьте журнал службы')
            if data['status']=='failed':
                if data.get('rollback')=='restored':message+='; предыдущий EXE восстановлен'
                elif data.get('rollback')=='failed':message+='; восстановление не завершено, проверьте службу локально'
                elif data.get('message')=='Не удалось скачать или проверить пакет; служба не заменена':message='Не удалось скачать пакет или проверить SHA256; EXE службы не заменён'
            c.execute("UPDATE agent_update_jobs SET status=?,message=?,updated=? WHERE id=? AND agent=? AND status IN ('queued','running')",(data['status'],message,time.time(),data['job_id'],agent))
        return {'ok':True}


def main():
    import argparse,shutil,tempfile
    from .app import db
    parser=argparse.ArgumentParser(description='Stage a trusted agent update package')
    parser.add_argument('platform',choices=['windows-x64','linux-source']);parser.add_argument('version');parser.add_argument('file',type=Path);parser.add_argument('sha256')
    args=parser.parse_args()
    if os.geteuid()!=0:parser.error('Run as root; package storage must not be writable by the web service')
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,80}',args.version) or not re.fullmatch(r'[a-fA-F0-9]{64}',args.sha256):parser.error('Invalid version or SHA256')
    PACKAGE_ROOT.mkdir(parents=True,exist_ok=True,mode=0o755)
    with tempfile.NamedTemporaryFile(dir=PACKAGE_ROOT,delete=False) as temporary:
        path=Path(temporary.name)
        try:
            with args.file.open('rb') as source:shutil.copyfileobj(source,temporary)
            temporary.flush()
            size=path.stat().st_size
            if not 1<=size<=200*1024**2:raise ValueError('Package exceeds size limit')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=args.sha256.lower():raise ValueError('SHA256 mismatch')
            target=PACKAGE_ROOT/args.sha256.lower();path.chmod(0o644);path.replace(target)
            with db() as c:c.execute('INSERT INTO update_packages(platform,version,sha256,size,path) VALUES (?,?,?,?,?)',(args.platform,args.version,args.sha256.lower(),size,str(target)))
        finally:path.unlink(missing_ok=True)
    print('Package staged:',args.version)

if __name__=='__main__':main()
