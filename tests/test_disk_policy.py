import json
import unittest
from server.disks import monitored_disks
from server.dashboard import dashboard,server_card
from server.overview import issues
from server.incidents import evaluate
from server.bot_reports import status_report,warning_report

class DiskPolicyTest(unittest.TestCase):
    def report(self,used=58.4):
        return {'hostname':'LINUX','system':{'os':'Linux'},'cpu_percent':1,'memory_percent':2,
                'disks':[{'path':'/','free_bytes':38*1024**3,'total_bytes':90*1024**3,'used_percent':used},
                         {'path':'/var/lib/snapd/snap/core/1','free_bytes':0,'used_percent':100},
                         {'path':'/tmp','free_bytes':38*1024**3,'used_percent':58.4}]}

    def test_only_root_for_linux_and_windows_unchanged(self):
        report=self.report()
        self.assertEqual([d['path'] for d in monitored_disks(report)],['/'])
        windows={'system':{'os':'Windows'},'disks':[{'path':'C:\\'},{'path':'D:\\'}]}
        self.assertEqual(monitored_disks(windows),windows['disks'])
        self.assertEqual(monitored_disks({'system':{'os':'Linux'},'disks':[{'path':'/tmp'}]}),[])

    def test_old_snapshots_filtered_in_ui_bot_and_incidents(self):
        report=self.report()
        row={'id':'linux','display_name':None,'received':1000,'data':json.dumps(report)}
        self.assertEqual(issues(row,1000),[])
        self.assertEqual(evaluate([row],[],1000,disk_threshold=98)[0],{})
        for markup in (server_card(row,1000),'\n'.join(status_report([row],1000)),'\n'.join(warning_report([row],1000))):
            self.assertNotIn('/var/lib/snapd',markup)
            self.assertNotIn('/tmp',markup)
        self.assertIn('38.0 Гб',server_card(row,1000))
        report['disks'][0]['used_percent']=99
        row['data']=json.dumps(report)
        self.assertEqual(len(evaluate([row],[],1000,disk_threshold=98)[0]),1)

    def test_offline_linux_drops_obsolete_snap_incidents_silently(self):
        from server.incidents import disk_key
        row={'id':'linux','received':1000,'data':json.dumps(self.report())}
        old_key=disk_key('linux','/var/lib/snapd/snap/core/1')
        old=[{'key':old_key,'agent':'linux'}]
        _,valid,_=evaluate([row],old,1300,disk_threshold=98)
        self.assertNotIn(old_key,valid)

    def test_linux_agent_does_not_measure_snap_or_bind_mounts(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch
        from agent.client import collect
        if not sys.platform.startswith('linux'):self.skipTest('Linux collector test')
        partitions=[SimpleNamespace(mountpoint=path,device='device',fstype='ext4') for path in ('/','/var/lib/snapd/snap/core/1','/tmp')]
        usage=SimpleNamespace(free=38*1024**3,total=90*1024**3,percent=58.4)
        with patch('agent.client.psutil.disk_partitions',return_value=partitions),patch('agent.client.psutil.disk_usage',return_value=usage) as measured,patch('agent.client.psutil.cpu_percent',return_value=1),patch('agent.client.discover_linux_services',return_value=[]):
            report=collect({}, {})
        self.assertEqual([disk['path'] for disk in report['disks']],['/'])
        measured.assert_called_once_with('/')
