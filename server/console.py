"""Authenticated opt-in console queue, bounded results, no shell execution on Pi."""
import hmac
import json
import time
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ValidationError
from .events import record

SCHEMA='''CREATE TABLE IF NOT EXISTS console_jobs (id INTEGER PRIMARY KEY,agent TEXT,command TEXT,timeout INTEGER,status TEXT,created REAL,expires REAL,updated REAL,result TEXT);
CREATE INDEX IF NOT EXISTS console_jobs_agent ON console_jobs(agent,id);'''
STATES={'queued':'Ожидает агента','running':'Выполняется','succeeded':'Завершено','failed':'Ошибка','timeout':'Превышен лимит времени','uncertain':'Результат неизвестен — проверьте сервер','expired':'Срок команды истёк','reviewed':'Проверено администратором'}

class ConsoleInfo(BaseModel):
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
    id:int=Field(ge=1)
    status:str=Field(pattern='^(running|succeeded|failed|timeout|uncertain)$')
    output:str=Field(default='',max_length=16384)
    exit_code:int|None=None
    truncated:bool=False


def expire(c,agent):
    now=time.time()
    c.execute("UPDATE console_jobs SET status='expired',updated=? WHERE agent=? AND status='queued' AND expires<?",(now,agent,now))
    c.execute("UPDATE console_jobs SET status='uncertain',updated=? WHERE agent=? AND status='running' AND updated<?",(now,agent,now-180))


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
    def history(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
        with db() as c:
            expire(c,agent)
            row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
            if not row:raise HTTPException(404)
            data=json.loads(row['data']);info=data.get('console') or {}
            jobs=[{**dict(job),'result':json.loads(job['result'] or '{}'),'label':STATES[job['status']]} for job in c.execute('SELECT * FROM console_jobs WHERE agent=? ORDER BY id DESC LIMIT 20',(agent,))]
        return JSONResponse({'info':info,'online':time.time()-row['received']<=60,'jobs':jobs},headers={'Cache-Control':'no-store'})

    @app.post('/api/servers/{agent}/console')
    async def enqueue(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
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
            identifier=c.execute("INSERT INTO console_jobs(agent,command,timeout,status,created,expires,updated,result) VALUES (?,?,?,'queued',?,?,?,'{}')",(agent,data.command,data.timeout,now,now+90,now)).lastrowid
            record(c,agent,'console','Назначена команда консоли #'+str(identifier))
            c.execute("DELETE FROM console_jobs WHERE agent=? AND id NOT IN (SELECT id FROM console_jobs WHERE agent=? ORDER BY id DESC LIMIT 100) AND status NOT IN ('queued','running','uncertain')",(agent,agent))
        return {'ok':True,'id':identifier}

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
        with db() as c:
            c.execute('BEGIN IMMEDIATE');authorize(c,agent,request);expire(c,agent)
            row=c.execute('SELECT status FROM console_jobs WHERE id=? AND agent=?',(data.id,agent)).fetchone()
            if not row:raise HTTPException(404)
            if data.status=='running' and row['status']!='queued':raise HTTPException(409,'Команда принята или просрочена')
            allowed=(row['status']=='queued' and data.status in ('running','uncertain')) or (row['status'] in ('running','uncertain') and data.status!='running')
            if allowed:
                c.execute('UPDATE console_jobs SET status=?,updated=?,result=? WHERE id=?',(data.status,time.time(),data.model_dump_json(),data.id))
                record(c,agent,'console','Консоль #'+str(data.id)+': '+STATES[data.status])
        return {'ok':True}
