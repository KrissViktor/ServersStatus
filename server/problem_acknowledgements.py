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
