"""Private text-only local-model chats via the reverse SSH loopback endpoint."""
import asyncio
import hmac
import json
import os
from pathlib import Path
import threading
import time
import httpx
from fastapi import HTTPException,Request
from fastapi.responses import HTMLResponse,JSONResponse,RedirectResponse
from pydantic import BaseModel,Field,ValidationError
from .access import principal,can_history
from .console import read_body

SCHEMA='''CREATE TABLE IF NOT EXISTS ai_turns(
 id INTEGER PRIMARY KEY AUTOINCREMENT,owner TEXT NOT NULL,chat TEXT NOT NULL,nonce TEXT NOT NULL,
 question TEXT NOT NULL,reply TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,
 created REAL NOT NULL,updated REAL NOT NULL,error TEXT NOT NULL DEFAULT '');
CREATE UNIQUE INDEX IF NOT EXISTS ai_nonce ON ai_turns(owner,nonce);
CREATE INDEX IF NOT EXISTS ai_owner_chat ON ai_turns(owner,chat,id);
CREATE INDEX IF NOT EXISTS ai_state ON ai_turns(status,created);
CREATE UNIQUE INDEX IF NOT EXISTS ai_single_running ON ai_turns((1)) WHERE status='running';'''
ORIGIN='http://127.0.0.1:18091'
MAX_RUNTIME=180
MAX_REPLY=16384
_lock=threading.Lock()
SYSTEM='Ты локальный помощник портала мониторинга. Отвечай по-русски, понятно и по существу. Используй только разрешённые для вопроса инструменты чтения. Не выдумывай результаты проверок, даты и источники. Не выполняй команды, не меняй настройки, не запрашивай секреты. Доступ к 1С, файловой системе и консоли не предоставлен.'

class Ask(BaseModel):
    csrf:str=Field(max_length=128)
    chat:str=Field(pattern='^[a-f0-9]{32}$')
    nonce:str=Field(pattern='^[a-f0-9]{32}$')
    question:str=Field(min_length=1,max_length=4000)
    portal_access:bool=False
    internet_access:bool=False
    web_query:str=Field(default='',max_length=300)

class Action(BaseModel):
    csrf:str=Field(max_length=128)

class ModelError(Exception):pass


def initialize(c):
    from .ai_tools import SCHEMA as TOOL_SCHEMA
    c.executescript(SCHEMA+TOOL_SCHEMA)
    columns={row[1] for row in c.execute('PRAGMA table_info(ai_turns)')}
    for name,definition in [('portal_access','INTEGER NOT NULL DEFAULT 0'),('internet_access','INTEGER NOT NULL DEFAULT 0'),('web_query',"TEXT NOT NULL DEFAULT ''")]:
        if name not in columns:c.execute('ALTER TABLE ai_turns ADD COLUMN '+name+' '+definition)
    c.commit()


def key():
    try:
        value=Path(os.environ.get('STATUS_AI_KEY_FILE','/var/lib/serversstatus/ai-api-key')).read_text(encoding='utf-8').strip()
        if not 16<=len(value)<=256 or any(ord(c)<33 or ord(c)>126 for c in value):return None
        return value
    except (OSError,UnicodeError):return None


def clean(c,now):
    c.execute("UPDATE ai_turns SET status='failed',error='Запрос прерван после перезапуска или потери связи',updated=? WHERE status='running' AND updated<?",(now,now-30))
    c.execute("UPDATE ai_turns SET status='failed',error='Время ожидания в очереди истекло',updated=? WHERE status='queued' AND created<?",(now,now-600))
    c.execute('DELETE FROM ai_tool_runs WHERE turn IN (SELECT id FROM ai_turns WHERE created<?)',(now-186*86400,))
    c.execute('DELETE FROM ai_turns WHERE created<?',(now-186*86400,))


def context(c,job):
    system=SYSTEM+' Чтение портала: '+('разрешено' if job.get('portal_access') else 'выключено')+'. Интернет: '+('разрешён' if job.get('internet_access') else 'выключен')+'.'
    messages=[{'role':'system','content':system}]
    budget=(5000 if job.get('portal_access') or job.get('internet_access') else 8000)-len(system)-len(job['question']);previous=[]
    rows=c.execute("SELECT question,reply FROM ai_turns WHERE owner=? AND chat=? AND id<? AND status='completed' ORDER BY id DESC LIMIT 4",(job['owner'],job['chat'],job['id'])).fetchall()
    for row in rows:
        size=len(row['question'])+len(row['reply'])
        if size>budget:break
        budget-=size;previous.append(row)
    for row in reversed(previous):messages.extend([{'role':'user','content':row['question']},{'role':'assistant','content':row['reply']}])
    messages.append({'role':'user','content':job['question']});return messages


def _save(db,identifier,reply,status=None,error=''):
    with db() as c:
        c.execute("UPDATE ai_turns SET reply=?,updated=?,status=COALESCE(?,status),error=? WHERE id=? AND status='running'",(reply,time.time(),status,error,identifier))


def _active(db,identifier):
    with db() as c:row=c.execute('SELECT status FROM ai_turns WHERE id=?',(identifier,)).fetchone()
    return row is not None and row['status']=='running'


async def generate(db,job,messages,api_key):
    reply='';done=False;last_save=0
    from .ai_tools import Session
    session=Session(db,job,messages)
    definitions=session.definitions()
    if definitions:
        messages=[dict(m) for m in messages];messages[0]['content']+=' '+session.instructions()
    async def consume():
        nonlocal reply,done,last_save
        rounds=3 if definitions else 1
        # Fetch current public context before generation: small local models may
        # answer from training data instead of choosing a tool themselves.
        if session.internet:
            name='web_page' if session.direct_source and not job.get('web_query') else 'web_search'
            args={'source_id':session.direct_source} if name=='web_page' else {}
            result=await session.execute(name,args)
            messages.append({'role':'assistant','content':None,'tool_calls':[{'id':'automatic_web','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]})
            messages.append({'role':'tool','tool_call_id':'automatic_web','content':json.dumps(result,ensure_ascii=False)})
        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=httpx.Timeout(120,connect=5,write=10,pool=5)) as client:
            for step in range(rounds):
                calls={};content='';finished=False
                payload={'model':'serversstatus-local','messages':messages,'stream':True,'max_tokens':512,'temperature':0.6}
                if definitions:payload.update(tools=definitions,tool_choice='auto' if step<rounds-1 and session.calls<4 else 'none')
                async with client.stream('POST',ORIGIN+'/v1/chat/completions',headers={'Authorization':'Bearer '+api_key},json=payload) as response:
                    if response.status_code in (401,403):raise ModelError('Модель отклонила ключ доступа. Обратитесь к администратору.')
                    if response.status_code==503:raise ModelError('Модель загружается или приостановлена. Попробуйте позже.')
                    if response.status_code!=200:raise ModelError('Модель не смогла обработать запрос. Попробуйте новый диалог или более короткий вопрос.')
                    async for line in response.aiter_lines():
                        if not line.startswith('data:'):continue
                        data=line[5:].strip()
                        if data=='[DONE]':finished=True;break
                        try:value=json.loads(data)
                        except ValueError:raise ModelError('Получен некорректный ответ модели.')
                        if value.get('error'):raise ModelError('Модель сообщила об ошибке обработки запроса.')
                        for choice in value.get('choices',[]):
                            delta=choice.get('delta',{});part=delta.get('content')
                            if isinstance(part,str):reply+=part;content+=part
                            if len(reply)>MAX_REPLY:raise ModelError('Достигнут лимит длины ответа. Уточните вопрос.')
                            for call in delta.get('tool_calls',[]):
                                index=call.get('index',0)
                                if type(index) is not int or not 0<=index<3:raise ModelError('Слишком много запросов инструментов')
                                entry=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                                if call.get('id'):entry['id']+=call['id']
                                function=call.get('function',{})
                                for key in ('name','arguments'):
                                    part=function.get(key)
                                    if isinstance(part,str):entry['function'][key]+=part
                                if len(entry['function']['arguments'])>2048 or len(entry['function']['name'])>64 or len(entry['id'])>128:raise ModelError('Параметры инструмента слишком велики')
                            if choice.get('finish_reason') is not None:finished=True
                        if time.monotonic()-last_save>.5:
                            _save(db,job['id'],reply);last_save=time.monotonic()
                if calls:
                    if not definitions or step>=rounds-1 or session.calls>=4:raise ModelError('Лимит инструментов исчерпан. Уточните вопрос.')
                    ordered=[calls[i] for i in sorted(calls)]
                    for index,call in enumerate(ordered):
                        if not call['id']:call['id']='source_'+str(step)+'_'+str(index)
                    messages.append({'role':'assistant','content':content,'tool_calls':ordered})
                    for call in ordered:
                        try:args=json.loads(call['function']['arguments'] or '{}')
                        except ValueError:result={'error':'Некорректный JSON параметров'}
                        else:result=await session.execute(call['function']['name'],args)
                        messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(result,ensure_ascii=False)})
                    if content:reply+='\n\n'
                    continue
                done=finished
                return
    task=None
    try:
        if not _active(db,job['id']):return
        task=asyncio.create_task(consume());deadline=time.monotonic()+(max(MAX_RUNTIME,300) if definitions else MAX_RUNTIME)
        while not task.done():
            if not _active(db,job['id']):task.cancel();return
            if time.monotonic()>deadline:raise ModelError('Время ответа истекло. Попробуйте более короткий вопрос.')
            await asyncio.wait({task},timeout=.5)
            if time.monotonic()-last_save>1:
                _save(db,job['id'],reply);last_save=time.monotonic()
        await task
        if not done or not reply.strip():raise ModelError('Модель не завершила ответ. Попробуйте ещё раз.')
        _save(db,job['id'],reply,'completed')
    except ModelError as exc:_save(db,job['id'],reply[:MAX_REPLY],'failed',str(exc))
    except Exception:_save(db,job['id'],reply[:MAX_REPLY],'failed','Нет связи с моделью. Проверьте туннель, паузу и состояние Backup.')
    finally:
        if task and not task.done():task.cancel()
        if task:
            try:await task
            except (Exception,asyncio.CancelledError):pass


def kick(db):
    if not _lock.acquire(blocking=False):return
    def worker():
        try:
            while True:
                with db() as c:
                    c.execute('BEGIN IMMEDIATE');clean(c,time.time())
                    if c.execute("SELECT 1 FROM ai_turns WHERE status='running'").fetchone():return
                    row=c.execute("SELECT * FROM ai_turns WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
                    if not row:return
                    job=dict(row);api_key=key()
                    if not api_key:
                        c.execute("UPDATE ai_turns SET status='failed',error='Подключение модели не настроено',updated=? WHERE id=?",(time.time(),job['id']));continue
                    c.execute("UPDATE ai_turns SET status='running',updated=? WHERE id=?",(time.time(),job['id']))
                    messages=context(c,job)
                asyncio.run(generate(db,job,messages,api_key))
        finally:_lock.release()
    threading.Thread(target=worker,daemon=True).start()


def register(app,db,authenticated,csrf_token):
    def user(request):
        value=principal(request,db)
        if not value:raise HTTPException(401)
        if not can_history():raise HTTPException(403)
        return value['name']
    async def body(request,model):
        try:value=model.model_validate_json(await read_body(request,32768))
        except ValidationError:raise HTTPException(422,'Проверьте текст запроса')
        if not hmac.compare_digest(value.csrf.encode(),csrf_token(request).encode()):raise HTTPException(403)
        return value
    def valid_chat(chat):
        if len(chat)!=32 or any(c not in 'abcdef0123456789' for c in chat):raise HTTPException(404)
    def response(value):return JSONResponse(value,headers={'Cache-Control':'no-store'})

    @app.get('/ai',response_class=HTMLResponse)
    def view(request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        user(request)
        from .ai_ui import render
        return HTMLResponse(render(csrf_token(request)),headers={'Cache-Control':'no-store'})

    @app.get('/api/ai/chats')
    def chats(request:Request):
        owner=user(request)
        with db() as c:
            clean(c,time.time())
            rows=c.execute('''SELECT chat,MIN(id) AS first_id,MAX(created) AS updated FROM ai_turns WHERE owner=? GROUP BY chat ORDER BY updated DESC LIMIT 50''',(owner,)).fetchall()
            result=[]
            for row in rows:
                title=c.execute('SELECT question FROM ai_turns WHERE id=?',(row['first_id'],)).fetchone()[0]
                result.append({'chat':row['chat'],'title':title[:64],'updated':row['updated']})
            active=c.execute("SELECT chat FROM ai_turns WHERE owner=? AND status IN ('queued','running') LIMIT 1",(owner,)).fetchone()
        kick(db)
        return response({'chats':result,'configured':key() is not None,'active':active['chat'] if active else None})

    @app.get('/api/ai/chat/{chat}')
    def turns(chat:str,request:Request):
        owner=user(request);valid_chat(chat)
        with db() as c:
            clean(c,time.time())
            rows=c.execute('SELECT id,question,reply,status,created,error,portal_access,internet_access FROM ai_turns WHERE owner=? AND chat=? ORDER BY id LIMIT 50',(owner,chat)).fetchall()
            if not rows:raise HTTPException(404)
            result=[]
            for row in rows:
                item=dict(row);item['tools']=[dict(t) for t in c.execute('SELECT id,name,label,url,status,error FROM ai_tool_runs WHERE turn=? ORDER BY id',(row['id'],))];result.append(item)
        kick(db);return response({'turns':result})

    @app.post('/api/ai/ask')
    async def ask(request:Request):
        owner=user(request);value=await body(request,Ask)
        if not value.question.strip():raise HTTPException(400,'Введите вопрос')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');clean(c,time.time())
            existing=c.execute('SELECT * FROM ai_turns WHERE owner=? AND nonce=?',(owner,value.nonce)).fetchone()
            if existing:
                if existing['question']!=value.question.strip() or existing['chat']!=value.chat or bool(existing['portal_access'])!=value.portal_access or bool(existing['internet_access'])!=value.internet_access or existing['web_query']!=value.web_query.strip():raise HTTPException(409,'Идентификатор запроса уже использован')
                return response({'id':existing['id'],'chat':existing['chat']})
            if not key():raise HTTPException(503,'Администратор ещё не настроил подключение модели')
            if c.execute("SELECT 1 FROM ai_turns WHERE owner=? AND status IN ('queued','running')",(owner,)).fetchone():raise HTTPException(409,'Дождитесь ответа на предыдущий вопрос или остановите его')
            if c.execute("SELECT COUNT(*) FROM ai_turns WHERE status IN ('queued','running')").fetchone()[0]>=3:raise HTTPException(429,'Модель занята. Попробуйте позже.')
            if c.execute('SELECT COUNT(*) FROM ai_turns WHERE owner=? AND chat=?',(owner,value.chat)).fetchone()[0]>=50:raise HTTPException(409,'В этом диалоге уже 50 вопросов. Начните новый.')
            count=c.execute('SELECT COUNT(DISTINCT chat) FROM ai_turns WHERE owner=?',(owner,)).fetchone()[0]
            if count>=50 and not c.execute('SELECT 1 FROM ai_turns WHERE owner=? AND chat=?',(owner,value.chat)).fetchone():raise HTTPException(409,'Лимит 50 диалогов. Удалите ненужный диалог.')
            now=time.time()
            identifier=c.execute("INSERT INTO ai_turns(owner,chat,nonce,question,status,created,updated,portal_access,internet_access,web_query) VALUES (?,?,?,?,'queued',?,?,?,?,?)",(owner,value.chat,value.nonce,value.question.strip(),now,now,int(value.portal_access),int(value.internet_access),value.web_query.strip())).lastrowid
        kick(db);return response({'id':identifier,'chat':value.chat})

    @app.post('/api/ai/chat/{chat}/{action}')
    async def change(chat:str,action:str,request:Request):
        owner=user(request);valid_chat(chat);await body(request,Action)
        if action not in ('cancel','delete'):raise HTTPException(404)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM ai_turns WHERE owner=? AND chat=?',(owner,chat)).fetchone():raise HTTPException(404)
            if action=='cancel':c.execute("UPDATE ai_turns SET status='cancelled',updated=? WHERE owner=? AND chat=? AND status IN ('queued','running')",(time.time(),owner,chat))
            else:
                c.execute('DELETE FROM ai_tool_runs WHERE turn IN (SELECT id FROM ai_turns WHERE owner=? AND chat=?)',(owner,chat))
                c.execute('DELETE FROM ai_turns WHERE owner=? AND chat=?',(owner,chat))
        return response({'ok':True})
