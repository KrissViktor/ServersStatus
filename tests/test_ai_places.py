import asyncio
from datetime import datetime,timedelta
import json
import unittest
from unittest.mock import AsyncMock,patch
from urllib.parse import parse_qs,urlsplit
from zoneinfo import ZoneInfo
from server import ai_places as places,ai_weather as weather
from server.ai_web import WebError

class PlacesTest(unittest.TestCase):
    def test_cases_agreement_and_lexical_prepositional_tails(self):
        cases={'Мытищах':'Мытищи','Нижнем Новгороде':'Нижний Новгород','Нижней Туре':'Нижняя Тура','Великих Луках':'Великие Луки','Набережных Челнах':'Набережные Челны','Минеральных Водах':'Минеральные Воды','Ростове-на-Дону':'Ростов-на-Дону','Комсомольске-на-Амуре':'Комсомольск-на-Амуре','Петропавловске-Камчатском':'Петропавловск-Камчатский','Санкт-Петербурге':'Санкт-Петербург','Твери':'Тверь','Электростали':'Электросталь','Сочи':'Сочи','Орле':'Орёл','Щёлкове':'Щёлково'}
        for value,expected in cases.items():
            with self.subTest(value=value):self.assertEqual(weather.city('Погода завтра в '+value+'?'),expected)
    def test_location_extraction_preserves_hyphen_and_handles_date(self):
        for query in ('Погода на завтра в Мытищах','Погода в Мытищах на завтра','Погода в г. Мытищах 10.11.2026','Погода для города Мытищ','Погода Мытищи завтра','Погода завтра Мытищи'):
            with self.subTest(query=query):self.assertEqual(weather.city(query),'Мытищи')
        self.assertEqual(weather.city('Погода в Ростове-на-Дону на завтра'),'Ростов-на-Дону')
        self.assertEqual(weather.city('Погода Москва'),'Москва')
        self.assertEqual(weather.city('weather in London tomorrow'),'London')
        for query in ('Какая погода завтра?','Погода на завтра','Прогноз погоды сегодня'):
            with self.subTest(query=query),self.assertRaises(WebError):weather.city(query)
    def test_unknown_spelling_is_preserved(self):
        self.assertEqual(places.normalize('Зюзюблюмбах'),'Зюзюблюмбах')
    def test_forecast_searches_canonical_name_and_reports_official_location(self):
        target=(datetime.now(ZoneInfo('Europe/Moscow')).date()+timedelta(days=1)).isoformat()
        values=[{'text':json.dumps({'results':[{'name':'Мытищи','admin1':'Московская область','country':'Россия','latitude':55.91,'longitude':37.73}]})},{'text':json.dumps({'timezone':'Europe/Moscow','daily':{'time':[target],'temperature_2m_min':[1],'temperature_2m_max':[5],'precipitation_probability_max':[10],'precipitation_sum':[0],'wind_speed_10m_max':[12]}})}]
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,side_effect=values) as fetch:data,_=asyncio.run(weather.forecast('Какая погода завтра в Мытищах?'))
        self.assertEqual(parse_qs(urlsplit(fetch.await_args_list[0].args[0]).query)['name'],['Мытищи'])
        self.assertIn('Мытищи, Московская область, Россия',weather.answer(data,'S1'))
    def test_unrecognized_city_has_no_demand_to_rephrase_in_nominative(self):
        with patch('server.ai_weather.fetch',new_callable=AsyncMock,return_value={'text':'{"results":[]}'}) as fetch:
            with self.assertRaises(WebError) as caught:asyncio.run(weather.forecast('Погода в Мытищах'))
        self.assertEqual(fetch.await_count,2);self.assertNotIn('именительном',str(caught.exception));self.assertIn('регион',str(caught.exception))
