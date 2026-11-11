from pathlib import Path
from urllib.parse import quote
from .dashboard import esc,page
from .update_versions import choices,stamp
import json
import time

SCRIPT=Path(__file__).with_name('updates.js').read_text()
LABELS={'queued':('В очереди','neutral'),'running':('Установка','warning'),'applied':('Установлено','normal'),'failed':('Ошибка','danger'),'cancelled':('Отменено','neutral')}


def render(c,csrf,result=None):
    packages=c.execute('SELECT p.*,d.built_at,d.commit_at FROM update_packages p LEFT JOIN update_package_dates d ON d.package=p.id').fetchall()
    content='<header class="topbar"><a href="/">← Все серверы</a></header><h1>Обновление агентов</h1><p class="update-safety">Обновление перезапускает только службу агента. Перезагрузка ОС и установка драйверов запрещены.</p><p class="muted">Текущая версия, последняя новая сборка (New) и ближайшая предыдущая (Older). Даты указаны по Москве.</p>'
    if result and result.get('bulk')=='done':
        from .updates import BULK_LABELS
        summary=[]
        for key,label in BULK_LABELS.items():
            try:count=max(0,min(1000000,int(result.get(key,0))))
            except (ValueError,TypeError):count=0
            if count or key=='queued':summary.append(f'<li>{esc(label)}: <b>{count}</b></li>')
        content+='<section class="server" role="status"><h2>Массовое обновление</h2><ul>'+''.join(summary)+'</ul><p class="muted">Результаты установки появятся в истории каждого агента.</p></section>'
    content+=f'<section class="server"><h2>Отмена заданий</h2><p>Можно отменить задания, которые агент ещё не принял. Уже принятую установку нельзя безопасно остановить из панели.</p><form method="post" action="/updates/all/cancel"><input type="hidden" name="csrf" value="{esc(csrf)}"><button>Отменить все ожидающие обновления</button></form></section>'
    if result and result.get('cancelled') is not None:
        try:count=max(0,int(result['cancelled']))
        except (ValueError,TypeError):count=0
        content+=f'<p role="status">Отменено ожидающих заданий: {count}. Уже принятые агентами задания продолжаются.</p>'
    content+=f'<section class="server"><h2>Обновить все агенты</h2><p>Проверить GitHub и отправить каждому доступному агенту последнюю новую версию для его платформы. Raspberry Pi обновляется вместе с порталом. Агенты без связи и с незавершёнными задачами будут пропущены.</p><form data-bulk-update method="post" action="/updates/all/latest"><input type="hidden" name="csrf" value="{esc(csrf)}"><label class="check"><input type="checkbox" name="confirm" value="yes" required> Разрешаю короткий перезапуск служб агентов</label><button>Обновить все агенты</button><p class="muted" data-bulk-progress hidden role="status">Проверяем GitHub и создаём задачи…</p></form></section>'
    content+=f'<section class="server"><h2>Доступные версии</h2><p>Нажмите, чтобы получить новые сборки из GitHub.</p><form method="post" action="/updates/github/check"><input type="hidden" name="csrf" value="{esc(csrf)}"><button>Проверить GitHub</button></form></section><div data-updates-root>'
    from .updates import pending
    for row in c.execute('SELECT a.id,r.data,r.received,p.display_name FROM agents a LEFT JOIN current_reports r ON r.agent=a.id LEFT JOIN agent_profiles p ON p.agent=a.id ORDER BY a.id').fetchall():
        agent=row['id'];data=json.loads(row['data'] or '{}');platform=data.get('agent_platform');current=data.get('agent_version') or 'неизвестна'
        active=pending(c,agent);options,current_date=choices(packages,platform,current)
        online=row['received'] is not None and time.time()-row['received']<=120
        content+=f'<section class="server" data-update-card="{esc(agent)}"><div data-update-summary><header class="server-head"><div><h2>{esc(row["display_name"] or agent)}</h2><p class="muted">{esc(agent)} · {esc(platform or "платформа неизвестна")}</p></div>'
        if active:content+='<span class="badge warning">Обновление выполняется</span>'
        elif not online:content+='<span class="badge danger">Нет свежего отчёта</span>'
        content+=f'</header><p><b>Текущая версия:</b> <code data-running-version="{esc(current)}">{esc(current)}</code> <span class="muted">· {stamp(current_date)} МСК</span></p>'
        if active:
            from .update_diagnostics import STAGES
            diagnostic=c.execute('SELECT * FROM update_job_diagnostics WHERE job=?',(active['id'],)).fetchone()
            stage=STAGES.get(diagnostic['stage'],'Ожидание первого сообщения об этапе') if diagnostic else 'Ожидание принятия задания агентом'
            content+='<p class="update-current-stage">Текущий этап: <b>'+esc(stage)+'</b></p>'
        else:
            last=c.execute('SELECT status,message FROM agent_update_jobs WHERE agent=? ORDER BY id DESC LIMIT 1',(agent,)).fetchone()
            if last and last['status']=='failed':content+='<p class="notice">Последнее обновление: '+esc(last['message'])+'</p>'
        content+='</div>'
        if platform=='portal':content+='<p>Локальный монитор обновляется вместе с кодом портала.</p>'
        elif 'remote_update_v1' not in data.get('features',[]):content+='<p class="muted">Обновите агент вручную для поддержки установки через панель.</p>'
        else:
            rendered=''.join(f'<option value="{p["id"]}">{esc(p["version"])} ({p["label"]}) · {stamp(p["display_date"])} МСК</option>' for p in options)
            disabled='disabled' if active or not online or not options else ''
            content+=f'<form data-update-form method="post" action="/updates/{esc(quote(agent,safe=""))}"><input type="hidden" name="csrf" value="{esc(csrf)}"><label>Перейти на версию<select name="package" required {"disabled" if not options else ""}>{rendered or "<option>Подходящих версий нет</option>"}</select></label><label class="check"><input type="checkbox" required> Разрешаю короткий перезапуск службы агента</label><button {disabled}>Установить выбранную версию</button></form>'
        cancellation=''
        if active:
            state=c.execute('SELECT status FROM agent_update_jobs WHERE id=?',(active['id'],)).fetchone()['status']
            if state=='queued':
                cancellation=f'<form method="post" action="/updates/{esc(quote(agent,safe=""))}/{active["id"]}/cancel"><input type="hidden" name="csrf" value="{esc(csrf)}"><button>Отменить задание #{active["id"]}</button></form>'
            else:cancellation='<p class="muted">Агент уже принял задание. Безопасная отмена установки недоступна.</p>'
        content+='<div data-update-cancel>'+cancellation+'</div>'
        content+='<div data-update-history tabindex="0" aria-label="История обновлений: прокручиваемый список" style="max-height:300px;overflow:hidden;overscroll-behavior:auto;border:1px solid var(--line);border-radius:12px;padding:0 14px;margin-top:18px">'
        jobs=c.execute('SELECT j.*,p.version,p.platform AS package_platform,x.from_version FROM agent_update_jobs j JOIN update_packages p ON p.id=j.package LEFT JOIN update_job_context x ON x.job=j.id WHERE j.agent=? ORDER BY j.id DESC LIMIT 10',(agent,)).fetchall()
        if jobs:
            content+='<h3 class="update-history-heading">История обновлений</h3>'
            for index,job in enumerate(jobs):
                label,color=LABELS.get(job['status'],(job['status'],'neutral'))
                content+=f'<details data-update-job="{job["id"]}"><summary style="padding:12px 0"><span class="badge {color}">{esc(label)}</span> <b>{esc(job["version"])}</b> · {stamp(job["created"])} МСК · #{job["id"]}</summary>'
                if job['from_version']:content+=f'<p><code>{esc(job["from_version"])}</code> → <code>{esc(job["version"])}</code></p>'
                from .update_diagnostics import render as diagnostics
                content+=diagnostics(c,job)
                content+='<p>'+esc(job['message'])+'</p><div class="table-scroll"><table class="metric-table"><thead><tr><th>Время (МСК)</th><th>Этап</th><th>Результат</th></tr></thead><tbody>'
                events=c.execute('SELECT created,status,message FROM update_job_events WHERE job=? ORDER BY id',(job['id'],)).fetchall()
                if not events:
                    events=[{'created':job['created'],'status':'queued','message':'Задание создано'},{'created':job['updated'],'status':job['status'],'message':job['message']}]
                for step in events:
                    content+=f'<tr><td>{stamp(step["created"])}</td><td>{esc(LABELS.get(step["status"],(step["status"],""))[0])}</td><td>{esc(step["message"])}</td></tr>'
                content+='</tbody></table></div></details>'
        else:content+='<p class="muted">История обновлений пока пуста.</p>'
        content+='</div></section>'
    return page(content+'</div><script>'+SCRIPT+'</script>')
