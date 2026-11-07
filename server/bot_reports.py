from .disks import monitored_disks
"""Read-only reports for the authorized Telegram chat."""
import json
import os
from urllib.parse import urlsplit
from .dashboard import duration,size,number,cpu_description,memory_description,backup_problems
from .overview import issues
from .daily import build_summary
from .history import stamp

KEYBOARD={'keyboard':[['Статус','Отчет'],['RDP','Предупреждения'],['Панель','Помощь']],
          'resize_keyboard':True,'is_persistent':True}


def split_text(text,limit=3800):
    result=[];chunk=''
    for line in text.split('\n'):
        for offset in range(0,max(1,len(line)),limit):
            part=line[offset:offset+limit]
            if len(chunk)+len(part)+1>limit:
                result.append(chunk);chunk=''
            chunk+=('\n' if chunk else '')+part
    if chunk:result.append(chunk)
    return result or ['Нет данных.']


def rows(connection):
    return connection.execute('SELECT a.id,p.display_name,r.received,r.data FROM agents a LEFT JOIN agent_profiles p ON p.agent=a.id LEFT JOIN current_reports r ON r.agent=a.id ORDER BY a.id').fetchall()


def title(row,data):
    return row['display_name'] or data.get('hostname') or row['id']


def status_report(servers,now):
    lines=['🖥 Статус серверов · '+stamp(now)]
    for row in servers:
        data=json.loads(row['data'] or '{}')
        name=title(row,data)
        if row['received'] is None:
            lines.append('\n⚪ '+name+' — ещё нет отчётов');continue
        age=max(0,now-row['received'])
        lines.append('\n'+('🟢 ' if age<180 else '🔴 ')+name+' · '+('онлайн' if age<180 else 'нет связи'))
        lines.append('Последний отчёт: '+duration(age)+' назад')
        lines.append(f'CPU {number(data.get("cpu_percent")):.1f}% · '+cpu_description(data))
        lines.append(f'RAM {number(data.get("memory_percent")):.1f}% · '+memory_description(data))
        for disk in monitored_disks(data):
            lines.append(str(disk.get('path',''))+': '+f'{number(disk.get("used_percent")):.1f}% занято · '+size(disk.get('free_bytes'))+' свободно')
    if not servers:lines.append('Серверы ещё не зарегистрированы.')
    return split_text('\n'.join(lines))


def rdp_report(servers,now):
    lines=['👥 Подключения RDP · '+stamp(now)]
    count=0
    for row in servers:
        data=json.loads(row['data'] or '{}')
        if (data.get('system') or {}).get('os')=='Linux':
            continue
        count+=1;lines.append('\n'+title(row,data))
        if row['received'] is None:
            lines.append('Нет отчётов агента.');continue
        age=max(0,now-row['received'])
        if age>=180:lines.append('⚠ Устаревшие данные: '+duration(age)+' назад')
        rdp=data.get('rdp')
        if not rdp:
            lines.append('Обновите агент для списка RDP.');continue
        if rdp.get('status')!='available':
            lines.append('Список сессий недоступен (платформа/права).');continue
        sessions=rdp.get('sessions',[])
        active=[session for session in sessions if session.get('state')=='active']
        users={(s.get('domain',''),s.get('username','')) for s in active}
        lines.append(f'Подключено пользователей: {len(users)}; активных сессий: {len(active)}')
        if not sessions:lines.append('RDP-сессий нет.')
        for session in sessions:
            user=(str(session.get('domain'))+'\\' if session.get('domain') else '')+str(session.get('username',''))
            state={'active':'подключён','disconnected':'отключён, сессия сохранена'}.get(session.get('state'),'другое состояние')
            lines.append(user+' · ID '+str(session.get('session_id',''))+' · '+state)
    if not count:lines.append('Windows-серверов с данными RDP пока нет.')
    return split_text('\n'.join(lines))


def warning_report(servers,now):
    lines=['⚠ Предупреждения панели · '+stamp(now)]
    count=0
    for row in servers:
        data=json.loads(row['data'] or '{}')
        problems=issues(row,now)
        if not problems:continue
        count+=1;lines.append('\n'+title(row,data))
        lines.extend('• '+problem for problem in problems if not problem.startswith('Ошибка бэкапа:'))
        elapsed=max(0,now-row['received']) if row['received'] is not None else 0
        for backup in data.get('backups',[]):
            for problem in backup_problems(backup,elapsed):
                lines.append('• '+str(backup.get('name') or backup.get('path','Бэкап'))+': '+problem)
    if not count:lines.append('Проблем по полученным данным не обнаружено.')
    lines.append('\nРучной запрос показывает все предупреждения панели (диски от 85%). Автоматические сообщения о дисках — только от 98%.')
    return split_text('\n'.join(lines))


def command_name(text):
    first=text.strip().split(maxsplit=1)[0] if text.strip() else ''
    first=first.split('@',1)[0].casefold().replace('ё','е')
    return {'статус':'status','/status':'status','отчет':'report','/report':'report',
            'rdp':'rdp','/rdp':'rdp','предупреждения':'warnings','/warnings':'warnings',
            'панель':'panel','/panel':'panel','помощь':'help','/help':'help','/start':'help'}.get(first)


def render(connection,command,now):
    if command=='report':
        chunks=build_summary(connection,now-86400,now,now)
        chunks[0]='📊 Отчёт за последние 24 часа\n'+stamp(now-86400)+' — '+stamp(now)+'\n'+chunks[0].split('\n',1)[-1]
        return chunks
    if command=='panel':
        url=os.environ.get('STATUS_PANEL_URL','https://panel.vikserver.ru').strip()
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            return ['Адрес панели не настроен корректно.']
        return ['🌐 Панель статусов:\n'+url]
    if command=='help':
        return ['Выберите кнопку:\nСтатус — доступность, CPU, RAM и диски.\nОтчет — сводка за последние 24 часа прямо сейчас.\nRDP — пользователи и состояния RDP-сессий.\nПредупреждения — все текущие проблемы панели.\nПанель — ссылка на сайт.\n\nОтветы на кнопки доступны круглосуточно. Автоуведомления: будни 08–20, выходные 12–20 МСК. Команды только читают данные и не управляют серверами.']
    servers=rows(connection)
    return {'status':status_report,'rdp':rdp_report,'warnings':warning_report}[command](servers,now)
