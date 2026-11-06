from .dashboard import esc, size


def rate(value):
    return 'Недоступно' if value is None else size(value) + '/с'


def extended_sections(data):
    system = data.get('system')
    if not system:
        return '<section class="extended"><h3>Система и производительность</h3><p class="muted">Обновите Windows-агент для сведений об ОС, сети и дисковых операциях.</p></section>'
    facts = [
        ('Операционная система', ' '.join(str(system.get(k) or '') for k in ('os', 'release', 'edition'))),
        ('Версия / сборка', system.get('version') or 'Недоступно'),
        ('Архитектура', system.get('architecture') or 'Недоступно'),
        ('Процессор', system.get('processor') or 'Недоступно'),
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
        content += '<p class="muted">Счётчики дисковых операций недоступны в Windows.</p>'
    content += '<p class="muted legend">IOPS — операций в секунду. Скорости измерены за ' + esc(f'{data.get("sample_seconds") or 0:.1f}') + ' с перед отправкой отчёта, а не за весь интервал между отчётами. Устройства указаны по именам Windows; соответствие буквам дисков не определялось.</p></section>'
    return content
