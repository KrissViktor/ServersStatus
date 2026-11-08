"""Account management visible only to privileged owners."""
import asyncio
import hmac
import re
import secrets
from urllib.parse import parse_qs
from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse
from .access import principal,ROLES,revoke
from .dashboard import page,esc
from .events import record
from .console import read_body


def render(rows,csrf,actor,message=''):
    hidden='<input type="hidden" name="csrf" value="'+esc(csrf)+'">'
    def choices(selected):return ''.join('<option value="'+key+'" '+('selected' if key==selected else '')+'>'+value+'</option>' for key,value in ROLES.items())
    content='<header class="topbar"><a href="/admin">← Администрирование</a></header><div class="heading"><h1>Пользователи</h1></div>'
    if message:content+='<p class="notice">'+esc(message)+'</p>'
    content+='<details class="server user-create"><summary>Добавить пользователя</summary><form method="post" action="/users/create">'+hidden+'<label>Логин<input name="name" required pattern="[A-Za-z0-9_.-]{1,64}" maxlength="64" autocomplete="off"></label><label>Пароль (от 12 символов)<input type="password" name="password" required minlength="12" maxlength="256" autocomplete="new-password"></label><label>Доступ<select name="role">'+choices('viewer')+'</select></label><button>Создать пользователя</button></form></details><div class="user-grid">'
    for row in rows:
        name=row['name'];role='superadmin' if name=='admin' else row['role'];enabled=bool(row['enabled'])
        fields=hidden+'<input type="hidden" name="name" value="'+esc(name)+'">'
        content+='<article class="server user-card"><header class="server-head"><h2>'+esc(name)+(' · Вы' if name==actor else '')+'</h2><span class="badge '+('normal' if enabled else 'neutral')+'">'+('Включён' if enabled else 'Отключён')+'</span></header><p class="muted">'+ROLES[role]+'</p>'
        if name!='admin':
            content+='<form method="post" action="/users/edit">'+fields+'<label>Доступ<select name="role">'+choices(role)+'</select></label><label class="check"><input type="checkbox" name="enabled" value="1" '+('checked' if enabled else '')+'> Учётная запись включена</label><button>Сохранить доступ</button></form>'
        else:content+='<p class="muted">Основная учётная запись: доступ сохраняется.</p>'
        content+='<details><summary>Изменить пароль</summary><form method="post" action="/users/password">'+fields+'<label>Новый пароль<input type="password" name="password" required minlength="12" maxlength="256" autocomplete="new-password"></label><button>Сменить пароль и завершить сеансы</button></form></details>'
        if name!=actor and name!='admin':
            content+='<details><summary>Удалить пользователя</summary><form method="post" action="/users/delete">'+fields+'<label>Для подтверждения введите логин<input name="confirmation" required autocomplete="off"></label><button class="delete-button">Удалить пользователя</button></form></details>'
        content+='</article>'
    return page(content+'</div><p class="muted">Пользователь — текущий просмотр. Администратор — история, графики и настройки без консоли. Суперадмин — полный доступ; консоль дополнительно защищена тремя шагами. Изменения доступа/пароля завершают сеансы. Список и роли видны только здесь.</p>')


def register(app,db,csrf_token,digest,password_hash):
    def owner(request):
        user=principal(request,db)
        if not user or (user['role']!='superadmin' and user['name']!='admin'):raise HTTPException(404)
        return user
    def account_rows(c):return c.execute("SELECT u.name,COALESCE(r.role,'viewer') AS role,COALESCE(r.enabled,1) AS enabled FROM users u LEFT JOIN user_roles r ON r.name=u.name ORDER BY u.name").fetchall()

    @app.get('/users',response_class=HTMLResponse)
    def listing(request:Request):
        actor=owner(request)
        with db() as c:rows=account_rows(c)
        return HTMLResponse(render(rows,csrf_token(request),actor['name']),headers={'Cache-Control':'no-store'})

    @app.post('/users/{action}')
    async def change(action:str,request:Request):
        actor=owner(request)
        if action not in ('create','edit','password','delete'):raise HTTPException(404)
        try:form=parse_qs((await read_body(request,8192)).decode('utf-8'))
        except UnicodeDecodeError:raise HTTPException(400)
        value=lambda key:form.get(key,[''])[0]
        if not hmac.compare_digest(value('csrf').encode(),csrf_token(request).encode()):raise HTTPException(403)
        name=value('name');role=value('role');password=value('password')
        if not name or len(name)>255:raise HTTPException(400,'Проверьте логин')
        salt=encoded=None
        if action in ('create','password'):
            if not 12<=len(password)<=256:raise HTTPException(400,'Пароль должен содержать от 12 до 256 символов')
            salt=secrets.token_hex(16);encoded=await asyncio.to_thread(password_hash,password,salt)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            valid=c.execute("SELECT u.name,COALESCE(r.role,'viewer') AS role FROM sessions s JOIN session_users i ON i.token=s.token JOIN users u ON u.name=i.name LEFT JOIN user_roles r ON r.name=u.name WHERE s.token=? AND s.expires>strftime('%s','now') AND COALESCE(r.enabled,1)=1",(digest(request.cookies.get('session','')),)).fetchone()
            if not valid or (valid['name']!='admin' and valid['role']!='superadmin'):raise HTTPException(404)
            existing=c.execute("SELECT u.name,COALESCE(r.role,'viewer') AS role,COALESCE(r.enabled,1) AS enabled FROM users u LEFT JOIN user_roles r ON r.name=u.name WHERE u.name=?",(name,)).fetchone()
            if action=='create':
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',name) or role not in ROLES or (name=='admin' and role!='superadmin'):raise HTTPException(400,'Проверьте логин и доступ')
                if c.execute('SELECT 1 FROM users WHERE lower(name)=lower(?)',(name,)).fetchone():raise HTTPException(409,'Этот логин уже занят')
                c.execute('INSERT INTO users VALUES (?,?,?)',(name,salt,encoded))
                c.execute('INSERT INTO user_roles VALUES (?,?,1)',(name,role))
                record(c,'','users','Создан пользователь '+name+' · '+ROLES[role])
            else:
                if not existing:raise HTTPException(404)
                if action=='edit':
                    enabled=int(value('enabled')=='1')
                    if role not in ROLES or value('enabled') not in ('','1'):raise HTTPException(400)
                    if name=='admin' or (name==actor['name'] and (role!=actor['role'] or not enabled)):raise HTTPException(400,'Собственный и основной доступ сохраняются')
                    if role!=existing['role'] or enabled!=existing['enabled']:
                        c.execute('INSERT INTO user_roles VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET role=excluded.role,enabled=excluded.enabled',(name,role,enabled))
                        revoke(c,name)
                        record(c,'','users','Изменён доступ пользователя '+name+' · '+ROLES[role]+' · '+('включён' if enabled else 'отключён'))
                elif action=='password':
                    c.execute('UPDATE users SET salt=?,password=? WHERE name=?',(salt,encoded,name));revoke(c,name)
                    record(c,'','users','Изменён пароль пользователя '+name)
                else:
                    if name=='admin' or name==actor['name']:raise HTTPException(400,'Нельзя удалить собственную или основную учётную запись')
                    if value('confirmation')!=name:raise HTTPException(400,'Введите точный логин')
                    c.execute('DELETE FROM ai_turns WHERE owner=?',(name,));revoke(c,name);c.execute('DELETE FROM user_roles WHERE name=?',(name,));c.execute('DELETE FROM users WHERE name=?',(name,))
                    record(c,'','users','Удалён пользователь '+name)
        return RedirectResponse('/' if action=='password' and name==actor['name'] else '/users',303)
