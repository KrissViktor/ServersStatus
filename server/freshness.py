"""Separate delivery freshness from collection failures and measurement times."""
import math
import re
import time
from .dashboard import esc,duration
from .windows_ui import stamp


def timestamp(value):
    return value if isinstance(value,(int,float)) and not isinstance(value,bool) and 0<=value<=4102444800 and math.isfinite(value) else None


def status(received,now):
    received=timestamp(received)
    if received is None:return 'unknown','neutral','Нет отчётов'
    age=max(0,now-received)
    if age>=180:return 'stale','danger','Нет связи с агентом'
    if age>30:return 'delayed','warning','Отчёты задерживаются'
    return 'fresh','normal','Отчёты поступают'


def line(received,now=None,info=None,historical=False,max_age=180):
    now=time.time() if now is None else now
    received=timestamp(received);info=info or {}
    sampled=timestamp(info.get('sampled_at',info.get('checked_at')))
    state,color,label=status(received,now)
    if historical:state,color,label='historical','neutral','Сохранённые данные'
    if info.get('status') in ('unavailable','error','unsupported','checking'):
        label={'unavailable':'Не удалось получить показатель','error':'Ошибка сбора показателя','unsupported':'Показатель не поддерживается','checking':'Сбор показателя ещё выполняется'}[info['status']]
        color='neutral' if historical else 'warning';state='collection-'+info['status']
    elif not historical and sampled is not None and now-sampled>=max_age:
        state,color,label='measurement-stale','warning','Измерение устарело'
    text=label
    if sampled is not None:text+=' · Проверено источником: '+stamp(sampled)
    if received is not None:
        text+=' · Отчёт получен: '+stamp(received)
        if not historical:text+=' ('+duration(max(0,now-received))+' назад)'
    if state=='stale':text+=' · Недоступность самого сервера не подтверждена'
    return '<p class="data-freshness text-'+color+'" data-freshness="'+state+'">'+esc(text)+'</p>'


def sections(content,received,now,info=None,historical=False):
    info=info or {}
    def annotate(match):
        title=re.sub('<[^>]+>','',re.sub(r'<span class="count">.*?</span>','',match[1])).strip()
        details=info.get(title,{})
        return match[0]+line(received,now,details.get('info'),historical,details.get('max_age',180))
    return re.sub(r'<h3>(.*?)</h3>',annotate,content,flags=re.S)
