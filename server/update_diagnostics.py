"""Only explicit, allowlisted agent observations become update progress."""
STAGES={'download':'Скачивание пакета','verify':'Проверка SHA-256','prepare':'Подготовка и проверка Linux-пакета',
        'stop':'Остановка службы агента','wait_exit':'Ожидание освобождения EXE','backup':'Резервная копия предыдущей версии',
        'replace':'Замена файлов агента','start':'Запуск службы агента','health':'Проверка работы службы',
        'awaiting_version':'Ожидание первого отчёта новой версии','confirmed':'Версия подтверждена порталом'}
PREPARATION_CODES=('archive_invalid','version_mismatch','dependency_changed','python_invalid','permissions','backup_exists')
ROLLBACK={'unknown':'Результат восстановления не сообщён','not_needed':'Замена не потребовала восстановления',
          'restored':'Предыдущая версия восстановлена, служба запущена','failed':'Восстановление не завершено — нужна локальная проверка'}
SCHEMA='''CREATE TABLE IF NOT EXISTS update_job_steps(job INTEGER NOT NULL,stage TEXT NOT NULL,phase TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(job,stage));
CREATE TABLE IF NOT EXISTS update_job_diagnostics(job INTEGER PRIMARY KEY,stage TEXT NOT NULL,error_code TEXT NOT NULL,rollback TEXT NOT NULL,updated REAL NOT NULL);'''


def reset_job(c,job):
    # SQLite can reuse a deleted job ID; never inherit another episode's history.
    for table in ('update_job_steps','update_job_diagnostics','update_job_context','update_job_events'):
        c.execute('DELETE FROM '+table+' WHERE job=?',(job,))


def record(c,job,data,now,server=False):
    stage=data.get('stage')
    if not isinstance(stage,str) or stage not in STAGES or (stage=='confirmed' and not server):stage=''
    phase=data.get('stage_state')
    if phase not in ('running','completed','failed'):phase='running'
    if data.get('status')=='failed':phase='failed'
    code=data.get('error_code')
    if not isinstance(code,str) or code not in (*STAGES,*PREPARATION_CODES,'helper_missing','helper_launch','helper_startup'):code=''
    rollback=data.get('rollback')
    if not isinstance(rollback,str) or rollback not in ROLLBACK:rollback='unknown'
    if stage:
        c.execute('''INSERT INTO update_job_steps VALUES (?,?,?,?) ON CONFLICT(job,stage) DO UPDATE SET phase=excluded.phase,created=excluded.created
            WHERE update_job_steps.phase!=excluded.phase AND NOT (update_job_steps.phase='completed' AND excluded.phase='running')''',(job,stage,phase,now))
    if stage or code or rollback!='unknown':
        c.execute('''INSERT INTO update_job_diagnostics VALUES (?,?,?,?,?) ON CONFLICT(job) DO UPDATE SET
            stage=CASE WHEN excluded.stage='' THEN update_job_diagnostics.stage ELSE excluded.stage END,
            error_code=excluded.error_code,rollback=CASE WHEN excluded.rollback='unknown' THEN update_job_diagnostics.rollback ELSE excluded.rollback END,updated=excluded.updated''',(job,stage,code,rollback,now))
    return STAGES.get(stage,'')+(' — завершено' if phase=='completed' else ' — ошибка' if phase=='failed' else ' — выполняется') if stage else ''


def render(c,job):
    from .dashboard import esc
    from .windows_ui import stamp
    steps={row['stage']:row for row in c.execute('SELECT * FROM update_job_steps WHERE job=?',(job['id'],))}
    diagnostic=c.execute('SELECT * FROM update_job_diagnostics WHERE job=?',(job['id'],)).fetchone()
    result='<div class="update-diagnostics"><h4>Диагностика установки</h4>'
    if not steps:
        result+='<p class="muted">'+('Ожидание принятия задания агентом.' if job['status']=='queued' else 'Этот агент не передал подробные этапы. Ниже показаны доступные сообщения.')+'</p>'
    else:
        result+='<ol class="update-stage-list">'
        for stage,label in STAGES.items():
            if stage=='prepare' and job['package_platform']!='linux-source':continue
            if stage=='wait_exit' and job['package_platform']!='windows-x64':continue
            step=steps.get(stage)
            state=step['phase'] if step else 'unknown'
            text={'running':'Выполняется','completed':'Подтверждено','failed':'Ошибка','unknown':'Не сообщалось'}[state]
            if state=='running' and job['status'] in ('failed','applied','cancelled'):
                state='unknown';text='Завершение этапа не сообщалось'
            result+='<li class="stage-'+state+'"><span>'+esc(label)+'</span><small>'+text+(' · '+esc(stamp(step['created'])) if step else '')+'</small></li>'
        result+='</ol>'
    if diagnostic:
        result+='<p class="muted">Обновлено: '+esc(stamp(diagnostic['updated']))+'</p>'
        if diagnostic['rollback']!='unknown' or job['status']=='failed':result+='<p class="update-rollback">'+esc(ROLLBACK.get(diagnostic['rollback'],ROLLBACK['unknown']))+'</p>'
        if diagnostic['error_code']:result+='<p class="muted">Код диагностики: <code>'+esc(diagnostic['error_code'])+'</code></p>'
    if job['status']=='applied':result+='<p class="text-normal">Новая версия подтверждена входящим отчётом агента.</p>'
    return result+'</div>'
