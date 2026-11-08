from pathlib import Path
from urllib.parse import quote
from .dashboard import esc
SCRIPT=Path(__file__).with_name('console.js').read_text()


def section(agent,csrf,data):
    info=data.get('console')
    if data.get('agent_platform')=='portal':return ''
    body='<section class="server" id="remote-console" data-url="/api/servers/'+esc(quote(agent,safe=''))+'/console" data-agent="'+esc(agent)+'"><h2>Мини-консоль</h2>'
    if not info:return body+'<p class="muted">Обновите агент для поддержки консоли.</p></section>'
    body+='<p>Оболочка: '+esc(info.get('shell'))+' · Пользователь службы: '+esc(info.get('identity'))+'</p><p class="muted">Одна команда за раз. Вывод появляется по мере выполнения после получения агентом задания. Рабочая папка — каталог конфигурации агента. Каждая команда запускается в новой оболочке; cd и переменные между запусками не сохраняются. Команды и вывод сохраняются в истории панели.</p>'
    if not info.get('streaming'):body+='<p class="muted">Обновите агент для живого вывода; текущая версия отправляет результат после завершения.</p>'
    if not info.get('enabled'):body+='<p class="notice">Консоль выключена на агенте. Включите allow_remote_console локально и перезапустите службу. См. deploy/CONSOLE.md.</p>'
    else:
        body+='<form id="console-form"><input type="hidden" name="csrf" value="'+esc(csrf)+'"><label>Команда<textarea name="command" rows="4" maxlength="4000" required spellcheck="false" placeholder="'+('Get-Service | Select-Object -First 10' if info.get('shell')=='powershell' else 'uptime; df -h /')+'"></textarea></label><label>Лимит времени<select name="timeout"><option value="15">15 секунд</option><option value="30" selected>30 секунд</option><option value="60">60 секунд</option></select></label><label class="check"><input type="checkbox" name="confirmation" required> Выполнить на '+esc(agent)+' с правами указанной службы</label><button type="submit">Выполнить</button><button type="button" id="console-review" hidden>Результат проверен локально — разрешить новую команду</button></form>'
    body+='<p id="console-message" role="status" aria-live="polite"></p><div id="console-history"></div></section><script>'+SCRIPT+'</script>'
    return body
