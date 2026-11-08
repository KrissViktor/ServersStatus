"""Single entry point for portal administration."""
from .dashboard import page, esc


def administration_page():
    sections = [
        ('/agents', 'Управление агентами', 'Добавление серверов, ключи доступа и снятие защиты для работы с консолью.'),
        ('/updates', 'Обновления агентов', 'Версии Windows и Linux, установка обновлений и история выполнения.'),
        ('/host', 'Raspberry Pi', 'Состояние сервера, на котором работает панель мониторинга.'),
        ('/bot', 'Telegram-бот', 'Состояние бота, уведомления и отчёты.'),
        ('/events', 'Журнал событий', 'Проблемы серверов, изменения состояния и события портала.'),
    ]
    content = '<header class="topbar"><a class="brand" href="/">Статус серверов</a><a class="nav-link" href="/">← Все серверы</a></header><div class="heading"><div><h1>Администрирование</h1><p class="muted">Настройки и обслуживание портала</p></div></div><nav class="admin-grid" aria-label="Разделы администрирования">'
    for url, title, description in sections:
        content += f'<a class="admin-card" href="{esc(url)}"><h2>{esc(title)} <span aria-hidden="true">→</span></h2><p>{esc(description)}</p></a>'
    return page(content + '</nav>')
