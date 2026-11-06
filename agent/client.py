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
from agent.settings import load_cache, save_cache, effective_config


def collect(config, previous):
    disks = []
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({'path': partition.mountpoint, 'filesystem': partition.fstype, 'device': partition.device, 'free_bytes': usage.free, 'total_bytes': usage.total, 'used_percent': usage.percent})
        except OSError:
            continue
    backups = [inspect_backup(item, previous) for item in config.get('backups', [])]
    discovered = discover_services()
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
    before = counters()
    cpu = psutil.cpu_percent(interval=1)
    after = counters()
    extra = extended_metrics(before, after)
    return {**extra, 'features': ['auto_services_v1', 'rdp_v1'], 'auto_services_enabled': bool(config.get('auto_monitor_services', True)), 'manual_services': config.get('services', []), 'discovered_services': discovered, 'rdp': rdp_sessions(), 'hostname': socket.gethostname(), 'cpu_percent': cpu, 'memory_percent': psutil.virtual_memory().percent, 'uptime_seconds': max(0, time.time() - psutil.boot_time()), 'disks': disks, 'backups': backups, 'services': services}


def run(config_path, stop=None):
    config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    if not config['server_url'].startswith('https://'):
        raise ValueError('server_url должен использовать HTTPS')
    previous = {}
    cache_path = Path(str(config_path) + '.remote.json')
    cached = load_cache(cache_path)
    while stop is None or not stop.is_set():
        try:
            report = collect(effective_config(config, cached), previous)
            report['monitoring_revision'] = cached['revision']
            from urllib.parse import quote
            url = config['server_url'].rstrip('/') + '/api/report/' + quote(config['agent_id'], safe='')
            request = urllib.request.Request(url, data=json.dumps(report).encode(), headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError('Сервер отклонил отчёт')
                reply = json.loads(response.read(65537))
                if 'monitoring' in reply:
                    updated = reply['monitoring']
                    if updated != cached:
                        cached = save_cache(cache_path, updated)
                        previous.clear()
        except Exception:
            logging.error('Не удалось собрать или отправить отчёт; повтор в следующем цикле')
        interval = max(15, int(config.get('interval_seconds', 60)))
        if stop is not None:
            stop.wait(interval)
        else:
            time.sleep(interval)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    run(sys.argv[1])
