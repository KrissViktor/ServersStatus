import json
from pathlib import Path
import tempfile
import time
import unittest
from server import app as application
from fastapi.testclient import TestClient


class ProcessApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,application,'DB',application.DB);application.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(application.app)
        with application.db() as c:
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',application.digest('key')))
            c.execute('INSERT INTO sessions VALUES (?,?)',(application.digest('session'),time.time()+3600))
            c.execute("INSERT OR IGNORE INTO users VALUES ('admin',?,?)",('00'*16,'0'*128))
            c.execute("INSERT INTO session_users VALUES (?,'admin')",(application.digest('session'),))
        self.headers={'Authorization':'Bearer key'}
        self.snapshot={'status':'available','items':[{'pid':1,'name':'<script>bad()</script>','cpu_percent':50,'memory_bytes':2048}],'total':1}

    def test_authenticated_latest_only_and_size_limits(self):
        self.assertEqual(self.client.post('/api/processes/pc',json=self.snapshot).status_code,401)
        self.assertEqual(self.client.get('/api/servers/pc/processes').status_code,401)
        self.assertEqual(self.client.post('/api/processes/other',headers=self.headers,json=self.snapshot).status_code,401)
        for i in range(2):self.assertEqual(self.client.post('/api/processes/pc',headers=self.headers,json=self.snapshot).status_code,200)
        with application.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM latest_processes').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reports').fetchone()[0],0)
        self.client.cookies.set('session','session')
        response=self.client.get('/api/servers/pc/processes')
        self.assertEqual(response.json()['snapshot']['items'][0]['cpu_percent'],50)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(self.client.post('/api/processes/pc',headers=self.headers,content=b'x'*(2*1024**2+1)).status_code,413)
        self.assertEqual(self.client.post('/api/report/pc',headers=self.headers,content=b'x'*65537).status_code,413)

    def test_validation_and_large_process_list(self):
        self.snapshot['items']=[{'pid':i,'name':'process-'+str(i),'cpu_percent':i%100} for i in range(1500)]
        payload=json.dumps(self.snapshot)
        self.assertGreater(len(payload),65536)
        self.assertEqual(self.client.post('/api/processes/pc',headers=self.headers,content=payload).status_code,200)
        self.snapshot['items'][0]['memory_bytes']=-1
        self.assertEqual(self.client.post('/api/processes/pc',headers=self.headers,json=self.snapshot).status_code,422)
        self.assertEqual(self.client.post('/api/processes/pc',headers=self.headers,content='bad').status_code,422)

    def test_rdp_fields_survive_report_validation_and_escape_html(self):
        from server.metrics_ui import rdp_section
        data={'hostname':'pc','cpu_percent':1,'memory_percent':1,'uptime_seconds':1,'disks':[], 'rdp':{'status':'available','sessions':[{'session_id':1,'username':'user','state':'active','client_name':'<b>client</b>','client_address':'192.168.1.2','logon_at':1700000000,'duration_seconds':120,'idle_seconds':60}]}}
        self.assertEqual(self.client.post('/api/report/pc',headers=self.headers,json=data).status_code,200)
        with application.db() as c:stored=json.loads(c.execute('SELECT data FROM latest_reports').fetchone()[0])
        html=rdp_section(stored)
        self.assertIn('Вход (МСК)',html);self.assertIn('Простой',html)
        self.assertIn('&lt;b&gt;client&lt;/b&gt;',html);self.assertNotIn('<b>client</b>',html)
        self.assertEqual(stored['rdp']['sessions'][0]['duration_seconds'],120)
