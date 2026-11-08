"""Identity-bound sessions and server-side access policy."""
from contextvars import ContextVar
import hashlib
import time
from fastapi.responses import JSONResponse

SCHEMA='''CREATE TABLE IF NOT EXISTS user_roles(name TEXT PRIMARY KEY,role TEXT NOT NULL CHECK(role IN ('viewer','administrator','superadmin')),enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)));
CREATE TABLE IF NOT EXISTS session_users(token TEXT PRIMARY KEY,name TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS session_users_name ON session_users(name);
CREATE TABLE IF NOT EXISTS access_migration(id INTEGER PRIMARY KEY CHECK(id=1));'''
ROLES={'viewer':'Пользователь','administrator':'Администратор','superadmin':'Суперадмин'}
_context=ContextVar('portal_principal',default=None)


def initialize(c):
    c.executescript(SCHEMA)
    if not c.execute('SELECT 1 FROM access_migration').fetchone():
        owner=c.execute("SELECT name FROM users ORDER BY CASE WHEN name='admin' THEN 0 ELSE 1 END,rowid LIMIT 1").fetchone()
        if owner:c.execute("INSERT OR IGNORE INTO user_roles VALUES (?,'superadmin',1)",(owner[0],))
        # Old sessions did not record an account identity; require a new login.
        c.execute('DELETE FROM sessions WHERE token NOT IN (SELECT token FROM session_users)')
        c.execute('INSERT INTO access_migration VALUES (1)')
        c.commit()


def principal(request,db):
    token=hashlib.sha256(request.cookies.get('session','').encode()).hexdigest()
    with db() as c:
        row=c.execute('''SELECT u.name,COALESCE(r.role,'viewer') AS role,COALESCE(r.enabled,1) AS enabled
            FROM sessions s JOIN session_users i ON i.token=s.token JOIN users u ON u.name=i.name
            LEFT JOIN user_roles r ON r.name=u.name WHERE s.token=? AND s.expires>?''',(token,time.time())).fetchone()
    if not row or not row['enabled']:return None
    return {'name':row['name'],'role':'superadmin' if row['name']=='admin' else row['role']}


def can_history():
    value=_context.get();return value is None or value.get('role') in ('administrator','superadmin')


def can_console():
    value=_context.get();return value is None or value.get('role')=='superadmin'


def can_users():
    value=_context.get();return value is None or value.get('role')=='superadmin' or value.get('name')=='admin'


def revoke(c,name):
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='ai_turns'").fetchone():
        c.execute("UPDATE ai_turns SET status='cancelled',updated=? WHERE owner=? AND status IN ('queued','running')",(time.time(),name))
    for table in ('console_grants','console_grant_tokens','console_challenges'):
        c.execute('DELETE FROM '+table+' WHERE session IN (SELECT token FROM session_users WHERE name=?)',(name,))
    c.execute('DELETE FROM sessions WHERE token IN (SELECT token FROM session_users WHERE name=?)',(name,))
    c.execute('DELETE FROM session_users WHERE name=?',(name,))


def middleware(db):
    async def enforce(request,call_next):
        user=principal(request,db) if request.cookies.get('session') else None
        token=_context.set(user or {'name':None,'role':None})
        try:
            path=request.url.path.rstrip('/') or '/'
            hidden=path=='/users' or path.startswith('/users/') or path.startswith('/console-access') or (path.startswith('/api/servers/') and any('/'+key in path for key in ('console','rdp')))
            if user:
                if hidden and ((path.startswith('/users') and not can_users()) or (not path.startswith('/users') and not can_console())):
                    return JSONResponse({'detail':'Not Found'},status_code=404,headers={'Cache-Control':'no-store'})
                current=(path=='/' and request.method=='GET') or path=='/logout' or (path.startswith('/servers/') and len(path.split('/'))==3 and request.method=='GET') or (path.startswith('/api/servers/') and path.endswith(('/processes','/services')) and request.method=='GET')
                infrastructure=path in ('/health','/login') or path.startswith(('/api/report/','/api/processes/','/api/agent-update/','/api/windows/','/api/console/'))
                if not current and not infrastructure and not can_history():return JSONResponse({'detail':'Доступ закрыт'},status_code=403,headers={'Cache-Control':'no-store'})
            elif path.startswith('/users'):
                return JSONResponse({'detail':'Not Found'},status_code=404,headers={'Cache-Control':'no-store'})
            return await call_next(request)
        finally:_context.reset(token)
    return enforce
