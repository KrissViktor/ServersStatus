import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from .dashboard import dashboard, login_page

DB = os.environ.get('STATUS_DB', 'status.sqlite3')
app = FastAPI(title='ServersStatus')


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
        CREATE INDEX IF NOT EXISTS reports_agent_time ON reports(agent, received);
        CREATE TABLE IF NOT EXISTS attempts (address TEXT PRIMARY KEY, count INTEGER, since REAL);
        ''')
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


@app.get('/', response_class=HTMLResponse)
def index(request: Request):
    if not authenticated(request):
        return HTMLResponse(login_page())
    with db() as c:
        rows = c.execute('SELECT a.id, r.received, r.data FROM agents a LEFT JOIN reports r ON r.rowid=(SELECT rowid FROM reports WHERE agent=a.id ORDER BY received DESC LIMIT 1) ORDER BY a.id').fetchall()
    return HTMLResponse(dashboard(rows))


@app.post('/login')
async def login(request: Request):
    from urllib.parse import parse_qs
    raw = await request.body()
    if len(raw) > 4096:
        raise HTTPException(413)
    form = parse_qs(raw.decode())
    name, password = form.get('username', [''])[0], form.get('password', [''])[0]
    address = request.client.host
    now = time.time()
    with db() as c:
        c.execute('DELETE FROM attempts WHERE since<?', (now - 900,))
        attempt = c.execute('SELECT count FROM attempts WHERE address=?', (address,)).fetchone()
        if attempt and attempt['count'] >= 10:
            raise HTTPException(429, 'Повторите через 15 минут')
        user = c.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
        salt = user['salt'] if user else '00' * 16
        calculated = password_hash(password, salt)
        valid = user is not None and hmac.compare_digest(calculated, user['password'])
        if not valid:
            c.execute('INSERT INTO attempts VALUES (?,1,?) ON CONFLICT(address) DO UPDATE SET count=count+1', (address, now))
        else:
            c.execute('DELETE FROM attempts WHERE address=?', (address,))
            token = secrets.token_urlsafe(32)
            c.execute('DELETE FROM sessions WHERE expires<?', (now,))
            c.execute('INSERT INTO sessions VALUES (?,?)', (digest(token), now + 28800))
    if not valid:
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


class Report(BaseModel):
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
        except ValueError:
            raise HTTPException(422, 'Некорректный отчёт')
        c.execute('INSERT INTO reports VALUES (?,?,?)', (agent_id, time.time(), data.model_dump_json()))
        c.execute('DELETE FROM reports WHERE received<?', (time.time() - 30 * 86400,))
    return {'ok': True}


@app.get('/health')
def health():
    with db() as c:
        c.execute('SELECT 1')
    return {'status': 'ok'}
