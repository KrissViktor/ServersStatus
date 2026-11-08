"""Search/extract API for the local model, with official optional-key mode."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .ai_web import WebError,addresses,normalize_url,web_proxy,connection_error

ORIGIN='https://api.tavily.com'
MAX_BYTES=2*1024*1024


def key():
    try:
        value=Path(os.environ.get('STATUS_AI_SEARCH_KEY_FILE','/var/lib/serversstatus/ai-search-key')).read_text(encoding='utf-8').strip()
        if not 16<=len(value)<=256 or any(ord(c)<33 or ord(c)>126 for c in value):raise WebError('Некорректный файл ключа поиска ИИ')
        return value
    except FileNotFoundError:return None
    except (OSError,UnicodeError):raise WebError('Не удалось прочитать файл ключа поиска ИИ') from None


def info():
    provider=os.environ.get('STATUS_AI_SEARCH_PROVIDER','tavily').strip().lower()
    if provider=='google':return {'provider':'google','label':'Google · HTML-поиск (старый режим)'}
    if provider!='tavily':return {'provider':provider,'label':'Неизвестный поисковый провайдер'}
    try:configured=bool(key())
    except WebError:return {'provider':'tavily','label':'Tavily · ошибка файла ключа'}
    return {'provider':'tavily','key_configured':configured,'label':'Tavily · личный ключ' if configured else 'Tavily · без ключа, лимиты сервиса'}


async def request(endpoint,payload):
    if endpoint not in ('search','extract'):raise WebError('Неизвестная операция поискового API')
    token=key();proxy=web_proxy();host='api.tavily.com'
    ips=await addresses(host,443)
    headers={'Host':host,'Accept':'application/json','Accept-Encoding':'identity','X-Client-Source':'serversstatus','Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    else:headers['X-Tavily-Access-Mode']='keyless'
    options={'trust_env':False,'follow_redirects':False,'timeout':httpx.Timeout(45,connect=8)}
    if proxy:options['proxy']=proxy
    url=httpx.URL(ORIGIN+'/'+endpoint).copy_with(host=ips[0])
    try:
        async with httpx.AsyncClient(**options) as client:
            async with client.stream('POST',url,headers=headers,json=payload,extensions={'sni_hostname':host}) as response:
                status=response.status_code
                if status==401:raise WebError('Tavily отклонил ключ или анонимный доступ. Настройте личный ключ поиска на Raspi.')
                if status in (402,403,429,432,433):raise WebError('Tavily ограничил доступ или исчерпан лимит поиска. Проверьте аккаунт/лимиты либо подключите личный ключ; повторите позже.')
                if status!=200:raise WebError('Поисковый API Tavily недоступен: HTTP '+str(status))
                if response.headers.get('content-encoding','identity').lower() not in ('','identity'):raise WebError('Tavily вернул неподдерживаемое сжатие')
                length=response.headers.get('content-length','0')
                if length.isdigit() and int(length)>MAX_BYTES:raise WebError('Ответ поиска слишком большой')
                data=bytearray()
                async for chunk in response.aiter_raw():
                    data.extend(chunk)
                    if len(data)>MAX_BYTES:raise WebError('Ответ поиска слишком большой')
        try:result=json.loads(data)
        except (ValueError,UnicodeError):raise WebError('Tavily вернул некорректный JSON') from None
        if not isinstance(result,dict):raise WebError('Tavily вернул неизвестный формат')
        if result.get('error'):raise WebError('Tavily сообщил об ограничении или ошибке поиска. Проверьте доступ и лимиты аккаунта.')
        return result
    except httpx.HTTPError as exc:raise connection_error(exc,host,bool(proxy)) from None


async def search(query):
    if not query.strip():raise WebError('Введите вопрос или поисковый запрос')
    result=await request('search',{'query':query[:300],'topic':'general','search_depth':'basic','max_results':5,'include_answer':False,'include_raw_content':'text','include_images':False})
    rows=result.get('results')
    if not isinstance(rows,list):raise WebError('Поисковый API не вернул список источников')
    items=[];seen=set()
    for row in rows[:10]:
        if not isinstance(row,dict):continue
        try:url=normalize_url(row.get('url'))
        except WebError:continue
        if url in seen:continue
        seen.add(url)
        item={'url':url,'title':str(row.get('title') or url)[:200],'snippet':str(row.get('content') or '')[:500]}
        raw=row.get('raw_content')
        if isinstance(raw,str) and raw.strip():item['_page']={'url':url,'type':'text/plain','text':raw[:12000],'provider':'Tavily'}
        items.append(item)
        if len(items)==5:break
    if not items:raise WebError('Tavily не нашёл подходящие публичные источники. Уточните вопрос.')
    return items


async def extract(value):
    url=normalize_url(value);parsed=urlsplit(url)
    # Do not relay private/metadata targets to a third-party extraction service.
    await addresses(parsed.hostname,443 if parsed.scheme=='https' else 80)
    result=await request('extract',{'urls':[url],'extract_depth':'basic','format':'text','include_images':False})
    for row in result.get('results',[])[:2]:
        if not isinstance(row,dict):continue
        text=row.get('raw_content')
        if isinstance(text,str) and text.strip():
            target=normalize_url(row.get('url') or url)
            return {'url':target,'type':'text/plain','text':text[:12000],'provider':'Tavily'}
    raise WebError('Tavily не смог извлечь текст указанной страницы')


if __name__=='__main__':
    import asyncio
    async def check():
        print(info()['label'])
        try:
            results=await search('Python official documentation')
            print('Поиск работает: публичных источников — '+str(len(results)))
        except WebError as exc:
            print('Ошибка: '+str(exc));raise SystemExit(1)
    asyncio.run(check())
