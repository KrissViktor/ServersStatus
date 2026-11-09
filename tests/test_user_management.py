import time
import unittest
from fastapi.testclient import TestClient
import test_access_roles as fixture
from server import app as a
from server.security import account_blocked_seconds,failed_account_login
from server.users import stamp

class UserManagementTest(unittest.TestCase):
    setUp=fixture.AccessRolesTest.setUp
    post=fixture.AccessRolesTest.post
    def login(self,name,password,address):
        return TestClient(a.app,base_url='https://testserver',client=(address,1234)).post('/login',data={'username':name,'password':password},follow_redirects=False)
    def test_cyrillic_viewer_creation_duplicate_and_friendly_error(self):
        self.assertEqual(self.post('create',name='Иван-тест',password=self.password,role='viewer').status_code,303)
        response=self.post('create',name='иван-ТЕСТ',password=self.password,role='viewer')
        self.assertEqual(response.status_code,409);self.assertIn('text/html',response.headers['content-type']);self.assertIn('уже занят',response.text)
        response=self.post('create',name='Имя с пробелом',password=self.password,role='viewer')
        self.assertEqual(response.status_code,400);self.assertIn('без пробелов',response.text);self.assertIn('value="Имя с пробелом"',response.text);self.assertNotIn(self.password,response.text)
        logged=self.login('Иван-тест',self.password,'198.51.100.10');self.assertEqual(logged.status_code,303)
        with a.db() as c:self.assertEqual(c.execute("SELECT role FROM user_roles WHERE name='Иван-тест'").fetchone()[0],'viewer')
    def test_disable_enable_revokes_sessions_and_cannot_disable_self(self):
        response=self.post('toggle',name='reader',enabled='0');self.assertEqual(response.status_code,303)
        self.assertIn('action="/login"',self.clients['reader'].get('/').text)
        self.assertEqual(self.clients['reader'].get('/api/servers/pc/processes').status_code,401)
        self.assertEqual(self.post('edit',name='reader',role='viewer',edit_access_only='1').status_code,303)
        self.assertEqual(self.login('reader',self.password,'198.51.100.11').status_code,401)
        self.assertEqual(self.post('toggle',name='reader',enabled='1').status_code,303)
        self.assertEqual(self.login('reader',self.password,'198.51.100.12').status_code,303)
        self.assertEqual(self.post('toggle',name='admin',enabled='0').status_code,400)
        self.assertEqual(self.clients['owner'].post('/users/toggle',data={'csrf':a.digest('agent-management:owner'),'name':'owner','enabled':'0'}).status_code,400)
        self.assertEqual(self.clients['operator'].post('/users/toggle',data={}).status_code,404)
    def test_two_account_failures_across_ips_block_correct_password_and_show_msk(self):
        self.assertEqual(self.login('reader','wrong','198.51.100.20').status_code,401)
        self.assertEqual(self.login('reader','wrong','198.51.100.21').status_code,429)
        response=self.login('reader',self.password,'198.51.100.22');self.assertEqual(response.status_code,429);self.assertGreater(int(response.headers['retry-after']),0)
        with a.db() as c:
            guard=dict(c.execute("SELECT * FROM account_auth_guard WHERE name='reader'").fetchone());self.assertEqual(guard['strikes'],1)
        html=self.clients['admin'].get('/users').text;self.assertIn(stamp(guard['blocked_until']),html);self.assertIn('Снять блокировку входа',html)
        self.assertEqual(self.post('unblock',name='reader').status_code,303)
        self.assertEqual(self.login('reader',self.password,'198.51.100.23').status_code,303)
        with a.db() as c:self.assertEqual(c.execute("SELECT strikes FROM account_auth_guard WHERE name='reader'").fetchone()[0],1)
    def test_ip_blocks_are_separate_and_unblock_is_protected(self):
        for _ in range(2):self.login('unknown','bad','198.51.100.30')
        html=self.clients['admin'].get('/users').text;self.assertIn('198.51.100.30',html);self.assertIn('Снять блокировку IP',html)
        self.assertEqual(self.clients['operator'].get('/users').status_code,404)
        self.assertEqual(self.post('unblock-ip',address='198.51.100.30',csrf='wrong').status_code,403)
        self.assertEqual(self.post('unblock-ip',address='198.51.100.30').status_code,303)
        with a.db() as c:
            self.assertEqual(c.execute("SELECT blocked_until FROM auth_guard WHERE address='198.51.100.30'").fetchone()[0],'0');self.assertEqual(c.execute('SELECT COUNT(*) FROM account_auth_guard').fetchone()[0],0)
    def test_escalation_survives_expiry_and_large_deadline_renders(self):
        with a.db() as c:
            self.assertEqual(failed_account_login(c,'reader',1000),0);self.assertEqual(failed_account_login(c,'reader',1000),900)
            self.assertEqual(account_blocked_seconds(c,'reader',1001),899)
            self.assertEqual(failed_account_login(c,'reader',1900),0);self.assertEqual(failed_account_login(c,'reader',1900),2700)
            c.execute("UPDATE account_auth_guard SET strikes=100,failures=0,blocked_until='0' WHERE name='reader'")
            failed_account_login(c,'reader',time.time());failed_account_login(c,'reader',time.time())
        self.assertEqual(self.clients['admin'].get('/users').status_code,200)
