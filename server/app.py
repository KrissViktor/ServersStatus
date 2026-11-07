import asyncio
import json
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel, Field
from .dashboard import dashboard, login_page
from .agents_ui import agents_page
from .history import PERIODS, load_history, history_page
from .configuration import MonitoringSettings
from .settings_ui import settings_page
from .events import record
from .disks import monitored_disks
from .retention import cleanup
from .security import client_address, limiter, login_limiter, blocked_seconds, failed_login

DB = os.environ.get('STATUS_DB', 'status.sqlite3')
app = FastAPI(title='ServersStatus')
login_slots = asyncio.Semaphore(2)


@contextmanager
def db():
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript('''
        CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, salt TEXT, password TEXT);
        CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires REAL);
        CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, token TEXT);
        CREATE TABLE IF NOT EXISTS reports (agent TEXT, received REAL, data TEXT);
        CREATE TABLE IF NOT EXISTS latest_reports (agent TEXT PRIMARY KEY, received REAL NOT NULL, data TEXT NOT NULL);
        CREATE VIEW IF NOT EXISTS current_reports AS
            SELECT agent,received,data FROM latest_reports
            UNION ALL
            SELECT a.id AS agent,r.received,r.data FROM agents a
            JOIN reports r ON r.rowid=(SELECT rowid FROM reports WHERE agent=a.id ORDER BY received DESC LIMIT 1)
            WHERE NOT EXISTS(SELECT 1 FROM latest_reports l WHERE l.agent=a.id);
        CREATE INDEX IF NOT EXISTS reports_agent_time ON reports(agent, received);
        CREATE INDEX IF NOT EXISTS reports_time ON reports(received);
        CREATE INDEX IF NOT EXISTS reports_resource_metrics ON reports(agent,received,json_extract(data,'$.cpu_percent'),json_extract(data,'$.memory_percent'));
        CREATE TABLE IF NOT EXISTS report_maintenance (name TEXT PRIMARY KEY,next_run REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_profiles (agent TEXT PRIMARY KEY, display_name TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agent_settings (agent TEXT PRIMARY KEY, revision INTEGER, data TEXT);
        CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT,received REAL,agent TEXT,category TEXT,level TEXT,message TEXT);
        CREATE INDEX IF NOT EXISTS events_time ON events(received);
        CREATE INDEX IF NOT EXISTS events_agent_time ON events(agent,received);
        CREATE TABLE IF NOT EXISTS event_state (key TEXT PRIMARY KEY,agent TEXT,body TEXT,active INTEGER);
        CREATE TABLE IF NOT EXISTS daily_delivery (day TEXT PRIMARY KEY,chunks TEXT,next_part INTEGER,retry_at REAL,completed INTEGER);
        CREATE TABLE IF NOT EXISTS auth_guard (address TEXT PRIMARY KEY, failures INTEGER NOT NULL, strikes INTEGER NOT NULL, blocked_until TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attempts (address TEXT PRIMARY KEY, count INTEGER, since REAL);
        ''')
        from .updates import SCHEMA
        connection.executescript(SCHEMA)
        yield connection
        connection.commit()
    finally:
        connection.close()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def authenticated(request):
    token = request.cookies.get('session', '')
    with db() as c:
        return c.execute('SELECT 1 FROM sessions WHERE token=? AND expires>?',
                         (digest(token), time.time())).fetchone() is not None


def server_rows():
    now=time.time()
    with db() as c:
        rows=[dict(row) for row in c.execute('SELECT a.id, p.display_name, r.received, r.data FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id ORDER BY a.id').fetchall()]
        for row in rows:
            row['sparkline']=[dict(point) for point in c.execute("""SELECT AVG(received) AS timestamp,
                AVG(json_extract(data,'$.cpu_percent')) AS cpu,
                AVG(json_extract(data,'$.memory_percent')) AS ram
                FROM reports INDEXED BY reports_resource_metrics
                WHERE agent=? AND received>=? AND received<=?
                GROUP BY CAST(received/10 AS INTEGER) ORDER BY timestamp""",(row['id'],now-300,now))]
        return rows


@app.get('/', response_class=HTMLResponse)
def index(request: Request, q: str = '', view: str = 'all'):
    if not authenticated(request):
        return HTMLResponse(login_page())
    if view not in ('all', 'problems', 'offline') or len(q) > 200:
        raise HTTPException(400)
    return HTMLResponse(dashboard(server_rows(), q, view))


@app.post('/login')
async def login(request: Request):
    from urllib.parse import parse_qs
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 4096:
            raise HTTPException(413)
    try:
        form = parse_qs(raw.decode())
    except UnicodeDecodeError:
        raise HTTPException(400)
    name, password = form.get('username', [''])[0], form.get('password', [''])[0]
    address = client_address(request)
    now = time.time()
    with db() as c:
        wait = blocked_seconds(c, address, now)
        if wait:
            raise HTTPException(429, 'Вход временно заблокирован', headers={'Retry-After': str(wait)})
        user = c.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
    salt = user['salt'] if user else '00' * 16
    async with login_slots:
        calculated = await asyncio.to_thread(password_hash, password, salt)
    valid = user is not None and hmac.compare_digest(calculated, user['password'])
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        wait = blocked_seconds(c, address, now)
        if wait:
            raise HTTPException(429, 'Вход временно заблокирован', headers={'Retry-After': str(wait)})
        if not valid:
            wait = failed_login(c, address, now)
            if wait:
                record(c, '', 'security', 'IP заблокирован после двух ошибок входа: '+address, 'warning',now)
        else:
            # Successful login clears the error counter, not escalation history.
            c.execute('UPDATE auth_guard SET failures=0 WHERE address=?', (address,))
            token = secrets.token_urlsafe(32)
            c.execute('DELETE FROM sessions WHERE expires<?', (now,))
            c.execute('INSERT INTO sessions VALUES (?,?)', (digest(token), now + 28800))
    if not valid:
        if wait:
            raise HTTPException(429, 'Две ошибки входа: адрес временно заблокирован', headers={'Retry-After': str(wait)})
        raise HTTPException(401, 'Неверный логин или пароль')
    response = RedirectResponse('/', status_code=303)
    response.set_cookie('session', token, httponly=True, secure=os.environ.get('STATUS_INSECURE_LOCAL') != '1', samesite='strict', max_age=28800)
    return response


@app.post('/logout')
def logout(request: Request):
    with db() as c:
        c.execute('DELETE FROM sessions WHERE token=?', (digest(request.cookies.get('session', '')),))
    response = RedirectResponse('/', status_code=303)
    response.delete_cookie('session')
    return response


class SystemInfo(BaseModel):
    os: str = Field(default='', max_length=100)
    release: str = Field(default='', max_length=100)
    version: str = Field(default='', max_length=200)
    edition: str = Field(default='', max_length=200)
    architecture: str = Field(default='', max_length=100)
    processor: str = Field(default='', max_length=255)
    physical_cores: int | None = Field(default=None, ge=1)
    logical_cores: int | None = Field(default=None, ge=1)
    distribution: str = Field(default='', max_length=255)
    cpu_current_mhz: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cpu_max_mhz: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    memory_used_bytes: int | None = Field(default=None, ge=0)
    memory_total_bytes: int = Field(default=0, ge=0)
    memory_available_bytes: int = Field(default=0, ge=0)


class NetworkInfo(BaseModel):
    name: str = Field(max_length=255)
    is_up: bool
    speed_mbps: int = Field(default=0, ge=0)
    addresses: list[str] = Field(default_factory=list, max_length=20)
    receive_bytes_per_second: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    send_bytes_per_second: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class DiskIO(BaseModel):
    name: str = Field(max_length=255)
    read_bytes_per_second: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    write_bytes_per_second: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    read_iops: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    write_iops: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class RdpSession(BaseModel):
    session_id: int = Field(ge=0)
    username: str = Field(max_length=255)
    domain: str = Field(default='', max_length=255)
    state: str = Field(pattern='^(active|disconnected|other)$')


class RdpInfo(BaseModel):
    status: str = Field(pattern='^(available|unavailable|unsupported)$')
    sessions: list[RdpSession] = Field(default_factory=list, max_length=200)


class Report(BaseModel):
    agent_version: str = Field(default="dev", max_length=80)
    agent_platform: str = Field(default="unknown", max_length=40)
    portal: dict | None = None
    auto_services_enabled: bool | None = None
    manual_services: list[str] | None = Field(default=None, max_length=100)
    features: list[str] = Field(default_factory=list, max_length=20)
    discovered_services: list[dict] = Field(default_factory=list, max_length=100)
    rdp: RdpInfo | None = None
    monitoring_revision: int | None = Field(default=None, ge=0)
    system: SystemInfo | None = None
    network: list[NetworkInfo] = Field(default_factory=list, max_length=100)
    disk_io: list[DiskIO] = Field(default_factory=list, max_length=100)
    sample_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    hostname: str = Field(max_length=255)
    cpu_percent: float = Field(ge=0, le=100)
    memory_percent: float = Field(ge=0, le=100)
    uptime_seconds: float = Field(ge=0)
    disks: list[dict] = Field(max_length=100)
    backups: list[dict] = Field(default_factory=list, max_length=100)
    services: list[dict] = Field(default_factory=list, max_length=100)


@app.post('/api/report/{agent_id}')
async def report(agent_id: str, request: Request):
    authorization = request.headers.get('authorization', '')
    with db() as c:
        agent = c.execute('SELECT token FROM agents WHERE id=?', (agent_id,)).fetchone()
        if not agent or not hmac.compare_digest(agent['token'], digest(authorization.removeprefix('Bearer '))):
            raise HTTPException(401)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                raise HTTPException(413)
        try:
            data = Report.model_validate_json(body)
            data.disks = monitored_disks(data.model_dump())
        except ValueError:
            raise HTTPException(422, 'Некорректный отчёт')
        c.execute('BEGIN IMMEDIATE')
        current = c.execute('SELECT token FROM agents WHERE id=?', (agent_id,)).fetchone()
        if not current or not hmac.compare_digest(current['token'], agent['token']):
            raise HTTPException(401)
        received = time.time()
        encoded = data.model_dump_json()
        c.execute('INSERT INTO latest_reports VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET received=excluded.received,data=excluded.data', (agent_id,received,encoded))
        c.execute('INSERT INTO reports VALUES (?,?,?)',(agent_id,received,encoded))
        cleanup(c,received)
        from .updates import confirm
        confirm(c,agent_id,data)

        remote = c.execute('SELECT revision, data FROM agent_settings WHERE agent=?', (agent_id,)).fetchone()
        monitoring = {'revision': remote['revision'], 'settings': json.loads(remote['data'])} if remote else {'revision': 0, 'settings': None}
    if monitoring['settings'] is not None and 'auto_services_v1' not in data.features:
        monitoring['settings'].pop('auto_monitor_services', None)
    return {'ok': True, 'monitoring': monitoring, 'report_interval_seconds': 10}


@app.get('/health')
def health():
    with db() as c:
        c.execute('SELECT 1')
    return {'status': 'ok'}


@app.middleware('http')
async def private_pages(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == '/' or request.url.path.startswith(('/agents', '/history', '/settings', '/servers', '/events', '/bot')):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def csrf_token(request):
    return digest('agent-management:' + request.cookies.get('session', ''))


def agent_rows():
    with db() as c:
        return c.execute('SELECT a.id,r.received FROM agents a LEFT JOIN current_reports r ON a.id=r.agent ORDER BY a.id').fetchall()


@app.get('/agents', response_class=HTMLResponse)
def manage_agents(request: Request):
    if not authenticated(request):
        return RedirectResponse('/', status_code=303)
    return HTMLResponse(agents_page(agent_rows(), csrf_token(request)))


@app.post('/agents/{action}', response_class=HTMLResponse)
async def change_agent(action: str, request: Request):
    from urllib.parse import parse_qs
    if not authenticated(request):
        raise HTTPException(401, 'Войдите в панель')
    if action not in ('create', 'rotate', 'delete'):
        raise HTTPException(404)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise HTTPException(413)
    try:
        form = parse_qs(body.decode('utf-8'))
    except UnicodeDecodeError:
        raise HTTPException(400)
    value = lambda name: form.get(name, [''])[0]
    if not hmac.compare_digest(value('csrf').encode(), csrf_token(request).encode()):
        raise HTTPException(403, 'Обновите страницу и повторите действие')
    name = value('agent_id').strip()
    error, key = '', None
    status = 200
    with db() as c:
        if action == 'create':
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
                error, status = 'Некорректное имя агента.', 400
            else:
                key = secrets.token_urlsafe(32)
                try:
                    c.execute('INSERT INTO agents VALUES (?,?)', (name, digest(key)))
                    record(c,name,'configuration','Агент зарегистрирован')
                except sqlite3.IntegrityError:
                    key = None
                    error, status = 'Агент с таким именем уже существует.', 409
        else:
            # Reserve the write transaction so concurrent report ingestion cannot
            # insert a report between deleting history and deleting registration.
            c.execute('BEGIN IMMEDIATE')
            exists = c.execute('SELECT 1 FROM agents WHERE id=?', (name,)).fetchone()
            if not exists:
                error, status = 'Агент не найден.', 404
            elif action == 'rotate':
                if value('confirm') != 'yes':
                    error, status = 'Подтвердите отключение старого ключа.', 400
                else:
                    key = secrets.token_urlsafe(32)
                    c.execute('UPDATE agents SET token=? WHERE id=?', (digest(key), name))
                    record(c,name,'configuration','Ключ агента перевыпущен')
            elif value('confirmation') != name:
                error, status = 'Имя для подтверждения удаления не совпало.', 400
            else:
                c.execute('DELETE FROM reports WHERE agent=?', (name,))
                c.execute('DELETE FROM latest_reports WHERE agent=?', (name,))
                c.execute('DELETE FROM agents WHERE id=?', (name,))
                c.execute('DELETE FROM agent_update_jobs WHERE agent=?', (name,))
                record(c,name,'configuration','Агент удалён')
                c.execute('DELETE FROM agent_settings WHERE agent=?', (name,))
                c.execute('DELETE FROM agent_profiles WHERE agent=?', (name,))
    if action == 'delete' and not error:
        return RedirectResponse('/agents', status_code=303)
    return HTMLResponse(agents_page(agent_rows(), csrf_token(request), error, key, name), status_code=status)


@app.get('/history/{agent_id}', response_class=HTMLResponse)
def agent_history(agent_id: str, request: Request, period: str = '24h', nic: str = '', disk: str = ''):
    if not authenticated(request):
        return RedirectResponse('/', status_code=303)
    if period not in PERIODS:
        raise HTTPException(400, 'Неизвестный период')
    _, seconds, bucket = PERIODS[period]
    end = time.time()
    start = end - seconds
    with db() as c:
        if not c.execute('SELECT 1 FROM agents WHERE id=?', (agent_id,)).fetchone():
            raise HTTPException(404, 'Агент не найден')
        points = load_history(c, agent_id, start, end, bucket)
        from .io_history import sections
        io, selected_io = sections(c, agent_id, period, start, end, bucket, nic, disk)
    return HTMLResponse(history_page(agent_id, points, period, start, end, io, selected_io))


def settings_state(agent_id):
    with db() as c:
        if not c.execute('SELECT 1 FROM agents WHERE id=?', (agent_id,)).fetchone():
            raise HTTPException(404, 'Агент не найден')
        remote = c.execute('SELECT revision, data FROM agent_settings WHERE agent=?', (agent_id,)).fetchone()
        last = c.execute('SELECT data FROM current_reports WHERE agent=?', (agent_id,)).fetchone()
    report = json.loads(last['data']) if last else {}
    if remote:
        values = json.loads(remote['data'])
    else:
        # Seed the form from the latest observed rules, without changing the agent.
        rules = []
        for backup in report.get('backups', []):
            path = backup.get('path', '')
            if not path:
                continue
            schedule = backup.get('schedule', 'daily')
            filename = backup.get('file', '')
            pattern = filename.split('_backup_')[0] + '_backup_*.bak' if '_backup_' in filename else '*.bak'
            rules.append({'name': backup.get('name') or path, 'path': path,
                          'pattern': backup.get('pattern', pattern), 'schedule': schedule,
                          'recursive': backup.get('recursive', schedule == 'monthly'),
                          'date_from_filename': backup.get('date_from_filename', not filename or '_backup_' in filename),
                          'min_size_bytes': backup.get('min_size_bytes', 1024**3),
                          'max_age_hours': backup.get('max_age_hours', 30),
                          'grace_hours': backup.get('grace_hours', 36)})
        values = {'auto_monitor_services': report.get('auto_services_enabled') if report.get('auto_services_enabled') is not None else True, 'backups': rules[:20], 'services': report.get('manual_services') if report.get('manual_services') is not None else [s['name'] for s in report.get('services', []) if s.get('name') and not s.get('kind')]}
    return values, remote['revision'] if remote else 0, report.get('monitoring_revision')


@app.get('/settings/{agent_id}', response_class=HTMLResponse)
def monitoring_form(agent_id: str, request: Request):
    if not authenticated(request):
        return RedirectResponse('/', status_code=303)
    values, revision, applied = settings_state(agent_id)
    return HTMLResponse(settings_page(agent_id, values, csrf_token(request), revision, applied))


@app.post('/settings/{agent_id}', response_class=HTMLResponse)
async def monitoring_save(agent_id: str, request: Request):
    from urllib.parse import parse_qs
    from pydantic import ValidationError
    if not authenticated(request):
        raise HTTPException(401)
    values, revision, applied = settings_state(agent_id)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 64000:
            raise HTTPException(413)
    try:
        form = parse_qs(body.decode())
    except UnicodeDecodeError:
        raise HTTPException(400)
    def value(key, default=''):
        return form.get(key, [default])[0]
    if not hmac.compare_digest(value('csrf').encode(), csrf_token(request).encode()):
        raise HTTPException(403)
    error = ''
    try:
        if value('mode') == 'local':
            if value('confirm_local') != 'yes':
                raise ValueError('Подтвердите возврат к локальному файлу.')
            with db() as c:
                c.execute('DELETE FROM agent_settings WHERE agent=?', (agent_id,))
                record(c,agent_id,'configuration','Возврат к локальным настройкам')
            values, revision, applied = settings_state(agent_id)
        elif value('mode') == 'save':
            indices = sorted({int(key[5:]) for key in form if re.fullmatch(r'path_[0-9]{1,6}', key)})
            if len(indices) > 20:
                raise ValueError('Допустимо не более 20 правил.')
            rules = []
            for i in indices:
                path = value(f'path_{i}').strip()
                if not path:
                    continue
                minimum = float(value(f'min_size_gb_{i}', '1'))
                if not 0 <= minimum <= 1048576:
                    raise ValueError('Некорректный минимальный размер.')
                rules.append({'name': value(f'name_{i}').strip() or path,
                              'path': path, 'pattern': value(f'pattern_{i}', '*.bak').strip(),
                              'schedule': value(f'schedule_{i}', 'daily'),
                              'recursive': value(f'recursive_{i}') == 'yes',
                              'date_from_filename': value(f'date_from_filename_{i}') == 'yes',
                              'max_age_hours': float(value(f'max_age_hours_{i}', '30')),
                              'grace_hours': float(value(f'grace_hours_{i}', '36')),
                              'min_size_bytes': round(minimum * 1024**3)})
            services = list(dict.fromkeys(s.strip() for s in value('services').splitlines() if s.strip()))
            if any(len(s) > 255 for s in services):
                raise ValueError('Имя службы слишком длинное.')
            values = MonitoringSettings(backups=rules, services=services, auto_monitor_services=value('auto_monitor_services') == 'yes').model_dump()
            revision = time.time_ns()
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                if not c.execute('SELECT 1 FROM agents WHERE id=?', (agent_id,)).fetchone():
                    raise HTTPException(404)
                c.execute('INSERT INTO agent_settings VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET revision=excluded.revision, data=excluded.data', (agent_id, revision, json.dumps(values, ensure_ascii=False)))
                record(c,agent_id,'configuration','Настройки мониторинга изменены')
        else:
            raise ValueError('Неизвестное действие.')
    except (ValueError, OverflowError, ValidationError):
        error = 'Настройки не сохранены. Проверьте расписание, размеры и числовые пороги (возраст 1–8760 ч, ожидание 0–672 ч).'
    return HTMLResponse(settings_page(agent_id, values, csrf_token(request), revision, applied, error, not error), status_code=400 if error else 200)


@app.get('/servers/{agent_id}', response_class=HTMLResponse)
def server_detail(agent_id: str, request: Request):
    if not authenticated(request):
        return RedirectResponse('/', status_code=303)
    from .overview import detail_page
    row = next((row for row in server_rows() if row['id'] == agent_id), None)
    if row is None:
        raise HTTPException(404)
    from .forecast import load_forecasts
    with db() as c:
        current_disks = {d.get('path') for d in monitored_disks(json.loads(row['data'] or '{}'))}
        row['forecasts'] = {path: value for path,value in load_forecasts(c, agent_id, time.time()).items() if path in current_disks}
    return HTMLResponse(detail_page(row, csrf_token(request)))


@app.post('/servers/{agent_id}/name')
async def rename_server(agent_id: str, request: Request):
    from urllib.parse import parse_qs, quote
    if not authenticated(request):
        raise HTTPException(401)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise HTTPException(413)
    try:
        form = parse_qs(body.decode())
    except UnicodeDecodeError:
        raise HTTPException(400)
    csrf = form.get('csrf', [''])[0]
    if not hmac.compare_digest(csrf.encode(), csrf_token(request).encode()):
        raise HTTPException(403)
    name = form.get('display_name', [''])[0].strip()
    if len(name) > 120:
        raise HTTPException(400, 'Название не должно превышать 120 символов')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM agents WHERE id=?', (agent_id,)).fetchone():
            raise HTTPException(404)
        c.execute('INSERT INTO agent_profiles VALUES (?,?) ON CONFLICT(agent) DO UPDATE SET display_name=excluded.display_name', (agent_id, name))
        record(c,agent_id,'configuration','Название в панели изменено')
    return RedirectResponse('/servers/' + quote(agent_id, safe=''), status_code=303)


@app.middleware('http')
async def request_protection(request: Request, call_next):
    address = client_address(request)
    allowed, retry = limiter.allow(address)
    if not allowed:
        return JSONResponse({'detail': 'Слишком много запросов'}, status_code=429, headers={'Retry-After': str(retry), 'Cache-Control': 'no-store'})
    if request.method not in ('GET', 'HEAD', 'POST'):
        return JSONResponse({'detail': 'Метод не разрешён'}, status_code=405)
    length = request.headers.get('content-length')
    if length:
        try:
            if int(length) > 65536 or int(length) < 0:
                return JSONResponse({'detail': 'Слишком большой запрос'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': 'Некорректная длина запроса'}, status_code=400)
    # Do not cut off Windows agents behind the same public NAT as a blocked user.
    if not request.url.path.startswith(('/api/report/','/api/agent-update/')):
        with db() as c:
            wait = blocked_seconds(c, address, time.time())
        if wait:
            return JSONResponse({'detail': 'Адрес временно заблокирован после ошибок входа'}, status_code=429, headers={'Retry-After': str(wait), 'Cache-Control': 'no-store'})
    if request.url.path == '/login' and request.method == 'POST':
        allowed, retry = login_limiter.allow(address)
        if not allowed:
            return JSONResponse({'detail': 'Слишком частые попытки входа'}, status_code=429, headers={'Retry-After': str(retry), 'Cache-Control': 'no-store'})
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@app.get('/events', response_class=HTMLResponse)
def journal(request: Request, agent: str = '', level: str = '', before: int = 0):
    if not authenticated(request):
        return RedirectResponse('/', status_code=303)
    if level not in ('','warning','info') or len(agent)>255 or before<0:
        raise HTTPException(400)
    from .events import event_page
    with db() as c:
        rows=c.execute("SELECT * FROM events WHERE (?='' OR agent=?) AND (?='' OR level=?) AND (?=0 OR id<?) ORDER BY id DESC LIMIT 51",(agent,agent,level,level,before,before)).fetchall()
    return HTMLResponse(event_page(rows,agent,level,before))

@app.get('/bot', response_class=HTMLResponse)
def bot_status(request: Request):
    if not authenticated(request):
        return RedirectResponse('/', status_code=303)
    from .bot_health import health_page
    with db() as c:
        return HTMLResponse(health_page(c))

from .updates import register as register_updates
register_updates(app,db,authenticated,csrf_token,digest)
from .host_ui import register as register_host_ui
register_host_ui(app,db,authenticated)
