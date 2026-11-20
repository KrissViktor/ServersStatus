"""Public site monitors, their run history and Telegram transitions."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import json
import logging
import secrets
import time
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .dashboard import esc, page
from .delivery_policy import delivery_window
from .monitor_probes import check_http, check_registry, target
from .notification_types import DeliveryError
from .windows_ui import stamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS site_monitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL,
    interval INTEGER NOT NULL, expected INTEGER NOT NULL, warn_days INTEGER NOT NULL,
    registry INTEGER NOT NULL, notify INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
    due REAL NOT NULL DEFAULT 0, token TEXT, latest TEXT, checked REAL
);
CREATE INDEX IF NOT EXISTS site_monitors_due ON site_monitors(enabled,due);
CREATE TABLE IF NOT EXISTS site_monitor_runs (
    id INTEGER PRIMARY KEY, monitor INTEGER NOT NULL, at REAL NOT NULL, result TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS site_monitor_runs_time ON site_monitor_runs(monitor,at);
CREATE INDEX IF NOT EXISTS site_monitor_runs_retention ON site_monitor_runs(at);
CREATE TABLE IF NOT EXISTS site_monitor_alerts (
    monitor INTEGER NOT NULL, kind TEXT NOT NULL, active INTEGER NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0, retry REAL NOT NULL DEFAULT 0, body TEXT NOT NULL,
    PRIMARY KEY(monitor,kind)
);
"""
LABELS = {'ok':'Доступен','unexpected':'Неожиданный HTTP-код','error':'Ошибка соединения',
          'off':'Выключено','unknown':'Ожидает проверки','expiring':'Скоро истекает',
          'invalid':'Ошибка сертификата','clear':'Не найден в снимке','listed':'Найден в снимке',
          'stale':'Снимок устарел','unconfigured':'Источник не настроен','unavailable':'Источник недоступен'}


def process_one(db):
    now=time.time()
    token=secrets.token_hex(12)
    with db() as c:
        row=c.execute('SELECT * FROM site_monitors WHERE enabled=1 AND due<=? ORDER BY due,id LIMIT 1',(now,)).fetchone()
        if not row or not c.execute('UPDATE site_monitors SET due=?,token=? WHERE id=? AND enabled=1 AND due<=?',
                                    (now+90,token,row['id'],now)).rowcount:
            return False
    result=check_http(row['url'],row['expected'],row['warn_days'],now)
    if row['registry']:
        result.update(check_registry(row['url'],now))
    checked=time.time()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        encoded=json.dumps(result,ensure_ascii=False)
        if not c.execute('UPDATE site_monitors SET latest=?,checked=?,due=?,token=NULL WHERE id=? AND token=?',
                         (encoded,checked,checked+row['interval'],row['id'],token)).rowcount:
            return True
        c.execute('INSERT INTO site_monitor_runs(monitor,at,result) VALUES (?,?,?)',(row['id'],checked,encoded))
        if row['notify']:
            transitions = {
                'http': result['http']!='ok',
                'tls': {'ok':False,'invalid':True,'expiring':True}.get(result['tls']),
                'rkn': {'clear':False,'listed':True}.get(result.get('rkn')),
            }
            for kind,active in transitions.items():
                if active is None:
                    continue
                state=LABELS[result[kind]]
                body=f'{row["name"]} · {row["url"]}\n{kind.upper()}: {state}'
                if kind=='http' and result['code'] is not None:
                    body+=f' · {result["code"]}'
                c.execute("""INSERT INTO site_monitor_alerts(monitor,kind,active,body) VALUES (?,?,?,?)
                    ON CONFLICT(monitor,kind) DO UPDATE SET active=excluded.active,body=excluded.body""",(row['id'],kind,int(active),body))
    return True


@asynccontextmanager
async def worker(db):
    stop=asyncio.Event()
    async def loop():
        while not stop.is_set():
            delay=5
            try:
                if await run_in_threadpool(process_one,db):
                    delay=0.25
            except Exception:
                logging.getLogger(__name__).exception('Ошибка фонового мониторинга сайтов')
            try:
                await asyncio.wait_for(stop.wait(),delay)
            except asyncio.TimeoutError:
                pass
    task=asyncio.create_task(loop())
    try:
        yield
    finally:
        stop.set()
        await task


def deliver(db, sender):
    now=time.time()
    if not delivery_window(now):
        return 0,0
    with db() as c:
        rows=c.execute("""SELECT a.* FROM site_monitor_alerts a JOIN site_monitors m ON m.id=a.monitor
            WHERE m.enabled=1 AND m.notify=1 AND a.active<>a.sent AND a.retry<=? ORDER BY a.retry LIMIT 10""",(now,)).fetchall()
    sent=failed=0
    for row in rows:
        if not delivery_window(time.time()):
            break
        headline='🔴 Проблема · мониторинг сайтов' if row['active'] else '🟢 Восстановлено · мониторинг сайтов'
        try:
            sender(headline+'\n'+row['body'])
        except DeliveryError as error:
            with db() as c:
                c.execute('UPDATE site_monitor_alerts SET retry=? WHERE monitor=? AND kind=?',
                          (time.time()+error.retry_after,row['monitor'],row['kind']))
            failed+=1
        else:
            with db() as c:
                c.execute('UPDATE site_monitor_alerts SET sent=?,retry=0 WHERE monitor=? AND kind=?',
                          (row['active'],row['monitor'],row['kind']))
            sent+=1
    return sent,failed


def badge(state):
    color='normal' if state in ('ok','clear') else 'danger' if state in ('error','unexpected','invalid','listed') else 'warning' if state in ('stale','expiring','unavailable') else 'neutral'
    return '<span class="badge '+color+'">'+esc(LABELS.get(state,state))+'</span>'


def fields(row):
    def val(key, default=''):
        return esc(row[key] if row else default)
    return (
        '<label>Название<input name="name" maxlength="80" required value="'+val('name')+'"></label>'
        '<label>URL<input name="url" type="url" maxlength="1024" required value="'+val('url')+'" placeholder="https://example.com/health"></label>'
        '<label>Интервал, секунд<input type="number" name="interval" min="60" max="86400" required value="'+val('interval',300)+'"></label>'
        '<label>Ожидаемый HTTP-код<input type="number" name="expected" min="100" max="599" required value="'+val('expected',200)+'"></label>'
        '<label>Предупреждать о TLS за, дней<input type="number" name="warn_days" min="1" max="90" required value="'+val('warn_days',14)+'"></label>'
        '<label class="check"><input type="checkbox" name="registry"'+(' checked' if row and row['registry'] else '')+'>Сверять домен с реестром РКН</label>'
        '<label class="check"><input type="checkbox" name="notify"'+(' checked' if row and row['notify'] else '')+'>Уведомлять в Telegram</label>'
    )


def render_result(result):
    http=badge(result.get('http','unknown'))
    if result.get('code') is not None:
        http+=' · HTTP '+str(result['code'])
    if result.get('ms') is not None:
        http+=' · '+str(result['ms'])+' мс'
    tls_state=result.get('tls','unknown')
    tls='<span class="badge normal">Имя и цепочка подтверждены</span>' if tls_state=='ok' else badge(tls_state)
    if result.get('expires'):
        tls+=' · до '+esc(stamp(result['expires']))
    if result.get('issuer'):
        tls+=' · '+esc(result['issuer'])
    rkn=badge(result.get('rkn','off'))
    if result.get('registry_at'):
        rkn+=' · снимок '+esc(stamp(result['registry_at']))
    return '<p>HTTP '+http+'</p><p>TLS '+tls+'</p><p>РКН '+rkn+'</p>'+(
        '<p class="muted">'+esc(result['error'])+'</p>' if result.get('error') else '')


def register(app,db,authenticated,csrf_token):
    from .access import can_history
    def authorize(request):
        if not authenticated(request) or not can_history():
            raise HTTPException(403)

    @app.get('/monitors',response_class=HTMLResponse)
    def listing(request:Request, monitor:int=0):
        authorize(request)
        if not 0<=monitor<2**63:
            raise HTTPException(400)
        with db() as c:
            rows=c.execute('SELECT * FROM site_monitors ORDER BY name,id').fetchall()
            history=c.execute('SELECT at,result FROM site_monitor_runs WHERE monitor=? ORDER BY at DESC LIMIT 30',(monitor,)).fetchall() if monitor else []
        csrf='<input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'">'
        content='<header class="topbar"><a class="brand" href="/">ServersStatus</a></header><div class="heading"><h1>Мониторы сайтов</h1></div>'
        content+='<details class="server"><summary>Добавить монитор</summary><form class="fleet-filter" action="/monitors" method="post">'+csrf+fields(None)+'<button>Добавить</button></form></details>'
        for row in rows:
            identifier=str(row['id'])
            result=json.loads(row['latest']) if row['latest'] else {'tls':'unknown' if row['url'].startswith('https:') else 'off','rkn':'unknown' if row['registry'] else 'off'}
            content+='<section class="server" id="monitor-'+identifier+'"><h2>'+esc(row['name'])+'</h2><p class="muted">'+esc(row['url'])+'</p>'
            content+=render_result(result)+'<p class="muted">'+('На паузе · ' if not row['enabled'] else '')+'Последняя проверка: '+esc(stamp(row['checked']))+'</p>'
            if row['enabled'] and row['checked'] and time.time()-row['checked']>max(120,2*row['interval']):
                content+='<p class="muted">Результат проверки устарел.</p>'
            content+='<a class="nav-link" href="/monitors?monitor='+identifier+'#monitor-'+identifier+'">История проверок</a>'
            content+='<details><summary>Настройки</summary><form class="fleet-filter" action="/monitors" method="post">'+csrf+'<input type="hidden" name="id" value="'+identifier+'">'+fields(row)+'<button>Сохранить</button><button name="action" value="toggle" formnovalidate>'+('Пауза' if row['enabled'] else 'Возобновить')+'</button></form></details>'
            if monitor==row['id']:
                content+='<details open><summary>Последние проверки</summary>'
                for run in history:
                    content+='<article><h3>'+esc(stamp(run['at']))+'</h3>'+render_result(json.loads(run['result']))+'</article>'
                content+=('</details>' if history else '<p class="muted">Проверок пока нет.</p></details>')
            content+='</section>'
        return HTMLResponse(page(content),headers={'Cache-Control':'no-store'})

    @app.post('/monitors')
    async def save(request:Request):
        authorize(request)
        from .console import read_body
        try:
            data=parse_qs((await read_body(request,8192)).decode())
        except UnicodeError:
            raise HTTPException(400,'Некорректная форма') from None
        def value(key,default=''):
            return data.get(key,[default])[0]
        if not hmac.compare_digest(value('csrf').encode(),csrf_token(request).encode()):
            raise HTTPException(403)
        try:
            identifier=int(value('id','0'))
            if not 0<=identifier<2**63:
                raise ValueError('Некорректный ID')
            action=value('action')
            if action!='toggle':
                name=value('name').strip()
                url=target(value('url').strip())
                interval,expected,warn_days=(int(value(key)) for key in ('interval','expected','warn_days'))
                if not 1<=len(name)<=80 or not 60<=interval<=86400 or not 100<=expected<=599 or not 1<=warn_days<=90:
                    raise ValueError('Проверьте параметры монитора')
                config=(name,url,interval,expected,warn_days,int('registry' in data),int('notify' in data))
        except (ValueError,UnicodeError) as error:
            raise HTTPException(400,str(error)) from None
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if identifier:
                if action=='toggle':
                    changed=c.execute('UPDATE site_monitors SET enabled=1-enabled,due=0,token=NULL WHERE id=?',(identifier,)).rowcount
                else:
                    changed=c.execute("""UPDATE site_monitors SET name=?,url=?,interval=?,expected=?,warn_days=?,
                        registry=?,notify=?,due=0,token=NULL,latest=NULL,checked=NULL WHERE id=?""",(*config,identifier)).rowcount
                    c.execute('DELETE FROM site_monitor_alerts WHERE monitor=?',(identifier,))
                if not changed:
                    raise HTTPException(404)
            elif action=='toggle':
                raise HTTPException(400)
            else:
                if c.execute('SELECT COUNT(*) FROM site_monitors').fetchone()[0]>=100:
                    raise HTTPException(400,'Достигнут предел в 100 мониторов')
                identifier=c.execute("""INSERT INTO site_monitors(name,url,interval,expected,warn_days,registry,notify)
                    VALUES (?,?,?,?,?,?,?)""",config).lastrowid
        return RedirectResponse('/monitors#monitor-'+str(identifier),303)
