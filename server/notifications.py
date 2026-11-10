"""Telegram notification worker. Run independently of web traffic via systemd timer."""
import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from .dashboard import backup_problems


from .notification_types import DeliveryError


def proxy_request(token, method, payload, proxy):
    # Only the Telegram transport uses this client; never change global proxies.
    try:
        import httpx
        from urllib.parse import urlsplit
        parsed = urlsplit(proxy)
        if parsed.scheme not in ('socks5', 'socks5h', 'http', 'https') or not parsed.hostname:
            raise DeliveryError()
        with httpx.Client(proxy=proxy, timeout=15, trust_env=False, follow_redirects=False) as client:
            response = client.post('https://api.telegram.org/bot' + token + '/' + method, json=payload)
            result = response.json()
            if response.status_code == 429:
                raise DeliveryError(int(result.get('parameters', {}).get('retry_after', 60)), status=429)
            if response.status_code != 200 or not result.get('ok'):
                raise DeliveryError(status=response.status_code)
            return result['result']
    except ImportError:
        raise DeliveryError() from None
    except Exception as error:
        if isinstance(error, DeliveryError):
            raise error from None
        # httpx errors can include the bot URL or proxy credentials. Redact them.
        raise DeliveryError() from None


def telegram_request(token, method, payload):
    proxy = os.environ.get('STATUS_TELEGRAM_PROXY', '').strip()
    if proxy:
        return proxy_request(token, method, payload, proxy)
    request = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method,
                                     data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read(1024*1024 if method == 'getUpdates' else 65536))
        if not result.get('ok'):
            raise DeliveryError()
        return result['result']
    except urllib.error.HTTPError as error:
        retry = 60
        if error.code == 429:
            try:
                retry = int(json.loads(error.read(65536)).get('parameters', {}).get('retry_after', 60))
            except (ValueError, TypeError):
                pass
        raise DeliveryError(retry,status=error.code) from None
    except (OSError, ValueError, KeyError):
        # Never expose the URL: it contains the bot credential.
        raise DeliveryError() from None


def send_message(token, chat_id, text):
    telegram_request(token, 'sendMessage', {'chat_id': chat_id, 'text': text[:4000]})


from .incidents import incident_key, evaluate
from .delivery_policy import delivery_window


def tick(db, sender, now=None):
    real_clock = now is None
    now = time.time() if now is None else now
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS telegram_state (
            key TEXT PRIMARY KEY, agent TEXT, body TEXT, active INTEGER,
            sent INTEGER, next_attempt REAL DEFAULT 0)''')
        rows = c.execute('SELECT a.id, r.received, r.data FROM agents a LEFT JOIN current_reports r ON r.agent=a.id LEFT JOIN agent_flags f ON f.agent=a.id WHERE COALESCE(f.important,1)=1').fetchall()
        existing = c.execute('SELECT * FROM telegram_state').fetchall()
        incidents, valid, checked = evaluate(rows, existing, now, disk_threshold=98)
        c.execute('CREATE TABLE IF NOT EXISTS telegram_policy (name TEXT PRIMARY KEY, value TEXT)')
        if not c.execute("SELECT 1 FROM telegram_policy WHERE name='disk98'").fetchone():
            # Do not send recoveries for old 85%-threshold incidents on upgrade.
            for state in existing:
                if state['key'].startswith('disk:') and state['key'] not in incidents:
                    c.execute('DELETE FROM telegram_state WHERE key=?', (state['key'],))
            existing = [state for state in existing if not state['key'].startswith('disk:') or state['key'] in incidents]
            c.execute("INSERT INTO telegram_policy VALUES ('disk98','1')")
        for state in existing:
            if state['key'] not in valid:
                c.execute('DELETE FROM telegram_state WHERE key=?', (state['key'],))
            elif state['key'] in checked and state['key'] not in incidents:
                c.execute('UPDATE telegram_state SET active=0 WHERE key=?', (state['key'],))
        for key, (agent, text) in incidents.items():
            c.execute('''INSERT INTO telegram_state(key,agent,body,active,sent) VALUES (?,?,?,1,0)
                         ON CONFLICT(key) DO UPDATE SET body=excluded.body, active=1''', (key, agent, text))
        pending = c.execute('SELECT * FROM telegram_state WHERE active!=sent AND next_attempt<=? ORDER BY active DESC, key LIMIT 20', (now,)).fetchall()
    if not delivery_window(now):
        return 0, 0
    delivered, failed = 0, 0
    for state in pending:
        if real_clock and not delivery_window(time.time()):
            break
        with db() as c:
            enabled=c.execute('SELECT COALESCE(f.important,1) FROM agents a LEFT JOIN agent_flags f ON f.agent=a.id WHERE a.id=?',(state['agent'],)).fetchone()
            if not enabled or not enabled[0]:
                c.execute('DELETE FROM telegram_state WHERE agent=?',(state['agent'],))
                continue
        text = ('🔴 ServersStatus · ПРОБЛЕМА\n' if state['active'] else '🟢 ServersStatus · ВОССТАНОВЛЕНО\nПроблема больше не обнаружена:\n') + state['body']
        try:
            sender(text)
        except DeliveryError as error:
            failed += 1
            with db() as c:
                c.execute('UPDATE telegram_state SET next_attempt=? WHERE key=?', (now + error.retry_after, state['key']))
        else:
            delivered += 1
            with db() as c:
                c.execute('UPDATE telegram_state SET sent=?, next_attempt=0 WHERE key=?', (state['active'], state['key']))
    return delivered, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--daily-test', action='store_true')
    parser.add_argument('--discover-chat', action='store_true')
    args = parser.parse_args()
    token = os.environ.get('STATUS_TELEGRAM_TOKEN', '').strip()
    chat_id = os.environ.get('STATUS_TELEGRAM_CHAT_ID', '').strip()
    if not token:
        raise SystemExit('Не задан STATUS_TELEGRAM_TOKEN. Настройте файл окружения.')
    try:
        if args.discover_chat:
            updates = telegram_request(token, 'getUpdates', {'timeout': 0, 'limit': 100})
            chats = {str(u['message']['chat']['id']): u['message']['chat'].get('title') or u['message']['chat'].get('first_name', '') for u in updates if 'message' in u}
            for identifier, title in chats.items():
                print(identifier, title)
            if not chats:
                print('Чаты не найдены. Отправьте /start боту и повторите. Для проекта используйте отдельного бота без webhook.')
            return
        if not chat_id:
            raise SystemExit('Не задан STATUS_TELEGRAM_CHAT_ID.')
        if args.test:
            send_message(token, chat_id, 'ServersStatus: тестовое уведомление. Отправка работает.')
            print('Тестовое сообщение отправлено.')
            return
        from .app import db, DB
        if args.daily_test:
            from .daily import build_summary, MSK
            from datetime import datetime, timedelta
            end = datetime.now(MSK).replace(hour=0, minute=0, second=0, microsecond=0)
            with db() as c:
                chunks = build_summary(c, (end-timedelta(days=1)).timestamp(), end.timestamp(), time.time())
            for chunk in chunks:
                send_message(token, chat_id, 'Тестовая сводка\n' + chunk)
                time.sleep(1.1)
            print('Тестовая суточная сводка отправлена.')
            return
        import fcntl
        # Timer normally serializes execution; lock also protects manual runs.
        with open(DB + '.telegram.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            def sender(text):
                send_message(token, chat_id, text)
                time.sleep(1.1)
            from .events import process_events
            from .daily import deliver_daily
            process_events(db)
            delivered, failed = tick(db, sender)
            daily_sent, daily_failed = deliver_daily(db, sender)
            delivered += daily_sent
            failed += daily_failed
        from .portal_backup import note
        with db() as c:note(c,'notifications','warning' if failed else 'ok',f'Отправок: {delivered}; ошибок: {failed}')
        print(f'Отправлено: {delivered}; ошибок доставки: {failed}.')
        if failed:
            raise SystemExit(1)
    except DeliveryError:
        raise SystemExit('Telegram недоступен или отклонил запрос. Проверьте соединение, токен и доступ бота к чату. Значения настроек не выводятся.') from None


if __name__ == '__main__':
    main()
