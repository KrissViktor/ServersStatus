"""Read-only, large-screen current status with explicit stale-data handling."""
import json
import time
from pathlib import Path
from urllib.parse import quote
from fastapi import Request
from fastapi.responses import HTMLResponse,JSONResponse,RedirectResponse
from .dashboard import page,esc,number
from .disks import monitored_disks
from .overview import issues
from .fleet import members,group_select
from .ui_icons import icon

SCRIPT=Path(__file__).with_name('wallboard.js')


def payload(c,group='',now=None):
    now=time.time() if now is None else now
    selected={row['id'] for row in members(c,group)}
    items=[]
    for row in c.execute('SELECT a.id,COALESCE(p.display_name,a.id) AS name,r.received,r.data,COALESCE(f.active,1) AS active FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id LEFT JOIN agent_flags f ON f.agent=a.id ORDER BY name'):
        if row['id'] not in selected or not row['active']:continue
        data=json.loads(row['data'] or '{}');age=max(0,now-row['received']) if row['received'] is not None else None
        state='pending' if age is None else 'online' if age<180 else 'offline'
        disks=monitored_disks(data)
        items.append({'id':row['id'],'name':row['name'],'state':state,'age_seconds':age,'cpu':data.get('cpu_percent'),'ram':data.get('memory_percent'),'disk_max':max((number(item.get('used_percent')) for item in disks),default=None),'issues':issues(row,now)[:3]})
    return {'checked_at':now,'items':items}


def register(app,db,authenticated):
    @app.get('/wallboard',response_class=HTMLResponse)
    def board(request:Request,group:str=''):
        if not authenticated(request):return RedirectResponse('/',303)
        with db() as c:
            data=payload(c,group);selector=group_select(c,group)
        seed=json.dumps(data,ensure_ascii=False).replace('<','\\u003c')
        content='<div class="wallboard" data-wallboard-url="/api/wallboard?group='+esc(quote(group,safe=''))+'"><header class="wallboard-toolbar"><a class="brand" href="/">'+icon('wallboard')+' ServersStatus</a><form>'+selector+'<button>Показать</button></form><time id="wallboard-clock"></time><button type="button" id="wallboard-fullscreen">Полный экран</button><a class="nav-link" href="/">← Обзор</a></header><div id="wallboard-summary" class="wallboard-summary"></div><p id="wallboard-status" class="muted" role="status"></p><div id="wallboard-grid" class="wallboard-grid"></div></div><script type="application/json" id="wallboard-seed">'+seed+'</script><script>'+SCRIPT.read_text(encoding='utf-8')+'</script>'
        return HTMLResponse(page(content))

    @app.get('/api/wallboard')
    def state(request:Request,group:str=''):
        if not authenticated(request):return JSONResponse({'detail':'Войдите в портал'},status_code=401)
        with db() as c:data=payload(c,group)
        return JSONResponse(data,headers={'Cache-Control':'no-store'})
