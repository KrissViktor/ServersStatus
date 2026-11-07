"""Server-rendered dashboard; all agent-provided text is escaped."""
from .disks import monitored_disks
import html
import json
import math
import time
from urllib.parse import quote
from pathlib import Path

CSS = Path(__file__).with_name('dashboard.css').read_text(encoding='utf-8')
REFRESH_SCRIPT = Path(__file__).with_name('refresh.js').read_text(encoding='utf-8')


def esc(value):
    return html.escape(str(value), quote=True)


def number(value):
    try:
        result = float(value)
        return max(0, result) if math.isfinite(result) else 0
    except (ValueError, TypeError):
        return 0


def size(value):
    value = number(value)
    for unit in ('Б', 'Кб', 'Мб', 'Гб', 'Тб', 'Пб'):
        if value < 1024 or unit == 'Пб':
            return f'{value:.1f} {unit}'
        value /= 1024


def duration(value):
    seconds = int(number(value))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days:
        return f'{days} д {hours} ч {minutes} мин'
    if hours:
        return f'{hours} ч {minutes} мин'
    return f'{minutes} мин' if minutes else f'{seconds} с'


def level(percent):
    return 'danger' if percent >= 95 else 'warning' if percent >= 85 else 'normal'


def meter(label,value,description,points=None,field='cpu',now=None):
    from .task_graph import graph
    percent=min(100,number(value))
    now=time.time() if now is None else now
    return f'<div class="metric task-metric task-{field}"><div class="metric-top"><span>{esc(label)}</span><strong>{percent:.1f}<small>%</small></strong></div><div class="task-scale"><span>100%</span></div><div class="task-plot">' + graph(points or [],field,now) + '</div><div class="task-axis"><span>5 минут</span><span>Сейчас</span></div><p class="muted task-description">' + esc(description) + '</p></div>'


def resource_points(row,data):
    cached=dict(row).get('sparkline')
    if cached is not None:
        return cached
    if row['received'] is None:
        return []
    return [{'timestamp':row['received'],'cpu':data.get('cpu_percent'),'ram':data.get('memory_percent')}]



def cpu_description(data):
    system = data.get('system') or {}
    frequency = number(system.get('cpu_current_mhz'))
    if frequency:
        return f'{frequency/1000:.2f} ГГц · частота ОС'
    maximum = number(system.get('cpu_max_mhz'))
    return f'До {maximum/1000:.2f} ГГц · максимум ОС' if maximum else 'Частота недоступна'


def memory_description(data):
    system = data.get('system') or {}
    total = number(system.get('memory_total_bytes'))
    if not total:
        return 'Объём RAM недоступен'
    used = system.get('memory_used_bytes')
    if used is None:
        used = max(0, total-number(system.get('memory_available_bytes')))
    return size(used) + ' / ' + size(total) + ' · занято / всего'

def page(content, refresh=False):
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + '<title>Статус серверов</title><style>' + CSS + '</style></head><body><main>' + content + ('<script>' + REFRESH_SCRIPT + '</script>' if refresh else '') + '<footer class="credits">Данный портал статусов серверов был создан: tg @kissviktor и ds _krissviktor.</footer></main></body></html>'


def login_page():
    return page('''<div class="login"><div class="logo">S<span>●</span></div><p class="eyebrow">SERVERSSTATUS</p><h1>Всё под контролем</h1><p class="muted">Войдите, чтобы увидеть состояние серверов</p><form method="post" action="/login"><label>Логин<input name="username" autocomplete="username" required autofocus></label><label>Пароль<input name="password" type="password" autocomplete="current-password" required></label><button class="primary">Войти</button></form><p class="muted footnote">Центр мониторинга инфраструктуры</p></div>''')


def backup_problems(backup, elapsed=0):
    """Evaluate latest report on every refresh, including time without contact."""
    state = backup.get('state', 'error')
    daily = backup.get('schedule', 'daily') == 'daily'
    limit_hours = number(backup.get('max_age_hours', 30))
    minimum = number(backup.get('min_size_bytes', 1024**3))
    age = number(backup.get('age_seconds')) + max(0, elapsed)
    problems = []
    if state == 'missing':
        problems.append('Бэкапы не делаются: файлы копий не найдены')
    elif daily and backup.get('file') and age > limit_hours * 3600:
        problems.append(f'Бэкапы не делаются: ежедневная копия старше {limit_hours:g} часов (' + duration(age) + ')')
    elif state == 'stale' and not daily:
        problems.append('Нет актуальной ежемесячной копии')
    if backup.get('file') and number(backup.get('size_bytes')) < minimum:
        problems.append(f'Ошибка бэкапа: размер файла меньше {minimum / 1024**3:g} Гб (' + size(backup.get('size_bytes')) + ')')
    if state == 'error':
        problems.append('Не удаётся проверить бэкапы: папка недоступна или ошибка чтения')
    if state == 'future':
        problems.append('Ошибка даты бэкапа: файл датирован будущим')
    return problems


def backup_alerts(rows, now):
    items = []
    for row in rows:
        data = json.loads(row['data']) if row['data'] else {}
        elapsed = max(0, now - row['received']) if row['received'] is not None else 0
        for backup in data.get('backups', []):
            problems = backup_problems(backup, elapsed)
            if not problems:
                continue
            name = backup.get('name') or backup.get('path', 'Бэкап')
            items.append('<li><strong>' + esc(data.get('hostname') or row['id']) + ' · ' + esc(name) + '</strong><ul>' + ''.join('<li>' + esc(problem) + '</li>' for problem in problems) + '</ul>' + ('<p>Нет связи с агентом — состояние рассчитано по последнему отчёту.</p>' if elapsed >= 180 else '') + '</li>')
    if not items:
        return ''
    return '<section class="backup-alarm" role="alert"><p class="eyebrow">ТРЕБУЕТСЯ ВНИМАНИЕ</p><h2>Ошибка резервного копирования</h2><ul>' + ''.join(items) + '</ul></section>'


def server_card(row, now):
    data = json.loads(row['data']) if row['data'] else {}
    data['disks'] = monitored_disks(data)
    age = max(0, now - row['received']) if row['received'] is not None else None
    online = age is not None and age < 180
    state = 'Нет данных' if age is None else 'Онлайн' if online else 'Нет связи'
    badge = 'normal' if online else 'danger' if age is not None else 'neutral'
    hostname = data.get('hostname') or row['id']
    title = dict(row).get('display_name') or hostname
    from .overview import issues
    problem_class = ' problem-server' if issues(row, now) else ''
    os_name = (data.get('system') or {}).get('os') or 'ОС неизвестна'
    content = f'<article class="server{problem_class}"><header class="server-head"><div><p class="eyebrow">{esc(os_name)} · АГЕНТ {esc(row["id"])}</p><h2>{esc(title)}</h2><p class="muted">{esc(hostname)}</p></div><span class="badge {badge}">● {state}</span></header>'
    content += f'<p class="history-link"><a class="nav-link" href="/history/{esc(quote(row["id"], safe=""))}">История нагрузки →</a></p>'
    if age is None:
        return content + '<div class="empty">Ожидаем первый отчёт агента</div></article>'
    content += f'<div class="timing"><span>Последний отчёт: <b>{duration(age)} назад</b></span><span>Время работы: <b>{duration(data.get("uptime_seconds"))}</b></span></div>'
    if not online:
        content += '<p class="notice">Данные устарели: агент не присылал отчёт более 3 минут.</p>'
    points=resource_points(row,data)
    content += '<div class="metrics">' + meter('Процессор', data.get('cpu_percent'), cpu_description(data),points,'cpu',now) + meter('Оперативная память', data.get('memory_percent'), memory_description(data),points,'ram',now) + '</div><section><h3>Диски <span class="count">' + str(len(monitored_disks(data))) + '</span></h3><div class="disks">'
    for disk in monitored_disks(data):
        percent = min(100, number(disk.get('used_percent')))
        content += f'<div class="disk"><div class="disk-title"><strong>{esc(disk.get("path", "—"))}</strong><span class="text-{level(percent)}">{percent:.1f}% занято</span></div><progress class="{level(percent)}" value="{percent}" max="100" aria-label="Занято на диске {esc(disk.get("path", ""))}"></progress><p class="muted">{esc(disk.get("filesystem") or "")}</p><p><b>{size(disk.get("free_bytes"))}</b> свободно <span class="muted">из {size(disk.get("total_bytes"))}</span></p></div>'
    content += '</div><p class="muted legend">Жёлтый: занято от 85% · Красный: от 95%</p></section><div class="secondary"><section><h3>Службы</h3>'
    services = data.get('services', [])
    if not services:
        content += '<p class="empty small">Контроль служб не настроен</p>'
    for service in services:
        state = service.get('status', 'unavailable')
        labels = {'running': 'Работает', 'stopped': 'Остановлена', 'paused': 'Приостановлена', 'unavailable': 'Недоступна'}
        content += f'<div class="list-row"><b>{esc(service.get("display_name") or service.get("name", "—"))}</b><span class="badge {"normal" if state == "running" else "warning"}">{esc(labels.get(state, state))}</span></div>'
    content += '</section><section><h3>Резервные копии</h3>'
    backups = data.get('backups', [])
    if not backups:
        content += '<p class="empty small">Папки бэкапов не настроены</p>'
    for backup in backups:
        state = backup.get('state', 'error')
        problems = backup_problems(backup, age)
        if problems:
            state = 'alarm'
        elif state == 'stale' and backup.get('schedule', 'daily') == 'daily':
            state = 'fresh'
        labels = {'alarm': 'Ошибка бэкапа', 'too_small': 'Размер меньше 1 Гб', 'fresh': 'Свежий файл', 'stale': 'Просрочен', 'observing': 'Проверяем стабильность', 'missing': 'Файл не найден', 'error': 'Ошибка чтения', 'future': 'Дата из будущего', 'empty': 'Пустой файл'}
        color = 'normal' if state == 'fresh' else 'danger' if state in ('alarm', 'too_small', 'stale', 'missing', 'error', 'future', 'empty') else 'warning'
        content += f'<div class="backup"><div class="list-row"><b>{esc(backup.get("name") or backup.get("path", "—"))}</b><span class="badge {color}">{esc(labels.get(state, state))}</span></div>'
        content += f'<p>{esc(backup.get("path", ""))}</p>'
        if backup.get('expected_since'):
            content += f'<p>Ожидается копия за 1-е число месяца от {esc(backup["expected_since"])}</p>'
        if backup.get('file'):
            content += f'<p>{esc(backup["file"])} · {size(backup.get("size_bytes"))} · {duration(backup.get("age_seconds"))} назад</p>'
        for problem in problems:
            content += '<p class="backup-error">' + esc(problem) + '</p>'
        content += '</div>'
    if backups:
        content += '<p class="muted legend">Свежесть файла не подтверждает возможность восстановления SQL.</p>'
    from .metrics_ui import extended_sections
    content += '</section></div>' + extended_sections(data) + '<details><summary>Исходный отчёт</summary><pre>' + esc(json.dumps(data, ensure_ascii=False, indent=2)) + '</pre></details></article>'
    return content


def dashboard(rows, q='', view='all'):
    now = time.time()
    online = sum(row['received'] is not None and now - row['received'] < 180 for row in rows)
    missing = sum(row['received'] is None for row in rows)
    attention = 0
    for row in rows:
        data = json.loads(row['data']) if row['data'] else {}
        if any(number(d.get('used_percent')) >= 85 for d in monitored_disks(data)):
            attention += 1
    header = '<header class="topbar"><a class="brand" href="/">S<span>●</span> <b>ServersStatus</b></a><a class="nav-link" href="/host">Raspberry Pi</a><a class="nav-link" href="/updates">Обновления</a><a class="nav-link" href="/bot">Бот</a><a class="nav-link" href="/events">Журнал событий</a><a class="nav-link" href="/agents">Управление агентами</a><form method="post" action="/logout"><button>Выйти</button></form></header><div class="heading"><div><p class="eyebrow">ИНФРАСТРУКТУРА</p><h1>Обзор серверов</h1><p class="muted">Состояние оборудования и резервных копий в одном месте</p></div><span class="refresh">↻ Обновление каждые 10 с</span></div>'
    stats = '<div class="stats">' + ''.join(f'<div class="stat"><span>{label}</span><strong class="text-{color}">{value}</strong></div>' for label, value, color in [('Всего серверов', len(rows), 'neutral'), ('Онлайн', online, 'normal'), ('Нет связи', len(rows) - online - missing, 'danger'), ('Диски от 85%', attention, 'warning')]) + '</div>'
    from .overview import compact_card, matches, search_form
    selected = [row for row in rows if matches(row, now, q, view)]
    cards = '<div class="server-grid">' + ''.join(compact_card(row, now) for row in selected) + '</div>'
    if not selected:
        cards = '<div class="empty">Нет серверов по выбранным условиям.</div>'
    from .overview import LIVE_SCRIPT
    cards = search_form(q, view, len(selected), len(rows)) + '<div id="server-results">' + cards + '</div><script>' + LIVE_SCRIPT + '</script>'
    return page(header + '<div id="overview-alerts">' + backup_alerts(rows, now) + '</div><div id="overview-stats">' + stats + '</div>' + cards + '<footer>ServersStatus · Показатели на момент последнего отчёта агента</footer>')
