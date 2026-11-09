"""Install from an elevated terminal; config is next to this file."""
import sys
import threading
import os
import logging
from logging.handlers import RotatingFileHandler
import servicemanager
from pathlib import Path

import win32service
import win32serviceutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.client import run


class ServersStatusService(win32serviceutil.ServiceFramework):
    _svc_name_ = 'ServersStatusAgent'
    _svc_display_name_ = 'ServersStatus Agent'
    _svc_description_ = 'Sends system metrics and backup file status over HTTPS.'

    def __init__(self, args):
        super().__init__(args)
        self.stop = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop.set()

    def SvcDoRun(self):
        if getattr(sys, 'frozen', False):
            data = Path(os.environ['ProgramData']) / 'ServersStatus'
            handler = RotatingFileHandler(data / 'agent.log', maxBytes=1024 * 1024, backupCount=3, encoding='utf-8')
            logging.basicConfig(level=logging.INFO, handlers=[handler])
            config = data / 'config.json'
        else:
            config = Path(__file__).with_name('config.json')
        run(config, self.stop)


if __name__ == '__main__':
    if sys.argv[1:]==['--sensor-self-test']:
        from agent.temperatures import bundle_self_test
        bundle_self_test()
        print('Hardware bundle OK')
        sys.exit(0)
    if getattr(sys, 'frozen', False):
        ServersStatusService._exe_name_ = sys.executable
    if len(sys.argv) == 1 and getattr(sys, 'frozen', False):
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ServersStatusService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ServersStatusService)
