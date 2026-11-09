"""Small Windows Task Manager style graphs for current CPU and RAM."""
from datetime import datetime,timedelta,timezone
import html
import math

WINDOW=300


def graph(points,field,now,snapshot=False,core=None):
    start=now-WINDOW
    end=now+WINDOW if snapshot else now
    width=end-start
    samples=[];missing=[]
    ram_sizes={p.get('timestamp'):p for p in points}
    for point in points:
        timestamp=point.get('timestamp')
        value=point.get(field)
        if not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp):continue
        if not isinstance(value,(int,float)):
            missing.append(timestamp);continue
        if not math.isfinite(timestamp) or not math.isfinite(value) or not start<=timestamp<=end:
            continue
        samples.append((timestamp,min(100,max(0,value))))
    samples.sort()
    intervals=[b[0]-a[0] for a,b in zip(samples,samples[1:]) if b[0]>a[0]]
    max_gap=min(180,max(35,min(intervals,default=10)*3))
    x=lambda timestamp:(timestamp-start)/width*320
    y=lambda value:98-value*.96
    label=f'Логический процессор {core}' if core is not None else 'Загрузка процессора' if field=='cpu' else 'Использование памяти'
    content='<svg class="task-graph" viewBox="0 0 320 100" preserveAspectRatio="none" role="img" aria-label="'+label+(' за 5 минут до и после снимка' if snapshot else ' за последние 5 минут')+'">'
    for position in (0,40,80,120,160,200,240,280,320):
        content+=f'<line class="task-grid" x1="{position}" x2="{position}" y1="0" y2="100"/>'
    for position in (2,26,50,74,98):
        content+=f'<line class="task-grid" x1="0" x2="320" y1="{position}" y2="{position}"/>'
    segments=[]
    for sample in samples:
        if not segments or sample[0]-segments[-1][-1][0]>max_gap or any(segments[-1][-1][0]<gap<sample[0] for gap in missing):
            segments.append([])
        segments[-1].append(sample)
    for segment in segments:
        line='M '+' L '.join(f'{x(t):.2f},{y(value):.2f}' for t,value in segment)
        if len(segment)>1:
            fill=f'M {x(segment[0][0]):.2f},100 L '+' L '.join(f'{x(t):.2f},{y(value):.2f}' for t,value in segment)+f' L {x(segment[-1][0]):.2f},100 Z'
            content+=f'<path class="task-fill" d="{fill}"/>'
        content+=f'<path class="task-line" d="{line}"/>'
    if snapshot:
        stamp=datetime.fromtimestamp(now,timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
        content+='<line class="task-snapshot-marker" x1="160" x2="160" y1="0" y2="100"><title>Момент снимка: '+html.escape(stamp)+'</title></line>'
    for timestamp,value in samples:
        stamp=datetime.fromtimestamp(timestamp,timezone(timedelta(hours=3))).strftime('%H:%M:%S МСК')
        tooltip=f'{stamp} · {value:.1f}%'
        if field=='ram':
            from .memory import memory_tooltip
            tooltip+=' · '+memory_tooltip(ram_sizes[timestamp])
        marker=' data-snapshot-point="true"' if snapshot and timestamp==now else ''
        report_id=ram_sizes[timestamp].get('report_id')
        if type(report_id) is int:marker+=f' data-detail-report="{report_id}"'
        metric='cpu_core' if core is not None else field
        title=f'Логический процессор {core}' if core is not None else 'Процессор' if field=='cpu' else 'Оперативная память'
        if core is not None:marker+=f' data-detail-name="{core}"'
        content+=f'<circle{marker} data-detail-metric="{metric}" data-detail-first="{timestamp}" data-detail-last="{timestamp}" data-detail-count="30" data-detail-title="{title}" tabindex="0" role="button" aria-label="Открыть исходные отчёты" class="task-point" cx="{x(timestamp):.2f}" cy="{y(value):.2f}" r="2"><title>{html.escape(tooltip)}</title></circle>'
    content+='</svg>'
    if not samples:
        content+='<span class="task-empty">'+('Нет измерений вокруг снимка' if snapshot else 'Нет измерений за последние 5 минут')+'</span>'
    return content
