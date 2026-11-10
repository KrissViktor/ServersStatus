import json
import time
import unittest
import test_snapshots as fixtures
from server import app as a


class FleetTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.HistoricalSnapshotsTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.client;self.csrf=a.digest('agent-management:test')

    def test_group_membership_filter_comparison_and_daily(self):
        self.fixture.report()
        self.assertEqual(self.client.post('/groups',data={'csrf':self.csrf,'mode':'create','name':'SQL <office>'},follow_redirects=False).status_code,303)
        with a.db() as c:identifier=c.execute('SELECT id FROM server_groups').fetchone()[0]
        self.assertEqual(self.client.post('/groups',data={'csrf':self.csrf,'mode':'members','group':identifier,'agents':'pc'},follow_redirects=False).status_code,303)
        html=self.client.get('/',params={'group':identifier}).text
        self.assertIn('data-server-id="pc"',html);self.assertNotIn('data-server-id="other"',html)
        self.assertIn('SQL &lt;office&gt;',html)
        response=self.client.get('/compare',params={'group':identifier,'agents':'pc','period':'1h'})
        self.assertEqual(response.status_code,200);self.assertIn('comparison-chart',response.text);self.assertIn('Диски · последний отчёт',response.text)
        self.assertIn('data-server-id="pc"',response.text)
        response=self.client.get('/daily',params={'day':time.strftime('%Y-%m-%d',time.gmtime()),'group':identifier})
        self.assertEqual(response.status_code,200);self.assertIn('Изменения комплектации',response.text)
        self.assertEqual(self.client.get('/compare',params=[('agents','pc')]*7).status_code,400)
        self.assertEqual(self.client.post('/groups',data={'csrf':'bad','mode':'delete','group':identifier}).status_code,403)
        self.assertEqual(self.client.get('/daily?day=2099-01-01').status_code,400)

    def test_equipment_revisions_ignore_partial_and_volatile_reports(self):
        data=self.fixture.data
        data['hardware']={'status':'available','items':[{'kind':'board','fields':{'Product':'Board A'}}]}
        self.fixture.report();self.fixture.report()
        with a.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM equipment_history').fetchone()[0],1)
        data['hardware']['items'][0]['fields']['Product']='Board B <script>'
        self.fixture.report()
        data['hardware']['truncated']=True;data['hardware']['items']=[];self.fixture.report()
        with a.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM equipment_history').fetchone()[0],2)
        html=self.client.get('/servers/pc').text
        self.assertIn('Board A',html);self.assertIn('Board B &lt;script&gt;',html)
        self.assertIn('Было',html);self.assertIn('Стало',html)

    def test_checks_config_old_agent_compatible_and_history_transitions(self):
        form={'csrf':self.csrf,'name_0':'SQL','target_0':'127.0.0.1','port_0':'1433','kind_0':'sql'}
        self.assertEqual(self.client.post('/checks/pc',data=form,follow_redirects=False).status_code,303)
        old=self.fixture.report();self.assertNotIn('application_checks',old)
        data=self.fixture.data;data['features'].append('app_checks_v1')
        data['application_checks']={'enabled':True,'checked_at':time.time(),'items':[{'id':'check-0','name':'SQL','kind':'sql','status':'failed','message':'No response','latency_ms':30}]}
        reply=self.fixture.report();self.assertEqual(reply['application_checks']['checks'][0]['kind'],'sql')
        with a.db() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM incident_history WHERE category='application' AND closed IS NULL").fetchone()[0],1)
        data['application_checks']['items'][0]['status']='ok';self.fixture.report()
        with a.db() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM incident_history WHERE category='application' AND resolution='recovered'").fetchone()[0],1)
        self.assertEqual(self.client.post('/checks/pc',data={**form,'target_0':'https://user:secret@example.com/','kind_0':'http'}).status_code,400)

    def test_daily_delivery_contains_availability_and_service_filename_is_escaped(self):
        self.fixture.data['services']=[{'name':'SQL','status':'running','executable':'sql<script>.exe','executable_source':'configuration'}]
        self.fixture.report()
        html=self.client.get('/servers/pc').text
        self.assertIn('sql&lt;script&gt;.exe',html);self.assertIn('Из конфигурации службы',html)
        from server.daily import build_summary
        now=time.time()
        with a.db() as c:result='\n'.join(build_summary(c,now-3600,now,now))
        self.assertIn('Доступность:',result);self.assertIn('Завершилось инцидентов:',result)

    def test_status_filters_exclude_unseen_and_keep_group_search(self):
        self.fixture.report();now=time.time()
        with a.db() as c:
            c.execute('INSERT INTO reports VALUES (?,?,?)',('other',now-500,json.dumps({**self.fixture.data,'hostname':'Old SQL'})))
            c.execute("INSERT INTO agents VALUES ('waiting','unused')")
            c.execute("INSERT INTO server_groups VALUES (1,'SQL')")
            c.execute("INSERT INTO server_group_members VALUES (1,'pc')")
        online=self.client.get('/?view=online').text
        self.assertIn('data-server-id="pc"',online);self.assertNotIn('data-server-id="other"',online);self.assertNotIn('data-server-id="waiting"',online)
        offline=self.client.get('/?view=offline').text
        self.assertIn('data-server-id="other"',offline);self.assertNotIn('data-server-id="pc"',offline);self.assertNotIn('data-server-id="waiting"',offline)
        scoped=self.client.get('/?q=pc&group=1').text
        self.assertIn('href="/?q=pc&amp;group=1&amp;view=online"',scoped)
        self.assertEqual(self.client.get('/?view=online&group=1&q=other').status_code,200)

    def test_private_routes_require_login_and_viewer_cannot_write(self):
        self.client.cookies.clear()
        for url in ['/groups','/daily','/compare','/checks/pc']:
            self.assertEqual(self.client.get(url,follow_redirects=False).status_code,303)
        with a.db() as c:c.execute("UPDATE user_roles SET role='viewer' WHERE name='admin'")
        # admin is deliberately always superadmin; use a separate viewer identity.
        with a.db() as c:
            c.execute("INSERT INTO users VALUES ('viewer',?,?)",('00'*16,'0'*128));c.execute("INSERT INTO user_roles VALUES ('viewer','viewer',1)")
            c.execute("UPDATE session_users SET name='viewer'")
        self.client.cookies.set('session','test')
        self.assertEqual(self.client.post('/groups',data={'csrf':self.csrf,'mode':'create','name':'no'}).status_code,403)
        self.assertEqual(self.client.get('/compare').status_code,403)
