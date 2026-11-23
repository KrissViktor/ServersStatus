"""Background health check for the fixed local-model endpoint."""
import asyncio
from contextlib import asynccontextmanager
import time

import httpx

_healthy_until = 0.0


def available():
    return time.monotonic() < _healthy_until


@asynccontextmanager
async def worker():
    global _healthy_until
    stop=asyncio.Event()
    async def refresh():
        global _healthy_until
        from .ai_chat import ORIGIN,key
        async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
            while not stop.is_set():
                healthy=False
                credential=await asyncio.to_thread(key)
                if credential:
                    try:
                        response=await client.get(ORIGIN+'/v1/models',headers={'Authorization':'Bearer '+credential})
                        healthy=response.is_success
                    except httpx.HTTPError:
                        pass
                _healthy_until=time.monotonic()+20 if healthy else 0
                try:
                    await asyncio.wait_for(stop.wait(),15)
                except asyncio.TimeoutError:
                    pass
    task=asyncio.create_task(refresh())
    try:
        yield
    finally:
        stop.set()
        await task
        _healthy_until=0
