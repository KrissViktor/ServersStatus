"""Validate the staged systemd override without touching system services."""
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
BLOCKS=re.findall(r"<<'PY'\n(.*?)\nPY",(ROOT/'deploy/upgrade-portal-python.sh').read_text(),re.S)


class PortalRuntimeTest(unittest.TestCase):
    def test_all_embedded_python_blocks_compile(self):
        self.assertEqual(len(BLOCKS),2)
        for block in BLOCKS:compile(block,'upgrade-portal-python.sh','exec')

    def stage(self,arguments):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'runtime.conf'
            definition='{ path=/opt/ServersStatus/.venv/bin/python ; argv[]='+arguments+' ; ignore_errors=no ; start_time=[n/a] ; }'
            with patch.object(sys,'argv',['runtime','/opt/ServersStatus/.portal-313/bin/python','serversstatus.service',str(output)]),patch('subprocess.check_output',return_value=definition):
                exec(compile(BLOCKS[1],'upgrade-portal-python.sh','exec'),{})
            return output.read_text()

    def test_only_the_interpreter_changes_and_all_uvicorn_arguments_are_preserved(self):
        previous='/opt/ServersStatus/.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --limit-concurrency 32 --no-proxy-headers'
        staged=self.stage(previous)
        self.assertIn('[Service]\nExecStart=\n',staged)
        args=shlex.split(staged.splitlines()[-1].removeprefix('ExecStart='))
        self.assertEqual(args[0],'/opt/ServersStatus/.portal-313/bin/python')
        self.assertEqual(args[1:],shlex.split(previous)[1:])

    def test_nonstandard_service_is_rejected_before_any_override_is_written(self):
        for command in ['python -m otherapp --host 127.0.0.1 --port 8000','python -m uvicorn server.app:app --host 0.0.0.0 --port 8000','python -m uvicorn server.app:app --host 127.0.0.1 --port 9000','python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --workers $WORKERS']:
            with self.assertRaises(SystemExit):self.stage(command)
