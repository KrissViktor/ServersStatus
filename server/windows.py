"""Typed Windows telemetry and narrowly scoped administrator commands."""
import hmac
import json
import time
from urllib.parse import parse_qs,quote
from fastapi import HTTPException,Request
from fastapi.responses import HTMLResponse,RedirectResponse
from pydantic import BaseModel,Field,ValidationError
from .dashboard import page,esc,size
from .events import record

SCHEMA='''CREATE TABLE IF NOT EXISTS windows_commands (id INTEGER PRIMARY KEY,agent TEXT,action TEXT,status TEXT,created REAL,expires REAL,updated REAL,result TEXT);
CREATE INDEX IF NOT EXISTS windows_commands_agent ON windows_commands(agent,id);'''
ACTIONS={'scan':'Проверить доступные обновления','install':'Установить обновления','reboot':'Перезагрузить через 5 минут','cancel_reboot':'Отменить перезагрузку'}
STATES={'queued':'Ожидает агента','running':'Выполняется','succeeded':'Команда выполнена','failed':'Ошибка','expired':'Срок команды истёк','uncertain':'Результат неизвестен — нужна проверка','reviewed':'Проверено администратором'}


class UpdateEvent(BaseModel):
    title:str=Field(max_length=500)
    installed_at:float|None=Field(default=None,ge=0,allow_inf_nan=False)
    result:int=Field(ge=0,le=5)

class Hotfix(BaseModel):
    kb:str=Field(max_length=100)
    description:str=Field(default='',max_length=255)
    installed_at:float|None=Field(default=None,ge=0,allow_inf_nan=False)

class WindowsInfo(BaseModel):
    status:str=Field(pattern='^(checking|available|unavailable)$')
    management_enabled:bool=False
    checked_at:float|None=Field(default=None,ge=0,allow_inf_nan=False)
    history_status:str=Field(default='unavailable',pattern='^(available|unavailable)$')
    hotfix_status:str=Field(default='unavailable',pattern='^(available|unavailable)$')
    history:list[UpdateEvent]=Field(default_factory=list,max_length=10)
    hotfixes:list[Hotfix]=Field(default_factory=list,max_length=10)
    reboot_required:bool|None=None
    reboot_reasons:list[str]=Field(default_factory=list,max_length=10)
    reboot_checked_at:float|None=Field(default=None,ge=0,allow_inf_nan=False)

class AvailableUpdate(BaseModel):
    title:str=Field(max_length=300)
    size_bytes:int=Field(ge=0)

class Result(BaseModel):
    count:int|None=Field(default=None,ge=0,le=100000)
    installed:int|None=Field(default=None,ge=0,le=100000)
    failed:int|None=Field(default=None,ge=0,le=100000)
    reboot_required:bool|None=None
    available:list[AvailableUpdate]=Field(default_factory=list,max_length=20)

class Acknowledgement(BaseModel):
    id:int=Field(ge=1)
    status:str=Field(pattern='^(running|succeeded|failed|uncertain)$')
    result:Result=Field(default_factory=Result)


def pending(c,agent):
    now=time.time()
    c.execute("UPDATE windows_commands SET status='expired',updated=? WHERE agent=? AND status='queued' AND expires<?",(now,agent,now))
    row=c.execute("SELECT id,action,expires FROM windows_commands WHERE agent=? AND status='queued' ORDER BY id LIMIT 1",(agent,)).fetchone()
    return dict(row) if row else None


def register(app,db,authenticated,csrf_token,digest):
    def authorize(c,agent,request):
        row=c.execute('SELECT token FROM agents WHERE id=?',(agent,)).fetchone()
        if not row or not hmac.compare_digest(row['token'],digest(request.headers.get('authorization','').removeprefix('Bearer '))):raise HTTPException(401)

    @app.get('/windows/{agent}',response_class=HTMLResponse)
    def control(agent:str,request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        with db() as c:
            pending(c,agent)
            row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
            if not row:raise HTTPException(404)
            data=json.loads(row['data']);windows=data.get('windows_updates') or {}
            jobs=c.execute('SELECT * FROM windows_commands WHERE agent=? ORDER BY id DESC LIMIT 15',(agent,)).fetchall()
        from .windows_ui import section,stamp
        content='<header class="topbar"><a href="/servers/'+esc(quote(agent,safe=''))+'">← Сервер</a></header><h1>Обновления и перезагрузка Windows</h1><h2>'+esc(agent)+'</h2>'
        content+='<div id="windows-live" data-refresh data-refresh-interval="10000">'+section(data)
        content+='<section class="server"><h2>История команд</h2>'
        for job in jobs:
            result=json.loads(job['result'] or '{}')
            label='Windows приняла команду перезагрузки с задержкой 5 минут' if job['action']=='reboot' and job['status']=='succeeded' else STATES[job['status']]
            content+=f'<p>#{job["id"]} · {stamp(job["created"])} · {esc(ACTIONS[job["action"]])} · {esc(label)}</p>'
            if result.get('count') is not None:content+=f'<p>Найдено: {result["count"]} · Установлено: {result.get("installed") if result.get("installed") is not None else "—"} · Ошибок: {result.get("failed") if result.get("failed") is not None else "—"}</p>'
            for update in result.get('available',[]):content+='<p>'+esc(update['title'])+' · '+size(update['size_bytes'])+'</p>'
        content+='</section></div>'
        if time.time()-row['received']>60:content+='<p class="notice">Нет свежего отчёта. Команды недоступны.</p>'
        elif not windows.get('management_enabled'):content+='<p class="notice">Управление выключено на агенте. Включите allow_windows_management в локальной конфигурации Windows и перезапустите службу. См. deploy/WINDOWS-MANAGEMENT.md.</p>'
        else:
            content+='<section class="server"><h2>Управление</h2><p>Установка использует настроенный источник Windows Update/WSUS, может принять условия лицензий обновлений и не запускает перезагрузку сама. Драйверы, обновления версии ОС и необязательные обновления исключены.</p><p class="notice">Перезагрузка через 5 минут: Windows может принудительно закрыть приложения. Предупредите RDP-пользователей и сохраните работу.</p>'
            choices=dict(ACTIONS)
            if any(job['status']=='uncertain' for job in jobs):choices['resolve']='Подтверждаю локальную проверку неизвестного результата'
            for action,label in choices.items():
                confirm=f'<label>Для подтверждения введите {esc(agent)}<input name="confirmation" required autocomplete="off"></label>' if action in ('install','reboot','resolve') else ''
                content+=f'<form method="post" action="/windows/{esc(quote(agent,safe=""))}"><input type="hidden" name="csrf" value="{esc(csrf_token(request))}"><input type="hidden" name="action" value="{action}">{confirm}<button>{esc(label)}</button></form>'
            content+='</section>'
        return HTMLResponse(page(content,refresh=True))

    @app.post('/windows/{agent}')
    async def enqueue(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
        body=await request.body()
        if len(body)>4096:raise HTTPException(413)
        form=parse_qs(body.decode());value=lambda key:form.get(key,[''])[0]
        if not hmac.compare_digest(value('csrf').encode(),csrf_token(request).encode()):raise HTTPException(403)
        action=value('action')
        if action not in (*ACTIONS,'resolve'):raise HTTPException(400)
        if action in ('install','reboot','resolve') and value('confirmation')!=agent:raise HTTPException(400,'Нужно подтвердить имя сервера')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');pending(c,agent)
            row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
            data=json.loads(row['data']) if row else {}
            if not row or time.time()-row['received']>60 or not (data.get('windows_updates') or {}).get('management_enabled') or 'windows_management_v1' not in data.get('features',[]):raise HTTPException(409,'Агент не готов к управлению')
            if action=='resolve':
                c.execute("UPDATE windows_commands SET status='reviewed',updated=? WHERE agent=? AND status='uncertain'",(time.time(),agent))
                record(c,agent,'management','Администратор подтвердил локальную проверку неизвестного результата Windows')
            else:
                if c.execute("SELECT 1 FROM agent_update_jobs WHERE agent=? AND status IN ('queued','running')",(agent,)).fetchone():raise HTTPException(409,'Дождитесь обновления агента')
                reboot=c.execute("SELECT action,updated FROM windows_commands WHERE agent=? AND action IN ('reboot','cancel_reboot') AND status='succeeded' ORDER BY id DESC LIMIT 1",(agent,)).fetchone()
                if reboot and reboot['action']=='reboot' and action in ('install','reboot') and row['received']-data.get('uptime_seconds',0)<reboot['updated']+5:
                    raise HTTPException(409,'Сначала отмените запланированную перезагрузку или дождитесь нового запуска Windows')
                if c.execute("SELECT 1 FROM windows_commands WHERE agent=? AND status IN ('queued','running','uncertain')",(agent,)).fetchone():raise HTTPException(409,'Предыдущая команда не завершена или требует проверки')
                now=time.time()
                c.execute("INSERT INTO windows_commands(agent,action,status,created,expires,updated,result) VALUES (?,?,'queued',?,?,?,'{}')",(agent,action,now,now+90,now))
                record(c,agent,'management','Назначена команда Windows: '+ACTIONS[action])
        return RedirectResponse('/windows/'+quote(agent,safe=''),303)

    @app.get('/api/windows/{agent}')
    def command(agent:str,request:Request):
        with db() as c:
            authorize(c,agent,request)
            return {'job':pending(c,agent)}

    @app.post('/api/windows/{agent}/status')
    async def status(agent:str,request:Request):
        with db() as c:authorize(c,agent,request)
        body=await request.body()
        if len(body)>32768:raise HTTPException(413)
        try:data=Acknowledgement.model_validate_json(body)
        except ValidationError:raise HTTPException(422)
        with db() as c:
            c.execute('BEGIN IMMEDIATE');authorize(c,agent,request)
            pending(c,agent)
            row=c.execute('SELECT * FROM windows_commands WHERE id=? AND agent=?',(data.id,agent)).fetchone()
            if not row:raise HTTPException(404)
            if data.status=='running' and row['status']!='queued':raise HTTPException(409,'Команда уже принята или срок истёк')
            allowed=(row['status']=='queued' and data.status in ('running','uncertain')) or (row['status']=='running' and data.status in ('succeeded','failed','uncertain'))
            if allowed:
                c.execute('UPDATE windows_commands SET status=?,updated=?,result=? WHERE id=?',(data.status,time.time(),data.result.model_dump_json(exclude_none=True),data.id))
                record(c,agent,'management',ACTIONS[row['action']]+': '+STATES[data.status])
        return {'ok':True}
