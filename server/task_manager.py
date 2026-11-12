"""Shared read-only task manager for current reports and historical snapshots."""
import json
from pathlib import Path
from urllib.parse import quote
from .dashboard import esc

SCRIPT=Path(__file__).with_name('task_manager.js').read_text(encoding='utf-8')


def assets():
    from .assets import script
    return script('task_manager.js')


def section(agent,payload=None):
    historical=payload is not None
    attrs=' data-task-payload="'+esc(json.dumps(payload,ensure_ascii=False))+'"' if historical else ' data-task-agent="'+esc(quote(agent,safe=''))+'"'
    content='<section class="server task-manager"'+attrs+'><h2>Диспетчер задач</h2><div class="task-tabs" role="tablist" aria-label="Диспетчер задач"><button type="button" role="tab" aria-selected="true" data-task-tab="processes">Процессы</button><button type="button" role="tab" aria-selected="false" data-task-tab="services" tabindex="-1">Службы</button></div>'
    for kind,title,cols in [('processes','процессов',[('name','Процесс'),('pid','PID'),('username','Пользователь'),('cpu_percent','CPU'),('memory_bytes','Память'),('status','Состояние'),('details','Подробности')]),('services','служб',[('name','Служба'),('display_name','Описание'),('status','Состояние'),('pid','PID'),('start','Автозапуск'),('user','Пользователь'),('details','Подробности')])]:
        content+='<div data-task-view="'+kind+'" role="tabpanel"'+(' hidden' if kind=='services' else '')+'><p class="muted task-info" role="status">Загрузка списка '+title+'…</p><div class="searchbar"><label>Поиск<input type="search" class="task-search" placeholder="Имя, PID, пользователь, сведения…"></label><label>Состояние<select class="task-state"><option value="all">Все</option></select></label><label>Сортировка<select class="task-sort">'+''.join('<option value="'+k+'">'+t+'</option>' for k,t in cols if k!='details')+'</select></label><button type="button" class="task-direction">По убыванию ↓</button></div><div class="task-table-scroll" tabindex="0" aria-label="Прокручиваемый список '+title+'"><table class="metric-table task-table"><thead><tr>'+''.join('<th scope="col"'+(' aria-sort="none"' if k!='details' else '')+'>'+('<button type="button" data-sort="'+k+'">'+t+'</button>' if k!='details' else t)+'</th>' for k,t in cols)+'</tr></thead><tbody></tbody></table></div></div>'
    content+='<details class="task-help"><summary>О данных и ограничениях</summary><p>CPU — доля общей мощности всех ядер. Память — резидентная память процесса. Показаны все сохранённые строки; недоступные сведения отмечены «—». Подробности раскрываются в каждой строке. Поиск и сортировка применяются сразу.</p><p>'+('Процессы относятся к выбранному отчёту. Службы — последняя сохранённая инвентаризация до него; её время указано отдельно. Текущие данные не подставляются в прошлое.' if historical else 'Процессы обновляются каждые 10 секунд, службы собираются агентом раз в минуту. Состояние службы и автозапуск независимы. Полный список служб не меняет список для оповещений.')+'</p></details></section>'
    return content
