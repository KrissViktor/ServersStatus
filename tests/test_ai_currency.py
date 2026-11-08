import asyncio
import json
import unittest
from unittest.mock import AsyncMock,patch
import test_ai_chat as fixture
from server import ai_currency as currency,ai_chat,app as a
from server.ai_web import WebError,WebConnectionError
XML='<ValCurs Date="09.11.2026"><Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>82,1234</Value></Valute><Valute><CharCode>JPY</CharCode><Nominal>100</Nominal><Value>50,0000</Value></Valute></ValCurs>'
class CurrencyTest(unittest.TestCase):
    def test_official_date_and_nominal(self):
        self.assertTrue(currency.requested('Какой курс доллара?'));self.assertFalse(currency.requested('История CPU'))
        with patch('server.ai_currency.fetch',new_callable=AsyncMock,return_value={'text':XML}) as fetch:data,url=asyncio.run(currency.rates('курс доллара и иены'))
        fetch.assert_awaited_once_with(currency.URL);self.assertEqual(data['rates'][1]['rub_per_unit'],'0.5000')
        answer=currency.answer(data,'S1');self.assertIn('09.11.2026',answer);self.assertIn('82.1234',answer);self.assertIn('1 JPY = 0.5000',answer);self.assertIn('не банковский',answer)
    def test_proxy_connection_failure_retries_official_source_directly(self):
        with patch('server.ai_currency.web_proxy',return_value='socks5h://127.0.0.1:1080'),patch('server.ai_currency.fetch',new_callable=AsyncMock,side_effect=[WebConnectionError('proxy connection failed'),{'text':XML}]) as fetch:
            data,url=asyncio.run(currency.rates('курс доллара'))
        self.assertEqual(data['rates'][0]['currency'],'USD');self.assertEqual(fetch.await_args_list[1].args,(currency.URL,));self.assertEqual(fetch.await_args_list[1].kwargs,{'direct':True})
    def test_both_route_errors_are_visible_and_blocking_errors_do_not_retry(self):
        with patch('server.ai_currency.web_proxy',return_value='socks5h://127.0.0.1:1080'),patch('server.ai_currency.fetch',new_callable=AsyncMock,side_effect=[WebConnectionError('proxy failed'),WebConnectionError('direct failed')]):
            with self.assertRaisesRegex(WebError,'proxy failed; direct failed'):asyncio.run(currency.rates('курс доллара'))
        for error,proxy in [(WebError('private IP blocked'),'socks5h://127.0.0.1:1080'),(WebConnectionError('direct failed'),None)]:
            with patch('server.ai_currency.web_proxy',return_value=proxy),patch('server.ai_currency.fetch',new_callable=AsyncMock,side_effect=error) as fetch:
                with self.assertRaises(WebError):asyncio.run(currency.rates('курс доллара'))
                self.assertEqual(fetch.await_count,1)

    def test_invalid_missing_and_entity_data_fail_closed(self):
        for text in ['<!DOCTYPE foo>'+XML,XML.replace('82,1234','NaN'),XML.replace('<Nominal>1</Nominal>','<Nominal>0</Nominal>'),'<ValCurs Date="09.11.2026"/>']:
            with self.subTest(text=text),patch('server.ai_currency.fetch',new_callable=AsyncMock,return_value={'text':text}):
                with self.assertRaises(WebError):asyncio.run(currency.rates('курс доллара'))

class CurrencyIntegrationTest(unittest.TestCase):
    setUp=fixture.AIChatTest.setUp
    ask=fixture.AIChatTest.ask
    generate=fixture.AIChatTest.generate
    def test_currency_does_not_depend_on_google_or_model_interpretation(self):
        identifier=self.ask(question='Какой курс доллара?',internet_access=True).json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,));job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone());messages=ai_chat.context(c,job)
        with patch('server.ai_currency.fetch',new_callable=AsyncMock,return_value={'text':XML}):
            result=self.generate(lambda request: (_ for _ in ()).throw(AssertionError('No Google or model needed')),job,messages)
        self.assertEqual(result['status'],'completed');self.assertIn('82.1234',result['reply']);self.assertIn('09.11.2026',result['reply'])
