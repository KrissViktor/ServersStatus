import time
from .dashboard import esc,page,duration


def health_page(connection,now=None):
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
    return page(content)
