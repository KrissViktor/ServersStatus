"""Full current service inventories, separate from alert-monitored services."""
import hmac
import json
import time
import zlib
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ValidationError
from .console import read_body

SCHEMA='''CREATE TABLE IF NOT EXISTS latest_services(agent TEXT PRIMARY KEY,received REAL,data TEXT);
CREATE TABLE IF NOT EXISTS service_history(id INTEGER PRIMARY KEY,agent TEXT,received REAL,data BLOB);
CREATE INDEX IF NOT EXISTS service_history_agent_time ON service_history(agent,received,id);'''

class Service(BaseModel):
    name:str=Field(min_length=1,max_length=255)
    display_name:str=Field(default='',max_length=512)
    status:str=Field(default='unavailable',max_length=64)
    details:dict[str,str]=Field(default_factory=dict,max_length=80)

class Inventory(BaseModel):
    status:str=Field(pattern='^(available|unavailable)$')
    platform:str=Field(pattern='^(windows|linux)$')
    items:list[Service]=Field(default_factory=list,max_length=5000)
    total:int=Field(default=0,ge=0)
    unreadable:int=Field(default=0,ge=0)
    truncated:bool=False


def store(c,agent,payload,now=None):
    data=Inventory.model_validate(payload)
    if any(len(k)>100 or len(v)>4096 for item in data.items for k,v in item.details.items()):raise ValueError('Service detail too long')
    if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent,)).fetchone():return False
    received=time.time() if now is None else now
    encoded=data.model_dump_json()
    previous=c.execute('SELECT data FROM latest_services WHERE agent=?',(agent,)).fetchone()
    # Store a revision only when the inventory changes; timestamp is server reception,
    # never backdated into a report whose service inventory was not yet known.
    if not previous or previous['data']!=encoded or not c.execute('SELECT 1 FROM service_history WHERE agent=? LIMIT 1',(agent,)).fetchone():
        c.execute('INSERT INTO service_history(agent,received,data) VALUES (?,?,?)',(agent,received,zlib.compress(encoded.encode('utf-8'))))
    c.execute('INSERT INTO latest_services VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET received=excluded.received,data=excluded.data',(agent,received,encoded))
    return True


def register(app,db,authenticated,digest):
    def authorize(c,agent,request):
        row=c.execute('SELECT token FROM agents WHERE id=?',(agent,)).fetchone()
        if not row or not hmac.compare_digest(row['token'],digest(request.headers.get('authorization','').removeprefix('Bearer '))):raise HTTPException(401)
    @app.post('/api/processes/{agent}/services')
    async def receive(agent:str,request:Request):
        with db() as c:authorize(c,agent,request)
        try:data=Inventory.model_validate_json(await read_body(request,2*1024**2))
        except ValidationError:raise HTTPException(422,'Некорректный список служб')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');authorize(c,agent,request)
            try:store(c,agent,data)
            except ValueError:raise HTTPException(422,'Некорректные сведения службы')
        return {'ok':True}
    @app.get('/api/servers/{agent}/services')
    def listing(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
        with db() as c:
            if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent,)).fetchone():raise HTTPException(404)
            row=c.execute('SELECT * FROM latest_services WHERE agent=?',(agent,)).fetchone()
            report=c.execute('SELECT data FROM current_reports WHERE agent=?',(agent,)).fetchone()
            capable='service_inventory_v1' in json.loads(report['data']).get('features',[]) if report else False
        return JSONResponse({'capable':capable,'received':row['received'] if row else None,'inventory':json.loads(row['data']) if row else None},headers={'Cache-Control':'no-store'})
