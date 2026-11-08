import json
import re
import time
from unittest.mock import patch
import unittest
import test_update_versions as fixtures


class BulkUpdateTest(unittest.TestCase):
    def add_agent(self,name,**changes):
        data={**self.data,**changes}
        with a.db() as c:
            c.execute('INSERT INTO agents VALUES (?,?)',(name,a.digest(name)))
            c.execute('INSERT INTO latest_reports VALUES (?,?,?)',(name,time.time(),json.dumps(data)))

    def setUp(self):
        fixtures.UpdatePageTest.setUp(self)
        self.csrf=re.search('name="csrf" value="([^"]+)"',self.client.get('/updates').text).group(1)

    def submit(self,**changes):
        return self.client.post('/updates/all/latest',data={'csrf':self.csrf,'confirm':'yes',**changes},follow_redirects=False)

    def test_platform_selection_skips_and_repeat_are_safe(self):
        self.add_agent('linux',agent_platform='linux-source',agent_version='linux-old')
        self.add_agent('current',agent_version='newest')
        self.add_agent('unknown',agent_version='unlisted-version')
        self.add_agent('ahead',agent_version='future')
        self.add_agent('offline');self.add_agent('busy');self.add_agent('console');self.add_agent('windows')
        self.add_agent('portal',agent_platform='portal');self.add_agent('legacy',features=[])
        with a.db() as c:
            c.execute('INSERT INTO update_packages VALUES (10,?,?,?,?,?)',('linux-source','linux-old','a'*64,10,'fake'))
            c.execute('INSERT INTO update_packages VALUES (11,?,?,?,?,?)',('linux-source','linux-new','b'*64,10,'fake'))
            c.execute('INSERT INTO update_package_dates VALUES (10,1700000100,1700000100)')
            c.execute('INSERT INTO update_package_dates VALUES (11,1700000500,1700000500)')
            c.execute("UPDATE latest_reports SET received=0 WHERE agent='offline'")
            c.execute("INSERT INTO agent_update_jobs(agent,package,status,created,updated) VALUES ('busy',4,'running',?,?)",(time.time(),time.time()))
            # Populate real command schemas without executing anything.
            c.execute("INSERT INTO console_jobs(agent,status,created) VALUES ('console','uncertain',?)",(time.time(),))
            c.execute("INSERT INTO windows_commands(agent,action,status,created) VALUES ('windows','updates','queued',?)",(time.time(),))
        with patch('server.github_updates.sync') as sync,patch('server.update_versions.commit_date',side_effect=lambda v:1700001000 if v=='future' else None):
            response=self.submit()
            self.assertEqual(response.status_code,303);sync.assert_called_once_with(a.db)
            location=response.headers['location'];self.assertIn('queued=2',location);self.assertIn('busy=3',location)
            self.assertIn('unknown=1',location);self.assertIn('current=2',location);self.assertIn('offline=1',location);self.assertIn('unsupported=2',location)
            result=self.client.get(location);self.assertIn('Задач создано: <b>2</b>',result.text)
            again=self.submit();self.assertIn('queued=0',again.headers['location'])
        with a.db() as c:
            rows=c.execute("SELECT agent,package FROM agent_update_jobs WHERE agent!='busy' ORDER BY agent").fetchall()
            self.assertEqual([tuple(row) for row in rows],[('linux',11),('pc',4)])
            self.assertEqual(c.execute('SELECT count(*) FROM update_job_context').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT count(*) FROM update_job_events').fetchone()[0],2)

    def test_failed_catalog_check_creates_no_jobs(self):
        with patch('server.github_updates.sync',side_effect=OSError('private diagnostic')):
            response=self.submit()
        self.assertEqual(response.status_code,502);self.assertNotIn('private diagnostic',response.text)
        with a.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM agent_update_jobs').fetchone()[0],0)

    def test_csrf_confirmation_and_current_viewer_cannot_enqueue(self):
        with patch('server.github_updates.sync') as sync:
            self.assertEqual(self.submit(csrf='wrong').status_code,403)
            self.assertEqual(self.submit(confirm='no').status_code,400)
            with a.db() as c:
                c.execute("INSERT INTO users VALUES ('reader',?,?)",('00'*16,'0'*128))
                c.execute("UPDATE session_users SET name='reader'")
            self.assertEqual(self.submit().status_code,403);sync.assert_not_called()
        self.client.cookies.clear()
        self.assertEqual(self.submit().status_code,401)


from server import app as a
