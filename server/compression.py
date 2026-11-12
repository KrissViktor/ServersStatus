"""Compress UI traffic without changing agent upload/download responses."""
from starlette.middleware.gzip import GZipMiddleware


class UICompression:
    def __init__(self,app):
        self.app=app
        self.compressed=GZipMiddleware(app,minimum_size=1024,compresslevel=3)

    async def __call__(self,scope,receive,send):
        path=scope.get('path','')
        target=self.app if scope['type']!='http' or path.startswith(('/api/report/','/api/processes/','/api/agent-update/','/api/windows/','/api/console/')) else self.compressed
        await target(scope,receive,send)
