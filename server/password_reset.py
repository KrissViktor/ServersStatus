"""One-time password setup links issued by authorized Telegram operators."""
import asyncio
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import os

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .access import revoke
from .dashboard import esc, page
from .events import record
from .portal_sessions import reset_digest


def issue(c, account, now):
    try:
        url = urlsplit(os.environ.get('STATUS_PANEL_URL','').strip())
    except ValueError:
        return None
    if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        return None
    token = secrets.token_urlsafe(32)
    c.execute('DELETE FROM portal_password_resets WHERE account=?',(account,))
    c.execute('INSERT INTO portal_password_resets VALUES (?,?,?)',(reset_digest(token),account,now+600))
    return url.geturl().rstrip('/')+'/password-reset?'+urlencode({'token':token})


def lookup(c, token, now):
    return c.execute("""SELECT p.account FROM portal_password_resets p
        JOIN users u ON u.name=p.account LEFT JOIN user_roles r ON r.name=u.name
        WHERE p.token=? AND p.expires>? AND COALESCE(r.enabled,1)=1""",(token,now)).fetchone()


def register(app, db, password_hash, slots):
    def key(value):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',value):
            raise HTTPException(404,'Ссылка недействительна или истекла')
        return reset_digest(value)

    @app.get('/password-reset',response_class=HTMLResponse)
    def form(request:Request, token:str=''):
        with db() as c:
            row = lookup(c,key(token),time.time())
        if not row:
            raise HTTPException(404,'Ссылка недействительна или истекла')
        content = (
            '<section class="server"><h1>Новый пароль</h1><p>Учётная запись '+esc(row['account'])+'</p>'
            '<form action="/password-reset" method="post"><input type="hidden" name="token" value="'+esc(token)+'">'
            '<label>Новый пароль<input type="password" name="password" autocomplete="new-password" '
            'required minlength="12" maxlength="256"></label><button>Сменить пароль и завершить сеансы</button></form></section>'
        )
        return HTMLResponse(page(content,refresh=False))

    @app.post('/password-reset')
    async def change(request:Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>4096:raise HTTPException(413)
        try:
            form_data = parse_qs(body.decode())
        except UnicodeDecodeError:
            raise HTTPException(400) from None
        token = key(form_data.get('token',[''])[0])
        password = form_data.get('password',[''])[0]
        if not 12<=len(password)<=256:
            raise HTTPException(400,'Пароль должен содержать от 12 до 256 символов')
        with db() as c:
            if not lookup(c,token,time.time()):
                raise HTTPException(404,'Ссылка недействительна или истекла')
        salt = secrets.token_hex(16)
        async with slots:
            encoded = await asyncio.to_thread(password_hash,password,salt)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = lookup(c,token,time.time())
            if not row:
                raise HTTPException(404,'Ссылка недействительна или истекла')
            account = row['account']
            c.execute('UPDATE users SET salt=?,password=? WHERE name=?',(salt,encoded,account))
            c.execute("UPDATE account_auth_guard SET failures=0,blocked_until='0' WHERE name=?",(account,))
            revoke(c,account)
            record(c,'','users','Изменён пароль по одноразовой ссылке Telegram · '+account)
        response = RedirectResponse('/',303)
        response.delete_cookie('session')
        return response
