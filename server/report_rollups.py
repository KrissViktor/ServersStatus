"""Daily report aggregates and exact composition with raw boundary intervals."""
from datetime import datetime
import json
from math import inf, nextafter
import time
import zlib

from .history import MSK, load_history
from .portal_settings import retention_days
from .stability import load, observation_start, rollup_result

DAY = 86400
BUCKET = 300
SCHEMA = """
CREATE TABLE IF NOT EXISTS report_rollups (
    agent TEXT NOT NULL, day INTEGER NOT NULL, built REAL NOT NULL,
    metrics TEXT NOT NULL, coverage TEXT NOT NULL, chart BLOB NOT NULL,
    PRIMARY KEY(agent,day)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS report_rollups_day ON report_rollups(day);
CREATE TABLE IF NOT EXISTS report_rollup_jobs (
    day INTEGER PRIMARY KEY, requested REAL NOT NULL, manual INTEGER NOT NULL DEFAULT 0,
    finished REAL, lease REAL, token TEXT, error TEXT
);
"""


def midnight(value):
    return int((value + 10800) // DAY) * DAY - 10800


def day_text(value):
    return datetime.fromtimestamp(value, MSK).date().isoformat()


def chart_bucket(bucket):
    return ((bucket+BUCKET-1)//BUCKET)*BUCKET if bucket >= BUCKET else bucket


def raw_metrics(c, agent, start, end):
    return dict(c.execute("""
        SELECT COUNT(*) AS n, SUM(json_extract(data,'$.cpu_percent')) AS cpu_sum,
            COUNT(json_extract(data,'$.cpu_percent')) AS cpu_count,
            MAX(json_extract(data,'$.cpu_percent')) AS cpu_max,
            SUM(json_extract(data,'$.memory_percent')) AS ram_sum,
            COUNT(json_extract(data,'$.memory_percent')) AS ram_count,
            MAX(json_extract(data,'$.memory_percent')) AS ram_max
        FROM reports INDEXED BY reports_resource_metrics
        WHERE agent=? AND received>=? AND received<?
    """, (agent,start,end)).fetchone())


def sum_metrics(rows):
    result = {'n': sum(row['n'] for row in rows)}
    for metric in ('cpu','ram'):
        total = sum(row[metric+'_sum'] or 0 for row in rows)
        count = sum(row[metric+'_count'] for row in rows)
        result[metric+'_sum'] = total
        result[metric+'_count'] = count
        result[metric] = total/count if count else None
        result[metric+'_max'] = max((row[metric+'_max'] for row in rows if row[metric+'_max'] is not None), default=None)
    return result


def build(c, agent, day):
    end = day+DAY
    chart = [dict(point) for point in load_history(c,agent,day,nextafter(end,-inf),BUCKET,totals=True)]
    metrics = sum_metrics([{**point,'n':point['samples'],'cpu_max':point['cpu_peak'],'ram_max':point['ram_peak']} for point in chart])
    coverage = load(c,agent,day,end)
    metrics_json,coverage_json,chart_json = (json.dumps(data,separators=(',',':')) for data in (metrics,coverage,chart))
    return metrics_json,coverage_json,zlib.compress(chart_json.encode(),level=3)


def spans(c, agent, start, end, column):
    """Yield alternating raw ranges and whole days with a published result."""
    if column not in ('metrics','coverage','chart'):
        raise ValueError('Unknown report aggregate')
    first = midnight(start)
    if first < start:
        first += DAY
    last = midnight(end)-DAY
    if first <= last:
        # A day straddling the rolling raw-data retention boundary may have
        # changed during cleanup. Recalculate that partial day on demand.
        cutoff = time.time()-retention_days(c)*DAY
        rows = c.execute(f'SELECT day,{column} FROM report_rollups WHERE agent=? AND day BETWEEN ? AND ? AND day>=? ORDER BY day',
                         (agent,first,last,cutoff))
        for day,data in rows:
            if start < day:
                yield start,day,None
            yield day,day+DAY,json.loads(zlib.decompress(data) if column == 'chart' else data)
            start = day+DAY
    if start < end:
        yield start,end,None


def metrics(c, agent, start, end):
    rows = [raw_metrics(c,agent,left,right) if cached is None else cached
            for left,right,cached in spans(c,agent,start,end,'metrics')]
    return sum_metrics(rows)


def availability(c, agent, start, end, details=True):
    boundary = nextafter(end,inf)
    full_end = boundary if midnight(boundary) == boundary else end
    parts = list(spans(c,agent,start,full_end,'coverage'))
    if not any(cached is not None for _,_,cached in parts):
        return load(c,agent,start,end,details=details)
    observed,_ = observation_start(c,agent,start,end)
    if observed is None:
        return {**rollup_result(None,end,[],[]),'start':start}
    segments, reboots = [], []
    for left,right,cached in parts:
        if right < observed:
            continue
        left,right = max(left,observed),min(right,end)
        data = cached if cached is not None else load(c,agent,left,right,details=details)
        for a,b in data['segments']:
            a,b = max(a,left),min(b,right)
            if b <= a:
                continue
            if segments and a <= segments[-1][1]:
                segments[-1][1] = max(b,segments[-1][1])
            else:
                segments.append([a,b])
        if details:
            reboots.extend(item for item in data['reboots']
                           if left <= item['detected'] and (item['detected'] < right or right == end))
    return rollup_result(observed,end,segments,reboots)


def merge_points(points, bucket, memory_sizes):
    output = []
    previous = None
    for point in points:
        key = int(point['first']/bucket)
        gap = bool(point['has_gap'] or (previous is not None and point['first']-previous > 180))
        previous = point['last']
        if not output or output[-1]['bucket'] != key:
            output.append({**point,'bucket':key,'has_gap':int(gap)})
            continue
        row = output[-1]
        row['last'] = point['last']
        row['has_gap'] |= int(gap)
        for field in ('samples','timestamp_sum','cpu_count','ram_count','ram_size_samples','ram_total_bytes_count'):
            row[field] += point[field]
        for field in ('cpu_sum','ram_sum','ram_used_bytes_sum','ram_total_bytes_sum'):
            row[field] = (row[field] or 0)+(point[field] or 0)
        for field in ('cpu_min','ram_min','cpu_peak','ram_peak','ram_used_peak_bytes'):
            values = [value for value in (row[field],point[field]) if value is not None]
            if values:
                row[field] = (min if field.endswith('_min') else max)(values)
    for row in output:
        row['timestamp'] = row.pop('timestamp_sum')/row['samples']
        for metric,count_key in [('cpu','cpu_count'),('ram','ram_count'),('ram_used_bytes','ram_size_samples'),('ram_total_bytes','ram_total_bytes_count')]:
            count = row[count_key]
            total = row.pop(metric+'_sum')
            row[metric] = total/count if count else None
        for field in ('cpu_count','ram_count','ram_total_bytes_count'):
            del row[field]
        if not memory_sizes:
            for field in ('ram_used_bytes','ram_total_bytes','ram_used_peak_bytes'):
                row[field] = None
            row['ram_size_samples'] = 0
    return output


def history_points(c, agent, start, end, bucket, *, memory_sizes=True):
    if bucket % BUCKET:
        return load_history(c,agent,start,end,bucket,memory_sizes=memory_sizes)
    # Raw history has an inclusive right bound. Use half-open pieces internally
    # so a report exactly at midnight is read once.
    parts = list(spans(c,agent,start,nextafter(end,inf),'chart'))
    if not any(cached is not None for _,_,cached in parts):
        return load_history(c,agent,start,end,bucket,memory_sizes=memory_sizes)
    points = []
    for left,right,cached in parts:
        if cached is not None:
            points.extend(cached)
        else:
            points.extend(dict(point) for point in load_history(c,agent,left,nextafter(right,-inf),bucket,memory_sizes=memory_sizes,totals=True))
    return merge_points(points,bucket,memory_sizes)
