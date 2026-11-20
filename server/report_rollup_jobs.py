"""Durable, throttled background generation of daily report aggregates."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import hmac
import logging
import secrets
import time
from urllib.parse import parse_qs

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .access import can_console
from .dashboard import esc, page
from .portal_settings import retention_days
from .report_rollups import DAY, MSK, build, day_text, midnight
from .windows_ui import stamp

log = logging.getLogger(__name__)
LEASE_SECONDS = 600


def enqueue_automatic(db, now):
    today = midnight(now)
    latest = today-DAY if now-today >= 3600 else today-2*DAY
    with db() as c:
        first_report = c.execute('SELECT MIN(received) FROM reports').fetchone()[0]
        if first_report is None:
            return
        first = max(midnight(first_report),today-(retention_days(c)-1)*DAY)
        if first > latest:
            return
        present = c.execute('SELECT COUNT(*) FROM report_rollup_jobs WHERE day BETWEEN ? AND ?',(first,latest)).fetchone()[0]
        if present == (latest-first)//DAY+1:
            return
        c.execute("""
            WITH RECURSIVE days(day) AS (
                SELECT ? UNION ALL SELECT day+? FROM days WHERE day<?
            )
            INSERT OR IGNORE INTO report_rollup_jobs(day,requested) SELECT day,? FROM days
        """,(first,DAY,latest,now))


def enqueue_manual(c, first, last, now):
    c.executemany("""
        INSERT INTO report_rollup_jobs(day,requested,manual) VALUES (?,?,1)
        ON CONFLICT(day) DO UPDATE SET requested=MAX(excluded.requested,requested+0.000001), manual=1,
            finished=NULL, lease=NULL, token=NULL, error=NULL
    """, ((day,now) for day in range(first,last+1,DAY)))


def claim(db, now, token):
    with db() as c:
        # Avoid taking the writer lock every time an idle worker polls.
        candidate = c.execute("""
            SELECT day FROM report_rollup_jobs WHERE finished IS NULL AND COALESCE(lease,0)<=?
            ORDER BY manual DESC,day DESC LIMIT 1
        """, (now,)).fetchone()
        if not candidate:
            return None
        day = candidate['day']
        changed = c.execute("""
            UPDATE report_rollup_jobs SET token=?,lease=?
            WHERE day=? AND finished IS NULL AND COALESCE(lease,0)<=?
            AND NOT EXISTS (SELECT 1 FROM report_rollup_jobs WHERE token IS NOT NULL AND lease>?)
        """,(token,now+LEASE_SECONDS,day,now,now)).rowcount
        if changed:
            return day
    return None


def process_one(db, now=None):
    now = time.time() if now is None else now
    token = secrets.token_hex(16)
    day = claim(db,now,token)
    if day is None:
        return False
    try:
        with db() as c:
            job = c.execute('SELECT requested FROM report_rollup_jobs WHERE day=? AND token=?',(day,token)).fetchone()
            if not job:
                return True
            # Agents first observed after the day cannot contribute historical
            # metrics; agents already known can contribute a full outage day.
            agent = c.execute("""
                SELECT a.id FROM agents a
                LEFT JOIN report_rollups r ON r.agent=a.id AND r.day=?
                WHERE (r.built IS NULL OR r.built<?)
                AND (SELECT received FROM reports WHERE agent=a.id ORDER BY received LIMIT 1)<?
                ORDER BY a.id LIMIT 1
            """,(day,job['requested'],day+DAY)).fetchone()
            data = build(c,agent['id'],day) if agent else None
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM report_rollup_jobs WHERE day=? AND token=?',(day,token)).fetchone():
                return True
            if data is None:
                c.execute('UPDATE report_rollup_jobs SET finished=?,lease=NULL,token=NULL,error=NULL WHERE day=?',(time.time(),day))
            else:
                c.execute("""
                    INSERT INTO report_rollups(agent,day,built,metrics,coverage,chart)
                    SELECT id,?,?,?,?,? FROM agents WHERE id=?
                    AND EXISTS (SELECT 1 FROM reports WHERE agent=agents.id AND received<?)
                    ON CONFLICT(agent,day) DO UPDATE SET built=excluded.built,
                        metrics=excluded.metrics,coverage=excluded.coverage,chart=excluded.chart
                """,(day,job['requested'],*data,agent['id'],day+DAY))
                c.execute('UPDATE report_rollup_jobs SET lease=NULL,token=NULL,error=NULL WHERE day=?',(day,))
        return True
    except Exception:
        log.exception('Daily report rollup failed for %s',day_text(day))
        with db() as c:
            c.execute("""UPDATE report_rollup_jobs SET token=NULL,lease=?,error=?
                         WHERE day=? AND token=?""",
                      (time.time()+60,'Ошибка расчёта. Повтор через минуту.',day,token))
        return False


@asynccontextmanager
async def worker(db):
    stop = asyncio.Event()

    async def loop():
        next_schedule = 0
        while not stop.is_set():
            delay = 5
            try:
                now = time.time()
                if now >= next_schedule:
                    await run_in_threadpool(enqueue_automatic,db,now)
                    next_schedule = now+30
                if await run_in_threadpool(process_one,db):
                    delay = 0.2
            except Exception:
                log.exception('Report rollup worker failed')
            try:
                await asyncio.wait_for(stop.wait(),delay)
            except asyncio.TimeoutError:
                pass

    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        stop.set()
        await task


def register(app, db, authenticated, csrf_token):
    @app.get('/report-rollups',response_class=HTMLResponse)
    def status(request: Request):
        if not authenticated(request):
            return RedirectResponse('/',303)
        if not can_console():
            raise HTTPException(403)
        today = midnight(time.time())
        with db() as c:
            earliest = today-(retention_days(c)-1)*DAY
            ready, pending = c.execute("""
                SELECT COUNT(finished),COUNT(*)-COUNT(finished) FROM report_rollup_jobs
            """).fetchone()
            last = c.execute('SELECT MAX(finished) FROM report_rollup_jobs').fetchone()[0]
            current = c.execute("""
                SELECT day,error,token IS NOT NULL AND lease>? AS running
                FROM report_rollup_jobs WHERE finished IS NULL
                ORDER BY running DESC,manual DESC,day DESC LIMIT 1
            """,(time.time(),)).fetchone()
        yesterday = day_text(today-DAY)
        content = (
            '<header class="topbar"><a class="brand" href="/">ServersStatus</a>'
            '<a class="nav-link" href="/admin">← Администрирование</a></header>'
            '<div class="heading"><h1>Суточные сводки</h1></div><section class="server">'
            f'<p>Готово дней: {ready} · В очереди: {pending}</p>'
            '<p class="muted">Последний завершённый расчёт · '+esc(stamp(last))+'</p>'
        )
        if current:
            label = 'В работе' if current['running'] else 'Следующая дата'
            content += '<p>'+label+' · '+esc(day_text(current['day']))+'</p>'
            if current['error']:
                content += '<p class="text-danger">'+esc(current['error'])+'</p>'
        content += '<p class="muted">Каждый день после 01:00 МСК рассчитываются завершённые сутки. Пересчёт выполняется в фоне.</p><p><a class="nav-link" href="/report-rollups">Обновить состояние</a></p>'
        if earliest < today:
            minimum = day_text(earliest)
            content += (
                '<form class="fleet-filter" method="post">'
                '<input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'">'
                f'<label>С (МСК)<input type="date" name="date_from" min="{minimum}" max="{yesterday}" value="{yesterday}" required></label>'
                f'<label>По (МСК)<input type="date" name="date_to" min="{minimum}" max="{yesterday}" value="{yesterday}" required></label>'
                '<button>Пересчитать сводки</button></form>'
            )
        return HTMLResponse(page(content+'</section>'),headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

    @app.post('/report-rollups')
    async def rebuild(request: Request):
        if not authenticated(request):
            raise HTTPException(401)
        if not can_console():
            raise HTTPException(403)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>4096:
                raise HTTPException(413)
        try:
            form = parse_qs(body.decode())
        except UnicodeDecodeError:
            raise HTTPException(400,'Некорректная форма') from None
        if not hmac.compare_digest(form.get('csrf',[''])[0].encode(),csrf_token(request).encode()):
            raise HTTPException(403)
        try:
            first,last = (
                int(datetime.strptime(form.get(field,[''])[0],'%Y-%m-%d').replace(tzinfo=MSK).timestamp())
                for field in ('date_from','date_to')
            )
        except (ValueError,OverflowError,OSError):
            raise HTTPException(400,'Укажите обе даты') from None
        now = time.time()
        today = midnight(now)
        def queue():
            with db() as c:
                if not today-(retention_days(c)-1)*DAY <= first <= last < today:
                    raise HTTPException(400,'Выберите завершённые сутки в пределах срока хранения')
                enqueue_manual(c,first,last,now)
        await run_in_threadpool(queue)
        return RedirectResponse('/report-rollups',303)
