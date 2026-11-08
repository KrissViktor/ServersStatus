import base64
import json
from pathlib import Path
import re
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from server import app as a
from server.rdp_control import command


class RdpControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(a.app,base_url='https://testserver')
        self.client.cookies.set('session','test');self.client.cookies.set('__Host-console-access','grant')
        self.csrf=a.digest('agent-management:test');now=time.time()
        self.target={'session_id':12,'username':'Пользователь','domain':'DOMAIN','logon_at':now-1000}
        self.report={'hostname':'SQL-TEST','cpu_percent':1,'memory_percent':20,'uptime_seconds':10000,'system':{'os':'Windows'},'disks':[],'features':['console_v1','rdp_details_v1'],'console':{'enabled':True,'shell':'powershell','identity':'SYSTEM'},'rdp':{'status':'available','sessions':[{**self.target,'state':'active'}]}}
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('test'),now+3600))
            c.execute("INSERT OR IGNORE INTO users VALUES ('admin',?,?)",('00'*16,'0'*128))
            c.execute("INSERT INTO session_users VALUES (?,'admin')",(a.digest('test'),))
            c.execute('INSERT INTO console_grants VALUES (?,?)',(a.digest('test'),now+1800))
            c.execute('INSERT INTO console_grant_tokens VALUES (?,?)',(a.digest('test'),a.digest('grant')))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
            c.execute('INSERT INTO agents VALUES (?,?)',('other',a.digest('other-key')))
        self.update()

    def update(self,**changes):
        self.report.update(changes)
        response=self.client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=self.report)
        self.assertEqual(response.status_code,200)

    def payload(self,**changes):return {**self.target,'csrf':self.csrf,'action':'disconnect',**changes}
    def queue(self,**changes):return self.client.post('/api/servers/pc/rdp',json=self.payload(**changes))

    def test_protection_csrf_and_target_identity(self):
        self.assertEqual(self.queue(csrf='bad').status_code,403)
        for changes in ({'username':'other'},{'domain':'OTHER'},{'logon_at':self.target['logon_at']+10},{'session_id':99}):
            self.assertEqual(self.queue(**changes).status_code,409)
        self.assertEqual(self.queue(action='delete_user').status_code,422)
        self.assertEqual(self.queue(action='logoff',confirmation='wrong').status_code,400)
        self.client.cookies.delete('__Host-console-access')
        self.assertEqual(self.queue().status_code,403)
        self.assertEqual(self.client.get('/api/servers/pc/rdp/operations').status_code,403)
        self.assertEqual(self.client.post('/api/servers/pc/rdp/shadow',json=self.payload()).status_code,403)
        html=self.client.get('/servers/pc').text
        self.assertNotIn('data-rdp-target=',html)
        self.client.cookies.clear();self.assertEqual(self.queue().status_code,401)

    def test_durable_queue_commands_and_history_labels(self):
        response=self.queue();self.assertEqual(response.status_code,200)
        identifier=response.json()['id']
        self.assertEqual(self.queue().status_code,409)
        # Exactly the existing console worker receives the guarded native action.
        job=self.client.get('/api/console/pc',headers={'Authorization':'Bearer key'}).json()['job']
        self.assertEqual(job['id'],identifier);self.assertLessEqual(len(job['command']),4000)
        payload=re.search(r"FromBase64String\('([^']+)'\)",job['command']).group(1)
        self.assertEqual(json.loads(base64.b64decode(payload)),{**self.target,'action':'disconnect'})
        self.assertIn('WTSDisconnectSession',job['command']);self.assertIn('LogonTime',job['command'])
        self.assertEqual(self.client.post('/api/console/pc/status',headers={'Authorization':'Bearer other-key'},json={'id':identifier,'status':'running'}).status_code,401)
        for status in ('running','succeeded'):
            result=self.client.post('/api/console/pc/status',headers={'Authorization':'Bearer key'},json={'id':identifier,'status':status,'output':'Windows accepted action','exit_code':0})
            self.assertEqual(result.status_code,200)
        operations=self.client.get('/api/servers/pc/rdp/operations')
        self.assertEqual(operations.headers['cache-control'],'no-store')
        self.assertEqual(operations.json()['jobs'][0]['status'],'succeeded')
        history=self.client.get('/api/servers/pc/console').json()['jobs'][0]
        self.assertIn('Отключить RDP',history['command']);self.assertNotIn('Add-Type',history['command'])
        with a.db() as c:self.assertIn('Add-Type',c.execute('SELECT command FROM console_jobs WHERE id=?',(identifier,)).fetchone()[0])
        self.assertIsNone(self.client.get('/api/console/pc',headers={'Authorization':'Bearer key'}).json()['job'])

    def test_logoff_requires_name_and_offline_or_disabled_refuses(self):
        session={**self.target,'state':'disconnected'}
        self.update(rdp={'status':'available','sessions':[session]})
        self.assertEqual(self.queue().status_code,409)
        response=self.queue(action='logoff',confirmation=self.target['username'])
        self.assertEqual(response.status_code,200)
        with a.db() as c:
            c.execute("UPDATE console_jobs SET status='succeeded'")
            c.execute('UPDATE latest_reports SET received=? WHERE agent=?',(time.time()-61,'pc'))
        self.assertEqual(self.queue(action='logoff',confirmation=self.target['username']).status_code,409)
        self.update(console={'enabled':False,'shell':'powershell','identity':'SYSTEM'})
        self.assertEqual(self.queue(action='logoff',confirmation=self.target['username']).status_code,409)

    def test_shadow_download_is_bounded_and_uses_consent_and_no_stored_password(self):
        response=self.client.post('/api/servers/pc/rdp/shadow',json=self.payload())
        self.assertEqual(response.status_code,200)
        self.assertIn('mstsc.exe /v:"SQL-TEST" /shadow:12 /control /prompt',response.text)
        self.assertNotIn('noConsentPrompt',response.text);self.assertNotIn('password',response.text)
        self.assertIn('.cmd',response.headers['content-disposition'])
        self.update(hostname='SQL&calc.exe')
        self.assertEqual(self.client.post('/api/servers/pc/rdp/shadow',json=self.payload()).status_code,409)
        self.update(hostname='SQL-TEST',rdp={'status':'available','sessions':[{**self.target,'state':'disconnected'}]})
        self.assertEqual(self.client.post('/api/servers/pc/rdp/shadow',json=self.payload()).status_code,409)

    def test_typed_controls_and_expired_queue(self):
        html=self.client.get('/servers/pc').text
        self.assertIn('data-rdp-target=',html);self.assertIn('data-rdp-action="disconnect"',html)
        self.assertIn('data-rdp-action="logoff"',html);self.assertIn('data-rdp-action="shadow"',html)
        identifier=self.queue().json()['id']
        with a.db() as c:c.execute('UPDATE console_jobs SET expires=? WHERE id=?',(time.time()-1,identifier))
        self.assertIsNone(self.client.get('/api/console/pc',headers={'Authorization':'Bearer key'}).json()['job'])
        self.assertEqual(self.client.get('/api/servers/pc/rdp/operations').json()['jobs'][0]['status'],'expired')
        self.assertEqual(self.queue().status_code,200)

    def test_payload_strings_are_not_interpolated_into_powershell(self):
        operation={**self.target,'username':"'; Start-Process calc; #",'action':'logoff'}
        script=command(operation)
        self.assertNotIn(operation['username'],script)
        encoded=re.search(r"FromBase64String\('([^']+)'\)",script).group(1)
        self.assertEqual(json.loads(base64.b64decode(encoded)),operation)
