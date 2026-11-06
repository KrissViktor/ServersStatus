"""Observe file stability and daily/monthly backup dates without opening backups."""
from datetime import datetime, timedelta
import fnmatch
import os
from pathlib import Path
import re
import time

DATE = re.compile(r'_backup_(\d{4}_\d{2}_\d{2}_\d{6})_')


def inspect_backup(item, previous, now=None):
    now = time.time() if now is None else now
    folder = item['path']
    result = {'path': folder, 'name': item.get('name', folder), 'schedule': item.get('schedule', 'daily'), 'min_size_bytes': item.get('min_size_bytes', 1024**3)}
    try:
        # scandir raises on a missing/inaccessible root; do not call it "no files".
        with os.scandir(folder):
            pass
        pattern = item.get('pattern', '*.bak')
        recursive = item.get('recursive', False) or '**' in pattern
        candidates = []
        def fail(error):
            raise error
        for root, dirs, files in os.walk(folder, onerror=fail):
            if not recursive:
                dirs[:] = []
            for filename in files:
                path = Path(root) / filename
                if not (fnmatch.fnmatchcase(filename.lower(), pattern.lower()) or path.relative_to(folder).match(pattern)):
                    continue
                stat = path.stat()
                if not path.is_file():
                    continue
                if item.get('date_from_filename', False):
                    match = DATE.search(filename)
                    if not match:
                        continue
                    try:
                        created = datetime.strptime(match[1], '%Y_%m_%d_%H%M%S')
                    except ValueError:
                        continue
                    if result['schedule'] == 'monthly' and created.day != 1:
                        continue
                    timestamp = created.timestamp()
                else:
                    timestamp = stat.st_mtime
                candidates.append((timestamp, path, stat))
        if not candidates:
            return dict(result, state='missing')
        timestamp, path, stat = max(candidates, key=lambda entry: entry[0])
        key = (folder, str(path))
        signature = (stat.st_size, stat.st_mtime_ns)
        stable = previous.get(key) == signature
        previous[key] = signature
        if result['schedule'] == 'monthly':
            current = datetime.fromtimestamp(now)
            month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            deadline = month_start + timedelta(hours=item.get('grace_hours', 36))
            required = month_start if current >= deadline else (month_start - timedelta(days=1)).replace(day=1)
            fresh = datetime.fromtimestamp(timestamp) >= required
            result['expected_since'] = required.strftime('%Y-%m-%d')
        else:
            fresh = now - timestamp <= item.get('max_age_hours', 30) * 3600
        state = 'fresh' if fresh else 'stale'
        if timestamp > now + 300:
            state = 'future'
        elif stat.st_size == 0:
            state = 'empty'
        elif stat.st_size < result['min_size_bytes']:
            state = 'too_small'
        elif not fresh:
            state = 'stale'
        elif not stable:
            state = 'observing'
        return dict(result, state=state, file=path.name, relative_path=str(path.relative_to(folder)),
                    size_bytes=stat.st_size, age_seconds=max(0, int(now-timestamp)),
                    backup_date=datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S'))
    except (OSError, ValueError, OverflowError) as error:
        return dict(result, state='error', error=type(error).__name__)
