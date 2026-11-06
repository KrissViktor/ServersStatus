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
        self.assertIn('52.4 ГиБ', content)
        self.assertIn('1 д 6 ч 31 мин', content)
        self.assertIn('Данные устарели', content)
        self.assertIn('Ожидаем первый отчёт', content)
        self.assertIn('Контроль служб не настроен', content)
        self.assertIn('Папки бэкапов не настроены', content)
        self.assertIn('http-equiv="refresh" content="30"', content)
