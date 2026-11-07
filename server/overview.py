"""Compact overview and detailed server pages."""
from .disks import monitored_disks
import json
import time
from pathlib import Path

LIVE_SCRIPT = Path(__file__).with_name("overview.js").read_text(encoding="utf-8")
from urllib.parse import quote
from .dashboard import esc, page, duration, size, number, meter, server_card, backup_problems, cpu_description, memory_description, resource_points


def issues(row, now):
    data = json.loads(row['data']) if row['data'] else {}
    elapsed = max(0, now - row['received']) if row['received'] is not None else 0
    problems = []
    if row['received'] is not None and elapsed >= 180:
        problems.append('Нет связи с агентом')
    if number(data.get('cpu_percent')) >= 95:
        problems.append('Высокая загрузка CPU')
    if number(data.get('memory_percent')) >= 95:
        problems.append('Мало свободной RAM')
    for disk in monitored_disks(data):
        if number(disk.get('used_percent')) >= 85:
            problems.append('Заполнен диск ' + str(disk.get('path', '')))
    for backup in data.get('backups', []):
        if backup_problems(backup, elapsed):
            problems.append('Ошибка бэкапа: ' + str(backup.get('name') or backup.get('path', '')))
    for service in data.get('services', []):
        if service.get('status') != 'running':
            problems.append('Служба не работает: ' + str(service.get('name', '')))
    return problems


def matches(row, now, query, view):
    data = json.loads(row['data']) if row['data'] else {}
    text = ' '.join(str(x or '') for x in (row['id'], dict(row).get('display_name'), data.get('hostname'))).casefold()
    if query.strip().casefold() not in text:
        return False
    if view == 'problems':
        return bool(issues(row, now))
    if view == 'offline':
        return row['received'] is not None and now - row['received'] >= 180
    return True


def search_form(query, view, shown, total):
    options = ''.join(f'<option value="{value}" {"selected" if value == view else ""}>{label}</option>' for value, label in [('all', 'Все серверы'), ('problems', 'Есть проблемы'), ('offline', 'Нет связи')])
    return f'<form class="searchbar" method="get" action="/"><label>Поиск по названию или имени<input name="q" value="{esc(query)}" maxlength="200" placeholder="SQL, ERP, WIN-…" type="search"></label><label>Показать<select name="view">{options}</select></label><noscript><button>Найти</button></noscript><a class="nav-link" href="/">Сбросить</a></form><p class="muted search-status" role="status" aria-live="polite"></p><p class="muted result-count">Показано {shown} из {total}. Фильтр «Есть проблемы»: связь, CPU/RAM от 95%, диски от 85%, бэкапы и службы.</p>'


def compact_card(row, now):
    data = json.loads(row['data']) if row['data'] else {}
    hostname = data.get('hostname') or row['id']
    title = dict(row).get('display_name') or hostname
    url = '/servers/' + quote(row['id'], safe='')
    age = max(0, now-row['received']) if row['received'] is not None else None
    state, color = ('Ожидает данных', 'neutral') if age is None else ('Онлайн', 'normal') if age < 180 else ('Нет связи', 'danger')
    problem_class = ' problem-server' if issues(row, now) else ''
    content = f'<article class="server compact{problem_class}" data-server-id="{esc(row["id"])}"><header class="server-head"><div><h2><a href="{esc(url)}">{esc(title)}</a></h2><p class="muted">{esc(hostname)} · {esc(row["id"])}</p></div><span class="badge {color}">● {state}</span></header>'
    if age is None:
        return content + '<p class="empty">Ожидаем первый отчёт агента</p><a class="nav-link" href="' + esc(url) + '">Открыть сервер →</a></article>'
    if age >= 180:
        content += '<p class="notice">Данные устарели — нет связи с агентом</p>'
    points=resource_points(row,data)
    content += '<div class="metrics">' + meter('CPU', data.get('cpu_percent'), cpu_description(data),points,'cpu',now) + meter('RAM', data.get('memory_percent'), memory_description(data),points,'ram',now) + '</div>'
    content += '<div class="compact-disks">'
    for disk in monitored_disks(data):
        content += '<p><b>' + esc(disk.get('path', '')) + '</b><span>' + size(disk.get('free_bytes')) + ' свободно · ' + f'{number(disk.get("used_percent")):.1f}% занято' + '</span></p>'
    content += '</div>'
    problems = issues(row, now)
    if problems:
        content += '<ul class="compact-issues">' + ''.join('<li>' + esc(p) + '</li>' for p in problems[:3]) + '</ul>'
        if len(problems) > 3:
            content += f'<p class="muted">Ещё проблем: {len(problems)-3}</p>'
    else:
        content += '<p class="text-normal compact-ok">Проблем по полученным данным нет</p>'
    content += '<p class="muted">Отчёт: ' + duration(age) + ' назад · В работе: ' + duration(data.get('uptime_seconds')) + '</p>'
    return content + f'<p class="history-link"><a class="nav-link" href="{esc(url)}">Открыть сервер →</a> <a class="nav-link" href="/history/{esc(quote(row["id"], safe=""))}">Графики нагрузки</a></p></article>'


def detail_page(row, csrf):
    identifier = quote(row['id'], safe='')
    title = dict(row).get('display_name') or ''
    content = '<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/">← Все серверы</a><a class="nav-link" href="/settings/' + esc(identifier) + '">Настройки мониторинга</a><a class="nav-link" href="/servers/' + esc(identifier) + '">Обновить данные</a></header>'
    content += '<p class="muted detail-note">Обновление показателей каждые 10 секунд, без перезагрузки страницы.</p><div id="server-live" data-refresh data-refresh-interval="10000">' + server_card(row, time.time())
    from .forecast import forecast_html
    content += forecast_html(dict(row).get('forecasts', {}), row['received'] is None or time.time()-row['received']>=180) + '</div>'
    from .processes_ui import process_section
    content += process_section(row['id'])
    content += f'<section class="server"><h3>Название в панели</h3><p class="muted">Не меняет имя компьютера, идентификатор агента или ключ. Пустое поле возвращает техническое имя.</p><form method="post" action="/servers/{esc(identifier)}/name"><input type="hidden" name="csrf" value="{esc(csrf)}"><label>Понятное название<input name="display_name" maxlength="120" value="{esc(title)}" placeholder="SQL — ERP"></label><button>Сохранить название</button></form></section>'
    return page(content, refresh=True)
