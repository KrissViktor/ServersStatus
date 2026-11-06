import json
from pathlib import Path
import tempfile
import unittest
from agent.settings import effective_config, save_cache, load_cache, validate_remote


class AgentSettingsTest(unittest.TestCase):
    def test_cache_and_local_fallback_preserve_credentials(self):
        local = {'server_url': 'https://example.com', 'token': 'secret', 'backups': [{'path': 'local'}], 'services': ['local']}
        remote = {'revision': 123, 'settings': {'backups': [], 'services': ['MSSQLSERVER']}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'remote.json'
            self.assertEqual(load_cache(path)['revision'], 0)
            save_cache(path, remote)
            effective = effective_config(local, load_cache(path))
            self.assertEqual(effective['token'], 'secret')
            self.assertEqual(effective['services'], ['MSSQLSERVER'])
            self.assertEqual(effective['backups'], [])
            save_cache(path, {'revision': 0, 'settings': None})
            self.assertEqual(effective_config(local, load_cache(path)), local)
            path.write_text('broken')
            self.assertEqual(load_cache(path)['revision'], 0)

    def test_reject_configuration_outside_monitoring(self):
        with self.assertRaises(ValueError):
            validate_remote({'revision': 1, 'settings': {'backups': [], 'services': [], 'token': 'replace'}})
        with self.assertRaises(ValueError):
            validate_remote({'revision': 1, 'settings': {'backups': [{'path': 'x'}], 'services': []}})

    def test_reporting_loop_applies_settings_next_cycle(self):
        from unittest.mock import patch
        from agent.client import run
        class Stop:
            count = 0
            def is_set(self):
                return self.count >= 2
            def wait(self, seconds):
                self.count += 1
        class Response:
            status = 200
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, maximum):
                return json.dumps({'ok': True, 'monitoring': {'revision': 55, 'settings': {'services': ['SQL'], 'backups': []}}}).encode()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(json.dumps({'server_url': 'https://example.com', 'agent_id': 'pc', 'token': 'keep', 'services': ['old']}))
            with patch('agent.client.collect', return_value={'hostname': 'pc'}) as collect, patch('agent.client.urllib.request.urlopen', return_value=Response()):
                run(path, Stop())
            self.assertEqual(collect.call_args_list[0].args[0]['services'], ['old'])
            self.assertEqual(collect.call_args_list[1].args[0]['services'], ['SQL'])
            self.assertEqual(json.loads(path.read_text())['token'], 'keep')
            self.assertEqual(load_cache(str(path) + '.remote.json')['revision'], 55)
