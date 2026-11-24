"""Privileged portal commands accepted only from explicitly allowed private chats."""
import json
import ipaddress
import re

from .access import ROLES, revoke
from .bot_reports import split_text
from .events import record
from .password_reset import issue
from .portal_sessions import current, end
from .windows_ui import stamp
from .telegram_config import blocked, read, user_ids, valid_user_id

COMMANDS = {
    'portal_users':'Учётные записи портала',
    'portal_sessions':'Текущие сеансы портала',
    'portal_kick':'Завершить все сеансы пользователя',
    'portal_end':'Завершить один сеанс портала',
    'portal_password':'Ссылка для смены пароля',
    'portal_blocks':'Блокировки входа',
    'portal_unblock':'Снять блокировку устройства или IP',
}


def admins():
    config = read()
    return {value for value in user_ids(config.get('admins','')) - blocked(config) if valid_user_id(value)}


def render(c, command, argument, actor, now):
    if command == 'portal_blocks':
        lines=['Блокировки входа. Снять блокировку: /portal_unblock ID или IP']
        for row in c.execute("SELECT address,blocked_until FROM auth_guard WHERE address NOT LIKE 'console:%' ORDER BY address"):
            remaining=int(row['blocked_until'])-int(now)
            if remaining>0:
                lines.append(f'{row["address"]} · {(remaining+59)//60} мин')
            if len(lines)==51:
                lines.append('Показаны первые 50 блокировок.')
                break
        return split_text('\n'.join(lines)) if len(lines)>1 else ['Активных блокировок входа нет.']

    if command == 'portal_unblock':
        identifier=argument.strip()
        if not re.fullmatch(r'device:[0-9a-f]{32}',identifier):
            try:
                identifier=str(ipaddress.ip_address(identifier))
            except ValueError:
                return ['Используйте /portal_unblock ID или IP из /portal_blocks.']
        changed=c.execute('DELETE FROM auth_guard WHERE address=?',(identifier,)).rowcount
        if changed:
            record(c,'','security',f'Telegram {actor} снял блокировку входа: {identifier}')
            return [f'Блокировка снята: {identifier}']
        return ['Для этого устройства или IP записи о блокировке нет.']

    if command == 'portal_users':
        rows = c.execute("""SELECT u.name,COALESCE(r.role,'viewer') AS role,COALESCE(r.enabled,1) AS enabled,
            (SELECT COUNT(*) FROM session_users i JOIN sessions s ON s.token=i.token
             WHERE i.name=u.name AND s.expires>?) AS sessions
            FROM users u LEFT JOIN user_roles r ON r.name=u.name ORDER BY u.name""",(now,))
        lines = ['Пользователи портала']
        for row in rows:
            lines.append(row['name']+' · '+ROLES[row['role']]+' · '+('сеансов: '+str(row['sessions']) if row['enabled'] else 'отключён'))
        return split_text('\n'.join(lines))

    if command == 'portal_sessions':
        rows = current(c,now,argument or None)
        lines = ['Текущие сеансы портала']
        for row in rows:
            browser = ' '.join(json.loads(row['browser'] or '{}').get('user-agent','').split())
            lines.append(
                f'{row["name"]} · {row["ip"] or "IP неизвестен"} · {row["country"] or "страна неизвестна"}\n'
                f'Вход: {stamp(row["at"])} · активность: {stamp(row["last_seen"])}\n'
                f'ID: {row["public_id"] or "—"}'
                + (f'\nПоследний IP: {row["last_ip"]} · {row["last_country"] or "страна неизвестна"}'
                   if row['last_ip'] and row['last_ip']!=row['ip'] else '')
                + ('\n'+browser[:200] if browser else '')
            )
        if not rows:
            lines.append('Активных сеансов нет.')
        elif len(rows)==100 and not argument:
            lines.append('Показано до 100 сеансов. Уточните логин: /portal_sessions логин.')
        return split_text('\n\n'.join(lines))

    if command == 'portal_end':
        if not re.fullmatch(r'[0-9a-f]{16}',argument):
            return ['Используйте /portal_end ID. ID указан в /portal_sessions.']
        row = c.execute("""SELECT i.token,u.name,COALESCE(a.last_ip,a.ip) AS ip,COALESCE(a.last_country,a.country) AS country,a.at FROM portal_session_info i
            JOIN sessions s ON s.token=i.token JOIN session_users u ON u.token=i.token
            LEFT JOIN portal_login_audit a ON a.id=i.login WHERE i.public_id=? AND s.expires>?""",(argument,now)).fetchone()
        if not row:
            return ['Активный сеанс не найден.']
        end(c,row['token'])
        record(c,'','users',f'Telegram {actor} завершил сеанс {argument} пользователя {row["name"]}')
        return [f'Сеанс {row["name"]} завершён. IP: {row["ip"] or "—"} · {row["country"] or "страна неизвестна"} · вход: {stamp(row["at"])}.']

    if not argument or len(argument)>64:
        return [f'Используйте /{command} логин.']
    account = c.execute("""SELECT u.name,COALESCE(r.enabled,1) AS enabled FROM users u
        LEFT JOIN user_roles r ON r.name=u.name WHERE u.name=?""",(argument,)).fetchone()
    if not account:
        return ['Пользователь не найден.']
    if command == 'portal_kick':
        rows = current(c,now,argument)
        revoke(c,argument)
        record(c,'','users',f'Telegram {actor} завершил все сеансы пользователя {argument}')
        details = [f'{row["last_ip"] or row["ip"] or "IP неизвестен"} · {row["last_country"] or row["country"] or "страна неизвестна"} · {stamp(row["at"])}' for row in rows]
        return split_text('Все сеансы завершены · '+argument+('\n'+'\n'.join(details) if details else ''))
    if not account['enabled']:
        return ['Учётная запись отключена.']
    link = issue(c,argument,now)
    if not link:
        return ['Для смены пароля настройте HTTPS-адрес STATUS_PANEL_URL.']
    record(c,'','users',f'Telegram {actor} выпустил ссылку для смены пароля пользователя {argument}')
    return ['Смена пароля · '+argument+'\nСсылка действует 10 минут и используется один раз. После смены пароля все сеансы пользователя завершатся.\n'+link]
