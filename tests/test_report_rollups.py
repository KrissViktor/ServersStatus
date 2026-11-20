import json
from contextlib import contextmanager
from math import inf, nextafter
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from server.history import load_history
from server.report_rollup_jobs import enqueue_automatic, enqueue_manual, process_one
from server.report_rollups import DAY, SCHEMA, availability, history_points, metrics, midnight, raw_metrics
from server.stability import load


class ReportRollupsTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)/'rollups.sqlite3'
        self.today = midnight(time.time())
        self.day = self.today-3*DAY
        with self.db() as c:
            c.executescript("""
                CREATE TABLE agents(id TEXT PRIMARY KEY);
                CREATE TABLE reports(agent TEXT,received REAL,data TEXT);
                CREATE INDEX reports_agent_time ON reports(agent,received);
                CREATE INDEX reports_resource_metrics ON reports(agent,received,
                    json_extract(data,'$.cpu_percent'),json_extract(data,'$.memory_percent'));
                CREATE VIEW current_reports AS SELECT agent,received,data FROM reports ORDER BY received DESC;
                INSERT INTO agents VALUES ('pc');
            """+SCHEMA)
            seconds = [-120, -10, 0, 10, 900, DAY-10, DAY, DAY+10, 2*DAY-900, 2*DAY+300]
            for index, offset in enumerate(seconds):
                data = {'cpu_percent':index,'memory_percent':20+index,
                        'uptime_seconds':offset+2000 if offset<DAY else offset-DAY+1,
                        'system':{'memory_total_bytes':1000000,'memory_used_bytes':index*1000}}
                c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',self.day+offset,json.dumps(data)))

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def drain(self):
        for _ in range(12):
            if not process_one(self.db):
                return
        self.fail('Rollup jobs did not finish')

    def test_cached_and_raw_intervals_match(self):
        with self.db() as c:
            enqueue_manual(c,self.day,self.day+DAY,time.time())
        self.drain()
        with self.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM report_rollups').fetchone()[0],2)
            for start,end in [
                (self.day,self.day+DAY),
                (self.day-60,self.day+2*DAY+600),
                (self.day,self.day+2*DAY),
                (self.day,nextafter(self.day+2*DAY,-inf)),
            ]:
                expected = raw_metrics(c,'pc',start,end)
                actual = metrics(c,'pc',start,end)
                self.assertEqual(actual['n'],expected['n'])
                self.assertEqual(actual['cpu_sum'],expected['cpu_sum'])
                self.assertEqual(actual['ram_max'],expected['ram_max'])
                expected_up = load(c,'pc',start,end)
                actual_up = availability(c,'pc',start,end)
                self.assertEqual(actual_up,expected_up)
                for bucket in (300,1800,3900):
                    raw = [dict(row) for row in load_history(c,'pc',start,end,bucket)]
                    self.assertEqual(history_points(c,'pc',start,end,bucket),raw)
            with patch('server.report_rollups.raw_metrics',side_effect=AssertionError('Closed day must use the cache')):
                self.assertGreater(metrics(c,'pc',self.day,self.day+DAY)['n'],0)

    def test_schedule_and_manual_rebuild_keep_published_result(self):
        enqueue_automatic(self.db,self.today+3599)
        with self.db() as c:
            self.assertEqual(c.execute('SELECT MAX(day) FROM report_rollup_jobs').fetchone()[0],self.today-2*DAY)
        enqueue_automatic(self.db,self.today+3600)
        with self.db() as c:
            self.assertEqual(c.execute('SELECT MAX(day) FROM report_rollup_jobs').fetchone()[0],self.today-DAY)
        self.drain()
        with self.db() as c:
            before = c.execute('SELECT built FROM report_rollups WHERE agent=? AND day=?',('pc',self.day)).fetchone()[0]
            enqueue_manual(c,self.day,self.day,self.today+7200)
            self.assertGreater(metrics(c,'pc',self.day,self.day+DAY)['n'],0)
        self.drain()
        with self.db() as c:
            after = c.execute('SELECT built FROM report_rollups WHERE agent=? AND day=?',('pc',self.day)).fetchone()[0]
            self.assertGreater(after,before)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM report_rollups WHERE day=?',(self.day,)).fetchone()[0],1)
