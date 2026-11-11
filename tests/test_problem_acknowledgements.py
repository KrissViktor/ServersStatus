import json
import time
import unittest
from unittest.mock import patch
import test_access_roles as fixtures
from server import app as a
from server.problem_acknowledgements import active
from server.incident_history import sync
from server.notifications import tick


class ProblemAcknowledgementTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AccessRolesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.clients['admin'];self.csrf=a.digest('agent-management:admin')
        self.data=dict(self.fixture.report)

    def report(self, **changes):
        self.data.update(changes)
        response=self.client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=self.data)
        self.assertEqual(response.status_code,200)

    def episode(self, category):
        self.client.get('/')
        with a.db() as c:
            row=c.execute('SELECT * FROM incident_history WHERE category=? AND closed IS NULL',(category,)).fetchone()
            self.assertIsNotNone(row)
            return dict(row)

    def acknowledge(self, episode, client=None, csrf=None):
        return (client or self.client).post('/problems/acknowledge',data={'incident':episode['id'],'csrf':csrf or self.csrf},follow_redirects=False)

    def test_only_selected_problem_hidden_until_recovery_and_recurrence(self):
        self.report(cpu_percent=96,memory_percent=97)
        episode=self.episode('cpu_percent')
        self.assertIn('Всё окей',self.client.get('/').text)
        self.assertEqual(self.acknowledge(episode).status_code,303)
        self.report(cpu_percent=99)
        html=self.client.get('/').text
        summary=html.split('<section class="problem-summary">')[1].split('</section>')[0]
        self.assertNotIn('Загрузка CPU',summary)
        self.assertIn('Занято RAM',summary)
        self.assertIn('Отмечено «Всё окей»: 1',summary)
        self.assertEqual(self.episode('cpu_percent')['id'],episode['id'])
        self.report(cpu_percent=10)
        # No page visit between recovery and the repeated problem.
        self.report(cpu_percent=98)
        repeated=self.episode('cpu_percent')
        self.assertNotEqual(repeated['id'],episode['id'])
        self.assertIn('Загрузка CPU',self.client.get('/').text)
        self.assertEqual(self.acknowledge(episode).status_code,409)
        with a.db() as c:self.assertFalse(next(row for row in active(c) if row['id']==repeated['id'])['acknowledged'])

    def test_acknowledgement_survives_outage_and_database_reopen(self):
        self.report(cpu_percent=99)
        episode=self.episode('cpu_percent');self.acknowledge(episode)
        with a.db() as c:
            rows=c.execute('SELECT a.id,r.data,r.received FROM agents a LEFT JOIN current_reports r ON r.agent=a.id').fetchall()
            sync(c,rows,time.time()+300)
        with a.db() as c:
            self.assertIsNone(c.execute('SELECT closed FROM incident_history WHERE id=?',(episode['id'],)).fetchone()[0])
            self.assertIsNotNone(next(row for row in active(c) if row['id']==episode['id'])['acknowledged'])
        self.report(cpu_percent=99)
        self.assertEqual(self.episode('cpu_percent')['id'],episode['id'])

    def test_auth_csrf_role_and_idempotence(self):
        self.report(cpu_percent=99);episode=self.episode('cpu_percent')
        self.assertEqual(self.acknowledge(episode,csrf='wrong').status_code,403)
        self.assertEqual(self.acknowledge(episode,client=self.fixture.clients['reader']).status_code,403)
        self.assertNotIn('action="/problems/acknowledge"',self.fixture.clients['reader'].get('/').text)
        self.assertEqual(self.acknowledge(episode).status_code,303)
        self.assertEqual(self.acknowledge(episode).status_code,303)
        with a.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM incident_acknowledgements').fetchone()[0],1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM events WHERE message LIKE 'Проблема отмечена%'").fetchone()[0],1)
        self.client.cookies.clear()
        self.assertEqual(self.acknowledge(episode).status_code,401)

    def test_backup_alarm_and_notifications_suppressed_but_other_service_visible(self):
        self.report(backups=[{'name':'SQL backup','path':'/backup','state':'missing'}],services=[{'name':'SQL','status':'stopped'}])
        episode=self.episode('backup');self.acknowledge(episode)
        html=self.client.get('/').text
        self.assertNotIn('class="backup-alarm"',html)
        summary=html.split('<section class="problem-summary">')[1].split('</section>')[0]
        self.assertNotIn('SQL backup',summary);self.assertIn('служба SQL',summary)
        sent=[]
        with patch('server.notifications.delivery_window',return_value=True):
            tick(a.db,sent.append,time.time())
        self.assertEqual(len(sent),1);self.assertNotIn('SQL backup',sent[0])
        self.report(backups=[],services=[])
        self.report(backups=[{'name':'SQL backup','path':'/backup','state':'missing'}])
        with patch('server.notifications.delivery_window',return_value=True):tick(a.db,sent.append,time.time())
        self.assertTrue(any('SQL backup' in text and 'ПРОБЛЕМА' in text for text in sent))

    def test_delay_and_collector_have_separate_episode_controls(self):
        self.report(hardware={'status':'unavailable'})
        episode=self.episode('collector');self.acknowledge(episode)
        self.report(hardware={'status':'available'})
        self.report(hardware={'status':'unavailable'})
        self.assertNotEqual(self.episode('collector')['id'],episode['id'])
        with a.db() as c:c.execute('UPDATE latest_reports SET received=? WHERE agent=?',(time.time()-60,'pc'))
        delay=self.episode('report_delay');self.assertEqual(self.acknowledge(delay).status_code,303)
        self.report()
        with a.db() as c:self.assertIsNotNone(c.execute('SELECT closed FROM incident_history WHERE id=?',(delay['id'],)).fetchone()[0])

    def test_notified_problem_reappears_even_between_notification_ticks(self):
        self.report(services=[{'name':'SQL','status':'stopped'}])
        episode=self.episode('service');sent=[]
        with patch('server.notifications.delivery_window',return_value=True):
            tick(a.db,sent.append,time.time())
            self.assertEqual(len(sent),1)
            self.acknowledge(episode)
            tick(a.db,sent.append,time.time())
            self.assertEqual(len(sent),1)
            self.report(services=[{'name':'SQL','status':'running'}])
            self.report(services=[{'name':'SQL','status':'stopped'}])
            tick(a.db,sent.append,time.time())
        self.assertEqual(len(sent),2)
        self.assertTrue(all('ПРОБЛЕМА' in text for text in sent))

    def test_many_ignored_problems_do_not_block_other_notifications(self):
        backups=[{'name':'backup '+str(i),'path':'/backup/'+str(i),'state':'missing'} for i in range(25)]
        self.report(backups=backups,services=[{'name':'SQL','status':'stopped'}])
        self.client.get('/')
        with a.db() as c:
            for row in c.execute("SELECT * FROM incident_history WHERE category='backup' AND closed IS NULL").fetchall():
                c.execute('INSERT INTO incident_acknowledgements VALUES (?,?,?,?,?)',(row['id'],row['key'],row['opened'],time.time(),'admin'))
        sent=[]
        with patch('server.notifications.delivery_window',return_value=True):tick(a.db,sent.append,time.time())
        self.assertEqual(len(sent),1)
        self.assertIn('служба SQL',sent[0])

    def test_card_actions_share_episode_with_summary_and_filter(self):
        import re
        self.report(cpu_percent=99)
        episode=self.episode('cpu_percent')
        compact=lambda html:re.search(r'<article[^>]*data-server-id="pc".*?</article>',html,re.S).group(0)
        html=compact(self.client.get('/').text)
        self.assertIn('Высокая загрузка CPU',html)
        self.assertIn('action="/problems/acknowledge"',html)
        self.acknowledge(episode)
        html=compact(self.client.get('/').text)
        self.assertNotIn('Высокая загрузка CPU',html)
        self.assertNotIn('problem-server',html)
        self.assertNotIn('data-server-id="pc"',self.client.get('/?view=problems').text)
        self.report(cpu_percent=10);self.report(cpu_percent=98)
        self.assertIn('Высокая загрузка CPU',compact(self.client.get('/').text))

    def test_tracked_services_show_control_and_shared_acknowledgement(self):
        import re
        self.report(services=[{'name':'SQL','display_name':'SQL <database>','status':'stopped'}, {'name':'healthy','status':'running'}])
        episode=self.episode('service')
        html=self.client.get('/servers/pc').text
        row=lambda name,html:re.search(r'<div class="list-row tracked-service[^>]*data-service-name="'+name+r'".*?</form>.*?</div>',html,re.S).group(0)
        service=row('SQL',html)
        self.assertIn('SQL &lt;database&gt;',service)
        self.assertIn('name="incident" value="'+str(episode['id'])+'"',service)
        self.assertIn('name="return_to" value="/servers/pc"',service)
        response=self.client.post('/problems/acknowledge',data={'csrf':self.csrf,'incident':episode['id'],'return_to':'/servers/pc'},follow_redirects=False)
        self.assertEqual(response.status_code,303);self.assertEqual(response.headers['location'],'/servers/pc')
        html=self.client.get('/servers/pc').text
        marked=re.search(r'<div class="list-row tracked-service service-acknowledged".*?</div>',html,re.S).group(0)
        self.assertIn('Остановлена',marked);self.assertIn('✓ Всё окей',marked)
        self.assertNotIn('<form',marked)
        self.assertNotIn('Служба не работает: SQL',self.client.get('/').text)
        self.report(services=[{'name':'SQL','status':'running'}])
        self.report(services=[{'name':'SQL','status':'stopped'}])
        self.assertIn('action="/problems/acknowledge"',row('SQL',self.client.get('/servers/pc').text))

    def test_detail_and_snapshots_do_not_expose_actions_to_viewers(self):
        self.report(cpu_percent=99,services=[{'name':'SQL','status':'stopped'}])
        for path in ['/', '/servers/pc']:
            self.assertNotIn('action="/problems/acknowledge"',self.fixture.clients['reader'].get(path).text)
        from server.dashboard import server_card
        html=server_card({'id':'pc','data':json.dumps(self.data),'received':time.time()},time.time(),historical=True,csrf=self.csrf)
        self.assertNotIn('action="/problems/acknowledge"',html)
        self.assertNotIn('problem-acknowledged',html)

    def test_redirect_is_limited_to_same_server(self):
        self.report(cpu_percent=99);episode=self.episode('cpu_percent')
        for target in ['https://outside.example','//outside.example','/servers/other']:
            response=self.client.post('/problems/acknowledge',data={'csrf':self.csrf,'incident':episode['id'],'return_to':target},follow_redirects=False)
            self.assertEqual(response.headers['location'],'/')
