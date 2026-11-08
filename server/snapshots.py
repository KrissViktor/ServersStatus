"""Read-only historical server snapshots and exact raw-report extrema."""
import json
import zlib
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException,Request,Query
from fastapi.responses import JSONResponse
from .dashboard import esc,size,server_card
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


def snapshot(c,agent,identifier):
    row=c.execute('SELECT rowid,received,data FROM reports WHERE rowid=? AND agent=?',(identifier,agent)).fetchone()
    if not row:raise HTTPException(404,'Отчёт не найден: он мог быть удалён по сроку хранения')
    data=json.loads(row['data']);data.pop('console',None)
    data['features']=[feature for feature in data.get('features',[]) if not feature.startswith('console')]
    name=c.execute('SELECT display_name FROM agent_profiles WHERE agent=?',(agent,)).fetchone()
    stamp=datetime.fromtimestamp(row['received'],timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
    card={'id':agent,'received':row['received'],'data':json.dumps(data),'display_name':name[0] if name else ''}
    content='<header class="snapshot-heading"><h2>Снимок · '+esc(stamp)+'</h2><p class="muted">Исходный отчёт #'+str(identifier)+'. Состояние на момент измерения.</p></header>'+server_card(card,row['received'],historical=True)
    process=c.execute('SELECT data,process_received FROM process_history WHERE report=? AND agent=? AND received=?',(identifier,agent,row['received'])).fetchone()
    compact=json.loads(zlib.decompress(process['data']).decode('utf-8')) if process else None
    content+='<section class="server snapshot-processes"><h3>Процессы в этом измерении</h3>'
    if compact is None:
        content+='<p class="muted">'+esc(missing_process_reason(c,agent,row['received']))+'</p>'
    elif compact.get('status','available')!='available':
        content+='<p class="muted">В этом измерении агент не смог прочитать список процессов. Проверьте права службы на сервере.</p>'
    else:
        content+='<p class="muted">Топ-10 по CPU и топ-10 по памяти. Всего процессов: '+str(compact['total'])+'; ограничены права: '+str(compact['unreadable'])+'. CPU — доля общей мощности сервера.</p>'
        if compact.get('truncated'):content+='<p class="notice">Исходный список был сокращён агентом; часть процессов может отсутствовать.</p>'
        by_pid={p['pid']:p for p in compact['items']}
        for key,title in [('cpu_pids','Наибольшая загрузка CPU'),('ram_pids','Наибольший объём памяти')]:
            content+='<h4>'+title+'</h4><div class="table-scroll"><table class="metric-table"><thead><tr><th>Процесс / PID</th><th>Пользователь</th><th>CPU</th><th>Память</th></tr></thead><tbody>'
            for pid in compact[key]:
                p=by_pid[pid]
                content+='<tr><td>'+esc(p['name'])+' · '+str(pid)+'</td><td>'+esc(p['username'] or '—')+'</td><td>'+esc(f"{p['cpu_percent']:.2f}%" if p['cpu_percent'] is not None else '—')+'</td><td>'+size(p['memory_bytes'])+'</td></tr>'
            content+='</tbody></table></div>'
        content+='<p class="muted legend">Процессы и общие метрики измеряются в одном цикле агента. Показатели помогают найти источник нагрузки; это снимок, а не трассировка всех событий.</p>'
    return {'report_id':identifier,'received':row['received'],'html':content+'</section>','processes_available':compact is not None and compact.get('status','available')=='available'}


def register(app,db,authenticated):
    @app.get('/api/history/{agent_id}/snapshot')
    def view(agent_id:str,request:Request,report_id:int=Query(ge=1)):
        if not authenticated(request):raise HTTPException(401)
        with db() as c:result=snapshot(c,agent_id,report_id)
        return JSONResponse(result,headers={'Cache-Control':'no-store'})
