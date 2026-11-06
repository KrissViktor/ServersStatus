"""Server-rendered dashboard; all agent-provided text is escaped."""
import html
import json
import math
import time
from pathlib import Path

CSS = Path(__file__).with_name('dashboard.css').read_text(encoding='utf-8')


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
    for unit in ('Б', 'КиБ', 'МиБ', 'Гб', 'ТиБ', 'ПиБ'):
        if value < 1024 or unit == 'ПиБ':
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


def meter(label, value, description):
    percent = min(100, number(value))
    return f'<div class="metric"><div class="metric-top"><span>{esc(label)}</span><strong>{percent:.1f}<small>%</small></strong></div><progress class="{level(percent)}" max="100" value="{percent}" aria-label="{esc(label)}"></progress><p class="muted">{esc(description)}</p></div>'


def page(content, refresh=False):
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + ('<meta http-equiv="refresh" content="30">' if refresh else '') + '<title>ServersStatus · Мониторинг</title><style>' + CSS + '</style></head><body><main>' + content + '</main></body></html>'


def login_page():
    return page('''<div class="login"><div class="logo">S<span>●</span></div><p class="eyebrow">SERVERSSTATUS</p><h1>Всё под контролем</h1><p class="muted">Войдите, чтобы увидеть состояние серверов</p><form method="post" action="/login"><label>Логин<input name="username" autocomplete="username" required autofocus></label><label>Пароль<input name="password" type="password" autocomplete="current-password" required></label><button class="primary">Войти</button></form><p class="muted footnote">Центр мониторинга инфраструктуры</p></div>''')


def server_card(row, now):
    data = json.loads(row['data']) if row['data'] else {}
    age = max(0, now - row['received']) if row['received'] is not None else None
    online = age is not None and age < 180
    state = 'Нет данных' if age is None else 'Онлайн' if online else 'Нет связи'
    badge = 'normal' if online else 'danger' if age is not None else 'neutral'
    hostname = data.get('hostname') or row['id']
    content = f'<article class="server"><header class="server-head"><div><p class="eyebrow">WINDOWS · АГЕНТ {esc(row["id"])}</p><h2>{esc(hostname)}</h2></div><span class="badge {badge}">● {state}</span></header>'
    if age is None:
        return content + '<div class="empty">Ожидаем первый отчёт агента</div></article>'
    content += f'<div class="timing"><span>Последний отчёт: <b>{duration(age)} назад</b></span><span>Время работы: <b>{duration(data.get("uptime_seconds"))}</b></span></div>'
    if not online:
        content += '<p class="notice">Данные устарели: агент не присылал отчёт более 3 минут.</p>'
    content += '<div class="metrics">' + meter('Процессор', data.get('cpu_percent'), 'Загрузка CPU') + meter('Оперативная память', data.get('memory_percent'), 'Использование RAM') + '</div><section><h3>Диски <span class="count">' + str(len(data.get('disks', []))) + '</span></h3><div class="disks">'
    for disk in data.get('disks', []):
        percent = min(100, number(disk.get('used_percent')))
        content += f'<div class="disk"><div class="disk-title"><strong>{esc(disk.get("path", "—"))}</strong><span class="text-{level(percent)}">{percent:.1f}% занято</span></div><progress class="{level(percent)}" value="{percent}" max="100" aria-label="Занято на диске {esc(disk.get("path", ""))}"></progress><p><b>{size(disk.get("free_bytes"))}</b> свободно <span class="muted">из {size(disk.get("total_bytes"))}</span></p></div>'
    content += '</div><p class="muted legend">Жёлтый: занято от 85% · Красный: от 95%</p></section><div class="secondary"><section><h3>Службы</h3>'
    services = data.get('services', [])
    if not services:
        content += '<p class="empty small">Контроль служб не настроен</p>'
    for service in services:
        state = service.get('status', 'unavailable')
        labels = {'running': 'Работает', 'stopped': 'Остановлена', 'paused': 'Приостановлена', 'unavailable': 'Недоступна'}
        content += f'<div class="list-row"><b>{esc(service.get("name", "—"))}</b><span class="badge {"normal" if state == "running" else "warning"}">{esc(labels.get(state, state))}</span></div>'
    content += '</section><section><h3>Резервные копии</h3>'
    backups = data.get('backups', [])
    if not backups:
        content += '<p class="empty small">Папки бэкапов не настроены</p>'
    for backup in backups:
        state = backup.get('state', 'error')
        labels = {'fresh': 'Свежий файл', 'stale': 'Просрочен', 'observing': 'Проверяем стабильность', 'missing': 'Файл не найден', 'error': 'Ошибка чтения'}
        color = 'normal' if state == 'fresh' else 'danger' if state in ('stale', 'missing', 'error') else 'warning'
        content += f'<div class="backup"><div class="list-row"><b>{esc(backup.get("path", "—"))}</b><span class="badge {color}">{esc(labels.get(state, state))}</span></div>'
        if backup.get('file'):
            content += f'<p>{esc(backup["file"])} · {size(backup.get("size_bytes"))} · {duration(backup.get("age_seconds"))} назад</p>'
        content += '</div>'
    if backups:
        content += '<p class="muted legend">Свежесть файла не подтверждает возможность восстановления SQL.</p>'
    content += '</section></div><details><summary>Исходный отчёт</summary><pre>' + esc(json.dumps(data, ensure_ascii=False, indent=2)) + '</pre></details></article>'
    return content


def dashboard(rows):
    now = time.time()
    online = sum(row['received'] is not None and now - row['received'] < 180 for row in rows)
    missing = sum(row['received'] is None for row in rows)
    attention = 0
    for row in rows:
        data = json.loads(row['data']) if row['data'] else {}
        if any(number(d.get('used_percent')) >= 85 for d in data.get('disks', [])):
            attention += 1
    header = '<header class="topbar"><a class="brand" href="/">S<span>●</span> <b>ServersStatus</b></a><form method="post" action="/logout"><button>Выйти</button></form></header><div class="heading"><div><p class="eyebrow">ИНФРАСТРУКТУРА</p><h1>Обзор серверов</h1><p class="muted">Состояние оборудования и резервных копий в одном месте</p></div><span class="refresh">↻ Обновление каждые 30 с</span></div>'
    stats = '<div class="stats">' + ''.join(f'<div class="stat"><span>{label}</span><strong class="text-{color}">{value}</strong></div>' for label, value, color in [('Всего серверов', len(rows), 'neutral'), ('Онлайн', online, 'normal'), ('Нет связи', len(rows) - online - missing, 'danger'), ('Диски от 85%', attention, 'warning')]) + '</div>'
    cards = ''.join(server_card(row, now) for row in rows) or '<div class="empty">Серверов пока нет. Зарегистрируйте агент, чтобы начать мониторинг.</div>'
    return page(header + stats + cards + '<footer>ServersStatus · Показатели на момент последнего отчёта агента</footer>', refresh=True)
