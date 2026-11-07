"""Per-interface and per-device historical charts; no double counting of NICs."""
from urllib.parse import quote, urlencode
import math
from .dashboard import esc, size
from .history import stamp

FIELDS = {'network': ('receive_bytes_per_second','send_bytes_per_second'),
          'disk_io': ('read_bytes_per_second','write_bytes_per_second','read_iops','write_iops')}


def names(connection, agent, group, start, end):
    assert group in FIELDS
    return [r[0] for r in connection.execute('''SELECT DISTINCT json_extract(v.value,'$.name')
        FROM reports r, json_each(r.data,?) v WHERE r.agent=? AND r.received BETWEEN ? AND ?
        ORDER BY 1 LIMIT 100''', ('$.'+group,agent,start,end)) if r[0]]


def metric_series(connection,agent,group,name,start,end,bucket):
    """Read JSON once per device group, aggregate every original measurement."""
    fields=FIELDS[group]
    projections=', '.join('json_extract(v.value,?) AS metric'+str(i) for i in range(len(fields)))
    query='SELECT r.received,'+projections+""" FROM reports r,json_each(r.data,?) v
        WHERE r.agent=? AND r.received BETWEEN ? AND ? AND json_extract(v.value,'$.name')=?
        ORDER BY r.received"""
    parameters=['$.'+field for field in fields]+['$.'+group,agent,start,end,name]
    aggregates={field:{} for field in fields}
    previous={}
    for row in connection.execute(query,parameters):
        timestamp=row[0]
        for index,field in enumerate(fields):
            value=row[index+1]
            if not isinstance(value,(int,float)) or not math.isfinite(value):
                continue
            key=int(timestamp/bucket)
            slots=aggregates[field]
            if key not in slots:
                slots[key]={'timestamp_sum':0,'sum':0,'count':0,'first':timestamp,'last':timestamp,'peak':value,'has_gap':0}
            slot=slots[key]
            slot['has_gap'] |= int(field in previous and timestamp-previous[field]>180)
            previous[field]=timestamp
            slot['timestamp_sum']+=timestamp
            slot['sum']+=value
            slot['count']+=1
            slot['last']=timestamp
            slot['peak']=max(slot['peak'],value)
    return {field:[{'timestamp':slot['timestamp_sum']/slot['count'],'value':slot['sum']/slot['count'],
                   'first':slot['first'],'last':slot['last'],'peak':slot['peak'],'has_gap':slot['has_gap']}
                  for _,slot in sorted(slots.items())] for field,slots in aggregates.items()}


def samples(connection,agent,group,name,field,start,end,bucket):
    assert field in FIELDS[group]
    return metric_series(connection,agent,group,name,start,end,bucket)[field]


def chart(rows,title,start,end,iops=False):
    if not rows:
        return '<section class="server"><h3>'+esc(title)+'</h3><p class="muted">Измерений пока нет.</p></section>'
    maximum=max(1,max(row['peak'] for row in rows)*1.1)
    fmt=lambda value: f'{value:.1f} оп/с' if iops else size(value)+'/с'
    x=lambda t: 90+(t-start)/(end-start)*890
    y=lambda value: 200-value/maximum*180
    drawing=''
    for ratio in (0,.25,.5,.75,1):
        drawing+=f'<line class="chart-grid" x1="90" x2="980" y1="{y(maximum*ratio)}" y2="{y(maximum*ratio)}"/><text class="chart-label" x="82" y="{y(maximum*ratio)+4}" text-anchor="end">{esc(fmt(maximum*ratio))}</text>'
    for fraction in (0,.5,1):
        timestamp=start+(end-start)*fraction
        drawing+=f'<text class="chart-label" x="{x(timestamp)}" y="230" text-anchor="{"start" if fraction==0 else "end" if fraction==1 else "middle"}">{stamp(timestamp)}</text>'
    previous=None
    for row in rows:
        if previous and not row['has_gap'] and not previous['has_gap'] and row['first']-previous['last']<=180:
            drawing+=f'<line stroke="#83c4ff" stroke-width="2" x1="{x(previous["timestamp"])}" y1="{y(previous["value"])}" x2="{x(row["timestamp"])}" y2="{y(row["value"])}"/>'
        tooltip=stamp(row['timestamp'])+' · среднее '+fmt(row['value'])+' · пик '+fmt(row['peak'])
        drawing+=f'<circle class="chart-point" fill="#83c4ff" r="3" cx="{x(row["timestamp"])}" cy="{y(row["value"])}"><title>{esc(tooltip)}</title></circle>'
        previous=row
    return '<section class="server"><h2>'+esc(title)+'</h2><div class="chart-scroll"><svg class="history-chart" role="img" aria-label="'+esc(title)+'" viewBox="0 0 1000 245">'+drawing+'</svg></div></section>'


def sections(connection, agent, period, start,end,bucket,nic=None,disk=None):
    options={group:names(connection,agent,group,start,end) for group in FIELDS}
    nic=nic if nic in options['network'] else next(iter(options['network']), '')
    disk=disk if disk in options['disk_io'] else next(iter(options['disk_io']), '')
    content='<form class="searchbar" method="get" action="/history/'+esc(quote(agent,safe=''))+'"><input type="hidden" name="period" value="'+esc(period)+'">'
    for group,key,selected,label in [('network','nic',nic,'Сетевой интерфейс'),('disk_io','disk',disk,'Дисковое устройство')]:
        content+='<label>'+label+'<select name="'+key+'">'+''.join('<option '+('selected ' if name==selected else '')+'value="'+esc(name)+'">'+esc(name)+'</option>' for name in options[group])+'</select></label>'
    content+='<button>Показать графики</button></form><p class="muted history-note">Скорости — секундные снимки перед отчётом. Выбран отдельный интерфейс/устройство, без суммирования виртуальных адаптеров. Пропуски не считаются нулями.</p>'
    series={group:metric_series(connection,agent,group,name,start,end,bucket) for group,name in [('network',nic),('disk_io',disk)] if name}
    for group,name,field,title,iops in [
        ('network',nic,'receive_bytes_per_second','Сеть · приём',False),('network',nic,'send_bytes_per_second','Сеть · передача',False),
        ('disk_io',disk,'read_bytes_per_second','Диски · чтение',False),('disk_io',disk,'write_bytes_per_second','Диски · запись',False),
        ('disk_io',disk,'read_iops','Диски · чтение IOPS',True),('disk_io',disk,'write_iops','Диски · запись IOPS',True)]:
        if name:
            content+=chart(series[group][field],title+' · '+name,start,end,iops)
    if not nic and not disk:
        content+='<p class="empty">История сети и дисковых операций появится после отчётов расширенного агента.</p>'
    return content, {'nic': nic, 'disk': disk}
