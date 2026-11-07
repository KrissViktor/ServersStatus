import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from server import app as module
from agent.client import collect


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        from server.security import limiter, login_limiter
        limiter.reset()
        login_limiter.reset()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        module.DB = str(Path(self.directory.name) / 'test.sqlite3')
        self.client = TestClient(module.app, base_url='https://testserver')
        salt = '12' * 16
        with module.db() as c:
            c.execute('INSERT INTO users VALUES (?,?,?)', ('admin', salt, module.password_hash('test-password-123', salt)))
            c.execute('INSERT INTO agents VALUES (?,?)', ('pc', module.digest('agent-secret')))

    def test_login_report_logout(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        self.assertIn('Войти', self.client.get('/').text)
        data = collect({}, {})
        self.assertEqual(self.client.post('/api/report/pc', json=data).status_code, 401)
        self.assertEqual(self.client.post('/api/report/pc', json=data, headers={'Authorization': 'Bearer agent-secret'}).status_code, 200)
        self.assertEqual(self.client.post('/login', data={'username': 'admin', 'password': 'wrong'}).status_code, 401)
        result = self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'}, follow_redirects=False)
        self.assertEqual(result.status_code, 303)
        self.assertIn('Secure', result.headers['set-cookie'])
        self.assertIn('Онлайн', self.client.get('/').text)
        self.client.post('/logout')
        self.assertIn('Войти', self.client.get('/').text)

    def test_limits_and_validation(self):
        headers = {'Authorization': 'Bearer agent-secret'}
        self.assertEqual(self.client.post('/api/report/pc', json={}, headers=headers).status_code, 422)
        self.assertEqual(self.client.post('/api/report/pc', content='x' * 65537, headers=headers).status_code, 413)
        self.assertEqual(self.client.post('/login', data={'username': 'admin', 'password': 'wrong'}).status_code, 401)
        blocked = self.client.post('/login', data={'username': 'admin', 'password': 'wrong'})
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.headers['retry-after'], '900')
        self.assertEqual(self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'}).status_code, 429)

    def test_backup_states(self):
        config = {'backups': [{'path': self.directory.name, 'pattern': '*.bak', 'max_age_hours': 1, 'min_size_bytes': 0}]}
        previous = {}
        self.assertEqual(collect(config, previous)['backups'][0]['state'], 'missing')
        path = Path(self.directory.name) / 'db.bak'
        path.write_bytes(b'backup')
        self.assertEqual(collect(config, previous)['backups'][0]['state'], 'observing')
        self.assertEqual(collect(config, previous)['backups'][0]['state'], 'fresh')
        os.utime(path, (1, 1))
        collect(config, previous)
        self.assertEqual(collect(config, previous)['backups'][0]['state'], 'stale')

    def test_dashboard_safe_render_and_stale_state(self):
        from server.dashboard import dashboard
        import time
        payload = {'hostname': '<script>alert(1)</script>', 'cpu_percent': 6.8,
                   'memory_percent': 50.4, 'uptime_seconds': 109895,
                   'disks': [{'path': 'C:', 'free_bytes': 56312016896,
                              'total_bytes': 479452983296, 'used_percent': 88.3}],
                   'services': [], 'backups': []}
        content = dashboard([{'id': 'pc', 'received': time.time() - 240, 'data': json.dumps(payload)},
                             {'id': 'new', 'received': None, 'data': None}])
        self.assertNotIn('<script>alert(1)</script>', content)
        self.assertIn('&lt;script&gt;', content)
        self.assertIn('52.4 Гб', content)
        self.assertIn('1 д 6 ч 31 мин', content)
        from server.overview import detail_page
        details = detail_page({'id': 'pc', 'received': time.time() - 240, 'data': json.dumps(payload)}, 'csrf')
        self.assertIn('Данные устарели', details)
        self.assertIn('Ожидаем первый отчёт', content)
        self.assertIn('Контроль служб не настроен', details)
        self.assertIn('Папки бэкапов не настроены', details)
        self.assertNotIn('http-equiv="refresh"', content)
        self.assertIn('10000', content)

    def test_agent_management_lifecycle(self):
        import re
        self.assertEqual(self.client.get('/agents', follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/agents/create', data={}).status_code, 401)
        self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'})
        response = self.client.get('/agents')
        self.assertEqual(response.headers['cache-control'], 'no-store')
        csrf = re.search(r'name="csrf" value="([^"]+)"', response.text).group(1)
        self.assertEqual(self.client.post('/agents/create', data={'agent_id': 'new'}).status_code, 403)
        form = {'agent_id': 'new', 'csrf': csrf}
        created = self.client.post('/agents/create', data=form)
        self.assertEqual(created.status_code, 200)
        key = re.search(r'<input readonly value="([^"]+)" autocomplete="off"', created.text).group(1)
        self.assertNotIn(key, self.client.get('/agents').text)
        with module.db() as c:
            self.assertEqual(c.execute('SELECT token FROM agents WHERE id=?', ('new',)).fetchone()['token'], module.digest(key))
        self.assertEqual(self.client.post('/agents/create', data=form).status_code, 409)
        payload = {'hostname': 'pc', 'cpu_percent': 1, 'memory_percent': 2, 'uptime_seconds': 3, 'disks': []}
        old_headers = {'Authorization': 'Bearer ' + key}
        self.assertEqual(self.client.post('/api/report/new', json=payload, headers=old_headers).status_code, 200)
        self.assertEqual(self.client.post('/agents/rotate', data=form).status_code, 400)
        rotated = self.client.post('/agents/rotate', data=dict(form, confirm='yes'))
        new_key = re.search(r'<input readonly value="([^"]+)" autocomplete="off"', rotated.text).group(1)
        self.assertNotEqual(key, new_key)
        self.assertEqual(self.client.post('/api/report/new', json=payload, headers=old_headers).status_code, 401)
        new_headers = {'Authorization': 'Bearer ' + new_key}
        self.assertEqual(self.client.post('/api/report/new', json=payload, headers=new_headers).status_code, 200)
        self.assertEqual(self.client.post('/agents/delete', data=dict(form, confirmation='wrong')).status_code, 400)
        self.assertEqual(self.client.post('/agents/delete', data=dict(form, confirmation='new'), follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/api/report/new', json=payload, headers=new_headers).status_code, 401)
        with module.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM reports WHERE agent=?', ('new',)).fetchone()[0], 0)

    def test_history_isolation_aggregation_and_gaps(self):
        from server.history import load_history, chart
        samples = [(1000, 10, 30), (1020, 30, 50), (1300, 90, 70)]
        with module.db() as c:
            for timestamp, cpu, ram in samples:
                c.execute('INSERT INTO reports VALUES (?,?,?)', ('pc', timestamp, json.dumps({'cpu_percent': cpu, 'memory_percent': ram})))
            c.execute('INSERT INTO reports VALUES (?,?,?)', ('other', 1010, json.dumps({'cpu_percent': 100, 'memory_percent': 100})))
            c.execute('INSERT INTO reports VALUES (?,?,?)', ('pc', 500, json.dumps({'cpu_percent': 100, 'memory_percent': 100})))
            points = load_history(c, 'pc', 900, 1400, 300)
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]['cpu'], 20)
        self.assertEqual(points[0]['ram'], 40)
        self.assertEqual(points[0]['cpu_peak'], 30)
        self.assertEqual(points[0]['samples'], 2)
        self.assertEqual(points[1]['has_gap'], 1)
        graph = chart(points, 'cpu', 'CPU', 900, 1400, '#4adeab')
        self.assertEqual(graph.count('<circle '), 2)
        self.assertNotIn('stroke-width="2"', graph)  # No line bridging missing reports.
        self.assertIn('пик 90.0%', graph)

    def test_history_routes(self):
        self.assertEqual(self.client.get('/history/pc', follow_redirects=False).status_code, 303)
        self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'})
        self.assertEqual(self.client.get('/history/pc?period=invalid').status_code, 400)
        self.assertEqual(self.client.get('/history/missing').status_code, 404)
        empty = self.client.get('/history/pc')
        self.assertIn('За выбранный период отчётов нет', empty.text)
        self.assertEqual(empty.headers['cache-control'], 'no-store')
        import time
        payload = {'cpu_percent': 6.8, 'memory_percent': 50.4}
        with module.db() as c:
            c.execute('INSERT INTO reports VALUES (?,?,?)', ('pc', time.time(), json.dumps(payload)))
        for period in ('1h', '6h', '24h', '7d', '30d'):
            result = self.client.get('/history/pc?period=' + period)
            self.assertEqual(result.status_code, 200)
            self.assertIn('6.8%', result.text)
            self.assertIn('50.4%', result.text)
            self.assertEqual(result.text.count('<svg '), 2)
            self.assertIn('МСК', result.text)

    def test_prominent_backup_alarm(self):
        from server.dashboard import backup_problems, dashboard
        import time
        backup = {'name': 'ERP <daily>', 'schedule': 'daily', 'file': 'copy.bak',
                  'size_bytes': 1024**3, 'age_seconds': 30*3600, 'state': 'fresh'}
        self.assertEqual(backup_problems(backup), [])
        self.assertIn('старше 30 часов', backup_problems(backup, 1)[0])
        backup['size_bytes'] -= 1
        self.assertIn('меньше 1 Гб', backup_problems(backup)[0])
        rows = [{'id': 'backup-host', 'received': time.time() - 240,
                 'data': json.dumps({'hostname': 'WIN-CU629F0N7II', 'backups': [backup]})}]
        content = dashboard(rows)
        self.assertIn('role="alert"', content)
        self.assertIn('Ошибка резервного копирования', content)
        self.assertIn('WIN-CU629F0N7II · ERP &lt;daily&gt;', content)
        self.assertIn('меньше 1 Гб', content)
        self.assertIn('старше 30 часов', content)
        self.assertIn('Нет связи с агентом', content)
        self.assertLess(content.index('role="alert"'), content.index('<div class="stats">'))

    def test_extended_report_roundtrip(self):
        payload = {'hostname': 'windows', 'cpu_percent': 10, 'memory_percent': 20,
                   'uptime_seconds': 1, 'disks': [], 'sample_seconds': 1.1,
                   'system': {'os': 'Windows', 'version': '10.0.17763', 'release': 'Server 2019',
                              'edition': 'ServerStandard', 'memory_total_bytes': 16*1024**3},
                   'network': [{'name': '<Ethernet>', 'is_up': True, 'addresses': ['192.168.1.10'],
                                'speed_mbps': 1000, 'receive_bytes_per_second': 1024**2}],
                   'disk_io': [{'name': 'PhysicalDrive0', 'read_bytes_per_second': 2*1024**2, 'read_iops': 12}]}
        headers = {'Authorization': 'Bearer agent-secret'}
        self.assertEqual(self.client.post('/api/report/pc', json=payload, headers=headers).status_code, 200)
        self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'})
        content = self.client.get('/servers/pc').text
        for text in ('ServerStandard', '10.0.17763', '192.168.1.10', '1.0 Мб/с', 'PhysicalDrive0'):
            self.assertIn(text, content)
        self.assertIn('&lt;Ethernet&gt;', content)
        self.assertNotIn('<Ethernet>', content)
        payload['network'][0]['receive_bytes_per_second'] = -1
        self.assertEqual(self.client.post('/api/report/pc', json=payload, headers=headers).status_code, 422)

    def test_web_monitoring_configuration_delivery_and_reset(self):
        import re
        self.assertEqual(self.client.get('/settings/pc', follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/settings/pc', data={}).status_code, 401)
        self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'})
        form_page = self.client.get('/settings/pc')
        csrf = re.search(r'name="csrf" value="([^"]+)"', form_page.text).group(1)
        self.assertEqual(self.client.post('/settings/pc', data={'mode': 'save'}).status_code, 403)
        form = {'csrf': csrf, 'mode': 'save', 'services': 'MSSQLSERVER\nSpooler\nMSSQLSERVER',
                'name_0': 'ERP', 'path_0': r'D:\backup\daily', 'pattern_0': 'ERP_backup_*.bak',
                'schedule_0': 'daily', 'date_from_filename_0': 'yes',
                'max_age_hours_0': '30', 'grace_hours_0': '36', 'min_size_gb_0': '1.5'}
        saved = self.client.post('/settings/pc', data=form)
        self.assertEqual(saved.status_code, 200)
        self.assertIn('Ожидает получения агентом', saved.text)
        headers = {'Authorization': 'Bearer agent-secret'}
        payload = {'hostname': 'pc', 'cpu_percent': 1, 'memory_percent': 1, 'uptime_seconds': 1, 'disks': [], 'monitoring_revision': 0}
        reply = self.client.post('/api/report/pc', json=payload, headers=headers).json()
        remote = reply['monitoring']
        self.assertGreater(remote['revision'], 0)
        self.assertEqual(remote['settings']['services'], ['MSSQLSERVER', 'Spooler'])
        self.assertEqual(remote['settings']['backups'][0]['min_size_bytes'], int(1.5*1024**3))
        from agent.settings import validate_remote
        self.assertEqual(validate_remote(remote), remote)
        payload['monitoring_revision'] = remote['revision']
        self.client.post('/api/report/pc', json=payload, headers=headers)
        self.assertIn('Применено агентом', self.client.get('/settings/pc').text)
        self.assertEqual(self.client.post('/settings/pc', data=dict(form, min_size_gb_0='nan')).status_code, 400)
        self.assertEqual(self.client.post('/settings/pc', data=dict(form, max_age_hours_0='-1')).status_code, 400)
        self.assertEqual(self.client.post('/settings/pc', data={'csrf': csrf, 'mode': 'local'}).status_code, 400)
        self.assertEqual(self.client.post('/settings/pc', data={'csrf': csrf, 'mode': 'local', 'confirm_local': 'yes'}).status_code, 200)
        reply = self.client.post('/api/report/pc', json=payload, headers=headers).json()
        self.assertEqual(reply['monitoring'], {'revision': 0, 'settings': None})
        self.assertEqual(self.client.get('/settings/unknown').status_code, 404)

    def test_backup_alerts_follow_custom_monitoring_thresholds(self):
        from server.dashboard import backup_problems
        backup = {'state': 'fresh', 'schedule': 'daily', 'file': 'copy.bak',
                  'age_seconds': 25 * 3600, 'size_bytes': int(1.5 * 1024**3),
                  'max_age_hours': 24, 'min_size_bytes': 2*1024**3}
        problems = backup_problems(backup)
        self.assertTrue(any('24 часов' in problem for problem in problems))
        self.assertTrue(any('меньше 2 Гб' in problem for problem in problems))
        backup.update(max_age_hours=48, min_size_bytes=1024**3)
        self.assertEqual(backup_problems(backup), [])

    def test_overview_filter_search_and_display_name(self):
        import re
        import time
        self.assertEqual(self.client.get('/servers/pc', follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post('/servers/pc/name', data={}).status_code, 401)
        self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'})
        details = self.client.get('/servers/pc')
        self.assertEqual(details.headers['cache-control'], 'no-store')
        csrf = re.search(r'name="csrf" value="([^"]+)"', details.text).group(1)
        self.assertEqual(self.client.post('/servers/pc/name', data={'display_name': 'ERP'}).status_code, 403)
        rename = {'csrf': csrf, 'display_name': 'SQL — ERP <main>'}
        self.assertEqual(self.client.post('/servers/pc/name', data=rename, follow_redirects=False).status_code, 303)
        payload = {'hostname': 'WIN-SQL', 'cpu_percent': 2, 'memory_percent': 30, 'uptime_seconds': 1, 'disks': []}
        with module.db() as c:
            c.execute('INSERT INTO reports VALUES (?,?,?)', ('pc', time.time(), json.dumps(payload)))
            c.execute('INSERT INTO agents VALUES (?,?)', ('offline', 'token'))
            c.execute('INSERT INTO reports VALUES (?,?,?)', ('offline', time.time()-500, json.dumps(dict(payload, hostname='WIN-OLD'))))
        content = self.client.get('/?q=erp').text
        self.assertIn('SQL — ERP &lt;main&gt;', content)
        self.assertNotIn('WIN-OLD', content)
        self.assertIn('WIN-SQL', self.client.get('/?q=win-sql').text)
        self.assertNotIn('WIN-SQL', self.client.get('/?view=offline').text)
        self.assertIn('WIN-OLD', self.client.get('/?view=problems').text)
        self.assertNotIn('WIN-SQL', self.client.get('/?view=problems').text)
        self.assertIn('Нет серверов по выбранным условиям', self.client.get('/?q=missing').text)
        self.assertEqual(self.client.get('/?view=invalid').status_code, 400)
        self.assertEqual(self.client.get('/servers/missing').status_code, 404)
        with module.db() as c:
            self.assertEqual(c.execute('SELECT token FROM agents WHERE id=?', ('pc',)).fetchone()[0], module.digest('agent-secret'))
        self.assertIn('SQL — ERP &lt;main&gt;', self.client.get('/servers/pc').text)
        self.assertEqual(self.client.post('/servers/pc/name', data={'csrf': csrf, 'display_name': 'x'*121}).status_code, 400)
        self.client.post('/servers/pc/name', data={'csrf': csrf, 'display_name': ''})
        self.assertNotIn('SQL — ERP &lt;main&gt;', self.client.get('/servers/pc').text)

    def test_ban_is_per_ip_persists_and_preserves_agent_reports(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        proxy = TestClient(module.app, base_url='https://testserver', client=('127.0.0.1', 1234))
        ip1 = {'X-Forwarded-For': '198.51.100.1'}
        ip2 = {'X-Forwarded-For': '198.51.100.2'}
        wrong = {'username': 'admin', 'password': 'wrong'}
        with patch('server.app.time.time', return_value=1000):
            self.assertEqual(proxy.post('/login', data=wrong, headers=ip1).status_code, 401)
            self.assertEqual(proxy.post('/login', data=wrong, headers=ip1).headers['retry-after'], '900')
            self.assertEqual(proxy.get('/', headers=ip1).status_code, 429)
            self.assertEqual(proxy.get('/', headers=ip2).status_code, 200)
            headers = dict(ip1, Authorization='Bearer agent-secret')
            payload = {'hostname': 'pc', 'cpu_percent': 1, 'memory_percent': 2, 'uptime_seconds': 3, 'disks': []}
            self.assertEqual(proxy.post('/api/report/pc', json=payload, headers=headers).status_code, 200)
        with patch('server.app.time.time', return_value=1901):
            self.assertEqual(proxy.post('/login', data=wrong, headers=ip1).status_code, 401)
            response = proxy.post('/login', data=wrong, headers=ip1)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(response.headers['retry-after'], '2700')

    def test_http_flood_rejected_before_handler(self):
        from server.security import limiter
        for _ in range(60):
            limiter.allow('testclient')
        limiter.refill = 0.0001
        try:
            response = self.client.get('/')
            self.assertEqual(response.status_code, 429)
            self.assertIn('retry-after', response.headers)
        finally:
            limiter.refill = 5
            limiter.reset()
        self.assertEqual(self.client.post('/login', content='x'*65537).status_code, 413)
        self.assertEqual(self.client.request('TRACE', '/').status_code, 405)

    def test_new_metrics_journal_and_forecast_pages(self):
        from server.events import process_events
        import time
        self.assertEqual(self.client.get('/events',follow_redirects=False).status_code,303)
        self.client.post('/login',data={'username':'admin','password':'test-password-123'})
        payload={'hostname':'SQL-RDP','cpu_percent':10,'memory_percent':40,'uptime_seconds':1,
                 'features':['auto_services_v1','rdp_v1'],'rdp':{'status':'available','sessions':[{'session_id':1,'username':'user<script>','domain':'DOMAIN','state':'active'}]},
                 'network':[{'name':'Ethernet','is_up':True,'receive_bytes_per_second':1048576,'send_bytes_per_second':2097152}],
                 'disk_io':[{'name':'PhysicalDrive0','read_bytes_per_second':3145728,'write_bytes_per_second':4194304,'read_iops':10,'write_iops':20}],
                 'services':[{'name':'MSSQLSERVER','status':'stopped'}],'disks':[{'path':'C:','free_bytes':50*1024**3,'total_bytes':100*1024**3,'used_percent':50}]}
        self.assertEqual(self.client.post('/api/report/pc',json=payload,headers={'Authorization':'Bearer agent-secret'}).status_code,200)
        process_events(module.db)
        journal=self.client.get('/events').text
        self.assertIn('MSSQLSERVER',journal)
        self.assertEqual(self.client.get('/events?level=invalid').status_code,400)
        details=self.client.get('/servers/pc').text
        self.assertIn('Прогноз заполнения',details)
        self.assertIn('user&lt;script&gt;',details)
        self.assertNotIn('user<script>',details)
        self.assertIn('Подключён',details)
        history=self.client.get('/history/pc?period=1h').text
        self.assertEqual(history.count('<svg '),8)
        self.assertIn('1.0 Мб/с',history)
        self.assertIn('PhysicalDrive0',history)

    def test_all_ten_second_reports_are_retained_with_linux_labels(self):
        from unittest.mock import patch
        headers={'Authorization':'Bearer agent-secret'}
        payload={'hostname':'btrx24','cpu_percent':10,'memory_percent':37.5,'uptime_seconds':1,'disks':[],
                 'system':{'os':'Linux','distribution':'CentOS Stream 9','memory_total_bytes':16*1024**3,
                           'memory_available_bytes':10*1024**3,'memory_used_bytes':6*1024**3,'cpu_current_mhz':3200}}
        for when,cpu in [(1000,10),(1010,99),(1060,30)]:
            payload['cpu_percent']=cpu
            with patch('server.app.time.time',return_value=when):
                reply=self.client.post('/api/report/pc',json=payload,headers=headers)
                self.assertEqual(reply.status_code,200)
                self.assertEqual(reply.json()['report_interval_seconds'],10)
            with module.db() as c:
                self.assertEqual(json.loads(c.execute('SELECT data FROM current_reports WHERE agent=?',('pc',)).fetchone()[0])['cpu_percent'],cpu)
        with module.db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM reports WHERE agent=?',('pc',)).fetchone()[0],3)
            self.assertEqual(c.execute('SELECT count(*) FROM latest_reports WHERE agent=?',('pc',)).fetchone()[0],1)
            self.assertEqual(c.execute("SELECT MAX(json_extract(data,'$.cpu_percent')) FROM reports WHERE agent=?",('pc',)).fetchone()[0],99)
        self.client.post('/login',data={'username':'admin','password':'test-password-123'})
        content=self.client.get('/servers/pc').text
        self.assertIn('CentOS Stream 9',content)
        self.assertIn('6.0 Гб / 16.0 Гб',content)
        self.assertIn('3.20 ГГц',content)
        self.assertNotIn('WINDOWS · АГЕНТ',content)
        self.assertNotIn('Пользователи RDP',content)
