import unittest
from unittest.mock import patch
from server.host_monitor import enrich_host


class HostTemperaturesTest(unittest.TestCase):
    def enrich(self, data, temperature):
        with patch('server.host_monitor.temperature', return_value=temperature), patch('server.host_monitor.database_size', return_value=42):
            return enrich_host(data, 'unused.sqlite3')

    def test_soc_fallback_is_shared_with_cards_and_snapshots(self):
        result = self.enrich({'features':['cpu_per_core_v1','temperature_sensors_v1'],
                             'temperatures':{'status':'unavailable','items':[]}}, 53.25)
        self.assertEqual(result['temperatures']['items'][0]['current'], 53.25)
        self.assertEqual(result['portal']['temperature_c'], 53.25)
        self.assertEqual(result['temperatures']['status'], 'available')
        self.assertIn('cpu_per_core_v1', result['features'])
        self.assertIn('temperature_sensors_v1', result['features'])
        self.assertIn('host_monitor_v1', result['features'])
        self.assertEqual(result['portal']['database_bytes'], 42)

    def test_existing_linux_sensors_are_preserved_without_duplicates(self):
        sensors={'status':'available','sampled_at':123,'items':[{'id':'cpu_thermal:0','current':50}]}
        result=self.enrich({'temperatures':sensors,'features':['host_monitor_v1']},50)
        self.assertEqual(result['temperatures'],sensors)
        self.assertEqual(result['features'].count('host_monitor_v1'),1)

    def test_missing_soc_never_becomes_zero(self):
        result=self.enrich({'temperatures':{'status':'unavailable','items':[]}},None)
        self.assertEqual(result['temperatures']['items'],[])
        self.assertIsNone(result['portal']['temperature_c'])
