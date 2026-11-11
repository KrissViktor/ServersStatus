"""Acknowledgements apply to one observed incident episode, never its recurrence."""
import hmac
import time
from urllib.parse import parse_qs
from fastapi import Request, HTTPException
from fastapi.responses import RedirectResponse
from .incident_history import sync


def active(c):
    return c.execute('''SELECT h.id,h.key,h.agent,a.acknowledged FROM incident_history h
        LEFT JOIN incident_acknowledgements a ON a.incident=h.id AND a.problem_key=h.key AND a.episode_opened=h.opened
        WHERE h.closed IS NULL''').fetchall()


def attach(c, rows, now):
    sync(c,rows,now)
    states={}
    for item in active(c):
        states.setdefault(item['agent'],{})[item['key']]={'id':item['id'],'acknowledged':item['acknowledged'] is not None}
    from .incident_history import current
    for row in rows:
        row['problem_states']=states.get(row['id'],{})
        confirmed,_,_=current([row],[],now)
        for key,state in row['problem_states'].items():state['confirmable']=key in confirmed


def control(row,key,csrf='',return_to='/'):
    from .dashboard import esc
    from .access import can_history
    state=dict(row).get('problem_states',{}).get(key,{})
    if state.get('acknowledged'):
        return '<span class="problem-acknowledged" title="Игнорируется до исчезновения и повторного появления">✓ Всё окей</span>'
    if not (can_history() and csrf and state.get('id') and state.get('confirmable')):return ''
    return '<form class="problem-ack-form" method="post" action="/problems/acknowledge"><input type="hidden" name="csrf" value="'+esc(csrf)+'"><input type="hidden" name="incident" value="'+str(state['id'])+'"><input type="hidden" name="return_to" value="'+esc(return_to)+'"><button class="problem-ack-button" title="Игнорировать только этот случай проблемы">Всё окей</button></form>'


def register(app,db,authenticated,csrf_token):
    async def management_form(request):
        from .access import can_history
        if not authenticated(request):raise HTTPException(401)
        if not can_history():raise HTTPException(403)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>16384:raise HTTPException(413)
        try:form=parse_qs(raw.decode('utf-8'),keep_blank_values=True)
        except UnicodeDecodeError:raise HTTPException(400)
        if not hmac.compare_digest(form.get('csrf',[''])[0].encode(),csrf_token(request).encode()):raise HTTPException(403)
        return form

    @app.get('/problems')
    def management(request:Request):
        from .access import can_history
        from .dashboard import page,esc
        from .server_names import lookup
        from .windows_ui import stamp
        from fastapi.responses import HTMLResponse
        from urllib.parse import quote
        if not authenticated(request):return RedirectResponse('/',303)
        if not can_history():raise HTTPException(403)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            reports=c.execute('SELECT a.id,p.display_name,r.received,r.data FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id').fetchall()
            sync(c,reports,time.time())
            rows=c.execute('''SELECT h.*,a.owner,a.acknowledged,COALESCE(n.comment,'') AS comment FROM incident_history h
                JOIN incident_acknowledgements a ON a.incident=h.id AND a.problem_key=h.key AND a.episode_opened=h.opened
                LEFT JOIN incident_acknowledgement_comments n ON n.incident=h.id AND n.problem_key=h.key AND n.episode_opened=h.opened
                WHERE h.closed IS NULL ORDER BY a.acknowledged DESC,h.id DESC''').fetchall()
            content='<header class="topbar"><a class="nav-link" href="/">← Все серверы</a><a class="nav-link" href="/admin">Администрирование</a></header><div class="heading"><h1>Отмеченные проблемы <span class="count">'+str(len(rows))+'</span></h1></div><p class="muted">Только текущие случаи, отмеченные «Всё окей». После подтверждённого исчезновения отметка прекращает действовать автоматически. Можно вернуть предупреждение раньше.</p>'
            if not rows:content+='<section class="server"><p class="text-normal">Скрытых проблем нет</p></section>'
            csrf='<input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'">'
            for row in rows:
                endpoint='/problems/'+str(row['id'])
                content+='<section class="server acknowledgement-card"><h2><a class="nav-link" href="/servers/'+esc(quote(row['agent'],safe=''))+'">'+esc(lookup(c,row['agent']))+'</a></h2><p class="acknowledgement-message">'+esc(row['message'])+'</p><p class="muted">Отметил: <b>'+esc(row['owner'] or 'Не указан')+'</b> · '+esc(stamp(row['acknowledged']))+'</p><form method="post" action="'+endpoint+'/comment">'+csrf+'<label>Комментарий<textarea name="comment" maxlength="1000" rows="2" placeholder="Почему эту проблему можно временно игнорировать">'+esc(row['comment'])+'</textarea></label><button>Сохранить комментарий</button></form><form method="post" action="'+endpoint+'/restore">'+csrf+'<button class="restore-problem">Вернуть предупреждение</button></form></section>'
        return HTMLResponse(page(content))

    async def change_mark(incident,request,restore):
        form=await management_form(request)
        if incident<1 or incident>9223372036854775807:raise HTTPException(404)
        comment=form.get('comment',[''])[0].replace('\r\n','\n').replace('\r','\n').strip()
        if len(comment)>1000 or any(ord(ch)<32 and ch not in '\n\t' for ch in comment):raise HTTPException(400,'Комментарий: до 1000 символов')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            reports=c.execute('SELECT a.id,p.display_name,r.received,r.data FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id').fetchall()
            sync(c,reports,time.time())
            row=c.execute('''SELECT h.* FROM incident_history h JOIN incident_acknowledgements a ON a.incident=h.id AND a.problem_key=h.key AND a.episode_opened=h.opened WHERE h.id=? AND h.closed IS NULL''',(incident,)).fetchone()
            if not row:raise HTTPException(409,'Отметка уже снята или проблема исчезла. Обновите страницу.')
            if restore:
                c.execute('DELETE FROM incident_acknowledgements WHERE incident=?',(incident,))
                c.execute('DELETE FROM incident_acknowledgement_comments WHERE incident=?',(incident,))
            else:c.execute('INSERT INTO incident_acknowledgement_comments VALUES (?,?,?,?) ON CONFLICT(incident) DO UPDATE SET problem_key=excluded.problem_key,episode_opened=excluded.episode_opened,comment=excluded.comment',(incident,row['key'],row['opened'],comment))
            from .events import record
            from .access import current_user
            record(c,row['agent'],'configuration',('Возвращено предупреждение' if restore else 'Изменён комментарий к отметке «Всё окей»')+' · '+(current_user().get('name') or '')+' · '+row['message'])
        return RedirectResponse('/problems',303)

    @app.post('/problems/{incident}/comment')
    async def comment(incident:int,request:Request):return await change_mark(incident,request,False)

    @app.post('/problems/{incident}/restore')
    async def restore(incident:int,request:Request):return await change_mark(incident,request,True)

    @app.post('/problems/acknowledge')
    async def acknowledge(request:Request):
        from .access import can_history,current_user
        if not authenticated(request):raise HTTPException(401)
        if not can_history():raise HTTPException(403)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>4096:raise HTTPException(413)
        try:form=parse_qs(body.decode('utf-8'))
        except UnicodeDecodeError:raise HTTPException(400)
        if not hmac.compare_digest(form.get('csrf',[''])[0].encode(),csrf_token(request).encode()):raise HTTPException(403)
        value=form.get('incident',[''])[0]
        if not value.isascii() or not value.isdigit() or len(value)>18:raise HTTPException(400)
        now=time.time()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            incident=c.execute('SELECT * FROM incident_history WHERE id=?',(int(value),)).fetchone()
            if not incident:raise HTTPException(404)
            rows=c.execute('SELECT a.id,p.display_name,r.received,r.data FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id WHERE a.id=?',(incident['agent'],)).fetchall()
            sync(c,rows,now)
            incident=c.execute('SELECT * FROM incident_history WHERE id=? AND closed IS NULL',(int(value),)).fetchone()
            if not incident:raise HTTPException(409,'Проблема уже исчезла. Обновите страницу.')
            from .incident_history import current
            problems,_,_=current(rows,[],now)
            if incident['key'] not in problems:raise HTTPException(409,'Состояние проблемы сейчас не подтверждено.')
            result=c.execute('''INSERT INTO incident_acknowledgements VALUES (?,?,?,?,?) ON CONFLICT(incident) DO UPDATE SET problem_key=excluded.problem_key,episode_opened=excluded.episode_opened,acknowledged=excluded.acknowledged,owner=excluded.owner WHERE problem_key!=excluded.problem_key OR episode_opened!=excluded.episode_opened''',(incident['id'],incident['key'],incident['opened'],now,current_user().get('name') or ''))
            if result.rowcount:
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='telegram_state'").fetchone():
                    c.execute('UPDATE telegram_state SET sent=0,next_attempt=0 WHERE key=?',(incident['key'],))
                from .events import record
                record(c,incident['agent'],'configuration','Проблема отмечена «Всё окей»: '+incident['message'])
        from urllib.parse import quote
        destination='/servers/'+quote(incident['agent'],safe='')
        return RedirectResponse(destination if form.get('return_to',[''])[0]==destination else '/',303)
