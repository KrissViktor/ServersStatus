"""Versioned, immutable public UI assets; no generated pages or private files."""
import hashlib
from functools import lru_cache
from pathlib import Path
from fastapi import Request,HTTPException
from fastapi.responses import JSONResponse, Response

ROOT=Path(__file__).parent
PRODUCT_NAME='Server Pulse'
FILES=frozenset(('dashboard.css','appearance.css','theme.js','language.js','ui_motion.js','folding.js','cpu_cores.js','refresh.js','portal_ui.js','interface_plus.js','chart_sync.js','resource_charts.js','overview.js','ai_chat.js','ai_widget.js','task_manager.js','drilldown.js','chart_geometry.js','disk_forecast.js','server-pulse.svg'))
FILES=FILES.union(f'server-pulse-{size}.png' for size in (180,192,512))
FILES=FILES.union(('portal_sounds.js',))


@lru_cache(maxsize=32)
def asset(name):
    if name not in FILES:raise ValueError('Unknown asset')
    data=(ROOT/name).read_bytes()
    return hashlib.sha256(data).hexdigest()[:20],data


def url(name):return '/assets/'+asset(name)[0]+'/'+name


def script(name):return '<script src="'+url(name)+'"></script>'


def styles():return ''.join('<link rel="stylesheet" href="'+url(name)+'">' for name in ('dashboard.css','appearance.css'))


def register(app):
    @app.get('/manifest.webmanifest')
    def manifest():
        return JSONResponse({
            'id':'/', 'name':PRODUCT_NAME, 'short_name':PRODUCT_NAME,
            'start_url':'/', 'scope':'/', 'display':'standalone',
            'icons':[{'src':url(f'server-pulse-{size}.png'),'sizes':f'{size}x{size}','type':'image/png'}
                     for size in (192,512)],
        },media_type='application/manifest+json',headers={'Cache-Control':'no-cache'})

    @app.api_route('/assets/{version}/{name}',methods=['GET','HEAD'])
    def public_asset(version:str,name:str,request:Request):
        if name not in FILES:raise HTTPException(404)
        checksum,data=asset(name)
        if version!=checksum:raise HTTPException(404)
        headers={'ETag':'W/"'+checksum+'"','Cache-Control':'public, max-age=31536000, immutable'}
        if request.headers.get('if-none-match')==headers['ETag']:return Response(status_code=304,headers=headers)
        headers['Content-Length']=str(len(data))
        media_type={'.css':'text/css','.svg':'image/svg+xml','.js':'text/javascript','.png':'image/png'}[Path(name).suffix]
        return Response(b'' if request.method=='HEAD' else data,media_type=media_type,headers=headers)
