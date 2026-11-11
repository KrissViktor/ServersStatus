"""Superadministrator-only retention policy; configuration itself is not purged."""
import hmac
from urllib.parse import parse_qs
from fastapi import HTTPException,Request
from fastapi.responses import HTMLResponse,RedirectResponse

DEFAULT_DAYS=186
SCHEMA='CREATE TABLE IF NOT EXISTS portal_settings(name TEXT PRIMARY KEY,value TEXT NOT NULL);'


def retention_days(c):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='portal_settings'").fetchone():return DEFAULT_DAYS
    row=c.execute("SELECT value FROM portal_settings WHERE name='retention_days'").fetchone()
    try:value=int(row[0]) if row else DEFAULT_DAYS
    except (TypeError,ValueError):return DEFAULT_DAYS
    return value if 1<=value<=3650 else DEFAULT_DAYS


def register(app,db,authenticated,csrf_token):
    from .access import can_console
    from .dashboard import page,esc
    @app.get('/portal-settings',response_class=HTMLResponse)
    def settings(request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        if not can_console():raise HTTPException(403)
        with db() as c:days=retention_days(c)
        content='<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/admin">← Администрирование</a></header><div class="heading"><h1>Настройки хранения</h1><span class="badge neutral">Только суперадминистратор</span></div><section class="server"><h2>История мониторинга</h2><form method="post"><input type="hidden" name="csrf" value="'+esc(csrf_token(request))+'"><label>Хранить записи, дней<input type="number" name="retention_days" min="1" max="3650" required value="'+str(days)+'"></label><p class="muted">От 1 до 3650 дней. Сейчас: '+str(days)+'. Применяется к отчётам, процессам, службам, инцидентам, журналу событий, истории ИИ и консоли.</p><label class="check"><input type="checkbox" name="confirm_shorter" value="yes">При уменьшении срока подтверждаю удаление более старых записей при следующей очистке</label><button class="primary">Сохранить срок хранения</button></form><details class="service-details"><summary>Как работает хранение</summary><p class="muted legend">Увеличение срока не восстанавливает удалённые данные. Текущие состояния, настройки, новости и записи о резервных копиях не удаляются. Для оборудования и служб сохраняется последняя базовая запись перед границей истории.</p></details></section>'
        return HTMLResponse(page(content))

    @app.post('/portal-settings')
    async def save(request:Request):
        if not authenticated(request):raise HTTPException(401)
        if not can_console():raise HTTPException(403)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>4096:raise HTTPException(413)
        try:form=parse_qs(body.decode('utf-8'));days=int(form.get('retention_days',[''])[0])
        except (UnicodeDecodeError,ValueError):raise HTTPException(400,'Укажите целое число дней') from None
        if not hmac.compare_digest(form.get('csrf',[''])[0].encode(),csrf_token(request).encode()):raise HTTPException(403)
        if not 1<=days<=3650:raise HTTPException(400,'Допустимо от 1 до 3650 дней')
        with db() as c:
            c.execute('BEGIN IMMEDIATE');previous=retention_days(c)
            if days<previous and form.get('confirm_shorter',[''])[0]!='yes':raise HTTPException(400,'Подтвердите сокращение срока хранения')
            c.execute("INSERT INTO portal_settings VALUES ('retention_days',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(str(days),))
            c.execute("DELETE FROM report_maintenance WHERE name='retention'")
            from .events import record
            record(c,'','configuration','Срок хранения истории: '+str(previous)+' → '+str(days)+' дней')
        return RedirectResponse('/portal-settings',303)
