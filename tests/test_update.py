import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from tools import update
from swiss_iptv.locking import update_lock


class UpdateContextTests(unittest.TestCase):
    def setUp(self):
        self.previous = Path.cwd()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'data').mkdir()
        (self.root / 'config.yaml').write_text('{}', encoding='utf-8')
        (self.root / 'data/domestic-reviews.yaml').write_text(yaml.safe_dump({'reviews': [
            {'source_id': 'fixture', 'decision': 'approved', 'scope': 'domestic_links'}]}), encoding='utf-8')

    def tearDown(self):
        os.chdir(self.previous)
        self.temp.cleanup()

    def test_foreign_connection_stops_before_catalogue_and_releases_lock(self):
        context = subprocess.CompletedProcess([], 0, json.dumps({'country': 'FR'}))
        with patch.object(update, 'ROOT', self.root), patch.object(update.subprocess, 'run', return_value=context), \
             patch.object(update, 'connect') as connector, patch.object(update, 'export_playlists') as exporter:
            with self.assertRaisesRegex(ValueError, 'Swiss playback is not assumed'):
                update.main()
        connector.assert_not_called()
        exporter.assert_not_called()
        with update_lock(self.root / 'data/update.lock'):
            pass  # A failed context check must release its OS lock.

    def test_existing_lock_prevents_parallel_run_and_is_preserved(self):
        with update_lock(self.root / 'data/update.lock'):
            with patch.object(update, 'ROOT', self.root), patch.object(update.subprocess, 'run') as runner:
                with self.assertRaisesRegex(ValueError, 'Another update'):
                    update.main()
        runner.assert_not_called()
        self.assertTrue((self.root / 'data/update.lock').exists())

    def test_lock_is_released_after_abrupt_process_exit(self):
        code = 'import os,sys; from swiss_iptv.locking import update_lock\nwith update_lock(sys.argv[1]): os._exit(0)'
        subprocess.run([sys.executable, '-c', code, str(self.root / 'data/update.lock')],
                       cwd=self.previous, check=True, capture_output=True, timeout=10)
        with update_lock(self.root / 'data/update.lock'):
            pass
