import asyncio
import json
import time
import unittest
from unittest.mock import patch
import httpx
import test_ai_chat as fixture
from server import ai_chat,app as a
from server.ai_tools import Session

class ActivityTest(unittest.TestCase):
    setUp=fixture.AIChatTest.setUp
    ask=fixture.AIChatTest.ask
    prepare=fixture.AIChatTest.prepare
    generate=fixture.AIChatTest.generate
    def test_live_phase_and_answer_are_separate(self):
        job,messages=self.prepare();phases=[]
        class Stream(httpx.AsyncByteStream):
            async def __aiter__(stream):
                with a.db() as c:phases.append(c.execute('SELECT activity FROM ai_turns').fetchone()[0])
                yield b'data: {"choices":[{"delta":{"reasoning_content":"INTERNAL_STREAM_ONLY"}}]}\n\n'
                yield b'data: {"choices":[{"delta":{"content":"Visible answer"}}]}\n\n'
                with a.db() as c:phases.append(c.execute('SELECT activity FROM ai_turns').fetchone()[0])
                yield b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        result=self.generate(lambda request:httpx.Response(200,stream=Stream()),job,messages)
        self.assertEqual(phases,['preparing_answer','writing_answer']);self.assertEqual(result['reply'],'Visible answer')
        data=self.client.get('/api/ai/chat/'+self.chat).json();self.assertNotIn('INTERNAL_STREAM_ONLY',json.dumps(data));self.assertEqual(data['turns'][0]['activity'],'writing_answer')
    def test_tool_stage_and_cancelled_request_cannot_be_overwritten(self):
        identifier=self.ask(portal_access=True).json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,));job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone())
        asyncio.run(Session(a.db,job,[]).execute('events',{}))
        with a.db() as c:
            self.assertEqual(c.execute('SELECT activity FROM ai_turns').fetchone()[0],'tool:events');c.execute("UPDATE ai_turns SET status='cancelled'")
        ai_chat._activity(a.db,identifier,'preparing_answer')
        with a.db() as c:self.assertEqual(c.execute('SELECT activity FROM ai_turns').fetchone()[0],'tool:events')
    def test_longer_read_timeout_and_queue_survives_old_limit(self):
        self.assertGreaterEqual(ai_chat.MAX_RUNTIME,540);self.assertGreaterEqual(ai_chat.MAX_TOOL_RUNTIME,900)
        job,messages=self.prepare();original=httpx.AsyncClient;seen=[]
        def client(**kwargs):
            seen.append(kwargs['timeout'].read)
            return original(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')),**kwargs)
        with patch('server.ai_chat.httpx.AsyncClient',side_effect=client):asyncio.run(ai_chat.generate(a.db,job,messages,'TEST_KEY'))
        self.assertEqual(seen,[540])
        identifier=self.ask(nonce='c'*32,portal_access=True).json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,));tool_job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone());tool_messages=ai_chat.context(c,tool_job)
        with patch('server.ai_chat.httpx.AsyncClient',side_effect=client):asyncio.run(ai_chat.generate(a.db,tool_job,tool_messages,'TEST_KEY'))
        self.assertEqual(seen,[540,900])
        now=time.time()
        with a.db() as c:
            c.execute("INSERT INTO ai_turns(owner,chat,nonce,question,status,created,updated) VALUES ('bob','other','other','q','queued',?,?)",(now-1200,now-1200));ai_chat.clean(c,now)
            self.assertEqual(c.execute("SELECT status FROM ai_turns WHERE nonce='other'").fetchone()[0],'queued')
