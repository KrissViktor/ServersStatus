"""System inventory and rates sampled over the CPU measurement interval."""
import platform
import math
import socket
import time

import psutil


def sample_cpu(interval=1):
    # Prime per-CPU counters, then measure both views over the same one-second
    # interval. No second blocking sample is added to the reporting loop.
    ready=False
    try:
        psutil.cpu_percent(interval=None,percpu=True);ready=True
    except (OSError,RuntimeError,NotImplementedError,psutil.Error):pass
    total=psutil.cpu_percent(interval=interval)
    values=[]
    if ready:
        try:
            result=psutil.cpu_percent(interval=None,percpu=True)
            if isinstance(result,list):
                values=[float(v) if isinstance(v,(int,float)) and math.isfinite(v) and 0<=v<=100 else None for v in result[:1024]]
        except (OSError,RuntimeError,NotImplementedError,psutil.Error):pass
    return total,values


def counters():
    snapshot = {'time': time.monotonic(), 'network': {}, 'disk_io': {}}
    for key, method in (('network', lambda: psutil.net_io_counters(pernic=True)),
                        ('disk_io', lambda: psutil.disk_io_counters(perdisk=True))):
        try:
            snapshot[key] = method() or {}
        except (OSError, RuntimeError, psutil.Error):
            pass
    return snapshot


def rates(before, after, group, fields):
    elapsed = after['time'] - before['time']
    result = {}
    if elapsed <= 0:
        return result
    for name, current in after[group].items():
        old = before[group].get(name)
        if old is None:
            continue
        values = {}
        for source, target in fields.items():
            delta = getattr(current, source) - getattr(old, source)
            values[target] = delta / elapsed if delta >= 0 else None
        result[name] = values
    return result


def extended_metrics(before, after):
    memory = psutil.virtual_memory()
    system = {'os': platform.system(), 'release': platform.release(), 'version': platform.version(),
              'architecture': platform.machine(), 'processor': platform.processor(),
              'physical_cores': psutil.cpu_count(logical=False), 'logical_cores': psutil.cpu_count(),
              'memory_total_bytes': memory.total, 'memory_available_bytes': memory.available,
              'memory_used_bytes': max(0, memory.total-memory.available)}
    try:
        frequency = psutil.cpu_freq()
        system['cpu_current_mhz'] = frequency.current if frequency and frequency.current > 0 and math.isfinite(frequency.current) else None
        system['cpu_max_mhz'] = frequency.max if frequency and frequency.max > 0 and math.isfinite(frequency.max) else None
    except (OSError, NotImplementedError, AttributeError, psutil.Error):
        system['cpu_current_mhz'] = system['cpu_max_mhz'] = None
    if platform.system() == 'Linux':
        try:
            system['distribution'] = platform.freedesktop_os_release().get('PRETTY_NAME', 'Linux')
        except OSError:
            system['distribution'] = 'Linux'
    if platform.system() == 'Windows':
        system['edition'] = platform.win32_edition()
    network_rates = rates(before, after, 'network', {'bytes_recv': 'receive_bytes_per_second', 'bytes_sent': 'send_bytes_per_second'})
    network = []
    try:
        addresses, stats = psutil.net_if_addrs(), psutil.net_if_stats()
        for name, stat in list(stats.items())[:100]:
            ips = [a.address for a in addresses.get(name, []) if a.family in (socket.AF_INET, socket.AF_INET6)]
            item = {'name': name, 'is_up': stat.isup, 'speed_mbps': max(0, stat.speed), 'addresses': ips[:20]}
            item.update(network_rates.get(name, {}))
            network.append(item)
    except (OSError, psutil.Error):
        pass
    io = rates(before, after, 'disk_io', {'read_bytes': 'read_bytes_per_second', 'write_bytes': 'write_bytes_per_second', 'read_count': 'read_iops', 'write_count': 'write_iops'})
    return {'system': system, 'network': network,
            'disk_io': [{'name': name, **values} for name, values in list(io.items())[:100]],
            'sample_seconds': max(0, after['time'] - before['time'])}
