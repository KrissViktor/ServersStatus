from .dashboard import esc, page, duration
import time
from urllib.parse import quote


def agents_page(rows, csrf, message='', key=None, agent_id=None):
    hidden = f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
    content = '<header class="topbar"><a class="brand" href="/">S<span>●</span> <b>ServersStatus</b></a><a class="nav-link" href="/">← Обзор серверов</a></header><div class="heading"><div><p class="eyebrow">ПОДКЛЮЧЕНИЯ</p><h1>Управление агентами</h1><p class="muted">Регистрация компьютеров и управление доступом</p></div></div>'
    if message:
        content += f'<p class="notice">{esc(message)}</p>'
    if key:
        content += f'<section class="server key-result"><h2>Ключ для {esc(agent_id)}</h2><p>Сохраните ключ сейчас — повторно он не отображается. Введите его в установщике Windows вместе с именем агента.</p><label>Имя агента<input readonly value="{esc(agent_id)}"></label><label>Индивидуальный ключ<input readonly value="{esc(key)}" autocomplete="off" spellcheck="false" aria-label="Новый ключ агента"></label><p class="muted">Не отправляйте ключ в чат. После перевыпуска обновите ключ в конфигурации Windows-агента и перезапустите службу.</p><a class="nav-link" href="/agents">Ключ сохранён — закрыть</a></section>'
    content += '<section class="server"><h2>Добавить компьютер</h2><p class="muted">Имя — постоянный идентификатор. Латинские буквы, цифры, дефис и подчёркивание; до 64 символов.</p><form class="agent-create" method="post" action="/agents/create">' + hidden + '<label>Имя агента<input name="agent_id" required pattern="[A-Za-z0-9_-]{1,64}" maxlength="64" placeholder="windows-02" autocomplete="off"></label><button>Создать и получить ключ</button></form></section>'
    for row in rows:
        age = duration(time.time() - row['received']) + ' назад' if row['received'] is not None else 'Отчётов пока нет'
        content += f'<section class="server"><h2>{esc(row["id"])}</h2><p><a class="nav-link" href="/settings/{esc(quote(row["id"], safe=""))}">Настройки бэкапов и служб →</a></p><p class="muted">Последний отчёт: {age}</p><div class="secondary"><div><h3>Перевыпуск ключа</h3><p class="muted">Старый ключ сразу перестанет работать. История отчётов сохранится.</p><form method="post" action="/agents/rotate">{hidden}<input type="hidden" name="agent_id" value="{esc(row["id"])}"><label class="check"><input type="checkbox" name="confirm" value="yes" required> Подтверждаю отключение старого ключа</label><button>Выдать новый ключ</button></form></div><div><h3>Удаление агента</h3><p class="muted">Удалятся регистрация и все отчёты. Служба на Windows останется, но её ключ будет отклоняться.</p><form method="post" action="/agents/delete">{hidden}<input type="hidden" name="agent_id" value="{esc(row["id"])}"><label>Для подтверждения введите имя агента<input name="confirmation" required autocomplete="off"></label><button class="delete-button">Удалить агента и историю</button></form></div></div></section>'
    if not rows:
        content += '<div class="empty">Агенты ещё не зарегистрированы. Создайте первый выше.</div>'
    return page(content)
