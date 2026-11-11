"""Проверки центра проблем и защиты от раскрытия закрытых событий."""
import json
import re
import time
import unittest
import test_access_roles as fixtures
from server import app as a
from server.dependencies import diagram
from server.windows_ui import section


class InterfaceNavigationTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AccessRolesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.clients['admin'];self.csrf=a.digest('agent-management:admin')

    def test_problem_center_acknowledges_one_episode_and_returns_to_active_view(self):
        report={**self.fixture.report,'cpu_percent':99,'memory_percent':98}
        self.assertEqual(self.client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=report).status_code,200)
        with a.db() as c:
            c.execute('INSERT INTO agent_profiles VALUES (?,?)',('pc','Склад SQL'))
        active=self.client.get('/problems?view=active&q=Склад&category=cpu_percent')
        self.assertEqual(active.status_code,200)
        self.assertEqual(active.text.count('class="server acknowledgement-card"'),1)
        with a.db() as c:incident=c.execute("SELECT id FROM incident_history WHERE category='cpu_percent' AND closed IS NULL").fetchone()[0]
        marked=self.client.post('/problems/acknowledge',data={'csrf':self.csrf,'incident':incident,'return_to':'/problems?view=active'},follow_redirects=False)
        self.assertEqual(marked.status_code,303);self.assertEqual(marked.headers['location'],'/problems?view=active')
        self.assertEqual(self.client.get('/problems?view=active&category=cpu_percent').text.count('class="server acknowledgement-card"'),0)
        self.assertEqual(self.client.get('/problems').text.count('class="server acknowledgement-card"'),1)
        self.assertEqual(self.client.get('/problems?view=active&category=memory_percent').text.count('class="server acknowledgement-card"'),1)
        self.assertEqual(self.fixture.clients['reader'].get('/problems?view=active').status_code,403)
        self.assertEqual(self.client.get('/problems?view=invalid').status_code,400)

    def test_event_filters_keep_console_and_user_events_private(self):
        with a.db() as c:
            c.execute('INSERT INTO agent_profiles VALUES (?,?)',('pc','Офис SQL'))
            c.executemany('INSERT INTO events(received,agent,category,level,message) VALUES (?,?,?,?,?)',[(time.time(),'pc',category,'info',message) for category,message in [('service','Перезапуск SQL'),('service','Проверка DNS'),('console','PRIVATE CONSOLE'),('users','PRIVATE USERS')]])
        operator=self.fixture.clients['operator']
        response=operator.get('/events?q=перезапуск&category=service&agent=pc')
        self.assertEqual(response.status_code,200);self.assertIn('Перезапуск SQL',response.text);self.assertNotIn('Проверка DNS',response.text)
        self.assertIn('Офис SQL',response.text)
        for category,message in [('console','PRIVATE CONSOLE'),('users','PRIVATE USERS')]:
            response=operator.get('/events',params={'category':category,'q':'PRIVATE'})
            self.assertEqual(response.status_code,200);self.assertNotIn(message,response.text)
            self.assertNotIn('value="'+category+'"',response.text)
        self.assertEqual(self.client.get('/events',params={'q':'x'*201}).status_code,400)

    def test_dependency_seed_roundtrips_names_without_closing_script(self):
        name='SQL </script><script>alert(1)</script>'
        html=diagram([{'id':'sql<1','name':name,'received':time.time()}],[])
        seed=re.search(r'<script type="application/json" id="dependency-seed">(.*?)</script>',html,re.S)[1]
        self.assertNotIn('<',seed);self.assertEqual(json.loads(seed)['nodes'],[{'id':'sql<1','name':name}])

    def test_windows_reboot_state_has_correct_severity(self):
        for value,color in [(False,'normal'),(True,'warning'),(None,'neutral')]:
            html=section({'windows_updates':{'reboot_required':value}})
            self.assertIn('class="status-note '+color+'"',html)
            self.assertNotIn('class="notice"',html)
