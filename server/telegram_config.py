"""Server-side Telegram configuration shared by the portal and workers."""
import json
import os
from pathlib import Path
import tempfile


def path():
    return Path(os.environ.get('STATUS_TELEGRAM_SETTINGS_FILE','/var/lib/serversstatus/telegram-settings.json'))


def read():
    try:
        raw=json.loads(path().read_text(encoding='utf-8'))
        if not isinstance(raw,dict):
            raise ValueError('Invalid Telegram settings')
        return raw
    except FileNotFoundError:
        names = {'token':'TOKEN','chat':'CHAT_ID','admins':'PORTAL_ADMINS','allowed':'ALLOWED_USERS'}
        return {key:os.environ.get('STATUS_TELEGRAM_'+value,'').strip() for key,value in names.items()}


def write(config):
    destination=path()
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=destination.parent,delete=False) as stream:
            temporary=Path(stream.name)
            os.chmod(temporary,0o600)
            json.dump(config,stream,ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def user_ids(value):
    return {item.strip() for item in value.split(',') if item.strip()}
