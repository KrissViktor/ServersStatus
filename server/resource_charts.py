"""Bounded resource history and safe metadata for interactive SVG charts."""
import json
import math
import time
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse

PERIODS={'15m':900,'1h':3600,'6h':21600,'24h':86400,'7d':604800,'30d':2592000}
CPU='#7dbbff'
RAM='#b9a0ff'


def metadata(points,metric,start,end):
    from .dashboard import esc
    safe=[]
    for raw in points:
        p=dict(raw)
        safe.append({k:v for k,v in p.items() if k in {'timestamp','first','last','samples','cpu','ram','cpu_min','ram_min','cpu_peak','ram_peak','has_gap','ram_used_bytes','ram_total_bytes','report_id'} and (v is None or isinstance(v,(int,float)) and math.isfinite(v))})
    return ' data-resource-metric="'+metric+'" data-resource-points="'+esc(json.dumps(safe,separators=(',',':'),allow_nan=False))+'"'


def markers(c,agent,start,end):
    result=[]
    for row in c.execute('SELECT opened,category,message FROM incident_history WHERE agent=? AND opened>=? AND opened<=? ORDER BY opened DESC LIMIT 60',(agent,start,end)):
        result.append({'timestamp':row['opened'],'kind':'connection' if row['category']=='connection' else 'incident','text':row['message'][:500]})
    for row in c.execute('SELECT at,kind,message FROM server_boot_events WHERE agent=? AND at>=? AND at<=? ORDER BY at DESC LIMIT 20',(agent,start,end)):
        result.append({'timestamp':row['at'],'kind':'boot','text':row['kind']+': '+row['message'][:500]})
    return sorted(result,key=lambda item:item['timestamp'])


def register(app,db,authenticated):
    @app.get('/api/history/{agent_id}/resources')
    def resources(agent_id:str,request:Request,period:str='15m',start:float|None=None,end:float|None=None,overview:bool=False):
        from .access import can_history
        from .history import load_history
        if not authenticated(request):raise HTTPException(401)
        if not can_history():raise HTTPException(403)
        now=time.time()
        if period not in PERIODS or (start is None)!=(end is None):raise HTTPException(400,'Некорректный период')
        if start is None:end=now;start=end-PERIODS[period]
        if any(not math.isfinite(v) or v<0 or v>4102444800 for v in (start,end)) or not 1<=end-start<=2678400:raise HTTPException(400,'Некорректные границы периода')
        bucket=max(30 if overview else 10,math.ceil((end-start)/360))
        with db() as c:
            if not c.execute('SELECT 1 FROM agents WHERE id=?',(agent_id,)).fetchone():raise HTTPException(404)
            points=[dict(row) for row in load_history(c,agent_id,start,end,bucket)]
            events=markers(c,agent_id,start,end)
        return JSONResponse({'start':start,'end':end,'bucket':bucket,'points':points,'events':events},headers={'Cache-Control':'no-store'})

    @app.get('/api/history/{agent_id}/report-step')
    def step(agent_id:str,request:Request,report_id:int,direction:int):
        from .access import can_history
        if not authenticated(request):raise HTTPException(401)
        if not can_history():raise HTTPException(403)
        if direction not in (-1,1) or not 1<=report_id<=9223372036854775807:raise HTTPException(400)
        with db() as c:
            row=c.execute('SELECT received FROM reports WHERE rowid=? AND agent=?',(report_id,agent_id)).fetchone()
            if not row:raise HTTPException(404,'Отчёт больше недоступен')
            sign,order=('<','DESC') if direction<0 else ('>','ASC')
            target=c.execute(f'SELECT rowid AS report_id,received AS timestamp FROM reports WHERE agent=? AND (received,rowid){sign}(?,?) ORDER BY received {order},rowid {order} LIMIT 1',(agent_id,row['received'],report_id)).fetchone()
        return JSONResponse(dict(target) if target else {'report_id':None},headers={'Cache-Control':'no-store'})
