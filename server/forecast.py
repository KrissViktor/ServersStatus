"""Hourly free-space regression with explicit data-quality gates."""
from datetime import datetime, timezone, timedelta
import hashlib
from .dashboard import esc, size

def predict(samples):
    if not samples:
        return {'status': 'insufficient'}
    ordered = sorted(samples, key=lambda s: s['timestamp'])
    total = ordered[-1]['total']
    # A resize invalidates measurements before it.
    start = 0
    for i in range(len(ordered)-1, -1, -1):
        if ordered[i]['total'] != total:
            start = i+1
            break
    rows = ordered[start:]
    if rows[-1]['free'] <= 0:
        return {'status': 'full', 'days': 0}
    if len(rows) < 12 or rows[-1]['timestamp']-rows[0]['timestamp'] < 86400:
        return {'status': 'insufficient'}
    origin = rows[0]['timestamp']
    x = [(s['timestamp']-origin)/86400 for s in rows]
    y = [s['free'] for s in rows]
    mx, my = sum(x)/len(x), sum(y)/len(y)
    slope = sum((a-mx)*(b-my) for a,b in zip(x,y))/sum((a-mx)**2 for a in x)
    if slope >= 0:
        return {'status': 'stable'}
    predicted = [my+slope*(a-mx) for a in x]
    variance = sum((b-my)**2 for b in y)
    quality = 1 - sum((b-p)**2 for b,p in zip(y,predicted))/variance if variance else 0
    if quality < .4 or len(rows)/(x[-1]*24+1) < .4:
        return {'status': 'unstable'}
    return {'status': 'estimated', 'days': rows[-1]['free']/-slope, 'bytes_per_day': -slope, 'quality': quality}


def load_forecasts(connection, agent, now):
    rows = connection.execute('''SELECT CAST(r.received/3600 AS INTEGER) AS hour,
        MAX(r.received) AS timestamp, json_extract(d.value,'$.path') AS path,
        AVG(json_extract(d.value,'$.free_bytes')) AS free,
        MAX(json_extract(d.value,'$.total_bytes')) AS total
        FROM reports r, json_each(r.data,'$.disks') d
        WHERE r.agent=? AND r.received>=? AND r.received<=?
        GROUP BY json_extract(d.value,'$.path'), CAST(r.received/3600 AS INTEGER) ORDER BY hour''', (agent, now-7*86400, now)).fetchall()
    disks = {}
    for row in rows:
        if row['total'] and row['free'] is not None:
            disks.setdefault(row['path'], []).append(dict(row))
    return {path: {**predict(samples), 'samples':len(samples),
        'hours':(samples[-1]['timestamp']-samples[0]['timestamp'])/3600,
        'change_bytes':samples[0]['free']-samples[-1]['free']} for path,samples in disks.items()}


def forecast_body(forecast,disk,stale=False):
    content=''
    if stale:content+='<p class="notice">Нет связи с агентом: данные устарели, сроки заполнения не рассчитываются.</p>'
    labels = {'insufficient':'Недостаточно истории: нужно ≥24 ч и ≥12 часовых точек',
              'stable':'Устойчивого уменьшения свободного места нет',
              'unstable':'Нагрузка меняется: надёжный линейный прогноз недоступен',
              'full':'Свободного места не осталось'}
    if not stale and forecast['status']=='estimated':
        rate=forecast['bytes_per_day']
        days=max(0,disk.get('free_bytes',rate*forecast['days']))/rate
        text='Более года до заполнения' if days>365 else f'Примерно {days:.1f} дн. до заполнения'
        content += '<p>'+esc(text)+'</p><p class="muted">Темп заполнения: '+size(rate)+'/сутки</p>'
        if disk.get('total_bytes'):
            for threshold in (95,98):
                remaining=(disk.get('free_bytes',0)-disk['total_bytes']*(1-threshold/100))/rate
                if remaining<=0:text='порог уже достигнут'
                elif remaining>365:text='более года'
                else:
                    date=(datetime.now(timezone(timedelta(hours=3)))+timedelta(days=remaining)).strftime('%d.%m.%Y %H:%M МСК')
                    text=f'примерно через {remaining:.1f} дн. · {date}'
                content += '<p class="muted">До '+str(threshold)+'%: '+esc(text)+'</p>'
        content += '<p class="muted">Соответствие линейному тренду: '+esc(f"{forecast['quality']*100:.0f}%")+'</p>'
    elif not stale:content += '<p>'+esc(labels[forecast['status']])+'</p>'
    if forecast.get('samples'):
        change=forecast['change_bytes']
        content += '<p class="muted">История: '+str(forecast['samples'])+' часовых точек за '+esc(f"{forecast['hours']:.1f}")+' ч. · '+('Места занято: ' if change>=0 else 'Освобождено: ')+size(abs(change))+'</p>'
    return content


def disk_forecast_html(forecast,disk,stale=False):
    path=str(disk.get('path',''))
    key='disk-forecast-'+hashlib.sha256(path.encode()).hexdigest()[:16]
    icon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4v16h16M7 15l4-4 4 2 5-7m-5 0h5v5"/></svg>'
    return '<details class="disk-forecast" data-fold-key="'+key+'"><summary title="Прогноз заполнения '+esc(path)+'">'+icon+'<span><b>Прогноз заполнения</b><small>Темп роста и сроки · подробнее</small></span><span class="disk-forecast-chevron" aria-hidden="true">›</span></summary><div class="disk-forecast-body">'+forecast_body(forecast,disk,stale)+'<p class="muted legend">Оценка по часовым средним за 7 дней. Удаления, рост БД и очистка бэкапов меняют прогноз.</p></div></details>'


def forecast_html(forecasts, stale=False, disks=None):
    content = '<section class="extended"><h3>Прогноз заполнения дисков</h3>'
    if stale:
        content += '<p class="notice">Нет связи с агентом: данные устарели, сроки заполнения не рассчитываются.</p>'
    current = {d.get('path'):d for d in disks} if disks is not None else {path:{} for path in forecasts}
    if not current:
        return content + '<p class="muted">Нет данных о дисках. Недостаточно истории: нужно не менее 24 часов измерений.</p></section>'
    content += '<div class="forecast-grid">'
    for path, disk in current.items():
        forecast=forecasts.get(path, {'status':'insufficient'})
        used=disk.get('used_percent')
        color='danger' if used is not None and used>=95 else 'warning' if used is not None and used>=85 else 'neutral'
        content += '<article class="forecast-disk"><header class="server-head"><h4>'+esc(path)+'</h4>'
        if used is not None:content += '<span class="badge '+color+'">'+esc(f'{used:.1f}% занято')+'</span>'
        content += '</header>'
        if disk.get('total_bytes'):
            content += '<p><b>'+size(disk.get('free_bytes'))+'</b> свободно из '+size(disk['total_bytes'])+'</p>'
        content+=forecast_body(forecast,disk,stale)
        content += '</article>'
    return content + '</div><p class="muted legend">Оценка по часовым средним за последние 7 дней, не гарантия. Сроки рассчитаны от последнего свободного места. Удаления, рост БД и очистка бэкапов меняют прогноз.</p></section>'
