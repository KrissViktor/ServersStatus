"""On-demand maintenance priorities from current reports and incident history."""
import json
from urllib.parse import quote

from .backup_status import schedule_status
from .dashboard import backup_problems, duration, esc, page
from .disks import monitored_disks
from .fleet import group_select, members
from .forecast import load_forecasts
from .incident_history import incident_url
from .server_names import display_name
from .windows_ui import stamp

WEEK = 7 * 86400


def collect(c, group, now):
    disks, backups, recurring, stale = [], [], [], []
    for member in members(c,group):
        agent = member['id']
        url = '/servers/'+quote(agent,safe='')
        current = c.execute('''SELECT a.id,p.display_name,r.received,r.data
            FROM agents a LEFT JOIN current_reports r ON r.agent=a.id
            LEFT JOIN agent_profiles p ON p.agent=a.id
            LEFT JOIN agent_flags f ON f.agent=a.id
            WHERE a.id=? AND COALESCE(f.active,1)=1''',(agent,)).fetchone()
        if current is None:
            continue
        name = display_name(current)
        for event in c.execute('''SELECT COUNT(*) AS episodes, MAX(id) AS latest
            FROM incident_history WHERE agent=? AND opened>=? AND opened<=?
            GROUP BY key HAVING COUNT(*)>=2''',(agent,now-WEEK,now)):
            latest = c.execute('SELECT message FROM incident_history WHERE id=?',(event['latest'],)).fetchone()
            message = ' '.join(latest['message'].split())
            recurring.append((event['episodes'], name, incident_url(agent,event['latest']), message))

        received = current['received']
        if received is None or now-received>=180:
            stale.append((name,url,received))
            continue
        data = json.loads(current['data'])
        for backup in data.get('backups',[]):
            _, deadline, overdue, _ = schedule_status(backup,received,now)
            problems = backup_problems(backup,now-received)
            if not problems and not overdue:
                continue
            reason = 'Просрочка '+duration(overdue)+' · срок '+stamp(deadline) if overdue else ' · '.join(problems)
            label = str(backup.get('name') or backup.get('path') or 'Резервная копия')
            backups.append((overdue or 0,name,url+'#backups',label+' · '+reason))

        monitored = monitored_disks(data)
        if not monitored:
            continue
        forecasts = load_forecasts(c,agent,now)
        for disk in monitored:
            path = str(disk.get('path',''))
            forecast = forecasts.get(path,{})
            if forecast.get('status') not in ('estimated','full') or forecast['days']>7:
                continue
            days = forecast['days']
            reason = 'Свободное место исчерпано' if forecast['status']=='full' else 'По текущему тренду осталось '+f'{days:.1f} дн.'
            disks.append((days,name,url,path+' · '+reason))
    disks.sort()
    backups.sort(key=lambda item:(-item[0],item[1],item[3]))
    recurring.sort(key=lambda item:(-item[0],item[1],item[3]))
    return disks,backups,recurring,stale


def render(c, group, now):
    disks,backups,recurring,stale = collect(c,group,now)
    content = (
        '<header class="topbar"><a class="brand" href="/">ServersStatus</a></header>'
        '<div class="heading"><h1>План на неделю</h1></div>'
        '<form class="fleet-filter">'+group_select(c,group)+'<button>Показать</button></form>'
        '<p class="muted">На '+esc(stamp(now))+' · прогноз дисков на 7 дней, повторения за последние 7 дней</p>'
    )
    sections = [
        ('Диски с риском заполнения', [(name,url,reason) for _,name,url,reason in disks], 'Подтверждённых прогнозов заполнения на эту неделю нет.'),
        ('Бэкапы требуют проверки', [(name,url,reason) for _,name,url,reason in backups], 'В свежих отчётах проблем с файлами копий нет.'),
        ('Повторяющиеся сбои', [(name,url,str(count)+' эпизода(-ов) · '+reason) for count,name,url,reason in recurring], 'Повторяющихся инцидентов за неделю нет.'),
    ]
    if stale:
        sections.append(('Серверы без свежих данных', [
            (name,url,'Последний отчёт '+stamp(received) if received else 'Отчётов пока нет') for name,url,received in stale
        ], ''))
    for title,items,empty in sections:
        content += '<section class="server weekly-plan"><h2>'+title+'</h2>'
        if not items:
            content += '<p class="muted">'+empty+'</p>'
        else:
            content += '<ul>'+''.join(
                '<li><a href="'+esc(url)+'"><b>'+esc(name)+'</b><span>'+esc(reason)+'</span></a></li>'
                for name,url,reason in items
            )+'</ul>'
        content += '</section>'
    return page(content)
