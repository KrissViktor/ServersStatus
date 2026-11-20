"""Portal login audit and public handles for revocable sessions."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import time
from functools import lru_cache

SCHEMA = """
CREATE TABLE IF NOT EXISTS portal_login_audit (
    id INTEGER PRIMARY KEY, account TEXT NOT NULL, at REAL NOT NULL,
    accepted INTEGER NOT NULL, ip TEXT NOT NULL, country TEXT, browser TEXT NOT NULL,
    expires REAL, last_seen REAL, last_ip TEXT, last_country TEXT, ended REAL
);
CREATE INDEX IF NOT EXISTS portal_login_audit_time ON portal_login_audit(at);
CREATE INDEX IF NOT EXISTS portal_login_audit_ip ON portal_login_audit(ip,at);
CREATE INDEX IF NOT EXISTS portal_login_audit_result ON portal_login_audit(accepted,id);
CREATE TABLE IF NOT EXISTS portal_session_info (
    token TEXT PRIMARY KEY, public_id TEXT NOT NULL UNIQUE, login INTEGER,
    last_seen REAL
);
CREATE INDEX IF NOT EXISTS portal_session_info_login ON portal_session_info(login);
CREATE TABLE IF NOT EXISTS portal_password_resets (
    token TEXT PRIMARY KEY, account TEXT NOT NULL UNIQUE, expires REAL NOT NULL
);
"""

HEADERS = (
    'user-agent','accept-language','sec-ch-ua','sec-ch-ua-mobile','sec-ch-ua-platform',
    'sec-ch-ua-platform-version','sec-ch-ua-full-version-list','sec-ch-ua-arch',
    'sec-ch-ua-bitness','sec-ch-ua-model','sec-gpc','dnt',
)


def initialize(c):
    c.executescript(SCHEMA)
    c.execute("""INSERT OR IGNORE INTO portal_session_info(token,public_id)
                 SELECT s.token,lower(hex(randomblob(8))) FROM sessions s
                 JOIN session_users u ON u.token=s.token
                 WHERE NOT EXISTS (SELECT 1 FROM portal_session_info i WHERE i.token=s.token)""")


@lru_cache(maxsize=2)
def country_networks(path, modified):
    networks = {4:{},6:{}}
    with Path(path).open(encoding='utf-8') as source:
        for line in source:
            network, separator, code = line.strip().partition(',')
            if separator and len(code)==2 and code.isascii() and code.isalpha():
                try:
                    parsed = ipaddress.ip_network(network)
                except ValueError:
                    continue
                shift = parsed.max_prefixlen-parsed.prefixlen
                networks[parsed.version].setdefault(shift,{})[int(parsed.network_address)>>shift] = code.upper()
    return {version:sorted(entries.items()) for version,entries in networks.items()}


def country_for(address):
    path = os.environ.get('STATUS_IP_COUNTRY_CSV')
    if not path:
        return None
    try:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            return None
        entries = country_networks(path,Path(path).stat().st_mtime_ns)[ip.version]
        address_number = int(ip)
        return next((ranges[address_number>>shift] for shift,ranges in entries if address_number>>shift in ranges),None)
    except (OSError, ValueError):
        return None


def browser_info(request):
    info = {name:request.headers[name][:512] for name in HEADERS if name in request.headers}
    info['session-cookie-present'] = 'да' if 'session' in request.cookies else 'нет'
    return info


def audit_login(c, account, now, accepted, ip, country, browser, token=None, expires=None):
    cursor = c.execute("""INSERT INTO portal_login_audit
        (account,at,accepted,ip,country,browser,expires,last_seen,last_ip,last_country) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (account[:64],now,int(accepted),ip,country,json.dumps(browser,ensure_ascii=False),
         expires,now if token else None,ip if token else None,country if token else None))
    if token:
        c.execute('INSERT INTO portal_session_info VALUES (?,?,?,?)',(token,secrets.token_hex(8),cursor.lastrowid,now))


def audit_blocked(c, account, now, ip, browser):
    # Repeated requests from a blocked address must not flood the audit database.
    if not c.execute('SELECT 1 FROM portal_login_audit WHERE ip=? AND at>? AND accepted=2 LIMIT 1',(ip,now-60)).fetchone():
        previous = c.execute('SELECT country FROM portal_login_audit WHERE ip=? ORDER BY at DESC LIMIT 1',(ip,)).fetchone()
        audit_login(c,account,now,2,ip,previous[0] if previous else None,browser)


def current(c, now, account=None, limit=100):
    return c.execute("""
        SELECT u.name,i.public_id,a.at,a.ip,a.country,a.browser,i.last_seen,s.expires,a.last_ip,a.last_country
        FROM sessions s JOIN session_users u ON u.token=s.token JOIN users p ON p.name=u.name
        LEFT JOIN portal_session_info i ON i.token=s.token
        LEFT JOIN portal_login_audit a ON a.id=i.login
        LEFT JOIN user_roles r ON r.name=u.name
        WHERE s.expires>? AND COALESCE(r.enabled,1)=1 AND (? IS NULL OR u.name=?)
        ORDER BY COALESCE(i.last_seen,0) DESC,s.expires DESC LIMIT ?
    """,(now,account,account,limit)).fetchall()


def history(c, now, failed, before):
    return c.execute("""
        SELECT a.id,a.account AS name,a.at,a.ip,a.country,a.browser,a.accepted,
               a.expires,a.last_seen,a.last_ip,a.last_country,COALESCE(a.ended,a.expires) AS ended
        FROM portal_login_audit a
        WHERE a.id<? AND (
            (? AND a.accepted<>1)
            OR (NOT ? AND a.accepted=1 AND NOT EXISTS (
                SELECT 1 FROM portal_session_info i JOIN sessions s ON s.token=i.token
                WHERE i.login=a.id AND s.expires>?
            ))
        )
        ORDER BY a.id DESC LIMIT 51
    """,(before,failed,failed,now)).fetchall()


def end(c, token):
    now = time.time()
    c.execute("""UPDATE portal_login_audit SET ended=? WHERE id=(
        SELECT login FROM portal_session_info WHERE token=?
    ) AND EXISTS (SELECT 1 FROM sessions WHERE token=? AND expires>?)""",(now,token,token,now))
    for table in ('console_grants','console_grant_tokens','console_challenges'):
        c.execute('DELETE FROM '+table+' WHERE session=?',(token,))
    c.execute('DELETE FROM portal_session_info WHERE token=?',(token,))
    c.execute('DELETE FROM session_users WHERE token=?',(token,))
    return c.execute('DELETE FROM sessions WHERE token=?',(token,)).rowcount


def reset_digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def touch(db, token, now, address):
    key = reset_digest(token)
    with db() as c:
        row = c.execute("""SELECT i.last_seen,i.login,a.last_ip,a.last_country FROM portal_session_info i
                       LEFT JOIN portal_login_audit a ON a.id=i.login WHERE i.token=?""",(key,)).fetchone()
        if row and (row['last_seen'] is None or row['last_seen']<=now-60):
            country = row['last_country'] if address==row['last_ip'] else country_for(address)
            if c.execute('UPDATE portal_session_info SET last_seen=? WHERE token=? AND (last_seen IS NULL OR last_seen<=?)',
                         (now,key,now-60)).rowcount:
                c.execute("""UPDATE portal_login_audit SET last_seen=?,last_ip=?,last_country=?
                    WHERE id=? AND ended IS NULL""",(now,address,country,row['login']))


def cleanup(c, now, cutoff):
    c.execute('DELETE FROM portal_login_audit WHERE at<?',(cutoff,))
    c.execute('DELETE FROM portal_session_info WHERE token NOT IN (SELECT token FROM sessions WHERE expires>?)',(now,))
    c.execute('DELETE FROM portal_password_resets WHERE expires<=?',(now,))
