"""Daily coverage heatmap and a merged, read-only server timeline."""
import json
import time
from datetime import datetime,timedelta
from urllib.parse import quote
from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from .dashboard import page,esc,duration
from .fleet import MSK,members,group_select
from .stability import load as availability,percentage
from .windows_ui import stamp
from .ui_icons import icon

SCHEMA='''CREATE TABLE IF NOT EXISTS server_boot_events(agent TEXT NOT NULL,source TEXT NOT NULL,record_id INTEGER NOT NULL,at REAL NOT NULL,event_id INTEGER NOT NULL,kind TEXT NOT NULL,message TEXT NOT NULL,reason_code TEXT NOT NULL,PRIMARY KEY(agent,source,record_id,at));
CREATE INDEX IF NOT EXISTS server_boot_events_time ON server_boot_events(agent,at);'''


def store_boots(c,agent,report):
    info=report.get('reboot_history') or {}
    if info.get('status')!='available':return
    from .portal_settings import retention_days
    cutoff=time.time()-retention_days(c)*86400
    for item in info.get('events',[]):
        if item['at']<cutoff:continue
        c.execute('INSERT OR IGNORE INTO server_boot_events VALUES (?,?,?,?,?,?,?,?)',(agent,item['source'],item['record_id'],item['at'],item['event_id'],item['kind'],item.get('message',''),item.get('reason_code','')))


def cells(c,agent,start,end,days):
    info=availability(c,agent,start,end,details=False);result=[]
    for index in range(days):
        day=start+index*86400;finish=min(day+86400,end);begin=max(day,info['start']);span=max(0,finish-begin)
        covered=sum(max(0,min(finish,b)-max(begin,a)) for a,b in info['segments']) if span else 0
        percent=covered/span*100 if span and info['percent'] is not None else None
        result.append({'day':datetime.fromtimestamp(day,MSK).date().isoformat(),'percent':percent,'missing':max(0,span-covered) if percent is not None else None,'partial':finish<day+86400 or begin>day})
    return result


def timeline(c,agent,start,end):
    result=[]
    def add(at,kind,title,description='',level='neutral',finish=None):
        if start<=at<=end:result.append({'at':at,'kind':kind,'title':title,'description':description,'level':level,'finish':finish})
    up=availability(c,agent,start,end)
    for a,b in up['gaps'][-150:]:
        add(a,'connection','Нет отчётов',duration(b-a)+' без подтверждения связи','danger',b)
        if b<end:add(b,'connection','Связь подтверждена','Получен следующий отчёт','normal')
    for item in up['reboots'][-100:]:add(item['at'],'reboot','Перезагрузка по аптайму','Предполагаемое время загрузки, определённое из соседних отчётов','warning')
    for item in c.execute('SELECT * FROM incident_history WHERE agent=? AND opened<=? AND (closed IS NULL OR closed>=?) ORDER BY opened DESC LIMIT 200',(agent,end,start)):
        if item['category']=='connection':continue
        add(item['opened'],'incident','Начало проблемы',item['message'],'danger')
        if item['closed'] is not None:add(item['closed'],'incident','Восстановлено' if item['resolution']=='recovered' else 'Проверка исключена',item['message'],'normal' if item['resolution']=='recovered' else 'neutral')
    for item in c.execute("SELECT * FROM events WHERE agent=? AND received>=? AND received<=? AND category IN ('configuration','management','updates','update') ORDER BY id DESC LIMIT 200",(agent,start,end)):
        add(item['received'],'configuration' if item['category']=='configuration' else 'update','Настройки изменены' if item['category']=='configuration' else 'Управление сервером',item['message'],'warning' if item['level']=='warning' else 'neutral')
    for item in c.execute('SELECT e.created,e.status,e.message,p.version FROM update_job_events e JOIN agent_update_jobs j ON j.id=e.job LEFT JOIN update_packages p ON p.id=j.package WHERE j.agent=? AND e.created>=? AND e.created<=? ORDER BY e.id DESC LIMIT 100',(agent,start,end)):
        add(item['created'],'update','Обновление агента · '+str(item['version'] or 'версия неизвестна'),str(item['status'])+' · '+str(item['message'] or ''),'danger' if item['status']=='failed' else 'normal' if item['status']=='succeeded' else 'neutral')
    from .equipment_history import changes
    from .hardware import KINDS
    for item in c.execute('SELECT * FROM equipment_history WHERE agent=? AND received>=? AND received<=? ORDER BY id DESC LIMIT 100',(agent,start,end)):
        previous=c.execute('SELECT data FROM equipment_history WHERE agent=? AND id<? ORDER BY id DESC LIMIT 1',(agent,item['id'])).fetchone()
        if previous:
            kinds=changes(json.loads(previous[0]),json.loads(item['data']))
            add(item['received'],'equipment','Изменение комплектации',', '.join(KINDS.get(kind,'Операционная система') for kind,_,_ in kinds),'warning')
    latest=c.execute('SELECT data FROM reports WHERE agent=? AND received<=? ORDER BY received DESC LIMIT 1',(agent,end)).fetchone()
    if latest:store_boots(c,agent,json.loads(latest[0]))
    for item in c.execute('SELECT * FROM server_boot_events WHERE agent=? AND at>=? AND at<=? ORDER BY at DESC LIMIT 100',(agent,start,end)):
        label={'planned':'Штатное завершение / перезагрузка','unexpected':'Нештатное завершение Windows','boot':'Запуск Windows','shutdown':'Остановка Windows','update':'Обслуживание / обновление Windows'}.get(item['kind'],'Событие Windows')
        add(item['at'],'reboot',label,item['source']+' · ID '+str(item['event_id'])+' · '+item['message']+(' · причина '+item['reason_code'] if item['reason_code'] else ''),'danger' if item['kind']=='unexpected' else 'neutral')
    return sorted(result,key=lambda item:item['at'],reverse=True)


def register(app,db,authenticated):
    @app.get('/heatmap',response_class=HTMLResponse)
    def heatmap(request:Request,days:int=30,group:str=''):
        if not authenticated(request):return RedirectResponse('/',303)
        if days not in (7,30,90):raise HTTPException(400)
        now=time.time();today=datetime.fromtimestamp(now,MSK).replace(hour=0,minute=0,second=0,microsecond=0);start=(today-timedelta(days=days-1)).timestamp()
        with db() as c:
            rows=members(c,group)
            if len(rows)>200:raise HTTPException(400,'Выберите группу до 200 серверов')
            content='<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/">← Серверы</a><a class="nav-link" href="/wallboard">Большой экран</a></header><div class="heading"><h1>'+icon('heatmap')+' Карта стабильности</h1></div><form class="fleet-filter">'+group_select(c,group)+'<label>Период<select name="days">'+''.join('<option value="'+str(value)+'" '+('selected' if value==days else '')+'>'+str(value)+' дней</option>' for value in (7,30,90))+'</select></label><button>Показать</button></form><div class="heatmap-legend"><span class="heat-good">● 99,9–100%</span><span class="heat-warn">● 95–99,9%</span><span class="heat-poor">● Менее 95%</span><span class="heat-down">● 0%</span><span class="muted">● Нет данных до начала наблюдений</span></div><div class="heatmap-scroll" tabindex="0" role="region" aria-label="Карта доступности по дням"><table class="heatmap-table"><thead><tr><th>Сервер</th>'
            for index in range(days):content+='<th>'+datetime.fromtimestamp(start+index*86400,MSK).strftime('%d')+'</th>'
            content+='</tr></thead><tbody>'
            for row in rows:
                content+='<tr><th><a href="/servers/'+esc(quote(row['id'],safe=''))+'">'+esc(row['name'])+'</a></th>'
                for cell in cells(c,row['id'],start,now,days):
                    value=cell['percent'];style='heat-empty' if value is None else 'heat-good' if value>=99.9 else 'heat-warn' if value>=95 else 'heat-poor' if value>0 else 'heat-down'
                    label=cell['day']+' · '+percentage(value)+(' · без данных '+duration(cell['missing']) if value is not None else '')+(' · неполный день' if cell['partial'] else '')
                    content+='<td><a class="heat-cell '+style+'" href="/timeline/'+esc(quote(row['id'],safe=''))+'?day='+cell['day']+'" data-heat-day="'+esc(cell['day'])+'" data-heat-server="'+esc(row['name'])+'" title="'+esc(label)+'" aria-label="'+esc(label)+'">'+('—' if value is None else '·' if value>=99.9 else '&lt;1' if 0<value<1 else str(int(value)))+'</a></td>'
                content+='</tr>'
            content+='</tbody></table></div><p class="muted legend">Дни по Москве. Сегодня учитывается прошедшая часть дня. Нажмите ячейку, чтобы открыть ленту с пропусками и событиями. Отсутствие отчётов не доказывает выключение сервера.</p>'
        return HTMLResponse(page(content))

    @app.get('/timeline/{agent}',response_class=HTMLResponse)
    def history(agent:str,request:Request,period:str='7d',day:str='',kind:str=''):
        if not authenticated(request):return RedirectResponse('/',303)
        types={'connection':'Связь','incident':'Проблемы','reboot':'Перезагрузки','update':'Обновления','equipment':'Комплектация','configuration':'Настройки'}
        if period not in ('24h','7d','30d') or kind not in ('',*types):raise HTTPException(400)
        now=time.time()
        if day:
            try:start=datetime.strptime(day,'%Y-%m-%d').replace(tzinfo=MSK).timestamp()
            except ValueError:raise HTTPException(400)
            if start>now:raise HTTPException(400,'Дата в будущем')
            end=min(now,start+86400)
        else:end=now;start=end-{'24h':86400,'7d':604800,'30d':2592000}[period]
        with db() as c:
            row=c.execute('SELECT a.id,COALESCE(p.display_name,a.id) AS name FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id WHERE a.id=?',(agent,)).fetchone()
            if not row:raise HTTPException(404)
            from .portal_settings import retention_days
            if end<now-retention_days(c)*86400:raise HTTPException(400,'Дата вне срока хранения')
            items=timeline(c,agent,start,end);items=[item for item in items if not kind or item['kind']==kind]
        content='<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/servers/'+esc(quote(agent,safe=''))+'">← Сервер</a><a class="nav-link" href="/heatmap">Карта стабильности</a></header><div class="heading"><h1>'+icon('timeline')+' Лента · '+esc(row['name'])+'</h1></div><form class="fleet-filter"><label>Период<select name="period">'+''.join('<option value="'+p+'" '+('selected' if p==period else '')+'>'+label+'</option>' for p,label in [('24h','Сутки'),('7d','Неделя'),('30d','30 дней')])+'</select></label><label>Дата (необязательно)<input type="date" name="day" value="'+esc(day)+'"></label><label>События<select name="kind"><option value="">Все</option>'+''.join('<option value="'+key+'" '+('selected' if key==kind else '')+'>'+label+'</option>' for key,label in types.items())+'</select></label><button>Показать</button></form><p class="muted">'+esc(stamp(start))+' — '+esc(stamp(end))+'</p><div class="server-timeline">'
        for item in items[:300]:
            content+='<article class="timeline-item timeline-'+item['level']+'"><div class="timeline-symbol">'+icon(item['kind'])+'</div><div><time>'+esc(stamp(item['at']))+'</time><h2>'+esc(item['title'])+'</h2><p>'+esc(item['description'])+'</p>'+('<small>До '+esc(stamp(item['finish']))+'</small>' if item['finish'] else '')+'</div></article>'
        if not items:content+='<p class="empty">Событий за этот период не найдено.</p>'
        return HTMLResponse(page(content+'</div><p class="muted legend">До 300 последних записей. Несколько записей Windows могут относиться к одной перезагрузке; время по аптайму оценочное. История Windows накапливается с обновления, старые записи восстанавливаются из доступных отчётов.</p>'))
