import json
import time
import unittest
import test_access_roles as fixtures
from server import app as a
from server.portal_settings import retention_days
from server.retention import cleanup
from server.observability import cells,store_boots
from server.dependencies import impacted
from server.news import sync


class ObservatoryTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AccessRolesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.clients=self.fixture.clients;self.csrf=a.digest('agent-management:admin')

    def test_superadmin_only_retention_and_actual_cleanup(self):
        for name in ['reader','operator']:
            self.assertEqual(self.clients[name].get('/portal-settings').status_code,403)
            self.assertEqual(self.clients[name].post('/portal-settings',data={'retention_days':'7','csrf':a.digest('agent-management:'+name),'confirm_shorter':'yes'}).status_code,403)
        admin=self.clients['admin'];self.assertEqual(admin.get('/portal-settings').status_code,200)
        self.assertEqual(admin.post('/portal-settings',data={'csrf':self.csrf,'retention_days':'7'}).status_code,400)
        with a.db() as c:self.assertEqual(retention_days(c),186)
        response=admin.post('/portal-settings',data={'csrf':self.csrf,'retention_days':'7','confirm_shorter':'yes'},follow_redirects=False);self.assertEqual(response.status_code,303)
        now=time.time()
        with a.db() as c:
            self.assertEqual(retention_days(c),7)
            for timestamp in [now-10*86400,now-3*86400]:c.execute('INSERT INTO reports VALUES (?,?,?)',('pc',timestamp,json.dumps(self.fixture.report)))
            c.execute("INSERT INTO events(received,agent,category,level,message) VALUES (?,'pc','test','info','old')",(now-10*86400,))
            old_boot={'source':'System','record_id':99,'at':now-10*86400,'event_id':6005,'kind':'boot'}
            store_boots(c,'pc',{'reboot_history':{'status':'available','events':[old_boot]}})
            self.assertEqual(c.execute('SELECT COUNT(*) FROM server_boot_events').fetchone()[0],0)
            cleanup(c,now)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reports WHERE received<?',(now-7*86400,)).fetchone()[0],0)
            self.assertIsNotNone(c.execute("SELECT 1 FROM current_reports WHERE agent='pc'").fetchone())
            self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE message='old'").fetchone()[0],0)
        self.assertIn('7 дней',admin.get('/history/pc').text)
        self.assertIn('7 дней',admin.get('/ai').text)

    def test_heatmap_unobserved_days_are_unknown_and_gaps_reduce_percent(self):
        with a.db() as c:
            c.execute("INSERT INTO agents VALUES ('other','unused')")
            c.execute('INSERT INTO reports VALUES (?,?,?)',('other',86500,json.dumps(self.fixture.report)))
            result=cells(c,'other',0,172800,2)
            self.assertIsNone(result[0]['percent']);self.assertGreater(result[1]['percent'],0);self.assertLess(result[1]['percent'],1)
        response=self.clients['admin'].get('/heatmap?days=7');self.assertEqual(response.status_code,200);self.assertIn('heat-cell',response.text)
        self.assertEqual(self.clients['reader'].get('/heatmap').status_code,403)
        self.assertEqual(self.clients['admin'].get('/heatmap?days=3650').status_code,400)

    def test_timeline_merges_sources_without_console_and_deduplicates_windows(self):
        now=time.time();data={**self.fixture.report,'reboot_history':{'status':'available','events':[{'event_id':41,'record_id':1,'at':now-30,'source':'Microsoft-Windows-Kernel-Power','kind':'unexpected','message':'reboot-proof'}]}}
        for _ in range(2):self.clients['admin'].post('/api/report/pc',headers={'Authorization':'Bearer key'},json=data)
        with a.db() as c:
            c.execute("INSERT INTO events(received,agent,category,level,message) VALUES (?,'pc','console','info','PRIVATE-CONSOLE')",(now,))
            c.execute("INSERT INTO events(received,agent,category,level,message) VALUES (?,'pc','configuration','info','profile-proof')",(now,))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM server_boot_events').fetchone()[0],1)
        html=self.clients['admin'].get('/timeline/pc').text
        self.assertIn('reboot-proof',html);self.assertIn('profile-proof',html);self.assertNotIn('PRIVATE-CONSOLE',html);self.assertNotIn('PRIVATE',html)
        self.assertEqual(self.clients['admin'].get('/timeline/missing').status_code,404)

    def test_dependency_cycle_impact_csrf_and_role_checks(self):
        with a.db() as c:c.execute("INSERT INTO agents VALUES ('sql','unused')")
        form={'csrf':self.csrf,'mode':'save','dependent':'pc','provider':'sql','label':'SQL <script>'}
        self.assertEqual(self.clients['admin'].post('/dependencies',data=form,follow_redirects=False).status_code,303)
        self.assertEqual(self.clients['admin'].post('/dependencies',data={**form,'csrf':'wrong'}).status_code,403)
        self.assertEqual(self.clients['reader'].post('/dependencies',data=form).status_code,403)
        self.assertEqual(self.clients['admin'].post('/dependencies',data={**form,'provider':'pc'}).status_code,400)
        html=self.clients['admin'].get('/dependencies').text
        self.assertIn('SQL &lt;script&gt;',html);self.assertIn('dependency-diagram',html)
        edges=[{'dependent':'pc','provider':'sql'},{'dependent':'sql','provider':'pc'}]
        self.assertEqual(impacted(edges,{'sql'}),{'pc'})

    def test_news_restore_is_idempotent_and_viewer_can_read(self):
        with a.db() as c:
            before=c.execute('SELECT COUNT(*) FROM portal_news').fetchone()[0];self.assertGreaterEqual(before,122)
            self.assertGreaterEqual(sum(len(json.loads(row[0])) for row in c.execute('SELECT tags FROM portal_news')),82)
            sync(c);self.assertEqual(c.execute('SELECT COUNT(*) FROM portal_news').fetchone()[0],before)
        response=self.clients['reader'].get('/news');self.assertEqual(response.status_code,200);self.assertIn('записей из Git',response.text)
        with a.db() as c:self.assertIsNotNone(c.execute("SELECT 1 FROM portal_news_seen WHERE username='reader'").fetchone())
        self.assertEqual(self.clients['reader'].get('/news?category=bad').status_code,400)

    def test_wallboard_is_current_only_and_table_has_safe_rows(self):
        response=self.clients['reader'].get('/api/wallboard');self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['items'][0]['id'],'pc');self.assertNotIn('PRIVATE',response.text);self.assertNotIn('token',response.text)
        self.assertEqual(self.clients['reader'].get('/wallboard').status_code,200)
        self.assertIn('data-table-server-id="pc"',self.clients['reader'].get('/').text)
        self.clients['reader'].cookies.clear();self.assertEqual(self.clients['reader'].get('/api/wallboard').status_code,401)
