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


def store(db,agent,data,now):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent,)).fetchone():return False
        encoded=json.dumps(data)
        c.execute('INSERT INTO latest_reports VALUES (?,?,?) ON CONFLICT(agent) DO UPDATE SET received=excluded.received,data=excluded.data',(agent,now,encoded))
        c.execute('INSERT INTO reports VALUES (?,?,?)',(agent,now,encoded))
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
            data=collect({'auto_monitor_services':False},{})
            data.update(agent_platform='portal',features=['host_monitor_v1'],services=[],discovered_services=[],auto_services_enabled=False)
            units=['serversstatus.service','serversstatus-bot.service','serversstatus-notify.timer','serversstatus-host-monitor.service','serversstatus-events.timer','serversstatus-hysteria.service']
            units=[name for name in units if Path('/etc/systemd/system',name).exists()]
            data['services']=systemd_services(units)
            data['portal']={'temperature_c':temperature(),'database_bytes':database_size(DB)}
            data=Report.model_validate(data).model_dump()
            if not store(db,agent,data,time.time()):return
        except Exception:
            logging.exception('Local telemetry collection failed')
        time.sleep(max(.5,10-(time.monotonic()-started)))


if __name__=='__main__':main()
