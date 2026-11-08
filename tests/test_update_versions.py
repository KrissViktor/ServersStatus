import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from server.update_versions import choices,stamp
from server import app as a
from server.github_updates import sync
from agent.github_releases import validate_manifest,BASE,PLATFORMS


class VersionChoiceTest(unittest.TestCase):
    def test_dates_not_hash_or_insertion_order_and_platform_isolation(self):
        packages=[{'id':40,'platform':'windows-x64','version':'old','commit_at':100,'built_at':110},
                  {'id':30,'platform':'windows-x64','version':'current','commit_at':200,'built_at':210},
                  {'id':20,'platform':'windows-x64','version':'middle','commit_at':300,'built_at':310},
                  {'id':10,'platform':'windows-x64','version':'newest','commit_at':400,'built_at':410},
                  {'id':50,'platform':'linux-source','version':'other','commit_at':500,'built_at':510}]
        result,current=choices(packages,'windows-x64','current')
        self.assertEqual([(p['version'],p['label']) for p in result],[('newest','New'),('old','Older')]);self.assertEqual(current,210)
        result,_=choices(packages,'windows-x64','newest')
        self.assertEqual([(p['version'],p['label']) for p in result],[('middle','Older')])
        result,_=choices(packages,'windows-x64','old')
        self.assertEqual([(p['version'],p['label']) for p in result],[('newest','New')])

    def test_current_not_in_catalog_and_legacy_date_fallback(self):
        packages=[{'id':1,'platform':'windows-x64','version':'old'},{'id':2,'platform':'windows-x64','version':'new'}]
        with patch('server.update_versions.commit_date',side_effect=lambda v:{'old':100,'current':200,'new':300}.get(v)):
            result,current=choices(packages,'windows-x64','current')
        self.assertEqual(current,200);self.assertEqual(len(result),2)
        self.assertEqual(stamp(0),'дата не указана')
        self.assertEqual(stamp(1700000000),'15.11.2023 01:13')


class UpdatePageTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(a.app);self.client.cookies.set('session','session')
        now=time.time()
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('session'),now+3600))
            c.execute("INSERT OR IGNORE INTO users VALUES ('admin',?,?)",('00'*16,'0'*128))
            c.execute("INSERT INTO session_users VALUES (?,'admin')",(a.digest('session'),))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
            for index,version in enumerate(['old','current','middle','newest'],1):
                c.execute('INSERT INTO update_packages VALUES (?,?,?,?,?,?)',(index,'windows-x64',version,str(index)*64,10,'/tmp/fake'))
                c.execute('INSERT INTO update_package_dates VALUES (?,?,?)',(index,1700000000+index*100,1700000000+index*100))
        self.headers={'Authorization':'Bearer key'}
        self.data={'hostname':'pc','cpu_percent':0,'memory_percent':1,'uptime_seconds':1000,'disks':[],'agent_platform':'windows-x64','agent_version':'current','features':['remote_update_v1']}
        self.client.post('/api/report/pc',headers=self.headers,json=self.data)

    def test_limited_selector_and_timeline_survive_confirmation(self):
        html=self.client.get('/updates').text
        select=re.search(r'<select name="package".*?</select>',html,re.S).group(0)
        self.assertIn('newest (New)',select);self.assertIn('old (Older)',select);self.assertNotIn('middle',select);self.assertNotIn('current',select)
        self.assertRegex(select,r'\(New\).*?\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}')
        csrf=re.search('name="csrf" value="([^"]+)"',html).group(1)
        response=self.client.post('/updates/pc',data={'csrf':csrf,'package':4},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        job=self.client.get('/api/agent-update/pc',headers=self.headers).json()['job']
        self.client.post('/api/agent-update/pc/status',headers=self.headers,json={'job_id':job['id'],'status':'running','message':'Скачивание проверенного пакета'})
        self.client.post('/api/agent-update/pc/status',headers=self.headers,json={'job_id':job['id'],'status':'running','error_code':'awaiting_version'})
        self.client.post('/api/report/pc',headers=self.headers,json={**self.data,'agent_version':'newest'})
        with a.db() as c:
            events=c.execute('SELECT status,message FROM update_job_events ORDER BY id').fetchall()
            self.assertEqual([r['status'] for r in events],['queued','running','running','applied'])
            self.assertEqual(c.execute('SELECT from_version FROM update_job_context').fetchone()[0],'current')
        html=self.client.get('/updates').text
        self.assertIn('История обновлений',html);self.assertIn('Скачивание пакета',html)
        self.assertIn('Версия подтверждена',html)

    def test_channel_imports_predecessor_and_dates_without_duplication(self):
        def release(platform):
            kind,file=PLATFORMS[platform]
            def build(version):return {'schema':1,'platform':platform,'version':version,'sha256':hashlib.sha256((platform+version).encode()).hexdigest(),'size':1,'download_url':BASE+'agent-'+kind+'-'+version+'/'+file,'built_at':1700000000,'commit_at':1699999999}
            data=build('abcdef123456');data['previous']=build('123456abcdef');return data
        with patch('server.github_updates.manifest',side_effect=release):sync(a.db);sync(a.db)
        with a.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM github_packages').fetchone()[0],4)
            self.assertEqual(c.execute('SELECT count(*) FROM update_package_dates WHERE package>4').fetchone()[0],4)
