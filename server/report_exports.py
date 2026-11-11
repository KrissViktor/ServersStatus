"""Downloadable, credential-free reports in four formats."""
import csv
from datetime import datetime,timedelta
import html
import io
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlencode
import xml.etree.ElementTree as ET
from fastapi import HTTPException,Request,Query
from fastapi.responses import Response
from .fleet import MSK,members,stats
from .history import PERIODS,load_history
from .stability import load as availability,percentage
from .disks import monitored_disks

NOTES=['Доступность подтверждается отчётами с допуском 30 секунд; отсутствие данных не доказывает выключение сервера.',
       'До первого известного отчёта время не учитывается. Средние рассчитаны по полученным измерениям.',
       'Перезагрузки определяются по аптайму. Изменения комплектации датированы временем обнаружения.']


def iso(value):return datetime.fromtimestamp(value,MSK).isoformat(timespec='seconds') if value is not None else None


def dataset(c,kind,now,agents=None,period='24h',day='',group=''):
    rows=members(c,group)
    if kind=='compare':
        if period not in PERIODS or len(agents or [])>6:raise HTTPException(400,'Выберите до 6 серверов и допустимый период')
        names={row['id']:row['name'] for row in rows};chosen=list(dict.fromkeys(agents or [])) if agents else [row['id'] for row in rows[:2]]
        if any(agent not in names for agent in chosen):raise HTTPException(400,'Сервер вне выбранной группы')
        rows=[{'id':agent,'name':names[agent]} for agent in chosen]
        end=now;start=end-PERIODS[period][1];title='Сравнение серверов';bucket=PERIODS[period][2]
    elif kind=='daily':
        today=datetime.fromtimestamp(now,MSK).date()
        try:date=datetime.strptime(day,'%Y-%m-%d').date() if day else today-timedelta(days=1)
        except ValueError:raise HTTPException(400,'Некорректная дата') from None
        from .portal_settings import retention_days
        if not today-timedelta(days=retention_days(c)-1)<=date<=today:raise HTTPException(400,'Дата вне сохранённой истории')
        start=datetime.combine(date,datetime.min.time(),MSK).timestamp();end=min(start+86400,now)
        title='Сводка за '+date.strftime('%d.%m.%Y');bucket=300
    else:raise HTTPException(404)
    if len(rows)>200:raise HTTPException(400,'Для выгрузки выберите группу до 200 серверов')
    result={'schema_version':1,'kind':kind,'title':title,'generated_at':iso(now),'timezone':'Europe/Moscow','start':iso(start),'end':iso(end),'start_unix':start,'end_unix':end,'group':None,'units':{'cpu':'percent','ram':'percent','availability':'percent','durations':'seconds','disk_capacity':'bytes'},'notes':NOTES,'servers':[]}
    if group:result['group']=dict(c.execute('SELECT id,name FROM server_groups WHERE id=?',(int(group),)).fetchone())
    for row in rows:
        agent=row['id'];summary=stats(c,agent,start,end);up=availability(c,agent,start,end)
        latest=c.execute('SELECT received,data FROM reports WHERE agent=? AND received<=? ORDER BY received DESC LIMIT 1',(agent,end)).fetchone()
        # For comparison include current telemetry retained outside the raw-history table.
        if kind=='compare':
            current=c.execute('SELECT received,data FROM current_reports WHERE agent=?',(agent,)).fetchone()
            if current and (latest is None or current['received']>latest['received']):latest=current
        data=json.loads(latest['data']) if latest else {}
        incidents=[dict(item) for item in c.execute('SELECT category,opened,closed,resolution,message FROM incident_history WHERE agent=? AND opened<? AND (closed IS NULL OR closed>=?) ORDER BY opened DESC LIMIT 201',(agent,end,start))]
        incident_truncated=len(incidents)>200;incidents=incidents[:200]
        for item in incidents:
            item['duration_in_period_seconds']=max(0,min(end,item['closed'] if item['closed'] is not None else end)-max(start,item['opened']))
            item['opened']=iso(item['opened']);item['closed']=iso(item['closed'])
        equipment=[]
        for revision in c.execute('SELECT id,received,data FROM equipment_history WHERE agent=? AND received>=? AND received<? ORDER BY id DESC LIMIT 101',(agent,start,end)):
            before=c.execute('SELECT data FROM equipment_history WHERE agent=? AND id<? ORDER BY id DESC LIMIT 1',(agent,revision['id'])).fetchone()
            if before:equipment.append({'detected_at':iso(revision['received']),'before':json.loads(before['data']),'after':json.loads(revision['data'])})
        previous=stats(c,agent,start-86400,end-86400)
        checks=data.get('application_checks') or {}
        result['servers'].append({'id':agent,'name':row['name'],'sample_count':summary['n'],
            'cpu_avg_percent':summary['cpu'],'cpu_peak_percent':summary['cpu_max'],'ram_avg_percent':summary['ram'],'ram_peak_percent':summary['ram_max'],
            'cpu_change_pp':summary['cpu']-previous['cpu'] if summary['cpu'] is not None and previous['cpu'] is not None else None,
            'ram_change_pp':summary['ram']-previous['ram'] if summary['ram'] is not None and previous['ram'] is not None else None,
            'availability_percent':up['percent'],'observed_start':iso(up['start']) if up['percent'] is not None else None,
            'missing_seconds':up['missing'],'longest_gap_seconds':up['longest'],'gap_count':len(up['gaps']),'reboot_count':len(up['reboots']),
            'incidents_started':c.execute('SELECT COUNT(*) FROM incident_history WHERE agent=? AND opened>=? AND opened<?',(agent,start,end)).fetchone()[0],
            'incidents_recovered':c.execute("SELECT COUNT(*) FROM incident_history WHERE agent=? AND resolution='recovered' AND closed>=? AND closed<?",(agent,start,end)).fetchone()[0],
            'last_report_at':iso(latest['received']) if latest else None,'last_report_stale':latest is None or end-latest['received']>=180,
            'processor':(data.get('system') or {}).get('processor'),'memory_total_bytes':(data.get('system') or {}).get('memory_total_bytes'),
            'disks':[{key:disk.get(key) for key in ('path','used_percent','free_bytes','total_bytes')} for disk in monitored_disks(data)],
            'application_checks':{'checked_at':iso(checks.get('checked_at')),'items':[{key:item.get(key) for key in ('id','name','kind','status','message','latency_ms')} for item in checks.get('items',[])]},
            'incidents':incidents,'incidents_truncated':incident_truncated,'equipment_changes':equipment[:100],'equipment_changes_truncated':len(equipment)>100,
            'chart_points':[dict(point) for point in load_history(c,agent,start,end,bucket)] if kind=='compare' else []})
    return result


COLUMNS=[('id','ID сервера'),('name','Сервер'),('sample_count','Отчётов'),('availability_percent','Доступность, %'),('missing_seconds','Без данных, с'),('longest_gap_seconds','Максимальный пропуск, с'),('cpu_avg_percent','CPU среднее, %'),('cpu_peak_percent','CPU пик, %'),('ram_avg_percent','RAM среднее, %'),('ram_peak_percent','RAM пик, %'),('cpu_change_pp','Изменение CPU, п.п.'),('ram_change_pp','Изменение RAM, п.п.'),('reboot_count','Перезагрузок'),('incidents_started','Началось инцидентов'),('incidents_recovered','Завершилось инцидентов'),('processor','Процессор'),('memory_total_bytes','RAM всего, байт'),('last_report_at','Последний отчёт'),('last_report_stale','Отчёт устарел')]


def csv_cell(value):
    if value is None:return ''
    if isinstance(value,str) and (value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n'))):return "'"+value
    return value


def csv_bytes(report):
    output=io.StringIO(newline='');writer=csv.writer(output,delimiter=';',lineterminator='\r\n')
    writer.writerow(['Тип записи','Период с','Период до']+[label for _,label in COLUMNS]+['Подробности JSON'])
    writer.writerow(['metadata',report['start'],report['end']]+['']*len(COLUMNS)+[json.dumps({key:value for key,value in report.items() if key!='servers'},ensure_ascii=False)])
    def row(kind,server,detail,overrides=None):
        values={**server,**(overrides or {})}
        writer.writerow([kind,report['start'],report['end']]+[csv_cell(values.get(key)) for key,_ in COLUMNS]+[json.dumps(detail,ensure_ascii=False,separators=(',',':'))])
    for server in report['servers']:
        row('server',server,{key:server[key] for key in ('observed_start','gap_count','incidents_truncated','equipment_changes_truncated')})
        for disk in server['disks']:row('disk',{'id':server['id'],'name':server['name']},disk)
        for check in server['application_checks']['items']:row('application_check',{'id':server['id'],'name':server['name']},{'checked_at':server['application_checks']['checked_at'],**check})
        for incident in server['incidents']:row('incident',{'id':server['id'],'name':server['name']},incident)
        for change in server['equipment_changes']:row('equipment_change',{'id':server['id'],'name':server['name']},change)
        for point in server['chart_points']:row('chart',{'id':server['id'],'name':server['name']},point,{'cpu_avg_percent':point.get('cpu'),'ram_avg_percent':point.get('ram'),'sample_count':point.get('samples')})
    return ('\ufeff'+output.getvalue()).encode('utf-8')


def xml_bytes(report):
    def append(parent,key,value):
        safe_key=key if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*',key) else 'field'
        node=ET.SubElement(parent,safe_key)
        if safe_key!=key:node.set('name',re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]','',key))
        if value is None:node.set('nil','true')
        elif isinstance(value,dict):
            for name,child in value.items():append(node,name,child)
        elif isinstance(value,list):
            for child in value:append(node,'item',child)
        else:node.text=re.sub('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]','',str(value).lower() if isinstance(value,bool) else str(value))
    root=ET.Element('serversstatus_report')
    for key,value in report.items():append(root,key,value)
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


_font_lock=threading.Lock()


def pdf_bytes(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,KeepTogether
    from reportlab.graphics.shapes import Drawing,Line,String,Circle
    with _font_lock:
        if 'PortalSans' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('PortalSans',str(Path(__file__).with_name('assets')/'fonts'/'DejaVuSans.ttf')))
    buffer=io.BytesIO();width,height=landscape(A4);usable=width-64
    style=ParagraphStyle('Portal',fontName='PortalSans',fontSize=8,leading=12,spaceAfter=5,splitLongWords=True)
    heading=ParagraphStyle('Heading',parent=style,fontSize=15,leading=20,spaceAfter=10,keepWithNext=True)
    def p(value,kind=style):return Paragraph(html.escape(str(value if value is not None else 'Нет данных')).replace('\n','<br/>'),kind)
    def value(v,suffix=''):return '—' if v is None else (f'{v:.2f}'+suffix if isinstance(v,(int,float)) and not isinstance(v,bool) else str(v))
    def date_text(text):return datetime.fromisoformat(text).strftime('%d.%m.%Y %H:%M:%S') if text else 'Нет данных'
    story=[p(report['title'],heading),p(date_text(report['start'])+' — '+date_text(report['end'])+' · МСК'),p('Сформировано: '+date_text(report['generated_at']))]
    if report['group']:story.append(p('Группа: '+report['group']['name']))
    table=[[p(x) for x in ['Сервер','Доступность','Без данных, с','CPU ср. / пик','RAM ср. / пик','Перезагрузки','Инциденты нач. / заверш.']]]
    for server in report['servers']:
        table.append([p(server['name']),p(percentage(server['availability_percent'])),p(value(server['missing_seconds'])),p(value(server['cpu_avg_percent'],'%')+' / '+value(server['cpu_peak_percent'],'%')),p(value(server['ram_avg_percent'],'%')+' / '+value(server['ram_peak_percent'],'%')),p(server['reboot_count']),p(str(server['incidents_started'])+' / '+str(server['incidents_recovered']))])
    summary=Table(table,colWidths=[usable*x for x in [.19,.12,.13,.16,.16,.1,.14]],repeatRows=1,hAlign='LEFT')
    summary.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e9efec')),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#bdc8c1')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6)]));story+=[Spacer(1,10),summary,Spacer(1,12)]
    if report['kind']=='compare':
        start=report.get('start_unix',datetime.fromisoformat(report['start']).timestamp());end=report.get('end_unix',datetime.fromisoformat(report['end']).timestamp());palette=['#34735b','#356b9a','#9a681f','#805399','#b44b59','#287b7b']
        for field,title in [('cpu','CPU, %'),('ram','RAM, %')]:
            drawing=Drawing(usable,190)
            for percent in [0,25,50,75,100]:
                y=25+percent*1.3;drawing.add(Line(35,y,usable-10,y,strokeColor=colors.HexColor('#d7ded9'),strokeWidth=.4));drawing.add(String(2,y-3,str(percent),fontName='PortalSans',fontSize=7))
            for index,server in enumerate(report['servers']):
                previous=None;color=colors.HexColor(palette[index%6])
                for point in server['chart_points']:
                    if point.get(field) is None:previous=None;continue
                    x=35+(usable-45)*(point['timestamp']-start)/max(1,end-start);y=25+point[field]*1.3
                    if previous and not point['has_gap'] and not previous[2]:drawing.add(Line(previous[0],previous[1],x,y,strokeColor=color,strokeWidth=.8))
                    drawing.add(Circle(x,y,1.1,fillColor=color,strokeColor=None));previous=(x,y,point['has_gap'])
                drawing.add(String(35+(index%3)*240,178-(index//3)*10,server['name'][:30],fontName='PortalSans',fontSize=7,fillColor=color))
            story+=[KeepTogether([p(title,heading),drawing]),Spacer(1,12)]
    from .dashboard import size
    from .hardware import KINDS,LABELS,display
    from .equipment_history import changes
    for server in report['servers']:
        story+=[p(server['name']+' · '+server['id'],heading),p('CPU: '+str(server['processor'] or 'Не сообщается')+' · RAM: '+(size(server['memory_total_bytes']) if server['memory_total_bytes'] else 'Нет данных')),p('Последний отчёт: '+date_text(server['last_report_at'])+(' · устаревшие данные' if server['last_report_stale'] else ''))]
        story.append(p('Изменение средней нагрузки: CPU '+value(server['cpu_change_pp'],' п.п.')+' · RAM '+value(server['ram_change_pp'],' п.п.')))
        story.append(p('Максимальный пропуск: '+value(server['longest_gap_seconds'],' с')+' · пропусков: '+str(server['gap_count'])))
        for disk in server['disks']:story.append(p('Диск '+str(disk['path'])+': занято '+value(disk['used_percent'],'%')+', свободно '+size(disk['free_bytes'])))
        for item in server['application_checks']['items']:story.append(p('Проверка '+str(item['name'])+': '+str(item['status'])+' · '+str(item['message'])))
        if server['incidents']:story.append(p('Инциденты'))
        for item in server['incidents']:story.append(p(date_text(item['opened'])+' — '+(date_text(item['closed']) if item['closed'] else 'продолжается')+' · '+item['message']))
        for item in server['equipment_changes']:
            story.append(p('Изменение комплектации: '+date_text(item['detected_at'])))
            for kind,old,new in changes(item['before'],item['after']):
                story.append(p(KINDS.get(kind,'Операционная система')))
                for label,components in [('Было',old),('Стало',new)]:
                    if not components:story.append(p(label+': не сообщается'))
                    for component in components:
                        story.append(p(label+': '+'; '.join(LABELS.get(key,key)+': '+str(display(key,v)) for key,v in component['fields'].items())))
        if server['incidents_truncated'] or server['equipment_changes_truncated']:story.append(p('Подробные списки сокращены: до 200 инцидентов и 100 изменений на сервер.'))
        story.append(Spacer(1,10))
    story.extend(p(note) for note in report['notes'])
    def footer(canvas,doc):
        canvas.setFont('PortalSans',7);canvas.drawString(32,18,'ServersStatus');canvas.drawRightString(width-32,18,'Страница '+str(doc.page))
    SimpleDocTemplate(buffer,pagesize=(width,height),leftMargin=32,rightMargin=32,topMargin=30,bottomMargin=32,title=report['title'],author='ServersStatus').build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()


def export_links(kind,params):
    from .dashboard import esc
    result='<nav class="report-downloads" aria-label="Скачать отчёт"><span>Скачать</span>'
    for format in ('csv','pdf','xml','json'):
        url='/export/'+kind+'?'+urlencode({**params,'format':format},doseq=True)
        result+='<a href="'+esc(url)+'">'+format.upper()+'</a>'
    return result+'</nav>'


def register(app,db,authenticated):
    @app.get('/export/{kind}')
    def download(kind:str,request:Request,format:str='csv',agents:list[str]=Query(default=[]),period:str='24h',day:str='',group:str=''):
        if not authenticated(request):raise HTTPException(401)
        if format not in ('csv','pdf','xml','json'):raise HTTPException(400,'Неизвестный формат')
        if kind not in ('compare','daily'):raise HTTPException(404)
        now=time.time()
        with db() as c:report=dataset(c,kind,now,agents,period,day,group)
        try:
            if format=='csv':data=csv_bytes(report);media='text/csv'
            elif format=='json':data=json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8');media='application/json'
            elif format=='xml':data=xml_bytes(report);media='application/xml'
            else:data=pdf_bytes(report);media='application/pdf'
        except ImportError:raise HTTPException(503,'Установите зависимости из requirements.txt для формирования PDF') from None
        filename='serversstatus-'+kind+'-'+report['start'][:10]+'.'+format
        return Response(data,media_type=media,headers={'Content-Disposition':'attachment; filename="'+filename+'"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
