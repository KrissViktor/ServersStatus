"""Cached, read-only hardware summary using the Windows CIM providers."""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

# Explicit properties keep this a component summary, not a device enumeration.
QUERIES = {
    'computer': ('Win32_ComputerSystem', ['Manufacturer', 'Model', 'SystemType', 'TotalPhysicalMemory']),
    'board': ('Win32_BaseBoard', ['Manufacturer', 'Product', 'Version', 'SerialNumber']),
    'bios': ('Win32_BIOS', ['Manufacturer', 'SMBIOSBIOSVersion', 'ReleaseDate', 'SerialNumber']),
    'cpu': ('Win32_Processor', ['Name', 'Manufacturer', 'SocketDesignation', 'NumberOfCores', 'NumberOfLogicalProcessors', 'MaxClockSpeed']),
    'memory_array': ('Win32_PhysicalMemoryArray', ['MemoryDevices', 'MaxCapacityEx']),
    'memory': ('Win32_PhysicalMemory', ['DeviceLocator', 'BankLabel', 'Manufacturer', 'PartNumber', 'Capacity', 'ConfiguredClockSpeed', 'SMBIOSMemoryType', 'SerialNumber']),
    'gpu': ('Win32_VideoController', ['Name', 'VideoProcessor', 'DriverVersion', 'CurrentHorizontalResolution', 'CurrentVerticalResolution']),
    'storage': ('Win32_DiskDrive', ['Model', 'SerialNumber', 'FirmwareRevision', 'Size', 'InterfaceType', 'MediaType']),
    'network': ('Win32_NetworkAdapter', ['Name', 'Manufacturer', 'MACAddress', 'Speed']),
}
_lock = threading.Lock()
_next = 0
_busy = False
_cached = {'status': 'checking', 'items': [], 'checked_at': None, 'unavailable': [], 'truncated': False}


def probe():
    script = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);$ErrorActionPreference='Stop';$r=@{};"
    for kind, (cls, fields) in QUERIES.items():
        where = " -Filter 'PhysicalAdapter=True'" if kind == 'network' else ''
        selected = ','.join("@{Name='ReleaseDate';Expression={if($_.ReleaseDate){$_.ReleaseDate.ToString('yyyy-MM-dd')}}}" if field == 'ReleaseDate' else field for field in fields)
        script += f"try{{$r['{kind}']=@(Get-CimInstance -ClassName {cls}{where} | Select-Object -First 32 -Property {selected})}}catch{{$r['{kind}']=$null}};"
    script += '$r|ConvertTo-Json -Depth 5 -Compress'
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-Command', script],
                            capture_output=True, encoding='utf-8-sig', errors='replace', timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Hardware CIM query failed')
    return sanitize(json.loads(result.stdout))


def sanitize(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid hardware inventory')
    items = []; unavailable = []; truncated = False
    for kind, (_, properties) in QUERIES.items():
        rows = data.get(kind)
        if not isinstance(rows, list):
            unavailable.append(kind)
            continue
        if len(rows) >= 32:
            truncated = True
        for row in rows[:32]:
            if not isinstance(row, dict):
                continue
            fields = {}
            for key in properties:
                value = row.get(key)
                if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                    continue
                text = ' '.join(str(value).replace('\x00', '').split())[:160]
                if text and text.casefold() not in ('unknown', 'none', 'not specified', 'to be filled by o.e.m.', 'default string'):
                    fields[key] = text
            if not fields:
                continue
            item = {'kind': kind, 'fields': fields}
            # Leave room for metrics in the existing 64 KiB report envelope.
            if len(items) >= 48 or len(json.dumps(items + [item], ensure_ascii=True)) > 10000:
                truncated = True
                continue
            items.append(item)
    return {'status': 'available' if items else 'unavailable', 'items': items,
            'unavailable': unavailable, 'truncated': truncated, 'checked_at': time.time()}


def _refresh():
    global _cached, _busy
    try:
        data = probe()
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        data = {'status': 'unavailable', 'items': [], 'checked_at': time.time(),
                'unavailable': list(QUERIES), 'truncated': False}
    with _lock:
        _cached = data
        _busy = False


def inventory():
    global _next, _busy
    if os.name != 'nt':
        return None
    with _lock:
        if time.monotonic() >= _next and not _busy:
            _next = time.monotonic() + 3600
            _busy = True
            threading.Thread(target=_refresh, daemon=True).start()
        return dict(_cached)
