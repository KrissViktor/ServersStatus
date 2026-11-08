import asyncio
import json
import unittest
from unittest.mock import patch
import httpx
from server import ai_navigation,ai_web

class NavigationTest(unittest.TestCase):
    def test_isolated_planner_sees_only_question_and_validates_urls(self):
        original=httpx.AsyncClient;seen=[]
        def handler(request):
            payload=json.loads(request.content);seen.append(payload)
            self.assertEqual(payload['messages'][-1],{'role':'user','content':'найди документацию Python'})
            self.assertEqual(len(payload['messages']),2);self.assertFalse(payload['stream'])
            self.assertEqual(request.headers['Authorization'],'Bearer TESTKEY')
            return httpx.Response(200,json={'choices':[{'message':{'content':'{"urls":["http://127.0.0.1/","https://docs.python.org/3/"]}'}}]})
        with patch('server.ai_navigation.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(handler),**kw)):
            self.assertEqual(asyncio.run(ai_navigation.discover('найди документацию Python','TESTKEY')),['https://docs.python.org/3/'])
        self.assertEqual(len(seen),1)
    def test_page_links_are_resolved_and_filter_private_and_duplicate(self):
        links=ai_web.page_links('<a href="/rates">Курсы</a><a href="/rates">Ещё</a><a href="http://127.0.0.1/private">secret</a><a href="javascript:alert(1)">JS</a><a href="#x">Anchor</a>','https://example.com/')
        self.assertEqual(links,[{'url':'https://example.com/rates','title':'Курсы'}])
