import json
import time
import unittest
from unittest.mock import patch
import test_access_roles as fixtures
from server import app as a
from server.freshness import status,line
from server.update_diagnostics import record,render


class ImprovedPortalTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.AccessRolesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client=self.fixture.clients['admin'];self.csrf=a.digest('agent-management:admin')
        self.data=dict(self.fixture.report)

    def report(self,**changes):
        self.data.update(changes)
        response=self.client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=self.data)
        self.assertEqual(response.status_code,200)

    def mark(self):
        self.report(cpu_percent=99)
        self.client.get('/')
        with a.db() as c:episode=dict(c.execute("SELECT * FROM incident_history WHERE category='cpu_percent' AND closed IS NULL").fetchone())
        response=self.client.post('/problems/acknowledge',data={'csrf':self.csrf,'incident':episode['id']},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        return episode

    def test_manage_comment_author_and_restore(self):
        episode=self.mark();endpoint='/problems/'+str(episode['id'])
        html=self.client.get('/problems').text
        self.assertIn('Отметил: <b>admin</b>',html);self.assertIn('Загрузка CPU',html)
        response=self.client.post(endpoint+'/comment',data={'csrf':self.csrf,'comment':'Плановая задача <script>alert(1)</script>'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        html=self.client.get('/problems').text
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;',html)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertEqual(self.client.post(endpoint+'/restore',data={'csrf':self.csrf},follow_redirects=False).status_code,303)
        self.assertIn('Скрытых проблем нет',self.client.get('/problems').text)
        summary=self.client.get('/').text.split('<section class="problem-summary">')[1].split('</section>')[0]
        self.assertIn('Загрузка CPU',summary)

    def test_manage_access_csrf_and_stale_episode(self):
        episode=self.mark();endpoint='/problems/'+str(episode['id'])
        self.assertEqual(self.fixture.clients['reader'].get('/problems').status_code,403)
        self.assertEqual(self.fixture.clients['reader'].post(endpoint+'/restore',data={'csrf':self.csrf}).status_code,403)
        self.assertEqual(self.client.post(endpoint+'/restore',data={'csrf':'wrong'}).status_code,403)
        self.assertEqual(self.client.post(endpoint+'/comment',data={'csrf':self.csrf,'comment':'a'*1001}).status_code,400)
        self.report(cpu_percent=10);self.report(cpu_percent=99)
        self.assertIn('Скрытых проблем нет',self.client.get('/problems').text)
        self.assertEqual(self.client.post(endpoint+'/restore',data={'csrf':self.csrf}).status_code,409)
        self.assertEqual(self.client.post(endpoint+'/comment',data={'csrf':self.csrf,'comment':'old'}).status_code,409)

    def test_multiline_comments_and_invalid_episode_id(self):
        episode=self.mark();endpoint='/problems/'+str(episode['id'])
        response=self.client.post(endpoint+'/comment',data={'csrf':self.csrf,'comment':'Первая строка\r\nВторая строка'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        self.assertIn('Первая строка\nВторая строка',self.client.get('/problems').text)
        response=self.client.post('/problems/'+('9'*50)+'/restore',data={'csrf':self.csrf})
        self.assertEqual(response.status_code,404)
        self.assertNotIn('МСК МСК',self.client.get('/problems').text)

    def test_freshness_in_cards_sections_and_table(self):
        with a.db() as c:c.execute("UPDATE latest_reports SET received=? WHERE agent='pc'",(time.time()-60,))
        html=self.client.get('/').text
        self.assertIn('Отчёты задерживаются',html)
        self.assertIn('data-freshness="delayed"',html)
        detail=self.client.get('/servers/pc').text
        self.assertGreater(detail.count('Отчёт получен:'),5)
        self.report(hardware={'status':'unavailable'},temperatures={'status':'available','sampled_at':time.time()-600,'items':[{'id':'cpu','current':40}]})
        detail=self.client.get('/servers/pc').text
        self.assertIn('Измерение устарело',detail)
        self.assertIn('Недоступен сбор: Комплектация',detail)

    def test_overview_controls_metadata_and_account_scope(self):
        self.report(cpu_percent=99)
        html=self.client.get('/').text
        for value in ['data-overview-sort','data-overview-direction','data-pin-server="pc"','data-sort-problems="1"','data-preference-scope=']:
            self.assertIn(value,html)
        import re
        admin_scope=re.search(r'data-preference-scope="([^"]+)"',html)[1]
        reader_scope=re.search(r'data-preference-scope="([^"]+)"',self.fixture.clients['reader'].get('/').text)[1]
        self.assertNotEqual(admin_scope,reader_scope)

    def job(self):
        now=time.time()
        with a.db() as c:
            package=c.execute("INSERT INTO update_packages(platform,version,sha256,size,path) VALUES ('windows-x64','new','hash',1,'/unused')").lastrowid
            return c.execute("INSERT INTO agent_update_jobs(agent,package,status,message,created,updated) VALUES ('pc',?,'queued','Ожидание',?,?)",(package,now,now)).lastrowid

    def test_update_progress_requires_explicit_steps_and_confirmed_report(self):
        job=self.job();path='/api/agent-update/pc/status';headers={'Authorization':'Bearer key'}
        for phase in ['running','completed']:
            response=self.client.post(path,headers=headers,json={'job_id':job,'status':'running','stage':'download','stage_state':phase,'message':'SECRET-RAW'})
            self.assertEqual(response.status_code,200)
        html=self.client.get('/updates').text
        self.assertIn('Скачивание пакета',html);self.assertIn('Подтверждено',html);self.assertIn('Не сообщалось',html)
        self.assertNotIn('SECRET-RAW',html)
        # Client cannot claim that the portal received a new version report.
        self.client.post(path,headers=headers,json={'job_id':job,'status':'running','stage':'confirmed','stage_state':'completed'})
        with a.db() as c:self.assertIsNone(c.execute("SELECT 1 FROM update_job_steps WHERE job=? AND stage='confirmed'",(job,)).fetchone())
        self.report(agent_version='new',agent_platform='windows-x64')
        with a.db() as c:
            self.assertEqual(c.execute('SELECT status FROM agent_update_jobs WHERE id=?',(job,)).fetchone()[0],'applied')
            self.assertEqual(c.execute("SELECT phase FROM update_job_steps WHERE job=? AND stage='confirmed'",(job,)).fetchone()[0],'completed')

    def test_failed_update_reports_rollback_without_raw_details(self):
        job=self.job()
        response=self.client.post('/api/agent-update/pc/status',headers={'Authorization':'Bearer key'},json={'job_id':job,'status':'failed','stage':'replace','error_code':'replace','rollback':'restored','message':'SECRET'})
        self.assertEqual(response.status_code,200)
        html=self.client.get('/updates').text
        self.assertIn('Предыдущая версия восстановлена',html);self.assertNotIn('SECRET',html)
        with a.db() as c:self.assertEqual(c.execute('SELECT phase FROM update_job_steps WHERE job=?',(job,)).fetchone()[0],'failed')

    def test_malformed_diagnostic_fields_are_ignored(self):
        job=self.job()
        response=self.client.post('/api/agent-update/pc/status',headers={'Authorization':'Bearer key'},json={'job_id':job,'status':'running','stage':{},'stage_state':[],'rollback':{},'error_code':[]})
        self.assertEqual(response.status_code,200)
        with a.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM update_job_steps WHERE job=?',(job,)).fetchone()[0],0)


class FreshnessTest(unittest.TestCase):
    def test_boundaries_and_unavailable_are_distinct(self):
        self.assertEqual(status(None,1000)[0],'unknown')
        self.assertEqual(status(970,1000)[0],'fresh')
        self.assertEqual(status(969,1000)[0],'delayed')
        self.assertEqual(status(820,1000)[0],'stale')
        self.assertIn('Недоступность самого сервера не подтверждена',line(0,1000))
        self.assertIn('Не удалось получить показатель',line(1000,1000,{'status':'unavailable','checked_at':990}))
        self.assertIn('Сохранённые данные',line(0,1000,historical=True))
        self.assertNotIn('МСК МСК',line(1000,1000))
