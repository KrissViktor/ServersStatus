import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from fastapi.testclient import TestClient
from server import app as a


class AccessRolesTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter,login_limiter
        limiter.reset();login_limiter.reset()
        self.now=time.time();self.password='test-password-12345';salt='ab'*16;encoded=a.password_hash(self.password,salt)
        self.clients={}
        with a.db() as c:
            for name,role in [('admin','superadmin'),('reader','viewer'),('operator','administrator'),('owner','superadmin')]:
                c.execute('INSERT INTO users VALUES (?,?,?)',(name,salt,encoded))
                c.execute('INSERT INTO user_roles VALUES (?,?,1)',(name,role))
                c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest(name),self.now+3600))
                c.execute('INSERT INTO session_users VALUES (?,?)',(a.digest(name),name))
                client=TestClient(a.app,base_url='https://testserver');client.cookies.set('session',name);self.clients[name]=client
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
        self.report={'hostname':'SQL','cpu_percent':12,'memory_percent':40,'uptime_seconds':1000,'disks':[],'features':['console_v1'],'console':{'enabled':True,'shell':'powershell','identity':'PRIVATE'}}
        self.clients['admin'].post('/api/report/pc',headers={'Authorization':'Bearer key'},json=self.report)

    def post(self,action,**fields):
        return self.clients['admin'].post('/users/'+action,data={'csrf':a.digest('agent-management:admin'),**fields},follow_redirects=False)

    def test_viewer_is_current_only_and_cannot_discover_accounts_or_console(self):
        client=self.clients['reader'];html=client.get('/').text
        self.assertNotIn('href="/admin"',html);self.assertNotIn('href="/history/',html)
        self.assertNotIn('class="task-graph"',html);self.assertNotIn('id="chart-detail"',html)
        for path in ('/admin','/agents','/updates','/settings/pc','/history/pc','/events','/bot','/host','/windows/pc','/api/history/pc/detail?center='+str(self.now),'/api/history/pc/snapshot?report_id=1'):
            self.assertEqual(client.get(path).status_code,403,path)
        for path in ('/users','/console-access','/console-access/status','/api/servers/pc/console','/api/servers/pc/rdp/operations'):
            self.assertEqual(client.get(path).status_code,404,path)
        self.assertEqual(client.post('/users/create',data={}).status_code,404)
        self.assertEqual(client.post('/agents/flags',data={}).status_code,403)
        details=client.get('/servers/pc');self.assertEqual(details.status_code,200)
        for hidden in ('Суперадмин','superadmin','PRIVATE','remote-console','id="protection-toggle"','id="chart-detail"','Название в панели'):
            self.assertNotIn(hidden,details.text)
        self.assertEqual(client.get('/api/servers/pc/processes').status_code,200)
        # Agent ingestion remains authorized separately by its bearer key.
        self.assertEqual(client.post('/api/report/pc',headers={'Authorization':'Bearer key'},json=self.report).status_code,200)

    def test_administrator_has_history_and_settings_but_no_role_or_console_information(self):
        client=self.clients['operator']
        self.assertEqual(client.get('/history/pc').status_code,200)
        self.assertEqual(client.get('/settings/pc').status_code,200)
        for path in ('/','/admin','/agents','/servers/pc','/events'):
            response=client.get(path);self.assertEqual(response.status_code,200,path)
            for hidden in ('Суперадмин','superadmin','href="/users"','id="protection-toggle"','id="protection-dialog"','remote-console'):
                self.assertNotIn(hidden,response.text,path)
        for path in ('/users','/console-access','/console-access/status','/api/servers/pc/console','/api/servers/pc/rdp/operations'):
            self.assertEqual(client.get(path).status_code,404,path)
        client.cookies.set('__Host-console-access','forged')
        self.assertEqual(client.post('/api/servers/pc/console',json={}).status_code,404)
        self.assertEqual(client.post('/users/create',data={}).status_code,404)

    def test_full_accounts_see_users_but_console_still_requires_challenges(self):
        for name in ('admin','owner'):
            client=self.clients[name];self.assertEqual(client.get('/users').status_code,200)
            self.assertIn('Суперадмин',client.get('/users').text)
            self.assertIn('href="/users"',client.get('/admin').text)
            self.assertIn('id="protection-toggle"',client.get('/agents').text)
            self.assertEqual(client.get('/console-access/status').json(),{'unlocked':False})
            self.assertEqual(client.get('/api/servers/pc/console').status_code,403)

    def test_create_edit_disable_reset_delete_revoke_sessions_and_grants(self):
        self.assertEqual(self.post('create',name='new-user',password=self.password,role='viewer').status_code,303)
        self.assertEqual(self.post('create',name='NEW-USER',password=self.password,role='viewer').status_code,409)
        self.assertEqual(self.post('create',name='bad',password='short',role='superadmin').status_code,400)
        self.assertEqual(self.post('create',name='bad',password=self.password,role='unexpected').status_code,400)
        client=TestClient(a.app,base_url='https://testserver')
        self.assertEqual(client.post('/login',data={'username':'new-user','password':self.password},follow_redirects=False).status_code,303)
        with a.db() as c:
            token=c.execute("SELECT token FROM session_users WHERE name='new-user'").fetchone()[0]
            c.execute('INSERT INTO console_grants VALUES (?,?)',(token,self.now+1800))
            c.execute('INSERT INTO console_grant_tokens VALUES (?,?)',(token,'fake'))
        self.assertEqual(self.post('edit',name='new-user',role='administrator',enabled='1').status_code,303)
        self.assertIn('Войти',client.get('/').text)
        with a.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM sessions WHERE token=?',(token,)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT count(*) FROM console_grants WHERE session=?',(token,)).fetchone()[0],0)
        self.assertEqual(self.post('password',name='new-user',password='changed-password-123').status_code,303)
        self.assertEqual(self.post('edit',name='new-user',role='administrator').status_code,303)
        self.assertEqual(client.post('/login',data={'username':'new-user','password':'changed-password-123'},follow_redirects=False).status_code,401)
        self.assertEqual(self.post('delete',name='new-user',confirmation='wrong').status_code,400)
        self.assertEqual(self.post('delete',name='new-user',confirmation='new-user').status_code,303)
        with a.db() as c:self.assertIsNone(c.execute("SELECT 1 FROM users WHERE name='new-user'").fetchone())

    def test_csrf_self_protection_private_audit_and_unowned_session(self):
        self.assertEqual(self.post('edit',name='reader',role='administrator',enabled='1',csrf='bad').status_code,403)
        self.assertEqual(self.post('delete',name='admin',confirmation='admin').status_code,400)
        self.assertEqual(self.post('edit',name='admin',role='viewer',enabled='1').status_code,400)
        owner=self.clients['owner'];csrf=a.digest('agent-management:owner')
        self.assertEqual(owner.post('/users/edit',data={'csrf':csrf,'name':'owner','role':'viewer','enabled':'1'}).status_code,400)
        self.post('create',name='secret-owner',password=self.password,role='superadmin')
        self.assertNotIn('secret-owner',self.clients['operator'].get('/events').text)
        self.assertIn('secret-owner',self.clients['admin'].get('/events').text)
        with a.db() as c:c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('legacy'),self.now+3600))
        anonymous=TestClient(a.app,base_url='https://testserver');anonymous.cookies.set('session','legacy')
        self.assertIn('Войти',anonymous.get('/').text)

    def test_admin_name_cannot_be_created_with_misleading_lower_access(self):
        with a.db() as c:
            c.execute("DELETE FROM session_users WHERE name='admin'")
            c.execute("DELETE FROM users WHERE name='admin'")
            c.execute("DELETE FROM user_roles WHERE name='admin'")
        owner=self.clients['owner'];csrf=a.digest('agent-management:owner')
        response=owner.post('/users/create',data={'csrf':csrf,'name':'admin','role':'viewer','password':self.password})
        self.assertEqual(response.status_code,400)
        with a.db() as c:self.assertIsNone(c.execute("SELECT name FROM users WHERE name='admin'").fetchone())

    def test_legacy_migration_preserves_admin_and_invalidates_identityless_sessions(self):
        old=str(Path(self.tmp.name)/'old.sqlite3')
        c=sqlite3.connect(old);c.executescript('CREATE TABLE users(name TEXT PRIMARY KEY,salt TEXT,password TEXT);CREATE TABLE sessions(token TEXT PRIMARY KEY,expires REAL);')
        c.execute('INSERT INTO users VALUES (?,?,?)',('admin','ab'*16,a.password_hash(self.password,'ab'*16)))
        c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('old-token'),self.now+3600));c.commit();c.close()
        a.DB=old
        with a.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT role FROM user_roles WHERE name='admin'").fetchone()[0],'superadmin')
        client=TestClient(a.app,base_url='https://testserver')
        self.assertEqual(client.post('/login',data={'username':'admin','password':self.password},follow_redirects=False).status_code,303)
        self.assertEqual(client.get('/users').status_code,200)
