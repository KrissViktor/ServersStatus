import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock,patch
import httpx
import test_ai_chat as fixture
from server import ai_search as search,ai_web,ai_chat,app as a

class Stream(httpx.AsyncByteStream):
    def __init__(self,value):self.value=value if isinstance(value,bytes) else json.dumps(value).encode()
    async def __aiter__(self):yield self.value

class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'key'
        env=patch.dict(os.environ,{'STATUS_AI_SEARCH_KEY_FILE':str(self.path),'STATUS_AI_WEB_PROXY':'','STATUS_AI_SEARCH_PROVIDER':'tavily'});env.start();self.addCleanup(env.stop)
    def run_request(self,handler,operation=None):
        original=httpx.AsyncClient
        def client(**kwargs):
            self.assertFalse(kwargs['trust_env']);self.assertFalse(kwargs['follow_redirects']);self.assertNotIn('verify',kwargs)
            return original(transport=httpx.MockTransport(handler),**kwargs)
        with patch('server.ai_search.addresses',new_callable=AsyncMock,return_value=['8.8.8.8']),patch('server.ai_search.httpx.AsyncClient',side_effect=client):return asyncio.run(operation() if operation else search.search('latest Python release'))
    def test_anonymous_structured_results_and_extracted_content(self):
        def handler(request):
            self.assertEqual(request.method,'POST');self.assertEqual(request.url.host,'8.8.8.8');self.assertEqual(request.headers['Host'],'api.tavily.com');self.assertEqual(request.extensions['sni_hostname'],'api.tavily.com')
            self.assertEqual(request.headers['X-Tavily-Access-Mode'],'keyless');self.assertNotIn('authorization',request.headers)
            data=json.loads(request.content);self.assertEqual(data['query'],'latest Python release');self.assertEqual(data['include_raw_content'],'text');self.assertFalse(data['include_answer'])
            return httpx.Response(200,stream=Stream({'results':[{'title':'Official','url':'https://example.com/','content':'Snippet','raw_content':'Actual extracted document'},{'url':'https://example.com/'},{'url':'http://127.0.0.1/private'}]}))
        items=self.run_request(handler);self.assertEqual(len(items),1);self.assertEqual(items[0]['_page']['text'],'Actual extracted document');self.assertEqual(search.info()['key_configured'],False)
    def test_key_is_only_sent_to_fixed_api_header_and_never_in_errors(self):
        self.path.write_text('tvly-PRIVATE_TEST_KEY')
        def handler(request):
            self.assertEqual(request.headers['authorization'],'Bearer tvly-PRIVATE_TEST_KEY');self.assertNotIn('PRIVATE',request.content.decode());self.assertNotIn('X-Tavily-Access-Mode',request.headers)
            return httpx.Response(401,stream=Stream({'error':'tvly-PRIVATE_TEST_KEY'}))
        with self.assertRaises(ai_web.WebError) as caught:self.run_request(handler)
        self.assertNotIn('PRIVATE',str(caught.exception));self.assertTrue(search.info()['key_configured']);self.assertNotIn('PRIVATE',json.dumps(search.info()))
    def test_limits_redirects_malformed_and_bounded_responses(self):
        for status in (302,403,429,502):
            with self.subTest(status=status),self.assertRaises(ai_web.WebError):self.run_request(lambda req:httpx.Response(status,headers={'Location':'https://evil.example/'},stream=Stream({'secret':'PRIVATE'})))
        for value in (b'<html>CAPTCHA</html>',{'error':{'code':'LIMIT'}},{'results':[]}):
            with self.subTest(value=value),self.assertRaises(ai_web.WebError):self.run_request(lambda req:httpx.Response(200,stream=Stream(value)))
        with patch('server.ai_search.MAX_BYTES',10),self.assertRaises(ai_web.WebError):self.run_request(lambda req:httpx.Response(200,stream=Stream(b'x'*11)))
    def test_extract_uses_public_url_and_filtered_payload(self):
        def handler(request):
            payload=json.loads(request.content);self.assertEqual(payload['urls'],['https://example.com/page']);self.assertEqual(request.url.path,'/extract')
            return httpx.Response(200,stream=Stream({'results':[{'url':'https://example.com/page','raw_content':'Page text'}]}))
        result=self.run_request(handler,lambda:search.extract('https://example.com/page'));self.assertEqual(result['text'],'Page text')
        with self.assertRaises(ai_web.WebError):asyncio.run(search.extract('http://169.254.169.254/'))
        with patch('server.ai_search.addresses',new_callable=AsyncMock,side_effect=ai_web.WebError('private DNS blocked')),patch('server.ai_search.request',new_callable=AsyncMock) as api:
            with self.assertRaises(ai_web.WebError):asyncio.run(search.extract('https://example.com/'))
            api.assert_not_called()
    def test_search_defaults_to_api_with_explicit_legacy_override(self):
        with patch('server.ai_search.search',new_callable=AsyncMock,return_value=['API']) as api:
            self.assertEqual(asyncio.run(ai_web.search('question')),['API']);api.assert_awaited_once_with('question')
        with patch.dict(os.environ,{'STATUS_AI_SEARCH_PROVIDER':'google'}),patch('server.ai_web.google_search',new_callable=AsyncMock,return_value=['legacy']):self.assertEqual(asyncio.run(ai_web.search('question')),['legacy'])

class SearchIntegrationTest(unittest.TestCase):
    setUp=fixture.AIChatTest.setUp
    ask=fixture.AIChatTest.ask
    generate=fixture.AIChatTest.generate
    def test_direct_page_failure_uses_extraction_api(self):
        from server.ai_tools import Session
        identifier=self.ask(question='Прочти https://example.com/article',internet_access=True).json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,));job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone())
        session=Session(a.db,job,[{'role':'user','content':job['question']}])
        with patch.dict(os.environ,{'STATUS_AI_SEARCH_PROVIDER':'tavily'}),patch('server.ai_tools.fetch',new_callable=AsyncMock,side_effect=ai_web.WebError('HTTP 403')),patch('server.ai_search.extract',new_callable=AsyncMock,return_value={'url':'https://example.com/article','text':'Extracted article','type':'text/plain','provider':'Tavily'}) as extract:
            result=asyncio.run(session.execute('web_page',{'source_id':session.direct_source}));extract.assert_awaited_once_with('https://example.com/article')
        self.assertIn('Extracted article',result['data']);self.assertNotIn('error',result)

    def test_cached_page_reaches_model_without_fetching_google_or_result_site(self):
        identifier=self.ask(question='Когда появилась новая версия Python?',internet_access=True).json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,));job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone());messages=ai_chat.context(c,job)
        messages.insert(1,{'role':'assistant','content':'PORTAL_HISTORY_PRIVATE'})
        def handler(request):
            if request.headers['host']=='api.tavily.com':
                self.assertNotIn('PORTAL_HISTORY_PRIVATE',request.content.decode());self.assertNotIn('AI_PRIVATE_KEY_TEST_ONLY',str(request.headers));self.assertNotIn('authorization',request.headers)
                return httpx.Response(200,stream=Stream({'results':[{'title':'Official source','url':'https://example.com/release','content':'Short snippet','raw_content':'Latest documented answer from the actual page'}]}))
            self.assertEqual(str(request.url),ai_chat.ORIGIN+'/v1/chat/completions');payload=json.loads(request.content)
            self.assertIn('Latest documented answer',payload['messages'][-1]['content'])
            return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"Answer [S2]"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        with patch.dict(os.environ,{'STATUS_AI_SEARCH_KEY_FILE':str(self.secret.parent/'absent-search-key'),'STATUS_AI_SEARCH_PROVIDER':'tavily','STATUS_AI_WEB_PROXY':''}),patch('server.ai_search.addresses',new_callable=AsyncMock,return_value=['8.8.8.8']),patch('server.ai_tools.fetch',new_callable=AsyncMock) as direct:
            result=self.generate(handler,job,messages);direct.assert_not_called()
        self.assertEqual(result['status'],'completed');tools=self.client.get('/api/ai/chat/'+self.chat).json()['turns'][0]['tools'];self.assertEqual(tools[-1]['url'],'https://example.com/release');self.assertIn('Tavily',tools[-1]['label'])
        self.assertNotIn('PRIVATE_TEST',self.client.get('/api/ai/chats').text)
