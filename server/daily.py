"""Calendar-day Moscow summary with a persistent multipart delivery queue."""
from datetime import datetime,timedelta,timezone
import json
import os
import time
from .dashboard import backup_problems,size
from .notification_types import DeliveryError
from .delivery_policy import delivery_window

MSK=timezone(timedelta(hours=3))


def build_summary(connection,start,end,now):
    day=datetime.fromtimestamp(start,MSK).strftime('%d.%m.%Y')
    lines=['📊 Статус серверов · отчёт за '+day+' (МСК)']
    warnings=connection.execute("SELECT COUNT(*) FROM events WHERE level='warning' AND received>=? AND received<?",(start,end)).fetchone()[0]
    lines.append(f'Всего событий проблем за сутки: {warnings}.')
    servers=connection.execute('SELECT a.id,p.display_name FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id ORDER BY a.id').fetchall()
    for server in servers:
        agent=server['id']
        stats=connection.execute('''SELECT COUNT(*) AS count,AVG(json_extract(data,'$.cpu_percent')) AS cpu,
             MAX(json_extract(data,'$.cpu_percent')) AS cpu_peak,AVG(json_extract(data,'$.memory_percent')) AS ram
             FROM reports WHERE agent=? AND received>=? AND received<?''',(agent,start,end)).fetchone()
        latest=connection.execute('SELECT data,received FROM current_reports WHERE agent=?',(agent,)).fetchone()
        lines.append('\n'+(server['display_name'] or agent))
        if stats['count']:
            lines.append(f'За сутки: отчётов {stats["count"]}; CPU ср. {stats["cpu"]:.1f}%, пик {stats["cpu_peak"]:.1f}%; RAM ср. {stats["ram"]:.1f}%.')
        else:
            lines.append('За сутки нет измерений.')
        count=connection.execute("SELECT COUNT(*) FROM events WHERE agent=? AND level='warning' AND received>=? AND received<?",(agent,start,end)).fetchone()[0]
        lines.append(f'Проблем за сутки: {count}.')
        if latest:
            data=json.loads(latest['data']);elapsed=max(0,now-latest['received'])
            lines.append('Сейчас: '+('онлайн' if elapsed<180 else 'нет связи'))
            for disk in data.get('disks',[]):
                lines.append(str(disk.get('path',''))+': свободно '+size(disk.get('free_bytes')))
            bad=sum(bool(backup_problems(b,elapsed)) for b in data.get('backups',[]))
            lines.append(f'Бэкапы сейчас: ошибок {bad}, проверок {len(data.get("backups",[]))}.')
            services=data.get('services',[])
            lines.append(f'Службы сейчас: не работают {sum(s.get("status")!="running" for s in services)} из {len(services)}.')
    chunks=[];text=''
    for line in lines:
        for offset in range(0,max(1,len(line)),3500):
            part=line[offset:offset+3500]
            if len(text)+len(part)+1>3800:
                chunks.append(text);text=''
            text+=('\n' if text else '')+part
    if text:chunks.append(text)
    return chunks


def deliver_daily(db,sender,now=None):
    real_clock=now is None
    now=time.time() if now is None else now
    if not delivery_window(now):
        return 0,0
    if os.environ.get('STATUS_DAILY_REPORT_ENABLED','1')=='0':
        return 0,0
    try:
        hour=int(os.environ.get('STATUS_DAILY_REPORT_HOUR','9'))
        if not 0<=hour<=23:return 0,0
    except ValueError:
        return 0,0
    current=datetime.fromtimestamp(now,MSK)
    with db() as c:
        if current.hour>=hour:
            end=current.replace(hour=0,minute=0,second=0,microsecond=0)
            start=end-timedelta(days=1);day=start.date().isoformat()
            if not c.execute('SELECT 1 FROM daily_delivery WHERE day=?',(day,)).fetchone():
                chunks=build_summary(c,start.timestamp(),end.timestamp(),now)
                c.execute('INSERT INTO daily_delivery VALUES (?,?,0,0,0)',(day,json.dumps(chunks,ensure_ascii=False)))
        pending=c.execute('SELECT * FROM daily_delivery WHERE completed=0 AND retry_at<=? ORDER BY day LIMIT 1',(now,)).fetchone()
    if not pending:return 0,0
    chunks=json.loads(pending['chunks'])
    count=0
    for index in range(pending['next_part'],min(len(chunks),pending['next_part']+5)):
        if real_clock and not delivery_window(time.time()):
            break
        try:
            sender(chunks[index])
        except DeliveryError as error:
            with db() as c:
                c.execute('UPDATE daily_delivery SET retry_at=? WHERE day=?',(now+error.retry_after,pending['day']))
            return count,1
        count+=1
        with db() as c:
            c.execute('UPDATE daily_delivery SET next_part=?,completed=? WHERE day=?',(index+1,int(index+1==len(chunks)),pending['day']))
    return count,0
