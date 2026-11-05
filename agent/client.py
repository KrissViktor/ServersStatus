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


def collect(config, previous):
    disks = []
    for partition in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({'path': partition.mountpoint, 'free_bytes': usage.free, 'total_bytes': usage.total, 'used_percent': usage.percent})
        except OSError:
            continue
    backups = []
    now = time.time()
    for item in config.get('backups', []):
        folder = item['path']
        try:
            files = [(p, p.stat()) for p in Path(folder).glob(item.get('pattern', '*.bak')) if p.is_file()]
            if not files:
                backups.append({'path': folder, 'state': 'missing'})
                continue
            path, stat = max(files, key=lambda pair: pair[1].st_mtime)
            key = str(path)
            signature = (stat.st_size, stat.st_mtime_ns)
            stable = previous.get(key) == signature
            previous[key] = signature
            state = 'observing' if not stable else ('stale' if now - stat.st_mtime > item.get('max_age_hours', 24) * 3600 else 'fresh')
            backups.append({'path': folder, 'file': path.name, 'size_bytes': stat.st_size, 'age_seconds': max(0, int(now - stat.st_mtime)), 'state': state})
        except OSError as error:
            backups.append({'path': folder, 'state': 'error', 'error': type(error).__name__})
    services = []
    if os.name == 'nt':
        for name in config.get('services', []):
            try:
                services.append({'name': name, 'status': psutil.win_service_get(name).status()})
            except (psutil.Error, OSError):
                services.append({'name': name, 'status': 'unavailable'})
    return {'hostname': socket.gethostname(), 'cpu_percent': psutil.cpu_percent(interval=1), 'memory_percent': psutil.virtual_memory().percent, 'uptime_seconds': max(0, time.time() - psutil.boot_time()), 'disks': disks, 'backups': backups, 'services': services}


def run(config_path, stop=None):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
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
