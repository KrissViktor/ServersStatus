import time
from .dashboard import esc,page,duration
from .telegram_config import read,user_ids


def health_page(connection,now=None,csrf=None,saved=False):
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
    pending=connection.execute('SELECT COUNT(*) FROM bot_replies WHERE completed=0').fetchone()[0] if exists else 0
    content='<header class="topbar"><a class="brand" href="/">Статус серверов</a><a class="nav-link" href="/">← Обзор</a></header><div class="heading"><h1>Telegram-бот</h1></div><section class="server"><h2 class="text-'+color+'">'+status+'</h2>'
    content+='<p>Ожидающих ответов: '+str(pending)+'</p><details class="service-details"><summary>Время проверок и диагностика</summary>'
    for label,key in [('Состояние процесса','heartbeat'),('Последний успешный опрос Telegram','last_poll'),('Последний ответ на команду','last_delivery')]:
        value=float(values.get(key,0))
        content+='<p>'+label+': '+(duration(max(0,now-value))+' назад' if value else 'ещё нет данных')+'</p>'

    if values.get('send_error'):content+='<p class="text-warning">Ошибка отправки ответа. Проверьте доступ бота к чату; код '+esc(values['send_error'])+'.</p>'
    content+='<p class="muted">Состояние на момент открытия страницы. В Telegram отправьте /start, чтобы показать кнопки. Запросы по кнопкам доступны круглосуточно.</p></details></section>'
    if csrf is not None:
        config=read()
        admins=user_ids(config.get('admins',''))
        allowed=user_ids(config.get('allowed',''))
        names=config.get('names',{})
        content+='<section class="server"><h2>Настройки Telegram</h2>'
        if saved:
            content+='<p class="notice" role="status">Настройки сохранены. Перезапустите службу serversstatus-bot.service.</p>'
        content+='<p>'+('Токен настроен' if config.get('token') else 'Токен не задан')+'</p>'
        content+='<form method="post" action="/bot/settings"><input type="hidden" name="csrf" value="'+esc(csrf)+'">'
        content+='<label>Новый токен бота<input type="password" name="token" autocomplete="new-password" maxlength="128"></label>'
        content+='<p class="muted">Оставьте токен пустым, чтобы сохранить текущий.</p>'
        for key,label in [('chat','ID чата уведомлений'),('admins','Telegram ID администраторов'),('allowed','Telegram ID пользователей отчётов')]:
            content+='<label>'+label+'<input name="'+key+'" value="'+esc(config.get(key,''))+'" maxlength="2000"></label>'
        content+='<p class="muted">ID разделяются запятыми. Пустой список пользователей отчётов разрешает команды всем участникам настроенного чата.</p>'
        content+='<label>Имена пользователей по ID<textarea name="names" rows="4" placeholder="123456789 = Alex">'+esc('\n'.join(key+' = '+value for key,value in names.items()))+'</textarea></label><button>Сохранить</button></form>'
        content+='<h3>Доступ пользователей Telegram</h3><ul>'
        for identifier in sorted(admins|allowed):
            roles=[role for members,role in [(admins,'Администратор портала'),(allowed,'Пользователь отчётов')] if identifier in members]
            content+='<li><b>'+esc(names.get(identifier,identifier))+'</b> · '+esc(identifier)+' · '+' / '.join('<span>'+role+'</span>' for role in roles)+'</li>'
        content+='</ul></section>'
    return page(content)
