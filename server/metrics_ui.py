from .dashboard import esc, size, cpu_description, memory_description, duration
from datetime import datetime, timezone, timedelta


def rate(value):
    return 'Недоступно' if value is None else size(value) + '/с'


def extended_sections(data,rdp_access=None):
    from .windows_ui import section as windows_section
    windows_html=windows_section(data)
    system = data.get('system')
    if not system:
        return '<section class="extended"><h3>Система и производительность</h3><p class="muted">Обновите агент для сведений об ОС, сети и дисковых операциях.</p></section>' + rdp_section(data,rdp_access) + windows_html
    facts = [
        ('Операционная система', system.get('distribution') or ' '.join(str(system.get(k) or '') for k in ('os', 'release', 'edition'))),
        ('Версия / сборка', system.get('version') or 'Недоступно'),
        ('Архитектура', system.get('architecture') or 'Недоступно'),
        ('Процессор', system.get('processor') or 'Недоступно'),
        ('Частота CPU', cpu_description(data)),
        ('RAM: занято / всего', memory_description(data)),
        ('Ядра / потоки', str(system.get('physical_cores') or '—') + ' / ' + str(system.get('logical_cores') or '—')),
        ('RAM: всего / доступно', size(system.get('memory_total_bytes')) + ' / ' + size(system.get('memory_available_bytes')))]
    content = '<section class="extended"><h3>Система</h3><dl class="system-facts">' + ''.join('<div><dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd></div>' for label, value in facts) + '</dl></section><section class="extended"><h3>Сетевые интерфейсы</h3><div class="table-scroll"><table class="metric-table"><thead><tr><th>Интерфейс / IP</th><th>Состояние</th><th>Линк</th><th>Приём</th><th>Передача</th></tr></thead><tbody>'
    for nic in data.get('network', []):
        content += '<tr><td><b>' + esc(nic['name']) + '</b><p class="muted">' + esc(', '.join(nic.get('addresses', [])) or 'Нет IP') + '</p></td><td>' + ('Работает' if nic['is_up'] else 'Отключён') + '</td><td>' + (str(nic['speed_mbps']) + ' Мбит/с' if nic.get('speed_mbps') else '—') + '</td><td>' + rate(nic.get('receive_bytes_per_second')) + '</td><td>' + rate(nic.get('send_bytes_per_second')) + '</td></tr>'
    content += '</tbody></table></div>'
    if not data.get('network'):
        content += '<p class="muted">Сведения об интерфейсах недоступны.</p>'
    content += '</section><section class="extended"><h3>Дисковые операции</h3><div class="table-scroll"><table class="metric-table"><thead><tr><th>Устройство</th><th>Чтение</th><th>Запись</th><th>Чтение IOPS</th><th>Запись IOPS</th></tr></thead><tbody>'
    for disk in data.get('disk_io', []):
        content += '<tr><td>' + esc(disk['name']) + '</td><td>' + rate(disk.get('read_bytes_per_second')) + '</td><td>' + rate(disk.get('write_bytes_per_second')) + '</td><td>' + ('—' if disk.get('read_iops') is None else f'{disk["read_iops"]:.1f}') + '</td><td>' + ('—' if disk.get('write_iops') is None else f'{disk["write_iops"]:.1f}') + '</td></tr>'
    content += '</tbody></table></div>'
    if not data.get('disk_io'):
        content += '<p class="muted">Счётчики дисковых операций недоступны в ОС.</p>'
    content += '<p class="muted legend">IOPS — операций в секунду. Скорости измерены за ' + esc(f'{data.get("sample_seconds") or 0:.1f}') + ' с перед отправкой отчёта, а не за весь интервал между отчётами. Устройства указаны по именам ОС; соответствие буквам дисков не определялось.</p></section>'
    return content + rdp_section(data,rdp_access) + windows_html


def rdp_section(data,rdp_access=None):
    if (data.get('system') or {}).get('os') == 'Linux':
        return ''
    rdp = data.get('rdp')
    content = '<section class="extended"><h3>Пользователи RDP</h3>'
    if not rdp:
        content += '<p class="muted">Обновите Windows-агент для списка RDP-пользователей.</p>'
    elif rdp.get('status') != 'available':
        content += '<p class="muted">Список RDP недоступен: платформа или права службы не позволяют прочитать сессии.</p>'
    elif not rdp.get('sessions'):
        content += '<p class="muted">Пользователей RDP нет.</p>'
    else:
        if rdp.get('partial'):content += '<p class="notice">Часть сеансов недоступна для чтения.</p>'
        active = [s for s in rdp['sessions'] if s.get('state') == 'active']
        unique = {(s.get('domain', ''), s.get('username', '')) for s in active}
        content += f'<p class="muted">Подключённых пользователей: {len(unique)} · Активных сессий: {len(active)}</p>'
        content += '<div class="table-scroll"><table class="metric-table"><tr><th>Пользователь</th><th>Сессия</th>'+('<th>Действия</th>' if rdp_access else '')+'<th>Состояние</th><th>Вход (МСК)</th><th>Длительность</th><th>Простой</th><th>Компьютер клиента</th><th>IP клиента</th></tr>'
        for session in rdp['sessions']:
            user = (str(session.get('domain'))+'\\' if session.get('domain') else '') + str(session.get('username', ''))
            state = {'active':'🟢 Подключён','disconnected':'🔴 Отключён (сессия сохранена)'}.get(session.get('state'), 'Другое')
            try:
                logon=datetime.fromtimestamp(session['logon_at'],timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M:%S') if session.get('logon_at') is not None else '—'
            except (ValueError,OverflowError,OSError):logon='—'
            extra=[logon, duration(session['duration_seconds']) if session.get('duration_seconds') is not None else '—',duration(session['idle_seconds']) if session.get('idle_seconds') is not None else '—',session.get('client_name') or '—',session.get('client_address') or '—']
            content += '<tr><td>'+esc(user)+'</td><td>'+esc(session.get('session_id',''))+'</td>'
            if rdp_access:
                from .rdp_control import controls
                content+=controls(session,rdp_access,data)
            content+='<td>'+state+'</td>'+''.join('<td>'+esc(v)+'</td>' for v in extra)+'</tr>'
        content += '</table></div>'
    return content + '</section>'
