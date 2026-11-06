"""Linux entry point with graceful systemd shutdown."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal
import sys
import threading
from agent.client import run


def main():
    config=Path(sys.argv[1])
    stop=threading.Event()
    def shutdown(signum,frame):
        stop.set()
    signal.signal(signal.SIGTERM,shutdown)
    signal.signal(signal.SIGINT,shutdown)
    handler=RotatingFileHandler(config.with_name('agent.log'),maxBytes=1024**2,backupCount=3,encoding='utf-8')
    logging.basicConfig(level=logging.INFO,handlers=[handler,logging.StreamHandler()])
    run(config,stop)


if __name__=='__main__':
    main()
