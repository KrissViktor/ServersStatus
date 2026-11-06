"""Read-only systemd service state. No shell or privileged service control."""
import re
import subprocess

UNIT=re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.@:\-]{0,254}')


def systemd_services(names, execute=subprocess.run):
    normalized=[]
    for name in names[:100]:
        if not isinstance(name,str) or not UNIT.fullmatch(name):
            continue
        unit=name if name.endswith(('.service','.timer','.socket')) else name+'.service'
        if unit not in normalized:normalized.append(unit)
    if not normalized:return []
    try:
        result=execute(['systemctl','show','--no-pager','--property=Id','--property=LoadState','--property=ActiveState','--property=Description','--',*normalized],
                       capture_output=True,text=True,timeout=5)
        found={}
        for block in result.stdout.strip().split('\n\n'):
            fields=dict(line.split('=',1) for line in block.splitlines() if '=' in line)
            if fields.get('Id'):found[fields['Id']]=fields
        states={'active':'running','inactive':'stopped','failed':'failed','activating':'start_pending','deactivating':'stop_pending'}
        return [{'name':name,'display_name':found.get(name,{}).get('Description',name),
                 'status':states.get(found.get(name,{}).get('ActiveState'),'unavailable') if found.get(name,{}).get('LoadState')=='loaded' else 'unavailable'} for name in normalized]
    except (OSError,subprocess.SubprocessError):
        return [{'name':name,'status':'unavailable'} for name in normalized]


def discover_services(execute=subprocess.run):
    try:
        result=execute(['systemctl','list-unit-files','--type=service','--no-legend','--no-pager'],
                       capture_output=True,text=True,timeout=5)
        names=[line.split()[0] for line in result.stdout.splitlines() if line.split()]
        wanted=[name for name in names if name=='mssql-server.service' or name.lower().startswith(('srv1cv8','srv1c','ras1c'))][:100]
        return [{**entry,'kind':'SQL' if entry['name']=='mssql-server.service' else '1C'} for entry in systemd_services(wanted,execute)]
    except (OSError,subprocess.SubprocessError):
        return []
