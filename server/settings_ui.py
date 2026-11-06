from urllib.parse import quote
from .dashboard import page, esc


def settings_page(agent_id, values, csrf, revision, applied, error='', saved=False):
    hidden = '<input type="hidden" name="csrf" value="' + esc(csrf) + '">'
    status = 'Используются локальные настройки агента' if not revision else 'Применено агентом' if applied == revision else 'Ожидает получения агентом'
    if revision == 0 and applied not in (None, 0):
        status = 'Ожидает возврата агента к локальному файлу'
    if applied is None:
        status += ' · Агент ещё не подтвердил поддержку настроек: обновите его EXE'
    content = '<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/agents">← Управление агентами</a></header><div class="heading"><div><p class="eyebrow">МОНИТОРИНГ</p><h1>' + esc(agent_id) + '</h1><p class="muted">' + esc(status) + '</p></div></div>'
    if not revision:
        content += '<p class="muted">Поля предварительно заполнены по последнему отчёту. Перед первым сохранением проверьте маски файлов, вложенные папки и чтение даты из имени.</p>'
    if error:
        content += '<p class="notice">' + esc(error) + '</p>'
    if saved:
        content += '<p class="notice">Настройки сохранены. Агент получит их при следующем отчёте и применит в следующем цикле. Обновите страницу через 1–2 минуты для проверки.</p>'
    url = '/settings/' + quote(agent_id, safe='')
    content += '<form method="post" action="' + esc(url) + '">' + hidden + '<section class="server"><h2>Службы Windows</h2><p class="muted">Системные имена служб, по одному на строку. Например MSSQLSERVER. Пустой список отключает контроль служб.</p><textarea name="services" rows="4" maxlength="26000">' + esc('\n'.join(values.get('services', []))) + '</textarea></section><section class="server"><h2>Правила бэкапов</h2><p class="muted">Пути на контролируемом компьютере. Пустой путь удаляет правило. Можно добавить до 20 правил. 1 Гб = 1024³ байт.</p><div id="backup-rules">'
    def rule_html(index, rule):
        def field(key, label, default='', kind='text', extra=''):
            value = rule.get(key, default)
            return f'<label>{label}<input type="{kind}" name="{key}_{index}" value="{esc(value)}" {extra}></label>'
        text = '<fieldset class="backup-rule"><legend>Правило бэкапа</legend><div class="rule-grid">'
        text += field('name', 'Название', extra='maxlength="120"') + field('path', 'Папка', extra='maxlength="500" placeholder="D:\\backup\\erp\\daily"') + field('pattern', 'Маска файла', '*.bak', extra='maxlength="200"')
        text += f'<label>Расписание<select name="schedule_{index}"><option value="daily">Ежедневно</option><option value="monthly" {"selected" if rule.get("schedule") == "monthly" else ""}>Каждое 1-е число</option></select></label>'
        text += field('max_age_hours', 'Максимальный возраст, часов (ежедневно)', 30, 'number', 'min="1" max="8760" step="0.1"')
        text += field('grace_hours', 'Ожидание от начала месяца, часов', 36, 'number', 'min="0" max="672" step="0.1"')
        text += field('min_size_gb', 'Минимальный размер, Гб', rule.get('min_size_bytes', 1024**3)/1024**3, 'number', 'min="0" max="1048576" step="any"') + '</div>'
        for key, label, default in [('recursive', 'Искать во вложенных папках', False), ('date_from_filename', 'Читать дату из имени SQL-бэкапа', True)]:
            checked = 'checked' if rule.get(key, default) else ''
            text += f'<label class="check"><input type="checkbox" name="{key}_{index}" value="yes" {checked}>{label}</label>'
        return text + '<button type="button" class="remove-rule">Удалить это правило</button></fieldset>'
    rules = values.get('backups', [])
    content += ''.join(rule_html(i, rule) for i, rule in enumerate(rules))
    content += '</div><template id="rule-template">' + rule_html('__INDEX__', {}) + '</template><button type="button" id="add-rule">Добавить папку</button><p class="muted">Дата из имени: _backup_YYYY_MM_DD_HHMMSS_. Для месячных выбираются файлы за 1-е число. Расписание использует локальное время Windows.</p></section><button class="primary" name="mode" value="save">Сохранить и передать агенту</button></form>'
    content += '<section class="server"><h3>Вернуться к локальному файлу</h3><p class="muted">Агент снова использует папки и службы из своего config.json.</p><form method="post" action="' + esc(url) + '">' + hidden + '<label class="check"><input type="checkbox" name="confirm_local" value="yes" required>Подтверждаю возврат к локальным настройкам</label><button name="mode" value="local">Использовать локальные настройки</button></form></section>'
    content += '''<script>
const container=document.getElementById('backup-rules');
let nextIndex=''' + str(len(rules)) + ''';
document.getElementById('add-rule').addEventListener('click',()=>{
 if(container.children.length>=20){alert('Максимум 20 правил');return;}
 const markup=document.getElementById('rule-template').innerHTML.replaceAll('__INDEX__',String(nextIndex++));
 container.insertAdjacentHTML('beforeend',markup);
});
container.addEventListener('click',event=>{if(event.target.classList.contains('remove-rule'))event.target.closest('fieldset').remove();});
</script>'''
    return page(content)
