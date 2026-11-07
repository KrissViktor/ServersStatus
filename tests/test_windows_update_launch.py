import json
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agent.remote_update import launch_windows


class WindowsLaunchTest(unittest.TestCase):
    def test_helper_launched_without_service_stdio_and_without_token_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'agent_id':'pc','token':'SECRET'};path=Path(directory)/'config.json'
            job={'id':1,'platform':'windows-x64','version':'v2','sha256':'0'*64,'size':1}
            with patch('agent.remote_update.acknowledge'),patch('agent.remote_update.download'),patch('agent.remote_update.subprocess.Popen') as popen:
                popen.return_value.wait.side_effect=subprocess.TimeoutExpired('powershell',1)
                popen.return_value.poll.return_value=None
                launch_windows(config,path,job)
                launch_windows(config,path,job)
            self.assertEqual(popen.call_count,1)
            kwargs=popen.call_args.kwargs
            self.assertIn('stdin',kwargs);self.assertIn('stdout',kwargs);self.assertIn('stderr',kwargs)
            self.assertTrue(popen.call_args.args[0][0].endswith('powershell.exe'))
            manifest=(Path(directory)/'updates/1/manifest.json').read_text()
            self.assertNotIn('SECRET',manifest)
            self.assertEqual(json.loads(manifest)['job_id'],1)

    def test_download_failure_reports_stage_without_touching_service(self):
        with tempfile.TemporaryDirectory() as directory,patch('agent.remote_update.download',side_effect=ValueError('bad SHA256')),patch('agent.remote_update.acknowledge') as ack,patch('agent.remote_update.subprocess.Popen') as popen:
            job={'id':1,'platform':'windows-x64','version':'v2','sha256':'0'*64,'size':1}
            with self.assertRaises(ValueError):launch_windows({'agent_id':'pc'},Path(directory)/'config.json',job)
            self.assertEqual(ack.call_args.kwargs['error_code'],'download');popen.assert_not_called()

    def test_early_powershell_exit_is_reported_without_waiting_15_minutes(self):
        with tempfile.TemporaryDirectory() as directory,patch('agent.remote_update.download'),patch('agent.remote_update.acknowledge') as ack,patch('agent.remote_update.subprocess.Popen') as popen:
            popen.return_value.wait.return_value=1
            job={'id':101,'platform':'windows-x64','version':'v2','sha256':'0'*64,'size':1}
            with self.assertRaises(RuntimeError):launch_windows({'agent_id':'pc'},Path(directory)/'config.json',job)
            self.assertEqual(ack.call_args.kwargs['error_code'],'helper_startup')
            folder=Path(directory)/'updates/101'
            self.assertTrue((folder/'helper-launch.log').exists())
            self.assertFalse((folder/'requested').exists())
