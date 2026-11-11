import json
import re
import time
import unittest
from html.parser import HTMLParser
import test_access_roles as fixtures
from server import app as a


class HeaderParser(HTMLParser):
    def __init__(self):super().__init__();self.depth=0;self.navigation_depths=[]
    def handle_starttag(self,tag,attrs):
        if tag=='header':self.depth+=1
        if tag=='nav' and dict(attrs).get('class')=='portal-navigation':self.navigation_depths.append(self.depth)
    def handle_endtag(self,tag):
        if tag=='header':self.depth-=1


class InterfaceWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AccessRolesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.clients['admin'];self.csrf=a.digest('agent-management:admin')

    def test_navigation_outside_nested_news_header_and_role_scoped(self):
        html=self.client.get('/').text
        parser=HeaderParser();parser.feed(html)
        self.assertEqual(parser.navigation_depths,[0])
        self.assertIn('portal-navigation-mobile',html)
        self.assertIn('data-primary-page="/updates"',html)
        reader=self.fixture.clients['reader'].get('/').text
        self.assertNotIn('data-primary-page="/updates"',reader)
        self.assertIn('data-primary-page="/wallboard"',reader)

    def test_check_slot_identity_survives_removing_other_checks(self):
        response=self.client.post('/checks/pc',data={'csrf':self.csrf,'name_2':'ERP','kind_2':'tcp','target_2':'erp.local','port_2':'443'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        html=self.client.get('/checks/pc').text
        slot=re.search(r'<fieldset[^>]*data-check-slot="2"[^>]*>',html).group(0)
        self.assertNotIn('hidden',slot)
        self.assertIn('hidden',re.search(r'<fieldset[^>]*data-check-slot="0"[^>]*>',html).group(0))
        self.assertIn('data-add-check',html);self.assertIn('data-form-state',html)
        self.assertIn('data-check-field="contains"',html)
        with a.db() as c:
            saved=json.loads(c.execute("SELECT data FROM application_check_config WHERE agent='pc'").fetchone()[0])
            self.assertEqual(saved[0]['id'],'check-2')

    def test_update_rows_prioritize_running_and_failed_tasks(self):
        with a.db() as c:
            package=c.execute("INSERT INTO update_packages(platform,version,sha256,size,path) VALUES ('windows-x64','v2','test-hash',1,'/unused')").lastrowid
            for agent,status in [('pc','applied'),('running','running'),('failure','failed')]:
                if agent!='pc':c.execute('INSERT INTO agents VALUES (?,?)',(agent,'unused'))
                c.execute('INSERT INTO agent_update_jobs(agent,package,status,message,created,updated) VALUES (?,?,?,?,?,?)',(agent,package,status,'state',time.time(),time.time()))
        html=self.client.get('/updates').text
        self.assertLess(html.index('data-update-card="running"'),html.index('data-update-card="failure"'))
        self.assertLess(html.index('data-update-card="failure"'),html.index('data-update-card="pc"'))
        self.assertIn('data-update-brief',html);self.assertIn('data-update-search',html)
        self.assertNotIn('open',re.search(r'<details class="server update-bulk-actions"[^>]*>',html).group(0))

    def test_density_and_monitoring_forms_have_shared_controls(self):
        html=self.client.get('/').text
        self.assertIn('data-density="compact"',html);self.assertIn('data-density="normal"',html)
        html=self.client.get('/settings/pc').text
        self.assertIn('data-dirty-form',html);self.assertIn('class="form-actions"',html)
