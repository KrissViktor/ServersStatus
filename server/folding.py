"""Collapsible sections for server-generated detail HTML."""
import hashlib
import html
import re


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
        return f'<details class="{outer}" data-fold-key="{key}"><summary><span class="fold-title">{title}</span>{expand}</summary><section{attrs}>{body}</section></details>'
    return re.sub(r'<section([^>]*)><h([23])>(.*?)</h\2>(.*?)</section>',replace,content,flags=re.S)
