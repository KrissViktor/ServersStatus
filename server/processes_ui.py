from pathlib import Path
from .dashboard import esc
from urllib.parse import quote

SCRIPT=Path(__file__).with_name('processes.js').read_text()


def process_section(agent):
    return '<section class="server process-panel" data-process-url="/api/servers/'+esc(quote(agent,safe=''))+'/processes"><h2>Процессы</h2><p class="muted process-info" role="status">Загрузка списка процессов…</p><div class="searchbar"><label>Сортировка<select class="process-sort"><option value="cpu_percent">CPU</option><option value="memory_bytes">Память</option><option value="pid">PID</option><option value="name">Имя</option><option value="username">Пользователь</option></select></label><button type="button" class="process-direction" aria-label="Изменить направление сортировки">По убыванию ↓</button><button type="button" class="process-expand" aria-expanded="false">Показать все</button></div><div class="table-scroll" style="max-height:600px;overflow:auto"><table class="metric-table"><thead><tr><th>PID</th><th>Имя</th><th>Пользователь</th><th>CPU</th><th>Память</th><th>Состояние</th></tr></thead><tbody class="process-rows"></tbody></table></div><p class="muted">CPU — доля общей мощности всех ядер. Недоступные значения отмечены «—». Полный список — последний. Исторические снимки содержат топ-10 по CPU и памяти при поддержке агентом привязки отчётов.</p></section><script>'+SCRIPT+'</script>'
