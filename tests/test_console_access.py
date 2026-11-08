import json
from pathlib import Path
import re
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import app as a
from server.console_access import pin_hash
from server.console import history_cutoff


class ConsoleAccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(a.app,base_url='https://testserver');self.client.cookies.set('session','session')
        self.csrf=a.digest('agent-management:session')
        now=time.time();salt='ab'*16
        self.data={'hostname':'pc','cpu_percent':0,'memory_percent':1,'uptime_seconds':1000,'disks':[],'features':['console_v1'],'console':{'enabled':True,'streaming':True,'interactive_input':True,'shell':'bash','identity':'agent'}}
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('session'),now+3600))
            c.execute('INSERT INTO agents VALUES (?,?)',('pc',a.digest('key')))
            c.execute('INSERT INTO latest_reports VALUES (?,?,?)',('pc',now,json.dumps(self.data)))
            c.execute('INSERT INTO console_access_config VALUES (1,?,?,?)',(salt,pin_hash('1234',salt),secrets.token_hex(32)))
        self.codes=[]
        self.sender=patch('server.console_access.send_code',side_effect=lambda code,step:self.codes.append((code,step)))
        self.sender.start();self.addCleanup(self.sender.stop)

    def enter(self,code):return self.client.post('/console-access',data={'csrf':self.csrf,'code':code},follow_redirects=False)
    def unlock(self):
        self.assertEqual(self.enter('1234').status_code,303)
        self.assertEqual(self.enter(self.codes[-1][0]).status_code,303)
        self.assertEqual(self.enter(self.codes[-1][0]).status_code,303)

    def test_administration_navigation_and_protection_entry(self):
        anonymous=TestClient(a.app,base_url='https://testserver')
        self.assertEqual(anonymous.get('/admin',follow_redirects=False).status_code,303)
        home=self.client.get('/').text
        header=re.search(r'<header class="topbar">(.*?)</header>',home,re.S).group(1)
        self.assertIn('href="/admin"',header)
        for url in ('/host','/updates','/bot','/events','/agents'):
            self.assertNotIn('href="'+url+'"',header)
        admin=self.client.get('/admin')
        self.assertEqual(admin.status_code,200)
        for url in ('/host','/updates','/bot','/events','/agents'):
            self.assertIn('href="'+url+'"',admin.text)
        self.assertRegex(home,r'<button hidden[^>]*id="protection-toggle"')
        agents=self.client.get('/agents').text
        self.assertRegex(agents,r'<button data-protection-entry="true"[^>]*id="protection-toggle"')

    def test_hidden_html_and_api_until_all_three_steps(self):
        html=self.client.get('/servers/pc').text
        self.assertNotIn('Мини-консоль',html);self.assertNotIn('remote-console',html);self.assertNotIn('console_v1',html)
        self.assertIn('Снять защиту',html)
        self.assertEqual(self.client.get('/api/servers/pc/console').status_code,403)
        self.assertEqual(self.client.post('/api/servers/pc/console',json={}).status_code,403)
        self.assertEqual(self.enter('1234').status_code,303)
        numeric=self.codes[-1][0];self.assertRegex(numeric,r'^\d{6}$')
        self.assertFalse(self.client.get('/console-access/status').json()['unlocked'])
        self.assertEqual(self.enter(numeric).status_code,303)
        mixed=self.codes[-1][0];self.assertEqual(len(mixed),6)
        self.assertTrue(any(v.isdigit() for v in mixed));self.assertTrue(any(v.isalpha() for v in mixed));self.assertRegex(mixed,r'^[A-Za-z0-9]{6}$')
        with a.db() as c:
            challenge=dict(c.execute('SELECT * FROM console_challenges').fetchone())
            self.assertNotEqual(challenge['digest'],mixed)
        self.assertFalse(self.client.get('/console-access/status').json()['unlocked'])
        self.assertEqual(self.enter(mixed).status_code,303)
        self.assertIn('Мини-консоль',self.client.get('/servers/pc').text)
        self.assertEqual(self.client.get('/api/servers/pc/console').status_code,200)
        self.assertEqual([stage for _,stage in self.codes],[2,3])

    def test_wrong_codes_block_after_two_and_do_not_send(self):
        self.assertEqual(self.enter('9999').status_code,400)
        self.assertEqual(self.enter('9999').status_code,400)
        self.assertEqual(self.enter('1234').status_code,400)
        self.assertEqual(self.codes,[])
        with a.db() as c:
            row=c.execute("SELECT blocked_until FROM auth_guard WHERE address='console:testclient'").fetchone()
            self.assertGreater(int(row[0]),time.time()+850)

    def test_expired_and_cross_session_codes_cannot_unlock(self):
        self.enter('1234');code=self.codes[-1][0]
        with a.db() as c:c.execute('UPDATE console_challenges SET expires=?',(time.time()-1,))
        self.assertEqual(self.enter(code).status_code,400)
        self.assertFalse(self.client.get('/console-access/status').json()['unlocked'])
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('other'),time.time()+3600))
        self.client.cookies.set('session','other');self.csrf=a.digest('agent-management:other')
        self.assertEqual(self.enter(code).status_code,400)
        self.assertFalse(self.client.get('/console-access/status').json()['unlocked'])

    def test_telegram_failure_is_closed_and_redacted(self):
        with patch('server.console_access.send_code',side_effect=RuntimeError('SECRET_TOKEN')):
            response=self.enter('1234')
        self.assertEqual(response.status_code,400);self.assertNotIn('SECRET_TOKEN',response.text)
        self.assertFalse(self.client.get('/console-access/status').json()['unlocked'])
        with a.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM console_challenges').fetchone()[0],0)

    def test_csrf_lock_and_lease_expiration(self):
        self.assertEqual(self.client.post('/console-access',data={'code':'1234'}).status_code,403)
        self.unlock()
        self.assertEqual(self.client.post('/console-access/lock',data={}).status_code,403)
        self.assertTrue(self.client.get('/console-access/status').json()['unlocked'])
        with a.db() as c:c.execute('UPDATE console_grants SET expires=?',(time.time()-1,))
        self.assertEqual(self.client.get('/api/servers/pc/console').status_code,403)
        self.unlock()
        self.assertEqual(self.client.post('/console-access/lock',data={'csrf':self.csrf},follow_redirects=False).status_code,303)
        self.assertNotIn('Мини-консоль',self.client.get('/servers/pc').text)

    def test_hour_archive_cleanup_pagination_and_monotonic_ids(self):
        self.unlock();now=time.time();cutoff=history_cutoff(now)
        with a.db() as c:
            for identifier,created in [(1,cutoff-1),(2,cutoff+100),(3,now-7200),(4,now-100)]:
                c.execute("INSERT INTO console_jobs VALUES (?,'pc','test',30,'succeeded',?,?,?,'{}')",(identifier,created,created+90,created))
        recent=self.client.get('/api/servers/pc/console').json()['jobs']
        self.assertEqual([j['id'] for j in recent],[4])
        archived=self.client.get('/api/servers/pc/console?archive=true').json()['jobs']
        self.assertEqual([j['id'] for j in archived],[4,3,2])
        response=self.client.post('/api/servers/pc/console',json={'csrf':self.csrf,'confirmation':'pc','command':'echo test','timeout':5})
        identifier=response.json()['id'];self.assertGreater(identifier,4)
        with a.db() as c:c.execute('DELETE FROM console_jobs')
        response=self.client.post('/api/servers/pc/console',json={'csrf':self.csrf,'confirmation':'pc','command':'echo test','timeout':5})
        self.assertGreater(response.json()['id'],identifier)

    def test_archive_loads_more_than_100_without_truncating_storage(self):
        self.unlock();now=time.time()
        with a.db() as c:
            c.executemany("INSERT INTO console_jobs VALUES (?,'pc','test',30,'succeeded',?,?,?,'{}')",[(i,now-10000,now-9990,now-9990) for i in range(1,121)])
        result=self.client.get('/api/servers/pc/console?archive=true').json()
        self.assertEqual(len(result['jobs']),100);self.assertTrue(result['more'])
        older=self.client.get('/api/servers/pc/console?archive=true&before='+str(result['next'])).json()
        self.assertEqual(len(older['jobs']),20)
        with a.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM console_jobs').fetchone()[0],120)

    def test_primary_cookie_alone_cannot_reuse_unlocked_grant(self):
        self.unlock()
        other=TestClient(a.app,base_url='https://testserver');other.cookies.set('session','session')
        self.assertEqual(other.get('/api/servers/pc/console').status_code,403)
        self.assertNotIn('Мини-консоль',other.get('/servers/pc').text)
        self.assertEqual(self.client.get('/api/servers/pc/console').status_code,200)

    def test_background_retention_and_no_fixed_command_limit(self):
        from server.retention import cleanup
        self.unlock();now=time.time()
        with a.db() as c:
            old=history_cutoff(now)-1
            c.execute("INSERT INTO console_jobs VALUES (1,'pc','old',30,'succeeded',?,?,?,'{}')",(old,old+90,old))
            cleanup(c,now)
            self.assertEqual(c.execute('SELECT count(*) FROM console_jobs').fetchone()[0],0)
            c.executemany("INSERT INTO console_jobs VALUES (?,'pc','test',30,'succeeded',?,?,?,'{}')",[(i,now-10000,now-9990,now-9990) for i in range(2,123)])
        response=self.client.post('/api/servers/pc/console',json={'csrf':self.csrf,'confirmation':'pc','command':'echo test','timeout':5})
        self.assertEqual(response.status_code,200)
        with a.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM console_jobs').fetchone()[0],122)

    def test_locked_journal_does_not_reveal_console_records(self):
        with a.db() as c:c.execute('INSERT INTO events(received,agent,category,level,message) VALUES (?,?,?,?,?)',(time.time(),'pc','console','info','PRIVATE_CONSOLE_RECORD'))
        self.assertNotIn('PRIVATE_CONSOLE_RECORD',self.client.get('/events').text)
        self.unlock()
        self.assertIn('PRIVATE_CONSOLE_RECORD',self.client.get('/events').text)

    def test_public_api_schema_does_not_reveal_protected_routes(self):
        self.assertEqual(self.client.get('/openapi.json').status_code,404)
        self.assertEqual(self.client.get('/docs').status_code,404)

    def test_modal_fragments_and_thirty_minute_cookie(self):
        started=time.time()
        fragment=self.client.get('/console-access?modal=1')
        self.assertNotIn('<html',fragment.text);self.assertIn('Шаг 1 из 3',fragment.text)
        def submit(code):return self.client.post('/console-access?modal=1',data={'csrf':self.csrf,'code':code},follow_redirects=False)
        response=submit('1234');self.assertEqual(response.status_code,200);self.assertIn('Шаг 2 из 3',response.text)
        response=submit(self.codes[-1][0]);self.assertEqual(response.status_code,200);self.assertIn('Шаг 3 из 3',response.text)
        response=submit(self.codes[-1][0]);self.assertEqual(response.status_code,200);self.assertIn('30 минут',response.text)
        self.assertIn('Max-Age=1800',response.headers['set-cookie'])
        with a.db() as c:self.assertGreaterEqual(c.execute('SELECT expires FROM console_grants').fetchone()[0],started+1800)
        self.assertTrue(self.client.get('/console-access/status').json()['unlocked'])
        response=self.client.post('/console-access/lock?modal=1',data={'csrf':self.csrf},follow_redirects=False)
        self.assertEqual(response.status_code,200);self.assertNotIn('<html',response.text)
        self.assertFalse(self.client.get('/console-access/status').json()['unlocked'])
