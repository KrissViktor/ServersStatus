"""Only the latest process snapshot is kept, independently of metric history."""
import hmac
import time
from fastapi import HTTPException,Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ValidationError

MAX_BODY=2*1024**2
SCHEMA='CREATE TABLE IF NOT EXISTS latest_processes (agent TEXT PRIMARY KEY,received REAL,data TEXT);'


class Process(BaseModel):
    pid:int=Field(ge=0)
    name:str=Field(default='',max_length=255)
    username:str=Field(default='',max_length=255)
    cpu_percent:float|None=Field(default=None,ge=0,le=100,allow_inf_nan=False)
    memory_bytes:int|None=Field(default=None,ge=0)
    status:str=Field(default='',max_length=40)


class Snapshot(BaseModel):
    status:str=Field(pattern='^(available|unavailable)$')
    items:list[Process]=Field(default_factory=list,max_length=10000)
    total:int=Field(default=0,ge=0)
    unreadable:int=Field(default=0,ge=0)
    truncated:bool=False


def store(c,agent,data,now=None):
    data=Snapshot.model_validate(data)
    c.execute('INSERT INTO latest_processes VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET received=excluded.received,data=excluded.data',(agent,now or time.time(),data.model_dump_json()))


def register(app,db,authenticated,digest):
    @app.post('/api/processes/{agent}')
    async def receive(agent:str,request:Request):
        token=digest(request.headers.get('authorization','').removeprefix('Bearer '))
        with db() as c:
            row=c.execute('SELECT token FROM agents WHERE id=?',(agent,)).fetchone()
        if not row or not hmac.compare_digest(row['token'],token):raise HTTPException(401)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>MAX_BODY:raise HTTPException(413)
        try:data=Snapshot.model_validate_json(body)
        except ValidationError:raise HTTPException(422,'Некорректный список процессов')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            current=c.execute('SELECT token FROM agents WHERE id=?',(agent,)).fetchone()
            if not current or not hmac.compare_digest(current['token'],token):raise HTTPException(401)
            store(c,agent,data)
        return {'ok':True}

    @app.get('/api/servers/{agent}/processes')
    def current(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
        with db() as c:
            if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent,)).fetchone():raise HTTPException(404)
            row=c.execute('SELECT received,data FROM latest_processes WHERE agent=?',(agent,)).fetchone()
        import json
        return JSONResponse({'received':row['received'] if row else None,'snapshot':json.loads(row['data']) if row else None},headers={'Cache-Control':'no-store'})
