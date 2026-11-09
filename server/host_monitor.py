"""Local portal telemetry, collected independently of browser visits."""
import hashlib
import json
from pathlib import Path
import secrets
import time
from agent.client import collect
from agent.linux_inventory import systemd_services
from .retention import cleanup


def temperature():
    try:
        value=float(Path('/sys/class/thermal/thermal_zone0/temp').read_text())/1000
        return value if -20<=value<=150 else None
    except (OSError,ValueError):return None


def database_size(path):
    return sum(p.stat().st_size for p in (Path(path),Path(str(path)+'-wal'),Path(str(path)+'-shm')) if p.is_file())


def enrich_host(data, path):
    """Keep common Linux sensors; provide the local SoC reading as a fallback."""
    current=temperature()
    data.update(agent_platform='portal',
        features=list(dict.fromkeys(data.get('features',[])+['host_monitor_v1','service_inventory_v1','process_history_v1'])),
        services=[],discovered_services=[],auto_services_enabled=False)
    data['portal']={'temperature_c':current,'database_bytes':database_size(path)}
    if current is not None and not (data.get('temperatures') or {}).get('items'):
        data['temperatures']={'status':'available','sampled_at':time.time(),'items':[
            {'id':'portal:thermal_zone0','label':'SoC','device':'Raspberry Pi',
             'component':'SoC','source':'Linux thermal_zone0','current':current,
             'high':None,'critical':None}]}
    return data


def register_host(db):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT agent FROM local_host WHERE id=1').fetchone()
        if row:return row['agent']
        agent='raspi-portal'
        if c.execute('SELECT 1 FROM agents WHERE id=?',(agent,)).fetchone():raise RuntimeError('Agent raspi-portal already exists; choose another ID for that agent first')
        c.execute('INSERT INTO agents VALUES (?,?)',(agent,hashlib.sha256(secrets.token_bytes(32)).hexdigest()))
        c.execute('INSERT INTO agent_profiles VALUES (?,?)',(agent,'Raspberry Pi — портал'))
        c.execute('INSERT INTO local_host VALUES (1,?)',(agent,))
        return agent


def store(db,agent,data,now,processes=None):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent,)).fetchone():return False
        encoded=json.dumps(data)
        c.execute('INSERT INTO latest_reports VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET received=excluded.received,data=excluded.data',(agent,now,encoded))
        identifier=c.execute('INSERT INTO reports VALUES (?,?,?)',(agent,now,encoded)).lastrowid
        if processes is not None:
            from .processes import store as store_processes
            store_processes(c,agent,{**processes,'report_id':identifier,'report_received':now},now)
        cleanup(c,now)
    return True


def main():
    import logging
    from .app import db,DB,Report
    logging.basicConfig(level=logging.INFO)
    agent=register_host(db)
    while True:
        started=time.monotonic()
        try:
            from agent.processes import begin,finish
            before=begin()
            data=collect({'auto_monitor_services':False},{})
            data=enrich_host(data,DB)
            units=['serversstatus.service','serversstatus-bot.service','serversstatus-notify.timer','serversstatus-host-monitor.service','serversstatus-events.timer','serversstatus-hysteria.service']
            units=[name for name in units if Path('/etc/systemd/system',name).exists()]
            data['services']=systemd_services(units)
            data=Report.model_validate(data).model_dump()
            processes=finish(before)
            if not store(db,agent,data,time.time(),processes):return
            from agent.service_inventory import handle
            def save_services(payload):
                from .services import store as store_services
                with db() as c:store_services(c,agent,payload)
            handle(sink=save_services)
        except Exception:
            logging.exception('Local telemetry collection failed')
        time.sleep(max(.5,10-(time.monotonic()-started)))


if __name__=='__main__':main()
