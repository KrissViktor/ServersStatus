import json
import os
import subprocess
import unittest
from unittest.mock import patch
from agent import hardware
from server.hardware import HardwareInfo, summary
from server.app import Report


class HardwareTest(unittest.TestCase):
    def fixture(self):
        data = {kind: [] for kind in hardware.QUERIES}
        data.update(board=[{'Manufacturer': 'ASUS', 'Product': 'PRIME B550M-A', 'SerialNumber': 'Default string'}],
                    memory=[{'Capacity': 17179869184, 'SMBIOSMemoryType': 26, 'PartNumber': 'DIMM <script>'}],
                    bios=None)
        return data

    def test_schema_and_render_real_components_escaped(self):
        info = hardware.sanitize(self.fixture())
        HardwareInfo.model_validate(info)
        report = Report.model_validate({'hostname':'pc', 'cpu_percent':0, 'memory_percent':0, 'uptime_seconds':0, 'disks':[], 'hardware':info})
        self.assertEqual(report.model_dump()['hardware']['items'][0]['fields']['Product'], 'PRIME B550M-A')
        html = summary({'hardware':info})
        self.assertIn('PRIME B550M-A', html)
        self.assertIn('DDR4', html)
        self.assertIn('16.0', html)
        self.assertIn('DIMM &lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertIn('Сведения недоступны', html)
        self.assertNotIn('Default string', html)

    def test_payload_is_bounded(self):
        data = {kind: [{field: 'x'*1000 for field in fields} for _ in range(40)] for kind, (_, fields) in hardware.QUERIES.items()}
        info = hardware.sanitize(data)
        HardwareInfo.model_validate(info)
        self.assertTrue(info['truncated'])
        self.assertLess(len(json.dumps(info)), 11000)

    def test_failure_does_not_break_report_and_clears_busy(self):
        with patch.object(hardware, 'probe', side_effect=subprocess.TimeoutExpired('powershell',30)), patch.object(hardware,'_cached',{}), patch.object(hardware,'_busy',True):
            hardware._refresh()
            self.assertFalse(hardware._busy)
            self.assertEqual(hardware._cached['status'], 'unavailable')
            HardwareInfo.model_validate(hardware._cached)

    def test_background_cache_only_refreshes_once(self):
        with patch.object(hardware.os, 'name','nt'), patch.object(hardware,'_next',0), patch.object(hardware,'_busy',False), patch.object(hardware.threading,'Thread') as thread:
            hardware.inventory();hardware.inventory()
            self.assertEqual(thread.call_count, 1)
            thread.return_value.start.assert_called_once()

    def test_probe_uses_read_only_cim_and_timeout(self):
        from types import SimpleNamespace
        with patch.object(hardware.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(self.fixture()))) as run:
            HardwareInfo.model_validate(hardware.probe())
            args=run.call_args.args[0]
            self.assertIn('Get-CimInstance -ClassName Win32_BaseBoard', args[-1])
            self.assertNotIn('Set-CimInstance', args[-1])
            self.assertEqual(run.call_args.kwargs['timeout'],30)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows CIM only')
    def test_native_windows_hardware(self):
        info=hardware.probe()
        HardwareInfo.model_validate(info)
        self.assertEqual(info['status'],'available')
        self.assertTrue(any(item['kind']=='computer' for item in info['items']))
