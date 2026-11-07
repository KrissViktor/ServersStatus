import json
from pathlib import Path
import tempfile
import unittest
from server import app as application
from server.bot import initialize,queue_update,flush,CommandLimiter,state
from server.bot_reports import KEYBOARD,render,split_text
from server.notification_types import DeliveryError

class BotTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous=application.DB
        self.addCleanup(setattr,application,'DB',previous)
        application.DB=str(Path(self.temp.name)/'bot.sqlite3')
        with application.db() as c:
            initialize(c)
            c.execute('INSERT INTO agents VALUES (?,?)',('sql','token'))
            data={'hostname':'SQL-PC','system':{'os':'Windows','memory_total_bytes':16*1024**3,'memory_used_bytes':6*1024**3},
                  'cpu_percent':10,'memory_percent':37.5,'rdp':{'status':'available','sessions':[{'username':'user1','domain':'DOMAIN','session_id':1,'state':'active'}]},
                  'disks':[],'services':[],'backups':[]}
            c.execute('INSERT INTO reports VALUES (?,?,?)',('sql',1000,json.dumps(data)))
        self.limiter=CommandLimiter()
        self.sent=[]

    def update(self,identifier=1,chat=123,user=5,text='Статус',date=1000):
        return {'update_id':identifier,'message':{'chat':{'id':chat},'from':{'id':user},'date':date,'text':text}}

    def test_keyboard_reports_and_manual_night_requests(self):
        for text in ('Статус','Отчет','RDP','Предупреждения','Панель','Помощь'):
            with application.db() as c:
                command={'Статус':'status','Отчет':'report','RDP':'rdp','Предупреждения':'warnings','Панель':'panel','Помощь':'help'}[text]
                chunks=render(c,command,1000)
                self.assertTrue(chunks)
                self.assertTrue(all(len(chunk)<=4000 for chunk in chunks))
                if command=='rdp':self.assertIn('DOMAIN\\user1','\n'.join(chunks))
                if command=='report':self.assertIn('24 часа',chunks[0])
        queue_update(application.db,self.update(),123,set(),self.limiter,1000)
        flush(application.db,lambda *args:self.sent.append(args),1000)
        self.assertEqual(len(self.sent),1)
        self.assertEqual(self.sent[0][0],'123')
        self.assertEqual(self.sent[0][2],KEYBOARD)
        self.assertIn('SQL-PC',self.sent[0][1])

    def test_unauthorized_chat_user_old_message_and_duplicate(self):
        queue_update(application.db,self.update(1,chat=999),123,set(),self.limiter,1000)
        queue_update(application.db,self.update(2,user=9),123,{'5'},self.limiter,1000)
        queue_update(application.db,self.update(3,date=0),123,set(),self.limiter,1000)
        queue_update(application.db,self.update(4),123,set(),self.limiter,1000)
        queue_update(application.db,self.update(4),123,set(),self.limiter,1000)
        with application.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM bot_replies').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT value FROM bot_state WHERE name='offset'").fetchone()[0],'5')

    def test_partial_reply_retries_unsent_part_and_cursor_persists(self):
        queue_update(application.db,self.update(),123,set(),self.limiter,1000)
        with application.db() as c:
            c.execute('UPDATE bot_replies SET parts=?',(json.dumps(['one','two']),))
        sent=[]
        def sender(chat,text,keyboard):
            if text=='two':raise DeliveryError(120)
            sent.append(text)
        flush(application.db,sender,1000)
        self.assertEqual(sent,['one'])
        self.assertFalse(flush(application.db,lambda *args:sent.append(args[1]),1060))
        flush(application.db,lambda *args:sent.append(args[1]),1120)
        self.assertEqual(sent,['one','two'])
        flush(application.db,lambda *args:sent.append(args[1]),1121)
        self.assertEqual(sent,['one','two'])

    def test_antiflood_and_expired_outbox(self):
        for identifier in range(1,8):
            queue_update(application.db,self.update(identifier),123,set(),self.limiter,1000)
        with application.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM bot_replies').fetchone()[0],3)
        self.assertFalse(flush(application.db,lambda *args:self.sent.append(args),1601))
        self.assertEqual(self.sent,[])

    def test_health_and_chunks(self):
        from server.bot_health import health_page
        with application.db() as c:
            self.assertIn('Бот ещё не запущен',health_page(c,1000))
            state(c,'heartbeat',1000);state(c,'last_poll',1000)
            self.assertIn('Бот работает',health_page(c,1000))
            self.assertIn('Нет свежего состояния',health_page(c,1300))
        self.assertEqual(''.join(split_text('x'*9000)), 'x'*9000)

    def test_daemon_poll_commands_watchdog_and_graceful_stop(self):
        import signal
        from unittest.mock import patch
        from server.bot import main
        callbacks={};messages=[];polls=[0];notifications=[]
        def register(sig,callback):callbacks[sig]=callback
        def transport(token,method,payload):
            if method=='setMyCommands':return True
            if method=='sendMessage':
                messages.append(payload);return {'message_id':len(messages)}
            if method=='getUpdates':
                polls[0]+=1
                if polls[0]==1:return [self.update(10,text='Статус',date=1000)]
                if polls[0]==2:return [self.update(11,text='RDP',date=1000)]
                callbacks[signal.SIGTERM](signal.SIGTERM,None)
                return []
            raise AssertionError(method)
        with patch.dict('os.environ',{'STATUS_TELEGRAM_TOKEN':'dummy','STATUS_TELEGRAM_CHAT_ID':'123','STATUS_TELEGRAM_ALLOWED_USERS':''}),patch('server.bot.signal.signal',side_effect=register),patch('server.bot.telegram_request',side_effect=transport),patch('server.bot.pause'),patch('server.bot.time.time',return_value=1000),patch('server.bot.notify_systemd',side_effect=notifications.append):
            main()
        self.assertEqual(len(messages),2)
        self.assertTrue(all(message['chat_id']=='123' for message in messages))
        self.assertTrue(all(message['reply_markup']==KEYBOARD for message in messages))
        self.assertIn('DOMAIN\\user1',messages[1]['text'])
        self.assertTrue(any('READY=1' in item for item in notifications))
        self.assertIn('STOPPING=1',notifications)

    def test_bot_page_requires_login(self):
        from fastapi.testclient import TestClient
        from server.security import limiter,login_limiter
        limiter.reset();login_limiter.reset()
        client=TestClient(application.app,base_url='https://testserver')
        self.assertEqual(client.get('/bot',follow_redirects=False).status_code,303)

    def test_systemd_watchdog_datagram(self):
        import os
        import socket
        from unittest.mock import patch
        from server.bot import notify_systemd
        if os.name!='posix':self.skipTest('systemd socket is Linux-only')
        address=str(Path(self.temp.name)/'notify.sock')
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as receiver:
            receiver.bind(address);receiver.settimeout(1)
            with patch.dict(os.environ,{'NOTIFY_SOCKET':address}):
                notify_systemd('READY=1\nWATCHDOG=1')
            self.assertEqual(receiver.recv(100),b'READY=1\nWATCHDOG=1')
