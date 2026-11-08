import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from server import app as a


class WindowsManagementTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(a.app);self.client.cookies.set('session','session')
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('session'),time.time()+3600))
            c.execute("INSERT OR IGNORE INTO users VALUES ('admin',?,?)",('00'*16,'0'*128))
            c.execute("INSERT INTO session_users VALUES (?,'admin')",(a.digest('session'),))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
        self.headers={'Authorization':'Bearer key'}
        self.data={'hostname':'pc','cpu_percent':0,'memory_percent':1,'uptime_seconds':1000,'disks':[],'features':['windows_management_v1'],'windows_updates':{'status':'available','management_enabled':True,'history_status':'available','hotfix_status':'available','history':[{'title':'KB123 <script>bad</script>','installed_at':1700000000,'result':2}],'reboot_required':True,'reboot_reasons':['Windows Update']}}
        self.assertEqual(self.client.post('/api/report/pc',headers=self.headers,json=self.data).status_code,200)
        self.csrf=re.search('name="csrf" value="([^"]+)"',self.client.get('/windows/pc').text).group(1)

    def queue(self,action='scan',confirmation=''):
        return self.client.post('/windows/pc',data={'csrf':self.csrf,'action':action,'confirmation':confirmation},follow_redirects=False)

    def job(self):return self.client.get('/api/windows/pc',headers=self.headers).json()['job']

    def status(self,job,status,result=None):return self.client.post('/api/windows/pc/status',headers=self.headers,json={'id':job['id'],'status':status,'result':result or {}})

    def test_confirmation_auth_and_local_opt_in(self):
        self.assertEqual(self.queue('reboot').status_code,400)
        self.assertEqual(self.client.post('/windows/pc',data={'action':'scan'}).status_code,403)
        self.assertEqual(self.client.get('/api/windows/pc').status_code,401)
        self.assertEqual(self.queue('shell').status_code,400)
        self.data['windows_updates']['management_enabled']=False
        self.client.post('/api/report/pc',headers=self.headers,json=self.data)
        self.assertEqual(self.queue().status_code,409)
        self.client.cookies.clear();self.assertEqual(self.queue().status_code,401)

    def test_lifecycle_expiry_and_no_duplicate_acceptance(self):
        self.assertEqual(self.queue().status_code,303)
        self.assertEqual(self.queue().status_code,409)
        job=self.job()
        with a.db() as c:c.execute('UPDATE windows_commands SET expires=?',(time.time()-1,))
        self.assertEqual(self.status(job,'running').status_code,409)
        self.assertIsNone(self.job())
        self.queue();job=self.job()
        self.assertEqual(self.status(job,'running').status_code,200)
        self.assertEqual(self.status(job,'running').status_code,409)
        self.assertEqual(self.status(job,'succeeded',{'count':1,'available':[{'title':'KB123','size_bytes':12}]}).status_code,200)
        self.assertIsNone(self.job())
        html=self.client.get('/windows/pc').text
        self.assertIn('KB123',html);self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>bad</script>',html)

    def test_uncertain_requires_review_and_scheduled_restart_blocks_install(self):
        self.queue('install','pc');job=self.job();self.status(job,'running');self.status(job,'uncertain')
        self.assertEqual(self.queue('install','pc').status_code,409)
        self.assertEqual(self.queue('resolve','pc').status_code,303)
        self.assertEqual(self.queue('reboot','pc').status_code,303)
        job=self.job();self.status(job,'running');self.status(job,'succeeded')
        self.assertEqual(self.queue('install','pc').status_code,409)
        self.assertEqual(self.queue('cancel_reboot').status_code,303)
        job=self.job();self.status(job,'running');self.status(job,'succeeded')
        self.assertEqual(self.queue('install','pc').status_code,303)
