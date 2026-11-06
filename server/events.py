"""Persistent state-transition log, independent of Telegram credentials."""
import json
import time
from datetime import datetime, timezone, timedelta
from .incidents import evaluate
from .dashboard import esc, page


def record(connection, agent, category, message, level='info', now=None):
    connection.execute('INSERT INTO events(received,agent,category,level,message) VALUES (?,?,?,?,?)',
                       (time.time() if now is None else now,agent,category,level,message[:4000]))


def process_events(db, now=None):
    now = time.time() if now is None else now
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        rows = c.execute('SELECT a.id,r.received,r.data FROM agents a LEFT JOIN reports r ON r.rowid=(SELECT rowid FROM reports WHERE agent=a.id ORDER BY received DESC LIMIT 1)').fetchall()
        existing = c.execute('SELECT * FROM event_state').fetchall()
        current, valid, checked = evaluate(rows, existing, now)
        states = {s['key']:s for s in existing}
        for key,(agent,text) in current.items():
            previous = states.get(key)
            if not previous or not previous['active']:
                record(c,agent,key.split(':')[0],text,'warning',now)
            c.execute('INSERT INTO event_state VALUES (?,?,?,1) ON CONFLICT(key) DO UPDATE SET body=excluded.body,active=1', (key,agent,text))
        for key,state in states.items():
            if key not in valid:
                c.execute('DELETE FROM event_state WHERE key=?',(key,))
            elif key in checked and key not in current and state['active']:
                record(c,state['agent'],key.split(':')[0],'Восстановлено: '+state['body'],'info',now)
                c.execute('UPDATE event_state SET active=0 WHERE key=?',(key,))
        c.execute('DELETE FROM events WHERE received<?',(now-90*86400,))


def event_page(rows, agent='', level='', before=None):
    from urllib.parse import urlencode
    content='<header class="topbar"><a class="brand" href="/">Статус серверов</a><a class="nav-link" href="/">← Обзор</a></header><div class="heading"><h1>Журнал событий</h1></div>'
    content+='<form class="searchbar" method="get"><label>ID агента<input name="agent" value="'+esc(agent)+'"></label><label>Уровень<select name="level"><option value="">Все</option><option value="warning" '+('selected' if level=='warning' else '')+'>Проблемы</option><option value="info" '+('selected' if level=='info' else '')+'>Информация</option></select></label><button>Показать</button><a class="nav-link" href="/events">Сбросить</a></form><section class="server">'
    for row in rows[:50]:
        stamp=datetime.fromtimestamp(row['received'],timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S МСК')
        content+='<article class="event-row"><p class="muted">'+stamp+' · '+esc(row['agent'] or 'Панель')+' · '+esc(row['category'])+'</p><p class="'+('text-warning' if row['level']=='warning' else '')+'">'+esc(row['message'])+'</p></article>'
    if not rows:
        content+='<p class="empty">Событий по выбранным условиям нет.</p>'
    content+='</section>'
    if len(rows)>50:
        content+='<a class="nav-link" href="/events?'+esc(urlencode({'agent':agent,'level':level,'before':rows[49]['id']}))+'">Более ранние события →</a>'
    return page(content+'<footer>Хранение — 90 дней. История начинается с установки этой версии.</footer>')


def main():
    import fcntl
    from .app import db,DB
    with open(DB+'.events.lock','a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        process_events(db)


if __name__=='__main__':
    main()
