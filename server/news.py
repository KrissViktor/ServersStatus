"""Idempotent portal news restored from bundled and locally available Git metadata."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import threading
import time
from urllib.parse import urlencode
from fastapi import Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse

ROOT=Path(__file__).resolve().parents[1]
BUNDLE=Path(__file__).with_name('data')/'release_history.json'
TITLES=Path(__file__).with_name('data')/'release_titles.json'
SCHEMA='''CREATE TABLE IF NOT EXISTS portal_news(id INTEGER PRIMARY KEY AUTOINCREMENT,sha TEXT NOT NULL UNIQUE,published REAL NOT NULL,title TEXT NOT NULL,original TEXT NOT NULL,category TEXT NOT NULL,tags TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS portal_news_time ON portal_news(published);
CREATE TABLE IF NOT EXISTS portal_news_seen(username TEXT PRIMARY KEY,news_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS portal_news_meta(name TEXT PRIMARY KEY,value TEXT NOT NULL);'''
_lock=threading.Lock();_cache=None;_until=0
CATEGORIES={'portal':'Портал','agents':'Агенты','ai':'ИИ-помощник','verification':'Проверки и сборки','project':'Проект'}


def git_entries(extra_tags=None):
    result=subprocess.run(['git','--no-pager','-c','safe.directory='+str(ROOT),'-C',str(ROOT),'log','--no-show-signature','--reverse','-n','10000','--format=%H%x1f%ct%x1f%s%x1e','HEAD'],capture_output=True,text=True,timeout=5,check=True)
    tags=dict(extra_tags or {})
    try:
        refs=subprocess.run(['git','-c','safe.directory='+str(ROOT),'-C',str(ROOT),'for-each-ref','--format=%(objectname)%09%(refname:short)%09%(*objectname)','refs/tags'],capture_output=True,text=True,timeout=3,check=True)
        for line in refs.stdout.splitlines():
            parts=line.split('\t');sha=parts[2] if len(parts)>2 and parts[2] else parts[0]
            if len(parts)>1:tags.setdefault(sha,[]).append(parts[1])
    except (OSError,subprocess.SubprocessError):pass
    translations=json.loads(TITLES.read_text(encoding='utf-8')) if TITLES.exists() else {}
    entries=[]
    for block in result.stdout.split('\x1e'):
        values=block.strip().split('\x1f',2)
        if len(values)!=3 or not re.fullmatch('[a-f0-9]{40}',values[0]):continue
        sha,at,subject=values;lower=subject.lower()
        category='verification' if any(term in lower for term in ('record successful','record passing','document successful','validation','regression checks','verification reference')) else 'ai' if any(term in lower for term in ('ai ','llama','model shards','tavily','weather','currency','cbr ','reverse ssh','tailscale')) else 'agents' if any(term in lower for term in ('agent','pywin32','sensor','cpu model','windows service')) else 'portal'
        title=translations.get(sha[:7],subject)
        if subject.startswith('Add table view, stability heatmap'):title='Таблица серверов, карта стабильности, лента событий, большой экран и новости'
        if subject.startswith('Refresh release news bundle'):title='Синхронизация истории обновлений портала';category='verification'
        entries.append({'sha':sha,'published':int(at),'title':title[:300],'original':subject[:500],'category':category,'tags':sorted(set(tags.get(sha,[])))})
    return entries


def catalog(force=False):
    global _cache,_until
    with _lock:
        if _cache is not None and time.monotonic()<_until and not force:return _cache
        entries={}
        try:
            for item in json.loads(BUNDLE.read_text(encoding='utf-8')):entries[item['sha']]=item
        except (OSError,ValueError,KeyError):pass
        try:
            for item in git_entries():
                if item['sha'] in entries:item['tags']=sorted(set(item['tags']+entries[item['sha']].get('tags',[])))
                entries[item['sha']]=item
        except (OSError,ValueError,subprocess.SubprocessError):pass
        _cache=sorted(entries.values(),key=lambda item:(item['published'],item['sha']));_until=time.monotonic()+60
        return _cache


def sync(c):
    entries=catalog();fingerprint=hashlib.sha256(json.dumps(entries,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    previous=c.execute("SELECT value FROM portal_news_meta WHERE name='catalog'").fetchone()
    if previous and previous[0]==fingerprint:return
    for item in entries:
        c.execute('INSERT INTO portal_news(sha,published,title,original,category,tags) VALUES (?,?,?,?,?,?) ON CONFLICT(sha) DO UPDATE SET title=excluded.title,tags=excluded.tags,category=excluded.category',(item['sha'],item['published'],item['title'],item['original'],item['category'],json.dumps(item['tags'],ensure_ascii=False)))
    c.execute("INSERT INTO portal_news_meta VALUES ('catalog',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value",(fingerprint,))


def banner(c,username):
    from .dashboard import esc
    from .ui_icons import icon
    seen=c.execute('SELECT news_id FROM portal_news_seen WHERE username=?',(username,)).fetchone();seen=seen[0] if seen else 0
    count=c.execute('SELECT COUNT(*) FROM portal_news WHERE id>?',(seen,)).fetchone()[0]
    result='<details class="portal-news-top"><summary title="Новости портала">'+icon('news')+'<span>Новости</span>'+('<b>'+('99+' if count>99 else str(count))+'</b>' if count else '')+'</summary><div class="news-popover"><header><strong>Что нового</strong><a href="/news">Все обновления →</a></header>'
    from .windows_ui import stamp
    for row in c.execute('SELECT * FROM portal_news ORDER BY id DESC LIMIT 3'):
        result+='<a class="news-preview" href="/news"><small>'+esc(stamp(row['published']))+' · '+esc(CATEGORIES.get(row['category'],'Проект'))+'</small><span>'+esc(row['title'])+'</span></a>'
    return result+'</div></details>'


def register(app,db,authenticated):
    from .dashboard import page,esc
    from .access import current_user
    from .windows_ui import stamp
    from .ui_icons import icon
    @app.get('/news',response_class=HTMLResponse)
    def news(request:Request,before:int=0,category:str='',q:str=''):
        if not authenticated(request):return RedirectResponse('/',303)
        if before<0 or len(q)>200 or category not in ('',*CATEGORIES):raise HTTPException(400)
        with db() as c:
            rows=c.execute("SELECT * FROM portal_news WHERE (?=0 OR id<?) AND (?='' OR category=?) AND (title LIKE ? OR original LIKE ?) ORDER BY id DESC LIMIT 21",(before,before,category,category,'%'+q+'%','%'+q+'%')).fetchall()
            latest=c.execute('SELECT COALESCE(MAX(id),0) FROM portal_news').fetchone()[0]
            c.execute('INSERT INTO portal_news_seen VALUES (?,?) ON CONFLICT(username) DO UPDATE SET news_id=MAX(news_id,excluded.news_id)',(current_user().get('name') or '',latest))
            total=c.execute('SELECT COUNT(*) FROM portal_news').fetchone()[0]
        content='<header class="topbar"><a class="brand" href="/">ServersStatus</a><a class="nav-link" href="/">← Серверы</a></header><div class="heading"><h1>'+icon('news')+' Новости портала</h1><span class="muted">'+str(total)+' записей из Git</span></div><form class="fleet-filter"><label>Поиск<input name="q" value="'+esc(q)+'"></label><label>Раздел<select name="category"><option value="">Все</option>'+''.join('<option value="'+key+'" '+('selected' if key==category else '')+'>'+label+'</option>' for key,label in CATEGORIES.items())+'</select></label><button>Показать</button></form><p class="muted">История разработки и релизов. Даты восстановлены из Git и не являются временем установки обновления на вашем сервере.</p><div class="news-feed">'
        for row in rows[:20]:
            tags=json.loads(row['tags'])
            content+='<article class="news-entry"><div class="news-entry-icon">'+icon('update' if row['category']!='verification' else 'timeline')+'</div><div><p class="muted">'+esc(stamp(row['published']))+' · '+esc(CATEGORIES.get(row['category'],'Проект'))+'</p><h2>'+esc(row['title'])+'</h2>'
            if tags:content+='<div class="news-tags">'+''.join('<span>'+esc(tag)+'</span>' for tag in tags)+'</div>'
            content+='<details><summary>Исходная запись Git · '+row['sha'][:7]+'</summary><p>'+esc(row['original'])+'</p><a class="nav-link" href="https://github.com/KrissViktor/ServersStatus/commit/'+row['sha']+'" target="_blank" rel="noopener noreferrer">Открыть коммит ↗</a></details></div></article>'
        if not rows:content+='<p class="empty">Записей по выбранным условиям нет.</p>'
        content+='</div>'
        if len(rows)>20:content+='<a class="nav-link" href="/news?'+esc(urlencode({'before':rows[19]['id'],'category':category,'q':q}))+'">Предыдущие обновления →</a>'
        return HTMLResponse(page(content))


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--build-bundle',action='store_true');parser.add_argument('--tags-file')
    args=parser.parse_args();tags={}
    if args.tags_file:
        refs={}
        for line in Path(args.tags_file).read_text().splitlines():
            sha,name=line.split('\t',1)
            if name.startswith('refs/tags/'):
                name=name.removeprefix('refs/tags/');peeled=name.endswith('^{}');name=name.removesuffix('^{}')
                if peeled or name not in refs:refs[name]=sha
        for name,sha in refs.items():tags.setdefault(sha,[]).append(name)
    data=git_entries(tags)
    if args.build_bundle:
        BUNDLE.parent.mkdir(parents=True,exist_ok=True);BUNDLE.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Git news entries:',len(data),'release tags:',sum(len(item['tags']) for item in data))


if __name__=='__main__':main()
