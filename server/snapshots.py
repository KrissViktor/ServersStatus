"""Read-only historical server snapshots and exact raw-report extrema."""
import json
import zlib
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException,Request,Query
from fastapi.responses import JSONResponse
from .dashboard import esc,size,server_card,resource_points
from .memory import RAM_USED_SQL,RAM_TOTAL_SQL


def extrema(c,agent,start,end):
    result={}
    for metric,path in [('cpu','$.cpu_percent'),('ram','$.memory_percent')]:
        for kind,order in [('min','ASC'),('max','DESC')]:
            row=c.execute(f"""SELECT rowid AS report_id,received AS timestamp,json_extract(data,'{path}') AS value
                FROM reports INDEXED BY reports_resource_metrics WHERE agent=? AND received>=? AND received<=?
                AND json_extract(data,'{path}') IS NOT NULL
                ORDER BY json_extract(data,'{path}') {order},received,rowid LIMIT 1""",(agent,start,end)).fetchone()
            if row:
                sizes=c.execute(f'SELECT {RAM_USED_SQL} AS ram_used_bytes,{RAM_TOTAL_SQL} AS ram_total_bytes FROM reports WHERE rowid=?',(row['report_id'],)).fetchone()
                result[metric+'_'+kind]={**dict(row),**dict(sizes)}
    return result


def missing_process_reason(c,agent,received):
    latest=c.execute('SELECT received,data FROM latest_processes WHERE agent=?',(agent,)).fetchone()
    first=c.execute('SELECT MIN(received) FROM process_history WHERE agent=?',(agent,)).fetchone()[0]
    if first is not None and received<first:
        when=datetime.fromtimestamp(first,timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
        return 'Этот отчёт старше начала истории процессов. Первые сохранённые процессы: '+when+'. Для более раннего момента список восстановить нельзя.'
    if latest is None:return 'Списки процессов от этого агента ещё не получены. Проверьте обновление агента, его журнал и разрешение /api/processes/ в reverse proxy.'
    data=json.loads(latest['data'])
    if not data.get('report_id') or data.get('report_received') is None:
        return 'Агент присылает только текущий список без привязки к отчёту. Обновите Windows/Linux-агент; для Raspberry Pi перезапустите serversstatus-host-monitor после git pull.'
    if abs(latest['received']-received)<30:
        return 'Процессы приходят отдельным запросом после метрик. Повторите открытие снимка через 10 секунд. Если список не появился, проверьте журнал агента.'
    return 'Для этого отчёта список процессов не был сохранён. Проверьте журнал агента и доступность /api/processes/. Текущие процессы в прошлый момент не подставляются.'


def surrounding_points(c,agent,received):
    # Two bounded scans retain the nearest reports on each side without loading
    # full JSON reports/inventories or letting another agent enter the snapshot.
    fields=f"rowid AS report_id,received AS timestamp,json_extract(data,'$.cpu_percent') AS cpu,json_extract(data,'$.memory_percent') AS ram,{RAM_USED_SQL} AS ram_used_bytes,{RAM_TOTAL_SQL} AS ram_total_bytes"
    before=c.execute(f"SELECT {fields} FROM reports INDEXED BY reports_resource_metrics WHERE agent=? AND received>=? AND received<? ORDER BY received DESC,rowid DESC LIMIT 450",(agent,received-300,received)).fetchall()
    after=c.execute(f"SELECT {fields} FROM reports INDEXED BY reports_resource_metrics WHERE agent=? AND received>=? AND received<=? ORDER BY received,rowid LIMIT 450",(agent,received,received+300)).fetchall()
    return sorted([dict(point) for point in before]+[dict(point) for point in after],key=lambda point:point['timestamp'])


def snapshot(c,agent,identifier):
    row=c.execute('SELECT rowid,received,data FROM reports WHERE rowid=? AND agent=?',(identifier,agent)).fetchone()
    if not row:raise HTTPException(404,'Отчёт не найден: он мог быть удалён по сроку хранения')
    data=json.loads(row['data']);data.pop('console',None)
    data['features']=[feature for feature in data.get('features',[]) if not feature.startswith('console')]
    name=c.execute('SELECT display_name FROM agent_profiles WHERE agent=?',(agent,)).fetchone()
    stamp=datetime.fromtimestamp(row['received'],timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
    card={'id':agent,'received':row['received'],'data':json.dumps(data),'display_name':name[0] if name else '','snapshot_report_id':identifier,'sparkline':surrounding_points(c,agent,row['received'])}
    center=resource_points({'received':row['received']},data)[0]
    center['report_id']=identifier
    card['sparkline']=sorted([point for point in card['sparkline'] if point['timestamp']!=row['received']]+[center],key=lambda point:point['timestamp'])
    content='<header class="snapshot-heading"><h2>Снимок · '+esc(stamp)+'</h2><p class="muted">Исходный отчёт #'+str(identifier)+'. Состояние на момент измерения.</p></header>'+server_card(card,row['received'],historical=True)
    process=c.execute('SELECT data,process_received FROM process_history WHERE report=? AND agent=? AND received=?',(identifier,agent,row['received'])).fetchone()
    compact=json.loads(zlib.decompress(process['data']).decode('utf-8')) if process else None
    process_result={'snapshot':compact,'received':row['received']}
    if compact is None:process_result['message']=missing_process_reason(c,agent,row['received'])
    elif compact.get('status')!='available':process_result['message']='В этом измерении агент не смог прочитать список процессов. Проверьте права службы агента.'
    elif 'archive_format' not in compact:compact['archive_format']='legacy_top'
    service=c.execute('SELECT received,data FROM service_history WHERE agent=? AND received<=? ORDER BY received DESC,id DESC LIMIT 1',(agent,row['received'])).fetchone()
    if service:
        services={'inventory':json.loads(zlib.decompress(service['data']).decode('utf-8')),'received':service['received']}
    else:
        services={'inventory':None,'received':None,'message':'Полный список служб для этого момента не сохранён. История служб начинается после обновления портала и первого сбора. Текущие службы в старый снимок не подставляются.'}
    from .task_manager import section
    content+=section(agent,{'processes':process_result,'services':services})
    return {'report_id':identifier,'received':row['received'],'html':content,'processes_available':compact is not None and compact.get('status','available')=='available'}



def register(app,db,authenticated):
    @app.get('/api/history/{agent_id}/snapshot')
    def view(agent_id:str,request:Request,report_id:int=Query(ge=1)):
        if not authenticated(request):raise HTTPException(401)
        with db() as c:result=snapshot(c,agent_id,report_id)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
