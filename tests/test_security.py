import sqlite3
import unittest
from starlette.requests import Request
from server.security import client_address, failed_login, blocked_seconds, RequestLimiter


class SecurityTest(unittest.TestCase):
    def connection(self):
        c = sqlite3.connect(':memory:')
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE auth_guard(address TEXT PRIMARY KEY, failures INTEGER, strikes INTEGER, blocked_until TEXT)')
        self.addCleanup(c.close)
        return c

    def test_two_failures_escalate_without_resetting_history(self):
        c = self.connection()
        self.assertEqual(failed_login(c, 'ip', 1000), 0)
        self.assertEqual(failed_login(c, 'ip', 1000), 900)
        self.assertEqual(blocked_seconds(c, 'ip', 1001), 899)
        self.assertEqual(blocked_seconds(c, 'other', 1001), 0)
        self.assertEqual(blocked_seconds(c, 'ip', 1900), 0)
        self.assertEqual(failed_login(c, 'ip', 1900), 0)
        self.assertEqual(failed_login(c, 'ip', 1900), 2700)
        self.assertEqual(failed_login(c, 'ip', 4600), 0)
        self.assertEqual(failed_login(c, 'ip', 4600), 8100)
        c.execute('UPDATE auth_guard SET strikes=100, blocked_until=?, failures=0', ('0',))
        failed_login(c, 'ip', 10000)
        self.assertEqual(failed_login(c, 'ip', 10000), 900*3**100)
        self.assertEqual(blocked_seconds(c, 'ip', 10000), 900*3**100)

    def test_forwarded_ip_only_from_loopback(self):
        def request(peer, headers):
            return Request({'type': 'http', 'client': (peer, 1), 'headers': [(k.encode(), v.encode()) for k,v in headers.items()]})
        self.assertEqual(client_address(request('198.51.100.1', {'x-status-client-ip':'203.0.113.2'})), '198.51.100.1')
        self.assertEqual(client_address(request('127.0.0.1', {'x-status-client-ip':'203.0.113.2'})), '203.0.113.2')
        self.assertEqual(client_address(request('127.0.0.1', {'x-forwarded-for':'203.0.113.3'})), '203.0.113.3')
        self.assertEqual(client_address(request('127.0.0.1', {'x-forwarded-for':'spoof, 203.0.113.3'})), '127.0.0.1')

    def test_flood_limit_refill_and_bounded_memory(self):
        limiter = RequestLimiter(capacity=2, refill=1, max_clients=2)
        self.assertTrue(limiter.allow('a', 100)[0])
        self.assertTrue(limiter.allow('a', 100)[0])
        self.assertFalse(limiter.allow('a', 100)[0])
        self.assertTrue(limiter.allow('b', 100)[0])
        self.assertTrue(limiter.allow('a', 101)[0])
        limiter.allow('c', 101)
        self.assertLessEqual(len(limiter.clients), 2)
