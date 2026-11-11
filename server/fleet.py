"""Server groups, period comparison and daily portal reports."""
import json
from pathlib import Path
import time
from datetime import datetime,timedelta,timezone
from urllib.parse import quote,parse_qs,urlencode
from fastapi import HTTPException,Request,Query
from fastapi.responses import HTMLResponse,RedirectResponse
from .dashboard import page,esc,duration,size,number
from .disks import monitored_disks
from .history import PERIODS,load_history
from .stability import load as availability,percentage
from .windows_ui import stamp

SCHEMA='''CREATE TABLE IF NOT EXISTS server_groups(id INTEGER PRIMARY KEY,name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS server_group_members(group_id INTEGER NOT NULL,agent TEXT NOT NULL,PRIMARY KEY(group_id,agent));
CREATE INDEX IF NOT EXISTS server_group_members_agent ON server_group_members(agent);'''
MSK=timezone(timedelta(hours=3))


def header(title):
    return '<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/compare">Сравнение</a><a class="nav-link" href="/groups">Группы</a><a class="nav-link" href="/daily">За сутки</a><a class="nav-link" href="/">← Серверы</a></header><div class="heading"><h1>'+esc(title)+'</h1></div>'


def groups(c):return [dict(row) for row in c.execute('SELECT * FROM server_groups ORDER BY name')]


def members(c,group=''):
    if not group:return [dict(row) for row in c.execute('SELECT a.id,COALESCE(p.display_name,a.id) AS name FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id ORDER BY name')]
    try:group_id=int(group)
    except (ValueError,TypeError):raise HTTPException(400,'Некорректная группа')
    if not c.execute('SELECT 1 FROM server_groups WHERE id=?',(group_id,)).fetchone():raise HTTPException(404,'Группа не найдена')
    return [dict(row) for row in c.execute('SELECT a.id,COALESCE(p.display_name,a.id) AS name FROM agents a JOIN server_group_members m ON m.agent=a.id LEFT JOIN agent_profiles p ON p.agent=a.id WHERE m.group_id=? ORDER BY name',(group_id,))]


def group_select(c,selected=''):
    return '<label>Группа<select name="group" data-auto-group><option value="">Все серверы</option>'+''.join('<option value="'+str(row['id'])+'" '+('selected' if str(row['id'])==str(selected) else '')+'>'+esc(row['name'])+'</option>' for row in groups(c))+'</select></label>'


def stats(c,agent,start,end):
    return dict(c.execute("SELECT COUNT(*) AS n,AVG(json_extract(data,'$.cpu_percent')) AS cpu,MAX(json_extract(data,'$.cpu_percent')) AS cpu_max,AVG(json_extract(data,'$.memory_percent')) AS ram,MAX(json_extract(data,'$.memory_percent')) AS ram_max FROM reports INDEXED BY reports_resource_metrics WHERE agent=? AND received>=? AND received<?",(agent,start,end)).fetchone())


def multi_chart(series,field,title,start,end):
    colors=['#8ecbad','#80b9ed','#d9b37c','#c3a0df','#e89da5','#8ad1d1']
    result='<section class="server"><h2>'+title+'</h2><svg class="comparison-chart" viewBox="0 0 1000 250" role="img" aria-label="'+title+'">'
    for value in [0,25,50,75,100]:
        y=215-value*1.9;result+=f'<line class="chart-grid" x1="45" y1="{y}" x2="980" y2="{y}"/><text class="chart-label" x="3" y="{y+4}">{value}%</text>'
    for i,(agent,name,points) in enumerate(series):
        color=colors[i];previous=None
        result+='<g data-server-id="'+esc(agent)+'">'
        for row in points:
            x=45+935*(row['timestamp']-start)/(end-start);y=215-min(100,max(0,row[field] or 0))*1.9
            if previous and not row['has_gap'] and not previous[2]:result+=f'<path d="M{previous[0]:.2f} {previous[1]:.2f}L{x:.2f} {y:.2f}" stroke="{color}" stroke-width="1.7"/>'
            tip=name+' · '+stamp(row['timestamp'])+' · '+f'{row[field]:.1f}%'
            result+=f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="{color}" data-detail-metric="{field}" data-detail-first="{row["first"]}" data-detail-last="{row["last"]}" data-detail-count="{row["samples"]}" tabindex="0" role="button" aria-label="{esc(tip)}"><title>{esc(tip)}</title></circle>'
            previous=(x,y,row['has_gap'])
        result+='</g>'
    result+='<text class="chart-label" x="45" y="245">'+esc(stamp(start))+'</text><text class="chart-label" x="980" y="245" text-anchor="end">'+esc(stamp(end))+'</text></svg><div class="comparison-legend">'
    result+=''.join('<span style="color:'+colors[i]+'">● '+esc(name)+'</span>' for i,(_,name,_) in enumerate(series))
    return result+'</div></section>'


def register(app,db,authenticated,csrf_token):
    @app.get('/compare',response_class=HTMLResponse)
    def compare(request:Request,agents:list[str]=Query(default=[]),period:str='24h',group:str=''):
        if not authenticated(request):return RedirectResponse('/',303)
        if period not in PERIODS or len(agents)>6:raise HTTPException(400,'Выберите до 6 серверов и допустимый период')
        end=time.time();start=end-PERIODS[period][1]
        with db() as c:
            all_rows=members(c,group);available={r['id'] for r in all_rows}
            chosen=list(dict.fromkeys(agents)) if agents else [r['id'] for r in all_rows[:2]]
            if any(agent not in available for agent in chosen):raise HTTPException(400,'Сервер отсутствует в выбранной группе')
            content=header('Сравнение серверов')+'<form id="compare-filter" class="fleet-filter">'+group_select(c,group)+'<label>Период<select name="period">'+''.join('<option value="'+p+'" '+('selected' if p==period else '')+'>'+label+'</option>' for p,(label,_,_) in PERIODS.items())+'</select></label><fieldset class="fleet-selection"><legend>Серверы · до 6</legend>'
            content+=''.join('<label class="check"><input type="checkbox" name="agents" value="'+esc(r['id'])+'" '+('checked' if r['id'] in chosen else '')+'>'+esc(r['name'])+'</label>' for r in all_rows)+'</fieldset><button>Сравнить</button></form>'
            from .report_exports import export_links
            content+=export_links('compare',{'agents':chosen,'period':period,'group':group})
            names={r['id']:r['name'] for r in all_rows};results=[];series=[]
            for agent in chosen:
                summary=stats(c,agent,start,end);up=availability(c,agent,start,end,details=False)
                latest=c.execute('SELECT received,data FROM current_reports WHERE agent=?',(agent,)).fetchone()
                data=json.loads(latest['data']) if latest else {}
                summary['state']='Нет данных' if not latest else 'На связи' if end-latest['received']<180 else 'Нет связи'
                summary['processor']=(data.get('system') or {}).get('processor') or 'Не сообщается'
                summary['memory_total']=size((data.get('system') or {}).get('memory_total_bytes')) if (data.get('system') or {}).get('memory_total_bytes') else 'Не сообщается'
                summary['disks']='; '.join(str(d.get('path',''))+': '+f'{number(d.get("used_percent")):.1f}%'+', '+size(d.get('free_bytes'))+' свободно' for d in monitored_disks(data)) or 'Нет данных'
                if latest and end-latest['received']>=180:summary['disks']+=' · устаревший отчёт '+stamp(latest['received'])
                results.append((agent,summary,up));series.append((agent,names[agent],load_history(c,agent,start,end,PERIODS[period][2])))
            if not results:content+='<p class="empty">В этой группе пока нет серверов.</p>'
            else:
                content+='<section class="server"><div class="table-scroll"><table class="metric-table compare-table"><tr><th>Показатель</th>'+''.join('<th><a class="nav-link" href="/servers/'+esc(quote(agent,safe=''))+'">'+esc(names[agent])+'</a></th>' for agent,_,_ in results)+'</tr>'
                for label,key,mode in [('Состояние сейчас','state','text'),('Процессор','processor','text'),('RAM: всего','memory_total','text'),('Диски · последний отчёт','disks','text'),('Доступность','percent','up'),('Без данных','missing','duration'),('Самый длинный пропуск','longest','duration'),('CPU: среднее','cpu','metric'),('CPU: пик','cpu_max','metric'),('RAM: среднее','ram','metric'),('RAM: пик','ram_max','metric'),('Отчётов','n','count')]:
                    content+='<tr><th>'+label+'</th>'
                    for _,summary,up in results:
                        value=up.get(key) if mode in ('up','duration') else summary.get(key)
                        text=percentage(value) if mode=='up' else duration(value) if mode=='duration' else str(value) if mode in ('count','text') else f'{value:.1f}%' if value is not None else 'Нет данных'
                        content+='<td>'+esc(text)+'</td>'
                    content+='</tr>'
                content+='</table></div><p class="muted legend">Одинаковые границы периода. У новых агентов доступность учитывается с первого известного отчёта; средние считаются только по полученным измерениям. Пробелы не заменяются нулями.</p></section>'
                content+=multi_chart(series,'cpu','Процессор · CPU',start,end)+multi_chart(series,'ram','Оперативная память · RAM',start,end)
        from .drilldown import widget
        return HTMLResponse(page(content+widget('')))

    @app.get('/groups',response_class=HTMLResponse)
    def group_page(request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        with db() as c:
            rows=members(c);content=header('Группы серверов')+'<form method="post" class="fleet-filter"><input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'"><label>Новая группа<input name="name" maxlength="80" required placeholder="SQL, 1С, Площадка…"></label><button name="mode" value="create">Создать</button></form>'
            now=time.time()
            for group in groups(c):
                assigned={r['agent'] for r in c.execute('SELECT agent FROM server_group_members WHERE group_id=?',(group['id'],))}
                states=[c.execute('SELECT received FROM current_reports WHERE agent=?',(agent,)).fetchone() for agent in assigned]
                online=sum(row is not None and now-row[0]<180 for row in states)
                content+='<section class="server group-card"><h2>'+esc(group['name'])+' <span class="count">'+str(len(assigned))+'</span></h2><p class="muted">На связи: '+str(online)+' · <a class="nav-link" href="/?group='+str(group['id'])+'">Карточки</a> · <a class="nav-link" href="/compare?group='+str(group['id'])+'">Сравнить</a> · <a class="nav-link" href="/daily?group='+str(group['id'])+'">Сутки</a></p><details class="group-editor"><summary>Изменить состав <span class="count">'+str(len(assigned))+'</span></summary><form method="post" data-group-editor><input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'"><input type="hidden" name="group" value="'+str(group['id'])+'"><div class="group-toolbar"><label>Найти сервер<input type="search" data-group-search placeholder="Название или ID сервера" autocomplete="off"></label><span class="group-selection-count" data-group-count role="status"></span><div class="group-actions"><button type="button" class="quiet" data-group-select="all">Выбрать найденные</button><button type="button" class="quiet" data-group-select="none">Снять выбор найденных</button></div></div><div class="group-server-grid">'
                content+=''.join('<label class="group-server-option" data-group-option><input type="checkbox" name="agents" value="'+esc(row['id'])+'" '+('checked' if row['id'] in assigned else '')+'><span class="group-server-copy"><strong>'+esc(row['name'])+'</strong><small>'+esc(row['id'])+'</small></span><span class="group-server-mark" aria-hidden="true">✓</span></label>' for row in rows)+'</div><p class="muted" data-group-empty hidden>По вашему запросу серверы не найдены.</p>'+('' if rows else '<p class="muted">Сначала добавьте серверы в разделе «Управление агентами».</p>')+'<div class="group-footer"><button name="mode" value="members">Сохранить состав</button><button name="mode" value="delete" class="quiet">Удалить группу</button></div></form></details></section>'
        return HTMLResponse(page(content+'<script>'+Path(__file__).with_name('groups.js').read_text(encoding='utf-8')+'</script>'))

    @app.post('/groups')
    async def group_save(request:Request):
        if not authenticated(request):raise HTTPException(401)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>65536:raise HTTPException(413)
        try:form=parse_qs(raw.decode('utf-8'))
        except UnicodeDecodeError:raise HTTPException(400)
        get=lambda name:form.get(name,[''])[0]
        if get('csrf')!=csrf_token(request):raise HTTPException(403)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            mode=get('mode')
            if mode=='create':
                name=get('name').strip()
                if not 1<=len(name)<=80 or any(ord(ch)<32 for ch in name):raise HTTPException(400,'Название группы: от 1 до 80 символов')
                if c.execute('SELECT 1 FROM server_groups WHERE name=?',(name,)).fetchone():raise HTTPException(400,'Группа уже существует')
                if c.execute('SELECT COUNT(*) FROM server_groups').fetchone()[0]>=100:raise HTTPException(400,'Максимум 100 групп')
                c.execute('INSERT INTO server_groups(name) VALUES (?)',(name,))
            elif mode in ('members','delete'):
                if not c.execute('SELECT 1 FROM server_groups WHERE id=?',(get('group'),)).fetchone():raise HTTPException(404)
                agents=list(dict.fromkeys(form.get('agents',[])))
                known={r[0] for r in c.execute('SELECT id FROM agents')}
                if any(agent not in known for agent in agents):raise HTTPException(400)
                c.execute('DELETE FROM server_group_members WHERE group_id=?',(get('group'),))
                if mode=='delete':c.execute('DELETE FROM server_groups WHERE id=?',(get('group'),))
                else:c.executemany('INSERT INTO server_group_members VALUES (?,?)',[(get('group'),agent) for agent in agents])
            else:raise HTTPException(400)
        return RedirectResponse('/groups',303)

    @app.get('/daily',response_class=HTMLResponse)
    def daily(request:Request,day:str='',group:str=''):
        if not authenticated(request):return RedirectResponse('/',303)
        today=datetime.now(MSK).date()
        try:date=datetime.strptime(day,'%Y-%m-%d').date() if day else today-timedelta(days=1)
        except ValueError:raise HTTPException(400,'Некорректная дата')
        with db() as c:
            from .portal_settings import retention_days
            days=retention_days(c)
        if not today-timedelta(days=days-1)<=date<=today:raise HTTPException(400,'Дата вне сохранённой истории')
        start=datetime.combine(date,datetime.min.time(),MSK).timestamp();end=min(start+86400,time.time())
        with db() as c:
            rows=members(c,group)
            content=header('Сводка за '+date.strftime('%d.%m.%Y'))+'<form class="fleet-filter"><label>Дата (МСК)<input type="date" name="day" value="'+date.isoformat()+'" max="'+today.isoformat()+'"></label>'+group_select(c,group)+'<button>Показать</button></form><p class="muted">'+esc(stamp(start))+' — '+esc(stamp(end))+'. Для сегодняшнего дня сводка неполная. Показатели относятся к выбранным суткам.</p>'
            from .report_exports import export_links
            content+=export_links('daily',{'day':date.isoformat(),'group':group})
            content+='<section class="server"><div class="table-scroll"><table class="metric-table"><tr><th>Сервер</th><th>Доступность</th><th>Без данных</th><th>CPU ср. / пик</th><th>RAM ср. / пик</th><th>Изменение CPU / RAM³</th><th>Перезагрузки¹</th><th>Началось / завершилось инцидентов</th><th>Изменения комплектации²</th></tr>'
            for row in rows:
                agent=row['id'];summary=stats(c,agent,start,end);up=availability(c,agent,start,end)
                opened=c.execute('SELECT COUNT(*) FROM incident_history WHERE agent=? AND opened>=? AND opened<?',(agent,start,end)).fetchone()[0]
                closed=c.execute("SELECT COUNT(*) FROM incident_history WHERE agent=? AND resolution='recovered' AND closed>=? AND closed<?",(agent,start,end)).fetchone()[0]
                revisions=c.execute('SELECT COUNT(*) FROM equipment_history h WHERE agent=? AND received>=? AND received<? AND EXISTS(SELECT 1 FROM equipment_history p WHERE p.agent=h.agent AND p.id<h.id)',(agent,start,end)).fetchone()[0]
                previous=stats(c,agent,start-86400,end-86400)
                trend='Нет данных' if summary['cpu'] is None or previous['cpu'] is None else f"{summary['cpu']-previous['cpu']:+.1f} / {summary['ram']-previous['ram']:+.1f} п.п."
                fmt=lambda a,b: 'Нет данных' if summary[a] is None else f'{summary[a]:.1f}% / {summary[b]:.1f}%'
                content+='<tr><td><a class="nav-link" href="/servers/'+esc(quote(agent,safe=''))+'">'+esc(row['name'])+'</a></td><td>'+percentage(up['percent'])+'</td><td>'+duration(up['missing'])+'</td><td>'+fmt('cpu','cpu_max')+'</td><td>'+fmt('ram','ram_max')+'</td><td>'+esc(trend)+'</td><td>'+str(len(up['reboots']))+'</td><td>'+str(opened)+' / '+str(closed)+'</td><td>'+str(revisions)+'</td></tr>'
            content+='</table></div><p class="muted legend">¹ По аптайму, а не числу событий Windows. ² Без первой базовой записи. ³ Разница со средними за такой же интервал предыдущих суток. Инциденты и изменения учитываются с обновления портала.</p></section>'
            from .incident_history import history_html
            for row in rows:
                count=c.execute('SELECT COUNT(*) FROM incident_history WHERE agent=? AND opened<=? AND (closed IS NULL OR closed>=?)',(row['id'],end,start)).fetchone()[0]
                if count:content+='<details class="server"><summary>'+esc(row['name'])+' · инциденты за сутки</summary>'+history_html(c,row['id'],start,end)+'</details>'
        return HTMLResponse(page(content))
