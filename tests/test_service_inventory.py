import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import psutil
from fastapi.testclient import TestClient
from agent import service_inventory as inventory
from server import app as a
from server.host_monitor import store as store_host,register_host


class InventoryApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset();self.now=time.time()
        self.client=TestClient(a.app,base_url='https://testserver');self.client.cookies.set('session','reader')
        with a.db() as c:
            c.execute("INSERT INTO users VALUES ('reader',?,?)",('00'*16,'0'*128))
            c.execute("INSERT INTO user_roles VALUES ('reader','viewer',1)")
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('reader'),self.now+3600))
            c.execute('INSERT INTO session_users VALUES (?,?)',(a.digest('reader'),'reader'))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
        self.payload={'status':'available','platform':'linux','total':1,'items':[{'name':'sshd.service','display_name':'<SSH>','status':'running','details':{'MainPID':'123','ExecStart':'/usr/sbin/sshd'}}]}

    def upload(self,payload=None):return self.client.post('/api/processes/pc/services',headers={'Authorization':'Bearer key'},json=payload or self.payload)

    def test_authenticated_current_only_api_and_large_payload(self):
        self.assertEqual(self.client.post('/api/processes/pc/services',json=self.payload).status_code,401)
        for _ in range(2):self.assertEqual(self.upload().status_code,200)
        response=self.client.get('/api/servers/pc/services');self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(response.json()['inventory']['items'][0]['status'],'running')
        self.payload['items']=[{'name':'svc'+str(i),'details':{'description':'x'*512},'status':'stopped'} for i in range(200)]
        self.assertGreater(len(json.dumps(self.payload)),65536);self.assertEqual(self.upload().status_code,200)
        with a.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM latest_services').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM reports').fetchone()[0],0)
        self.client.cookies.clear();self.assertEqual(self.client.get('/api/servers/pc/services').status_code,401)

    def test_validation_and_local_raspi_process_history_binding(self):
        self.payload['items'][0]['details']['bad']='x'*4097
        self.assertEqual(self.upload().status_code,422)
        self.assertEqual(self.client.post('/api/processes/pc/services',headers={'Authorization':'Bearer key'},content=b'x'*(2*1024**2+1)).status_code,413)
        host=register_host(a.db)
        report={'hostname':'raspi','cpu_percent':10,'memory_percent':20,'uptime_seconds':1000,'disks':[]}
        processes={'status':'available','items':[{'pid':1,'name':'local-python','cpu_percent':10,'memory_bytes':2048}],'total':1}
        self.assertTrue(store_host(a.db,host,report,self.now,processes))
        from server.snapshots import snapshot
        with a.db() as c:
            identifier=c.execute('SELECT rowid FROM reports WHERE agent=?',(host,)).fetchone()[0]
            self.assertEqual(c.execute('SELECT count(*) FROM process_history WHERE agent=?',(host,)).fetchone()[0],1)
            self.assertIn('local-python',snapshot(c,host,identifier)['html'])
