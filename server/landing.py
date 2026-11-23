"""Public product introduction with synthetic monitoring data."""
from random import Random


def chart(seed, baseline, label):
    rng = Random(seed)
    points = [max(3,min(97,baseline+rng.randint(-12,12)+(18 if index in (16,17) else 0))) for index in range(37)]
    line = ' '.join(f'{index*20:.0f},{112-value*1.06:.1f}' for index,value in enumerate(points))
    grid = ''.join(f'<path d="M0 {y}H720"/>' for y in (16,40,64,88,112))
    return (
        f'<svg viewBox="0 0 720 116" role="img" aria-label="{label}, демонстрационные данные">'
        f'<g class="showcase-grid">{grid}</g><polygon points="0,112 {line} 720,112" class="showcase-area"/>'
        f'<polyline points="{line}" class="showcase-line"/></svg>'
    )


def content(brand, login):
    rows = [
        ('Web-Atlas', 'Linux', 'На связи', 'normal', '24%', '48%', '63%'),
        ('SQL-Orion', 'Windows Server', 'Диск почти заполнен', 'warning', '31%', '72%', '91%'),
        ('Backup-Nova', 'Linux', 'На связи', 'normal', '12%', '36%', '57%'),
    ]
    server_rows = ''.join(
        f'<tr><th scope="row">{name}<small>{os_name}</small></th>'
        f'<td><span class="badge {kind}">{state}</span></td>'
        f'<td>{cpu}</td><td>{ram}</td><td>{disk}</td></tr>'
        for name,os_name,state,kind,cpu,ram,disk in rows
    )
    return (
        '<div class="public-landing"><header class="landing-header">'+brand+'<div class="landing-actions">'+login+'</div></header>'
        '<section class="landing-intro"><div><h1>Состояние серверов<br>в одном месте</h1>'
        '<p>Server Pulse показывает нагрузку, свободное место, состояние служб и резервных копий. '
        'По истории замеров можно понять, когда началась проблема и что происходило с сервером в тот момент.</p>'
        '<div class="landing-links"><a href="#demo">Посмотреть пример ↓</a><a href="#how">Как это работает</a></div></div>'
        '<div class="landing-preview"><div class="landing-preview-title"><span class="badge normal">На связи</span>'
        '<strong>Web-Atlas</strong><span class="muted">Последние 60 минут · пример</span></div>'
        '<div class="landing-chart"><div><b>CPU</b><span>24%</span></div>'+chart(13,25,'Загрузка CPU')+'</div>'
        '<div class="landing-chart landing-chart-ram"><div><b>RAM</b><span>48%</span></div>'+chart(32,49,'Занятость RAM')+'</div></div></section>'
        '<section id="demo" class="landing-demo" tabindex="-1"><div class="landing-section-title"><h2>Как выглядит обзор</h2>'
        '<span class="muted">Вымышленные серверы и показатели</span></div>'
        '<div class="table-scroll" tabindex="0" role="region" aria-label="Пример списка серверов"><table class="metric-table">'
        '<thead><tr><th scope="col">Сервер</th><th scope="col">Состояние</th><th scope="col">CPU</th><th scope="col">RAM</th><th scope="col">Диск</th></tr></thead>'
        '<tbody>'+server_rows+'</tbody></table></div>'
        '<div class="landing-site-examples"><h3>Пример мониторинга сайтов</h3>'
        '<div class="landing-site-row"><strong>atlas.example</strong><span class="badge normal">HTTP 200</span><span>124 мс</span><span>TLS действителен</span></div>'
        '<div class="landing-site-row"><strong>api.nova.example</strong><span class="badge warning">HTTP 503</span><span>836 мс</span><span>TLS истекает через 9 дней</span></div>'
        '</div></section>'
        '<section id="how" class="landing-how" tabindex="-1"><h2>Как это работает</h2><div class="landing-steps">'
        '<article><h3>Агенты собирают замеры</h3><p>Агенты Windows и Linux отправляют метрики, сведения о дисках, службах и резервных копиях по HTTPS.</p></article>'
        '<article><h3>Портал хранит историю</h3><p>Выбирайте период, сравнивайте серверы и открывайте снимок исходного отчёта по точке графика.</p></article>'
        '<article><h3>Уведомления помогают реагировать</h3><p>Портал показывает инциденты, а мониторы сайтов проверяют HTTP и сроки сертификатов. Предупреждения можно получать в Telegram.</p></article>'
        '</div></section>'
        '<section class="landing-how"><div class="landing-section-title"><h2>От замера до решения</h2><span class="muted">Пример инцидента</span></div>'
        '<div class="landing-scenario"><div class="landing-preview"><div class="landing-preview-title"><strong>SQL-Orion</strong>'
        '<span class="badge warning">Мало места на диске</span></div>'
        '<div class="landing-chart"><div><b>Диск C:</b><span>91%</span></div>'+chart(47,86,'Заполненность диска')+'</div></div>'
        '<ol class="landing-incident"><li><time>09:30</time><b>Диск заполнился на 91%</b><p>На обзоре появилось предупреждение.</p></li>'
        '<li><time>09:34</time><b>Открыли снимок сервера</b><p>По выбранной точке проверили нагрузку, свободное место и состояние бэкапов.</p></li>'
        '<li><time>09:42</time><b>Место освободилось</b><p>Новый отчёт агента подтвердил восстановление.</p></li></ol></div></section>'
        '<section class="landing-how"><h2>Для ежедневной работы</h2><div class="landing-steps">'
        '<article><h3>История нагрузки</h3><p>CPU, RAM и диски на общей шкале. Откройте снимок по точке, чтобы увидеть исходный отчёт.</p></article>'
        '<article><h3>План на неделю</h3><p>Прогноз заполнения дисков, повторяющиеся сбои и бэкапы, требующие проверки.</p></article>'
        '<article><h3>Мониторы сайтов</h3><p>Ожидаемый HTTP-код, время отклика, срок действия TLS и история проверок.</p></article>'
        '</div></section></div>'
    )
