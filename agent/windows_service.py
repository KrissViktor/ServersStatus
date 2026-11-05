"""Install from an elevated terminal; config is next to this file."""
import sys
import threading
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
        run(Path(__file__).with_name('config.json'), self.stop)


if __name__ == '__main__':
    win32serviceutil.HandleCommandLine(ServersStatusService)
