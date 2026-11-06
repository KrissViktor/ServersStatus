from types import SimpleNamespace
import unittest
from unittest.mock import patch
from agent.linux_inventory import systemd_services,discover_services
from agent.metrics import extended_metrics
from server.dashboard import cpu_description,memory_description
from server.metrics_ui import rdp_section

class LinuxAgentTest(unittest.TestCase):
    def test_systemd_read_only_batch_and_injection_filter(self):
        calls=[]
        def execute(args,**kwargs):
            calls.append(args)
            return SimpleNamespace(stdout='Id=nginx.service\nLoadState=loaded\nActiveState=active\nDescription=Web server\n\nId=missing.service\nLoadState=not-found\nActiveState=inactive\n')
        result=systemd_services(['nginx','missing.service','--bad','nginx;touch /tmp/bad'],execute)
        self.assertEqual([s['name'] for s in result],['nginx.service','missing.service'])
        self.assertEqual([s['status'] for s in result],['running','unavailable'])
        self.assertIn('--',calls[0])
        self.assertNotIn('--bad',calls[0])

    def test_systemd_discovery_and_failure(self):
        def execute(args,**kwargs):
            if args[1]=='list-unit-files':
                return SimpleNamespace(stdout='mssql-server.service enabled\nsrv1cv8-83.service enabled\nnginx.service enabled\n')
            return SimpleNamespace(stdout='Id=mssql-server.service\nLoadState=loaded\nActiveState=failed\n\nId=srv1cv8-83.service\nLoadState=loaded\nActiveState=active\n')
        found=discover_services(execute)
        self.assertEqual([s['kind'] for s in found],['SQL','1C'])
        self.assertEqual(found[0]['status'],'failed')
        def fail(*args,**kwargs):raise OSError()
        self.assertEqual(systemd_services(['nginx'],fail)[0]['status'],'unavailable')

    def test_memory_and_cpu_frequency_labels(self):
        data={'system':{'memory_total_bytes':16*1024**3,'memory_used_bytes':6*1024**3,'cpu_current_mhz':3200,'os':'Linux'}}
        self.assertEqual(memory_description(data),'6.0 Гб / 16.0 Гб · занято / всего')
        self.assertEqual(cpu_description(data),'3.20 ГГц · частота ОС')
        self.assertEqual(rdp_section(data),'')
        self.assertEqual(cpu_description({}),'Частота недоступна')
