import asyncio
from datetime import datetime,timedelta
import json
import unittest
from unittest.mock import AsyncMock,patch
from zoneinfo import ZoneInfo
import test_ai_chat as fixture
from server import ai_weather as weather,ai_chat,app as a
from server.ai_web import WebError


def responses():
    target=(datetime.now(ZoneInfo('Europe/Moscow')).date()+timedelta(days=1)).isoformat()
    return [{'text':json.dumps({'results':[{'name':'Москва','latitude':55.75,'longitude':37.62,'country':'Россия'}]})}, {'text':json.dumps({'timezone':'Europe/Moscow','daily':{'time':[target],'temperature_2m_min':[1.5],'temperature_2m_max':[5.5],'precipitation_probability_max':[40],'precipitation_sum':[1.2],'wind_speed_10m_max':[15]}})}]


class WeatherTest(unittest.TestCase):
    def test_city_and_real_date_fields(self):
        self.assertTrue(weather.requested('Какая погода завтра в Москве?'));self.assertEqual(weather.city('Погода в Москве'),'Москва')
        with self.assertRaises(WebError):weather.city('Какая погода завтра?')
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,side_effect=responses()) as fetch:
            data,url=asyncio.run(weather.forecast('Какая погода завтра в Москве?'))
        self.assertEqual(data['temperature_2m_max'],5.5);self.assertIn('api.open-meteo.com',url)
        self.assertIn('geocoding-api.open-meteo.com',fetch.await_args_list[0].args[0]);self.assertNotIn('погода',fetch.await_args_list[0].args[0])
        self.assertIn('5.5 °C',weather.answer(data,'S1'));self.assertIn(data['date'].split('-')[2],weather.answer(data,'S1'))
    def test_explicit_date_and_unsupported_relative_date(self):
        values=responses();target=json.loads(values[1]['text'])['daily']['time'][0]
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,side_effect=values):
            data,_=asyncio.run(weather.forecast('погода в Москве '+target))
        self.assertEqual(data['date'],target)
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,side_effect=responses()):
            with self.assertRaisesRegex(WebError,'точную дату'):asyncio.run(weather.forecast('погода в Москве на выходных'))

    def test_empty_incomplete_and_wrong_day_are_not_forecasts(self):
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,return_value={'text':'{"results":[]}'}):
            with self.assertRaises(WebError):asyncio.run(weather.forecast('погода в Москве'))
        for issue in ('missing','wrong_day'):
            values=responses();data=json.loads(values[1]['text'])
            if issue=='missing':data['daily']['temperature_2m_min']=[None]
            else:data['daily']['time']=['2000-01-01']
            values[1]['text']=json.dumps(data)
            with patch('server.ai_weather.fetch',new_callable=AsyncMock,side_effect=values):
                with self.assertRaises(WebError):asyncio.run(weather.forecast('погода завтра в Москве'))

class WeatherIntegrationTest(unittest.TestCase):
    setUp=fixture.AIChatTest.setUp
    ask=fixture.AIChatTest.ask
    generate=fixture.AIChatTest.generate
    def run_weather(self):
        identifier=self.ask(question='Какая погода завтра в Москве?',internet_access=True).json()['id']
        with a.db() as c:
            c.execute("UPDATE ai_turns SET status='running' WHERE id=?",(identifier,));job=dict(c.execute('SELECT * FROM ai_turns WHERE id=?',(identifier,)).fetchone());messages=ai_chat.context(c,job)
        def forbidden(request):raise AssertionError('Structured weather must not depend on model interpretation')
        return self.generate(forbidden,job,messages)
    def test_forecast_cannot_be_replaced_with_generic_model_refusal(self):
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,side_effect=responses()):result=self.run_weather()
        self.assertEqual(result['status'],'completed');self.assertIn('5.5 °C',result['reply']);self.assertIn('Open-Meteo [S',result['reply'])
        tools=self.client.get('/api/ai/chat/'+self.chat).json()['turns'][0]['tools'];self.assertEqual(tools[0]['status'],'completed');self.assertIn('api.open-meteo.com',tools[0]['url'])
    def test_upstream_failure_is_visible_and_not_fabricated(self):
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,side_effect=WebError('Сайт недоступен: HTTP 503')):result=self.run_weather()
        self.assertEqual(result['status'],'completed');self.assertIn('HTTP 503',result['reply']);self.assertNotIn('°C',result['reply'])
        self.assertEqual(self.client.get('/api/ai/chat/'+self.chat).json()['turns'][0]['tools'][0]['status'],'failed')
