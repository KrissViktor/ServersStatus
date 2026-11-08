"""Official Bank of Russia rates, always labelled with effective date/nominal."""
from datetime import datetime
from decimal import Decimal,InvalidOperation
import re
import xml.etree.ElementTree as ET
from .ai_web import fetch,WebError,WebConnectionError,web_proxy

URL='https://www.cbr.ru/scripts/XML_daily.asp'
CURRENCIES={'USD':r'доллар|\busd\b','EUR':r'евро|\beur\b','CNY':r'юан|\bcny\b','GBP':r'фунт|\bgbp\b','CHF':r'франк|\bchf\b','TRY':r'лир|\btry\b','AED':r'дирхам|\baed\b','KZT':r'тенге|\bkzt\b','BYN':r'белорус|\bbyn\b','JPY':r'иен|йен|\bjpy\b'}

def requested(query):
    return bool(re.search(r'курс|сколько.{0,20}(?:рубл|доллар|евро)|(?:USD|EUR|CNY)[ /-]RUB',query,re.I) and (re.search(r'валют',query,re.I) or any(re.search(pattern,query,re.I) for pattern in CURRENCIES.values())))

async def rates(query):
    try:result=await fetch(URL)
    except WebConnectionError as proxy_error:
        if not web_proxy():raise
        # Russian official source may be unreachable from the VPN exit. Retry
        # only this fixed public HTTPS endpoint, without changing global routes.
        try:result=await fetch(URL,direct=True)
        except WebError as direct_error:
            raise WebError('ЦБ недоступен обоими маршрутами. '+str(proxy_error)+'; '+str(direct_error)) from None
    text=result['text']
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():raise WebError('ЦБ вернул неподдерживаемый XML')
    try:
        root=ET.fromstring(text);date=datetime.strptime(root.attrib['Date'],'%d.%m.%Y').strftime('%d.%m.%Y')
        codes=[code for code,pattern in CURRENCIES.items() if re.search(pattern,query,re.I)] or ['USD','EUR','CNY']
        values=[]
        for node in root.findall('Valute'):
            code=node.findtext('CharCode')
            if code not in codes:continue
            nominal=Decimal(node.findtext('Nominal','').replace(' ',''));value=Decimal(node.findtext('Value','').replace(',','.').replace(' ',''))
            if not nominal.is_finite() or not value.is_finite() or nominal<=0 or value<=0:raise ValueError()
            values.append({'currency':code,'rub_per_unit':str(value/nominal)})
        if not values or set(codes)-{v['currency'] for v in values}:raise ValueError()
    except (ET.ParseError,ValueError,InvalidOperation,KeyError):raise WebError('В ответе Банка России нет полного корректного курса запрошенных валют')
    return {'effective_date':date,'base':'RUB','rates':values,'kind':'Официальный курс Банка России, не наличный курс покупки/продажи'},URL

def answer(data,source):
    lines=[f"Официальные курсы Банка России на {data['effective_date']}:"]
    for row in data['rates']:lines.append(f"1 {row['currency']} = {Decimal(row['rub_per_unit']):.4f} ₽")
    lines.append(f"Это курс ЦБ к рублю, не банковский курс покупки/продажи. В выходные может действовать курс, установленный ранее. Источник: Банк России [{source}].")
    return '\n'.join(lines)
