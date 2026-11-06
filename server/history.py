"""Bounded history aggregation and dependency-free SVG charts."""
from datetime import datetime, timezone, timedelta
from urllib.parse import quote, urlencode

from .dashboard import esc, page

PERIODS = {'1h': ('Час', 3600, 60), '6h': ('6 часов', 21600, 60),
           '24h': ('Сутки', 86400, 300), '7d': ('Неделя', 604800, 1800),
           '30d': ('30 дней', 2592000, 3600)}


def load_history(connection, agent_id, start, end, bucket):
    # Filter by indexed agent/time before extracting metrics. Grouping returns
    # at most one point per time bucket, independent of reporting frequency.
    return connection.execute('''
        WITH samples AS (
            SELECT received,
                   json_extract(data, '$.cpu_percent') AS cpu,
                   json_extract(data, '$.memory_percent') AS ram,
                   received - LAG(received) OVER (ORDER BY received) AS gap
            FROM reports WHERE agent=? AND received>=? AND received<=?
        )
        SELECT CAST(received / ? AS INTEGER) AS bucket,
               AVG(received) AS timestamp, MIN(received) AS first,
               MAX(received) AS last, COUNT(*) AS samples,
               AVG(cpu) AS cpu, MAX(cpu) AS cpu_peak,
               AVG(ram) AS ram, MAX(ram) AS ram_peak,
               MAX(CASE WHEN gap>180 THEN 1 ELSE 0 END) AS has_gap
        FROM samples GROUP BY bucket ORDER BY bucket
    ''', (agent_id, start, end, bucket)).fetchall()


def stamp(timestamp):
    return datetime.fromtimestamp(timestamp, timezone(timedelta(hours=3))).strftime('%d.%m %H:%M МСК')


def chart(points, metric, title, start, end, color):
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
        drawing += f'<circle class="chart-point" cx="{px:.2f}" cy="{py:.2f}" r="3" fill="{color}"><title>{esc(tooltip)}</title></circle>'
        previous = point
    return f'<section class="server"><h2>{title}</h2><div class="chart-scroll"><svg class="history-chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}: от 0 до 100 процентов"><title>{esc(title)}</title>{drawing}</svg></div></section>'


def history_page(agent_id, points, period, start, end, extra_html="", selectors=None):
    _, _, bucket = PERIODS[period]
    url = '/history/' + quote(agent_id, safe='')
    links = ''.join(f'<a class="period {"selected" if key == period else ""}" href="{esc(url)}?{esc(urlencode({"period": key, **(selectors or {})}))}">{label}</a>' for key, (label, _, _) in PERIODS.items())
    content = '<header class="topbar"><a class="brand" href="/">S<span>●</span> <b>ServersStatus</b></a><a class="nav-link" href="/">← Обзор серверов</a></header>'
    content += f'<div class="heading"><div><p class="eyebrow">ИСТОРИЯ НАГРУЗКИ</p><h1>{esc(agent_id)}</h1><p class="muted">{stamp(start)} — {stamp(end)} · обновление каждые 30 с</p></div></div><nav class="periods" aria-label="Период истории">{links}</nav>'
    if not points:
        content += '<div class="empty">За выбранный период отчётов нет. История появится после получения данных агента.</div>'
    else:
        total = sum(p['samples'] for p in points)
        content += '<div class="stats">' + ''.join(f'<div class="stat"><span>{label}</span><strong>{value}</strong></div>' for label, value in [
            ('Среднее CPU', f'{sum(p["cpu"] * p["samples"] for p in points)/total:.1f}%'),
            ('Пик CPU', f'{max(p["cpu_peak"] for p in points):.1f}%'),
            ('Среднее RAM', f'{sum(p["ram"] * p["samples"] for p in points)/total:.1f}%'),
            ('Пик RAM', f'{max(p["ram_peak"] for p in points):.1f}%')]) + '</div>'
        content += f'<p class="muted history-note">Отчётов: {total} · Точки — средние за {bucket // 60} мин. Наведите на точку, чтобы увидеть пик и время. Разрывы означают отсутствие отчётов более 3 минут; интервалы с пропусками показаны отдельными точками. Время — московское (МСК).</p>'
        content += chart(points, 'cpu', 'Процессор · CPU', start, end, '#4adeab')
        content += chart(points, 'ram', 'Оперативная память · RAM', start, end, '#83c4ff')
    content += extra_html
    return page('<div id="history-content" data-refresh>' + content + '</div><footer>История хранится 30 дней. Значения усредняются только по полученным отчётам, пропуски не считаются нулевой нагрузкой.</footer>', refresh=True)
