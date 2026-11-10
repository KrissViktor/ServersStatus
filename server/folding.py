"""Collapsible sections for server-generated detail HTML."""
import hashlib
import html
import re


# Small inline illustrations inherit the portal palette and need no external assets.
def section_icon(title):
    drawings = {
        'Отклик приложений': '<rect x="2" y="3" width="20" height="18" rx="3"/><path d="M2 8h20M6 14h3l2-3 3 7 2-4h3"/>',
        'Изменения комплектации': '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7m2-4v6l4 2"/>',
        'Доступность и агент': '<path d="M12 2 3 6v6c0 5 9 10 9 10s9-5 9-10V6Z"/><path d="M6 12h3l2-4 3 8 2-4h2"/>',
        'Диски': '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="11" cy="10" r="4"/><path d="m11 10 6 5M6 18h1m3 0h1"/>',
        'Температуры': '<path d="M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0Z"/><path d="M12 7v10m6-10h3m-3 4h2"/>',
        'Службы': '<path d="m12 3 2 3 4-1 1 4 3 3-3 2 1 4-4 1-4 3-2-3-4 1-1-4-3-2 3-3-1-4 4 1Z"/><circle cx="12" cy="12" r="3"/>',
        'Резервные копии': '<path d="M4 8h16v13H4zM3 3h18v5H3zM9 12h6m-3 0v5m-2-2 2 2 2-2"/>',
        'Сетевые интерфейсы': '<rect x="8" y="2" width="8" height="6" rx="1"/><path d="M12 8v6M4 17v-3h16v3"/><rect x="1" y="17" width="6" height="5" rx="1"/><rect x="17" y="17" width="6" height="5" rx="1"/>',
        'Дисковые операции': '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M6 9h12m-3-3 3 3-3 3M18 16H6m3-3-3 3 3 3"/>',
        'Пользователи RDP': '<circle cx="9" cy="7" r="3"/><path d="M3 19v-2a6 6 0 0 1 12 0v2m2-15a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 5"/>',
        'Диспетчер задач': '<rect x="2" y="3" width="20" height="15" rx="2"/><path d="M8 22h8m-4-4v4M5 12h3l2-5 4 8 2-4h3"/>',
        'Мини-консоль': '<rect x="2" y="3" width="20" height="18" rx="3"/><path d="m6 8 4 4-4 4m7 0h5"/>',
    }
    if 'Windows' in title:
        drawing = '<path d="m3 5 8-1v8H3Zm10-1 8-1v9h-8ZM3 14h8v7l-8-1Zm10 0h8v9l-8-1Z"/>'
    else:
        drawing = drawings.get(title, '<rect x="2" y="3" width="20" height="15" rx="2"/><path d="M8 22h8m-4-4v4M6 7h12M6 11h7"/>')
    return '<svg class="section-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+drawing+'</svg>'


def fold_sections(content):
    # Sections produced by our renderers are flat and their heading is the first child.
    def replace(match):
        attrs,title,body=match.group(1),match.group(3),match.group(4)
        plain=html.unescape(re.sub('<[^>]+>','',re.sub(r'<span class="count">.*?</span>','',title))).strip()
        key=hashlib.sha256(plain.encode()).hexdigest()[:16]
        classes=re.search(r'class="([^"]*)"',attrs)
        outer='server server-fold' if classes and 'server' in classes.group(1).split() else 'section-fold'
        if classes and 'terminal-panel' in classes.group(1).split():outer+=' terminal-fold'
        expand='<button type="button" class="fold-size" aria-pressed="false" title="Развернуть блок на всю ширину"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M8 4H4v4m12-4h4v4M4 16v4h4m12-4v4h-4M4 4l5 5m11-5-5 5M4 20l5-5m11 5-5-5"/></svg><span>Расширить</span></button>' if outer=='section-fold' else ''
        attrs=re.sub(r'class="([^"]*)"',lambda m:'class="'+' '.join(v for v in m.group(1).split() if v!='server')+'"',attrs)
        return f'<details class="{outer}" data-fold-key="{key}"><summary><span class="fold-title">{section_icon(plain)}{title}</span>{expand}</summary><section{attrs}>{body}</section></details>'
    return re.sub(r'<section([^>]*)><h([23])>(.*?)</h\2>(.*?)</section>',replace,content,flags=re.S)
