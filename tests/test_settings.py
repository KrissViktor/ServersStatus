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
            with patch('agent.service_inventory.handle'),patch('agent.client.collect', return_value={'hostname': 'pc'}) as collect, patch('agent.client.urllib.request.urlopen', return_value=Response()):
                run(path, Stop())
            self.assertEqual(collect.call_args_list[0].args[0]['services'], ['old'])
            self.assertEqual(collect.call_args_list[1].args[0]['services'], ['SQL'])
            self.assertEqual(json.loads(path.read_text())['token'], 'keep')
            self.assertEqual(load_cache(str(path) + '.remote.json')['revision'], 55)

    def test_server_interval_overrides_old_minute_config_and_accounts_for_collection(self):
        from unittest.mock import patch
        from agent.client import run
        class Stop:
            def __init__(self):self.waits=[]
            def is_set(self):return len(self.waits)>=2
            def wait(self,delay):self.waits.append(delay)
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,maximum):
                return json.dumps({'ok':True,'report_interval_seconds':10}).encode()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            path.write_text(json.dumps({'server_url':'https://example.com','agent_id':'pc','token':'keep','interval_seconds':60}))
            stop=Stop()
            with patch('agent.service_inventory.handle'),patch('agent.client.collect',return_value={'hostname':'pc'}),patch('agent.client.urllib.request.urlopen',return_value=Response()),patch('agent.client.time.monotonic',side_effect=[100,102,110,112]):
                run(path,stop)
            self.assertEqual(stop.waits,[8,8])

    def test_process_upload_carries_exact_report_reference(self):
        from unittest.mock import patch
        from agent.client import run
        requests=[]
        class Stop:
            def __init__(self):self.done=False
            def is_set(self):return self.done
            def wait(self,delay):self.done=True
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,maximum):return json.dumps({'ok':True,'report_id':123,'report_received':1700000000.5}).encode()
        def upload(request,*args,**kwargs):
            requests.append(request);return Response()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_text(json.dumps({'server_url':'https://example.com','agent_id':'pc','token':'key'}))
            with patch('agent.service_inventory.handle'),patch('agent.client.collect',return_value={'hostname':'pc'}),patch('agent.processes.begin',return_value={}),patch('agent.processes.finish',return_value={'status':'available','items':[]}),patch('agent.client.urllib.request.urlopen',side_effect=upload):
                run(path,Stop())
        process=next(request for request in requests if '/api/processes/' in request.full_url)
        self.assertEqual(json.loads(process.data)['report_id'],123)
        self.assertEqual(json.loads(process.data)['report_received'],1700000000.5)
