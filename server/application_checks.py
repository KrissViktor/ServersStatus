import json
import time
from urllib.parse import quote,parse_qs
from fastapi import HTTPException,Request
from fastapi.responses import HTMLResponse,RedirectResponse
from pydantic import BaseModel,Field
from agent.application_checks import validate_rules

SCHEMA='CREATE TABLE IF NOT EXISTS application_check_config(agent TEXT PRIMARY KEY,revision INTEGER NOT NULL,data TEXT NOT NULL);'


class CheckResult(BaseModel):
    id:str=Field(max_length=40)
    name:str=Field(max_length=100)
    kind:str=Field(pattern='^(http|tcp|sql)$')
    status:str=Field(pattern='^(ok|failed|unsupported)$')
    message:str=Field(max_length=200)
    latency_ms:float=Field(ge=0,allow_inf_nan=False)


class CheckInfo(BaseModel):
    enabled:bool=False
    revision:int=Field(default=0,ge=0)
    checked_at:float|None=Field(default=None,ge=0,allow_inf_nan=False)
    items:list[CheckResult]=Field(default_factory=list,max_length=6)


def configuration(c,agent):
    row=c.execute('SELECT revision,data FROM application_check_config WHERE agent=?',(agent,)).fetchone()
    return {'revision':row['revision'],'checks':json.loads(row['data'])} if row else None


def panel(data,agent=None,historical=False):
    from .dashboard import esc
    from .windows_ui import stamp
    info=data.get('application_checks') or {}
    result='<div class="application-checks">'
    if agent and not historical:result+='<a class="nav-link" href="/checks/'+esc(quote(agent,safe=''))+'">Настроить проверки →</a>'
    if not info.get('enabled'):
        return result+'<p class="muted">Проверки не включены на агенте.</p></div>'
    if not info.get('items'):
        return result+'<p class="muted">Проверки не настроены или ожидают первого запуска.</p></div>'
    result+='<div class="table-scroll"><table class="metric-table"><tr><th>Приложение</th><th>Результат</th><th>Отклик</th></tr>'
    for item in info['items']:
        result+='<tr><td>'+esc(item['name'])+'</td><td><span class="badge '+('normal' if item['status']=='ok' else 'danger' if item['status']=='failed' else 'neutral')+'">'+esc(item['message'])+'</span></td><td>'+esc(item['latency_ms'])+' мс</td></tr>'
    return result+'</table></div><p class="muted legend">Проверено: '+esc(stamp(info.get('checked_at')))+'. Проверки раз в минуту с компьютера агента. Неудача — подозрение на недоступность приложения; причиной также могут быть сеть, доступ или TLS. TCP подтверждает только открытый порт.</p></div>'


def register(app,db,authenticated,csrf_token):
    from .dashboard import esc,page
    from .server_names import lookup
    @app.get('/checks/{agent}',response_class=HTMLResponse)
    def settings(agent:str,request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        with db() as c:
            row=c.execute('SELECT a.id,r.data FROM agents a LEFT JOIN current_reports r ON r.agent=a.id WHERE a.id=?',(agent,)).fetchone()
            if not row:raise HTTPException(404)
            config=configuration(c,agent) or {'revision':0,'checks':[]}
            title=lookup(c,agent)
        data=json.loads(row['data'] or '{}');info=data.get('application_checks') or {}
        content='<header class="topbar"><a class="brand" href="/">ServersStatus</a><a href="/servers/'+esc(quote(agent,safe=''))+'">← Сервер</a></header><div class="heading"><h1>Проверки приложений · '+esc(title)+'</h1></div>'
        if 'app_checks_v1' not in data.get('features',[]):content+='<p class="notice">Обновите агент для поддержки проверок отклика.</p>'
        elif not info.get('enabled'):content+='<p class="notice">В локальном config.json агента задайте allow_application_checks: true и перезапустите службу агента.</p>'
        elif info.get('revision')!=config['revision']:content+='<p class="muted">Ожидает применения агентом.</p>'
        content+='<p class="muted">До 6 проверок. HTTP: адрес без параметров и паролей, ожидается статус 200 и, при желании, текст в ответе. TCP: узел и порт. SQL: Windows, SELECT 1 с учётной записью службы и проверкой TLS-сертификата. Доступность порта SQL сама по себе не подтверждает выполнение запросов.</p>'
        content+='<form method="post"><input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'">'
        for index in range(6):
            rule=config['checks'][index] if index<len(config['checks']) else {}
            content+='<fieldset class="check-rule"><legend>Проверка '+str(index+1)+'</legend><div class="rule-grid">'
            for key,label,default in [('name','Название',''),('target','HTTP URL или узел',''),('port','Порт для TCP / SQL',''),('contains','Текст в HTTP-ответе (необязательно)',''),('database','База SQL (по умолчанию master)','')]:
                content+='<label>'+label+'<input name="'+key+'_'+str(index)+'" value="'+esc(rule.get(key,default))+'" maxlength="500"></label>'
            content+='<label>Тип<select name="kind_'+str(index)+'">'+''.join('<option value="'+kind+'" '+('selected' if rule.get('kind','http')==kind else '')+'>'+label+'</option>' for kind,label in [('http','HTTP'),('tcp','TCP-порт'),('sql','SQL SELECT 1')])+'</select></label></div></fieldset>'
        content+='<p class="muted">Пустое название удаляет проверку. Изменения не перезапускают приложения. Пароли и секреты в настройках проверок не указывайте.</p><button class="primary">Сохранить проверки</button></form>'
        return HTMLResponse(page(content))

    @app.post('/checks/{agent}')
    async def save(agent:str,request:Request):
        if not authenticated(request):raise HTTPException(401)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>16000:raise HTTPException(413)
        try:form=parse_qs(body.decode('utf-8'))
        except UnicodeDecodeError:raise HTTPException(400)
        if form.get('csrf',[''])[0]!=csrf_token(request):raise HTTPException(403)
        rules=[]
        try:
            for i in range(6):
                get=lambda k:form.get(k+'_'+str(i),[''])[0].strip()
                if not get('name'):continue
                rules.append({'id':'check-'+str(i),'name':get('name'),'kind':get('kind'),'target':get('target'),'port':int(get('port') or 0),'contains':get('contains'),'database':get('database')})
            rules=validate_rules(rules)
        except ValueError as error:raise HTTPException(400,str(error)) from None
        with db() as c:
            if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent,)).fetchone():raise HTTPException(404)
            c.execute('INSERT INTO application_check_config VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET revision=excluded.revision,data=excluded.data',(agent,time.time_ns(),json.dumps(rules,ensure_ascii=False)))
            from .events import record
            record(c,agent,'configuration','Изменены проверки отклика приложений')
        return RedirectResponse('/checks/'+quote(agent,safe=''),303)
