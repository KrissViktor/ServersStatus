from .dashboard import esc, page, duration
import time
from pathlib import Path

SCRIPT=Path(__file__).with_name("agents.js").read_text(encoding="utf-8")
from urllib.parse import quote


def agents_page(rows, csrf, message='', key=None, agent_id=None):
    hidden = f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
    content = '<header class="topbar"><a class="brand" href="/">S<span>●</span> <b>ServersStatus</b></a><a class="nav-link" href="/">← Обзор серверов</a></header><div class="heading"><div><p class="eyebrow">ПОДКЛЮЧЕНИЯ</p><h1>Управление агентами</h1><p class="muted">Регистрация компьютеров и управление доступом</p></div></div>'
    if message:
        content += f'<p class="notice">{esc(message)}</p>'
    if key:
        content += f'<section class="server key-result"><h2>Ключ для {esc(agent_id)}</h2><p>Сохраните ключ сейчас — повторно он не отображается. Введите его в установщике Windows вместе с именем агента.</p><label>Имя агента<input readonly value="{esc(agent_id)}"></label><label>Индивидуальный ключ<input readonly value="{esc(key)}" autocomplete="off" spellcheck="false" aria-label="Новый ключ агента"></label><p class="muted">Не отправляйте ключ в чат. После перевыпуска обновите ключ в конфигурации Windows-агента и перезапустите службу.</p><a class="nav-link" href="/agents">Ключ сохранён — закрыть</a></section>'
    content += '<details class="server agent-create-fold"><summary>Добавить компьютер</summary><div class="agent-create-body"><p class="muted">Имя — постоянный идентификатор. Латинские буквы, цифры, дефис и подчёркивание; до 64 символов.</p><form class="agent-create" method="post" action="/agents/create">' + hidden + '<label>Имя агента<input name="agent_id" required pattern="[A-Za-z0-9_-]{1,64}" maxlength="64" placeholder="windows-02" autocomplete="off"></label><button>Создать и получить ключ</button></form></div></details>'
    content+='<p class="muted agent-flags-help">Важный — уведомления о проблемах. Активный — в основном списке. Флажки сохраняются сразу.</p><div class="agent-grid">'
    for row in rows:
        item=dict(row);identifier=quote(row['id'],safe='');title=item.get('display_name') or item.get('hostname') or row['id']
        age = duration(time.time() - row['received']) + ' назад' if row['received'] is not None else 'Отчётов пока нет'
        content+=f'<article class="server agent-card" data-agent-id="{esc(row["id"])}"><button type="button" class="agent-disclosure" aria-expanded="false" aria-controls="agent-settings-{esc(row["id"])}"><span><strong>{esc(title)}</strong><span class="muted">ID агента: {esc(row["id"])}</span></span><span class="agent-chevron" aria-hidden="true">⌄</span></button><div class="agent-flags">'
        for flag,label in [('important','Важный'),('active','Активный')]:
            content+=f'<form class="agent-flag-form" method="post" action="/agents/flags">{hidden}<input type="hidden" name="agent_id" value="{esc(row["id"])}"><input type="hidden" name="flag" value="{flag}"><label class="check"><input type="checkbox" name="enabled" value="1" '+('checked' if item.get(flag,1) else '')+f'> {label}</label><noscript><button>Сохранить</button></noscript></form>'
        content+=f'</div><p class="agent-flag-status muted" role="status" aria-live="polite"></p><div class="agent-settings-body" id="agent-settings-{esc(row["id"])}" hidden><p class="muted">Последний отчёт: {age}</p><p><a class="nav-link" href="/settings/{esc(identifier)}">Настройки бэкапов и служб →</a></p><form method="post" action="/servers/{esc(identifier)}/name">{hidden}<input type="hidden" name="return_to" value="/agents"><label>Название в панели<input name="display_name" maxlength="120" value="{esc(item.get("display_name") or "")}" placeholder="{esc(item.get("hostname") or row["id"])}"></label><button>Сохранить название</button></form><details class="agent-key-settings"><summary>Перевыпуск ключа</summary><p class="muted">Старый ключ сразу перестанет работать. История отчётов сохранится.</p><form method="post" action="/agents/rotate">{hidden}<input type="hidden" name="agent_id" value="{esc(row["id"])}"><label class="check"><input type="checkbox" name="confirm" value="yes" required> Подтверждаю отключение старого ключа</label><button>Выдать новый ключ</button></form></details><details class="agent-delete-settings"><summary>Удаление агента</summary><p class="muted">Удалятся регистрация и все отчёты. Служба на сервере останется, но её ключ будет отклоняться.</p><form method="post" action="/agents/delete">{hidden}<input type="hidden" name="agent_id" value="{esc(row["id"])}"><label>Для подтверждения введите имя агента<input name="confirmation" required autocomplete="off"></label><button class="delete-button">Удалить агента и историю</button></form></details></div></article>'
    content+='</div><noscript><style>.agent-settings-body[hidden]'+chr(123)+'display:block'+chr(125)+'</style></noscript><script>'+SCRIPT+'</script>'
    if not rows:
        content += '<div class="empty">Агенты ещё не зарегистрированы. Создайте первый выше.</div>'
    return page(content, protection_entry=True)
