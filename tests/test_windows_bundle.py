import unittest
from agent.check_windows_bundle import validate_entries


class WindowsBundleTest(unittest.TestCase):
    def test_native_probe_required(self):
        validate_entries(['agent/temperature_sensors.ps1','python312.dll'])
        with self.assertRaises(ValueError):validate_entries(['python312.dll'])

    def test_forbidden_payloads_rejected_case_insensitively(self):
        for entry in ['agent/hardware-monitor-bin/helper.exe','PawnIO_setup.exe',
                      'agent/LibreHardwareMonitorLib.dll','agent/install_sensor_driver.ps1',
                      'OPENHARDWAREMONITOR.dll']:
            with self.subTest(entry=entry),self.assertRaises(ValueError):
                validate_entries(['agent/temperature_sensors.ps1',entry])
