import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from server import app as a


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(a.app);self.client.cookies.set('session','session')
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('session'),time.time()+3600))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
        self.headers={'Authorization':'Bearer key'}
        self.report={'hostname':'pc','cpu_percent':0,'memory_percent':1,'uptime_seconds':1000,'disks':[],'features':['console_v1'],'console':{'enabled':True,'shell':'bash','identity':'agent'}}
        self.client.post('/api/report/pc',headers=self.headers,json=self.report)
        html=self.client.get('/servers/pc').text
        self.csrf=re.search('name="csrf" value="([^"]+)"',html).group(1)

    def queue(self,**changes):return self.client.post('/api/servers/pc/console',json={'csrf':self.csrf,'confirmation':'pc','command':'uptime','timeout':30,**changes})
    def job(self):return self.client.get('/api/console/pc',headers=self.headers).json()['job']
    def ack(self,job,status,**extras):return self.client.post('/api/console/pc/status',headers=self.headers,json={'id':job['id'],'status':status,**extras})

    def test_permissions_confirmations_and_local_flag(self):
        self.assertEqual(self.queue(csrf='bad').status_code,403)
        self.assertEqual(self.queue(confirmation='other').status_code,400)
        self.assertEqual(self.queue(timeout=61).status_code,422)
        self.assertEqual(self.client.get('/api/console/pc').status_code,401)
        self.report['console']['enabled']=False
        self.client.post('/api/report/pc',headers=self.headers,json=self.report)
        self.assertEqual(self.queue().status_code,409)
        self.client.cookies.clear();self.assertEqual(self.client.get('/api/servers/pc/console').status_code,401)

    def test_accept_expiry_lifecycle_output_and_no_replay(self):
        self.assertEqual(self.queue().status_code,200);job=self.job()
        self.assertEqual(self.queue().status_code,409)
        self.assertEqual(self.ack(job,'running').status_code,200)
        self.assertEqual(self.ack(job,'running').status_code,409)
        self.assertEqual(self.ack(job,'succeeded',output='<script>bad</script>',exit_code=0).status_code,200)
        self.assertIsNone(self.job())
        response=self.client.get('/api/servers/pc/console');self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(response.json()['jobs'][0]['result']['output'],'<script>bad</script>')
        self.queue();job=self.job()
        with a.db() as c:c.execute('UPDATE console_jobs SET expires=? WHERE id=?',(time.time()-1,job['id']))
        self.assertEqual(self.ack(job,'running').status_code,409);self.assertIsNone(self.job())

    def test_unknown_requires_review_and_agent_update_mutex(self):
        self.queue();job=self.job();self.ack(job,'running');self.ack(job,'uncertain')
        self.assertEqual(self.queue().status_code,409)
        self.assertEqual(self.queue(review=True).status_code,200)
        with a.db() as c:
            now=time.time()
            c.execute("INSERT INTO agent_update_jobs VALUES (1,'pc',1,'queued','',?,?)",(now,now))
        self.assertEqual(self.queue().status_code,409)
        with a.db() as c:c.execute('DELETE FROM agent_update_jobs')
        self.assertEqual(self.queue().status_code,200)

    def test_live_progress_is_not_new_acceptance_or_audit_spam(self):
        self.queue();job=self.job()
        self.assertEqual(self.ack(job,'running',progress=True,output='too early').status_code,409)
        self.ack(job,'running')
        self.assertEqual(self.ack(job,'running',progress=True,output='first').status_code,200)
        self.assertEqual(self.ack(job,'running',progress=True,output='first\nsecond').status_code,200)
        result=self.client.get('/api/servers/pc/console').json()['jobs'][0]
        self.assertEqual(result['status'],'running');self.assertEqual(result['result']['output'],'first\nsecond')
        with a.db() as c:self.assertEqual(c.execute("SELECT count(*) FROM events WHERE category='console'").fetchone()[0],2)
        self.ack(job,'succeeded',output='final',exit_code=0)
        self.assertEqual(self.ack(job,'running',progress=True,output='late').status_code,409)
        result=self.client.get('/api/servers/pc/console').json()['jobs'][0]
        self.assertEqual(result['result']['output'],'final')

    def test_input_queue_scoped_delivery_and_no_id_reuse(self):
        self.report['console']['interactive_input']=True
        self.client.post('/api/report/pc',headers=self.headers,json=self.report)
        self.queue();job=self.job();self.ack(job,'running')
        url='/api/servers/pc/console/'+str(job['id'])+'/control'
        body={'csrf':self.csrf,'confirmation':'pc','action':'stdin','text':'Виктор'}
        self.assertEqual(self.client.post(url,json={**body,'csrf':'bad'}).status_code,403)
        self.assertEqual(self.client.post(url,json=body).status_code,200)
        agent_url='/api/console/pc/'+str(job['id'])+'/controls'
        self.assertEqual(self.client.get(agent_url).status_code,401)
        first=self.client.get(agent_url,headers=self.headers).json()['controls'][0]
        self.assertEqual(first['text'],'Виктор')
        self.assertEqual(self.client.get(agent_url+'?after='+str(first['id']),headers=self.headers).json()['controls'],[])
        self.client.post(url,json={**body,'text':'next'})
        second=self.client.get(agent_url+'?after='+str(first['id']),headers=self.headers).json()['controls'][0]
        self.assertGreater(second['id'],first['id'])
        self.ack(job,'cancelled')
        self.assertEqual(self.client.post(url,json=body).status_code,409)
        with a.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM console_controls').fetchone()[0],0)

    def test_cancel_bypasses_a_full_input_queue(self):
        self.report['console']['interactive_input']=True
        self.client.post('/api/report/pc',headers=self.headers,json=self.report)
        self.queue();job=self.job();self.ack(job,'running')
        url='/api/servers/pc/console/'+str(job['id'])+'/control'
        body={'csrf':self.csrf,'confirmation':'pc','action':'stdin','text':'answer'}
        for _ in range(8):self.assertEqual(self.client.post(url,json=body).status_code,200)
        self.assertEqual(self.client.post(url,json=body).status_code,429)
        self.assertEqual(self.client.post(url,json={**body,'action':'cancel'}).status_code,200)
        controls=self.client.get('/api/console/pc/'+str(job['id'])+'/controls',headers=self.headers).json()['controls']
        self.assertEqual([c['action'] for c in controls],['cancel'])
