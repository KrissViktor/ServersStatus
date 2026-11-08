"""Read-only structured forecasts; requests contain only the user's city."""
import json
import math
import re
from datetime import datetime,timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
from .ai_web import fetch,WebError


def requested(query):return bool(re.search(r'погод|weather|прогноз.{0,20}(?:моск|температур)|температур.{0,20}(?:улиц|завтра)',query,re.I))


def city(query):
    if re.search(r'москв|\bmoscow\b',query,re.I):return 'Москва'
    if re.search(r'петербург|\bспб\b|saint petersburg',query,re.I):return 'Санкт-Петербург'
    match=re.search(r'(?:\bв|\bво|\bдля|\bin)\s+([\w -]+)',query,re.I)
    if not match:raise WebError('Для прогноза укажите город, например: «Какая погода завтра в Москве?»')
    value=re.split(r'\b(?:завтра|сегодня|послезавтра|на|tomorrow|today)\b',match[1],flags=re.I)[0].strip(' -')
    if not value or len(value)>80:raise WebError('Не удалось определить город. Укажите его название отдельно в вопросе.')
    return value


async def forecast(query):
    place=city(query)
    geo=await fetch('https://geocoding-api.open-meteo.com/v1/search?'+urlencode({'name':place,'count':1,'language':'ru','format':'json'}))
    try:locations=json.loads(geo['text']).get('results',[])
    except (ValueError,AttributeError):raise WebError('Погодный сервис вернул некорректный список городов')
    if not locations:raise WebError('Погодный сервис не нашёл город «'+place+'». Укажите название в именительном падеже и страну.')
    point=locations[0]
    try:
        lat=float(point['latitude']);lon=float(point['longitude'])
        if not -90<=lat<=90 or not -180<=lon<=180:raise ValueError()
    except (ValueError,TypeError,KeyError):raise WebError('Погодный сервис вернул некорректные координаты')
    url='https://api.open-meteo.com/v1/forecast?'+urlencode({'latitude':lat,'longitude':lon,'daily':'temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max','timezone':'auto','forecast_days':7})
    result=await fetch(url)
    try:
        data=json.loads(result['text']);daily=data['daily'];tz=ZoneInfo(data['timezone'])
        offset=2 if 'послезавтра' in query.lower() else 1 if re.search(r'завтра|tomorrow',query,re.I) else 0
        explicit=re.search(r'\b(\d{4}-\d{2}-\d{2}|\d{2}\.\d{2}\.\d{4})\b',query)
        if explicit:
            value=explicit.group(1);target=datetime.strptime(value,'%d.%m.%Y' if '.' in value else '%Y-%m-%d').date().isoformat()
        elif re.search(r'недел|выходн|понедельник|вторник|сред[уа]|четверг|пятниц|суббот|воскресень|через\s+\d',query,re.I):
            raise WebError('Укажите точную дату прогноза (дд.мм.гггг), сегодня, завтра или послезавтра. Доступны ближайшие 7 дней.')
        else:target=(datetime.now(tz).date()+timedelta(days=offset)).isoformat()
        # Never silently substitute today's data for a missing requested day.
        index=daily['time'].index(target)
        fields={key:daily[key][index] for key in ('temperature_2m_min','temperature_2m_max','precipitation_probability_max','precipitation_sum','wind_speed_10m_max')}
        if any(type(value) not in (int,float) or not math.isfinite(value) for value in fields.values()):raise ValueError()
    except (ValueError,TypeError,KeyError,IndexError):raise WebError('В ответе погодного сервиса нет полного прогноза на нужную дату')
    return {'city':point.get('name',place),'region':point.get('admin1',''),'country':point.get('country',''),'date':target,'timezone':data['timezone'],'retrieved':datetime.now(tz).isoformat(timespec='seconds'),**fields},url


def answer(data,source):
    date=datetime.fromisoformat(data['date']).strftime('%d.%m.%Y')
    return (f"{data['city']} · прогноз на {date} ({data['timezone']})\n"
            f"Температура: от {data['temperature_2m_min']:g} до {data['temperature_2m_max']:g} °C.\n"
            f"Вероятность осадков: {data['precipitation_probability_max']:g}%; количество: {data['precipitation_sum']:g} мм.\n"
            f"Максимальный ветер: {data['wind_speed_10m_max']:g} км/ч.\n"
            f"Источник: Open-Meteo [{source}]. Получено: {data['retrieved']}. Это прогноз; фактическая погода может отличаться.")
