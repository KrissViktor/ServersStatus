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
        with patch('agent.temperatures.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='[{"id":"cpu","current":70,"source":"root\\\\LibreHardwareMonitor"}]')) as process:
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

    def test_bundled_probe_preferred_and_no_powershell_after_success(self):
        with patch.object(t.Path,'is_file',return_value=True),patch.object(t,'ensure_sensor_driver') as driver,patch.object(t.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='[{"id":"lhm:/intelcpu/0/temperature/0","current":62,"device":"CPU"}]')) as process:
            result=t.windows_probe()
        self.assertEqual(result['items'][0]['current'],62)
        self.assertEqual(process.call_count,1)
        self.assertTrue(process.call_args.args[0][0].endswith('ServersStatusHardwareMonitor.exe'))
        self.assertEqual(process.call_args.kwargs['timeout'],15)
        driver.assert_called_once()

    def test_native_failure_empty_and_unreadable_fall_back(self):
        import subprocess
        for failure in (None, RuntimeError('blocked'), subprocess.TimeoutExpired('probe',15)):
            with self.subTest(failure=failure),patch.object(t,'native_probe',side_effect=failure if failure else None,return_value=None),patch.object(t.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='[{"id":"acpi:0","current":45}]')) as process:
                self.assertEqual(t.windows_probe()['items'][0]['id'],'acpi:0')
                self.assertIn('-NonInteractive',process.call_args.args[0])
        with patch.object(t.Path,'is_file',return_value=True),patch.object(t,'ensure_sensor_driver'),patch.object(t.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='[{"id":"lhm:bad","current":999}]')):
            self.assertIsNone(t.native_probe())

    def test_native_disabled_never_installs_driver(self):
        with patch.dict(t.os.environ,{'STATUS_AGENT_HARDWARE_TEMPERATURES':'0'}),patch.object(t,'ensure_sensor_driver') as driver,patch.object(t.subprocess,'run') as process:
            self.assertIsNone(t.native_probe())
        driver.assert_not_called();process.assert_not_called()

    def test_driver_install_attempt_is_once_even_when_it_fails(self):
        with patch.object(t,'_driver_attempted',False),patch.object(t.subprocess,'run',side_effect=OSError('not elevated')) as process:
            t.ensure_sensor_driver();t.ensure_sensor_driver()
        self.assertEqual(process.call_count,1)
        self.assertEqual(process.call_args.kwargs['timeout'],80)
        self.assertTrue(process.call_args.args[0][-1].endswith('install_sensor_driver.ps1'))

    def test_frozen_bundle_self_test_never_installs_or_probes_hardware(self):
        with patch.object(t.Path,'is_file',return_value=True),patch.object(t,'ensure_sensor_driver') as driver,patch.object(t.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'[]\r\n')) as process:
            t.bundle_self_test()
        self.assertEqual(process.call_args.args[0][-1],'--self-test');driver.assert_not_called()
        with patch.object(t.Path,'is_file',return_value=False),patch.object(t.subprocess,'run') as process:
            with self.assertRaises(RuntimeError):t.bundle_self_test()
        process.assert_not_called()
