"""Receive monitoring settings only; retain cached rules while offline."""
import json
import math
from pathlib import Path


def validate_remote(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('revision'), int) or payload['revision'] < 0:
        raise ValueError('Invalid revision')
    settings = payload.get('settings')
    if settings is None:
        if payload['revision'] != 0:
            raise ValueError('Invalid local settings revision')
        return {'revision': 0, 'settings': None}
    if not isinstance(settings, dict) or not {'backups', 'services'} <= set(settings) or set(settings) - {'backups', 'services', 'auto_monitor_services'}:
        raise ValueError('Invalid settings keys')
    if 'auto_monitor_services' in settings and not isinstance(settings['auto_monitor_services'], bool):
        raise ValueError('Invalid service discovery flag')
    services, backups = settings['services'], settings['backups']
    if not isinstance(services, list) or len(services) > 100 or any(not isinstance(s, str) or not s.strip() or len(s) > 255 for s in services):
        raise ValueError('Invalid services')
    if not isinstance(backups, list) or len(backups) > 20:
        raise ValueError('Invalid backup rules')
    allowed = {'name', 'path', 'pattern', 'schedule', 'recursive', 'date_from_filename', 'max_age_hours', 'grace_hours', 'min_size_bytes'}
    for rule in backups:
        if not isinstance(rule, dict) or set(rule) - allowed:
            raise ValueError('Invalid rule keys')
        for key, limit in (('name', 120), ('path', 500), ('pattern', 200)):
            if not isinstance(rule.get(key), str) or not 1 <= len(rule[key]) <= limit:
                raise ValueError('Invalid rule text')
        if rule.get('schedule') not in ('daily', 'monthly'):
            raise ValueError('Invalid schedule')
        for key in ('recursive', 'date_from_filename'):
            if not isinstance(rule.get(key), bool):
                raise ValueError('Invalid rule flag')
        for key, lower, upper in (('max_age_hours', 1, 8760), ('grace_hours', 0, 672), ('min_size_bytes', 0, 1024**5)):
            value = rule.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError('Invalid rule threshold')
        if not isinstance(rule['min_size_bytes'], int):
            raise ValueError('Invalid size')
    return {'revision': payload['revision'], 'settings': settings}


def load_cache(path):
    try:
        return validate_remote(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return {'revision': 0, 'settings': None}


def save_cache(path, payload):
    validated = validate_remote(payload)
    temporary = Path(str(path) + '.new')
    temporary.write_text(json.dumps(validated, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)
    return validated


def effective_config(local, cached):
    return {**local, **(cached['settings'] or {})}
