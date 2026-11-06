from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from agent.updater import update_service


class UpdaterTest(unittest.TestCase):
    def test_update_preserves_configuration_on_any_host(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / 'ServersStatusService.exe'
            installed.write_bytes(b'old')
            source = root / 'new.exe'
            source.write_bytes(b'new')
            config = root / 'config.json'
            config.write_text('{"token":"keep","backups":[1]}')
            def command(*args, **kwargs):
                return SimpleNamespace(returncode=0, stderr='', stdout='')
            with patch('agent.updater.time.sleep'):
                backup = update_service(command, root, source)
            self.assertEqual(installed.read_bytes(), b'new')
            self.assertEqual(backup.read_bytes(), b'old')
            self.assertEqual(config.read_text(), '{"token":"keep","backups":[1]}')

    def test_failed_start_restores_old_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / 'ServersStatusService.exe'
            installed.write_bytes(b'old')
            source = root / 'new.exe'
            source.write_bytes(b'new')
            starts = 0
            def command(*args, **kwargs):
                nonlocal starts
                if args[:2] == ('sc.exe', 'start'):
                    starts += 1
                    if starts == 1:
                        raise subprocess.CalledProcessError(1, 'sc start')
                return SimpleNamespace(returncode=0, stderr='', stdout='')
            with self.assertRaisesRegex(RuntimeError, 'Предыдущий EXE восстановлен'):
                update_service(command, root, source)
            self.assertEqual(installed.read_bytes(), b'old')
            self.assertEqual(starts, 2)
