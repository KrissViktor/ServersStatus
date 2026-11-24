"""Authorized Telegram command polling with persistent cursor and reply queue."""
from collections import OrderedDict
import json
import os
import re
import signal
import socket
import threading
import time

from .bot_reports import KEYBOARD,command_name,render
from .bot_portal import COMMANDS as PORTAL_COMMANDS, admins as portal_admins, render as render_portal
from .notifications import telegram_request
from .notification_types import DeliveryError
from .telegram_config import blocked, read, user_ids, valid_user_id

PORTAL_KEYBOARD = {
    **KEYBOARD,
    'keyboard': [*KEYBOARD['keyboard'][:-1], ['Помощь','Портал']],
}
PORTAL_ONLY_KEYBOARD = {
    **KEYBOARD,
    'keyboard': [['Портал'], ['/help']],
}
PORTAL_ONLY_REPLY = 3
PORTAL_SUBMENU = {
    **KEYBOARD,
    'keyboard': [['Ссылка','Сессии'], ['Поменять пароль'], ['Назад']],
}
PORTAL_HELP = (
    'Управление порталом\n'
    '/portal_users — пользователи и роли\n'
    '/portal_sessions [логин] — активные сеансы и их ID\n'
    '/portal_end ID — завершить один сеанс\n'
    '/portal_kick логин — завершить все сеансы пользователя\n'
    '/portal_password логин — ссылка для смены пароля\n'
    '/portal_blocks — блокировки входа / sign-in locks\n'
    '/portal_unblock ID — снять блокировку / remove a lock'
)


class StopRequested(Exception):
    pass


def initialize(connection):
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS bot_state(name TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE IF NOT EXISTS bot_users(
        id TEXT PRIMARY KEY, first_name TEXT NOT NULL, username TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS bot_replies(
        update_id INTEGER PRIMARY KEY,chat_id TEXT,parts TEXT,next_part INTEGER,
        retry_at REAL,created REAL,completed INTEGER DEFAULT 0,portal INTEGER NOT NULL DEFAULT 0);
    ''')
    if not any(row[1]=='portal' for row in connection.execute('PRAGMA table_info(bot_replies)')):
        connection.execute('ALTER TABLE bot_replies ADD COLUMN portal INTEGER NOT NULL DEFAULT 0')
    if not any(row[1]=='requester' for row in connection.execute('PRAGMA table_info(bot_replies)')):
        connection.execute("ALTER TABLE bot_replies ADD COLUMN requester TEXT NOT NULL DEFAULT ''")


def state(connection,name,value):
    connection.execute('INSERT INTO bot_state VALUES (?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value',(name,str(value)))


def offset(connection):
    row=connection.execute("SELECT value FROM bot_state WHERE name='offset'").fetchone()
    return int(row[0]) if row else 0


def restart_marker(connection):
    row=connection.execute("SELECT value FROM bot_state WHERE name='restart_request'").fetchone()
    return row[0] if row else ''


def portal_reply(c, action, argument, sender, now):
    prompt = 'portal_password_prompt:'+sender
    c.execute('DELETE FROM bot_state WHERE name=?',(prompt,))
    if action in ('home','help'):
        return [PORTAL_HELP],1
    if action == 'menu':
        return ['Портал. Выберите действие.'],2
    if action == 'link':
        return render(c,'panel',now),2
    if action == 'portal_password' and not argument:
        state(c,prompt,now+300)
        return ['Отправьте логин пользователя. Я пришлю одноразовую ссылку для смены пароля.'],2
    if action == 'password_login':
        if not re.fullmatch(r'[A-Za-zА-Яа-яЁё0-9_.-]{1,64}',argument):
            state(c,prompt,now+300)
            return ['Укажите логин пользователя или нажмите «Назад».'],2
        action = 'portal_password'
    parts = render_portal(c,action,argument,sender,now)
    if action == 'portal_sessions':
        parts.append('Завершить один сеанс: /portal_end ID\nЗавершить все сеансы пользователя: /portal_kick логин')
    return parts,2


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
        parts_text = text.strip().split(maxsplit=1) if isinstance(text,str) else []
        portal_command = parts_text[0].split('@',1)[0].removeprefix('/').casefold() if parts_text and parts_text[0].startswith('/') else ''
        sender_id = str(sender.get('id',''))
        private_chat = (message_chat.get('type')=='private' and str(message_chat.get('id',''))==sender_id
                        and not sender.get('is_bot'))
        private_admin = private_chat and sender_id in portal_admins()
        fresh=isinstance(date,(int,float)) and now-600<=date<=now+60
        config=read()
        known_users=set().union(*(user_ids(config.get(key,'')) for key in ('users','admins','allowed','blocked')))
        if (fresh and not sender.get('is_bot') and valid_user_id(sender_id)
                and (str(message_chat.get('id',''))==str(chat_id) or sender_id in known_users)):
            name=' '.join(str(sender.get(key) or '') for key in ('first_name','last_name')).strip()
            c.execute('INSERT OR IGNORE INTO bot_users VALUES (?,?,?)',
                      (sender_id,name[:160],str(sender.get('username') or '')[:80]))
        if sender_id in blocked(config):
            state(c,'offset',identifier+1)
            return
        pending=c.execute('SELECT COUNT(*) FROM bot_replies WHERE completed=0').fetchone()[0]
        action = None
        argument = parts_text[1].strip() if portal_command and len(parts_text)>1 else ''
        if private_admin and fresh and parts_text:
            label = text.strip().casefold()
            if portal_command in PORTAL_COMMANDS:
                action = portal_command
            else:
                buttons = {'портал':'menu','ссылка':'link','сессии':'portal_sessions',
                           'поменять пароль':'portal_password','назад':'home'}
                action = 'help' if command=='help' else buttons.get(label)
                if not action and not command and not portal_command:
                    prompt = c.execute('SELECT value FROM bot_state WHERE name=?',('portal_password_prompt:'+sender_id,)).fetchone()
                    if prompt and float(prompt[0])>now:
                        action,argument = 'password_login',text.strip()
        if action and pending<20 and limiter.allow(sender_id,now):
            parts,keyboard = portal_reply(c,action,argument,sender_id,now)
            if keyboard==1 and not authorized:
                keyboard = PORTAL_ONLY_REPLY
            c.execute('INSERT OR IGNORE INTO bot_replies VALUES (?,?,?,0,0,?,0,?,?)',(identifier,sender_id,json.dumps(parts,ensure_ascii=False),now,keyboard,sender_id))
        elif authorized and fresh and command and pending<20 and limiter.allow(sender_id,now):
            parts=render(c,command,now)
            if private_chat and command=='help':
                parts.append(
                    'Ваш Telegram ID: '+sender_id+'\n'
                    'Для управления порталом добавьте этот ID в STATUS_TELEGRAM_PORTAL_ADMINS в настройках бота на сервере.'
                )
            c.execute('INSERT OR IGNORE INTO bot_replies VALUES (?,?,?,0,0,?,0,0,?)',(identifier,str(chat_id),json.dumps(parts,ensure_ascii=False),now,sender_id))
        state(c,'offset',identifier+1)
        c.execute('DELETE FROM bot_replies WHERE completed=1 AND created<?',(now-86400,))


def flush(db,sender,now,heartbeat=lambda:None):
    with db() as c:
        c.execute("UPDATE bot_replies SET completed=1,parts='[]' WHERE completed=0 AND created<?",(now-600,))
        pending=c.execute('SELECT * FROM bot_replies WHERE completed=0 AND retry_at<=? ORDER BY update_id LIMIT 1',(now,)).fetchone()
    if not pending:return False
    parts=json.loads(pending['parts'])
    if pending['portal']==2:
        keyboard = PORTAL_SUBMENU
    elif pending['portal']==PORTAL_ONLY_REPLY:
        keyboard = PORTAL_ONLY_KEYBOARD
    else:
        keyboard = PORTAL_KEYBOARD if pending['chat_id'] in portal_admins() else KEYBOARD
    for index in range(pending['next_part'],min(len(parts),pending['next_part']+3)):
        heartbeat()
        blocked_ids=blocked(read())
        if ({pending['requester'],pending['chat_id']} & blocked_ids
                or pending['portal'] and pending['chat_id'] not in portal_admins()):
            with db() as c:
                c.execute("UPDATE bot_replies SET completed=1,parts='[]' WHERE update_id=?",(pending['update_id'],))
            return False
        try:
            sender(pending['chat_id'],parts[index],keyboard)
        except DeliveryError as error:
            with db() as c:
                c.execute('UPDATE bot_replies SET retry_at=? WHERE update_id=?',(now+error.retry_after,pending['update_id']))
                state(c,'send_error',error.status or 'delivery')
            return False
        with db() as c:
            completed = int(index+1==len(parts))
            c.execute("UPDATE bot_replies SET next_part=?,completed=?,parts=CASE WHEN ? THEN '[]' ELSE parts END WHERE update_id=?",(index+1,completed,completed,pending['update_id']))
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
    from .app import db,DB
    import fcntl
    stop=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stop.set())
    signal.signal(signal.SIGINT,lambda *_:stop.set())
    with open(DB+'.bot.lock','a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Другой экземпляр бота уже запущен.')
        with db() as c:
            initialize(c)
            c.execute('BEGIN IMMEDIATE')
            marker=restart_marker(c)
            config=read()
            token=config.get('token','')
            chat_id=config.get('chat','')
            if not token or not chat_id:raise SystemExit('Не настроены токен бота и ID чата.')
            bot_id=token.partition(':')[0]
            previous=c.execute("SELECT value FROM bot_state WHERE name='bot_id'").fetchone()
            if previous and previous[0]!=bot_id:
                c.execute("DELETE FROM bot_state WHERE name='offset' OR name LIKE 'portal_password_prompt:%'")
                c.execute('DELETE FROM bot_replies')
            state(c,'bot_id',bot_id)
            state(c,'restart_applied',marker)
            state(c,'heartbeat',time.time())
            for key in ('last_poll','poll_error','send_error'):
                state(c,key,'0' if key=='last_poll' else '')
        allowed_users=user_ids(config.get('allowed',''))
        limiter=CommandLimiter()
        def heartbeat():
            notify_systemd('WATCHDOG=1')
            with db() as c:
                requested=restart_marker(c)
                if requested!=marker:
                    state(c,'restart_seen',requested)
                    stop.set()
                else:
                    state(c,'heartbeat',time.time())
        notify_systemd('READY=1\nWATCHDOG=1\nSTATUS=Опрос команд Telegram')
        commands=[{'command':name,'description':description} for name,description in [
          ('status','Статус серверов'),('report','Отчёт за 24 часа'),('rdp','RDP-пользователи'),
          ('backup','Свежесть и файлы бэкапов'),('warnings','Предупреждения'),('panel','Открыть панель'),('help','Кнопки и помощь')]]
        registered=False
        registered_admins=set()
        def register_admin(chat):
            if chat in registered_admins:
                return
            base = commands if chat==chat_id and (not allowed_users or chat in allowed_users) else [
                {'command':'help','description':'Команды управления порталом'}
            ]
            try:
                telegram_request(token,'setMyCommands',{'scope':{'type':'chat','chat_id':int(chat)},'commands':base+[
                    {'command':name,'description':description} for name,description in PORTAL_COMMANDS.items()
                ]})
            except DeliveryError:
                return
            registered_admins.add(chat)
        while not stop.is_set():
            heartbeat()
            if stop.is_set():break
            try:
                if not registered:
                    telegram_request(token,'setMyCommands',{'commands':commands})
                    for admin in portal_admins():
                        heartbeat()
                        if stop.is_set():raise StopRequested()
                        register_admin(admin)
                    registered=True
                current_admins=portal_admins()
                for admin in registered_admins-current_admins:
                    heartbeat()
                    if stop.is_set():raise StopRequested()
                    try:
                        telegram_request(token,'deleteMyCommands',{'scope':{'type':'chat','chat_id':int(admin)}})
                    except DeliveryError:
                        continue
                    registered_admins.discard(admin)
                def sender(chat,text,keyboard):
                    if stop.is_set():raise StopRequested()
                    telegram_request(token,'sendMessage',{'chat_id':chat,'text':text,
                        'reply_markup':keyboard,'disable_web_page_preview':True})
                    if any(keyboard is layout for layout in (PORTAL_KEYBOARD,PORTAL_ONLY_KEYBOARD,PORTAL_SUBMENU)):
                        register_admin(chat)
                    pause(stop,1.1,heartbeat)
                flushed=flush(db,sender,time.time(),heartbeat)
                if stop.is_set():break
                with db() as c:cursor=offset(c)
                updates=telegram_request(token,'getUpdates',{'offset':cursor,'limit':10,'timeout':0 if flushed else 10,'allowed_updates':['message']})
                heartbeat()
                if stop.is_set():break
                with db() as c:
                    state(c,'last_poll',time.time());state(c,'poll_error','')
                for update in sorted(updates,key=lambda item:item.get('update_id',0)):
                    queue_update(db,update,chat_id,user_ids(read().get('allowed','')),limiter,time.time())
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
