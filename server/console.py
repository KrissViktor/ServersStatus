"""Authenticated opt-in console queue, bounded results, no shell execution on Pi."""
import hmac
import json
import time
from datetime import datetime,timezone
import calendar
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ValidationError
from .events import record

SCHEMA='''CREATE TABLE IF NOT EXISTS console_jobs (id INTEGER PRIMARY KEY,agent TEXT,command TEXT,timeout INTEGER,status TEXT,created REAL,expires REAL,updated REAL,result TEXT);
CREATE INDEX IF NOT EXISTS console_jobs_agent ON console_jobs(agent,id);
CREATE INDEX IF NOT EXISTS console_jobs_created ON console_jobs(created);
CREATE TABLE IF NOT EXISTS console_job_sequence(id INTEGER PRIMARY KEY CHECK(id=1),value INTEGER);

CREATE TABLE IF NOT EXISTS console_controls (id INTEGER PRIMARY KEY AUTOINCREMENT,job INTEGER,agent TEXT,action TEXT,text TEXT,created REAL);
CREATE INDEX IF NOT EXISTS console_controls_job ON console_controls(job,id);'''
STATES={'queued':'Ожидает агента','running':'Выполняется','succeeded':'Завершено','failed':'Ошибка','cancelled':'Остановлено пользователем','timeout':'Превышен лимит времени','uncertain':'Результат неизвестен — проверьте сервер','expired':'Срок команды истёк','reviewed':'Проверено администратором'}

class ConsoleInfo(BaseModel):
    streaming:bool=False
    interactive_input:bool=False
    enabled:bool=False
    shell:str=Field(pattern='^(powershell|bash)$')
    identity:str=Field(max_length=255)

class Command(BaseModel):
    csrf:str=Field(max_length=200)
    confirmation:str=Field(max_length=64)
    command:str=Field(min_length=1,max_length=4000)
    timeout:int=Field(default=30,ge=1,le=60)
    review:bool=False

class Result(BaseModel):
    progress:bool=False
    id:int=Field(ge=1)
    status:str=Field(pattern='^(running|succeeded|failed|timeout|cancelled|uncertain)$')
    output:str=Field(default='',max_length=16384)
    exit_code:int|None=None
    truncated:bool=False


class Control(BaseModel):
    csrf:str=Field(max_length=200)
    confirmation:str=Field(max_length=64)
    action:str=Field(pattern='^(stdin|eof|cancel)$')
    text:str=Field(default='',max_length=1024)


def initialize_sequence(c):
    if not c.execute('SELECT 1 FROM console_job_sequence WHERE id=1').fetchone():
        c.execute('INSERT OR IGNORE INTO console_job_sequence SELECT 1,COALESCE(MAX(id),0) FROM console_jobs')


def history_cutoff(now):
    current=datetime.fromtimestamp(now,timezone.utc)
    index=current.year*12+current.month-1-6
    year,month=divmod(index,12);month+=1
    return current.replace(year=year,month=month,day=min(current.day,calendar.monthrange(year,month)[1])).timestamp()


def cleanup_history(c,now):
    cutoff=history_cutoff(now)
    c.execute('DELETE FROM console_controls WHERE job IN (SELECT id FROM console_jobs WHERE created<?)',(cutoff,))
    c.execute('DELETE FROM console_jobs WHERE created<?',(cutoff,))


def expire(c,agent):
    now=time.time()
    cleanup_history(c,now)
    c.execute("UPDATE console_jobs SET status='expired',updated=? WHERE agent=? AND status='queued' AND expires<?",(now,agent,now))
    c.execute("UPDATE console_jobs SET status='uncertain',updated=? WHERE agent=? AND status='running' AND updated<?",(now,agent,now-180))
    c.execute("DELETE FROM console_controls WHERE agent=? AND job IN (SELECT id FROM console_jobs WHERE agent=? AND status!='running')",(agent,agent))


async def read_body(request,limit):
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>limit:raise HTTPException(413)
    return body


def register(app,db,authenticated,csrf_token,digest):
    def authorize(c,agent,request):
        row=c.execute('SELECT token FROM agents WHERE id=?',(agent,)).fetchone()
        if not row or not hmac.compare_digest(row['token'],digest(request.headers.get('authorization','').removeprefix('Bearer '))):raise HTTPException(401)

    @app.get('/api/servers/{agent}/console')
    def history(agent:str,request:Request,archive:bool=False,before:int=0):
        if not authenticated(request):raise HTTPException(401)
        from .console_access import require
        require(request,db)
        if before<0:raise HTTPException(400)
        with db() as c:
            expire(c,agent)
            row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
            if not row:raise HTTPException(404)
            data=json.loads(row['data']);info=data.get('console') or {}
            cutoff=history_cutoff(time.time()) if archive else time.time()-3600
            rows=c.execute('SELECT * FROM console_jobs WHERE agent=? AND created>=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 101',(agent,cutoff,before,before)).fetchall()
            more=len(rows)>100
            jobs=[{**dict(job),'result':json.loads(job['result'] or '{}'),'label':STATES[job['status']]} for job in rows[:100]]
        return JSONResponse({'info':info,'online':time.time()-row['received']<=60,'jobs':jobs,'cutoff':cutoff,'more':more,'next':jobs[-1]['id'] if more else None},headers={'Cache-Control':'no-store'})

    @app.post('/api/servers/{agent}/console')
    async def enqueue(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
        from .console_access import require
        require(request,db)
        body=await read_body(request,32768)
        try:data=Command.model_validate_json(body)
        except ValidationError:raise HTTPException(422,'Проверьте команду и лимит времени')
        if not hmac.compare_digest(data.csrf.encode(),csrf_token(request).encode()):raise HTTPException(403)
        if data.confirmation!=agent:raise HTTPException(400,'Подтвердите целевой сервер')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');expire(c,agent)
            row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
            report=json.loads(row['data']) if row else {}
            if not row or time.time()-row['received']>60 or not (report.get('console') or {}).get('enabled') or 'console_v1' not in report.get('features',[]):raise HTTPException(409,'Агент недоступен или консоль выключена локально')
            if data.review:
                c.execute("UPDATE console_jobs SET status='reviewed',updated=? WHERE agent=? AND status='uncertain'",(time.time(),agent))
                record(c,agent,'console','Администратор подтвердил локальную проверку неизвестного результата консоли')
                return {'ok':True}
            if not data.command.strip():raise HTTPException(400,'Пустая команда')
            if c.execute("SELECT 1 FROM console_jobs WHERE agent=? AND status IN ('queued','running','uncertain')",(agent,)).fetchone() or c.execute("SELECT 1 FROM windows_commands WHERE agent=? AND status IN ('queued','running','uncertain')",(agent,)).fetchone() or c.execute("SELECT 1 FROM agent_update_jobs WHERE agent=? AND status IN ('queued','running')",(agent,)).fetchone():raise HTTPException(409,'Дождитесь предыдущей операции или проверьте неизвестный результат')
            now=time.time()
            highest=c.execute('SELECT MAX(value,COALESCE((SELECT MAX(id) FROM console_jobs),0)) FROM console_job_sequence WHERE id=1').fetchone()[0]+1
            c.execute('UPDATE console_job_sequence SET value=? WHERE id=1',(highest,))
            identifier=c.execute("INSERT INTO console_jobs(id,agent,command,timeout,status,created,expires,updated,result) VALUES (?,?,?,?,'queued',?,?,?,'{}')",(highest,agent,data.command,data.timeout,now,now+90,now)).lastrowid
            record(c,agent,'console','Назначена команда консоли #'+str(identifier))
            cleanup_history(c,now)
        return {'ok':True,'id':identifier}

    @app.post('/api/servers/{agent}/console/{job_id}/control')
    async def control(agent:str,job_id:int,request:Request):
        if not authenticated(request):raise HTTPException(401)
        from .console_access import require
        require(request,db)
        try:data=Control.model_validate_json(await read_body(request,8192))
        except ValidationError:raise HTTPException(422)
        if not hmac.compare_digest(data.csrf.encode(),csrf_token(request).encode()):raise HTTPException(403)
        if data.confirmation!=agent:raise HTTPException(400)
        with db() as c:
            c.execute('BEGIN IMMEDIATE');expire(c,agent)
            row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
            info=(json.loads(row['data']).get('console') or {}) if row else {}
            if not row or time.time()-row['received']>60 or not info.get('enabled') or not info.get('interactive_input'):raise HTTPException(409,'Агент недоступен или не поддерживает ввод')
            job=c.execute('SELECT status FROM console_jobs WHERE id=? AND agent=?',(job_id,agent)).fetchone()
            if not job or job['status']!='running':raise HTTPException(409,'Команда уже завершена или ещё не запущена')
            if data.action=='cancel':c.execute('DELETE FROM console_controls WHERE job=?',(job_id,))
            elif c.execute('SELECT count(*) FROM console_controls WHERE job=?',(job_id,)).fetchone()[0]>=8:raise HTTPException(429,'Дождитесь передачи предыдущих ответов')
            c.execute('INSERT INTO console_controls(job,agent,action,text,created) VALUES (?,?,?,?,?)',(job_id,agent,data.action,data.text if data.action=='stdin' else '',time.time()))
            if data.action=='cancel':record(c,agent,'console','Запрошена остановка команды #'+str(job_id))
        return {'ok':True}

    @app.get('/api/console/{agent}/{job_id}/controls')
    def controls(agent:str,job_id:int,request:Request,after:int=0):
        if after<0:raise HTTPException(400)
        with db() as c:
            c.execute('BEGIN IMMEDIATE');authorize(c,agent,request)
            job=c.execute('SELECT status FROM console_jobs WHERE id=? AND agent=?',(job_id,agent)).fetchone()
            if not job or job['status']!='running':raise HTTPException(409)
            # Delete only IDs this same agent previously fetched and acknowledged via its cursor.
            maximum=c.execute('SELECT max(id) FROM console_controls WHERE job=? AND agent=?',(job_id,agent)).fetchone()[0]
            if after and maximum and after>maximum:raise HTTPException(400)
            c.execute('DELETE FROM console_controls WHERE job=? AND agent=? AND id<=?',(job_id,agent,after))
            rows=c.execute('SELECT id,action,text FROM console_controls WHERE job=? AND agent=? AND id>? ORDER BY id LIMIT 8',(job_id,agent,after)).fetchall()
        return JSONResponse({'controls':[dict(row) for row in rows]},headers={'Cache-Control':'no-store'})

    @app.get('/api/console/{agent}')
    def pending(agent:str,request:Request):
        with db() as c:
            authorize(c,agent,request);expire(c,agent)
            row=c.execute("SELECT id,command,timeout,expires FROM console_jobs WHERE agent=? AND status='queued' ORDER BY id LIMIT 1",(agent,)).fetchone()
        return {'job':dict(row) if row else None}

    @app.post('/api/console/{agent}/status')
    async def status(agent:str,request:Request):
        with db() as c:authorize(c,agent,request)
        body=await read_body(request,65536)
        try:data=Result.model_validate_json(body)
        except ValidationError:raise HTTPException(422)
        if data.progress and data.status!='running':raise HTTPException(422,'Прогресс допустим только для работающей команды')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');authorize(c,agent,request);expire(c,agent)
            row=c.execute('SELECT status,result FROM console_jobs WHERE id=? AND agent=?',(data.id,agent)).fetchone()
            if not row:raise HTTPException(404)
            if data.status=='running' and ((not data.progress and row['status']!='queued') or (data.progress and row['status']!='running')):raise HTTPException(409,'Команда принята, завершена или просрочена')
            allowed=(row['status']=='running' and data.status=='running' and data.progress) or (row['status']=='queued' and data.status in ('running','uncertain')) or (row['status'] in ('running','uncertain') and data.status!='running')
            if allowed:
                if data.status=='uncertain' and not data.output:
                    previous=json.loads(row['result'] or '{}')
                    data.output=previous.get('output','');data.truncated=previous.get('truncated',False)
                c.execute('UPDATE console_jobs SET status=?,updated=?,result=? WHERE id=?',(data.status,time.time(),data.model_dump_json(),data.id))
                if data.status!='running':c.execute('DELETE FROM console_controls WHERE job=?',(data.id,))
                if not data.progress:record(c,agent,'console','Консоль #'+str(data.id)+': '+STATES[data.status])
        return {'ok':True}
