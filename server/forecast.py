"""Hourly free-space regression with explicit data-quality gates."""
import math
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
    if len(rows) < 12 or rows[-1]['timestamp']-rows[0]['timestamp'] < 86400:
        return {'status': 'insufficient'}
    if rows[-1]['free'] <= 0:
        return {'status': 'full', 'days': 0}
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
        GROUP BY path,hour ORDER BY hour''', (agent, now-7*86400, now)).fetchall()
    disks = {}
    for row in rows:
        if row['total'] and row['free'] is not None:
            disks.setdefault(row['path'], []).append(dict(row))
    return {path: predict(samples) for path,samples in disks.items()}


def forecast_html(forecasts, stale=False):
    content = '<section class="extended"><h3>Прогноз заполнения дисков</h3>'
    if stale:
        return content + '<p class="muted">Нет связи с агентом: актуальный прогноз недоступен.</p></section>'
    if not forecasts:
        return content + '<p class="muted">Недостаточно истории: нужно не менее 24 часов измерений.</p></section>'
    labels = {'insufficient':'Недостаточно истории: нужно ≥24 ч и ≥12 часовых точек',
              'stable':'Устойчивого уменьшения свободного места нет',
              'unstable':'Нагрузка меняется: надёжный линейный прогноз недоступен',
              'full':'Свободного места не осталось'}
    for path, forecast in forecasts.items():
        if forecast['status']=='estimated':
            days=forecast['days']
            text = ('Более года до заполнения' if days>365 else f'Примерно {days:.1f} дн. до заполнения') + ' · расход ' + size(forecast['bytes_per_day']) + '/сутки'
        else:
            text=labels[forecast['status']]
        content += '<p><b>' + esc(path) + '</b> · ' + esc(text) + '</p>'
    return content + '<p class="muted legend">Оценка по часовым средним за последние 7 дней, не гарантия. Удаления, рост БД и очистка бэкапов меняют прогноз.</p></section>'
