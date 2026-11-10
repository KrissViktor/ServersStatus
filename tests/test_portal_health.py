import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import test_snapshots as fixtures
from server import app as a
from server.portal_backup import begin,execute,note
from server.portal_health import snapshot,systemd_snapshot,systemd_time


class PortalHealthTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.HistoricalSnapshotsTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client;self.fixture.report()

    def test_verified_online_backup_duplicate_guard_and_file_state(self):
        run=begin(a.db);self.assertIsNotNone(run);self.assertIsNone(begin(a.db))
        folder=Path(self.fixture.tmp.name)/'backups'
        self.assertTrue(execute(a.db,a.DB,run,folder))
        with a.db() as c:
            data=snapshot(c,a.DB);saved=data['backup'];self.assertTrue(saved['file_present']);self.assertTrue(saved['size_matches'])
        path=Path(saved['path']);self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),saved['sha256'])
        if os.name!='nt':self.assertEqual(path.stat().st_mode&0o777,0o600)
        c=sqlite3.connect(path)
        try:self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0],'ok');self.assertEqual(c.execute("SELECT COUNT(*) FROM agents WHERE id='pc'").fetchone()[0],1)
        finally:c.close()
        with path.open('ab') as stream:stream.write(b'changed')
        with a.db() as c:self.assertFalse(snapshot(c,a.DB)['backup']['size_matches'])

    def test_failed_backup_and_task_heartbeat(self):
        bad=Path(self.fixture.tmp.name)/'bad.sqlite3';bad.write_bytes(b'not a sqlite database')
        run=begin(a.db);self.assertFalse(execute(a.db,bad,run,Path(self.fixture.tmp.name)/'output'))
        with a.db() as c:
            note(c,'events',now=time.time())
            data=snapshot(c,a.DB);self.assertEqual(data['recent_backups'][0]['status'],'failed');self.assertEqual(data['tasks'][0]['name'],'events');self.assertIsNone(data['backup'])
        self.assertEqual(list((Path(self.fixture.tmp.name)/'output').glob('*.partial')),[])

    def test_portal_page_and_csrf_start(self):
        with patch('server.portal_health.systemd_snapshot',return_value={'available':False,'items':[]}):
            response=self.client.get('/portal-health');self.assertEqual(response.status_code,200)
            self.assertIn('Нет зарегистрированных копий',response.text);self.assertIn('systemd недоступно',response.text)
        self.assertEqual(self.client.post('/portal-health/backup',data={'csrf':'bad'}).status_code,403)
        with patch('server.portal_backup.launch',return_value=True) as launch:
            response=self.client.post('/portal-health/backup',data={'csrf':a.digest('agent-management:test')},follow_redirects=False)
            self.assertEqual(response.status_code,303);launch.assert_called_once()
        with patch('server.portal_backup.launch',return_value=False):self.assertEqual(self.client.post('/portal-health/backup',data={'csrf':a.digest('agent-management:test')}).status_code,409)

    def test_systemd_observations_are_parsed_without_commands_or_secrets(self):
        from types import SimpleNamespace
        text='Id=serversstatus.service\nLoadState=loaded\nActiveState=active\nSubState=running\n\nId=unexpected.service\nActiveState=failed\n'
        with patch('server.portal_health.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=text)) as run:
            result=systemd_snapshot();self.assertTrue(result['available']);self.assertEqual(len(result['items']),1)
            self.assertEqual(run.call_args.kwargs['timeout'],4)
            self.assertNotIn('Environment',str(run.call_args.args))
        self.assertIn('03:00',systemd_time('Wed 2026-11-11 00:00:00 UTC'))
        self.assertEqual(systemd_time('n/a'),'Нет данных')
