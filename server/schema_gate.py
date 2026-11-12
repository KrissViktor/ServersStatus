"""Initialize each SQLite schema once per file/schema revision, not per request."""
from collections import OrderedDict
from pathlib import Path
import threading
import time

_lock=threading.RLock()
_ready=OrderedDict()


def ensure(c,path,initialize,refresh):
    with _lock:
        file=Path(path)
        stat=file.stat() if file.exists() else None
        key=(str(file.resolve()),stat.st_dev,stat.st_ino) if stat else None
        version=c.execute('PRAGMA schema_version').fetchone()[0]
        previous=_ready.get(key) if key else None
        now=time.monotonic()
        if not previous or previous[0]!=version:
            initialize(c);c.commit()
            version=c.execute('PRAGMA schema_version').fetchone()[0]
        elif now-previous[1]>=60:
            refresh(c)
        else:
            _ready.move_to_end(key)
            return
        if key:
            _ready[key]=(version,now);_ready.move_to_end(key)
            while len(_ready)>64:_ready.popitem(last=False)
