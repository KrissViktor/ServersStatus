from types import SimpleNamespace
import math
import unittest
from unittest.mock import patch
from agent import temperatures as t

class TemperatureSensorsTest(unittest.TestCase):
    def test_linux_all_providers_thresholds_and_missing_values(self):
        sample={'coretemp':[SimpleNamespace(label='Package id 0',current=65.5,high=85,critical=100)],'nvme':[SimpleNamespace(label='Composite',current=42,high=None,critical=90)],'jc42':[SimpleNamespace(label='DIMM A1',current=None,high=85,critical=None)]}
        with patch.object(t.psutil,'sensors_temperatures',return_value=sample,create=True):result=t.linux_sensors()
        self.assertEqual(result['status'],'available');self.assertEqual(len(result['items']),3);self.assertEqual(result['items'][0]['current'],65.5);self.assertIsNone(result['items'][2]['current'])
        self.assertEqual(result['items'][1]['device'],'nvme');self.assertEqual(result['items'][0]['critical'],100)
    def test_sanitize_duplicate_nonfinite_and_invalid_acpi_not_zero(self):
        rows=[{'id':'CPU','label':'CPU','current':float('nan')},{'id':'CPU','current':5},{'id':'ACPI','current':-273.15},{'id':'cold','current':0},{'id':'high','current':300}]
        items=t.sanitize(rows);self.assertEqual(len(items),4);self.assertIsNone(items[0]['current']);self.assertIsNone(items[1]['current']);self.assertEqual(items[2]['current'],0);self.assertIsNone(items[3]['current'])
        self.assertEqual(len(t.sanitize([{'id':str(i),'current':10} for i in range(600)])),512)
    def test_unavailable_does_not_break_report(self):
        with patch.object(t.psutil,'sensors_temperatures',side_effect=OSError('no permission'),create=True):self.assertEqual(t.linux_sensors()['status'],'unavailable')
    def test_windows_probe_is_bounded_and_decodes_real_json(self):
        with patch('agent.temperatures.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='[{"id":"cpu","current":70,"source":"ACPI"}]')) as process:
            result=t.windows_probe();self.assertEqual(result['items'][0]['current'],70)
            self.assertEqual(process.call_args.kwargs['timeout'],9);self.assertIn('-NonInteractive',process.call_args.args[0]);self.assertTrue(process.call_args.args[0][-1].endswith('temperature_sensors.ps1'))
        with patch('agent.temperatures.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='broken')):
            with self.assertRaises(ValueError):t.windows_probe()

    def test_background_cache_is_nonblocking_and_old_readings_are_not_current(self):
        import time
        result={'status':'available','items':[{'id':'cpu','current':65}],'sampled_at':time.time()}
        with patch.object(t.os,'name','nt'),patch.object(t,'_busy',False),patch.object(t,'_next',0),patch.object(t,'_cached',{'status':'checking','items':[],'sampled_at':None}),patch.object(t,'windows_probe',return_value=result) as probe:
            t.collect_temperatures()
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                with t._lock:busy=t._busy
                if not busy:break
                time.sleep(.01)
            self.assertEqual(t.collect_temperatures()['status'],'available');self.assertEqual(probe.call_count,1)
        stale={**result,'sampled_at':time.time()-121}
        with patch.object(t.os,'name','nt'),patch.object(t,'_busy',False),patch.object(t,'_next',float('inf')),patch.object(t,'_cached',stale):
            self.assertEqual(t.collect_temperatures()['items'],[])
