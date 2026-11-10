"""Service executable names only; command arguments are never reported here."""
import ntpath
import os
import re
import psutil


def executable_name(command):
    text=str(command or '').strip()
    match=re.match(r'^"([^"]+)"',text) or re.match(r'^(.*?\.(?:exe|sys))(?=\s|$)',text,re.I)
    return ntpath.basename(match.group(1))[:255] if match else ''


def process_fields(info):
    pid=info.get('pid')
    if isinstance(pid,int) and pid>0:
        try:return {'executable':psutil.Process(pid).name()[:255],'executable_source':'process'}
        except (OSError,psutil.Error):pass
    name=executable_name(info.get('binpath'))
    return {'executable':name,'executable_source':'configuration'} if name else {}


def enrich(services):
    if os.name!='nt':return services
    for item in services:
        try:
            info=psutil.win_service_get(item['name']).as_dict()
            item.update(process_fields(info))
            if info.get('display_name'):item.setdefault('display_name',info['display_name'])
        except (OSError,psutil.Error,AttributeError,KeyError):pass
    return services
