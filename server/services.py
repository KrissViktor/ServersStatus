"""Full current service inventories, separate from alert-monitored services."""
import hmac
import json
import time
from pathlib import Path
from urllib.parse import quote
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel,Field,ValidationError
from .console import read_body
from .dashboard import esc

SCHEMA='CREATE TABLE IF NOT EXISTS latest_services(agent TEXT PRIMARY KEY,received REAL,data TEXT);'
SCRIPT=Path(__file__).with_name('services.js').read_text(encoding='utf-8')

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
    c.execute('INSERT INTO latest_services VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET received=excluded.received,data=excluded.data',(agent,time.time() if now is None else now,data.model_dump_json()))
    return True


def section(agent):
    return '<section class="server all-services-panel" data-services-url="/api/servers/'+esc(quote(agent,safe=''))+'/services"><h2>Все службы</h2><p class="muted services-info" role="status">Загрузка списка служб…</p><div class="searchbar"><label>Поиск<input type="search" class="services-search" placeholder="Имя, описание, пользователь, путь…"></label><label>Состояние<select class="services-filter"><option value="all">Все</option><option value="running">🟢 Работает</option><option value="stopped">🔴 Остановлена</option><option value="paused">🟡 На паузе</option><option value="failed">🔴 Ошибка</option><option value="other">Остальные</option></select></label><button type="button" class="services-expand" aria-expanded="false">Показать все</button></div><div class="table-scroll services-table"><table class="metric-table"><thead><tr><th>Имя / описание</th><th>Состояние</th><th>PID</th><th>Автозапуск</th><th>Пользователь</th><th>Подробности</th></tr></thead><tbody class="services-rows"></tbody></table></div><p class="muted legend">Полный список обновляется агентом раз в минуту. Сведения доступны в пределах прав службы агента. Эти состояния показываются для справки; уведомления используют отдельный настроенный список контролируемых служб.</p></section><script>'+SCRIPT+'</script>'


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
