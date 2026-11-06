from types import SimpleNamespace
import unittest
from agent.metrics import rates, counters, extended_metrics


class MetricsTest(unittest.TestCase):
    def test_rates_interval_reset_and_new_interface(self):
        before = {'time': 10, 'network': {'eth': SimpleNamespace(bytes_recv=100, bytes_sent=200)}}
        after = {'time': 12, 'network': {'eth': SimpleNamespace(bytes_recv=300, bytes_sent=100), 'new': SimpleNamespace(bytes_recv=500, bytes_sent=500)}}
        fields = {'bytes_recv': 'rx', 'bytes_sent': 'tx'}
        result = rates(before, after, 'network', fields)
        self.assertEqual(result, {'eth': {'rx': 100, 'tx': None}})
        after['time'] = 10
        self.assertEqual(rates(before, after, 'network', fields), {})

    def test_live_inventory_and_optional_counters(self):
        sample = counters()
        data = extended_metrics(sample, sample)
        self.assertGreater(data['system']['memory_total_bytes'], 0)
        self.assertIn('version', data['system'])
        self.assertEqual(data['disk_io'], [])
        self.assertIsInstance(data['network'], list)
