"""Compact current-state rows, sharing the overview filters."""
import json
from urllib.parse import quote
from .dashboard import esc,number,size,duration
from .disks import monitored_disks
from .access import can_history
from .stability import percentage


def sort_values(row,now):
    from .overview import issues
    data=json.loads(row['data'] or '{}')
    age=max(0,now-row['received']) if row['received'] is not None else None
    disks=monitored_disks(data)
    return {'name':(dict(row).get('display_name') or data.get('hostname') or row['id']).casefold(),
        'status':3 if age is None else 2 if age>=180 else 1 if age>30 else 0,
        'cpu':data.get('cpu_percent'),'ram':data.get('memory_percent'),
        'disk':max((number(disk.get('used_percent')) for disk in disks),default=None),
        'availability':dict(row).get('availability'),'age':age,'problems':len(issues(row,now))}


def pin_button(agent):
    return '<button type="button" class="server-pin" data-pin-server="'+esc(agent)+'" aria-pressed="false" aria-label="Закрепить сервер" title="Закрепить сервер">☆</button>'


def render(rows,now):
    columns=[('name','Сервер'),('status','Связь'),('cpu','CPU'),('ram','RAM'),('disk','Диски')]
    if can_history():columns.append(('availability','Доступность · 24 ч'))
    columns.append(('age','Последний отчёт'))
    result='<div id="server-table-view" class="server-table-view"><div class="table-scroll" tabindex="0" role="region" aria-label="Таблица серверов"><table class="metric-table fleet-table"><thead><tr>'
    result+=''.join('<th scope="col" aria-sort="none"><button type="button" data-server-sort="'+key+'">'+label+'<span class="sort-indicator" aria-hidden="true">↕</span></button></th>' for key,label in columns)+'</tr></thead><tbody>'
    for row in rows:
        data=json.loads(row['data'] or '{}');name=dict(row).get('display_name') or data.get('hostname') or row['id'];age=max(0,now-row['received']) if row['received'] is not None else None
        from .freshness import status as freshness_status
        state_key,color,state=freshness_status(row['received'],now)
        order={'fresh':0,'delayed':1,'stale':2,'unknown':3}[state_key]
        disks=monitored_disks(data);disk=max(disks,key=lambda item:number(item.get('used_percent'))) if disks else None
        attrs=sort_values(row,now)
        result+='<tr data-table-server-id="'+esc(row['id'])+'" '+('class="table-row-stale" ' if state_key=='stale' else '')+' '.join('data-sort-'+key+'="'+esc(value if value is not None else '')+'"' for key,value in attrs.items())+'>'
        result+='<td>'+pin_button(row['id'])+'<a href="/servers/'+esc(quote(row['id'],safe=''))+'">'+esc(name)+'</a><small>'+esc(row['id'])+(' · Не активный' if not dict(row).get('active',1) else '')+'</small></td><td><span class="badge '+color+'">● '+state+'</span></td>'
        for key in ('cpu_percent','memory_percent'):
            value=data.get(key);percent=number(value)
            result+='<td><span class="table-resource">'+(f'{percent:.1f}%' if value is not None else '—')+'</span>'+('<progress value="'+str(percent)+'" max="100" aria-label="'+('CPU' if key=='cpu_percent' else 'RAM')+'"></progress>' if value is not None else '')+'</td>'
        if disk:
            title='; '.join(str(item.get('path',''))+': '+size(item.get('free_bytes'))+' свободно' for item in disks)
            result+='<td title="'+esc(title)+'"><span class="text-'+('danger' if number(disk.get('used_percent'))>=95 else 'warning' if number(disk.get('used_percent'))>=85 else 'normal')+'">'+f'{number(disk.get("used_percent")):.1f}%'+'</span><small>'+esc(str(disk.get('path',''))+' · '+size(disk.get('free_bytes'))+' свободно')+(' · ещё '+str(len(disks)-1) if len(disks)>1 else '')+'</small></td>'
        else:result+='<td>—</td>'
        if can_history():result+='<td>'+esc(percentage(dict(row).get('availability')))+'</td>'
        result+='<td>'+esc(duration(age)+' назад' if age is not None else 'Нет данных')+'</td></tr>'
    return result+'</tbody></table></div><p class="muted table-hint">Нажмите заголовок для сортировки. Для дисков показан самый заполненный раздел. При потере связи отображаются последние, уже устаревшие показания.</p></div>'


def controls():
    from .ui_icons import icon
    result='<div class="layout-switch" role="group" aria-label="Вид серверов"><button type="button" data-server-layout="cards" aria-pressed="true" title="Карточки">'+icon('cards')+'<span>Карточки</span></button><button type="button" data-server-layout="table" aria-pressed="false" title="Компактная таблица">'+icon('table')+'<span>Таблица</span></button></div>'
    result+='<div class="density-switch" role="group" aria-label="Плотность карточек"><button type="button" data-density="normal" aria-pressed="true" title="Карточки с графиками">'+icon('chart')+'<span>Обычные</span></button><button type="button" data-density="compact" aria-pressed="false" title="Компактные карточки без графиков">'+icon('compact')+'<span>Компактные</span></button></div>'
    if can_history():
        for route,label,name in [('/heatmap','Карта','heatmap'),('/dependencies','Связи','dependencies')]:result+='<a class="overview-view-link" data-fleet-page="'+route+'" href="'+route+'">'+icon(name)+label+'</a>'
    result+='<a class="overview-view-link" data-fleet-page="/wallboard" href="/wallboard">'+icon('wallboard')+'Экран</a>'
    return result
