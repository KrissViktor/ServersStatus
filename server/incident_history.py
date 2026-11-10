"""Durable incident intervals, independent of notifications and page visits."""
import json
from .incidents import evaluate

SCHEMA='''CREATE TABLE IF NOT EXISTS incident_history (
    id INTEGER PRIMARY KEY, key TEXT NOT NULL, agent TEXT NOT NULL, category TEXT NOT NULL,
    opened REAL NOT NULL, last_seen REAL NOT NULL, closed REAL, resolution TEXT, message TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS incident_history_agent_time ON incident_history(agent,opened);
CREATE UNIQUE INDEX IF NOT EXISTS incident_history_open ON incident_history(key) WHERE closed IS NULL;'''


def current(rows, existing, now):
    incidents,valid,checked=evaluate(rows,existing,now)
    for row in rows:
        if row['received'] is None or now-row['received']>=180:
            continue
        data=json.loads(row['data'])
        for field,label in [('cpu_percent','Загрузка CPU'),('memory_percent','Занято RAM')]:
            key=field+':'+row['id'];valid.add(key);checked.add(key)
            if (data.get(field) or 0)>=95:
                incidents[key]=(row['id'],label+' '+f'{data[field]:.1f}%')
    return incidents,valid,checked


def sync(c, rows, now):
    if not rows:
        return
    agents=[row['id'] for row in rows]
    existing=[]
    for agent in agents:
        existing.extend(dict(row) for row in c.execute('SELECT *,1 AS active FROM incident_history WHERE agent=? AND closed IS NULL',(agent,)))
    incidents,valid,checked=current(rows,existing,now)
    opened={row['key']:row for row in existing};by_agent={row['id']:row for row in rows}
    for key,(agent,message) in incidents.items():
        if key in opened:
            c.execute('UPDATE incident_history SET last_seen=?,message=? WHERE id=?',(now,message[:4000],opened[key]['id']))
        else:
            since=by_agent[agent]['received']+180 if key.startswith('connection:') else now
            c.execute('INSERT OR IGNORE INTO incident_history(key,agent,category,opened,last_seen,message) VALUES (?,?,?,?,?,?)',(key,agent,key.split(':')[0],since,now,message[:4000]))
    for key,row in opened.items():
        if key not in valid or (key in checked and key not in incidents):
            c.execute('UPDATE incident_history SET closed=?,resolution=? WHERE id=?',(now,'recovered' if key in valid else 'removed',row['id']))


def on_report(c,agent,previous,received,encoded):
    # Recover outages even if the portal/event timer was down for the entire gap.
    if previous and received-previous['received']>=180:
        key='connection:'+agent
        if not c.execute('SELECT 1 FROM incident_history WHERE key=? AND closed IS NULL',(key,)).fetchone():
            since=previous['received']+180
            c.execute('INSERT INTO incident_history(key,agent,category,opened,last_seen,message) VALUES (?,?,?,?,?,?)',(key,agent,'connection',since,received,'Нет связи с агентом более 3 минут. Интервал восстановлен по отчётам.'))
    sync(c,[{'id':agent,'received':received,'data':encoded}],received)


def history_html(c,agent,start,end):
    from .dashboard import esc,duration
    from .windows_ui import stamp
    rows=c.execute('SELECT * FROM incident_history WHERE agent=? AND opened<=? AND (closed IS NULL OR closed>=?) ORDER BY opened DESC,id DESC LIMIT 51',(agent,end,start)).fetchall()
    result='<div class="incident-history"><h3>История инцидентов</h3>'
    if not rows:
        return result+'<p class="muted">В выбранном периоде зарегистрированных инцидентов нет.</p><p class="muted legend">История ресурсов начинается с обновления портала. Пропуски связи за прошлое доступны выше по сохранённым отчётам.</p></div>'
    result+='<div class="table-scroll"><table class="metric-table"><tr><th>Начало</th><th>Окончание</th><th>Длительность</th><th>Проблема</th></tr>'
    for row in rows[:50]:
        state='Продолжается' if row['closed'] is None else stamp(row['closed'])
        if row['resolution']=='removed':state+=' · исключено из мониторинга'
        result+='<tr><td>'+esc(stamp(row['opened']))+'</td><td>'+esc(state)+'</td><td>'+esc(duration(max(0,(row['closed'] if row['closed'] is not None else end)-row['opened'])))+'</td><td>'+esc(row['message'])+'</td></tr>'
    result+='</table></div><p class="muted legend">Последние 50 интервалов; длительность считается с первого обнаружения проблемы. Изменение правил не считается восстановлением. Для связи инцидент начинается после 3 минут без отчётов; процент доступности выше учитывает пропуски уже после 30 с.</p></div>'
    return result


def summary_html(rows,now):
    from .dashboard import esc
    from urllib.parse import quote
    incidents,_,_=current(rows,[],now)
    priority={'connection':0,'backup':0,'service':1,'cpu_percent':1,'memory_percent':1,'disk':2}
    labels=['Критично','Высокий','Внимание']
    items=[]
    for key,(agent,message) in incidents.items():
        rank=priority.get(key.split(':')[0],2)
        items.append((rank,agent,message))
    from .stability import agent_health
    for row in rows:
        data=json.loads(row['data'] or '{}');age,errors=agent_health(data,row['received'],now)
        if age is not None and age<180:
            if age>30:items.append((1,row['id'],'Задержка отчётов агента: '+str(int(age))+' с'))
            if errors:items.append((2,row['id'],'Недоступен сбор: '+', '.join(errors)))
    items.sort()
    counts=[sum(rank==i for rank,_,_ in items) for i in range(3)]
    content='<section class="problem-summary"><header><h2>Проблемы <span class="count">'+str(len(items))+'</span></h2>'
    if not items:return content+'<span class="text-normal">Всё в порядке</span></header></section>'
    content+='<span class="problem-counts">'+esc(' · '.join(labels[i]+': '+str(n) for i,n in enumerate(counts) if n))+'</span></header>'
    names={row['id']:(json.loads(row['data'] or '{}').get('hostname') or row['id']) for row in rows}
    def line(item):
        rank,agent,message=item
        short=message.removeprefix(names.get(agent,agent)+' ('+agent+')').lstrip(' :·')
        short=' '.join(short.split())
        if len(short)>140:short=short[:137]+'…'
        return '<a class="problem-summary-row" href="/servers/'+esc(quote(agent,safe=''))+'" title="'+esc(message)+'"><span class="badge '+('danger' if rank==0 else 'warning')+'">'+labels[rank]+'</span><b>'+esc(agent)+'</b><span>'+esc(short)+'</span></a>'
    content+=''.join(line(item) for item in items[:3])
    if len(items)>3:
        content+='<details class="problem-more"><summary>Ещё '+str(len(items)-3)+'</summary>'+''.join(line(item) for item in items[3:20])
        if len(items)>20:content+='<p class="muted">Остальные — в карточках серверов.</p>'
        content+='</details>'
    return content+'</section>'
