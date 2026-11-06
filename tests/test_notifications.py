import json
from pathlib import Path
import tempfile
import unittest
from server import app as application
from server.notifications import tick, DeliveryError


class NotificationsTest(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        window=patch('server.notifications.delivery_window',return_value=True)
        window.start()
        self.addCleanup(window.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous = application.DB
        self.addCleanup(setattr, application, 'DB', previous)
        application.DB = str(Path(self.temp.name) / 'notify.sqlite3')
        with application.db() as c:
            c.execute('INSERT INTO agents VALUES (?,?)', ('pc', 'hashed-token'))
        self.sent = []

    def report(self, timestamp, backups=None):
        with application.db() as c:
            c.execute('INSERT INTO reports VALUES (?,?,?)', ('pc', timestamp, json.dumps({'hostname': 'WINDOWS', 'backups': backups or []})))

    def tick(self, timestamp, sender=None):
        return tick(application.db, sender or self.sent.append, timestamp)

    def test_offline_dedup_restart_and_recovery(self):
        self.assertEqual(self.tick(1000), (0, 0))  # Unconnected registration.
        self.report(1000)
        self.assertEqual(self.tick(1000), (0, 0))
        self.assertEqual(self.tick(1180), (1, 0))
        self.assertIn('нет связи', self.sent[0])
        self.assertEqual(self.tick(1240), (0, 0))  # State retained in SQLite.
        self.report(1300)
        self.assertEqual(self.tick(1300), (1, 0))
        self.assertIn('ВОССТАНОВЛЕНО', self.sent[1])
        self.assertEqual(self.tick(1301), (0, 0))

    def test_backup_dedup_no_false_recovery_when_observing_or_offline(self):
        backup = {'name': 'ERP', 'path': 'D:/backup', 'state': 'stale', 'file': 'copy.bak',
                  'size_bytes': 512, 'age_seconds': 31*3600}
        self.report(1000, [backup])
        self.assertEqual(self.tick(1000), (1, 0))
        self.assertIn('30 часов', self.sent[0])
        self.assertIn('меньше 1 Гб', self.sent[0])
        self.assertEqual(self.tick(1060), (0, 0))
        self.assertEqual(self.tick(1200), (1, 0))  # Connection issue only.
        self.assertNotIn('ВОССТАНОВЛЕНО', self.sent[-1])
        backup.update(state='observing', size_bytes=1024**3, age_seconds=1)
        self.report(1300, [backup])
        self.assertEqual(self.tick(1300), (1, 0))  # Connection recovery only.
        backup['state'] = 'fresh'
        self.report(1400, [backup])
        self.assertEqual(self.tick(1400), (1, 0))
        self.assertIn('ВОССТАНОВЛЕНО', self.sent[-1])
        self.assertEqual(self.tick(1401), (0, 0))

    def test_failed_delivery_retried_and_rate_limit_respected(self):
        self.report(1000)
        def fail(text):
            raise DeliveryError(180)
        self.assertEqual(self.tick(1200, fail), (0, 1))
        self.assertEqual(self.tick(1260), (0, 0))
        self.assertEqual(self.tick(1380), (1, 0))
        self.assertEqual(len(self.sent), 1)

    def test_deleted_agent_does_not_generate_false_recovery(self):
        self.report(1000)
        self.tick(1200)
        with application.db() as c:
            c.execute('DELETE FROM agents')
        self.assertEqual(self.tick(1300), (0, 0))
        with application.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM telegram_state').fetchone()[0], 0)

    def test_transport_plain_text_and_safe_rate_limit_error(self):
        from unittest.mock import patch
        import io
        import urllib.error
        from server.notifications import telegram_request, send_message
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, size):
                return b'{"ok":true,"result":{"message_id":1}}'
        with patch('server.notifications.urllib.request.urlopen', return_value=Response()) as send:
            send_message('dummy-test-token', '123', '<ERP> alert')
            request = send.call_args.args[0]
            body = json.loads(request.data)
            self.assertNotIn('parse_mode', body)
            self.assertEqual(body['text'], '<ERP> alert')
            self.assertEqual(send.call_args.kwargs['timeout'], 15)
        error = urllib.error.HTTPError('https://example.test/dummy-test-token', 429, 'retry', {}, io.BytesIO(b'{"parameters":{"retry_after":120}}'))
        with patch('server.notifications.urllib.request.urlopen', side_effect=error):
            with self.assertRaises(DeliveryError) as caught:
                telegram_request('dummy-test-token', 'sendMessage', {})
            self.assertEqual(caught.exception.retry_after, 120)
            self.assertNotIn('dummy-test-token', str(caught.exception))

    def test_telegram_only_proxy_and_no_direct_fallback(self):
        import os
        from unittest.mock import patch, MagicMock
        from server.notifications import telegram_request
        response = MagicMock(status_code=200)
        response.json.return_value = {'ok': True, 'result': {'message_id': 123}}
        with patch.dict(os.environ, {'STATUS_TELEGRAM_PROXY': 'socks5h://127.0.0.1:1080'}), patch('httpx.Client') as factory, patch('server.notifications.urllib.request.urlopen') as direct:
            client = factory.return_value.__enter__.return_value
            client.post.return_value = response
            self.assertEqual(telegram_request('dummy-token', 'sendMessage', {}), {'message_id': 123})
            factory.assert_called_once_with(proxy='socks5h://127.0.0.1:1080', timeout=15, trust_env=False, follow_redirects=False)
            direct.assert_not_called()
            client.post.side_effect = RuntimeError('proxy-secret dummy-token')
            with self.assertRaises(DeliveryError) as caught:
                telegram_request('dummy-token', 'sendMessage', {})
            self.assertNotIn('dummy-token', str(caught.exception))
            direct.assert_not_called()

    def test_proxy_rate_limit_and_invalid_scheme(self):
        import os
        from unittest.mock import patch, MagicMock
        from server.notifications import telegram_request
        response = MagicMock(status_code=429)
        response.json.return_value = {'parameters': {'retry_after': 180}}
        with patch.dict(os.environ, {'STATUS_TELEGRAM_PROXY': 'socks5h://127.0.0.1:1080'}), patch('httpx.Client') as factory:
            factory.return_value.__enter__.return_value.post.return_value = response
            with self.assertRaises(DeliveryError) as caught:
                telegram_request('dummy-token', 'sendMessage', {})
            self.assertEqual(caught.exception.retry_after, 180)
        with patch.dict(os.environ, {'STATUS_TELEGRAM_PROXY': 'ftp://invalid'}), patch('httpx.Client') as factory:
            with self.assertRaises(DeliveryError):
                telegram_request('dummy-token', 'sendMessage', {})
            factory.assert_not_called()
