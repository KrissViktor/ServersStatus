"""Public GitHub release downloads. Panel credentials are never used here."""
import json
import math
import re
import urllib.parse
import urllib.request

BASE='https://github.com/KrissViktor/ServersStatus/releases/download/'
PLATFORMS={'windows-x64':('windows','ServersStatusService.exe'),'linux-source':('linux','ServersStatus-Linux.tar.gz')}
MAX_PACKAGE=200*1024**2


def validate_url(url,redirect=False):
    if not isinstance(url,str):raise ValueError('Invalid GitHub URL')
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or parsed.fragment:
        raise ValueError('Invalid GitHub URL')
    if parsed.hostname=='github.com' and url.startswith(BASE) and not parsed.query:
        return url
    if redirect and parsed.hostname in ('release-assets.githubusercontent.com','objects.githubusercontent.com'):
        return url
    raise ValueError('Unexpected release host')


class ReleaseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_url(newurl,redirect=True)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def open_public(url):
    validate_url(url)
    request=urllib.request.Request(url,headers={'User-Agent':'ServersStatus-agent','Accept':'application/octet-stream'})
    return urllib.request.build_opener(ReleaseRedirect()).open(request,timeout=30)


def validate_manifest(data,platform):
    if not isinstance(data,dict) or data.get('schema')!=1 or data.get('platform')!=platform:
        raise ValueError('Invalid release manifest')
    version=data.get('version','')
    if not isinstance(version,str) or not re.fullmatch(r'[a-f0-9]{12}',version):raise ValueError('Invalid release version')
    if not isinstance(data.get('sha256'),str) or not re.fullmatch(r'[a-f0-9]{64}',data['sha256']):raise ValueError('Invalid checksum')
    if type(data.get('size')) is not int or not 1<=data['size']<=MAX_PACKAGE:raise ValueError('Invalid release size')
    for key in ('built_at','commit_at'):
        value=data.get(key)
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or not 0<value<4102444800):raise ValueError('Invalid version timestamp')
    kind,filename=PLATFORMS[platform]
    expected=BASE+'agent-'+kind+'-'+version+'/'+filename
    if data.get('download_url')!=expected:raise ValueError('Unexpected release path')
    return data


def manifest(platform):
    kind,_=PLATFORMS[platform]
    with open_public(BASE+'agents-stable/update-'+kind+'.json') as response:
        body=response.read(16385)
    if len(body)>16384:raise ValueError('Manifest too large')
    data=validate_manifest(json.loads(body),platform)
    if data.get('previous') is not None:
        previous=validate_manifest(data['previous'],platform)
        if previous.get('previous') is not None or previous['version']==data['version']:raise ValueError('Invalid previous release')
    return data
