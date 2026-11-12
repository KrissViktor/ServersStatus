"""Bounded access to original reports for interactive historical charts."""
import json
import math
from pathlib import Path
from urllib.parse import quote
from .dashboard import esc
from .assets import script
from .io_history import FIELDS

SCRIPT=Path(__file__).with_name('drilldown.js').read_text(encoding='utf-8')


def widget(agent):
    from .task_manager import assets
    return assets()+'<dialog id="chart-detail" aria-labelledby="chart-detail-title" data-url="/api/history/'+esc(quote(agent,safe=''))+'/detail"><header class="detail-chart-toolbar"><h2 id="chart-detail-title">Подробный график</h2><button type="button" data-detail-close aria-label="Закрыть график">Закрыть ×</button></header><div class="detail-chart-controls"><button type="button" data-pan="-1" aria-label="Предыдущие отчёты">← Раньше</button><button type="button" data-zoom="in">⊕ Приблизить</button><button type="button" data-zoom="out">⊖ Отдалить</button><button type="button" data-detail-reset>↺ Сброс</button><button type="button" data-pan="1" aria-label="Следующие отчёты">Позже →</button><span class="muted" id="detail-chart-count"></span></div><p class="muted" id="detail-chart-status" role="status" aria-live="polite"></p><div id="detail-chart-plot"></div><div id="detail-chart-tooltip" role="tooltip" hidden></div><p id="detail-point-info" class="muted">Наведите на точку для просмотра отчёта.</p><div class="detail-snapshot-actions"><button type="button" data-report-step="-1" disabled>‹ Предыдущий отчёт</button><button type="button" data-report-step="1" disabled>Следующий отчёт ›</button><button type="button" id="detail-snapshot" disabled>▣ Снимок отчёта</button><span id="detail-selected-label" class="muted"></span><button type="button" data-view-extreme="min">Минимум</button><button type="button" data-view-extreme="max">Максимум</button></div><section id="detail-snapshot-content" hidden></section><p class="muted detail-chart-help">Колесо мыши — масштаб · Потяните график — перемещение · Стрелки — предыдущий/следующий отчёт · До 900 исходных отчётов без усреднения. Разрывы — отсутствие данных.</p></dialog>'+script('drilldown.js')


def load_reports(connection, agent, center, count, metric, name='', first=None, last=None,selected_id=None):
    # Both scans use agent/time index and are bounded regardless of retention size.
    rows=list(connection.execute('SELECT rowid,received FROM reports WHERE agent=? AND received<? ORDER BY received DESC,rowid DESC LIMIT 900',(agent,center)))
    rows+=list(connection.execute('SELECT rowid,received FROM reports WHERE agent=? AND received>=? ORDER BY received,rowid LIMIT 900',(agent,center)))
    if selected_id is not None:
        selected=connection.execute('SELECT rowid,received FROM reports WHERE rowid=? AND agent=?',(selected_id,agent)).fetchone()
        if not selected:
            from fastapi import HTTPException
            raise HTTPException(404,'Отчёт больше недоступен')
        if not any(row['rowid']==selected_id for row in rows):rows.append(selected)
    rows.sort(key=lambda r:(0 if r['rowid']==selected_id else 1 if first is not None and last is not None and first<=r['received']<=last else 2,abs(r['received']-center),r['rowid']))
    chosen=sorted(rows[:count],key=lambda r:(r['received'],r['rowid']))
    percent=metric in ('cpu','ram','cpu_core')
    unit='%' if percent else 'оп/с' if metric.endswith('_iops') else 'bytes/s'
    def finite(value):return value if isinstance(value,(int,float)) and math.isfinite(value) else None
    points=[]
    for row in chosen:
        # Fetch only this report's requested group and RAM fields, never the
        # full 900-report JSON payload (which can include large inventories).
        path='$.cpu_per_core' if metric=='cpu_core' else '$.cpu_percent' if metric=='cpu' else '$.memory_percent' if metric=='ram' else '$.'+metric.split('.',1)[0]
        report=connection.execute("SELECT json_extract(data,?) AS value,json_extract(data,'$.cpu_percent') AS cpu,json_extract(data,'$.memory_percent') AS ram,json_extract(data,'$.system.memory_total_bytes') AS total,json_extract(data,'$.system.memory_used_bytes') AS used,json_extract(data,'$.system.memory_available_bytes') AS available FROM reports WHERE rowid=?",(path,row['rowid'])).fetchone()
        if metric=='cpu_core':
            values=json.loads(report['value'] or '[]');index=int(name)
            value=values[index] if index<len(values) else None
        elif percent:value=report['value']
        else:
            group,field=metric.split('.',1)
            value=next((device.get(field) for device in json.loads(report['value'] or '[]') if device.get('name')==name),None)
        point={'report_id':row['rowid'],'timestamp':row['received'],'value':finite(value),'cpu':finite(report['cpu']),'ram':finite(report['ram'])}
        total=finite(report['total']);used=finite(report['used'])
        if used is None and total:
            available=finite(report['available'])
            used=max(0,total-available) if available is not None else total*point['ram']/100 if point['ram'] is not None else None
        point.update(ram_used_bytes=used,ram_total_bytes=total)
        points.append(point)
    return {'points':points,'count':len(points),'requested':count,'limit':900,'unit':unit,'metric':metric,'name':name}


def register(app,db,authenticated):
    from fastapi import Request,HTTPException,Query
    from fastapi.responses import JSONResponse
    @app.get('/api/history/{agent_id}/detail')
    def detail(agent_id: str, request: Request, center: float, count: int=Query(default=30,ge=1,le=900), metric: str='cpu', name: str=Query(default='',max_length=256), first: float|None=None,last: float|None=None,report_id:int|None=Query(default=None,ge=1,le=9223372036854775807)):
        if not authenticated(request):raise HTTPException(401,'Войдите в панель')
        allowed={'cpu','ram','cpu_core'}|{group+'.'+field for group,fields in FIELDS.items() for field in fields}
        if metric not in allowed or any(value is not None and (not math.isfinite(value) or value<0 or value>4102444800) for value in (center,first,last)) or (first is not None and last is not None and first>last):
            raise HTTPException(400,'Некорректные параметры графика')
        if metric=='cpu_core' and (not name.isascii() or not name.isdigit() or len(name)>4 or not 0<=int(name)<1024):raise HTTPException(400,'Некорректный номер логического процессора')
        with db() as c:
            if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent_id,)).fetchone():raise HTTPException(404,'Агент не найден')
            result=load_reports(c,agent_id,center,count,metric,name,first,last,report_id)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
