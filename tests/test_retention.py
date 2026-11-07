import json
from pathlib import Path
import tempfile
import unittest
from server import app as application
from server.retention import RETENTION_DAYS,cleanup

class RetentionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous=application.DB
        self.addCleanup(setattr,application,'DB',previous)
        application.DB=str(Path(self.temp.name)/'retention.sqlite3')

    def test_six_month_boundary_and_30_day_history_survives(self):
        now=200*86400
        cutoff=now-RETENTION_DAYS*86400
        with application.db() as c:
            for timestamp in (cutoff-1,cutoff,now-180*86400,now-31*86400,now):
                c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',timestamp,json.dumps({'cpu_percent':1,'memory_percent':2})))
            self.assertEqual(cleanup(c,now),1)
            actual=[r[0] for r in c.execute('SELECT received FROM reports ORDER BY received')]
            self.assertEqual(actual,[cutoff,now-180*86400,now-31*86400,now])
            self.assertEqual(cleanup(c,now+1),0)

    def test_cleanup_is_bounded_and_catches_up_in_batches(self):
        from unittest.mock import patch
        now=200*86400
        with application.db() as c:
            c.executemany('INSERT INTO reports VALUES (?,?,?)',[('pc',0,'{}')]*5)
            with patch('server.retention.CLEANUP_BATCH',2):
                self.assertEqual(cleanup(c,now),2)
                self.assertEqual(cleanup(c,now+1),0)
                self.assertEqual(cleanup(c,now+60),2)
                self.assertEqual(cleanup(c,now+120),1)
            self.assertEqual(c.execute('SELECT count(*) FROM reports').fetchone()[0],0)
