"""Observed portal storage, workers and backup status, without secret values."""
import hmac
import os
import re
from datetime import datetime,timezone
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import parse_qs
from fastapi import HTTPException,Request
from fastapi.responses import HTMLResponse,RedirectResponse
from .dashboard import page,esc,size,duration
from .windows_ui import stamp

STARTED=time.monotonic()
UNITS=['serversstatus.service','serversstatus-host-monitor.service','serversstatus-events.timer','serversstatus-events.service','serversstatus-notify.timer','serversstatus-notify.service','serversstatus-bot.service']


def systemd_snapshot():
    properties='Id,LoadState,ActiveState,SubState,UnitFileState,Result,ExecMainStatus,ExecMainStartTimestamp,LastTriggerUSec,NextElapseUSecRealtime'
    try:
        result=subprocess.run(['systemctl','show','--no-pager','--property='+properties,'--',*UNITS],capture_output=True,text=True,timeout=4,env={**os.environ,'TZ':'UTC','LC_ALL':'C'})
        rows=[]
        for block in result.stdout.strip().split('\n\n'):
            fields=dict(line.split('=',1) for line in block.splitlines() if '=' in line)
            if fields.get('Id') not in UNITS:continue
            rows.append(fields)
        return {'available':bool(rows),'items':rows}
    except (OSError,subprocess.SubprocessError):return {'available':False,'items':[]}


def systemd_time(value):
    match=re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',value or '')
    if not match:return 'Нет данных'
    try:return stamp(datetime.strptime(match.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp())
    except ValueError:return 'Нет данных'


def snapshot(c,path,now=None):
    now=time.time() if now is None else now
    database=Path(path).resolve();files=[]
    for suffix in ('','-wal','-shm','-journal'):
        file=Path(str(database)+suffix)
        try:
            if file.is_file():files.append({'name':file.name,'bytes':file.stat().st_size})
        except OSError:pass
    try:
        usage=shutil.disk_usage(database.parent);disk={'total':usage.total,'free':usage.free,'free_percent':100*usage.free/usage.total}
    except OSError:disk=None
    c.execute('SELECT 1').fetchone()
    last=c.execute('SELECT MAX(received) FROM current_reports').fetchone()[0]
    tasks=[dict(row) for row in c.execute('SELECT * FROM portal_task_state ORDER BY name')]
    recent=[dict(row) for row in c.execute('SELECT * FROM portal_backup_runs ORDER BY id DESC LIMIT 10')]
    success=c.execute("SELECT * FROM portal_backup_runs WHERE status='succeeded' ORDER BY id DESC LIMIT 1").fetchone()
    backup=dict(success) if success else None
    if backup:
        try:
            saved=Path(backup['path']);backup['file_present']=saved.is_file();backup['size_matches']=saved.is_file() and saved.stat().st_size==backup['bytes']
        except OSError:backup['file_present']=backup['size_matches']=False
    for row in recent:
        if row['status']=='running' and now-row['started']>600:row['status']='interrupted'
    bot=dict(c.execute("SELECT name,value FROM bot_state WHERE name IN ('heartbeat','last_poll','poll_error','send_error')").fetchall()) if c.execute("SELECT 1 FROM sqlite_master WHERE name='bot_state'").fetchone() else {}
    return {'bot':bot,'checked_at':now,'database_path':str(database),'files':files,'database_bytes':sum(item['bytes'] for item in files),'journal_mode':c.execute('PRAGMA journal_mode').fetchone()[0],
            'page_count':c.execute('PRAGMA page_count').fetchone()[0],'free_pages':c.execute('PRAGMA freelist_count').fetchone()[0],
            'disk':disk,'agents':c.execute('SELECT COUNT(*) FROM agents').fetchone()[0],'last_report':last,'tasks':tasks,'backup':backup,'recent_backups':recent,'process_uptime':time.monotonic()-STARTED}


def render(data,services,csrf):
    disk=data['disk'];backup=data['backup'];now=data['checked_at']
    content='<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/admin">Администрирование</a><a class="nav-link" href="/host">Raspberry Pi</a><a class="nav-link" href="/">← Серверы</a></header><div class="heading"><h1>Контроль портала</h1><span class="muted">Проверено: '+esc(stamp(now))+'</span></div>'
    content+='<div class="portal-metrics">'
    metrics=[('SQLite и журналы',size(data['database_bytes'])),('Свободное место',size(disk['free'])+' · '+f'{disk["free_percent"]:.1f}%' if disk else 'Недоступно'),('Последний отчёт',duration(now-data['last_report'])+' назад' if data['last_report'] is not None else 'Нет данных'),('Процесс портала',duration(data['process_uptime']))]
    content+=''.join('<div class="stat"><span>'+label+'</span><strong>'+esc(value)+'</strong></div>' for label,value in metrics)+'</div>'
    if disk and disk['free_percent']<10:content+='<p class="notice">Мало свободного места на разделе базы: '+f'{disk["free_percent"]:.1f}%.</p>'
    content+='<section class="server"><h2>База данных</h2><p class="text-normal">Чтение SQLite работает</p><p class="muted">'+esc(data['database_path'])+' · режим '+esc(data['journal_mode'])+' · страниц '+str(data['page_count'])+', свободных внутри базы '+str(data['free_pages'])+'</p>'
    for item in data['files']:content+='<p>'+esc(item['name'])+' · '+esc(size(item['bytes']))+'</p>'
    content+='<p class="muted legend">Проверка подключения и размеров не является полной проверкой целостности базы. Свободные страницы SQLite могут быть повторно использованы.</p></section>'
    content+='<section class="server"><h2>Резервные копии</h2>'
    if backup:
        state='Файл на месте, размер совпадает' if backup['file_present'] and backup['size_matches'] else 'Файл отсутствует или изменён'
        content+='<p class="'+('text-normal' if backup['file_present'] and backup['size_matches'] else 'text-warning')+'">Последняя успешная копия: '+esc(stamp(backup['finished']))+' · '+esc(size(backup['bytes']))+' · '+state+'</p><p class="muted">SQLite quick_check: ok на момент создания · SHA-256: '+esc(backup['sha256'])+'</p>'
    else:content+='<p class="muted">Нет зарегистрированных копий. Внешние резервные копии здесь не учитываются.</p>'
    running=any(row['status']=='running' for row in data['recent_backups'])
    content+='<form method="post" action="/portal-health/backup"><input type="hidden" name="csrf" value="'+esc(csrf)+'"><button '+('disabled' if running else '')+'>'+('Копирование выполняется…' if running else 'Создать копию базы')+'</button></form><p class="muted legend">Копия создаётся на сервере через SQLite Backup API и проверяется до сохранения результата. Остановка портала не требуется. Файл не публикуется и не скачивается через браузер; каталог задаётся STATUS_BACKUP_DIR, по умолчанию backups рядом с базой.</p>'
    labels={'running':'Выполняется','succeeded':'Успешно','failed':'Ошибка','interrupted':'Процесс прерван'}
    for row in data['recent_backups']:
        content+='<p class="backup-run">'+esc(stamp(row['started']))+' · '+labels.get(row['status'],'Неизвестно')+(' · '+esc(row['error']) if row.get('error') else '')+'</p>'
    content+='</section><section class="server"><h2>Фоновые задачи</h2>'
    task_names={'events':'Обработка событий','retention':'Очистка истории','notifications':'Проверка уведомлений'}
    if not data['tasks']:content+='<p class="muted">Отметок выполнения пока нет. Они появятся после работы обновлённых задач.</p>'
    for item in data['tasks']:
        limit=7500 if item['name']=='retention' else 300
        status='Нет свежей отметки' if now-item['checked']>limit else 'Обработка завершилась' if item['status']=='ok' else 'Есть ошибки'
        content+='<p><b>'+esc(task_names.get(item['name'],item['name']))+'</b> · '+status+' · '+esc(stamp(item['checked']))+'</p>'+('<p class="muted">'+esc(item['detail'])+'</p>' if item['detail'] else '')
    if data['bot']:
        try:age=now-float(data['bot'].get('heartbeat',0))
        except ValueError:age=float('inf')
        content+='<p><b>Telegram-бот</b> · '+('Есть свежая отметка процесса' if age<180 else 'Нет свежей отметки процесса')+'</p><p class="muted">'+('Есть ошибка опроса или отправки' if data['bot'].get('poll_error') or data['bot'].get('send_error') else 'Ошибки не заявлены процессом')+'</p>'
    content+='<h3 class="portal-subheading">Службы и таймеры systemd</h3>'
    if not services['available']:content+='<p class="muted">Состояние systemd недоступно в этой среде.</p>'
    else:
        content+='<div class="table-scroll"><table class="metric-table"><tr><th>Компонент</th><th>Наблюдаемое состояние</th><th>Результат / последний запуск</th></tr>'
        for item in services['items']:
            state='Не установлено' if item.get('LoadState')=='not-found' else item.get('ActiveState','Неизвестно')+' / '+item.get('SubState','')
            result=item.get('Result') or 'Не сообщается'
            if item.get('ExecMainStatus'):result+=' · код '+item['ExecMainStatus']
            last=systemd_time(item.get('LastTriggerUSec') or item.get('ExecMainStartTimestamp'))
            if item.get('NextElapseUSecRealtime'):last+='; следующий: '+systemd_time(item['NextElapseUSecRealtime'])
            content+='<tr><td>'+esc(item['Id'])+'</td><td>'+esc(state)+'</td><td>'+esc(result)+' · '+esc(last)+'</td></tr>'
        content+='</table></div>'
    content+='<p class="muted legend">Отметка выполнения подтверждает запуск задачи, а не доставку каждого уведомления. Отсутствующий компонент не считается автоматически неисправным. Страница показывает состояние на момент открытия; обновите её для новых результатов.</p></section>'
    if running:content+='<script>setTimeout(()=>location.reload(),3000)</script>'
    return page('<div class="portal-health">'+content+'</div>')


def register(app,db,authenticated,csrf_token):
    @app.get('/portal-health',response_class=HTMLResponse)
    def health(request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        from .app import DB
        with db() as c:data=snapshot(c,DB)
        return HTMLResponse(render(data,systemd_snapshot(),csrf_token(request)))

    @app.post('/portal-health/backup')
    async def backup(request:Request):
        if not authenticated(request):raise HTTPException(401)
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>4096:raise HTTPException(413)
        try:token=parse_qs(raw.decode('utf-8')).get('csrf',[''])[0]
        except UnicodeDecodeError:raise HTTPException(400)
        if not hmac.compare_digest(token.encode(),csrf_token(request).encode()):raise HTTPException(403)
        from .app import DB
        from .portal_backup import launch
        if not launch(db,DB):raise HTTPException(409,'Резервное копирование уже выполняется')
        return RedirectResponse('/portal-health',303)
