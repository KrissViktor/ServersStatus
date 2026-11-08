import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import app as application
from server import updates
from agent.remote_update import download,validate
from agent.update_worker import extract,install
from server.host_monitor import register_host,store,database_size


class UpdatesTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.addCleanup(setattr,application,'DB',application.DB);application.DB=str(self.root/'db.sqlite3')
        self.addCleanup(setattr,updates,'PACKAGE_ROOT',updates.PACKAGE_ROOT);updates.PACKAGE_ROOT=self.root
        self.client=TestClient(application.app)
        self.client.cookies.set('session','session')
        with application.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(application.digest('session'),time.time()+3600))
            c.execute("INSERT OR IGNORE INTO users VALUES ('admin',?,?)",('00'*16,'0'*128))
            c.execute("INSERT INTO session_users VALUES (?,'admin')",(application.digest('session'),))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',application.digest('key')))
        self.headers={'Authorization':'Bearer key'}
        self.data={'hostname':'pc','cpu_percent':1,'memory_percent':2,'uptime_seconds':3,'disks':[], 'features':['remote_update_v1'],'agent_version':'v1','agent_platform':'linux-source'}
        self.assertEqual(self.client.post('/api/report/pc',headers=self.headers,json=self.data).status_code,200)
        self.package=self.root/'package';self.package.write_bytes(b'package')
        with application.db() as c:
            c.execute('INSERT INTO update_packages VALUES (1,?,?,?,?,?)',('linux-source','v2',hashlib.sha256(b'package').hexdigest(),7,str(self.package)))
        response=self.client.get('/updates')
        import re
        self.csrf=re.search(r'name="csrf" value="([^"]+)"',response.text).group(1)

    def queue(self):return self.client.post('/updates/pc',data={'csrf':self.csrf,'package':'1'},follow_redirects=False)

    def test_auth_csrf_assignment_and_version_confirmation(self):
        self.assertEqual(self.client.post('/updates/pc',data={'package':1}).status_code,403)
        self.assertEqual(self.queue().status_code,303)
        self.assertEqual(self.queue().status_code,409)
        self.assertEqual(self.client.get('/api/agent-update/pc').status_code,401)
        job=self.client.get('/api/agent-update/pc',headers=self.headers).json()['job']
        self.assertEqual(self.client.get(f'/api/agent-update/other/{job["id"]}/package',headers=self.headers).status_code,401)
        self.assertEqual(self.client.get(f'/api/agent-update/pc/{job["id"]}/package',headers=self.headers).content,b'package')
        self.client.post('/api/agent-update/pc/status',headers=self.headers,json={'job_id':job['id'],'status':'applied'})
        with application.db() as c:self.assertEqual(c.execute('SELECT status FROM agent_update_jobs').fetchone()[0],'queued')
        self.client.post('/api/report/pc',headers=self.headers,json={**self.data,'agent_version':'v2'})
        with application.db() as c:self.assertEqual(c.execute('SELECT status FROM agent_update_jobs').fetchone()[0],'applied')
        self.assertIsNone(self.client.get('/api/agent-update/pc',headers=self.headers).json()['job'])

    def test_platform_timeout_and_no_fake_success(self):
        self.data['agent_platform']='windows-x64'
        self.client.post('/api/report/pc',headers=self.headers,json=self.data)
        self.assertEqual(self.queue().status_code,400)
        self.data['agent_platform']='linux-source'
        self.client.post('/api/report/pc',headers=self.headers,json=self.data)
        self.queue()
        with application.db() as c:c.execute('UPDATE agent_update_jobs SET created=?',(time.time()-901,))
        self.assertIsNone(self.client.get('/api/agent-update/pc',headers=self.headers).json()['job'])
        with application.db() as c:self.assertEqual(c.execute('SELECT status FROM agent_update_jobs').fetchone()[0],'failed')

    def test_host_stores_every_sample_and_stops_after_deletion(self):
        agent=register_host(application.db)
        self.assertEqual(register_host(application.db),agent)
        report={**self.data,'agent_platform':'portal','portal':{'temperature_c':45,'database_bytes':123}}
        self.assertTrue(store(application.db,agent,report,time.time()))
        self.assertTrue(store(application.db,agent,report,time.time()+10))
        self.assertIn('45',self.client.get('/host').text)
        with application.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reports WHERE agent=?',(agent,)).fetchone()[0],2)
            c.execute('DELETE FROM agents WHERE id=?',(agent,))
        self.assertFalse(store(application.db,agent,report,time.time()))
        self.assertGreater(database_size(application.DB),0)


class PackageTest(unittest.TestCase):
    def archive(self,path,members):
        with tarfile.open(path,'w:gz') as archive:
            for name,content in members.items():
                member=tarfile.TarInfo(name);member.size=len(content)
                archive.addfile(member,io.BytesIO(content))

    def test_download_rejects_corruption_and_cleans_partial(self):
        job={'id':1,'platform':'linux-source','size':3,'sha256':'0'*64}
        validate(job,'linux-source')
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'package.tar.gz'
            with patch('agent.remote_update.request',return_value=io.BytesIO(b'bad')):
                with self.assertRaises(ValueError):download({'agent_id':'pc'},job,target)
            self.assertEqual(list(Path(directory).iterdir()),[])

    def test_reject_traversal_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);package=root/'x.tar.gz'
            self.archive(package,{'../outside':b'bad'})
            with self.assertRaises(ValueError):extract(package,root/'out')
            with tarfile.open(package,'w:gz') as archive:
                member=tarfile.TarInfo('agent/client.py');member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd';archive.addfile(member)
            with self.assertRaises(ValueError):extract(package,root/'out')

    def test_linux_swap_and_rollback_preserve_old_code(self):
        for fail in (False,True):
            with self.subTest(fail=fail),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);current=root/'current';(current/'agent').mkdir(parents=True)
                (current/'agent/client.py').write_text('OLD=True')
                (current/'agent/requirements-linux.txt').write_text('psutil==7.2.2')
                package=root/'x.tar.gz';self.archive(package,{'agent/client.py':b'NEW=True','agent/VERSION':b'v2','agent/requirements-linux.txt':b'psutil==7.2.2'})
                calls=[]
                def execute(args,**kwargs):
                    calls.append(args)
                    if fail and 'is-active' in args:raise RuntimeError('failed')
                with patch('agent.update_worker.time.sleep'):
                    if fail:
                        with self.assertRaises(RuntimeError):install(package,{'id':1,'version':'v2'},execute,root)
                        self.assertIn('OLD',(current/'agent/client.py').read_text())
                    else:
                        install(package,{'id':1,'version':'v2'},execute,root)
                        self.assertIn('NEW',(current/'agent/client.py').read_text())
                        self.assertEqual((current/'agent/client.py').stat().st_mode & 0o777,0o644)
                        self.assertEqual((current/'agent').stat().st_mode & 0o777,0o755)
                        self.assertEqual((root/'releases').stat().st_mode & 0o777,0o755)
                        self.assertIn('OLD',(root/'previous-1/agent/client.py').read_text())
                self.assertTrue(any('stop' in args for args in calls))

class UpdateDiagnosticsTest(unittest.TestCase):
    def test_fixed_codes_are_shown_but_raw_exceptions_are_not(self):
        from server import app as application
        with tempfile.TemporaryDirectory() as directory:
            prior=application.DB;application.DB=str(Path(directory)/'db.sqlite3')
            try:
                client=TestClient(application.app)
                from server.security import limiter
                limiter.reset()
                with application.db() as c:
                    c.execute('INSERT INTO agents VALUES (?,?)',('pc',application.digest('key')))
                    now=time.time()
                    c.execute("INSERT INTO agent_update_jobs VALUES (1,'pc',1,'running','',?,?)",(now,now))
                response=client.post('/api/agent-update/pc/status',headers={'Authorization':'Bearer key'},json={'job_id':1,'status':'failed','error_code':'wait_exit','rollback':'restored','message':'TOKEN=SECRET'})
                self.assertEqual(response.status_code,200)
                with application.db() as c:message=c.execute('SELECT message FROM agent_update_jobs').fetchone()[0]
                self.assertIn('EXE',message);self.assertIn('восстановлен',message);self.assertNotIn('SECRET',message)
            finally:application.DB=prior
