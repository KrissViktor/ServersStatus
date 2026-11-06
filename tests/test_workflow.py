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
        for _ in range(10):
            self.assertEqual(self.client.post('/login', data={'username': 'admin', 'password': 'wrong'}).status_code, 401)
        self.assertEqual(self.client.post('/login', data={'username': 'admin', 'password': 'test-password-123'}).status_code, 429)

    def test_backup_states(self):
        config = {'backups': [{'path': self.directory.name, 'pattern': '*.bak', 'max_age_hours': 1}]}
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
        self.assertIn('Данные устарели', content)
        self.assertIn('Ожидаем первый отчёт', content)
        self.assertIn('Контроль служб не настроен', content)
        self.assertIn('Папки бэкапов не настроены', content)
        self.assertIn('http-equiv="refresh" content="30"', content)

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
