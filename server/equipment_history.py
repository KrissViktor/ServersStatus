"""Inventory revisions from complete snapshots; volatile readings are excluded."""
import hashlib
import json
from .hardware import KINDS, LABELS, display

SCHEMA='''CREATE TABLE IF NOT EXISTS equipment_history(id INTEGER PRIMARY KEY,agent TEXT NOT NULL,received REAL NOT NULL,fingerprint TEXT NOT NULL,data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS equipment_history_agent ON equipment_history(agent,id);'''
VOLATILE={'CurrentHorizontalResolution','CurrentVerticalResolution','Speed'}


def canonical(report):
    info=report.get('hardware') or {}
    if info.get('status')!='available' or info.get('truncated') or info.get('unavailable'):
        return None
    items=[]
    for item in info.get('items',[]):
        fields={key:value for key,value in item.get('fields',{}).items() if key not in VOLATILE and value}
        if fields:items.append({'kind':item['kind'],'fields':fields})
    if not items:return None
    system=report.get('system') or {}
    items.append({'kind':'os','fields':{key:system[key] for key in ('os','release','version','edition','architecture') if system.get(key)}})
    return sorted(items,key=lambda item:json.dumps(item,sort_keys=True,ensure_ascii=False))


def record(c,agent,received,report):
    items=canonical(report)
    if items is None:return
    encoded=json.dumps(items,sort_keys=True,ensure_ascii=False)
    fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
    last=c.execute('SELECT fingerprint FROM equipment_history WHERE agent=? ORDER BY id DESC LIMIT 1',(agent,)).fetchone()
    if last and last[0]==fingerprint:return
    c.execute('INSERT INTO equipment_history(agent,received,fingerprint,data) VALUES (?,?,?,?)',(agent,received,fingerprint,encoded))


def changes(before,after):
    kinds=set(item['kind'] for item in before+after)
    return [(kind,[v for v in before if v['kind']==kind],[v for v in after if v['kind']==kind]) for kind in sorted(kinds) if [v for v in before if v['kind']==kind]!=[v for v in after if v['kind']==kind]]


def render(c,agent):
    from .dashboard import esc
    from .windows_ui import stamp
    rows=c.execute('SELECT * FROM equipment_history WHERE agent=? ORDER BY id DESC LIMIT 31',(agent,)).fetchall()
    result='<div class="equipment-history">'
    if not rows:return result+'<p class="muted">Ожидаем первый полный отчёт оборудования. Старые изменения не восстанавливаются задним числом.</p></div>'
    if len(rows)==1:return result+'<p class="muted">Базовая комплектация сохранена '+esc(stamp(rows[0]['received']))+'. Изменений пока нет.</p></div>'
    for current,previous in zip(rows[:30],rows[1:]):
        diff=changes(json.loads(previous['data']),json.loads(current['data']))
        result+='<details><summary>'+esc(stamp(current['received']))+' · '+esc(', '.join(KINDS.get(kind,'Операционная система') for kind,_,_ in diff))+'</summary>'
        for kind,old,new in diff:
            result+='<h4>'+esc(KINDS.get(kind,'Операционная система'))+'</h4><div class="equipment-diff">'
            for label,items in [('Было',old),('Стало',new)]:
                result+='<div><b>'+label+'</b>'
                for item in items:
                    result+='<dl>'+''.join('<dt>'+esc(LABELS.get(k,k))+'</dt><dd>'+esc(display(k,v))+'</dd>' for k,v in item['fields'].items())+'</dl>'
                if not items:result+='<p class="muted">Не сообщается</p>'
                result+='</div>'
            result+='</div>'
        result+='</details>'
    return result+'<p class="muted legend">Время обнаружения изменения, а не время физической замены. Порядок устройств и текущие скорости не учитываются. Неполные отчёты не меняют базу сравнения. Показаны последние 30 изменений.</p></div>'
