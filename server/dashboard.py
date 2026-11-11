"""Server-rendered dashboard; all agent-provided text is escaped."""
from .disks import monitored_disks
from .access import can_history,can_console
import html
import json
import math
import time
from urllib.parse import quote, urlencode
from pathlib import Path

CSS = Path(__file__).with_name('dashboard.css').read_text(encoding='utf-8')
PROTECTION_SCRIPT=Path(__file__).with_name('protection.js').read_text(encoding='utf-8')

FOLD_SCRIPT=Path(__file__).with_name('folding.js').read_text(encoding='utf-8')
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


def meter(label,value,description,points=None,field='cpu',now=None,snapshot=False,extra=''):
    from .task_graph import graph
    percent=min(100,number(value))
    now=time.time() if now is None else now
    if not can_history():return f'<div class="metric current-metric"><div class="metric-top"><span>{esc(label)}</span><strong>{percent:.1f}<small>%</small></strong></div><p class="muted task-description">{esc(description)}</p></div>'
    axis_class='task-axis snapshot-axis' if snapshot else 'task-axis'
    axis='<span>−5 минут</span><span>Снимок</span><span>+5 минут</span>' if snapshot else '<span>5 минут</span><span>Сейчас</span>'
    return f'<div class="metric task-metric task-{field}"><div class="metric-top"><span>{esc(label)}</span><strong>{percent:.1f}<small>%</small></strong></div><div class="task-scale"><span>100%</span></div><div class="task-plot">' + graph(points or [],field,now,snapshot=snapshot) + '</div><div class="'+axis_class+'">'+axis+'</div><p class="muted task-description">' + esc(description) + '</p>'+extra+'</div>'


def resource_points(row,data):
    cached=dict(row).get('sparkline')
    if cached is not None:
        return cached
    if row['received'] is None:
        return []
    system=data.get('system') or {}
    total=system.get('memory_total_bytes')
    used=system.get('memory_used_bytes')
    if used is None and total:
        used=max(0,total-system['memory_available_bytes']) if system.get('memory_available_bytes') is not None else total*number(data.get('memory_percent'))/100
    return [{'timestamp':row['received'],'cpu':data.get('cpu_percent'),'ram':data.get('memory_percent'),'ram_used_bytes':used,'ram_total_bytes':total}]



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

def page(content, refresh=False, protection_entry=False):
    if '<header class="topbar"' in content:
        if can_history() and 'href="/admin"' not in content:
            content=content.replace('</header>','<a class="nav-link" href="/admin">Администрирование</a></header>',1)
        if can_console():
            visibility='data-protection-entry="true"' if protection_entry else 'hidden'
            content=content.replace('</header>',f'<button {visibility} type="button" id="protection-toggle" aria-haspopup="dialog" aria-controls="protection-dialog" class="protection-toggle" aria-label="Снять защиту" title="Снять защиту"><svg viewBox="0 0 24 24" aria-hidden="true"><path data-lock-shackle d="M7 10V7a5 5 0 0 1 10 0v3"/><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M12 14v3"/></svg></button></header>',1)
            content+='<dialog id="protection-dialog" aria-labelledby="protection-title"><button type="button" id="protection-close" aria-label="Закрыть окно">×</button><div id="protection-content"></div></dialog><script>'+PROTECTION_SCRIPT+'</script>'
    widget=''
    if can_history() and '<header class="topbar"' in content and 'data-ai-csrf=' not in content:
        widget=('<button type="button" id="ai-launcher" class="ai-launcher" aria-label="Открыть ИИ-помощника" aria-expanded="false" aria-controls="ai-widget">✦ <span>ИИ-помощник</span></button>'
                '<aside id="ai-widget" class="ai-widget" role="dialog" aria-modal="false" aria-labelledby="ai-widget-title" hidden><header class="ai-widget-head"><strong id="ai-widget-title">✦ ИИ-помощник</strong><span class="badge neutral" id="ai-state">Подключение…</span><a href="/ai" title="Открыть полную страницу" aria-label="Открыть полную страницу помощника">↗</a><button type="button" id="ai-widget-close" aria-label="Свернуть чат">−</button></header><div id="ai-widget-body"><p role="status">Загрузка чата…</p></div></aside><script>'
                +Path(__file__).with_name('ai_chat.js').read_text(encoding='utf-8')+'</script><script>'+Path(__file__).with_name('ai_widget.js').read_text(encoding='utf-8')+'</script>')
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + '<title>Статус серверов</title><style>' + CSS + '</style></head><body><main>' + content + '<script>'+FOLD_SCRIPT+'</script><script>'+Path(__file__).with_name('cpu_cores.js').read_text(encoding='utf-8')+'</script>'+('<script>' + REFRESH_SCRIPT + '</script>' if refresh else '') + '<footer class="credits">Данный портал статусов серверов был создан: tg @kissviktor и ds _krissviktor.</footer></main>'+widget+'</body></html>'


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


def server_card(row, now, rdp_access=None, historical=False, forecasts=None):
    data = json.loads(row['data']) if row['data'] else {}
    data['disks'] = monitored_disks(data)
    age = max(0, now - row['received']) if row['received'] is not None else None
    online = age is not None and age < 180
    state = 'Нет данных' if age is None else 'Онлайн' if online else 'Нет связи'
    badge = 'normal' if online else 'danger' if age is not None else 'neutral'
    if historical:state,badge='Снимок','neutral'
    hostname = data.get('hostname') or row['id']
    title = dict(row).get('display_name') or hostname
    from .overview import issues
    problem_class = ' problem-server' if issues(row, now) else ''
    os_name = (data.get('system') or {}).get('os') or 'ОС неизвестна'
    content = f'<article class="server{problem_class}"><header class="server-head"><div><p class="eyebrow">{esc(os_name)} · АГЕНТ {esc(row["id"])}</p><h2>{esc(title)}</h2><p class="muted">{esc(hostname)}</p></div><span class="badge {badge}">● {state}</span></header>'
    if can_history():content += f'<p class="history-link"><a class="nav-link" href="/history/{esc(quote(row["id"], safe=""))}">История нагрузки →</a></p>'
    if age is None:
        return content + '<div class="empty">Ожидаем первый отчёт агента</div></article>'
    if historical:
        from datetime import datetime,timezone,timedelta
        when=datetime.fromtimestamp(row['received'],timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
        content+=f'<div class="timing"><span>Отчёт: <b>{when}</b></span><span>Время работы на момент отчёта: <b>{duration(data.get("uptime_seconds"))}</b></span></div>'
    else:
        content += f'<div class="timing"><span>Последний отчёт: <b>{duration(age)} назад</b></span><span>Время работы: <b>{duration(data.get("uptime_seconds"))}</b></span></div>'
    if not online:
        content += '<p class="notice">Данные устарели: агент не присылал отчёт более 3 минут.</p>'
    points=resource_points(row,data)
    from .cpu_cores import controls as cpu_controls
    content += '<div class="metrics">' + meter('Процессор', data.get('cpu_percent'), cpu_description(data),points,'cpu',now,snapshot=historical,extra=cpu_controls(row,historical)) + meter('Оперативная память', data.get('memory_percent'), memory_description(data),points,'ram',now,snapshot=historical) + '</div><div class="server-information"><section><h3>Диски <span class="count">' + str(len(monitored_disks(data))) + '</span></h3><div class="disks">'
    for disk in monitored_disks(data):
        percent = min(100, number(disk.get('used_percent')))
        content += f'<div class="disk"><div class="disk-title"><strong>{esc(disk.get("path", "—"))}</strong><span class="text-{level(percent)}">{percent:.1f}% занято</span></div><progress class="{level(percent)}" value="{percent}" max="100" aria-label="Занято на диске {esc(disk.get("path", ""))}"></progress><p class="muted">{esc(disk.get("filesystem") or "")}</p><p><b>{size(disk.get("free_bytes"))}</b> свободно <span class="muted">из {size(disk.get("total_bytes"))}</span></p>'
        if forecasts is not None and can_history():
            from .forecast import disk_forecast_html
            content+=disk_forecast_html(forecasts.get(disk.get('path'),{'status':'insufficient'}),disk,not online)
        content+='</div>'
    content += '</div><p class="muted legend">Жёлтый: занято от 85% · Красный: от 95%</p></section>'
    from .temperatures import section as temperature_section
    content+='<div class="secondary fold-grid">'+temperature_section(data,historical=historical)+'<section><h3>Службы</h3>'
    services = data.get('services', [])
    if not services:
        content += '<p class="empty small">Контроль служб не настроен</p>'
    for service in services:
        state = service.get('status', 'unavailable')
        labels = {'running': '🟢 Работает', 'stopped': '🔴 Остановлена', 'paused': '🟡 На паузе', 'failed':'🔴 Ошибка','start_pending':'🟠 Запускается','stop_pending':'🟠 Останавливается','continue_pending':'🟠 Возобновляется','pause_pending':'🟠 Переход на паузу','unavailable': '⚪ Недоступна'}
        service_file = ('<small class="service-executable" title="'+('Процесс' if service.get('executable_source')=='process' else 'Из конфигурации службы')+'">'+esc(service['executable'])+'</small>') if service.get('executable') else ''
        content += f'<div class="list-row"><b>{esc(service.get("display_name") or service.get("name", "—"))}{service_file}</b><span class="badge {"normal" if state == "running" else "warning"}">{esc(labels.get(state, state))}</span></div>'
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
    if not historical or data.get('reboot_history'):
        from .stability import agent_panel,reboot_panel
        content+='</section><section><h3>Доступность и агент</h3>'+dict(row).get('stability_html','')+agent_panel(data,row['received'],now)+reboot_panel(data)
    from .application_checks import panel as check_panel
    if data.get('application_checks') or (not historical and can_history()):
        content+='</section><section><h3>Отклик приложений</h3>'+check_panel(data,row['id'] if can_history() else None,historical)
    if dict(row).get('equipment_history_html'):
        content+='</section><section><h3>Изменения комплектации</h3>'+row['equipment_history_html']
    from .metrics_ui import extended_sections
    content += '</section></div>' + extended_sections(data,rdp_access) + '</div><details class="raw-report"><summary>Исходный отчёт</summary><pre>' + esc(json.dumps(data, ensure_ascii=False, indent=2)) + '</pre></details></article>'
    from .folding import fold_sections
    return fold_sections(content)


def overview_shortcuts():
    def icon(paths):
        return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths+'</svg>'
    compare=icon('<path d="M4 19V9m5 10V5m6 14v-7m5 7V3M2 21h20"/>')
    daily=icon('<rect x="3" y="4" width="18" height="17" rx="3"/><path d="M7 2v4m10-4v4M3 10h18m-14 5h3m4 0h3m-10 3h3"/>')
    arrow=icon('<path d="m9 5 7 7-7 7"/>')
    groups=icon('<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>')
    result='<div id="overview-tools" class="overview-tools"><nav class="overview-shortcuts" aria-label="Аналитика серверов">'
    for url,title,description,svg in [('/compare','Сравнение','Нагрузки и доступность',compare),('/daily','Сводка за сутки','События и изменения',daily)]:
        result+='<a class="overview-shortcut" href="'+url+'"><span class="shortcut-icon">'+svg+'</span><span class="shortcut-copy"><strong>'+title+'</strong><small>'+description+'</small></span><span class="shortcut-arrow">'+arrow+'</span></a>'
    return result+'</nav><a class="overview-groups" href="/groups">'+groups+'<span>Группы</span></a></div>'


def dashboard(rows, q='', view='all', group='', news_html=''):
    all_rows=rows
    if group:rows=[row for row in rows if group in [item['id'] for item in dict(row).get('groups',[])]]
    now = time.time()
    online = sum(row['received'] is not None and now - row['received'] < 180 for row in rows)
    missing = sum(row['received'] is None for row in rows)
    attention = 0
    for row in rows:
        data = json.loads(row['data']) if row['data'] else {}
        if any(number(d.get('used_percent')) >= 85 for d in monitored_disks(data)):
            attention += 1
    header = '<header class="topbar"><a class="brand" href="/">S<span>●</span> <b>ServersStatus</b></a><a class="nav-link" href="/admin">Администрирование</a><form method="post" action="/logout"><button>Выйти</button></form></header><div class="overview-commandbar"><div class="heading"><h1>Обзор серверов</h1><span class="refresh" title="Автообновление каждые 10 секунд">↻ 10 с</span></div>'
    header=header.replace('<form method="post" action="/logout">',news_html+'<form method="post" action="/logout">')
    if not can_history():header=header.replace('<a class="nav-link" href="/admin">Администрирование</a>','')
    if can_history():header+=overview_shortcuts()
    header+='</div>'
    if group:header=header.replace('href="/compare"','href="/compare?group='+esc(group)+'"').replace('href="/daily"','href="/daily?group='+esc(group)+'"')
    stats='<div class="stats">'
    for label,value,color,selection in [('Всего',len(rows),'neutral','all'),('Онлайн',online,'normal','online'),('Нет связи',len(rows)-online-missing,'danger','offline'),('Диски от 85%',attention,'warning','disks')]:
        query={**({'q':q} if q else {}),**({'group':group} if group else {}),**({'view':selection} if selection!='all' else {})}
        url='/'+('?' + urlencode(query) if query else '')
        current=' aria-current="true"' if view==selection else ''
        stats+='<a class="stat stat-filter" data-overview-view="'+selection+'" href="'+esc(url)+'"'+current+'><span>'+label+'</span><strong class="text-'+color+'">'+str(value)+'</strong></a>'
    stats+='</div>'
    from .overview import compact_card, matches, search_form
    selected = [row for row in rows if matches(row, now, q, view) and (not group or group in [item['id'] for item in dict(row).get('groups',[])])]
    active=[row for row in selected if dict(row).get('active',1)]
    inactive=[row for row in selected if not dict(row).get('active',1)]
    cards='<div class="server-grid" data-server-group="active">'+''.join(compact_card(row,now) for row in active)+'</div>'
    cards+='<details id="inactive-servers" class="inactive-servers" '+('hidden' if not inactive else '')+' '+('open' if inactive and (q or view!='all') else '')+'><summary>Не активные <span class="count">'+str(len(inactive))+'</span></summary><div class="server-grid" data-server-group="inactive">'+''.join(compact_card(row,now) for row in inactive)+'</div></details>'
    from .overview_table import render as table_render
    cards+=table_render(selected,now)
    cards+='<p class="empty empty-results" '+('hidden' if selected else '')+'>Нет серверов по выбранным условиям.</p>'
    from .overview import LIVE_SCRIPT
    cards = search_form(q, view, len(selected), len(rows), all_rows, group) + '<div id="server-results">' + cards + '</div><script>' + LIVE_SCRIPT + '</script>'
    from .incident_history import summary_html
    summary=summary_html([row for row in selected if dict(row).get('active',1)],now)
    from .drilldown import widget
    return page('<div class="overview-page">'+header+'<div class="overview-summary-row"><div id="overview-alerts">'+backup_alerts([row for row in rows if dict(row).get('important',1)],now)+summary+'</div><div id="overview-stats" role="group" aria-label="Фильтры по состоянию серверов">'+stats+'</div></div>'+cards+'</div>'+(widget('') if can_history() else '')+'<footer>ServersStatus · Показатели на момент последнего отчёта агента</footer>')
