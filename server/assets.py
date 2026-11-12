"""Versioned, immutable public UI assets; no generated pages or private files."""
import hashlib
from functools import lru_cache
from pathlib import Path
from fastapi import Request,HTTPException
from fastapi.responses import Response

ROOT=Path(__file__).parent
FILES=frozenset(('dashboard.css','appearance.css','ui_motion.js','folding.js','cpu_cores.js','refresh.js','portal_ui.js','interface_plus.js','chart_sync.js','resource_charts.js','overview.js','ai_chat.js','ai_widget.js','task_manager.js','drilldown.js','chart_geometry.js'))


@lru_cache(maxsize=32)
def asset(name):
    if name not in FILES:raise ValueError('Unknown asset')
    data=(ROOT/name).read_bytes()
    return hashlib.sha256(data).hexdigest()[:20],data


def url(name):return '/assets/'+asset(name)[0]+'/'+name


def script(name):return '<script src="'+url(name)+'"></script>'


def styles():return ''.join('<link rel="stylesheet" href="'+url(name)+'">' for name in ('dashboard.css','appearance.css'))


def register(app):
    @app.api_route('/assets/{version}/{name}',methods=['GET','HEAD'])
    def public_asset(version:str,name:str,request:Request):
        if name not in FILES:raise HTTPException(404)
        checksum,data=asset(name)
        if version!=checksum:raise HTTPException(404)
        headers={'ETag':'W/"'+checksum+'"','Cache-Control':'public, max-age=31536000, immutable'}
        if request.headers.get('if-none-match')==headers['ETag']:return Response(status_code=304,headers=headers)
        headers['Content-Length']=str(len(data))
        return Response(b'' if request.method=='HEAD' else data,media_type='text/css' if name.endswith('.css') else 'text/javascript',headers=headers)
