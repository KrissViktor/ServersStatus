"""Local administrator recovery from an accidental IP ban."""
import argparse
from .app import db

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['list', 'unblock'])
parser.add_argument('address', nargs='?')
args = parser.parse_args()
with db() as c:
    if args.action == 'list':
        for row in c.execute('SELECT address, failures, strikes, blocked_until FROM auth_guard'):
            print(dict(row))
    elif not args.address:
        parser.error('Для unblock укажите IP')
    else:
        c.execute('UPDATE auth_guard SET failures=0, blocked_until=? WHERE address=?', ('0', args.address))
        print('Блокировка снята. История повышений срока сохранена.')
