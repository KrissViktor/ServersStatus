import asyncio
import os
import ssl
import unittest
from unittest.mock import patch,AsyncMock
import httpx
from server import ai_web as web

class ConnectionTest(unittest.TestCase):
    def test_proxy_explicit_local_only(self):
        with patch.dict(os.environ,{'STATUS_AI_WEB_PROXY':''}):self.assertIsNone(web.web_proxy())
        with patch.dict(os.environ,{'STATUS_AI_WEB_PROXY':'socks5h://127.0.0.1:1080'}):self.assertEqual(web.web_proxy(),'socks5h://127.0.0.1:1080')
        for value in ['http://external.example:8080','http://user:password@localhost:1080','ftp://localhost:1080','http://localhost:0','http://localhost:1080/private']:
            with self.subTest(value=value),patch.dict(os.environ,{'STATUS_AI_WEB_PROXY':value}):
                with self.assertRaises(web.WebError):web.web_proxy()
    def test_errors_identify_host_route_and_kind_without_secret(self):
        cases=[(httpx.ConnectTimeout('SECRET URL'),'таймаут подключения'),(httpx.ReadTimeout('SECRET URL'),'таймаут чтения'),(httpx.ProxyError('SECRET URL'),'ошибка локального прокси')]
        for error,expected in cases:
            message=str(web.connection_error(error,'example.com',True));self.assertIn(expected,message);self.assertIn('example.com',message);self.assertIn('прокси',message);self.assertNotIn('SECRET',message)
        error=httpx.ConnectError('secret');error.__cause__=ssl.SSLCertVerificationError('CERTIFICATE_VERIFY_FAILED')
        message=str(web.connection_error(error,'example.com',False));self.assertIn('TLS-сертификата',message);self.assertIn('напрямую',message);self.assertNotIn('secret',message)
    def test_direct_retry_ignores_configured_proxy_but_keeps_security(self):
        original=httpx.AsyncClient
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):yield b'hello'
        def client(**kwargs):
            self.assertNotIn('proxy',kwargs);self.assertFalse(kwargs['trust_env']);self.assertNotIn('verify',kwargs)
            return original(transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'text/plain'},stream=Stream())),**kwargs)
        with patch.dict(os.environ,{'STATUS_AI_WEB_PROXY':'socks5h://127.0.0.1:1080'}),patch('server.ai_web.addresses',new_callable=AsyncMock,return_value=['8.8.8.8']),patch('server.ai_web.httpx.AsyncClient',side_effect=client):
            self.assertEqual(asyncio.run(web.fetch('https://example.com/',direct=True))['transport'],'direct')

    def test_proxy_keeps_dns_pin_sni_and_certificate_verification(self):
        original=httpx.AsyncClient;seen=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):yield b'hello'
        def handler(request):
            self.assertEqual(request.url.host,'8.8.8.8');self.assertEqual(request.headers['Host'],'example.com');self.assertEqual(request.extensions['sni_hostname'],'example.com')
            return httpx.Response(200,headers={'content-type':'text/plain'},stream=Stream())
        def client(**kwargs):
            seen.append(kwargs.copy());self.assertEqual(kwargs.pop('proxy'),'socks5h://127.0.0.1:1080');self.assertFalse(kwargs['trust_env']);self.assertNotIn('verify',kwargs)
            return original(transport=httpx.MockTransport(handler),**kwargs)
        with patch.dict(os.environ,{'STATUS_AI_WEB_PROXY':'socks5h://127.0.0.1:1080'}),patch('server.ai_web.addresses',new_callable=AsyncMock,return_value=['8.8.8.8']),patch('server.ai_web.httpx.AsyncClient',side_effect=client):
            self.assertEqual(asyncio.run(web.fetch('https://example.com/'))['text'],'hello')
        self.assertEqual(len(seen),1)
