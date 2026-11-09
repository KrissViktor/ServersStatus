"""Lazy logical-CPU charts, exact historical reports and no invented topology."""
import json
import time
from urllib.parse import quote
from fastapi import HTTPException,Request,Query
from fastapi.responses import JSONResponse
from .access import can_history
from .dashboard import esc
from .task_graph import graph



def controls(row,historical=False):
    if not can_history():return ''
    identifier=dict(row).get('snapshot_report_id')
    if historical and not identifier:return ''
    url='/api/servers/'+quote(row['id'],safe='')+'/cpu-cores'
    if historical:url+='?report_id='+str(identifier)
    return '<details class="cpu-breakdown" data-fold-key="'+esc('cpu-cores:'+row['id']+':'+str(identifier or 'live'))+'" data-cpu-cores data-cpu-url="'+esc(url)+'"'+(' data-cpu-historical' if historical else '')+'><summary>По ядрам · логические процессоры</summary><div class="cpu-cores-content"><p class="muted">Раскройте для загрузки.</p></div></details>'


def render(c,agent,identifier=None,offset=0):
    if identifier is not None:
        row=c.execute('SELECT received,data FROM reports WHERE rowid=? AND agent=?',(identifier,agent)).fetchone()
    else:
        row=c.execute('SELECT received,data FROM current_reports WHERE agent=?',(agent,)).fetchone()
    if not row:raise HTTPException(404,'Отчёт не найден')
    data=json.loads(row['data']);values=data.get('cpu_per_core') or []
    if not values:
        message='В этом снимке нагрузка по логическим процессорам не сохранялась. Новые данные появятся после обновления агента.' if identifier else 'Агент ещё не прислал нагрузку по логическим процессорам. Обновите агент и дождитесь нового отчёта.'
        if 'cpu_per_core_v1' in data.get('features',[]):message='В этом отчёте агент не смог получить нагрузку логических процессоров. Проверьте журнал агента; текущие значения вместо исторических не подставляются.'
        return {'html':'<p class="muted">'+message+'</p>','count':0}
    offset=min(offset,((len(values)-1)//32)*32)
    center=row['received'] if identifier else time.time();start=center-300;end=center+300 if identifier else center
    # Bounded scans around the selected moment, only array metrics, no inventories.
    fields="rowid AS report_id,received,json_extract(data,'$.cpu_per_core') AS cores"
    rows=list(c.execute(f'SELECT {fields} FROM reports WHERE agent=? AND received>=? AND received<? ORDER BY received DESC,rowid DESC LIMIT 450',(agent,start,center)))
    rows+=list(c.execute(f'SELECT {fields} FROM reports WHERE agent=? AND received>=? AND received<=? ORDER BY received,rowid LIMIT 450',(agent,center,end)))
    samples=[]
    for item in rows:
        array=json.loads(item['cores'] or '[]')
        # Changes in CPU count are gaps, not reassigned old CPU indices.
        if len(array)!=len(values):array=[]
        samples.append({'timestamp':item['received'],'report_id':item['report_id'],'cores':array})
    buckets={}
    for point in sorted(samples,key=lambda p:p['timestamp']):buckets[int((point['timestamp']-start)//10)]=point
    samples=list(buckets.values())
    if identifier:samples=[p for p in samples if int((p['timestamp']-start)//10)!=30]+[{'timestamp':center,'report_id':identifier,'cores':values}]
    system=data.get('system') or {};physical=system.get('physical_cores')
    description=str(len(values))+' логических процессоров'+(' · физических ядер: '+str(physical) if physical else '')
    content='<p class="muted cpu-topology">'+esc(description)+'. Индексы логических процессоров из отчёта агента.</p><div class="cpu-core-grid">'
    for index in range(offset,min(offset+32,len(values))):
        value=values[index]
        points=[{'timestamp':p['timestamp'],'report_id':p['report_id'],'cpu':p['cores'][index] if p['cores'] else None} for p in samples]
        current=f'{value:.1f}%' if value is not None else 'Нет данных'
        attrs=' data-detail-metric="cpu_core" data-detail-name="'+str(index)+'" data-detail-first="'+str(row['received'])+'" data-detail-last="'+str(row['received'])+'" data-detail-count="30" data-detail-title="Логический процессор '+str(index)+'"'
        if identifier:attrs+=' data-detail-report="'+str(identifier)+'"'
        content+='<section class="cpu-core"><div><button type="button" class="cpu-core-open"'+attrs+'>CPU '+str(index)+'</button><span>'+esc(current)+'</span></div><div class="task-plot">'+graph(points,'cpu',center,snapshot=identifier is not None,core=index)+'</div></section>'
    content+='</div>'
    if offset or len(values)>32:
        content+='<div class="cpu-core-pages">'
        if offset:content+='<button type="button" data-core-page="'+str(max(0,offset-32))+'">← Предыдущие</button>'
        content+='<span>'+str(min(offset+1,len(values)))+'–'+str(min(offset+32,len(values)))+' из '+str(len(values))+'</span>'
        if offset+32<len(values):content+='<button type="button" data-core-page="'+str(offset+32)+'">Следующие →</button>'
        content+='</div>'
    content+='<p class="muted cpu-core-axis">'+('−5 минут · Снимок по центру · +5 минут' if identifier else 'Последние 5 минут · справа последние измерения')+'</p>'
    return {'html':content,'count':len(values),'received':row['received'],'historical':identifier is not None,'offset':offset}


def register(app,db,authenticated):
    @app.get('/api/servers/{agent}/cpu-cores')
    def view(agent:str,request:Request,report_id:int|None=Query(default=None,ge=1),offset:int=Query(default=0,ge=0,le=1023)):
        if not authenticated(request):raise HTTPException(401)
        if not can_history():raise HTTPException(403)
        with db() as c:result=render(c,agent,report_id,offset)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
