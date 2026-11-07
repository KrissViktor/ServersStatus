import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from agent import windows_management as wm


class WindowsManagementAgentTest(unittest.TestCase):
    def test_registry_missing_denied_and_positive(self):
        class Registry:
            HKEY_LOCAL_MACHINE=0;KEY_READ=1;KEY_WOW64_64KEY=2
            OpenKey=staticmethod(lambda *a: (_ for _ in ()).throw(FileNotFoundError()))
        self.assertIs(wm.reboot_state(Registry)['reboot_required'],False)
        Registry.OpenKey=staticmethod(lambda *a: (_ for _ in ()).throw(PermissionError()))
        self.assertIsNone(wm.reboot_state(Registry)['reboot_required'])
        class Key:
            def __enter__(self):return self
            def __exit__(self,*args):pass
        Registry.OpenKey=staticmethod(lambda *a: Key())
        Registry.QueryValueEx=staticmethod(lambda *a:(['file'],0))
        self.assertTrue(wm.reboot_state(Registry)['reboot_required'])
        self.assertEqual(len(wm.reboot_state(Registry)['reboot_reasons']),3)

    def test_commands_are_fixed_and_reboot_has_delay(self):
        with patch('agent.windows_management.subprocess.run',return_value=SimpleNamespace(returncode=0)) as run:
            wm.execute('reboot');args=run.call_args.args[0]
            self.assertIn('/r',args);self.assertEqual(args[args.index('/t')+1],'300')
            wm.execute('cancel_reboot');self.assertEqual(run.call_args.args[0][-1],'/a')
            with self.assertRaises(ValueError):wm.execute('cmd.exe /c anything')
        with patch('agent.windows_management.powershell',return_value={}) as powershell:
            wm.execute('install');powershell.assert_called_once_with('install',timeout=7200)

    def test_durable_execution_and_crash_do_not_repeat(self):
        config={'agent_id':'pc','token':'key','allow_windows_management':True}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'job':{'id':1,'action':'scan','expires':time.time()+60}}).encode()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json'
            with patch('agent.windows_management.request',return_value=Response()),patch('agent.windows_management.acknowledge') as ack,patch('agent.windows_management.execute',return_value={'count':0}) as execute:
                wm._handle(config,path);wm._handle(config,path)
                self.assertEqual(execute.call_count,1)
                record=Path(str(path)+'.windows-command.json')
                record.write_text(json.dumps({'id':2,'status':'running','result':{},'pending':True}))
                wm._handle(config,path)
                self.assertTrue(any(call.args[1].get('status')=='uncertain' for call in ack.call_args_list))
                self.assertEqual(execute.call_count,1)  # Older IDs cannot replay after recovery.

    def test_rejected_acceptance_and_local_opt_out_do_not_execute(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'job':{'id':1,'action':'reboot','expires':time.time()+60}}).encode()
        with tempfile.TemporaryDirectory() as directory,patch('agent.windows_management.request',return_value=Response()),patch('agent.windows_management.acknowledge',side_effect=OSError()),patch('agent.windows_management.execute') as execute:
            wm._handle({},Path(directory)/'config.json');execute.assert_not_called()
        with patch('agent.windows_management.threading.Thread') as thread:
            wm.handle({'allow_windows_management':False},'config.json');thread.assert_not_called()
