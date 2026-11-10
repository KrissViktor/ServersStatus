"""Shared incident evaluation for events and Telegram."""
from .disks import monitored_disks, is_linux
import hashlib
import json
from .dashboard import backup_problems, number

def incident_key(agent, path):
    return 'backup:' + hashlib.sha256((agent + '\0' + path).encode()).hexdigest()


def disk_key(agent,path):
    return 'disk:' + hashlib.sha256((agent+'\\0'+path).encode()).hexdigest()


def evaluate(rows, existing, now, disk_threshold=85):
    incidents, valid, checked = {}, set(), set()
    for row in rows:
        if row['received'] is None:
            continue  # Newly registered agents have not yet been connected.
        agent = row['id']
        report = json.loads(row['data'])
        name = report.get('hostname') or agent
        elapsed = max(0, now - row['received'])
        connection = 'connection:' + agent
        valid.add(connection)
        checked.add(connection)
        if elapsed >= 180:
            incidents[connection] = (agent, f'{name} ({agent}): нет связи более 3 минут.')
            # Do not claim recovery of backup problems using stale reports.
            valid.update(s['key'] for s in existing if s['agent'] == agent and not s['key'].startswith('connection:') and (not is_linux(report) or not s['key'].startswith('disk:') or s['key']==disk_key(agent,'/')))
            continue
        probes=report.get('application_checks') or {}
        if probes.get('enabled') and probes.get('checked_at') is not None and now-probes['checked_at']<180:
            for item in probes.get('items',[]):
                key='application:'+agent+':'+item['id'];valid.add(key)
                if item.get('status') not in ('ok','failed'):continue
                checked.add(key)
                if item['status']=='failed':incidents[key]=(agent,f'{name} ({agent}): не отвечает приложение '+item['name'])
        elif probes.get('enabled'):
            valid.update(s['key'] for s in existing if s['agent']==agent and s['key'].startswith('application:'))
        for backup in report.get('backups', []):
            key = incident_key(agent, backup.get('path', backup.get('name', '')))
            valid.add(key)
            problems = backup_problems(backup, elapsed)
            if backup.get('state') == 'observing' and not problems:
                continue  # Require a confirmed file before recovery.
            checked.add(key)
            if problems:
                label = backup.get('name') or backup.get('path', 'Бэкап')
                incidents[key] = (agent, f'{name} ({agent}) · {label}\n' + '\n'.join(problems))
        for service in report.get('services', []):
            service_name = service.get('name', '')
            key = 'service:' + hashlib.sha256((agent+'\\0'+service_name).encode()).hexdigest()
            valid.add(key)
            checked.add(key)
            if service.get('status') != 'running':
                incidents[key] = (agent, f'{name} ({agent}): служба {service_name} не работает ({service.get("status", "unavailable")}).')
        for disk in monitored_disks(report):
            path = str(disk.get('path', ''))
            key = disk_key(agent,path)
            valid.add(key)
            checked.add(key)
            if number(disk.get('used_percent', 0)) >= disk_threshold:
                incidents[key] = (agent, f'{name} ({agent}): диск {path} заполнен на {number(disk.get("used_percent")):.1f}%.')
    return incidents, valid, checked
