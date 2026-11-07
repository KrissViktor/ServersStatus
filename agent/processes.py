"""Read-only process snapshots. CPU is normalized to total machine capacity."""
import time
import json
import os
import psutil

MAX_PROCESSES=10000


def begin():
    result={}
    try:
        psutil.process_iter.cache_clear()
        for process in psutil.process_iter(['pid','create_time','cpu_times'],ad_value=None):
            info=process.info;cpu=info.get('cpu_times')
            if cpu is not None and info.get('create_time') is not None:
                result[(info['pid'],info['create_time'])]=(cpu.user+cpu.system,time.perf_counter())
    except (psutil.Error,OSError):pass
    return result


def finish(before):
    result=[];total=0;unreadable=0;encoded_size=0
    cores=max(1,psutil.cpu_count() or 1)
    try:
        psutil.process_iter.cache_clear()
        for process in psutil.process_iter(['pid','name','username','create_time','cpu_times','memory_info','status'],ad_value=None):
            info=process.info;total+=1
            if len(result)>=MAX_PROCESSES:continue
            old=before.get((info['pid'],info.get('create_time')))
            cpu=info.get('cpu_times');percent=None
            if old and cpu is not None:
                elapsed=time.perf_counter()-old[1]
                if elapsed>0:percent=round(min(100,max(0,(cpu.user+cpu.system-old[0])/elapsed/cores*100)),2)
            memory=info.get('memory_info')
            if any(info.get(field) is None for field in ('name','username','cpu_times','memory_info')):unreadable+=1
            if os.name=='nt' and info['pid']==0:percent=0
            entry={'pid':info['pid'],'name':str(info.get('name') or '')[:255],
                'username':str(info.get('username') or '')[:255],'cpu_percent':percent,
                'memory_bytes':memory.rss if memory is not None else None,
                'status':str(info.get('status') or '')[:40]}
            size=len(json.dumps(entry,ensure_ascii=False).encode('utf-8'))+2
            if encoded_size+size>1900000:continue
            encoded_size+=size
            result.append(entry)
    except (psutil.Error,OSError):
        return {'status':'unavailable','items':[],'total':total,'unreadable':unreadable,'truncated':False}
    return {'status':'available','items':result,'total':total,'unreadable':unreadable,'truncated':total>len(result)}
