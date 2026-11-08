"""Session-bound three-step authorization for protected actions."""
import asyncio
import getpass
import hashlib
import hmac
import os
import re
import secrets
import string
import time
from urllib.parse import parse_qs
from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,JSONResponse
from .security import client_address,blocked_seconds,failed_login

SCHEMA='''CREATE TABLE IF NOT EXISTS console_access_config(id INTEGER PRIMARY KEY CHECK(id=1),salt TEXT,pin TEXT,pepper TEXT);
CREATE TABLE IF NOT EXISTS console_challenges(session TEXT PRIMARY KEY,step INTEGER,nonce TEXT,digest TEXT,expires REAL,created REAL);
CREATE TABLE IF NOT EXISTS console_grants(session TEXT PRIMARY KEY,expires REAL);
CREATE TABLE IF NOT EXISTS console_grant_tokens(session TEXT PRIMARY KEY,token TEXT);
CREATE TABLE IF NOT EXISTS console_delivery_rate(created REAL);'''
ACCESS_SECONDS=1800
_slots=asyncio.Semaphore(2)


def session_key(request):return hashlib.sha256(request.cookies.get('session','').encode()).hexdigest()


def unlocked(request,db):
    with db() as c:
        now=time.time()
        return c.execute('SELECT 1 FROM console_grants g JOIN sessions s ON s.token=g.session JOIN console_grant_tokens t ON t.session=g.session WHERE g.session=? AND g.expires>? AND s.expires>? AND t.token=?',(session_key(request),now,now,hashlib.sha256(request.cookies.get('__Host-console-access','').encode()).hexdigest())).fetchone() is not None


def require(request,db):
    if not unlocked(request,db):raise HTTPException(403,'Доступ закрыт')


def pin_hash(pin,salt):return hashlib.scrypt(pin.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()


def code_hash(config,session,nonce,code):
    return hmac.new(bytes.fromhex(config['pepper']),(session+':'+nonce+':'+code).encode(),hashlib.sha256).hexdigest()


def send_code(code,step):
    from .notifications import send_message
    token=os.environ.get('STATUS_TELEGRAM_TOKEN','').strip();chat=os.environ.get('STATUS_TELEGRAM_CHAT_ID','').strip()
    if not token or not chat:raise RuntimeError('Telegram unavailable')
    send_message(token,chat,'🔐 Снятие защиты портала · шаг '+str(step)+'/3\nКод: '+code+'\nДействует 5 минут. Если вы не запрашивали код, не вводите и никому не сообщайте его.')


def access_page(request,db,csrf,message='',fragment=False):
    from .dashboard import page,esc
    with db() as c:
        config=c.execute('SELECT 1 FROM console_access_config').fetchone()
        challenge=c.execute('SELECT step,expires FROM console_challenges WHERE session=?',(session_key(request),)).fetchone()
    def render(body):
        if fragment:return body
        return page('<header class="topbar"><a href="/">← На главную</a></header>'+body)
    body='<h1 id="protection-title">Снятие защиты</h1>'
    if message:body+='<p class="notice">'+esc(message)+'</p>'
    if not config:return render(body+'<p>Защита ещё не настроена администратором. Выполните настройку на Raspberry Pi по deploy/CONSOLE-ACCESS.md.</p>')
    if unlocked(request,db):
        return render(body+f'<p>Защита снята для этого сеанса на 30 минут.</p><form method="post" action="/console-access/lock"><input type="hidden" name="csrf" value="{esc(csrf)}"><button>Включить защиту</button></form><a href="/">Вернуться к серверам</a>')
    step=challenge['step'] if challenge and challenge['expires']>time.time() else 1
    if step==0:return render(body+'<p>Код отправляется. Обновите страницу через несколько секунд.</p>')
    if step==1:
        label='Постоянный PIN: 4 цифры';pattern='[0-9]{4}';maxlength=4;autocomplete='off'
    elif step==2:
        label='Код из Telegram: 6 цифр';pattern='[0-9]{6}';maxlength=6;autocomplete='one-time-code'
    else:
        label='Второй код из Telegram: 6 цифр и латинских букв';pattern='[A-Za-z0-9]{6}';maxlength=6;autocomplete='off'
    return render(body+f'<section class="server"><h2>Шаг {step} из 3</h2><form method="post" action="/console-access"><input type="hidden" name="csrf" value="{esc(csrf)}"><label>{label}<input type="password" name="code" required pattern="{pattern}" maxlength="{maxlength}" autocomplete="{autocomplete}" autofocus></label><button>Продолжить</button></form><p class="muted">Каждый код действует 5 минут. Доступ откроется только после всех трёх шагов.</p></section>')


def register(app,db,authenticated,csrf_token):
    @app.get('/console-access',response_class=HTMLResponse)
    def form(request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        return HTMLResponse(access_page(request,db,csrf_token(request),fragment=request.query_params.get('modal')=='1'),headers={'Cache-Control':'no-store'})

    @app.get('/console-access/status')
    def state(request:Request):
        return JSONResponse({'unlocked':authenticated(request) and unlocked(request,db)},headers={'Cache-Control':'no-store'})

    @app.post('/console-access')
    async def check(request:Request):
        if not authenticated(request):raise HTTPException(401)
        from .console import read_body
        try:fields=parse_qs((await read_body(request,4096)).decode())
        except UnicodeDecodeError:raise HTTPException(400)
        if not hmac.compare_digest(fields.get('csrf',[''])[0].encode(),csrf_token(request).encode()):raise HTTPException(403)
        code=fields.get('code',[''])[0]
        if len(code)>64:raise HTTPException(400)
        session=session_key(request);address='console:'+client_address(request);now=time.time()
        error='';delivery=None;lease_token=None
        with db() as c:
            config=c.execute('SELECT * FROM console_access_config').fetchone()
            challenge=c.execute('SELECT * FROM console_challenges WHERE session=?',(session,)).fetchone()
            if blocked_seconds(c,address,now):error='Временно заблокировано после ошибок. Попробуйте позже.'
            elif not config:error='Защита не настроена.'
        if not error:
            step=challenge['step'] if challenge and challenge['expires']>now else 1
            if step==0:error='Дождитесь отправки кода.'
            else:
                async with _slots:
                    valid=await asyncio.to_thread(lambda: bool(re.fullmatch('[0-9]{4}',code)) and hmac.compare_digest(pin_hash(code,config['salt']),config['pin'])) if step==1 else hmac.compare_digest(code_hash(config,session,challenge['nonce'],code),challenge['digest'])
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    fresh=c.execute('SELECT * FROM console_challenges WHERE session=?',(session,)).fetchone()
                    settings=c.execute('SELECT * FROM console_access_config').fetchone()
                    if not settings or settings['pin']!=config['pin'] or blocked_seconds(c,address,time.time()):error='Запрос устарел или временно заблокирован.'
                    elif step>1 and (not fresh or fresh['nonce']!=challenge['nonce'] or fresh['step']!=step or fresh['expires']<time.time()):error='Код истёк или уже использован.'
                    elif step==1 and fresh and fresh['expires']>time.time():error='Продолжите текущую проверку или дождитесь её окончания.'
                    elif not valid:
                        failed_login(c,address,time.time());c.execute('DELETE FROM console_challenges WHERE session=?',(session,))
                        error='Неверный или просроченный код. Начните проверку заново.'
                    elif step==3:
                        lease_token=secrets.token_urlsafe(32)
                        c.execute('INSERT INTO console_grant_tokens VALUES (?,?) ON CONFLICT(session) DO UPDATE SET token=excluded.token',(session,hashlib.sha256(lease_token.encode()).hexdigest()))
                        c.execute('DELETE FROM console_challenges WHERE session=?',(session,))
                        c.execute('INSERT INTO console_grants VALUES (?,?) ON CONFLICT(session) DO UPDATE SET expires=excluded.expires',(session,time.time()+ACCESS_SECONDS))
                        c.execute('UPDATE auth_guard SET failures=0 WHERE address=?',(address,))
                        from .events import record
                        record(c,'','security','Защита снята для сеанса портала на 30 минут')
                    else:
                        c.execute('DELETE FROM console_delivery_rate WHERE created<?',(time.time()-60,))
                        if c.execute('SELECT count(*) FROM console_delivery_rate').fetchone()[0]>=6:
                            error='Слишком много отправок. Повторите через минуту.'
                        nonce=secrets.token_hex(16)
                        if step==1:otp=''.join(secrets.choice(string.digits) for _ in range(6))
                        else:
                            chars=[secrets.choice(string.digits),secrets.choice(string.ascii_letters)]+[secrets.choice(string.digits+string.ascii_letters) for _ in range(4)]
                            secrets.SystemRandom().shuffle(chars);otp=''.join(chars)
                        if not error:c.execute('INSERT INTO console_challenges VALUES (?,0,?,?,?,?) ON CONFLICT(session) DO UPDATE SET step=0,nonce=excluded.nonce,digest=excluded.digest,expires=excluded.expires,created=excluded.created',(session,nonce,code_hash(config,session,nonce,otp),time.time()+300,time.time()))
                        if not error:
                            c.execute('INSERT INTO console_delivery_rate VALUES (?)',(time.time(),))
                            delivery=(otp,step+1,nonce)
        if delivery:
            otp,next_step,nonce=delivery
            try:await asyncio.to_thread(send_code,otp,next_step)
            except Exception:
                with db() as c:c.execute('DELETE FROM console_challenges WHERE session=? AND nonce=?',(session,nonce))
                error='Не удалось отправить код в Telegram. Доступ остаётся закрытым.'
            else:
                with db() as c:c.execute('UPDATE console_challenges SET step=? WHERE session=? AND nonce=?',(next_step,session,nonce))
        if error:return HTMLResponse(access_page(request,db,csrf_token(request),error,fragment=request.query_params.get('modal')=='1'),status_code=400,headers={'Cache-Control':'no-store'})
        response=HTMLResponse(access_page(request,db,csrf_token(request),fragment=True),headers={'Cache-Control':'no-store'}) if request.query_params.get('modal')=='1' else RedirectResponse('/console-access',303)
        if lease_token and request.query_params.get('modal')=='1':response=HTMLResponse('<h1 id="protection-title">Защита снята</h1><p>Доступ открыт на 30 минут.</p>',headers={'Cache-Control':'no-store'})
        if lease_token:response.set_cookie('__Host-console-access',lease_token,max_age=ACCESS_SECONDS,httponly=True,secure=True,samesite='strict',path='/')
        return response

    @app.post('/console-access/lock')
    async def lock(request:Request):
        if not authenticated(request):raise HTTPException(401)
        from .console import read_body
        try:fields=parse_qs((await read_body(request,4096)).decode())
        except UnicodeDecodeError:raise HTTPException(400)
        if not hmac.compare_digest(fields.get('csrf',[''])[0].encode(),csrf_token(request).encode()):raise HTTPException(403)
        with db() as c:
            c.execute('DELETE FROM console_grant_tokens WHERE session=?',(session_key(request),))
            c.execute('DELETE FROM console_grants WHERE session=?',(session_key(request),));c.execute('DELETE FROM console_challenges WHERE session=?',(session_key(request),))
            from .events import record
            record(c,'','security','Защита включена для сеанса портала')
        response=HTMLResponse(access_page(request,db,csrf_token(request),fragment=True),headers={'Cache-Control':'no-store'}) if request.query_params.get('modal')=='1' else RedirectResponse('/',303)
        response.delete_cookie('__Host-console-access',path='/',secure=True,httponly=True,samesite='strict');return response


def main():
    from .app import db
    pin=getpass.getpass('New 4-digit console PIN: ')
    if not re.fullmatch('[0-9]{4}',pin) or pin!=getpass.getpass('Repeat PIN: '):raise SystemExit('PIN must match and contain exactly 4 digits')
    salt=secrets.token_hex(16)
    with db() as c:
        c.execute('INSERT INTO console_access_config VALUES (1,?,?,?) ON CONFLICT(id) DO UPDATE SET salt=excluded.salt,pin=excluded.pin,pepper=excluded.pepper',(salt,pin_hash(pin,salt),secrets.token_hex(32)))
        c.execute('DELETE FROM console_grant_tokens');c.execute('DELETE FROM console_grants');c.execute('DELETE FROM console_challenges')
        c.execute("DELETE FROM auth_guard WHERE address LIKE 'console:%'")
    print('PIN configured. All previous protected sessions were locked.')

if __name__=='__main__':main()
