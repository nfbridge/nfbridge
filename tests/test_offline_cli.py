# SPDX-License-Identifier: GPL-3.0-only
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / 'mac-client' / 'f100_readonly.py'

class OfflineCommandTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(CLIENT), *args], cwd=ROOT,
                              capture_output=True, text=True)

    def test_tables_missing_is_offline_report(self):
        with tempfile.TemporaryDirectory() as directory:
            for args in [('tables',), ('tables', '--table-dir', directory)]:
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(json.loads(result.stdout)['ok'])
                self.assertNotIn('--capture-dir', result.stderr)
                self.assertNotIn('Traceback', result.stderr)

    def test_invalid_fixtures_have_actionable_errors(self):
        for path in ['nonexistent-file.hex', 'mac-client/fixtures/negative/truncated_roll.hex']:
            result = self.run_cli('lq', '--fixture', path)
            self.assertEqual(result.returncode, 2)
            self.assertIn('No serial port was opened', result.stderr)
            self.assertNotIn('Traceback', result.stderr)
            self.assertEqual(result.stdout, '')

    def test_tables_valid_files_succeed_without_live_options(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ['shutter_speed', 'aperture', 'focal_length', 'ev_compensation']:
                (Path(directory) / ('lq_' + name + '_table.tsv')).write_text('raw_hex\traw_decimal\tdisplay\n0x00\t0\t0\n')
            result = self.run_cli('tables', '--table-dir', directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)['ok'])
