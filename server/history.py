"""Bounded history aggregation and dependency-free SVG charts."""
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlencode
from pathlib import Path

IO_SCRIPT=Path(__file__).with_name("io_history.js").read_text(encoding="utf-8")

from .dashboard import esc, page, size
from .memory import RAM_USED_SQL, RAM_TOTAL_SQL, memory_tooltip

PERIODS = {'15m': ('15 минут',900,10), '1h': ('Час', 3600, 60), '6h': ('6 часов', 21600, 60),
           '24h': ('Сутки', 86400, 300), '7d': ('Неделя', 604800, 1800),
           '30d': ('30 дней', 2592000, 3600)}


def load_history(connection, agent_id, start, end, bucket):
    # Filter by indexed agent/time before extracting metrics. Grouping returns
    # at most one point per time bucket, independent of reporting frequency.
    return connection.execute(f'''
        WITH samples AS (
            SELECT received,
                   json_extract(data, '$.cpu_percent') AS cpu,
                   json_extract(data, '$.memory_percent') AS ram,
                   {RAM_USED_SQL} AS ram_used_bytes, {RAM_TOTAL_SQL} AS ram_total_bytes,
                   received - LAG(received) OVER (ORDER BY received) AS gap
            FROM reports INDEXED BY reports_resource_metrics WHERE agent=? AND received>=? AND received<=?
        )
        SELECT CAST(received / ? AS INTEGER) AS bucket,
               AVG(received) AS timestamp, MIN(received) AS first,
               MAX(received) AS last, COUNT(*) AS samples,
               AVG(cpu) AS cpu, MIN(cpu) AS cpu_min, MAX(cpu) AS cpu_peak,
               AVG(ram) AS ram, MIN(ram) AS ram_min, MAX(ram) AS ram_peak,
               AVG(ram_used_bytes) AS ram_used_bytes, MAX(ram_used_bytes) AS ram_used_peak_bytes,
               AVG(ram_total_bytes) AS ram_total_bytes, COUNT(ram_used_bytes) AS ram_size_samples,
               MAX(CASE WHEN gap>180 THEN 1 ELSE 0 END) AS has_gap
        FROM samples GROUP BY bucket ORDER BY bucket
    ''', (agent_id, start, end, bucket)).fetchall()


def stamp(timestamp):
    return datetime.fromtimestamp(timestamp, timezone(timedelta(hours=3))).strftime('%d.%m %H:%M МСК')


def chart(points, metric, title, start, end, color):
    from .resource_charts import metadata,CPU,RAM
    color=CPU if metric=='cpu' else RAM
    resource_attrs=metadata(points,metric,start,end)
    width, height, left, top, bottom = 1000, 240, 48, 14, 202
    plot_width = width - left - 18
    plot_height = bottom - top
    def x(t):
        return left + (t - start) / (end - start) * plot_width
    def y(v):
        return bottom - min(100, max(0, v)) / 100 * plot_height
    drawing = ''
    for percent in (0, 25, 50, 75, 100):
        drawing += f'<line class="chart-grid" x1="{left}" y1="{y(percent)}" x2="982" y2="{y(percent)}"/><text class="chart-label" x="38" y="{y(percent)+4}" text-anchor="end">{percent}%</text>'
    for fraction in (0, .25, .5, .75, 1):
        t = start + (end - start) * fraction
        anchor = 'start' if fraction == 0 else 'end' if fraction == 1 else 'middle'
        drawing += f'<text class="chart-label" x="{x(t)}" y="228" text-anchor="{anchor}">{stamp(t)}</text>'
    previous = None
    for point in points:
        px, py = x(point['timestamp']), y(point[metric])
        if previous is not None and not point['has_gap'] and not previous['has_gap'] and point['first'] - previous['last'] <= 180:
            drawing += f'<line x1="{x(previous["timestamp"]):.2f}" y1="{y(previous[metric]):.2f}" x2="{px:.2f}" y2="{py:.2f}" stroke="{color}" stroke-width="2"/>'
        tooltip = f'{stamp(point["first"])} — {stamp(point["last"])} · среднее {point[metric]:.1f}% · пик {point[metric + "_peak"]:.1f}% · отчётов: {point["samples"]}'
        if metric=='ram':
            tooltip+=' · средний объём: '+memory_tooltip(point)
            if dict(point).get('ram_used_peak_bytes') is not None:
                from .dashboard import size
                tooltip+=' · пик объёма: '+size(point['ram_used_peak_bytes'])
                tooltip+=' · отчётов с объёмом: '+str(point['ram_size_samples'])
        attributes=f'data-detail-metric="{esc(metric)}" data-detail-first="{point["first"]}" data-detail-last="{point["last"]}" data-detail-count="{point["samples"]}" data-detail-title="{esc(title)}" tabindex="0" role="button" aria-label="Открыть исходные отчёты: {esc(tooltip)}"'
        drawing += f'<circle {attributes} class="chart-point" cx="{px:.2f}" cy="{py:.2f}" r="3" fill="{color}"><title>{esc(tooltip)}</title></circle>'
        previous = point
    return f'<section class="server"><h2>{title}</h2><div class="chart-scroll"><svg class="history-chart"{resource_attrs} data-chart-start="{start}" data-chart-end="{end}" data-chart-left="48" data-chart-right="982" data-chart-top="14" data-chart-bottom="202" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}: от 0 до 100 процентов"><title>{esc(title)}</title>{drawing}</svg></div></section>'


def history_page(agent_id, points, period, start, end, extra_html="", selectors=None,extremes=None,retention_days=186, display_name=None):
    _, _, bucket = PERIODS[period]
    bucket_label=str(bucket)+' с' if bucket<60 else str(bucket//60)+' мин'
    url = '/history/' + quote(agent_id, safe='')
    links = ''.join(f'<a class="period {"selected" if key == period else ""}" href="{esc(url)}?{esc(urlencode({"period": key, **(selectors or {})}))}">{label}</a>' for key, (label, _, _) in PERIODS.items())
    content = '<header class="topbar"><a class="brand" href="/">S<span>●</span> <b>ServersStatus</b></a><a class="nav-link" href="/">← Обзор серверов</a></header>'
    content += f'<div class="heading"><div><p class="eyebrow">ИСТОРИЯ НАГРУЗКИ</p><h1>{esc(display_name or agent_id)}</h1><p class="muted">{stamp(start)} — {stamp(end)} · обновление каждые 30 с</p></div></div><nav class="periods" aria-label="Период истории">{links}</nav>'
    if not points:
        content += '<div class="empty">За выбранный период отчётов нет. История появится после получения данных агента.</div>'
    else:
        total = sum(p['samples'] for p in points)
        size_points=[dict(p) for p in points if dict(p).get('ram_used_bytes') is not None]
        size_count=sum(p.get('ram_size_samples',0) for p in size_points)
        average_size=size(sum(p['ram_used_bytes']*p.get('ram_size_samples',0) for p in size_points)/size_count) if size_count else 'Объём недоступен'
        peak_sizes=[dict(p)['ram_used_peak_bytes'] for p in points if dict(p).get('ram_used_peak_bytes') is not None]
        peak_size=size(max(peak_sizes)) if peak_sizes else 'Объём недоступен'
        extremes=extremes or {}
        def stat(label,value,record=None,metric='cpu'):
            if record:
                attrs=f'data-detail-metric="{metric}" data-detail-first="{record["timestamp"]}" data-detail-last="{record["timestamp"]}" data-detail-count="30" data-detail-report="{record["report_id"]}" data-detail-title="{esc(label)}"'
                return f'<button type="button" class="stat extreme-stat" {attrs}><span>{label}</span><strong>{value}</strong></button>'
            return f'<div class="stat"><span>{label}</span><strong>{value}</strong></div>'
        content+='<div class="stats '+('history-stats' if extremes else '')+'">'
        content+=stat('Среднее CPU',f'{sum(p["cpu"]*p["samples"] for p in points)/total:.1f}%')
        record=extremes.get('cpu_max');content+=stat('Пик CPU',f'{max(p["cpu_peak"] for p in points):.1f}%',record)
        record=extremes.get('cpu_min')
        if record:content+=stat('Минимум CPU',f'{record["value"]:.1f}%',record)
        content+=stat('Среднее RAM',f'{sum(p["ram"]*p["samples"] for p in points)/total:.1f}%<small class="stat-detail" title="Объём по {size_count} отчётам с данными памяти">{average_size}</small>')
        record=extremes.get('ram_max')
        peak_size=size(record['ram_used_bytes']) if record and record.get('ram_used_bytes') is not None else peak_size
        content+=stat('Пик RAM',f'{max(p["ram_peak"] for p in points):.1f}%<small class="stat-detail">{peak_size}</small>',record,'ram')
        record=extremes.get('ram_min')
        if record:content+=stat('Минимум RAM',f'{record["value"]:.1f}%<small class="stat-detail">{size(record.get("ram_used_bytes"))}</small>',record,'ram')
        content+='</div>'
        content += f'<p class="muted history-note">Отчётов: {total} · Точки — средние за {bucket_label}. Наведите на точку, чтобы увидеть пик и время. Нажмите на точку для просмотра исходных отчётов и масштаба до 900 отчётов. Разрывы означают отсутствие отчётов более 3 минут; интервалы с пропусками показаны отдельными точками. Время — московское (МСК).</p>'
        content += chart(points, 'cpu', 'Процессор · CPU', start, end, '#4adeab')
        content += chart(points, 'ram', 'Оперативная память · RAM', start, end, '#83c4ff')
    content += extra_html
    from .drilldown import widget
    return page('<div id="history-content" data-resource-agent="'+esc(agent_id)+'" data-resource-period="'+period+'" data-refresh data-refresh-interval="30000">' + content + '</div><script>'+IO_SCRIPT+'</script>'+widget(agent_id)+'<footer>История хранится '+str(retention_days)+' дней. Значения усредняются только по полученным отчётам, пропуски не считаются нулевой нагрузкой.</footer>', refresh=True)
