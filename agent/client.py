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


def collect(config, previous):
    disks = []
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({'path': partition.mountpoint, 'free_bytes': usage.free, 'total_bytes': usage.total, 'used_percent': usage.percent})
        except OSError:
            continue
    backups = [inspect_backup(item, previous) for item in config.get('backups', [])]
    services = []
    if os.name == 'nt':
        for name in config.get('services', []):
            try:
                services.append({'name': name, 'status': psutil.win_service_get(name).status()})
            except (psutil.Error, OSError):
                services.append({'name': name, 'status': 'unavailable'})
    return {'hostname': socket.gethostname(), 'cpu_percent': psutil.cpu_percent(interval=1), 'memory_percent': psutil.virtual_memory().percent, 'uptime_seconds': max(0, time.time() - psutil.boot_time()), 'disks': disks, 'backups': backups, 'services': services}


def run(config_path, stop=None):
    config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    if not config['server_url'].startswith('https://'):
        raise ValueError('server_url должен использовать HTTPS')
    previous = {}
    while stop is None or not stop.is_set():
        try:
            report = collect(config, previous)
            from urllib.parse import quote
            url = config['server_url'].rstrip('/') + '/api/report/' + quote(config['agent_id'], safe='')
            request = urllib.request.Request(url, data=json.dumps(report).encode(), headers={'Authorization': 'Bearer ' + config['token'], 'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError('Сервер отклонил отчёт')
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
