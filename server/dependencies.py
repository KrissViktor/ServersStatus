"""Manually declared server dependencies and possible outage impact."""
import hmac
import time
from urllib.parse import parse_qs,quote
from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from .dashboard import page,esc
from .fleet import group_select,members
from .ui_icons import icon

SCHEMA='CREATE TABLE IF NOT EXISTS server_dependencies(dependent TEXT NOT NULL,provider TEXT NOT NULL,label TEXT NOT NULL DEFAULT \'\',created REAL NOT NULL,PRIMARY KEY(dependent,provider),CHECK(dependent!=provider));'


def impacted(edges,offline):
    affected=set(offline)
    while True:
        new={edge['dependent'] for edge in edges if edge['provider'] in affected}
        if new<=affected:return affected-set(offline)
        affected.update(new)


def diagram(rows,edges,group_ids=None):
    now=time.time();nodes={row['id']:row for row in rows}
    if group_ids is not None:
        keep=set(group_ids)
        for edge in edges:
            if edge['dependent'] in group_ids or edge['provider'] in group_ids:keep.update([edge['dependent'],edge['provider']])
        nodes={key:row for key,row in nodes.items() if key in keep}
    omitted=max(0,len(nodes)-60);nodes=dict(list(nodes.items())[:60]);edges=[edge for edge in edges if edge['dependent'] in nodes and edge['provider'] in nodes]
    offline={key for key,row in nodes.items() if row['received'] is not None and now-row['received']>=180};risk=impacted(edges,offline)
    levels={key:0 for key in nodes if not any(edge['dependent']==key for edge in edges)}
    for _ in range(len(nodes)):
        changed=False
        for key in nodes:
            providers=[edge['provider'] for edge in edges if edge['dependent']==key]
            if key not in levels and providers and all(provider in levels for provider in providers):levels[key]=min(5,1+max(levels[p] for p in providers));changed=True
        if not changed:break
    fallback=min(5,max(levels.values(),default=-1)+1)
    for key in nodes:levels.setdefault(key,fallback)
    highest=max(levels.values(),default=0);columns={};positions={}
    for key,level in levels.items():
        column=highest-level;row=len(columns.setdefault(column,[]));columns[column].append(key);positions[key]=(25+column*245,35+row*100)
    width=max(600,(highest+1)*245+20);height=max(200,max((len(value) for value in columns.values()),default=0)*100+40)
    result='<div class="dependency-summary"><span class="badge danger">Нет связи: '+str(len(offline))+'</span><span class="badge warning">Возможное влияние: '+str(len(risk))+'</span></div><div class="dependency-canvas" tabindex="0" role="region" aria-label="Схема связей"><svg class="dependency-diagram" width="'+str(width)+'" height="'+str(height)+'" viewBox="0 0 '+str(width)+' '+str(height)+'" role="img" aria-label="Стрелки направлены от зависимого сервера к поставщику"><defs><marker id="dependency-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10Z" fill="#6e8d80"/></marker></defs>'
    for edge in edges:
        x,y=positions[edge['dependent']];tx,ty=positions[edge['provider']];sx=x+190;sy=y+34;target_y=ty+34;mid=(sx+tx)/2
        if tx<=x:mid=max(sx,tx+190)+35
        result+='<path class="dependency-line" d="M'+str(sx)+' '+str(sy)+' C'+str(mid)+' '+str(sy)+','+str(mid)+' '+str(target_y)+','+str(tx)+' '+str(target_y)+'" marker-end="url(#dependency-arrow)"><title>'+esc(edge['dependent']+' → '+edge['provider']+(' · '+edge['label'] if edge['label'] else ''))+'</title></path>'
    for key,row in nodes.items():
        x,y=positions[key];state='danger' if key in offline else 'neutral' if row['received'] is None else 'warning' if key in risk else 'normal'
        label='Нет связи' if key in offline else 'Нет данных' if row['received'] is None else 'Онлайн · возможное влияние' if key in risk else 'Онлайн'
        result+='<a href="/servers/'+esc(quote(key,safe=''))+'"><g class="dependency-node node-'+state+'"><title>'+esc(row['name'])+'</title><rect x="'+str(x)+'" y="'+str(y)+'" width="190" height="68" rx="11"/><circle cx="'+str(x+16)+'" cy="'+str(y+20)+'" r="4"/><text x="'+str(x+29)+'" y="'+str(y+24)+'">'+esc(row['name'][:23])+'</text><text class="dependency-state" x="'+str(x+14)+'" y="'+str(y+49)+'">'+esc(label)+'</text></g></a>'
    result+='</svg></div>'
    if omitted:result+='<p class="muted">На схеме показаны 60 серверов. Выберите группу, чтобы сузить обзор.</p>'
    return result+'<p class="muted legend">A → B: сервер A зависит от B. Влияние — предположение по вручную заданным связям, не подтверждение сбоя приложения. Циклические связи допускаются. По группе видны также соседние узлы.</p>'


def register(app,db,authenticated,csrf_token):
    @app.get('/dependencies',response_class=HTMLResponse)
    def dependencies(request:Request,group:str=''):
        if not authenticated(request):return RedirectResponse('/',303)
        with db() as c:
            rows=[dict(row) for row in c.execute('SELECT a.id,COALESCE(p.display_name,a.id) AS name,r.received FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id ORDER BY name')]
            edges=[dict(row) for row in c.execute('SELECT * FROM server_dependencies ORDER BY dependent,provider')]
            chosen={row['id'] for row in members(c,group)} if group else None
            content='<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/">← Серверы</a></header><div class="heading"><h1>'+icon('dependencies')+' Связи серверов</h1></div><form class="fleet-filter">'+group_select(c,group)+'<button>Показать</button></form>'+diagram(rows,edges,chosen)
            csrf='<input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'">'
            content+='<details class="server dependency-editor"><summary>Добавить или изменить связь</summary><form method="post">'+csrf+'<div class="rule-grid">'
            for field,label in [('dependent','Зависимый сервер'),('provider','От какого сервера зависит')]:content+='<label>'+label+'<select name="'+field+'">'+''.join('<option value="'+esc(row['id'])+'">'+esc(row['name'])+'</option>' for row in rows)+'</select></label>'
            content+='<label>Назначение (необязательно)<input name="label" maxlength="80" placeholder="SQL, файловое хранилище…"></label></div><button name="mode" value="save">Сохранить связь</button></form></details><div class="dependency-list">'
            names={row['id']:row['name'] for row in rows}
            for edge in edges:
                content+='<form method="post" class="dependency-list-row">'+csrf+'<input type="hidden" name="dependent" value="'+esc(edge['dependent'])+'"><input type="hidden" name="provider" value="'+esc(edge['provider'])+'"><span>'+esc(names.get(edge['dependent'],edge['dependent']))+' → '+esc(names.get(edge['provider'],edge['provider']))+(' · '+esc(edge['label']) if edge['label'] else '')+'</span><button name="mode" value="delete" aria-label="Удалить связь '+esc(edge['dependent']+' → '+edge['provider'])+'">Удалить</button></form>'
            return HTMLResponse(page(content+'</div>'))

    @app.post('/dependencies')
    async def save(request:Request):
        if not authenticated(request):raise HTTPException(401)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>4096:raise HTTPException(413)
        try:form=parse_qs(body.decode('utf-8'))
        except UnicodeDecodeError:raise HTTPException(400)
        get=lambda name:form.get(name,[''])[0].strip()
        if not hmac.compare_digest(get('csrf').encode(),csrf_token(request).encode()):raise HTTPException(403)
        dependent,provider,label=get('dependent'),get('provider'),get('label')
        if dependent==provider or len(label)>80 or any(ord(ch)<32 for ch in label):raise HTTPException(400,'Укажите два разных сервера и короткое назначение')
        with db() as c:
            known={row[0] for row in c.execute('SELECT id FROM agents')}
            if dependent not in known or provider not in known:raise HTTPException(404)
            if get('mode')=='save':c.execute('INSERT INTO server_dependencies VALUES (?,?,?,?) ON CONFLICT(dependent,provider) DO UPDATE SET label=excluded.label',(dependent,provider,label,time.time()))
            elif get('mode')=='delete':c.execute('DELETE FROM server_dependencies WHERE dependent=? AND provider=?',(dependent,provider))
            else:raise HTTPException(400)
            from .events import record
            record(c,dependent,'configuration',('Удалена связь: ' if get('mode')=='delete' else 'Связь: ')+dependent+' → '+provider)
        return RedirectResponse('/dependencies',303)
