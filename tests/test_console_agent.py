import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from agent import console


class ConsoleAgentTest(unittest.TestCase):
    def test_real_command_exit_output_and_cap(self):
        with tempfile.TemporaryDirectory() as cwd:
            command="Write-Output 'hello'; exit 7" if os.name=='nt' else "printf 'hello'; exit 7"
            result=console.execute(command,5,cwd)
            self.assertEqual(result['status'],'failed');self.assertEqual(result['exit_code'],7);self.assertIn('hello',result['output'])
            command="Write-Output ('x'*30000)" if os.name=='nt' else "printf '%030000d' 1"
            result=console.execute(command,5,cwd)
            self.assertEqual(result['status'],'succeeded');self.assertTrue(result['truncated']);self.assertEqual(len(result['output']),16384)

    def test_multiline_block_shares_shell_state(self):
        command="$value='shared'\nWrite-Output ('first '+$value)\nWrite-Output ('second '+$value)" if os.name=='nt' else "value=shared\nprintf 'first %s\\n' \"$value\"\nprintf 'second %s\\n' \"$value\""
        with tempfile.TemporaryDirectory() as cwd:result=console.execute(command,5,cwd)
        self.assertEqual(result['status'],'succeeded')
        self.assertIn('first shared',result['output']);self.assertIn('second shared',result['output'])

    def test_real_timeout(self):
        with tempfile.TemporaryDirectory() as cwd:
            command='Start-Sleep -Seconds 20' if os.name=='nt' else 'sleep 20'
            started=time.monotonic();result=console.execute(command,1,cwd)
            self.assertEqual(result['status'],'timeout');self.assertLess(time.monotonic()-started,10)

    def test_opt_out_and_durable_at_most_once(self):
        with patch('agent.console.threading.Thread') as thread:
            console.handle({},'config.json');thread.assert_not_called()
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'job':{'id':1,'command':'whoami','timeout':10,'expires':time.time()+60}}).encode()
        with tempfile.TemporaryDirectory() as directory,patch('agent.console.request',return_value=Response()),patch('agent.console.ack') as ack,patch('agent.console.execute',return_value={'status':'succeeded','output':'user','exit_code':0,'truncated':False}) as execute:
            path=Path(directory)/'config.json'
            console.worker({'agent_id':'pc'},path);console.worker({'agent_id':'pc'},path)
            self.assertEqual(execute.call_count,1)
            (Path(str(path)+'.console-job.json')).write_text(json.dumps({'id':2,'status':'running','pending':True}))
            console.worker({'agent_id':'pc'},path)
            self.assertEqual(execute.call_count,1)
            self.assertTrue(any(call.args[1]['status']=='uncertain' for call in ack.call_args_list))

    def test_rejected_acceptance_never_executes(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'job':{'id':1,'command':'whoami','timeout':10,'expires':time.time()+60}}).encode()
        with tempfile.TemporaryDirectory() as directory,patch('agent.console.request',return_value=Response()),patch('agent.console.ack',side_effect=OSError()),patch('agent.console.execute') as execute:
            console.worker({'agent_id':'pc'},Path(directory)/'config.json');execute.assert_not_called()

    def test_output_arrives_before_command_finishes(self):
        seen=[]
        with tempfile.TemporaryDirectory() as cwd:
            command="[Console]::WriteLine('first'); Start-Sleep -Seconds 2; [Console]::WriteLine('second')" if os.name=='nt' else "printf 'first\\n'; sleep 2; printf 'second\\n'"
            result=console.execute(command,10,cwd,progress=lambda value:seen.append(dict(value)))
        self.assertEqual(result['status'],'succeeded')
        self.assertTrue(any('first' in value['output'] and 'second' not in value['output'] for value in seen))
        self.assertIn('second',result['output'])

    def test_unicode_answer_to_running_prompt(self):
        controls=console.ControlChannel();sent=False
        command="$name=Read-Host 'Name';[Console]::WriteLine('Hello '+$name)" if os.name=='nt' else "printf 'Name: '; IFS= read -r name; printf 'Hello %s' \"$name\""
        def progress(value):
            nonlocal sent
            if not sent and 'Name:' in value['output']:
                controls.put_nowait({'action':'stdin','text':'Виктор'});sent=True
        with tempfile.TemporaryDirectory() as cwd:result=console.execute(command,10,cwd,progress=progress,controls=controls)
        self.assertTrue(sent);self.assertEqual(result['status'],'succeeded');self.assertIn('Hello Виктор',result['output'])

    def test_eof_and_cancel(self):
        controls=console.ControlChannel()
        controls.put_nowait({'action':'stdin','text':'answer'});controls.put_nowait({'action':'eof'})
        command='[Console]::Write([Console]::In.ReadToEnd())' if os.name=='nt' else 'cat'
        with tempfile.TemporaryDirectory() as cwd:result=console.execute(command,10,cwd,controls=controls)
        self.assertEqual(result['status'],'succeeded');self.assertIn('answer',result['output'])
        controls=console.ControlChannel();controls.put_nowait({'action':'cancel'})
        command='Start-Sleep -Seconds 20' if os.name=='nt' else 'sleep 20'
        with tempfile.TemporaryDirectory() as cwd:
            before=time.monotonic();result=console.execute(command,10,cwd,controls=controls)
        self.assertEqual(result['status'],'cancelled');self.assertLess(time.monotonic()-before,5)
