"""Bounded checks of public HTTP endpoints and a local registry snapshot."""
import functools
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import ssl
import time
from urllib.parse import quote, urlsplit, urlunsplit


def hostname(value):
    value = value.rstrip('.').encode('idna').decode().lower()
    if not value or len(value)>253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in value.split('.')):
        raise ValueError('Некорректное доменное имя')
    return value


def target(value):
    if len(value)>1024 or any(ord(ch)<32 or ch.isspace() or ch=='\\' for ch in value):
        raise ValueError('Проверьте адрес сайта')
    url = urlsplit(value)
    if url.scheme not in ('http','https') or not url.hostname or url.username is not None or url.password is not None or url.fragment or url.query or url.port not in (None,80,443):
        raise ValueError('Укажите HTTP или HTTPS URL без учётных данных, параметров и фрагмента. Порты 80 и 443.')
    host = hostname(url.hostname)
    if '.' not in host:
        raise ValueError('Укажите публичное доменное имя')
    path = quote(url.path or '/',safe='/:%!$&\'()*+,;=@-._~')
    return urlunsplit((url.scheme,host+(':'+str(url.port) if url.port else ''),path,'',''))


def public_address(host, port):
    addresses = []
    for family,_,_,_,address in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(address[0])
        if isinstance(ip,ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        tunnel = isinstance(ip,ipaddress.IPv6Address) and (ip.sixtofour or ip.teredo)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip,'scope_id',None) or tunnel:
            raise ValueError('Адрес вне публичной сети')
        addresses.append((family,address))
    if not addresses:
        raise OSError('Не удалось получить адрес')
    return addresses[:4]


def check_http(url, expected, warn_days, now):
    parsed = urlsplit(url)
    tls = parsed.scheme=='https'
    port = parsed.port or (443 if tls else 80)
    conn = None
    result = {'http':'error','code':None,'ms':None,'tls':'unknown' if tls else 'off'}
    started = time.monotonic()
    try:
        addresses = public_address(parsed.hostname,port)
        def connect(_address, timeout, source_address=None):
            for family,address in addresses:
                remaining=4-(time.monotonic()-started)
                if remaining<=0:
                    break
                sock=socket.socket(family,socket.SOCK_STREAM)
                try:
                    sock.settimeout(remaining)
                    sock.connect(address)
                    sock.settimeout(4)
                    return sock
                except OSError:
                    sock.close()
            raise OSError('Соединение с сайтом недоступно')
        if tls:
            conn=http.client.HTTPSConnection(parsed.hostname,port,timeout=4,context=ssl.create_default_context())
        else:
            conn=http.client.HTTPConnection(parsed.hostname,port,timeout=4)
        # Preserve the HTTP Host header and TLS SNI while connecting to a validated address.
        conn._create_connection=connect
        conn.connect()
        if tls:
            cert=conn.sock.getpeercert()
            expires=ssl.cert_time_to_seconds(cert['notAfter'])
            result.update(tls='expiring' if expires-now<=warn_days*86400 else 'ok',expires=expires,
                          issuer=', '.join(value for part in cert.get('issuer',()) for key,value in part if key in ('organizationName','commonName'))[:200])
        conn.request('GET',parsed.path,headers={'User-Agent':'ServersStatus-Monitor/1','Connection':'close'})
        response=conn.getresponse()
        result.update(http='ok' if response.status==expected else 'unexpected',code=response.status)
        response.close()
    except ssl.SSLCertVerificationError as error:
        result.update(tls='invalid',error=str(error.verify_message)[:160])
    except (ValueError,OSError,http.client.HTTPException) as error:
        result['error']=str(error)[:160]
    finally:
        if conn:
            conn.close()
        result['ms']=round((time.monotonic()-started)*1000)
    return result


@functools.lru_cache(maxsize=1)
def read_registry(path, file_version):
    with Path(path).open('rb') as source:
        raw=source.read(32*1024*1024+1)
    if len(raw)>32*1024*1024:
        raise ValueError('Снимок слишком большой')
    data=json.loads(raw)
    if not isinstance(data,dict) or not isinstance(data.get('domains'),list):
        raise ValueError('Некорректный снимок')
    updated=data.get('updated_at')
    if not isinstance(updated,(int,float)) or not math.isfinite(updated) or updated<=0:
        raise ValueError('Некорректное время снимка')
    exact,wild=set(),set()
    for value in data['domains']:
        if not isinstance(value,str):
            raise ValueError('Некорректное доменное имя в снимке')
        if value.startswith('*.'):
            wild.add(hostname(value[2:]))
        else:
            exact.add(hostname(value))
    return updated,exact,wild


def check_registry(url, now):
    path=os.environ.get('STATUS_RKN_SNAPSHOT','')
    if not path:
        return {'rkn':'unconfigured'}
    try:
        stat=Path(path).stat()
        updated,exact,wild=read_registry(path,(stat.st_mtime_ns,stat.st_size,stat.st_ino))
        if now-updated>86400 or updated>now+300:
            return {'rkn':'stale','registry_at':updated}
        host=urlsplit(url).hostname
        labels=host.split('.')
        matched=host in exact or any('.'.join(labels[index:]) in wild for index in range(1,len(labels)))
        return {'rkn':'listed' if matched else 'clear','registry_at':updated}
    except (ValueError,UnicodeError,OSError,RecursionError):
        return {'rkn':'unavailable'}
