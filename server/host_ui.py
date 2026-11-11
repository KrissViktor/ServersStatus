import json
import time
from fastapi import Request
from fastapi.responses import HTMLResponse,RedirectResponse
from .dashboard import page,esc


def register(app,db,authenticated):
    @app.get('/host',response_class=HTMLResponse)
    def host(request:Request):
        if not authenticated(request):return RedirectResponse('/',303)
        content='<header class="topbar"><a href="/">← Все серверы</a><a class="nav-link" href="/portal-health">Контроль портала →</a></header><h1>Raspberry Pi — портал</h1>'
        with db() as c:
            row=c.execute('SELECT r.data,r.received,l.agent FROM local_host l LEFT JOIN current_reports r ON r.agent=l.agent WHERE l.id=1').fetchone()
        if not row or not row['data']:
            content+='<section class="server"><h2>Мониторинг хоста ещё не подключён</h2><p class="muted">Данных о ресурсах машины портала пока нет.</p><details class="service-details"><summary>Как подключить мониторинг</summary><p>Установите и запустите serversstatus-host-monitor.service по инструкции deploy/UPDATES.md.</p></details></section>'
        else:
            data=json.loads(row['data']);portal=data.get('portal') or {};temp=portal.get('temperature_c')
            content+=f'<section class="server"><p>{"🟢 Онлайн" if time.time()-row["received"]<120 else "🔴 Нет свежих данных"} · обновлено {int(max(0,time.time()-row["received"]))} с назад</p><p>Температура процессора: {esc(str(round(temp,1))+" °C" if temp is not None else "датчик недоступен")}</p><p>База данных с журналом SQLite: {portal.get("database_bytes",0)/1024**2:.1f} Мб</p><p>CPU: {data["cpu_percent"]:.1f}% · ОЗУ: {data["memory_percent"]:.1f}%</p><a href="/servers/{esc(row["agent"])}">Диски, службы и состояние →</a> · <a href="/history/{esc(row["agent"])}">Графики CPU, ОЗУ, сети и дисков →</a></section>'
            content+='<p class="muted">Новые данные каждые 10 секунд. Raspberry Pi также отображается в общем списке и уведомлениях.</p>'
            content+='''<script>setInterval(async()=>{try{const r=await fetch('/host');if(!r.ok)return;const d=new DOMParser().parseFromString(await r.text(),'text/html');const a=document.querySelector('section.server'),b=d.querySelector('section.server');if(a&&b)a.replaceWith(b)}catch(e){}},10000)</script>'''
        return HTMLResponse(page(content))
