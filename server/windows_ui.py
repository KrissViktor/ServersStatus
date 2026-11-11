from datetime import datetime,timezone,timedelta
from .dashboard import esc,duration
import time


def stamp(value):
    if value is None:return '—'
    try:return datetime.fromtimestamp(value,timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M МСК')
    except (ValueError,OverflowError,OSError):return '—'


def section(data):
    if (data.get('system') or {}).get('os')=='Linux':return ''
    windows=data.get('windows_updates')
    content='<section class="extended"><h3>Обновления и перезагрузка Windows</h3>'
    if not windows:return content+'<p class="muted">Обновите Windows-агент для сведений об обновлениях.</p></section>'
    required=windows.get('reboot_required')
    label='🟠 Требуется перезагрузка' if required is True else '🟢 Признаков необходимости перезагрузки нет' if required is False else 'Не удалось определить необходимость перезагрузки'
    content+='<p class="status-note '+('warning' if required is True else 'normal' if required is False else 'neutral')+'">'+label+'</p>'
    if windows.get('reboot_reasons'):content+='<p>'+esc(', '.join(windows['reboot_reasons']))+'</p>'
    content+='<p class="muted">История проверена: '+stamp(windows.get('checked_at'))+' · обновление истории каждые 15 минут.</p>'
    if windows.get('status')=='checking':content+='<p>Получаем сведения Windows…</p>'
    if windows.get('status')=='unavailable':content+='<p>Windows не предоставила историю обновлений. Проверьте службы Windows Update и права агента.</p>'
    content+='<h4>Последние записи установок Windows Update</h4>'
    if windows.get('history_status')=='unavailable':content+='<p class="muted">История Windows Update недоступна.</p>'
    elif not windows.get('history'):content+='<p class="muted">История пуста или очищена.</p>'
    for event in windows.get('history',[]):
        state={2:'🟢 Установлено',3:'🟠 Завершено с ошибками',4:'🔴 Ошибка',5:'🔴 Отменено'}.get(event['result'],'Не завершено')
        content+='<p>'+esc(event['title'])+' · '+stamp(event.get('installed_at'))+' · '+state+'</p>'
    content+='<h4>Системные исправления (KB)</h4>'
    if windows.get('hotfix_status')=='unavailable':content+='<p class="muted">Список системных исправлений недоступен.</p>'
    elif not windows.get('hotfixes'):content+='<p class="muted">Системные исправления не найдены.</p>'
    for fix in windows.get('hotfixes',[]):content+='<p>'+esc(fix['kb'])+' · '+esc(fix.get('description',''))+' · '+stamp(fix.get('installed_at'))+'</p>'
    return content+'<p class="muted">История и Get-HotFix не являются полным аудитом всех компонентов. Проверка доступных обновлений запускается отдельно.</p></section>'
