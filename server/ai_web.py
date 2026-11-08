"""Bounded, DNS-pinned public HTTP reads; no credentials, local network or proxies."""
import asyncio
import html
from html.parser import HTMLParser
import ipaddress
import re
import socket
from urllib.parse import urlsplit,urlunsplit,urljoin,quote,parse_qs
import httpx

class WebError(Exception):pass
MAX_BYTES=512*1024


def public_ip(value):
    try:
        address=ipaddress.ip_address(value)
        if address.version==6 and (address.ipv4_mapped or address.sixtofour or address.teredo):return False
        return address.is_global and not (address.is_multicast or address.is_reserved or address.is_loopback or address.is_link_local or address.is_unspecified) and str(address)!='168.63.129.16'
    except ValueError:return False


def normalize_url(value):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<33 or ord(c)==127 for c in value):raise WebError('Некорректная ссылка')
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or parsed.username is not None or parsed.password is not None:raise ValueError()
        host=(parsed.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
        port=parsed.port if parsed.port is not None else (443 if parsed.scheme=='https' else 80)
        if not host or port!=(443 if parsed.scheme=='https' else 80):raise ValueError()
        if host=='localhost' or host.endswith(('.localhost','.local','.internal','.onion')):raise ValueError()
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9.-]{1,253}',host):raise ValueError()
        else:
            if not public_ip(str(address)):raise ValueError()
        netloc='['+host+']' if ':' in host else host
        return urlunsplit((parsed.scheme,netloc,parsed.path or '/',parsed.query,''))
    except (ValueError,UnicodeError):raise WebError('Разрешены только публичные HTTP/HTTPS-ссылки без паролей и нестандартных портов')


async def addresses(host,port):
    try:
        items=await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host,port,type=socket.SOCK_STREAM),5)
    except (OSError,asyncio.TimeoutError):raise WebError('Не удалось разрешить адрес сайта')
    result=list(dict.fromkeys(item[4][0] for item in items))
    if not result or not all(public_ip(value) for value in result):raise WebError('Локальные, служебные и непубличные адреса запрещены')
    return sorted(result,key=lambda v:ipaddress.ip_address(v).version)


async def fetch(value):
    current=normalize_url(value)
    for hop in range(4):
        parsed=urlsplit(current);port=443 if parsed.scheme=='https' else 80
        ips=await addresses(parsed.hostname,port)
        # Connect to the validated IP snapshot, never resolve the hostname again.
        # Host and TLS SNI retain the original hostname/certificate verification.
        pinned=httpx.URL(current).copy_with(host=ips[0])
        try:
            async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=httpx.Timeout(8,connect=5)) as client:
                async with client.stream('GET',pinned,headers={'Host':parsed.netloc,'User-Agent':'ServersStatus-Research/1.0','Accept':'text/html,application/xhtml+xml,application/rss+xml,text/plain,application/xml;q=0.9','Accept-Encoding':'identity'},extensions={'sni_hostname':parsed.hostname}) as response:
                    if response.status_code in (301,302,303,307,308):
                        target=response.headers.get('location')
                        if not target:raise WebError('Сайт вернул пустое перенаправление')
                        current=normalize_url(urljoin(current,target));continue
                    if response.status_code!=200:raise WebError('Сайт недоступен: HTTP '+str(response.status_code))
                    kind=response.headers.get('content-type','').lower()
                    if not (kind.startswith('text/') or any(x in kind for x in ('application/xhtml+xml','application/xml','application/rss+xml','application/json'))):raise WebError('Поддерживаются текстовые страницы; этот формат пока не читается')
                    if response.headers.get('content-encoding','identity').lower() not in ('','identity'):raise WebError('Сайт прислал неподдерживаемое сжатие')
                    length=response.headers.get('content-length','0')
                    if length.isdigit() and int(length)>MAX_BYTES:raise WebError('Страница слишком большая')
                    data=bytearray()
                    async for chunk in response.aiter_raw():
                        data.extend(chunk)
                        if len(data)>MAX_BYTES:raise WebError('Страница слишком большая')
                    charset=re.search(r'charset=["\']?([a-zA-Z0-9_-]+)',kind)
                    encoding=charset.group(1) if charset else 'utf-8'
                    try:text=bytes(data).decode(encoding,errors='replace')
                    except LookupError:text=bytes(data).decode('utf-8',errors='replace')
                    return {'url':current,'type':kind,'text':text}
        except httpx.HTTPError:raise WebError('Не удалось прочитать сайт: соединение или сертификат недоступны')
    raise WebError('Слишком много перенаправлений')


class Text(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript','iframe','svg','nav','footer'):self.skip+=1
        if tag in ('p','div','br','li','tr','h1','h2','h3','pre'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript','iframe','svg','nav','footer') and self.skip:self.skip-=1
        if tag in ('p','div','li','tr','h1','h2','h3','pre'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)


def page_text(content,kind):
    if 'html' in kind:
        parser=Text();parser.feed(content);content=' '.join(parser.parts)
    return '\n'.join(re.sub(r'[ \t]+',' ',line).strip() for line in content.splitlines() if line.strip())[:4000]


class GoogleResults(HTMLParser):
    """Extract result headings and adjacent snippets without CSS class coupling."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchor=None;self.heading=False;self.title=[];self.items=[];self.current=None;self.skip=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','style','noscript'):self.skip+=1
        if tag=='a':self.anchor=attrs.get('href','')
        if tag=='h3' and self.anchor:
            self.heading=True;self.title=[]
    def handle_data(self,data):
        if self.skip:return
        if self.heading:self.title.append(data)
        elif self.current and len(self.current['snippet'])<700:self.current['snippet']+=' '+data.strip()
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript') and self.skip:self.skip-=1
        if tag=='h3' and self.heading:
            self.heading=False;href=urljoin('https://www.google.com',self.anchor or '')
            parsed=urlsplit(href)
            if parsed.hostname in ('www.google.com','google.com') and parsed.path=='/url':
                query=parse_qs(parsed.query);href=(query.get('q') or query.get('url') or [''])[0]
            try:
                url=normalize_url(href);host=urlsplit(url).hostname
                if host in ('google.com','www.google.com','accounts.google.com','consent.google.com','support.google.com'):return
            except WebError:return
            title=' '.join(' '.join(self.title).split())[:200]
            if title and not any(item['url']==url for item in self.items):
                self.current={'url':url,'title':title,'snippet':''};self.items.append(self.current)
        if tag=='a':self.anchor=None


async def search(query):
    if not query.strip():raise WebError('Введите вопрос или поисковый запрос')
    result=await fetch('https://www.google.com/search?hl=ru&num=5&gbv=1&q='+quote(query[:300],safe=''))
    host=urlsplit(result['url']).hostname
    text=result['text'];lower=text.lower()
    if host in ('consent.google.com','accounts.google.com') or any(marker in lower for marker in ('/sorry/','unusual traffic','detected unusual','g-recaptcha','our systems have detected')):
        raise WebError('Google запросил CAPTCHA или согласие. Автоматический поиск временно недоступен; можно указать прямую ссылку.')
    parser=GoogleResults();parser.feed(text)
    items=parser.items[:5]
    for item in items:item['snippet']=' '.join(item['snippet'].split())[:600]
    if not items:raise WebError('Google не вернул читаемую выдачу (возможно, требуется JavaScript или согласие). Можно указать прямую ссылку; Bing не используется.')
    return items
