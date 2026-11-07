"""Version dates and a small, ordered per-agent update selector."""
from datetime import datetime,timezone,timedelta
from functools import lru_cache
from pathlib import Path
import re
import subprocess

SCHEMA='''CREATE TABLE IF NOT EXISTS update_package_dates (package INTEGER PRIMARY KEY,built_at REAL,commit_at REAL);
CREATE TABLE IF NOT EXISTS update_job_context (job INTEGER PRIMARY KEY,from_version TEXT);
CREATE TABLE IF NOT EXISTS update_job_events (id INTEGER PRIMARY KEY,job INTEGER,created REAL,status TEXT,message TEXT);
CREATE INDEX IF NOT EXISTS update_job_events_job ON update_job_events(job,id);'''


@lru_cache(maxsize=1024)
def commit_date(version):
    if not isinstance(version,str) or not re.fullmatch(r'[a-f0-9]{7,40}',version):return None
    root=Path(__file__).resolve().parents[1]
    try:
        result=subprocess.run(['git','-c','safe.directory='+str(root),'-C',str(root),'show','-s','--format=%ct','--end-of-options',version,'--'],capture_output=True,text=True,timeout=2)
        return float(result.stdout.strip()) if result.returncode==0 else None
    except (OSError,ValueError,subprocess.TimeoutExpired):return None


def stamp(value):
    if not value:return 'дата не указана'
    try:return datetime.fromtimestamp(value,timezone(timedelta(hours=3))).strftime('%d.%m.%Y %H:%M')
    except (ValueError,OSError,OverflowError):return 'дата не указана'


def choices(packages,platform,current):
    unique={}
    for item in packages:
        item=dict(item)
        if item['platform']!=platform:continue
        item['order_date']=item.get('commit_at') or commit_date(item['version']) or item.get('built_at')
        item['display_date']=item.get('built_at') or item['order_date']
        if item['version'] not in unique or item['id']>unique[item['version']]['id']:unique[item['version']]=item
    current_package=unique.get(current)
    current_date=(current_package or {}).get('order_date') or commit_date(current)
    candidates=[p for p in unique.values() if p['version']!=current]
    if current_date:
        newer=[p for p in candidates if p['order_date'] and p['order_date']>current_date]
        older=[p for p in candidates if p['order_date'] and p['order_date']<current_date]
        key=lambda p:(p['order_date'],p['id'])
    else:
        # Legacy/manual versions without a source date use catalog registration order.
        base=current_package['id'] if current_package else 0
        newer=[p for p in candidates if p['id']>base]
        older=[p for p in candidates if p['id']<base]
        key=lambda p:p['id']
    result=[]
    if newer:result.append({**max(newer,key=key),'label':'New'})
    if older:result.append({**max(older,key=key),'label':'Older'})
    return result,(current_package or {}).get('display_date') or current_date


def event(c,job,status,message,now):
    previous=c.execute('SELECT status,message FROM update_job_events WHERE job=? ORDER BY id DESC LIMIT 1',(job,)).fetchone()
    if not previous or (previous['status'],previous['message'])!=(status,message):
        c.execute('INSERT INTO update_job_events(job,created,status,message) VALUES (?,?,?,?)',(job,now,status,message))
