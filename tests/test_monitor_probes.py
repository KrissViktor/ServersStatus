import json
import socket
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from server.monitor_probes import check_http, check_registry, public_address, target


class MonitorProbesTest(unittest.TestCase):
    def test_url_normalization_and_destination_policy(self):
        self.assertEqual(target('https://пример.рф/путь'), 'https://xn--e1afmkfd.xn--p1ai/%D0%BF%D1%83%D1%82%D1%8C')
        for url in ('file:///tmp/file','https://user:secret@example.org/','https://example.org:22/','https://example.org/?token=secret'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                target(url)
        with patch('server.monitor_probes.socket.getaddrinfo',return_value=[
            (socket.AF_INET,socket.SOCK_STREAM,0,'',('8.8.8.8',443)),
            (socket.AF_INET,socket.SOCK_STREAM,0,'',('192.168.0.1',443)),
        ]), self.assertRaises(ValueError):
            public_address('example.org',443)

    def test_expected_status_and_certificate_metadata(self):
        with patch('server.monitor_probes.public_address'), patch('server.monitor_probes.http.client.HTTPSConnection') as factory:
            connection=factory.return_value
            connection.sock.getpeercert.return_value={
                'notAfter':'Jan  1 00:00:00 2030 GMT',
                'issuer':((('organizationName','Example CA'),),),
            }
            connection.getresponse.return_value.status=204
            result=check_http('https://example.org/health',200,14,1700000000)
            self.assertEqual((result['http'],result['tls'],result['code'],result['issuer']),
                             ('unexpected','ok',204,'Example CA'))
            self.assertEqual(factory.call_args.args[:2],('example.org',443))
            self.assertEqual(connection.request.call_args.args,('GET','/health'))
            connection.close.assert_called_once()

    def test_registry_exact_wildcard_and_stale(self):
        now=1800000000
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.json'
            with patch.dict('os.environ',{'STATUS_RKN_SNAPSHOT':str(path)}):
                self.assertEqual(check_registry('https://example.org/',now)['rkn'],'unavailable')
                path.write_text(json.dumps({'updated_at':now,'domains':['*.example.org','пример.рф']}),encoding='utf8')
                self.assertEqual(check_registry('https://x.example.org/',now)['rkn'],'listed')
                self.assertEqual(check_registry('https://example.org/',now)['rkn'],'clear')
                self.assertEqual(check_registry('https://xn--e1afmkfd.xn--p1ai/',now)['rkn'],'listed')
                result=check_registry('https://example.org/',now+86401)
                self.assertEqual(result,{'rkn':'stale','registry_at':now})
