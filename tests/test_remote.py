from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml

from swiss_iptv.catalog import connect, digest, now
from swiss_iptv.remote import PLAYLISTS, SITE_FILES, publish_site, repository_url, site_payload
from swiss_iptv.seed import seed_catalog


class RemotePublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.site = self.root / 'site'
        self.site.mkdir()
        self.status = {'audience': 'public', 'generated_at': now(), 'playlists': {name: 1 for name in PLAYLISTS}}
        self.write_site()

    def tearDown(self):
        self.temp.cleanup()

    def write_site(self):
        for name in PLAYLISTS:
            (self.site / (name + '.m3u')).write_text('#EXTM3U\n#EXTINF:-1 tvg-id="TV.ch",TV\nhttps://example.org/live.m3u8\n', encoding='utf-8')
        (self.site / 'index.html').write_text('<html lang="fr">Sources externes</html>', encoding='utf-8')
        (self.site / 'status.json').write_text(json.dumps(self.status), encoding='utf-8')

    def test_rejects_domestic_stale_or_inconsistent_exports_before_git(self):
        for change in [{'audience': 'domestic'}, {'generated_at': (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
                       {'playlists': {name: 0 for name in PLAYLISTS}}]:
            previous = self.status.copy()
            self.status.update(change)
            self.write_site()
            with patch('swiss_iptv.remote.subprocess.run') as runner:
                with self.assertRaises(ValueError):
                    publish_site(self.site, 'https://github.com/example/iptv.git', self.root / 'cache.git')
                runner.assert_not_called()
            self.status = previous

    def test_temporary_session_and_repository_credentials_rejected(self):
        for url in ['https://cdn.example.org/tok_session/live.m3u8', 'https://user:secret@example.org/live.m3u8',
                    'https://example.org/live.m3u8?token=secret', 'https://example.org/live.m3u8?session=secret']:
            (self.site / 'swiss-fr.m3u').write_text('#EXTM3U\n#EXTINF:-1,TV\n' + url + '\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                site_payload(self.site)
        for url in ['https://secret@github.com/owner/repo', 'file:///tmp/remote', 'https://github.com/owner/repo?token=secret']:
            with self.assertRaises(ValueError):
                repository_url(url)

    def test_real_git_push_excludes_private_files_and_preserves_history(self):
        if not shutil.which('git'):
            self.skipTest('Git not installed')
        origin = self.root / 'origin.git'
        subprocess.run(['git', 'init', '--bare', str(origin)], check=True, capture_output=True)
        (self.site / 'catalog.sqlite').write_bytes(b'PRIVATE DATABASE')
        (self.site / 'cookies.json').write_text('PRIVATE SESSION', encoding='utf-8')
        with patch('swiss_iptv.remote.repository_url', return_value=str(origin)):
            first = publish_site(self.site, 'fixture', self.root / 'cache.git')
            same = publish_site(self.site, 'fixture', self.root / 'cache.git')
            self.assertTrue(first['changed'])
            self.assertFalse(same['changed'])
            files = subprocess.check_output(['git', '--git-dir', str(origin), 'ls-tree', '--name-only', 'gh-pages'], text=True).splitlines()
            self.assertEqual(set(files), set(SITE_FILES) | {'.nojekyll'})
            (self.site / 'index.html').write_text('Version suivante', encoding='utf-8')
            second = publish_site(self.site, 'fixture', self.root / 'cache.git')
            parent = subprocess.check_output(['git', '--git-dir', str(origin), 'rev-parse', second['commit'] + '^'], text=True).strip()
            self.assertEqual(parent, first['commit'])

    def test_curated_seed_is_idempotent_and_never_approves_sources(self):
        url = 'https://example.org/live.m3u8'
        item = {'source_id': digest('TV.ch\n' + url)[:24], 'channel': {'id': 'TV.ch', 'name': 'TV', 'country': 'CH'},
                'url': url, 'origins': [{'url': 'https://example.org/live', 'sha256': 'a' * 64, 'observed_at': now()}]}
        seed = self.root / 'seed.yaml'
        seed.write_text(yaml.safe_dump({'sources': [item]}), encoding='utf-8')
        db = connect(self.root / 'catalog.sqlite')
        try:
            seed_catalog(db, seed)
            seed_catalog(db, seed)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sources').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 0)
            item['url'] = 'https://example.org/changed.m3u8'
            seed.write_text(yaml.safe_dump({'sources': [item]}), encoding='utf-8')
            with self.assertRaises(ValueError):
                seed_catalog(db, seed)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sources').fetchone()[0], 1)
        finally:
            db.close()
