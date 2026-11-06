from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from server import app as application
from server.delivery_policy import MSK,delivery_window
from server.notifications import tick
from server.daily import deliver_daily

def timestamp(day,hour,minute=0):
    return datetime(2026,11,day,hour,minute,tzinfo=MSK).timestamp()


class DeliveryPolicyTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous=application.DB
        self.addCleanup(setattr,application,'DB',previous)
        application.DB=str(Path(self.temp.name)/'policy.sqlite3')
        with application.db() as c:
            c.execute('INSERT INTO agents VALUES (?,?)',('pc','token'))
        self.sent=[]

    def report(self,now,used=0,status='running'):
        data={'hostname':'PC','disks':[{'path':'C:','used_percent':used}], 'services':[{'name':'SQL','status':status}], 'cpu_percent':10,'memory_percent':20}
        with application.db() as c:
            c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',now,json.dumps(data)))

    def test_weekday_and_weekend_boundaries(self):
        for day,start in [(6,8),(7,12),(8,12),(9,8)]:
            self.assertFalse(delivery_window(timestamp(day,start-1,59)))
            self.assertTrue(delivery_window(timestamp(day,start)))
            self.assertTrue(delivery_window(timestamp(day,19,59)))
            self.assertFalse(delivery_window(timestamp(day,20)))
            self.assertFalse(delivery_window(timestamp(day,23)))

    def test_quiet_hours_hold_current_incident_and_dont_replay_resolved(self):
        night=timestamp(6,7,59)
        self.report(night,status='stopped')
        self.assertEqual(tick(application.db,self.sent.append,night),(0,0))
        opening=timestamp(6,8)
        self.report(opening,status='stopped')
        self.assertEqual(tick(application.db,self.sent.append,opening),(1,0))
        self.assertEqual(tick(application.db,self.sent.append,opening),(0,0))
        # Recovery waits for allowed hours too.
        evening=timestamp(6,20)
        self.report(evening)
        self.assertEqual(tick(application.db,self.sent.append,evening),(0,0))
        weekend=timestamp(7,12)
        self.report(weekend)
        self.assertEqual(tick(application.db,self.sent.append,weekend),(1,0))
        self.assertIn('ВОССТАНОВЛЕНО',self.sent[-1])

    def test_disk_98_boundary_and_dedup(self):
        now=timestamp(6,10)
        self.report(now,97.99)
        self.assertEqual(tick(application.db,self.sent.append,now),(0,0))
        self.report(now+1,98)
        self.assertEqual(tick(application.db,self.sent.append,now+1),(1,0))
        self.report(now+2,99)
        self.assertEqual(tick(application.db,self.sent.append,now+2),(0,0))
        self.report(now+3,97)
        self.assertEqual(tick(application.db,self.sent.append,now+3),(1,0))
        self.assertIn('ВОССТАНОВЛЕНО',self.sent[-1])

    def test_old_disk_warning_does_not_send_false_recovery_on_upgrade(self):
        from server.incidents import evaluate
        now=timestamp(6,10)
        self.report(now,90)
        with application.db() as c:
            rows=c.execute('SELECT id,? AS received,? AS data FROM agents',(now,json.dumps({'disks':[{'path':'C:','used_percent':90}]}))).fetchall()
        incidents,_,_=evaluate(rows,[],now)
        key=next(iter(incidents))
        with application.db() as c:
            c.execute('CREATE TABLE telegram_state(key TEXT PRIMARY KEY,agent TEXT,body TEXT,active INTEGER,sent INTEGER,next_attempt REAL DEFAULT 0)')
            c.execute('INSERT INTO telegram_state VALUES (?,?,?,1,1,0)',(key,'pc','Old disk 90%'))
        self.assertEqual(tick(application.db,self.sent.append,now),(0,0))
        self.assertEqual(self.sent,[])

    def test_weekend_daily_report_delayed_until_noon(self):
        now=timestamp(7,9)
        self.report(now)
        with patch.dict('os.environ',{'STATUS_DAILY_REPORT_ENABLED':'1','STATUS_DAILY_REPORT_HOUR':'9'}):
            self.assertEqual(deliver_daily(application.db,self.sent.append,now),(0,0))
            self.assertEqual(deliver_daily(application.db,self.sent.append,timestamp(7,12)),(1,0))
            self.assertEqual(deliver_daily(application.db,self.sent.append,timestamp(7,13)),(0,0))
