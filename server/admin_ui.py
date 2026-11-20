"""Single entry point for portal administration."""
from .dashboard import page, esc
from .ui_icons import icon
from .access import can_console,can_users


def appearance_settings():
    return (
        '<section class="server appearance-settings"><h2>Внешний вид</h2>'
        '<label class="theme-picker"><span>Тема сайта</span><select data-theme-choice>'
        '<option value="system">Системная</option><option value="light">Светлая</option>'
        '<option value="dark">Тёмная</option></select></label>'
        '<p class="muted">Тема сохраняется в этом браузере.</p></section>'
    )


def preferences_page():
    return page('<header class="topbar"><a class="brand" href="/">ServersStatus</a></header>'
                '<div class="heading"><h1>Настройки</h1></div>'+appearance_settings())


def administration_page():
    sections = [
        ('/problems','Отмеченные проблемы','Кто отметил «Всё окей», комментарии и возврат предупреждений.'),
        ('/groups','Группы серверов','Площадки, роли и состав групп.'),
        ('/agents', 'Управление агентами', 'Добавление серверов, ключи доступа и снятие защиты для работы с консолью.'),
        ('/updates', 'Обновления агентов', 'Версии Windows и Linux, установка обновлений и история выполнения.'),
        ('/portal-health','Контроль портала','База данных, свободное место, фоновые задачи и резервные копии.'),
        ('/host', 'Raspberry Pi', 'Состояние сервера, на котором работает панель мониторинга.'),
        ('/bot', 'Telegram-бот', 'Состояние бота, уведомления и отчёты.'),
        ('/ai','ИИ-помощник','Локальный чат на сервере Backup и личная история диалогов.'),
        ('/events', 'Журнал событий', 'Проблемы серверов, изменения состояния и события портала.'),
    ]
    if can_console():
        sections.append(('/portal-settings','Настройки хранения','Срок хранения истории; доступ только суперадминистратору.'))
        sections.append(('/report-rollups','Суточные сводки','Состояние фонового расчёта и ручной пересчёт по датам.'))
    if can_users():
        sections.append(('/users','Пользователи','Создание учётных записей, доступ и управление пользователями.'))
        sections.append(('/users/sessions','Сеансы портала','Текущие сеансы, архив и неудачные попытки входа.'))
    if not can_console():sections=[('/agents','Управление агентами','Добавление серверов и управление доступом агентов.') if entry[0]=='/agents' else entry for entry in sections]
    icons={'/problems':'incident','/groups':'layers','/agents':'server','/updates':'update','/portal-health':'heatmap','/host':'wallboard','/bot':'message','/ai':'sparkles','/events':'timeline','/portal-settings':'settings','/report-rollups':'chart','/users':'users'}
    categories=[('Мониторинг',{'/problems','/groups','/agents','/events','/ai'}),('Обслуживание',{'/updates','/portal-health','/host','/bot','/portal-settings','/report-rollups'}),('Доступ',{'/users'})]
    content='<header class="topbar"><a class="brand" href="/">Статус серверов</a><a class="nav-link" href="/">← Все серверы</a></header><div class="heading"><div><h1>Администрирование</h1><p class="muted">Настройки и обслуживание портала</p></div></div>'
    content+=appearance_settings()
    icons['/users/sessions']='users'
    categories[-1][1].add('/users/sessions')
    for heading,paths in categories:
        visible=[section for section in sections if section[0] in paths]
        if not visible:continue
        content+='<section class="admin-category"><h2>'+heading+'</h2><nav class="admin-grid" aria-label="'+heading+'">'
        for url,title,description in visible:content+='<a class="admin-card" href="'+esc(url)+'"><h3><span class="admin-card-icon">'+icon(icons[url])+'</span><span class="admin-card-title">'+esc(title)+'</span><span class="admin-card-arrow" aria-hidden="true">→</span></h3><p>'+esc(description)+'</p></a>'
        content+='</nav></section>'
    return page(content)
