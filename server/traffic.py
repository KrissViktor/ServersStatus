"""First-party navigation log and superadministrator traffic overview."""
import ipaddress
import json
import logging
import sqlite3
import time
from urllib.parse import urlencode, urlsplit

from .portal_sessions import browser_info, country_for
from .security import client_address

SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_traffic (
    id INTEGER PRIMARY KEY,
    at REAL NOT NULL,
    kind TEXT NOT NULL,
    ip TEXT NOT NULL,
    country TEXT,
    account TEXT NOT NULL,
    source TEXT NOT NULL,
    browser TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS portal_traffic_time ON portal_traffic(at);
CREATE INDEX IF NOT EXISTS portal_traffic_ip_time ON portal_traffic(ip,at);
"""

EVENTS = {
    'landing':'Просмотры визитки',
    'login_open':'Открытия формы входа',
    'panel':'Открытия панели',
    'login_ok':'Успешные входы',
    'login_fail':'Неудачные входы',
    'login_blocked':'Отклонено блокировкой',
    'demo':'Переходы к примеру',
    'how':'Переходы к описанию',
}
PAGE_SIZE=50
log=logging.getLogger(__name__)


def referrer_origin(value):
    try:
        url=urlsplit(value[:2048])
        if url.scheme not in ('http','https') or not url.hostname:
            return ''
        host=f'[{url.hostname}]' if ':' in url.hostname else url.hostname
        port=f':{url.port}' if url.port else ''
        return f'{url.scheme}://{host}{port}'[:255]
    except ValueError:
        return ''


def record_navigation(db, request, kind, account=''):
    if (request.headers.get('sec-fetch-dest','document') == 'document'
            and request.headers.get('x-portal-refresh') != '1'
            and 'prefetch' not in request.headers.get('sec-purpose','')):
        record_visit(db,request,kind,account)


def record_visit(db, request, kind, account=''):
    address=client_address(request)
    try:
        address=str(ipaddress.ip_address(address))
    except ValueError:
        address='unknown'
    source=referrer_origin(request.headers.get('referer',''))
    context=browser_info(request)
    for name in ('sec-fetch-site','sec-fetch-mode','sec-fetch-dest'):
        if name in request.headers:
            context[name]=request.headers[name][:32]
    try:
        with db() as c:
            c.execute('PRAGMA busy_timeout=75')
            c.execute('INSERT INTO portal_traffic(at,kind,ip,country,account,source,browser) VALUES (?,?,?,?,?,?,?)',
                      (time.time(),kind,address,country_for(address),account,source,json.dumps(context,ensure_ascii=False)))
    except sqlite3.OperationalError as error:
        if (getattr(error,'sqlite_errorcode',0) & 255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
            log.warning('Portal traffic write failed',exc_info=True)


def traffic_page(c, now, days, address, kind, offset):
    from .dashboard import esc, page
    from .windows_ui import stamp

    days=days if days in (1,7,30,90) else 7
    address=address.strip()[:45]
    try:
        address=str(ipaddress.ip_address(address))
    except ValueError:
        pass
    kind=kind if kind in EVENTS else ''
    offset=max(0,min(offset,1_000_000))
    offset-=offset%PAGE_SIZE
    where='at>=? AND at<=?'
    args=[now-days*86400,now]
    if address:
        where+=' AND ip=?'
        args.append(address)
    cte=f"""WITH activity AS (
        SELECT id,0 AS audit,at,kind,ip,country,account,source,browser FROM portal_traffic WHERE {where}
        UNION ALL
        SELECT id,1,at,CASE accepted WHEN 1 THEN 'login_ok' WHEN 2 THEN 'login_blocked' ELSE 'login_fail' END,
               ip,country,account,'',browser FROM portal_login_audit WHERE {where}
    )"""
    params=args+args
    counts=dict(c.execute(cte+' SELECT kind,COUNT(*) FROM activity GROUP BY kind',params))
    unique=c.execute(cte+" SELECT COUNT(DISTINCT ip) FROM activity WHERE kind='landing' AND ip<>'unknown'",params).fetchone()[0]
    top_ips=c.execute(cte+""" SELECT ip,MAX(country),COUNT(*) FROM activity
        WHERE kind='landing' AND ip<>'unknown' GROUP BY ip ORDER BY COUNT(*) DESC,ip LIMIT 8""",params).fetchall()
    top_sources=c.execute(cte+""" SELECT source,COUNT(*) FROM activity WHERE kind='landing'
        GROUP BY source ORDER BY COUNT(*) DESC,source LIMIT 8""",params).fetchall()
    criteria=' WHERE kind=?' if kind else ''
    rows=c.execute(cte+' SELECT at,kind,ip,country,account,source,browser FROM activity'+criteria+
                   ' ORDER BY at DESC,audit DESC,id DESC LIMIT ? OFFSET ?',
                   params+([kind] if kind else [])+[PAGE_SIZE+1,offset]).fetchall()

    def link(**changes):
        return '/admin/traffic?'+esc(urlencode(dict({'days':days,'ip':address,'kind':kind},**changes)))

    title='<header class="topbar"><a class="brand" href="/">Server Pulse</a><a class="nav-link" href="/admin">← Администрирование</a></header>'
    title+='<div class="heading"><h1>Посещаемость портала</h1><a class="nav-link" href="/users/sessions">Сеансы портала →</a></div>'
    controls='<form class="searchbar"><label>Период<select name="days">'
    for value,label in ((1,'24 часа'),(7,'7 дней'),(30,'30 дней'),(90,'90 дней')):
        controls+=f'<option value="{value}"{" selected" if days==value else ""}>{label}</option>'
    controls+=f'</select></label><label>IP-адрес<input name="ip" value="{esc(address)}" maxlength="45" placeholder="IPv4 / IPv6"></label>'
    controls+='<label>Событие<select name="kind"><option value="">Все события</option>'
    for value,label in EVENTS.items():
        controls+=f'<option value="{value}"{" selected" if kind==value else ""}>{label}</option>'
    controls+='</select></label><button>Применить</button></form>'
    cards=[(label,counts.get(key,0)) for key,label in EVENTS.items()]
    cards.insert(1,('Уникальные IP визитки',unique))
    stats='<div class="stats traffic-stats">'+''.join(f'<div class="stat"><span>{label}</span><strong>{count}</strong></div>' for label,count in cards)+'</div>'
    leaders='<div class="traffic-leaders"><section class="server"><h2>Частые IP визитки</h2>'
    for ip,country,count in top_ips:
        country_text=f' · {esc(country)}' if country else ''
        leaders+=f'<div class="list-row"><a class="nav-link" href="{link(ip=ip)}"><code>{esc(ip)}</code>{country_text}</a><strong>{count}</strong></div>'
    if not top_ips:
        leaders+='<p class="muted">Нет данных за период</p>'
    leaders+='</section><section class="server"><h2>Источники визитки</h2>'
    for source,count in top_sources:
        label=f'<code>{esc(source)}</code>' if source else '<span>Источник не передан</span>'
        leaders+=f'<div class="list-row">{label}<strong>{count}</strong></div>'
    if not top_sources:
        leaders+='<p class="muted">Нет данных за период</p>'
    leaders+='</section></div>'
    journal='<section class="server"><h2>Журнал посещений и входов</h2><div class="table-scroll"><table class="metric-table traffic-table">'
    journal+='<thead><tr><th>Время</th><th>Событие</th><th>IP-адрес</th><th>Страна</th><th>Пользователь</th><th>Источник</th><th>Данные браузера</th></tr></thead><tbody>'
    for at,event,ip,country,account,source,raw in rows[:PAGE_SIZE]:
        browser=json.loads(raw)
        details=''.join(f'<dt>{esc(key)}</dt><dd><code>{esc(value)}</code></dd>' for key,value in browser.items())
        browser_html=f'<details><summary>Подробнее</summary><dl>{details}</dl></details>' if details else '—'
        journal+=f'<tr><td>{esc(stamp(at))}</td><td>{EVENTS[event]}</td><td><a href="{link(ip=ip)}"><code>{esc(ip)}</code></a></td>'
        journal+=f'<td>{esc(country or "—")}</td><td data-no-translate>{esc(account or "—")}</td><td><code>{esc(source or "—")}</code></td><td>{browser_html}</td></tr>'
    if not rows:
        journal+='<tr><td colspan="7">Нет данных за период</td></tr>'
    journal+='</tbody></table></div><nav class="traffic-pages">'
    if offset:
        journal+=f'<a class="nav-link" href="{link(offset=offset-PAGE_SIZE)}">← Назад</a>'
    if len(rows)>PAGE_SIZE:
        journal+=f'<a class="nav-link" href="{link(offset=offset+PAGE_SIZE)}">Далее →</a>'
    journal+='</nav></section>'
    note='<p class="muted traffic-note">Новые события навигации записываются после обновления. Один IP могут использовать несколько человек. Страна показывается при наличии базы IP-геолокации.</p>'
    return page(title+controls+note+stats+leaders+journal)
