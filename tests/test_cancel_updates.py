import time
import unittest
import test_remote_updates as fixtures
from server import app as application


class CancelUpdatesTest(unittest.TestCase):
    setUp=fixtures.UpdatesTest.setUp
    queue=fixtures.UpdatesTest.queue

    def job(self):
        return self.client.get('/api/agent-update/pc',headers=self.headers).json()['job']

    def cancel(self,job):
        return self.client.post('/updates/pc/'+str(job)+'/cancel',data={'csrf':self.csrf},follow_redirects=False)

    def test_cancel_fetched_queue_blocks_ack_download_and_confirmation(self):
        self.queue();job=self.job();self.assertIn('Отменить задание',self.client.get('/updates').text)
        self.assertEqual(self.cancel(job['id']).status_code,303)
        self.assertIsNone(self.job())
        response=self.client.post('/api/agent-update/pc/status',headers=self.headers,json={'job_id':job['id'],'status':'running'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.client.get('/api/agent-update/pc/'+str(job['id'])+'/package',headers=self.headers).status_code,404)
        self.client.post('/api/report/pc',headers=self.headers,json={**self.data,'agent_version':'v2'})
        with application.db() as c:
            self.assertEqual(c.execute('SELECT status FROM agent_update_jobs WHERE id=?',(job['id'],)).fetchone()[0],'cancelled')
            self.assertEqual(c.execute("SELECT count(*) FROM update_job_events WHERE job=? AND status='cancelled'",(job['id'],)).fetchone()[0],1)
        self.assertEqual(self.cancel(job['id']).status_code,303)
        self.assertIn('Отменено',self.client.get('/updates').text)

    def test_running_cannot_be_cancelled_and_bulk_preserves_running(self):
        self.queue();job=self.job()
        self.client.post('/api/agent-update/pc/status',headers=self.headers,json={'job_id':job['id'],'status':'running'})
        self.assertEqual(self.cancel(job['id']).status_code,409)
        with application.db() as c:
            queued=c.execute("INSERT INTO agent_update_jobs(agent,package,status,message,created,updated) VALUES ('pc',1,'queued','',?,?)",(time.time(),time.time())).lastrowid
        response=self.client.post('/updates/all/cancel',data={'csrf':self.csrf},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        with application.db() as c:
            self.assertEqual(c.execute('SELECT status FROM agent_update_jobs WHERE id=?',(job['id'],)).fetchone()[0],'running')
            self.assertEqual(c.execute('SELECT status FROM agent_update_jobs WHERE id=?',(queued,)).fetchone()[0],'cancelled')
        self.assertIn('Безопасная отмена установки недоступна',self.client.get('/updates').text)

    def test_csrf_auth_and_agent_scope(self):
        self.queue();job=self.job()
        self.assertEqual(self.client.post('/updates/pc/'+str(job['id'])+'/cancel',data={}).status_code,403)
        self.assertEqual(self.client.post('/updates/all/cancel',data={}).status_code,403)
        self.assertEqual(self.client.post('/updates/other/'+str(job['id'])+'/cancel',data={'csrf':self.csrf}).status_code,404)
        self.assertEqual(self.job()['id'],job['id'])
        self.client.cookies.clear()
        self.assertEqual(self.cancel(job['id']).status_code,401)
