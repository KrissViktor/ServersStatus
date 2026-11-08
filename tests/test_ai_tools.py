import asyncio
import json
import time
import unittest
from unittest.mock import patch, AsyncMock
import test_ai_chat as fixture
from server import app as a, ai_chat, ai_tools, ai_web

class ToolsTest(unittest.TestCase):
    setUp=fixture.AIChatTest.setUp
    ask=fixture.AIChatTest.ask
    generate=fixture.AIChatTest.generate
    def session(self,**flags):
        identifier=self.ask(**flags).json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,))
            job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone())
        return ai_tools.Session(a.db,job,[{'role':'user','content':job['question']}])
    def test_scope_nonce_validation_and_fixed_search(self):
        s=self.session(internet_access=True,web_query='Windows SQL backup')
        self.assertEqual(self.ask(internet_access=False).status_code,409)
        with patch('server.ai_tools.search',new_callable=AsyncMock,return_value=[{'url':'https://example.com/','title':'Guide'}]) as search:
            denied=asyncio.run(s.execute('web_search',{'query':'private server data'}))
            self.assertIn('error',denied);search.assert_not_called()
            result=asyncio.run(s.execute('web_search',{}));search.assert_awaited_once_with('Windows SQL backup')
            self.assertIn('W1',result['data'])
        with patch('server.ai_tools.fetch',new_callable=AsyncMock) as fetch:
            self.assertIn('error',asyncio.run(s.execute('web_page',{'source_id':'W999'})));fetch.assert_not_called()
        self.assertIn('error',asyncio.run(s.execute('servers',{})))
    def test_portal_journal_redaction_and_revocation(self):
        s=self.session(portal_access=True)
        with a.db() as c:
            for category,message in [('console','hidden command'),('users','hidden role'),('backup','password=secretvalue failed')]:
                c.execute('INSERT INTO events(received,agent,category,level,message) VALUES (?,?,?,?,?)',(time.time(),'win',category,'warning',message))
        result=asyncio.run(s.execute('events',{}))
        self.assertNotIn('secretvalue',result['data']);self.assertNotIn('hidden',result['data']);self.assertIn('скрыто',result['data'])
        traces=self.client.get('/api/ai/chat/'+self.chat).json()['turns'][0]['tools'];self.assertEqual(len(traces),1)
        with a.db() as c:c.execute("UPDATE user_roles SET role='viewer' WHERE name='alice'")
        self.assertIn('error',asyncio.run(s.execute('servers',{})))
    def test_current_metrics_history_and_inventories(self):
        s=self.session(portal_access=True)
        data={'hostname':'Backup','cpu_percent':40,'memory_percent':50,'disks':[{'path':'/','used_percent':60}], 'system':{'memory_total_bytes':32*1024**3},'backups':[{'name':'ERP','created_at':123,'state':'ok','age_seconds':60}]}
        with a.db() as c:
            c.execute("INSERT INTO agents VALUES ('win','AGENT_SECRET')")
            c.execute('INSERT INTO latest_reports VALUES (?,?,?)',('win',time.time(),json.dumps(data)))
            c.execute('INSERT INTO reports VALUES (?,?,?)',('win',time.time(),json.dumps(data)))
            c.execute('INSERT INTO latest_processes VALUES (?,?,?)',('win',time.time(),json.dumps({'status':'available','items':[{'pid':3,'name':'sql','cpu_percent':40,'memory_bytes':1024}]})))
            c.execute('INSERT INTO latest_services VALUES (?,?,?)',('win',time.time(),json.dumps({'status':'available','items':[{'name':'SQL','status':'running','details':{'command':'password=PRIVATE'}}]})))
        value=asyncio.run(s.execute('server_info',{'agent':'win'}));self.assertIn('memory_total_bytes',value['data']);self.assertIn('created_at',value['data']);self.assertNotIn('AGENT_SECRET',value['data'])
        value=asyncio.run(s.execute('history',{'agent':'win'}));self.assertEqual(json.loads(value['data'])['cpu_max'],40)
        self.assertIn('sql',asyncio.run(s.execute('processes',{'agent':'win'}))['data'])
        value=asyncio.run(s.execute('services',{'agent':'win'}));self.assertIn('running',value['data']);self.assertNotIn('PRIVATE',value['data'])

    def test_automatic_search_before_model_without_separate_query(self):
        import httpx
        s=self.session(internet_access=True,question='Какая погода завтра в Москве?')
        with a.db() as c:messages=ai_chat.context(c,s.job)
        def handler(request):
            payload=json.loads(request.content)
            self.assertEqual(payload['messages'][-1]['role'],'tool')
            self.assertIn('Weather forecast',payload['messages'][-1]['content'])
            return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"Forecast [S1]"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        with patch('server.ai_tools.search',new_callable=AsyncMock,return_value=[{'url':'https://example.com/weather','title':'Weather forecast'}]) as search, patch('server.ai_tools.fetch',new_callable=AsyncMock,return_value={'url':'https://example.com/weather','type':'text/html','text':'<p>Weather forecast: tomorrow +5 C</p>'}) as page:
            result=self.generate(handler,s.job,messages)
            page.assert_awaited_once_with('https://example.com/weather')
            search.assert_awaited_once_with('Какая погода завтра в Москве?')
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.client.get('/api/ai/chat/'+self.chat).json()['turns'][0]['tools'][0]['status'],'completed')

    def test_direct_source_uses_current_question_only(self):
        s=self.session(internet_access=True,question='Какая погода?')
        messages=[{'role':'user','content':'https://example.com/old'},{'role':'user','content':s.job['question']}]
        self.assertIsNone(ai_tools.Session(a.db,s.job,messages).direct_source)
        job={**s.job,'question':'Прочти https://example.com/new'}
        session=ai_tools.Session(a.db,job,messages+[{'role':'user','content':job['question']}])
        self.assertEqual(session.urls[session.direct_source],'https://example.com/new')

    def test_automatic_source_failure_is_visible_not_invented(self):
        import httpx
        s=self.session(internet_access=True)
        with a.db() as c:messages=ai_chat.context(c,s.job)
        def handler(request):
            payload=json.loads(request.content);self.assertIn('Search unavailable',payload['messages'][-1]['content'])
            return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"Search unavailable"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        with patch('server.ai_tools.search',new_callable=AsyncMock,side_effect=ai_web.WebError('Search unavailable')):
            self.assertEqual(self.generate(handler,s.job,messages)['status'],'completed')
        self.assertEqual(self.client.get('/api/ai/chat/'+self.chat).json()['turns'][0]['tools'][0]['status'],'failed')

    def test_stream_tool_round_trip(self):
        import httpx
        s=self.session(portal_access=True);seen=[]
        with a.db() as c:messages=ai_chat.context(c,s.job)
        def handler(request):
            payload=json.loads(request.content);seen.append(payload)
            if len(seen)==1:
                delta={'tool_calls':[{'index':0,'id':'call1','type':'function','function':{'name':'servers','arguments':'{}'}}]}
            else:
                self.assertEqual(payload['messages'][-1]['role'],'tool')
                delta={'content':'Серверы проверены [S1]'}
            return httpx.Response(200,content=('data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n').encode())
        result=self.generate(handler,s.job,messages)
        self.assertEqual(result['status'],'completed');self.assertEqual(len(seen),2);self.assertIn('[S1]',result['reply'])
        self.assertIn('tools',seen[0])

class WebTest(unittest.TestCase):
    def test_public_urls_and_addresses(self):
        for url in ['http://127.0.0.1/','http://[::1]/','http://169.254.169.254/','http://100.64.0.1/','http://168.63.129.16/','https://localhost/','https://x.local/','https://u:p@example.com/','https://example.com:0/','file:///etc/passwd','https://example.com/\nsecret']:
            with self.subTest(url=url),self.assertRaises(ai_web.WebError):ai_web.normalize_url(url)
        self.assertEqual(ai_web.normalize_url('https://example.com:443/a#fragment'),'https://example.com/a')
        self.assertFalse(ai_web.public_ip('::ffff:8.8.8.8'))
    def test_html_and_search(self):
        self.assertEqual(ai_web.page_text('<h1>Title</h1><script>secret</script><p>Body</p>','text/html'),'Title\nBody')
        with patch('server.ai_web.fetch',new_callable=AsyncMock,return_value={'url':'https://www.google.com/search','text':'<html><a href="/url?q=https%3A%2F%2Fexample.com%2F&amp;sa=U"><h3>Guide</h3></a><div>Useful snippet</div></html>'}) as fetch:
            result=asyncio.run(ai_web.search('safe query'));self.assertEqual(result[0]['title'],'Guide');self.assertIn('safe%20query',fetch.call_args.args[0]);self.assertTrue(fetch.call_args.args[0].startswith('https://www.google.com/search?'));self.assertIn('Useful snippet',result[0]['snippet'])
    def test_google_block_pages_are_errors_and_no_bing_fallback(self):
        for url,text in [('https://www.google.com/sorry/','unusual traffic'),('https://consent.google.com/','consent'),('https://www.google.com/search','Please enable JavaScript')]:
            with self.subTest(url=url),patch('server.ai_web.fetch',new_callable=AsyncMock,return_value={'url':url,'text':text}) as fetch:
                with self.assertRaises(ai_web.WebError):asyncio.run(ai_web.search('weather'))
                self.assertEqual(fetch.await_count,1);self.assertIn('www.google.com',fetch.call_args.args[0])
    def test_google_parser_filters_private_links_and_deduplicates(self):
        parser=ai_web.GoogleResults()
        parser.feed('<a href="http://127.0.0.1/"><h3>Private</h3></a><a href="https://example.com/a"><h3>Forecast <span>tomorrow</span></h3></a><p>+5 degrees</p><a href="https://example.com/a"><h3>Duplicate</h3></a>')
        self.assertEqual(len(parser.items),1);self.assertEqual(parser.items[0]['title'],'Forecast tomorrow');self.assertIn('+5 degrees',parser.items[0]['snippet'])

    def test_mixed_dns_and_response_limits(self):
        import httpx
        import socket
        async def mixed():
            loop=asyncio.get_running_loop()
            with patch.object(loop,'getaddrinfo',new_callable=AsyncMock,return_value=[(socket.AF_INET,1,6,'',('8.8.8.8',443)),(socket.AF_INET,1,6,'',('127.0.0.1',443))]):
                with self.assertRaises(ai_web.WebError):await ai_web.addresses('example.com',443)
        asyncio.run(mixed())
        original=httpx.AsyncClient
        for headers in [{'content-type':'text/html','content-length':str(ai_web.MAX_BYTES+1)},{'content-type':'text/html','content-encoding':'gzip'},{'content-type':'application/octet-stream'}]:
            def client(**kwargs):return original(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers=headers)),**kwargs)
            with patch('server.ai_web.addresses',new_callable=AsyncMock,return_value=['8.8.8.8']),patch('server.ai_web.httpx.AsyncClient',side_effect=client):
                with self.assertRaises(ai_web.WebError):asyncio.run(ai_web.fetch('https://example.com/'))

    def test_dns_pin_and_redirect_guard(self):
        import httpx
        original=httpx.AsyncClient;seen=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):yield b'hello'
        def handler(request):
            seen.append(request);return httpx.Response(200,headers={'content-type':'text/plain'},stream=Stream())
        def client(**kwargs):
            self.assertFalse(kwargs['trust_env']);self.assertFalse(kwargs['follow_redirects'])
            return original(transport=httpx.MockTransport(handler),**kwargs)
        with patch('server.ai_web.addresses',new_callable=AsyncMock,return_value=['8.8.8.8']),patch('server.ai_web.httpx.AsyncClient',side_effect=client):
            self.assertEqual(asyncio.run(ai_web.fetch('https://example.com/'))['text'],'hello')
        self.assertEqual(seen[0].url.host,'8.8.8.8');self.assertEqual(seen[0].headers['host'],'example.com');self.assertEqual(seen[0].extensions['sni_hostname'],'example.com')
        def redirect(request):return httpx.Response(302,headers={'location':'http://127.0.0.1/'})
        with patch('server.ai_web.addresses',new_callable=AsyncMock,return_value=['8.8.8.8']),patch('server.ai_web.httpx.AsyncClient',side_effect=lambda **kw:original(transport=httpx.MockTransport(redirect),**kw)):
            with self.assertRaises(ai_web.WebError):asyncio.run(ai_web.fetch('https://example.com/'))
