import argparse
import getpass
import secrets
from .app import db, digest, password_hash

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['create-admin', 'add-agent'])
parser.add_argument('name')
args = parser.parse_args()
with db() as c:
    if args.action == 'create-admin':
        password = getpass.getpass('Пароль (минимум 12 символов): ')
        if len(password) < 12:
            raise SystemExit('Пароль слишком короткий')
        if password != getpass.getpass('Повторите пароль: '):
            raise SystemExit('Пароли не совпадают')
        salt = secrets.token_hex(16)
        c.execute('INSERT INTO users VALUES (?,?,?)', (args.name, salt, password_hash(password, salt)))
    else:
        token = secrets.token_urlsafe(32)
        c.execute('INSERT INTO agents VALUES (?,?)', (args.name, digest(token)))
        print('Сохраните ключ в конфигурации агента (повторно не отображается):', token)
