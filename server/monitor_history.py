"""Compact check history and observed HTTP failures."""
import json
from math import ceil
from urllib.parse import urlencode

from .dashboard import duration, esc
from .ui_icons import icon
from .windows_ui import stamp

BUCKETS=48
DANGER_SQL="""(json_extract(result,'$.http') IN ('error','unexpected')
    OR json_extract(result,'$.tls')='invalid' OR json_extract(result,'$.rkn')='listed')"""


def tone(result):
    if result.get('http') in ('error','unexpected') or result.get('tls')=='invalid' or result.get('rkn')=='listed':
        return 'danger'
    if result.get('tls')=='expiring' or result.get('rkn') in ('stale','unconfigured','unavailable'):
        return 'warning'
    return 'normal' if result.get('http')=='ok' else 'neutral'


def outages(rows, interval, selected_start, selected_end, now):
    """Report observed outages, breaking the sequence when monitoring has a gap."""
    first=last=None
    count=0
    for at, state, stored_interval in rows:
        gap=max(120,2.5*(stored_interval or interval))
        if first is not None and (state=='ok' or at-last>gap):
            if first<=selected_end and last>=selected_start:
                yield first,last,count,at if state=='ok' and at-last<=gap else None,False
            first=last=None
            count=0
        if state in ('error','unexpected'):
            if first is None:
                first=at
            last=at
            count+=1
    if first is not None and first<=selected_end and last>=selected_start:
        yield first,last,count,None,now-last<=max(120,2.5*(stored_interval or interval))


def timeline(c, monitor, start, end, selected, now):
    width=max(1,ceil((end-start+1)/BUCKETS))
    count=max(1,ceil((end-start+1)/width))
    rows=c.execute(f"""SELECT CAST((at-?)/? AS INTEGER) AS bucket, count(*) AS checks,
        sum(CASE WHEN {DANGER_SQL} THEN 1 ELSE 0 END),
        sum(CASE WHEN json_extract(result,'$.tls')='expiring'
          OR json_extract(result,'$.rkn') IN ('stale','unconfigured','unavailable') THEN 1 ELSE 0 END)
        FROM site_monitor_runs WHERE monitor=? AND at BETWEEN ? AND ? GROUP BY bucket""",
        (start,width,monitor['id'],start,end))
    buckets={index:(checks,errors,warnings) for index,checks,errors,warnings in rows}
    if selected not in buckets:
        return start,width,count,buckets,[],[]
    left=start+selected*width
    right=min(end,start+(selected+1)*width)
    interval_end='at<=?' if right==end else 'at<?'
    samples=c.execute(f"""SELECT at,result FROM site_monitor_runs
        WHERE monitor=? AND at>=? AND {interval_end}
        ORDER BY CASE WHEN {DANGER_SQL} THEN 0 ELSE 1 END,at DESC,id DESC LIMIT 40""",
        (monitor['id'],left,right)).fetchall()
    failures=[]
    if buckets[selected][1]:
        rows=c.execute("""SELECT at,json_extract(result,'$.http'),json_extract(result,'$.interval')
            FROM site_monitor_runs WHERE monitor=? AND at BETWEEN ? AND ? ORDER BY at,id""",
            (monitor['id'],start,end))
        failures=list(outages(rows,monitor['interval'],left,right,now))[-20:][::-1]
    return start,width,count,buckets,samples,failures


def history_panel(monitor, history, selected, end, filters, controls, render_result):
    start,width,count,buckets,samples,failures=history
    identifier=monitor['id']
    labels={'normal':'В норме','danger':'Проблемы','warning':'Предупреждения','neutral':'Нет проверок'}
    result='<div class="monitor-history" id="monitor-history"><h3>'+icon('timeline')+' История проверок</h3>'+controls
    if not buckets:
        return result+'<p class="muted">За этот период проверок нет.</p></div>'
    result+='<div class="monitor-timeline">'
    for index in range(count):
        checks,errors,warnings=buckets.get(index,(0,0,0))
        color='danger' if errors else 'warning' if warnings else 'normal' if checks else 'neutral'
        left=start+index*width
        right=min(end,left+width)
        label=esc(f'{stamp(left)} — {stamp(right)} · {labels[color]}')
        url=esc(urlencode({'monitor':identifier,**filters,'slot':index,'anchor':int(end)}))
        current=' aria-current="true"' if selected==index else ''
        result+=f'<a class="{color}" href="/monitors?{url}#monitor-history" title="{label}" aria-label="{label}"{current}></a>'
    result+='</div><div class="monitor-range muted"><span>'+esc(stamp(start))+'</span><span>'+esc(stamp(end))+'</span></div>'
    result+='<div class="monitor-legend">'+''.join(f'<span class="{color}"><i></i>{label}</span>' for color,label in labels.items())+'</div>'
    if selected<0:
        return result+'<p class="muted">Выберите участок шкалы, чтобы увидеть проверки и длительность сбоев.</p></div>'
    if not samples:
        return result+'<p class="muted">На выбранном участке проверок нет.</p></div>'
    result+='<div class="monitor-events">'
    if failures:
        result+='<p class="muted">Начало и восстановление определяются по проверкам внутри выбранного периода.</p>'
    for first,last,checks,recovered,ongoing in failures:
        title='HTTP снова отвечает' if recovered else 'Сбой продолжается' if ongoing else 'Восстановление не подтверждено'
        span=(recovered or last)-first
        result+=f'<article class="monitor-outage"><strong>{icon("incident")} {title}</strong>'
        result+=f'<p><span>Первый сбой</span> <time>{esc(stamp(first))}</time></p>'
        result+=f'<p><span>{"Восстановление" if recovered else "Последний сбой"}</span> <time>{esc(stamp(recovered or last))}</time></p>'
        if span>0:
            result+=f'<p><span>Длительность по замерам</span> <b>{esc(duration(span))}</b></p>'
        else:
            result+='<p class="muted">Длительность пока неизвестна.</p>'
        result+='</article>'
    result+='<h4>Проверки участка</h4>'
    for at,raw in samples:
        check=json.loads(raw)
        color=tone(check)
        result+=f'<details class="monitor-run"><summary><span class="badge {color}">{labels[color]}</span> {esc(stamp(at))}</summary>{render_result(check)}</details>'
    return result+'</div></div>'
