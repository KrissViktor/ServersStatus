import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import app as a
from server.notifications import tick


class AgentFlagsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        from server.security import limiter
        limiter.reset()
        self.client=TestClient(a.app,base_url='https://testserver');self.client.cookies.set('session','test')
        self.csrf=a.digest('agent-management:test');self.now=time.time()
        self.report={'hostname':'SQL-HOST','cpu_percent':10,'memory_percent':25,'uptime_seconds':1000,'disks':[]}
        with a.db() as c:
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('test'),self.now+3600))
            for agent in ('pc','other'):
                c.execute('INSERT INTO agents VALUES (?,?)',(agent,a.digest('key')))
                c.execute('INSERT INTO latest_reports VALUES (?,?,?)',(agent,self.now,json.dumps(self.report)))
            c.execute('INSERT INTO agent_profiles VALUES (?,?)',('pc','Основной SQL'))

    def flag(self,flag,enabled,agent='pc',**changes):
        data={'csrf':self.csrf,'agent_id':agent,'flag':flag,**changes}
        if enabled:data['enabled']='1'
        return self.client.post('/agents/flags',data=data,headers={'Accept':'application/json'},follow_redirects=False)

    def test_defaults_names_independent_flags_and_name_edit(self):
        row=next(row for row in a.agent_rows() if row['id']=='pc')
        self.assertEqual((row['important'],row['active']),(1,1))
        html=self.client.get('/agents').text
        self.assertIn('Основной SQL',html);self.assertIn('ID агента: pc',html)
        self.assertIn('class="agent-grid"',html);self.assertIn('aria-expanded="false"',html)
        self.assertEqual(self.flag('active',False).status_code,200)
        self.assertEqual(self.flag('important',False).status_code,200)
        self.assertEqual(self.flag('active',True).status_code,200)
        with a.db() as c:
            row=c.execute('SELECT * FROM agent_flags WHERE agent=?',('pc',)).fetchone()
            self.assertEqual((row['important'],row['active']),(0,1))
        response=self.client.post('/servers/pc/name',data={'csrf':self.csrf,'display_name':'Новое имя','return_to':'/agents'},follow_redirects=False)
        self.assertEqual(response.headers['location'],'/agents')
        self.assertIn('Новое имя',self.client.get('/agents').text)

    def test_authorization_csrf_unknown_agent_and_field_validation(self):
        self.assertEqual(self.flag('active',False,csrf='bad').status_code,403)
        self.assertEqual(self.flag('active',False,agent='missing').status_code,404)
        self.assertEqual(self.flag('unexpected_column',False).status_code,400)
        self.assertEqual(self.client.post('/agents/flags',data={'csrf':self.csrf,'agent_id':'pc','flag':'active','enabled':'0'}).status_code,400)
        self.client.cookies.clear();self.assertEqual(self.flag('active',False).status_code,401)

    def test_active_servers_above_collapsed_inactive_and_search_finds_both(self):
        self.flag('active',False)
        html=self.client.get('/').text
        position=html.index('id="inactive-servers"')
        self.assertLess(html.index('data-server-id="other"'),position)
        self.assertGreater(html.index('data-server-id="pc"'),position)
        self.assertIn('Не активные',html)
        detail=html[position:html.index('<summary>',position)]
        self.assertNotIn('open',detail)
        search=self.client.get('/?q=Основной').text
        self.assertIn('data-server-id="pc"',search);self.assertNotIn('data-server-id="other"',search)
        self.assertIn('open',search[search.index('id="inactive-servers"'):search.index('<summary>',search.index('id="inactive-servers"'))])
        self.assertEqual(self.client.get('/servers/pc').status_code,200)

    def test_important_stops_alerts_recovery_and_retry_and_can_reenable(self):
        with a.db() as c:c.execute('UPDATE latest_reports SET received=?',(self.now-200,))
        sent=[]
        with patch('server.notifications.delivery_window',return_value=True):
            self.assertEqual(tick(a.db,sent.append,self.now),(2,0))
            self.flag('important',False)
            with a.db() as c:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM telegram_state WHERE agent=?',('pc',)).fetchone()[0],0)
                c.execute('UPDATE latest_reports SET received=? WHERE agent=?',(self.now,'pc'))
            sent.clear();self.assertEqual(tick(a.db,sent.append,self.now),(0,0))
            self.flag('important',True)
            with a.db() as c:c.execute('UPDATE latest_reports SET received=? WHERE agent=?',(self.now-200,'pc'))
            self.assertEqual(tick(a.db,sent.append,self.now),(1,0))
            self.flag('active',False)
            self.assertEqual(tick(a.db,sent.append,self.now),(0,0))

    def test_disabling_during_batch_skips_already_selected_message(self):
        with a.db() as c:c.execute('UPDATE latest_reports SET received=?',(self.now-200,))
        sent=[]
        def sender(text):
            sent.append(text)
            self.flag('important',False)
        with patch('server.notifications.delivery_window',return_value=True):
            delivered,failed=tick(a.db,sender,self.now)
        self.assertEqual((delivered,failed),(1,0))
        self.assertIn('(other)',sent[0]);self.assertNotIn('(pc)',sent[0])

    def test_nonimportant_backup_alarm_hidden_and_flags_removed_with_agent(self):
        self.flag('important',False)
        self.report['backups']=[{'name':'ERP','path':'D:/backup','state':'missing'}]
        with a.db() as c:c.execute('UPDATE latest_reports SET data=? WHERE agent=?',(json.dumps(self.report),'pc'))
        html=self.client.get('/').text
        self.assertNotIn('class="backup-alarm"',html)
        self.assertIn('Ошибка бэкапа',html)
        response=self.client.post('/agents/delete',data={'csrf':self.csrf,'agent_id':'pc','confirmation':'pc'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        with a.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM agent_flags WHERE agent=?',('pc',)).fetchone()[0],0)
