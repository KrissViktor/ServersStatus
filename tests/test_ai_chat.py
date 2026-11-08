import asyncio
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from server import app as a
from server import ai_chat as ai


class AIChatTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.addCleanup(setattr,a,'DB',a.DB);a.DB=str(Path(self.tmp.name)/'db.sqlite3')
        self.secret=Path(self.tmp.name)/'key';self.secret.write_text('AI_PRIVATE_KEY_TEST_ONLY')
        self.env=patch.dict(os.environ,{'STATUS_AI_KEY_FILE':str(self.secret)});self.env.start();self.addCleanup(self.env.stop)
        self.kick=patch('server.ai_chat.kick');self.kick.start();self.addCleanup(self.kick.stop)
        from server.security import limiter
        limiter.reset();self.client=TestClient(a.app,base_url='https://testserver');self.client.cookies.set('session','test')
        with a.db() as c:
            for name,role in [('alice','administrator'),('bob','administrator'),('reader','viewer')]:
                c.execute('INSERT INTO users VALUES (?,?,?)',(name,'00'*16,'0'*128));c.execute('INSERT INTO user_roles VALUES (?,?,1)',(name,role))
            c.execute('INSERT INTO sessions VALUES (?,?)',(a.digest('test'),time.time()+3600));c.execute("INSERT INTO session_users VALUES (?,'alice')",(a.digest('test'),))
        self.csrf=re.search('data-ai-csrf="([^"]+)"',self.client.get('/ai').text).group(1)
        self.chat='a'*32;self.nonce='b'*32

    def ask(self,**changes):
        return self.client.post('/api/ai/ask',json={'csrf':self.csrf,'chat':self.chat,'nonce':self.nonce,'question':'Привет',**changes})

    def role(self,name):
        with a.db() as c:c.execute('UPDATE session_users SET name=?',(name,))

    def test_permissions_csrf_and_key_never_exposed(self):
        self.assertEqual(self.ask(csrf='wrong').status_code,403)
        self.assertEqual(self.ask(question=' ').status_code,400)
        self.assertEqual(self.ask(question='x'*4001).status_code,422)
        for url in ['/ai','/api/ai/chats']:
            response=self.client.get(url);self.assertNotIn('AI_PRIVATE_KEY_TEST_ONLY',response.text);self.assertEqual(response.headers['cache-control'],'no-store')
        self.role('reader');self.assertEqual(self.client.get('/ai').status_code,403);self.assertEqual(self.ask().status_code,403)
        self.client.cookies.clear();self.assertEqual(self.ask().status_code,401)

    def test_idempotency_owner_privacy_cancel_delete(self):
        first=self.ask();self.assertEqual(first.status_code,200)
        self.assertEqual(self.ask().json(),first.json())
        self.assertEqual(self.ask(question='Changed').status_code,409)
        self.assertEqual(self.ask(nonce='c'*32).status_code,409)
        self.role('bob');self.assertEqual(self.client.get('/api/ai/chats').json()['chats'],[])
        self.assertEqual(self.client.get('/api/ai/chat/'+self.chat).status_code,404)
        self.assertEqual(self.client.post('/api/ai/chat/'+self.chat+'/delete',json={'csrf':self.csrf}).status_code,404)
        self.role('alice');self.assertEqual(self.client.post('/api/ai/chat/'+self.chat+'/cancel',json={'csrf':self.csrf}).status_code,200)
        self.assertEqual(self.client.get('/api/ai/chat/'+self.chat).json()['turns'][0]['status'],'cancelled')
        self.assertEqual(self.client.post('/api/ai/chat/'+self.chat+'/delete',json={'csrf':self.csrf}).status_code,200)
        self.assertEqual(self.client.get('/api/ai/chat/'+self.chat).status_code,404)

    def test_missing_config_global_queue_and_retention(self):
        self.secret.unlink();self.assertFalse(self.client.get('/api/ai/chats').json()['configured']);self.assertEqual(self.ask().status_code,503)
        self.secret.write_text('AI_PRIVATE_KEY_TEST_ONLY')
        with a.db() as c:
            for i in range(3):c.execute("INSERT INTO ai_turns(owner,chat,nonce,question,status,created,updated) VALUES (?,?,?,?, 'queued',?,?)",('other'+str(i),self.chat,str(i),'q',time.time(),time.time()))
        self.assertEqual(self.ask().status_code,429)
        with a.db() as c:
            c.execute('UPDATE ai_turns SET created=0,updated=0');ai.clean(c,time.time())
            self.assertEqual(c.execute('SELECT COUNT(*) FROM ai_turns').fetchone()[0],0)

    def prepare(self):
        identifier=self.ask().json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,))
            job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone());messages=ai.context(c,job)
        return job,messages

    def generate(self,handler,job,messages):
        original=httpx.AsyncClient
        def client(**kwargs):
            self.assertFalse(kwargs['trust_env']);self.assertFalse(kwargs['follow_redirects'])
            return original(transport=httpx.MockTransport(handler),**kwargs)
        with patch('server.ai_chat.httpx.AsyncClient',side_effect=client):asyncio.run(ai.generate(a.db,job,messages,'AI_PRIVATE_KEY_TEST_ONLY'))
        with a.db() as c:return dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(job['id'],)).fetchone())

    def test_streaming_plain_text_and_context_isolation(self):
        job,messages=self.prepare();seen=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(stream):
                yield b'data: {"choices":[{"delta":{"content":"first "}}]}\n\n'
                await asyncio.sleep(.05)
                with a.db() as c:seen.append(c.execute('SELECT reply FROM ai_turns WHERE id=?',(job['id'],)).fetchone()[0])
                yield b'data: {"choices":[{"delta":{"content":"<script>text</script>"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        def handler(request):
            self.assertEqual(str(request.url),ai.ORIGIN+'/v1/chat/completions')
            self.assertEqual(request.headers['authorization'],'Bearer AI_PRIVATE_KEY_TEST_ONLY')
            payload=json.loads(request.content);self.assertTrue(payload['stream']);self.assertEqual(payload['max_tokens'],512)
            return httpx.Response(200,stream=Stream())
        result=self.generate(handler,job,messages)
        self.assertEqual(result['status'],'completed');self.assertIn('first ',seen);self.assertEqual(result['reply'],'first <script>text</script>')
        self.role('bob');self.chat='c'*32;self.nonce='d'*32;new_job,new_messages=self.prepare()
        self.assertNotIn('<script>',json.dumps(new_messages));self.assertEqual(len(new_messages),2)

    def test_upstream_errors_timeouts_and_cancellation_are_safe(self):
        job,messages=self.prepare()
        result=self.generate(lambda r:httpx.Response(401,text='PRIVATE-ERROR-DETAIL'),job,messages)
        self.assertEqual(result['status'],'failed');self.assertNotIn('PRIVATE',result['error']);self.assertIn('ключ',result['error'])
        with a.db() as c:c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(job['id'],))
        result=self.generate(lambda r:httpx.Response(302,headers={'Location':'https://evil.invalid/'}),job,messages)
        self.assertEqual(result['status'],'failed')
        with a.db() as c:c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(job['id'],))
        async def slow(request):await asyncio.sleep(1);return httpx.Response(200,content=b'')
        with patch('server.ai_chat.MAX_RUNTIME',.01):result=self.generate(slow,job,messages)
        self.assertEqual(result['status'],'failed');self.assertIn('Время',result['error'])
        with a.db() as c:c.execute("UPDATE ai_turns SET status='cancelled' WHERE id=?",(job['id'],))
        def forbidden(request):raise AssertionError('Cancelled request must not contact model')
        self.assertEqual(self.generate(forbidden,job,messages)['status'],'cancelled')

    def test_context_bound_and_stale_job_failure(self):
        job,messages=self.prepare()
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='completed',reply=? WHERE id=?",('old answer',job['id']))
        self.nonce='e'*32
        next_job,context=self.prepare();self.assertEqual(len(context),4);self.assertEqual(context[2]['content'],'old answer')
        self.assertLessEqual(sum(len(m['content']) for m in context),8000)
        with a.db() as c:
            c.execute('UPDATE ai_turns SET updated=0 WHERE id=?',(next_job['id'],));ai.clean(c,time.time())
            self.assertEqual(c.execute('SELECT status FROM ai_turns WHERE id=?',(next_job['id'],)).fetchone()[0],'failed')

    def test_deleted_account_history_is_not_inherited_by_recreated_name(self):
        self.ask()
        with a.db() as c:c.execute("INSERT INTO users VALUES ('admin',?,?)",('00'*16,'0'*128))
        self.role('admin')
        response=self.client.post('/users/delete',data={'csrf':self.csrf,'name':'alice','confirmation':'alice'},follow_redirects=False)
        self.assertEqual(response.status_code,303)
        with a.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM ai_turns WHERE owner='alice'").fetchone()[0],0)

    def test_real_worker_claims_and_completes_without_locking_web_requests(self):
        self.kick.stop()
        original=httpx.AsyncClient
        async def handler(request):
            await asyncio.sleep(.05)
            return httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"worker answer"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        def client(**kwargs):return original(transport=httpx.MockTransport(handler),**kwargs)
        with patch('server.ai_chat.httpx.AsyncClient',side_effect=client):
            response=self.ask();self.assertEqual(response.status_code,200)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                with a.db() as c:row=c.execute('SELECT status,reply FROM ai_turns').fetchone()
                if row and row['status']=='completed' and not ai._lock.locked():break
                time.sleep(.02)
            else:self.fail('Worker did not finish')
        self.assertEqual(row['reply'],'worker answer')
