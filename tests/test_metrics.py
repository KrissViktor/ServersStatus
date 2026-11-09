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

class PerCoreCpuTest(unittest.TestCase):
    def test_one_interval_and_separate_per_cpu_samples(self):
        from unittest.mock import patch,call
        from agent.metrics import sample_cpu
        with patch('agent.metrics.psutil.cpu_percent',side_effect=[[0,0,0],50,[10,80,float('nan')]]) as read:
            self.assertEqual(sample_cpu(),(50,[10.0,80.0,None]))
            self.assertEqual(read.call_args_list,[call(interval=None,percpu=True),call(interval=1),call(interval=None,percpu=True)])
    def test_optional_per_cpu_failure_does_not_break_total(self):
        from unittest.mock import patch
        from agent.metrics import sample_cpu
        with patch('agent.metrics.psutil.cpu_percent',side_effect=[OSError('no per cpu'),25]):self.assertEqual(sample_cpu(),(25,[]))


class ProcessorNameTest(unittest.TestCase):
    def test_windows_brand_from_registry(self):
        from unittest.mock import MagicMock, patch
        from agent.metrics import processor_name
        registry = MagicMock()
        registry.QueryValueEx.return_value = ('  AMD Ryzen 5 5600  6-Core Processor  ', 1)
        with patch('agent.metrics.platform.system', return_value='Windows'), patch.dict('sys.modules', winreg=registry):
            self.assertEqual(processor_name(), 'AMD Ryzen 5 5600 6-Core Processor')
        registry.QueryValueEx.assert_called_once_with(registry.OpenKey.return_value.__enter__.return_value, 'ProcessorNameString')

    def test_windows_missing_brand_falls_back(self):
        from unittest.mock import MagicMock, patch
        from agent.metrics import processor_name
        registry = MagicMock()
        registry.OpenKey.side_effect = OSError('Unavailable')
        with patch('agent.metrics.platform.system', return_value='Windows'), patch('agent.metrics.platform.processor', return_value='AMD64 fallback'), patch.dict('sys.modules', winreg=registry):
            self.assertEqual(processor_name(), 'AMD64 fallback')

    def test_linux_model_name(self):
        from unittest.mock import mock_open, patch
        from agent.metrics import processor_name
        with patch('agent.metrics.platform.system', return_value='Linux'), patch('builtins.open', mock_open(read_data='processor : 0\nmodel name : Intel(R) Xeon(R) CPU\n')):
            self.assertEqual(processor_name(), 'Intel(R) Xeon(R) CPU')
