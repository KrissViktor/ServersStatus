"""Compact overview and detailed server pages."""
from .disks import monitored_disks
from .access import can_history,can_console
import json
import time
from pathlib import Path

LIVE_SCRIPT = Path(__file__).with_name("overview.js").read_text(encoding="utf-8")
from urllib.parse import quote
from .dashboard import esc, page, duration, size, number, meter, server_card, backup_problems, cpu_description, memory_description, resource_points


def issue_entries(row, now):
    data = json.loads(row['data']) if row['data'] else {}
    elapsed = max(0, now - row['received']) if row['received'] is not None else 0
    from .incidents import disk_key,incident_key,service_key
    import hashlib
    problems = []
    def add(key,message):
        if not dict(row).get('problem_states',{}).get(key,{}).get('acknowledged'):
            problems.append((key,message))
    if row['received'] is not None and elapsed >= 180:
        add('connection:'+row['id'],'Нет связи с агентом')
    if number(data.get('cpu_percent')) >= 95:
        add('cpu_percent:'+row['id'],'Высокая загрузка CPU')
    if number(data.get('memory_percent')) >= 95:
        add('memory_percent:'+row['id'],'Мало свободной RAM')
    for disk in monitored_disks(data):
        if number(disk.get('used_percent')) >= 85:
            add(disk_key(row['id'],str(disk.get('path',''))),'Заполнен диск ' + str(disk.get('path', '')))
    for backup in data.get('backups', []):
        if backup_problems(backup, elapsed):
            add(incident_key(row['id'],backup.get('path',backup.get('name',''))),'Ошибка бэкапа: ' + str(backup.get('name') or backup.get('path', '')))
    for service in data.get('services', []):
        if service.get('status') != 'running':
            add(service_key(row['id'],service.get('name','')),'Служба не работает: ' + str(service.get('name', '')))
    from .stability import agent_health
    age,errors=agent_health(data,row['received'],now)
    if age is not None and age<180:
        if age>30:add('report_delay:'+row['id'],'Задержка отчётов агента')
        for error in errors:add('collector:'+row['id']+':'+hashlib.sha256(error.encode()).hexdigest(),'Недоступен сбор: '+error)
    checks=data.get('application_checks') or {}
    if elapsed<180 and checks.get('checked_at') is not None and now-checks['checked_at']<180:
        for item in checks.get('items',[]):
            if item.get('status')=='failed':add('application:'+row['id']+':'+item['id'],'Не отвечает приложение: '+item['name'])
    return problems



def issues(row,now):
    return [message for _,message in issue_entries(row,now)]


def matches(row, now, query, view):
    data = json.loads(row['data']) if row['data'] else {}
    text = ' '.join(str(x or '') for x in (row['id'], dict(row).get('display_name'), data.get('hostname'))).casefold()
    if query.strip().casefold() not in text:
        return False
    if view == 'problems':
        return bool(issues(row, now))
    if view == 'online':
        return row['received'] is not None and now-row['received']<180
    if view == 'disks':
        return any(number(disk.get('used_percent'))>=85 for disk in monitored_disks(data))
    if view == 'offline':
        return row['received'] is not None and now - row['received'] >= 180
    return True


def search_form(query, view, shown, total, rows=None, group=''):
    options = ''.join(f'<option value="{value}" {"selected" if value == view else ""}>{label}</option>' for value, label in [('all', 'Все серверы'), ('online','Онлайн'), ('offline', 'Нет связи'), ('problems', 'Есть проблемы'), ('disks','Диски от 85%')])
    groups={item['id']:item['name'] for row in (rows or []) for item in dict(row).get('groups',[])}
    group_control='<label>Группа<select name="group"><option value="">Все группы</option>'+''.join('<option value="'+esc(key)+'" '+('selected' if key==group else '')+'>'+esc(name)+'</option>' for key,name in groups.items())+'</select></label>'
    from .overview_table import controls
    tools=controls()
    from .access import current_user
    import hashlib
    scope=hashlib.sha256((current_user().get('name') or 'local').encode()).hexdigest()[:16]
    problem_url='/?view=problems'+('&group='+quote(group,safe='') if group else '')
    ordering='<div class="overview-order"><a class="nav-link overview-problem-shortcut" data-overview-view="problems" href="'+esc(problem_url)+'">Показать проблемы</a><label>Порядок<select data-overview-sort aria-label="Сортировка серверов">'+''.join('<option value="'+key+'">'+label+'</option>' for key,label in [('name','По названию'),('problems','По числу проблем'),('status','По состоянию связи'),('cpu','По загрузке CPU'),('ram','По занятости RAM'),('disk','По заполнению дисков'),('availability','По доступности'),('age','По возрасту отчёта')])+'</select></label><button type="button" data-overview-direction aria-label="Изменить направление сортировки">По возрастанию ↑</button><span class="muted">★ Закреплённые — первыми. Настройки сохраняются в этом браузере.</span></div>'
    return f'<form class="searchbar" data-preference-scope="{scope}" method="get" action="/"><label>Поиск<input aria-label="Поиск по названию или имени" name="q" value="{esc(query)}" maxlength="200" placeholder="SQL, ERP, WIN-…" type="search"></label><label>Показать<select name="view">{options}</select></label>{group_control}<noscript><button>Найти</button></noscript><a class="nav-link" href="/" data-overview-reset>Сбросить</a></form><p class="muted search-status" role="status" aria-live="polite"></p><div class="overview-resultbar"><p class="muted result-count">Показано {shown} из {total}</p>{tools}</div>{ordering}'


def compact_card(row, now, csrf=""):
    data = json.loads(row['data']) if row['data'] else {}
    hostname = data.get('hostname') or row['id']
    title = dict(row).get('display_name') or hostname
    url = '/servers/' + quote(row['id'], safe='')
    age = max(0, now-row['received']) if row['received'] is not None else None
    from .freshness import status as freshness_status,line as freshness_line
    _,color,state=freshness_status(row['received'],now)
    problem_class = ' problem-server' if issues(row, now) else ''
    from .overview_table import sort_values,pin_button
    sort_attrs=' '.join('data-sort-'+key+'="'+esc(value if value is not None else '')+'"' for key,value in sort_values(row,now).items())
    content = f'<article class="server compact{problem_class}" data-server-id="{esc(row["id"])}" {sort_attrs}><header class="server-head"><div><h2><a href="{esc(url)}">{esc(title)}</a></h2><p class="muted">{esc(hostname)} · {esc(row["id"])}</p></div><div class="server-overview-status">{pin_button(row["id"])}<span class="badge {color}">● {state}</span></div></header>'
    if age is None:
        return content + '<p class="empty">Ожидаем первый отчёт агента</p><a class="nav-link" href="' + esc(url) + '">Открыть сервер →</a></article>'
    content+=freshness_line(row['received'],now)
    if age >= 180:
        content += '<p class="notice">Данные устарели — нет связи с агентом</p>'
    points=resource_points(row,data)
    from .cpu_cores import controls as cpu_controls
    content += '<div class="metrics">' + meter('CPU', data.get('cpu_percent'), cpu_description(data),points,'cpu',now,extra=cpu_controls(row)) + meter('RAM', data.get('memory_percent'), memory_description(data),points,'ram',now) + '</div>'
    content += '<div class="compact-disks">'
    for disk in monitored_disks(data):
        content += '<p><b>' + esc(disk.get('path', '')) + '</b><span>' + size(disk.get('free_bytes')) + ' свободно · ' + f'{number(disk.get("used_percent")):.1f}% занято' + '</span></p>'
    content += '</div>'
    from .problem_acknowledgements import control
    problems = issue_entries(row, now)
    if problems:
        def problem_line(item):
            key,message=item
            return '<li class="card-problem"><span>'+esc(message)+'</span>'+control(row,key,csrf)+'</li>'
        content += '<ul class="compact-issues">' + ''.join(problem_line(item) for item in problems[:3]) + '</ul>'
        if len(problems)>3:
            content+='<details class="card-more-problems"><summary>Ещё проблем: '+str(len(problems)-3)+'</summary><ul class="compact-issues">'+''.join(problem_line(item) for item in problems[3:])+'</ul></details>'

    else:
        content += '<p class="text-normal compact-ok">Проблем по полученным данным нет</p>'
    if can_history() and 'availability' in dict(row):
        from .stability import percentage
        content+='<p class="availability-brief">Доступность за 24 ч: <b>'+esc(percentage(row['availability']))+'</b></p>'
    content += '<p class="muted">Отчёт: ' + duration(age) + ' назад · В работе: ' + duration(data.get('uptime_seconds')) + '</p>'
    if not can_history():return content+f'<p class="history-link"><a class="nav-link" href="{esc(url)}">Открыть сервер →</a></p></article>'
    return content + f'<p class="history-link"><a class="nav-link" href="{esc(url)}">Открыть сервер →</a> <a class="nav-link" href="/history/{esc(quote(row["id"], safe=""))}">Графики нагрузки</a></p></article>'


def detail_page(row, csrf,console_access=False):
    identifier = quote(row['id'], safe='')
    title = dict(row).get('display_name') or ''
    content = '<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/">← Все серверы</a><a class="nav-link" href="/settings/' + esc(identifier) + '">Настройки мониторинга</a><a class="nav-link" href="/servers/' + esc(identifier) + '">Обновить данные</a></header>'
    if not can_history():content=content.replace('<a class="nav-link" href="/settings/'+esc(identifier)+'">Настройки мониторинга</a>','')
    data=json.loads(row['data'] or '{}')
    fallback_name=data.get('hostname') or row['id']
    name=title or fallback_name
    content+='<div class="panel-name-heading"><span>Панель:</span> '
    if can_history():
        content+=f'<button type="button" class="panel-name-trigger" title="Двойной щелчок — изменить название; Enter — редактировать" aria-label="Изменить название панели"><span class="panel-name-value">{esc(name)}</span></button><form class="panel-name-form" method="post" action="/servers/{esc(identifier)}/name" hidden><input type="hidden" name="csrf" value="{esc(csrf)}"><label class="sr-only" for="panel-name-input">Название панели</label><input id="panel-name-input" name="display_name" maxlength="120" value="{esc(title)}" placeholder="{esc(fallback_name)}"><button type="submit">Сохранить</button><button type="button" data-name-cancel>Отмена</button></form><p class="panel-name-message" role="status"></p>'
    else:content+='<span class="panel-name-value">'+esc(name)+'</span>'
    content+='</div>'
    if can_history():content+='<nav class="detail-analysis-links"><a class="nav-link" href="/timeline/'+esc(identifier)+'">◷ Лента событий</a><a class="nav-link" href="/dependencies">Связи серверов</a></nav>'
    content += '<div class="server-detail"><div class="detail-toolbar"><p class="muted">↻ Автообновление · 10 с</p><button type="button" id="collapse-details" hidden>Свернуть подробности</button></div><div id="server-live" data-refresh data-refresh-interval="10000">' + server_card(row, time.time(), {'agent':row['id'],'csrf':csrf} if console_access else None,forecasts=dict(row).get('forecasts',{}),csrf=csrf)
    content+='</div>'
    from .task_manager import section as task_section,assets as task_assets
    content += task_section(row['id'])+task_assets()
    data=json.loads(row['data'] or '{}')
    from .console_ui import section as console_section
    if console_access:content+=console_section(row['id'],csrf,data)


    from .folding import fold_sections
    content += '</div>'
    from .drilldown import widget
    from .rdp_control import widget as rdp_widget
    return page(fold_sections(content)+(widget(row['id']) if can_history() else '')+(rdp_widget() if can_console() else ''), refresh=True)
