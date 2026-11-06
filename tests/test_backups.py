from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from agent.backups import inspect_backup


class BackupScheduleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.rule = {'path': str(self.root), 'pattern': 'ERP_backup_*.bak', 'schedule': 'monthly', 'recursive': True, 'date_from_filename': True, 'grace_hours': 36}
        self.previous = {}

    def create(self, date):
        folder = self.root / date[:7]
        folder.mkdir(exist_ok=True)
        path = folder / ('ERP_backup_' + date + '_003723_2684907.bak')
        path.write_bytes(b'backup')
        return path

    def inspect(self, date):
        return inspect_backup(self.rule, self.previous, datetime.fromisoformat(date).timestamp())

    def test_month_rollover_and_grace(self):
        self.create('2026_10_01')
        self.assertEqual(self.inspect('2026-11-01T10:00:00')['state'], 'observing')
        self.assertEqual(self.inspect('2026-11-01T10:00:00')['state'], 'fresh')
        self.assertEqual(self.inspect('2026-11-02T12:00:00')['state'], 'stale')
        self.create('2026_11_01')
        self.assertEqual(self.inspect('2026-11-06T10:00:00')['state'], 'observing')
        self.assertEqual(self.inspect('2026-11-06T10:00:00')['state'], 'fresh')

    def test_filename_over_mtime_and_daily(self):
        self.rule.update(schedule='daily', max_age_hours=26)
        self.create('2026_11_04')  # Newly copied file, but old backup date.
        self.inspect('2026-11-06T10:00:00')
        self.assertEqual(self.inspect('2026-11-06T10:00:00')['state'], 'stale')
        self.create('2026_11_06')
        self.inspect('2026-11-06T10:00:00')
        self.assertEqual(self.inspect('2026-11-06T10:00:00')['state'], 'fresh')

    def test_missing_error_and_empty(self):
        self.assertEqual(self.inspect('2026-11-06T10:00:00')['state'], 'missing')
        path = self.create('2026_11_01')
        path.write_bytes(b'')
        self.assertEqual(self.inspect('2026-11-06T10:00:00')['state'], 'empty')
        self.rule['path'] += '/not-present'
        self.assertEqual(self.inspect('2026-11-06T10:00:00')['state'], 'error')

    def test_january_and_future(self):
        self.create('2025_12_01')
        self.inspect('2026-01-01T10:00:00')
        self.assertEqual(self.inspect('2026-01-01T10:00:00')['state'], 'fresh')
        self.create('2026_02_01')
        self.assertEqual(self.inspect('2026-01-06T10:00:00')['state'], 'future')
