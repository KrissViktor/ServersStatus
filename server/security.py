"""IP attribution, bounded request throttles and persistent login penalties."""
from collections import OrderedDict
import ipaddress
import math
import threading
import time


def client_address(request):
    peer = request.client.host if request.client else 'unknown'
    try:
        loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        loopback = False
    # Uvicorn is bound to loopback. Only the local Caddy may supply client IP.
    if loopback:
        for header in ('x-forwarded-for', 'x-status-client-ip'):
            value = request.headers.get(header, '').strip()
            try:
                return str(ipaddress.ip_address(value))
            except ValueError:
                continue
    return peer


class RequestLimiter:
    def __init__(self, capacity=60, refill=5, max_clients=10000, global_capacity=120, global_refill=30):
        self.capacity, self.refill, self.max_clients = capacity, refill, max_clients
        self.clients = OrderedDict()
        self.global_capacity, self.global_refill = global_capacity, global_refill
        self.global_tokens, self.global_time = global_capacity, time.monotonic()
        self.lock = threading.Lock()

    def reset(self):
        with self.lock:
            self.clients.clear()
            self.global_tokens, self.global_time = self.global_capacity, time.monotonic()

    def allow(self, address, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            previous = self.clients.pop(address, (self.capacity, now))
            tokens = min(self.capacity, previous[0] + max(0, now-previous[1])*self.refill)
            self.global_tokens = min(self.global_capacity, self.global_tokens + max(0, now-self.global_time)*self.global_refill)
            self.global_time = now
            wait = max((1-tokens)/self.refill, (1-self.global_tokens)/self.global_refill)
            permitted = tokens >= 1 and self.global_tokens >= 1
            if permitted:
                tokens -= 1
                self.global_tokens -= 1
            self.clients[address] = (tokens, now)
            while len(self.clients) > self.max_clients:
                self.clients.popitem(last=False)
            return permitted, max(1, math.ceil(wait))


limiter = RequestLimiter()
login_limiter = RequestLimiter(capacity=4, refill=1/30, global_capacity=10, global_refill=1)


def blocked_seconds(connection, address, now):
    row = connection.execute('SELECT blocked_until FROM auth_guard WHERE address=?', (address,)).fetchone()
    return max(0, int(row['blocked_until']) - int(now)) if row else 0


def failed_login(connection, address, now):
    row = connection.execute('SELECT failures, strikes FROM auth_guard WHERE address=?', (address,)).fetchone()
    failures, strikes = (row['failures'], row['strikes']) if row else (0, 0)
    failures += 1
    blocked_until = 0
    if failures >= 2:
        blocked_until = int(now) + 900 * 3**strikes
        strikes += 1
        failures = 0
    connection.execute('''INSERT INTO auth_guard VALUES (?,?,?,?)
        ON CONFLICT(address) DO UPDATE SET failures=excluded.failures,
        strikes=excluded.strikes, blocked_until=excluded.blocked_until''',
        (address, failures, strikes, str(blocked_until)))
    return max(0, blocked_until - int(now))


def account_blocked_seconds(connection,name,now):
    row=connection.execute('SELECT blocked_until FROM account_auth_guard WHERE name=?',(name,)).fetchone()
    return max(0,int(row['blocked_until'])-int(now)) if row else 0


def failed_account_login(connection,name,now):
    row=connection.execute('SELECT failures,strikes FROM account_auth_guard WHERE name=?',(name,)).fetchone()
    failures,strikes=(row['failures'],row['strikes']) if row else (0,0)
    failures+=1;until=0
    if failures>=2:until=int(now)+900*3**strikes;strikes+=1;failures=0
    connection.execute("INSERT INTO account_auth_guard VALUES (?,?,?,?) ON CONFLICT(name) DO UPDATE SET failures=excluded.failures,strikes=excluded.strikes,blocked_until=excluded.blocked_until",(name,failures,strikes,str(until)))
    return max(0,until-int(now))
