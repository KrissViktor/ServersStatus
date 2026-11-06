from datetime import datetime,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from server import app as application
from server.events import process_events
from server.daily import MSK,deliver_daily
from server.notifications import DeliveryError

class OperationsTest(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        previous=application.DB
        self.addCleanup(setattr,application,'DB',previous)
        application.DB=str(Path(self.directory.name)/'operations.sqlite3')
        with application.db() as c:
            c.execute('INSERT INTO agents VALUES (?,?)',('pc','token'))
        self.sent=[]

    def report(self,when,status='running'):
        data={'hostname':'SQL-PC','cpu_percent':20,'memory_percent':50,'disks':[],
              'services':[{'name':'MSSQLSERVER','status':status}], 'backups':[]}
        with application.db() as c:
            c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',when,json.dumps(data)))

    def test_event_transitions_dedup_and_offline(self):
        self.report(1000,'stopped')
        process_events(application.db,1000)
        process_events(application.db,1060)
        with application.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],1)
        self.report(1100)
        process_events(application.db,1100)
        process_events(application.db,1300)
        with application.db() as c:
            rows=c.execute('SELECT * FROM events ORDER BY id').fetchall()
        self.assertEqual([r['level'] for r in rows],['warning','info','warning'])
        self.assertIn('Восстановлено',rows[1]['message'])
        self.assertIn('нет связи',rows[2]['message'])

    def test_daily_calendar_period_and_no_duplicate(self):
        now=datetime(2026,11,7,9,tzinfo=MSK).timestamp()
        self.report(datetime(2026,11,6,12,tzinfo=MSK).timestamp())
        with patch.dict('os.environ',{'STATUS_DAILY_REPORT_ENABLED':'1','STATUS_DAILY_REPORT_HOUR':'9'}):
            self.assertEqual(deliver_daily(application.db,self.sent.append,now-60),(0,0))
            self.assertEqual(deliver_daily(application.db,self.sent.append,now),(1,0))
            self.assertIn('06.11.2026',self.sent[0])
            self.assertIn('CPU ср. 20.0%',self.sent[0])
            self.assertEqual(deliver_daily(application.db,self.sent.append,now+60),(0,0))

    def test_daily_partial_failure_resumes_unsent_chunk(self):
        now=datetime(2026,11,7,9,tzinfo=MSK).timestamp()
        calls=[]
        def sender(text):
            calls.append(text)
            if text=='part two':raise DeliveryError(120)
        with patch.dict('os.environ',{'STATUS_DAILY_REPORT_ENABLED':'1','STATUS_DAILY_REPORT_HOUR':'9'}),patch('server.daily.build_summary',return_value=['part one','part two']):
            self.assertEqual(deliver_daily(application.db,sender,now),(1,1))
            self.assertEqual(deliver_daily(application.db,self.sent.append,now+60),(0,0))
            self.assertEqual(deliver_daily(application.db,self.sent.append,now+120),(1,0))
            self.assertEqual(self.sent,['part two'])
            self.assertEqual(deliver_daily(application.db,self.sent.append,now+180),(0,0))
