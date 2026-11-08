"""Run with: python -m agent.client /absolute/path/config.json"""
import json
import logging
import os
from pathlib import Path
import socket
import sys
import time
import urllib.request

import psutil
from agent.backups import inspect_backup
from agent.metrics import counters, extended_metrics
from agent.windows_inventory import discover_services, rdp_sessions
from agent.linux_inventory import systemd_services, discover_services as discover_linux_services
from agent.settings import load_cache, save_cache, effective_config


def collect(config, previous):
    disks = []
    for partition in psutil.disk_partitions():
        if sys.platform.startswith('linux') and partition.mountpoint != '/':
            continue
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({'path': partition.mountpoint, 'filesystem': partition.fstype, 'device': partition.device, 'free_bytes': usage.free, 'total_bytes': usage.total, 'used_percent': usage.percent})
        except OSError:
            continue
        if sys.platform.startswith('linux'):
            break
    if not disks and sys.platform.startswith('linux'):
        usage = psutil.disk_usage('/')
        disks.append({'path':'/','free_bytes':usage.free,'total_bytes':usage.total,'used_percent':usage.percent})
    backups = [inspect_backup(item, previous) for item in config.get('backups', [])]
    discovered = discover_services() if os.name == 'nt' else discover_linux_services() if sys.platform.startswith('linux') else []
    services = list(discovered) if config.get('auto_monitor_services', True) else []
    names = {s['name'].casefold() for s in services}
    if os.name == 'nt':
        for name in config.get('services', []):
            if name.casefold() in names:
                continue
            try:
                services.append({'name': name, 'status': psutil.win_service_get(name).status()})
            except (psutil.Error, OSError):
                services.append({'name': name, 'status': 'unavailable'})
    elif sys.platform.startswith('linux'):
        services.extend(entry for entry in systemd_services(config.get('services', [])) if entry['name'].casefold() not in names)
    before = counters()
    cpu = psutil.cpu_percent(interval=1)
    after = counters()
    extra = extended_metrics(before, after)
    memory = extra['system']
    memory_percent = round(memory['memory_used_bytes']/memory['memory_total_bytes']*100,1) if memory['memory_total_bytes'] else 0
    from agent.version import version, agent_platform
    from agent.remote_update import enabled
    from agent.windows_management import inventory
    extra['windows_updates']=inventory(config)
    from agent.console import info as console_info
    extra['console']=console_info(config)
    return {'agent_version': version(), 'agent_platform': agent_platform(), **extra, 'features': (['remote_update_v1','github_update_v1'] if enabled() else []) + (['auto_services_v1', 'rdp_v1', 'rdp_details_v1', 'processes_v1', 'windows_management_v1','console_v1'] if os.name == 'nt' else ['auto_services_v1','systemd_v1','processes_v1','console_v1']), 'auto_services_enabled': bool(config.get('auto_monitor_services', True)), 'manual_services': config.get('services', []), 'discovered_services': discovered, 'rdp': rdp_sessions(), 'hostname': socket.gethostname(), 'cpu_percent': cpu, 'memory_percent': memory_percent, 'uptime_seconds': max(0, time.time() - psutil.boot_time()), 'disks': disks, 'backups': backups, 'services': services}


def run(config_path, stop=None):
    config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    if not config['server_url'].startswith('https://'):
        raise ValueError('server_url должен использовать HTTPS')
    interval = max(5, int(config.get('interval_seconds', 10)))
    previous = {}
    cache_path = Path(str(config_path) + '.remote.json')
    cached = load_cache(cache_path)
    while stop is None or not stop.is_set():
        cycle_started = time.monotonic()
        try:
            from agent.processes import begin, finish
            process_before = begin()
            report = collect(effective_config(config, cached), previous)
            process_snapshot = finish(process_before)
            report['monitoring_revision'] = cached['revision']
            from urllib.parse import quote
            url = config['server_url'].rstrip('/') + '/api/report/' + quote(config['agent_id'], safe='')
            request = urllib.request.Request(url, data=json.dumps(report,ensure_ascii=False).encode('utf-8'), headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError('Сервер отклонил отчёт')
                reply = json.loads(response.read(65537))
                if os.name == 'nt':
                    from agent.remote_update import enabled, request as update_request, endpoint, launch_windows
                    if enabled():
                        with update_request(config, endpoint(config)) as update_response:
                            job = json.loads(update_response.read(65536)).get('job')
                        if job:
                            launch_windows(config, config_path, job)
                requested_interval = reply.get('report_interval_seconds')
                if isinstance(requested_interval, int) and 5 <= requested_interval <= 3600:
                    interval = requested_interval
                if 'monitoring' in reply:
                    updated = reply['monitoring']
                    if updated != cached:
                        cached = save_cache(cache_path, updated)
                        previous.clear()
            if type(reply.get('report_id')) is int and isinstance(reply.get('report_received'),(int,float)):
                process_snapshot['report_id']=reply['report_id']
                process_snapshot['report_received']=reply['report_received']
            from agent.console import handle as handle_console
            handle_console(config,config_path)
            if os.name == 'nt':
                from agent.windows_management import handle
                handle(config,config_path)
            # Failure of optional process upload must not discard monitoring settings.
            try:
                process_url = config['server_url'].rstrip('/') + '/api/processes/' + quote(config['agent_id'], safe='')
                process_request = urllib.request.Request(process_url, data=json.dumps(process_snapshot,ensure_ascii=False).encode('utf-8'), headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(process_request, timeout=15) as response:
                    response.read(4096)
            except Exception:
                logging.warning('Не удалось отправить список процессов; повтор в следующем цикле')
        except Exception:
            logging.error('Не удалось собрать или отправить отчёт; повтор в следующем цикле')
        delay = max(0.5, interval-(time.monotonic()-cycle_started))
        if stop is not None:
            stop.wait(delay)
        else:
            time.sleep(delay)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run(sys.argv[1])
