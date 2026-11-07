"""Authorized Telegram command polling with persistent cursor and reply queue."""
from collections import OrderedDict
import json
import os
import signal
import socket
import threading
import time

from .bot_reports import KEYBOARD,command_name,render
from .notifications import telegram_request
from .notification_types import DeliveryError


class StopRequested(Exception):
    pass


def initialize(connection):
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS bot_state(name TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS bot_replies(
        update_id INTEGER PRIMARY KEY,chat_id TEXT,parts TEXT,next_part INTEGER,
        retry_at REAL,created REAL,completed INTEGER DEFAULT 0);
    ''')


def state(connection,name,value):
    connection.execute('INSERT INTO bot_state VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',(name,str(value)))


def offset(connection):
    row=connection.execute("SELECT value FROM bot_state WHERE name='offset'").fetchone()
    return int(row[0]) if row else 0


class CommandLimiter:
    def __init__(self):
        self.users=OrderedDict()
    def allow(self,user,now):
        tokens,last=self.users.pop(user,(3,now))
        tokens=min(3,tokens+max(0,now-last)/5)
        allowed=tokens>=1
        self.users[user]=(tokens-1 if allowed else tokens,now)
        while len(self.users)>1000:self.users.popitem(last=False)
        return allowed


def queue_update(db,update,chat_id,allowed_users,limiter,now):
    identifier=update.get('update_id')
    if not isinstance(identifier,int) or identifier<0:return
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if identifier<offset(c):return
        message=update.get('message',{})
        sender=message.get('from',{})
        message_chat=message.get('chat',{})
        text=message.get('text','')
        date=message.get('date',0)
        authorized=str(message_chat.get('id',''))==str(chat_id) and not sender.get('is_bot')
        if allowed_users and str(sender.get('id','')) not in allowed_users:authorized=False
        command=command_name(text) if isinstance(text,str) else None
        fresh=isinstance(date,(int,float)) and now-600<=date<=now+60
        pending=c.execute('SELECT COUNT(*) FROM bot_replies WHERE completed=0').fetchone()[0]
        if authorized and fresh and command and pending<20 and limiter.allow(str(sender.get('id','')),now):
            parts=render(c,command,now)
            c.execute('INSERT OR IGNORE INTO bot_replies VALUES (?,?,?,0,0,?,0)',(identifier,str(chat_id),json.dumps(parts,ensure_ascii=False),now))
        state(c,'offset',identifier+1)
        c.execute('DELETE FROM bot_replies WHERE completed=1 AND created<?',(now-86400,))


def flush(db,sender,now,heartbeat=lambda:None):
    with db() as c:
        c.execute('UPDATE bot_replies SET completed=1 WHERE completed=0 AND created<?',(now-600,))
        pending=c.execute('SELECT * FROM bot_replies WHERE completed=0 AND retry_at<=? ORDER BY update_id LIMIT 1',(now,)).fetchone()
    if not pending:return False
    parts=json.loads(pending['parts'])
    for index in range(pending['next_part'],min(len(parts),pending['next_part']+3)):
        heartbeat()
        try:
            sender(pending['chat_id'],parts[index],KEYBOARD)
        except DeliveryError as error:
            with db() as c:
                c.execute('UPDATE bot_replies SET retry_at=? WHERE update_id=?',(now+error.retry_after,pending['update_id']))
                state(c,'send_error',error.status or 'delivery')
            return False
        with db() as c:
            c.execute('UPDATE bot_replies SET next_part=?,completed=? WHERE update_id=?',(index+1,int(index+1==len(parts)),pending['update_id']))
            state(c,'last_delivery',time.time())
            state(c,'send_error','')
        heartbeat()
    return True


def notify_systemd(text):
    address=os.environ.get('NOTIFY_SOCKET')
    if not address:return
    if address.startswith('@'):address='\0'+address[1:]
    try:
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as client:
            client.connect(address);client.sendall(text.encode())
    except OSError:
        pass


def pause(stop,seconds,heartbeat=None):
    deadline=time.monotonic()+seconds
    while not stop.is_set() and time.monotonic()<deadline:
        if heartbeat:heartbeat()
        else:notify_systemd('WATCHDOG=1')
        stop.wait(min(10,max(0,deadline-time.monotonic())))


def main():
    token=os.environ.get('STATUS_TELEGRAM_TOKEN','').strip()
    chat_id=os.environ.get('STATUS_TELEGRAM_CHAT_ID','').strip()
    if not token or not chat_id:raise SystemExit('Не настроены токен бота и ID чата.')
    allowed_users={user.strip() for user in os.environ.get('STATUS_TELEGRAM_ALLOWED_USERS','').split(',') if user.strip()}
    from .app import db,DB
    import fcntl
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    with open(DB+'.bot.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Другой экземпляр бота уже запущен.')
        with db() as c:initialize(c)
        limiter=CommandLimiter()
        def heartbeat():
            notify_systemd('WATCHDOG=1')
            with db() as c:state(c,'heartbeat',time.time())
        notify_systemd('READY=1\nWATCHDOG=1\nSTATUS=Опрос команд Telegram')
        commands=[{'command':name,'description':description} for name,description in [
          ('status','Статус серверов'),('report','Отчёт за 24 часа'),('rdp','RDP-пользователи'),
          ('backup','Свежесть и файлы бэкапов'),('warnings','Предупреждения'),('panel','Открыть панель'),('help','Кнопки и помощь')]]
        registered=False
        while not stop.is_set():
            heartbeat()
            try:
                if not registered:
                    telegram_request(token,'setMyCommands',{'commands':commands})
                    registered=True
                def sender(chat,text,keyboard):
                    if stop.is_set():raise StopRequested()
                    telegram_request(token,'sendMessage',{'chat_id':chat,'text':text,
                        'reply_markup':keyboard,'disable_web_page_preview':True})
                    pause(stop,1.1,heartbeat)
                flushed=flush(db,sender,time.time(),heartbeat)
                if stop.is_set():break
                with db() as c:cursor=offset(c)
                updates=telegram_request(token,'getUpdates',{'offset':cursor,'limit':10,'timeout':0 if flushed else 10,'allowed_updates':['message']})
                if stop.is_set():break
                with db() as c:
                    state(c,'last_poll',time.time());state(c,'poll_error','')
                for update in sorted(updates,key=lambda item:item.get('update_id',0)):
                    queue_update(db,update,chat_id,allowed_users,limiter,time.time())
                flush(db,sender,time.time(),heartbeat)
                if not updates:pause(stop,1,heartbeat)
            except StopRequested:
                break
            except DeliveryError as error:
                with db() as c:state(c,'poll_error',error.status or 'connection')
                print('Не удалось обратиться к Telegram; повтор позже. Код:',error.status or 'соединение',flush=True)
                pause(stop,error.retry_after,heartbeat)
        notify_systemd('STOPPING=1')


if __name__=='__main__':
    main()
