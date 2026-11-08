"""Protected, identity-bound RDP actions through the durable console queue."""
import base64
import hmac
import json
from pathlib import Path
import re
import time
from urllib.parse import quote
from fastapi import Request,HTTPException
from fastapi.responses import Response,JSONResponse
from pydantic import BaseModel,Field,ValidationError
from .dashboard import esc
from .console import read_body,expire,STATES,cleanup_history
from .console_access import require
from .events import record

SCHEMA='''CREATE TABLE IF NOT EXISTS rdp_operations(job INTEGER PRIMARY KEY,agent TEXT,action TEXT,session_id INTEGER,username TEXT,domain TEXT,logon_at REAL);
CREATE INDEX IF NOT EXISTS rdp_operations_agent ON rdp_operations(agent,job);'''
TEMPLATE=Path(__file__).with_name('rdp_command.ps1').read_text(encoding='utf-8')
SCRIPT=Path(__file__).with_name('rdp_control.js').read_text(encoding='utf-8')
ACTIONS={'disconnect':'Отключить RDP','logoff':'Завершить RDP-сеанс'}

class Target(BaseModel):
    session_id:int=Field(ge=1,le=2147483647)
    username:str=Field(min_length=1,max_length=255)
    domain:str=Field(default='',max_length=255)
    logon_at:float=Field(gt=0,allow_inf_nan=False)

class ShadowRequest(Target):
    csrf:str=Field(max_length=200)

class Operation(Target):
    csrf:str=Field(max_length=200)
    action:str=Field(pattern='^(disconnect|logoff)$')
    confirmation:str=Field(default='',max_length=255)


def label(operation):
    user=(operation['domain']+'\\' if operation['domain'] else '')+operation['username']
    return ACTIONS[operation['action']]+': '+user+' · сеанс '+str(operation['session_id'])


def command(operation):
    payload=base64.b64encode(json.dumps(operation,ensure_ascii=False).encode('utf-8')).decode('ascii')
    result=TEMPLATE.replace('__PAYLOAD__',payload)
    if len(result)>4000:raise HTTPException(400,'Данные сеанса слишком длинные для агента')
    return result


def current(c,agent,target):
    row=c.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
    if not row:raise HTTPException(404,'Сервер не найден')
    data=json.loads(row['data'])
    if time.time()-row['received']>60:raise HTTPException(409,'Отчёт устарел. Дождитесь свежих данных')
    if (data.get('system') or {}).get('os')=='Linux' or (data.get('rdp') or {}).get('status')!='available':raise HTTPException(409,'Список RDP недоступен')
    session=next((s for s in data['rdp']['sessions'] if s['session_id']==target.session_id),None)
    if not session or session.get('state') not in ('active','disconnected') or session.get('logon_at') is None or abs(session['logon_at']-target.logon_at)>.01 or session['username'].casefold()!=target.username.casefold() or session.get('domain','').casefold()!=target.domain.casefold():
        raise HTTPException(409,'Сеанс изменился. Обновите список пользователей')
    return data,session


def register(app,db,authenticated,csrf_token):
    def authorize(request):
        if not authenticated(request):raise HTTPException(401)
        require(request,db)

    @app.post('/api/servers/{agent}/rdp')
    async def enqueue(agent:str,request:Request):
        authorize(request)
        try:value=Operation.model_validate_json(await read_body(request,8192))
        except ValidationError:raise HTTPException(422,'Проверьте данные RDP-сеанса')
        if not hmac.compare_digest(value.csrf.encode(),csrf_token(request).encode()):raise HTTPException(403)
        if value.action=='logoff' and value.confirmation!=value.username:raise HTTPException(400,'Для завершения введите имя пользователя')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');expire(c,agent)
            data,session=current(c,agent,value)
            info=data.get('console') or {}
            if not info.get('enabled') or info.get('shell')!='powershell' or 'console_v1' not in data.get('features',[]):raise HTTPException(409,'Включите allow_remote_console на Windows-агенте')
            if value.action=='disconnect' and session['state']!='active':raise HTTPException(409,'Сеанс уже отключён')
            if c.execute("SELECT 1 FROM console_jobs WHERE agent=? AND status IN ('queued','running','uncertain')",(agent,)).fetchone() or c.execute("SELECT 1 FROM windows_commands WHERE agent=? AND status IN ('queued','running','uncertain')",(agent,)).fetchone() or c.execute("SELECT 1 FROM agent_update_jobs WHERE agent=? AND status IN ('queued','running')",(agent,)).fetchone():raise HTTPException(409,'Дождитесь предыдущей операции или проверьте неизвестный результат')
            operation={key:getattr(value,key) for key in ('action','session_id','username','domain','logon_at')}
            script=command(operation);now=time.time()
            identifier=c.execute('SELECT MAX(value,COALESCE((SELECT MAX(id) FROM console_jobs),0)) FROM console_job_sequence WHERE id=1').fetchone()[0]+1
            c.execute('UPDATE console_job_sequence SET value=? WHERE id=1',(identifier,))
            c.execute("INSERT INTO console_jobs VALUES (?,?,?,?, 'queued',?,?,?,'{}')",(identifier,agent,script,30,now,now+90,now))
            c.execute('INSERT INTO rdp_operations VALUES (?,?,?,?,?,?,?)',(identifier,agent,value.action,value.session_id,value.username,value.domain,value.logon_at))
            record(c,agent,'console',label(operation)+' · команда #'+str(identifier));cleanup_history(c,now)
        return {'ok':True,'id':identifier}

    @app.get('/api/servers/{agent}/rdp/operations')
    def operations(agent:str,request:Request):
        authorize(request)
        with db() as c:
            expire(c,agent)
            rows=c.execute('SELECT o.*,j.status,j.result,j.created FROM rdp_operations o JOIN console_jobs j ON j.id=o.job WHERE o.agent=? ORDER BY o.job DESC LIMIT 10',(agent,)).fetchall()
        from .console_output import clean_output
        return JSONResponse({'jobs':[{'id':r['job'],'title':label(r),'status':r['status'],'label':STATES[r['status']],'created':r['created'],'output':clean_output(json.loads(r['result'] or '{}').get('output',''))} for r in rows]},headers={'Cache-Control':'no-store'})

    @app.post('/api/servers/{agent}/rdp/shadow')
    async def shadow(agent:str,request:Request):
        authorize(request)
        try:value=ShadowRequest.model_validate_json(await read_body(request,8192))
        except ValidationError:raise HTTPException(422)
        if not hmac.compare_digest(value.csrf.encode(),csrf_token(request).encode()):raise HTTPException(403)
        with db() as c:
            data,session=current(c,agent,value)
            if session['state']!='active':raise HTTPException(409,'Shadow доступен для активного сеанса')
            host=data.get('hostname','')
            if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,252}',host):raise HTTPException(409,'Имя сервера не подходит для команды mstsc')
            record(c,agent,'console','Подготовлена команда Shadow RDP: '+host+' · сеанс '+str(value.session_id))
        text='@echo off\r\nmstsc.exe /v:"'+host+'" /shadow:'+str(value.session_id)+' /control /prompt\r\n'
        return Response(text,media_type='application/octet-stream',headers={'Content-Disposition':'attachment; filename="ServersStatus-Shadow-'+str(value.session_id)+'.cmd"','Cache-Control':'no-store'})


def controls(session,context,data):
    if not session.get('logon_at') or session.get('state') not in ('active','disconnected'):
        return '<td class="muted">Для управления нужны данные времени входа</td>'
    target={key:session.get(key,'') for key in ('session_id','username','domain','logon_at')}
    endpoint='/api/servers/'+quote(context['agent'],safe='')+'/rdp'
    enabled=(data.get('console') or {}).get('enabled') and (data.get('console') or {}).get('shell')=='powershell' and 'console_v1' in data.get('features',[])
    attributes='data-rdp-target="'+esc(json.dumps(target,ensure_ascii=False))+'" data-rdp-url="'+esc(endpoint)+'" data-rdp-csrf="'+esc(context['csrf'])+'" data-rdp-host="'+esc(data.get('hostname',context['agent']))+'"'
    result='<td><div class="rdp-actions" '+attributes+'>'
    for action,text in [('disconnect','Отключить'),('logoff','Завершить сеанс'),('shadow','Shadow RDP')]:
        disabled=(not enabled and action!='shadow') or (session.get('state')!='active' and action!='logoff')
        result+='<button type="button" data-rdp-action="'+action+'" '+('disabled title="Нужен активный сеанс и включённое управление на агенте"' if disabled else '')+'>'+text+'</button>'
    return result+'</div></td>'


def widget():
    return '<dialog id="rdp-action-dialog" aria-labelledby="rdp-action-title"><header class="rdp-dialog-heading"><h2 id="rdp-action-title">RDP</h2><button type="button" data-rdp-close aria-label="Закрыть RDP">×</button></header><p id="rdp-action-target"></p><p id="rdp-action-description" class="muted"></p><form id="rdp-action-form"><label id="rdp-logoff-confirm">Для завершения введите имя пользователя<input name="confirmation" autocomplete="off"></label><label class="check" id="rdp-action-confirm"><input type="checkbox" name="confirm" required> Подтверждаю сервер и пользователя</label><button type="submit" id="rdp-action-submit">Выполнить</button></form><p id="rdp-action-message" class="muted" role="status" aria-live="polite"></p></dialog><script>'+SCRIPT+'</script>'
