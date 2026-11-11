"""Availability is coverage by received reports, never inferred from OS uptime."""
from urllib.parse import quote
from .dashboard import esc, duration
from .windows_ui import stamp

REPORT_GRACE = 30  # three normal ten-second reporting intervals


def load(c, agent, start, end, details=True):
    first = c.execute('SELECT received FROM reports WHERE agent=? ORDER BY received LIMIT 1', (agent,)).fetchone()
    latest = c.execute('SELECT received FROM current_reports WHERE agent=?', (agent,)).fetchone()
    known = [row[0] for row in (first, latest) if row is not None and row[0] is not None]
    if not known or min(known) > end:
        return {'start': start, 'end': end, 'percent': None, 'gaps': [], 'segments': [], 'reboots': [], 'covered': 0, 'missing': 0, 'longest': 0}
    from .portal_settings import retention_days
    start = max(start, min(known), end - retention_days(c)*86400)
    previous = c.execute('SELECT received FROM reports WHERE agent=? AND received<? ORDER BY received DESC LIMIT 1', (agent, start)).fetchone()
    timestamps = ([previous[0]] if previous else []) + [r[0] for r in c.execute('SELECT received FROM reports WHERE agent=? AND received>=? AND received<=? ORDER BY received', (agent, start, end))]
    if latest and latest[0] <= end and latest[0] not in timestamps:
        timestamps.append(latest[0]); timestamps.sort()
    covered = []
    for value in timestamps:
        a, b = max(start, value), min(end, value + REPORT_GRACE)
        if b <= a:
            continue
        if covered and a <= covered[-1][1]:
            covered[-1][1] = max(b, covered[-1][1])
        else:
            covered.append([a, b])
    gaps = []; cursor = start
    for a, b in covered:
        if a > cursor:
            gaps.append([cursor, a])
        cursor = b
    if cursor < end:
        gaps.append([cursor, end])
    seconds = sum(b-a for a,b in covered)
    total = max(0, end-start)
    reboots = []
    if details:
        # Only compare actual neighboring reports; no extrapolation across missing samples.
        before = c.execute("SELECT received,json_extract(data,'$.uptime_seconds') AS uptime FROM reports WHERE agent=? AND received<? ORDER BY received DESC LIMIT 1", (agent,start)).fetchone()
        last = before
        for row in c.execute("SELECT received,json_extract(data,'$.uptime_seconds') AS uptime FROM reports WHERE agent=? AND received>=? AND received<=? ORDER BY received", (agent,start,end)):
            if last is not None and isinstance(row['uptime'], (int,float)) and isinstance(last['uptime'], (int,float)):
                boot = row['received'] - row['uptime']; old_boot = last['received'] - last['uptime']
                reset = row['uptime'] + 5 < last['uptime']
                if (reset or boot > old_boot + 120) and last['received']-120 <= boot <= row['received']:
                    reboots.append({'at': boot, 'detected': row['received']})
            last = row
    return {'start':start, 'end':end, 'percent':100*seconds/total if total else None,
            'covered':seconds, 'missing':max(0,total-seconds), 'longest':max((b-a for a,b in gaps),default=0),
            'gaps':gaps, 'segments':covered, 'reboots':reboots}


def percentage(value):
    return 'Нет данных' if value is None else ('100%' if value == 100 else f'{min(value,99.99):.2f}%')


def render(info, agent, period='24h', base='servers'):
    from .history import PERIODS
    url = '/' + base + '/' + quote(agent, safe='')
    key = 'period' if base == 'history' else 'stability'
    links = ''.join(f'<a class="period {"selected" if p==period else ""}" href="{esc(url)}?{key}={p}">{label}</a>' for p,(label,_,_) in PERIODS.items())
    content = '<div class="stability-panel"><h3>Доступность по отчётам</h3><nav class="periods" aria-label="Период доступности">'+links+'</nav>'
    content += '<div class="stability-stats">' + ''.join('<div><span>'+label+'</span><strong>'+esc(value)+'</strong></div>' for label,value in [
        ('Подтверждённая доступность',percentage(info['percent'])), ('Без данных',duration(info['missing'])),
        ('Самый длинный пропуск',duration(info['longest'])), ('Пропусков / перезагрузок по аптайму',str(len(info['gaps']))+' / '+str(len(info['reboots'])))]) + '</div>'
    if info['percent'] is not None:
        content += '<div class="availability-strip" aria-label="Интервалы наличия отчётов">'
        span = max(1,info['end']-info['start'])
        # Fixed bins bound HTML even when a connection flaps thousands of times.
        for i in range(96):
            a=info['start']+span*i/96;b=info['start']+span*(i+1)/96
            seconds=sum(max(0,min(b,y)-max(a,x)) for x,y in info['segments'])
            state='normal' if seconds>=b-a-.001 else 'danger' if seconds==0 else 'warning'
            content+='<span class="'+state+'" title="'+esc(stamp(a)+' — '+stamp(b)+' · отчёты покрывают '+f'{seconds/(b-a)*100:.1f}%')+'"></span>'
        content+='</div><p class="muted">Учтённый период: '+esc(stamp(info['start']))+' — '+esc(stamp(info['end']))+'</p>'
    content+='<p class="muted legend">Ожидаемый интервал — 10 с. Отчёт подтверждает связь на 30 с вперёд; остальное время снижает процент. Зелёный — есть отчёты, жёлтый — частичный пропуск, красный — нет данных. До первого известного отчёта время не считается. Потеря связи, остановка агента и выключение сервера здесь неразличимы. Системный аптайм — отдельный показатель.</p>'
    if info['gaps']:
        content+='<details><summary>Пропуски отчётов · '+str(len(info['gaps']))+'</summary><div class="table-scroll"><table class="metric-table"><tr><th>Начало</th><th>Конец</th><th>Без данных</th></tr>'
        for a,b in reversed(info['gaps'][-50:]):
            content+='<tr><td>'+esc(stamp(a))+'</td><td>'+esc('Продолжается' if b==info['end'] else stamp(b))+'</td><td>'+esc(duration(b-a))+'</td></tr>'
        content+='</table></div><p class="muted">Последние 50 интервалов. Пропуски восстановлены из сохранённых отчётов, включая время остановки портала.</p></details>'
    if info['reboots']:
        content+='<details><summary>Перезагрузки по системному аптайму · '+str(len(info['reboots']))+'</summary>'
        for event in reversed(info['reboots'][-30:]):
            content+='<p>'+esc(stamp(event['at']))+' · предполагаемое время загрузки по аптайму</p>'
        content+='<p class="muted">Определены по сбросу аптайма более чем на 5 с или изменению времени загрузки более чем на 2 минуты. Смена часов или ошибки ОС могут влиять на оценку; причина проверяется по журналу Windows.</p></details>'
    return content+'</div>'


def agent_health(data, received, now):
    age = max(0, now-received) if received is not None else None
    checks = []
    for key,label in [('hardware','Комплектация'),('reboot_history','Журнал перезагрузок'),('windows_updates','Windows Update')]:
        value=data.get(key)
        if isinstance(value,dict) and value.get('status')=='unavailable':
            checks.append(label)
    probe=data.get('application_checks') or {}
    if probe.get('enabled') and (probe.get('checked_at') is None or now-probe['checked_at']>=180):checks.append('Проверки приложений: нет свежего результата')
    return age,checks


def agent_panel(data, received, now):
    age,checks = agent_health(data,received,now)
    state='Ожидаем первый отчёт' if age is None else 'Нет связи' if age>=180 else 'Отчёты задерживаются' if age>30 else 'На связи'
    facts=[('Состояние',state),('Версия',data.get('agent_version') or 'Не сообщается'),('Платформа',data.get('agent_platform') or 'Не сообщается'),('Последний отчёт',stamp(received) if received is not None else 'Нет данных'),('Возраст отчёта',duration(age) if age is not None else '—'),('Ожидаемый интервал','10 с'),('Ошибки чтения компонентов',', '.join(checks) if checks else 'Не заявлены агентом')]
    result='<div class="agent-health"><h3>Состояние агента</h3><dl class="system-facts">'+''.join('<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>' for k,v in facts)+'</dl>'
    if (data.get('system') or {}).get('os')=='Windows' and not data.get('reboot_history'):
        result+='<p class="muted">Обновите Windows-агент для причин перезагрузок.</p>'
    return result+'</div>'


def reboot_panel(data):
    info=data.get('reboot_history')
    if not info:
        return ''
    labels={'planned':'Штатное завершение / перезагрузка','unexpected':'Аварийное завершение','boot':'Запуск Windows','shutdown':'Остановка Windows','update':'Обновление / обслуживание ОС по коду причины Windows'}
    result='<div class="reboot-history"><h3>Журнал загрузок Windows</h3>'
    if info.get('status')!='available':
        return result+'<p class="muted">'+('Собираем сведения…' if info.get('status')=='checking' else 'Журнал System недоступен для чтения.')+'</p></div>'
    for item in info.get('events',[]):
        result+='<article class="event-row"><p><b>'+esc(labels.get(item['kind'],'Событие Windows'))+'</b> · '+esc(stamp(item['at']))+'</p><p class="muted">'+esc(item['source'])+' · ID '+str(item['event_id'])+'</p><p>'+esc(item.get('message') or 'Описание не предоставлено')+'</p>'+('<p class="muted">Причина: '+esc(item['reason_code'])+'</p>' if item.get('reason_code') else '')+('<p class="muted">Процесс: '+esc(item['process'])+'</p>' if item.get('process') else '')+'</article>'
    if not info.get('events'):
        result+='<p class="muted">За последние 30 дней подходящих событий не найдено.</p>'
    result+='<p class="muted legend">Последние 12 событий System; собрано '+esc(stamp(info.get('checked_at')))+'. Обновление каждые 15 минут. Несколько событий могут относиться к одной перезагрузке. Kernel-Power 41 и 6008 подтверждают нештатное завершение, но не устанавливают его причину.</p></div>'
    return result
