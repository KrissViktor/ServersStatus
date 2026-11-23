import time
from .dashboard import esc,page,duration
from .telegram_config import blocked,read,user_ids
from .ui_icons import icon


ERRORS = {
    'format':'Проверьте формат токена и ID чата.',
    'confirm':'Подтвердите замену токена перед сохранением.',
    'user':'Укажите числовой Telegram ID и имя длиной до 80 символов.',
    'limit':'Достигнут предел списка пользователей Telegram.',
    'duplicate':'Этот Telegram ID уже есть в списке. Измените существующую запись.',
    'missing':'Сначала настройте токен и чат уведомлений.',
    'write':'Не удалось сохранить настройки Telegram.',
}


def indicator_state(db):
    try:
        config=read()
    except (OSError,ValueError):
        return False
    if not config.get('token') or not config.get('chat'):
        return None
    with db() as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='bot_state'").fetchone():
            return False
        values=dict(c.execute("SELECT name,value FROM bot_state WHERE name IN ('heartbeat','last_poll','poll_error','send_error')"))
    now=time.time()
    return (all(0<=now-float(values.get(key,0))<=180 for key in ('heartbeat','last_poll'))
            and not (values.get('poll_error') or values.get('send_error')))


def indicator_markup(db):
    active=indicator_state(db)
    if active is None:
        return ''
    color='normal' if active else 'danger'
    label='Telegram-бот работает' if active else 'Telegram-бот не работает'
    return f'<span class="telegram-indicator {color}" data-telegram-indicator role="img" aria-label="{label}" title="{label}">'+icon('telegram')+'</span>'


def restart_status(values, now):
    marker=values.get('restart_request')
    if not marker:
        return None
    requested=float(values.get('restart_requested_at',0))
    if marker==values.get('restart_applied'):
        if not requested or now-requested>300:
            return None
        if values.get('poll_error'):
            return 'warning','Бот перезапустился, но пока не подключился к Telegram.'
        if float(values.get('last_poll',0)):
            return 'normal','Бот перезапустился и подключился к Telegram.'
        return 'warning','Бот перезапустился. Ожидаем подключения к Telegram.'
    seen=marker==values.get('restart_seen')
    if requested and now-requested<60:
        if seen:
            return 'warning','Бот принял запрос. Ожидаем запуска нового процесса.'
        return 'warning','Запрос отправлен. Ожидаем ответа от бота.'
    if seen:
        return 'danger','Бот принял запрос, но новый процесс не подтвердил запуск. Проверьте журнал службы.'
    return 'danger','Бот не подтвердил перезапуск. Проверьте, что служба запущена и обновлена.'


def user_fields(identifier='', alias='', roles=()):
    fields = ''
    if identifier:
        fields += f'<input type="hidden" name="telegram_id" value="{esc(identifier)}">'
    else:
        fields += '<label>Telegram ID<input name="telegram_id" inputmode="numeric" pattern="[0-9]{1,19}" maxlength="19" required></label>'
    fields += f'<label>Имя в портале<input name="alias" value="{esc(alias)}" maxlength="80"></label>'
    fields += '<div class="bot-roles">'
    for key, label in [('allowed','Пользователь отчётов'),('admins','Администратор бота'),('blocked','Заблокирован')]:
        checked = ' checked' if key in roles else ''
        fields += f'<label class="check"><input type="checkbox" name="{key}" value="1"{checked}><span>{label}</span></label>'
    return fields+'</div>'


def health_page(connection,now=None,csrf=None,saved=False,error=''):
    now=time.time() if now is None else now
    exists=connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bot_state'").fetchone()
    values=dict(connection.execute('SELECT name,value FROM bot_state').fetchall()) if exists else {}
    heartbeat=float(values.get('heartbeat',0))
    poll=float(values.get('last_poll',0))
    if not heartbeat:
        status='Бот ещё не запущен';color='warning'
    elif now-heartbeat>180:
        status='Нет свежего состояния процесса бота';color='danger'
    elif values.get('poll_error'):
        status='Процесс работает, но соединение с Telegram недоступно';color='warning'
    elif values.get('send_error'):
        status='Процесс работает, но ответ в Telegram не доставлен';color='warning'
    elif not poll:
        status='Подключается к Telegram';color='warning'
    elif now-poll>180:
        status='Процесс работает, успешный опрос Telegram пока не подтверждён';color='warning'
    else:
        status='Бот работает';color='normal'
    pending=connection.execute('SELECT COUNT(*) FROM bot_replies WHERE completed=0').fetchone()[0] if connection.execute("SELECT 1 FROM sqlite_master WHERE name='bot_replies'").fetchone() else 0
    content='<header class="topbar"><a class="brand" href="/">Статус серверов</a><a class="nav-link" href="/">← Обзор</a></header><div class="heading monitor-heading"><h1>'+icon('telegram')+' Telegram-бот</h1></div><div class="bot-settings"><section class="server"><div class="server-head"><h2>Состояние бота</h2>'
    if csrf is not None:
        hidden=f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
        content+=f'<form method="post" action="/bot/restart">{hidden}<button>Перезапустить бота</button></form>'
    content+='</div>'
    if csrf is not None and saved and not error:
        content+='<p class="text-normal" role="status">Настройки сохранены.</p>'
    if csrf is not None and error in ERRORS:
        content+='<p class="notice" role="alert">'+ERRORS[error]+'</p>'
    content+='<div id="telegram-health" data-refresh data-refresh-interval="10000"><p class="text-'+color+'">'+status+'</p>'
    restart=restart_status(values,now) if csrf is not None else None
    if restart:
        tone,message=restart
        content+=f'<p class="text-{tone}" role="status">{message}</p>'
    content+='<p><span>Ожидающих ответов:</span> '+str(pending)+'</p><details class="service-details"><summary>Время проверок и диагностика</summary>'
    for label,key in [('Состояние процесса','heartbeat'),('Последний успешный опрос Telegram','last_poll'),('Последний ответ на команду','last_delivery')]:
        value=float(values.get(key,0))
        content+='<p><span>'+label+'</span> · '+(duration(max(0,now-value))+' назад' if value else 'ещё нет данных')+'</p>'

    if values.get('send_error'):content+='<p class="text-warning"><span>Ошибка отправки ответа. Проверьте доступ бота к чату.</span> <code>'+esc(values['send_error'])+'</code></p>'
    content+='<p class="muted">Состояние обновляется автоматически. В Telegram отправьте /start, чтобы показать кнопки. Запросы по кнопкам доступны круглосуточно.</p></details></div></section>'
    if csrf is not None:
        config=read()
        membership={'admins':user_ids(config.get('admins','')), 'allowed':user_ids(config.get('allowed','')),
                    'blocked':blocked(config)}
        aliases=config.get('names',{})
        has_users=connection.execute("SELECT 1 FROM sqlite_master WHERE name='bot_users'").fetchone()
        telegram_users={key:(name,handle) for key,name,handle in connection.execute(
            'SELECT id,first_name,username FROM bot_users')} if has_users else {}
        identifiers=set(telegram_users)|set(aliases)|user_ids(config.get('users',''))
        identifiers.update(*membership.values())
        content+='<section class="server"><h2>Доступ пользователей Telegram</h2>'
        content+='<p class="muted">Исходное имя появится после первого сообщения, которое бот получит от пользователя.</p>'
        if not membership['allowed']:
            content+='<p class="muted">Пока список пользователей отчётов пуст, команды доступны участникам чата уведомлений.</p>'
        content+='<p class="muted">Заблокированный пользователь не сможет пользоваться ботом или получать личные сообщения. Чтобы скрыть уведомления общего чата, удалите пользователя из этого чата в Telegram.</p>'
        content+=f'<form method="post" action="/bot/users" class="bot-user-form bot-user-add">{hidden}<input type="hidden" name="add" value="1">{user_fields()}<button>Добавить пользователя</button></form>'
        for identifier in sorted(identifiers,key=lambda key:(key not in membership['admins'],key not in membership['blocked'],key)):
            name,handle=telegram_users.get(identifier,('',''))
            roles={role for role in membership if identifier in membership[role]}
            original=' <span data-no-translate>'+esc(name)+'</span>' if name else ' <span>Имя пока неизвестно</span>'
            if handle:
                original+=' <code>@'+esc(handle)+'</code>'
            fields=user_fields(identifier,aliases.get(identifier,''),roles)
            content+=f'<article class="bot-user"><div class="bot-user-identity"><code>{esc(identifier)}</code>{original}</div>'
            content+=f'<form method="post" action="/bot/users" class="bot-user-form">{hidden}{fields}<button>Сохранить</button></form></article>'
        content+='</section><section class="server"><div class="server-head"><h2>Настройки Telegram</h2>'
        content+='<span class="badge neutral">'+('Токен настроен' if config.get('token') else 'Токен не задан')+'</span></div>'
        content+=f'<form method="post" action="/bot/settings" class="bot-connection">{hidden}'
        content+=f'<label>ID чата уведомлений<input name="chat" value="{esc(config.get("chat",""))}" maxlength="20" required></label>'
        content+='<label>Новый токен бота<input type="password" name="token" autocomplete="new-password" maxlength="128"></label>'
        content+='<p class="muted">Оставьте токен пустым, чтобы сохранить текущий.</p>'
        content+='<div class="bot-token-warning"><p>После замены токена старый бот перестанет обслуживать портал. Вы уверены?</p>'
        content+='<label class="check"><input type="checkbox" name="confirm_token" value="1"><span>Подтверждаю замену токена</span></label></div>'
        content+='<button>Сохранить настройки</button></form></section>'
    return page(content+'</div>',refresh=True)
