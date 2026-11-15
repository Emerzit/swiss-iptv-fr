import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch, Mock

from swiss_iptv.catalog import connect
from swiss_iptv.intake import sync_inputs


class DiscoveryIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / 'db.sqlite')
        self.url = 'https://example.org/french.m3u'
        self.cfg = {'verification': {'request_delay': 0}, 'discovery': {
            'inputs': [{'url': self.url, 'file': 'fra.m3u'}]}}

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def response(self, body):
        result = io.BytesIO(body)
        result.headers = {'ETag': 'test-etag'}
        return result

    def test_conditional_refresh_reuses_exact_evidence_and_failed_fetch_keeps_snapshot(self):
        body = b'#EXTM3U\n#EXTINF:-1,TV\nhttps://example.org/tv.m3u8\n'
        opener = Mock()
        opener.open.return_value = self.response(body)
        with patch('swiss_iptv.intake.public_url'), patch('swiss_iptv.intake.urllib.request.build_opener', return_value=opener):
            self.assertEqual(sync_inputs(self.db, self.cfg, self.root / 'cache')[0]['status'], 'updated')
            opener.open.side_effect = urllib.error.HTTPError(self.url, 304, 'Not Modified', {}, None)
            self.assertEqual(sync_inputs(self.db, self.cfg, self.root / 'cache', force=True)[0]['status'], 'unchanged')
            self.assertEqual(opener.open.call_args.args[0].get_header('If-none-match'), 'test-etag')
            opener.open.side_effect = OSError('offline')
            self.assertEqual(sync_inputs(self.db, self.cfg, self.root / 'cache', force=True)[0]['status'], 'error')
        records = json.loads((self.root / 'cache/manifest.json').read_text())
        self.assertEqual(records[0]['sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual((self.root / 'cache/fra.m3u').read_bytes(), body)

    def test_corrupted_cache_is_not_relabelled_as_downloaded_provenance(self):
        opener = Mock()
        opener.open.return_value = self.response(b'#EXTM3U\n')
        with patch('swiss_iptv.intake.public_url'), patch('swiss_iptv.intake.urllib.request.build_opener', return_value=opener):
            sync_inputs(self.db, self.cfg, self.root / 'cache')
            (self.root / 'cache/fra.m3u').write_bytes(b'#EXTM3U\n#EXTINF:-1,Injected\nhttps://evil.example/live.m3u8\n')
            opener.open.side_effect = OSError('offline')
            result = sync_inputs(self.db, self.cfg, self.root / 'cache')
        self.assertEqual(result[0]['status'], 'cache_corrupted')
        self.assertEqual(json.loads((self.root / 'cache/manifest.json').read_text()), [])
        self.assertIsNone(opener.open.call_args.args[0].get_header('If-none-match'))


if __name__ == '__main__':
    unittest.main()
