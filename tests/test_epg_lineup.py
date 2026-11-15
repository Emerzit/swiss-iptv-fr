from datetime import datetime, timedelta, timezone
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from swiss_iptv.catalog import add_source, connect, now, operator_for
from swiss_iptv.cli import main
from swiss_iptv.epg import download_guide, matching_guide, parse_xmltv, verify_guides
from swiss_iptv.lineup import ordered_selection
from swiss_iptv.publish import export_playlists, load_reviews


def guide_document(future=True):
    start = datetime.now(timezone.utc) + timedelta(days=1 if future else -2)
    stop = start + timedelta(hours=1)
    return (f'<tv><channel id="rts-one"><display-name>RTS 1</display-name></channel>'
            f'<channel id="rts-two"><display-name>RTS 2</display-name></channel>'
            f'<programme channel="rts-one" start="{start:%Y%m%d%H%M%S} +0000" stop="{stop:%Y%m%d%H%M%S} +0000"><title>Test</title></programme>'
            f'<programme channel="rts-two" start="{start:%Y%m%d%H%M%S} +0000" stop="{stop:%Y%m%d%H%M%S} +0000"><title>Test</title></programme></tv>').encode()


class GuideAndLineupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / 'catalog.sqlite')
        self.config = {
            'verification': {'attempts': 2, 'retry_delay': 0},
            'publication': {'review_max_days': 90, 'check_max_hours': 48},
            'lineup': [{'ids': ['RTS1.ch'], 'number': 1}, {'ids': ['RTS2.ch'], 'number': 2}],
            'epg': {'check_max_hours': 24, 'sources': [
                {'url': 'https://example.org/guide.xml.gz', 'link_scopes': ['public_links', 'domestic_links'],
                 'channel_ids': {'RTS1.ch': 'rts-one', 'RTS2.ch': 'rts-two'}}]},
        }
        for cid, name in [('RTS2.ch', 'A second'), ('RTS1.ch', 'Z first')]:
            self.db.execute('INSERT INTO channels (id,name,country,category,epg_id) VALUES (?,?,?,?,?)',
                            (cid, name, 'CH', 'general', cid))
            sid = add_source(self.db, cid, f'https://example.org/{cid}.m3u8', 'https://example.org/live', 'a' * 64)
            load_reviews(self.db, [{'source_id': sid, 'decision': 'approved', 'evidence_url': 'https://example.org/terms',
                'evidence_sha256': 'b' * 64, 'reviewer': 'Synthetic test only', 'reviewed_at': now(),
                'scope': 'public_links', 'notes': 'Fixture, not broadcaster permission', 'access_ch': True, 'operator': ''}])
            self.db.execute('INSERT INTO checks (source_id,run_id,checked_at,country,network,attempt,status,details) VALUES (?,?,?,?,?,?,?,?)',
                            (sid, now(), now(), 'CH', 'internet', 1, 'playable', json.dumps({'decode': {'frames': 125}})))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def store_guide(self, future=True):
        channels, status = parse_xmltv(io.BytesIO(guide_document(future)))
        with patch('swiss_iptv.epg.download_guide', return_value=(status, channels, {'sha256': 'c' * 64})):
            verify_guides(self.db, self.config, self.root)

    def test_header_exact_epg_ids_and_swiss_order(self):
        self.store_guide()
        result = export_playlists(self.db, self.config, self.root / 'public')
        body = (self.root / 'public/swiss-fr.m3u').read_text(encoding='utf-8')
        header = body.splitlines()[0]
        self.assertEqual(header, '#EXTM3U url-tvg="https://example.org/guide.xml.gz" x-tvg-url="https://example.org/guide.xml.gz"')
        self.assertLess(body.index('tvg-id="rts-one"'), body.index('tvg-id="rts-two"'))
        self.assertIn('tvg-chno="1"', body)
        self.assertIn('tvg-chno="2"', body)
        self.assertEqual(result['epg']['swiss-fr']['matched_channels'], 2)
        self.assertFalse((self.root / 'public/Swiss_IPTV_FR_Kodi.zip').exists())

    def test_kodi_archive_contains_only_generated_household_files(self):
        self.store_guide()
        export_playlists(self.db, self.config, self.root / 'private', 'domestic')
        with zipfile.ZipFile(self.root / 'private/Swiss_IPTV_FR_Kodi.zip') as package:
            self.assertEqual(len(package.namelist()), 6)
            self.assertEqual(sum(name.endswith('.m3u') for name in package.namelist()), 5)
            self.assertIn('LISEZ_MOI.txt', package.namelist())
            self.assertIn(b'https://example.org/guide.xml.gz', package.read('swiss-fr-internet.m3u'))
            self.assertIn('guide vérifié pour 2', package.read('LISEZ_MOI.txt').decode('utf-8'))

    def test_expired_empty_or_wrong_scope_guide_is_omitted(self):
        self.store_guide(False)
        result = export_playlists(self.db, self.config, self.root / 'public')
        self.assertIsNone(result['epg']['swiss-fr']['url'])
        self.store_guide()
        self.config['epg']['sources'][0]['link_scopes'] = ['domestic_links']
        result = export_playlists(self.db, self.config, self.root / 'public')
        self.assertIsNone(result['epg']['swiss-fr']['url'])
        self.assertEqual(result['playlists']['swiss-fr'], 2)
        result = export_playlists(self.db, self.config, self.root / 'private', 'domestic')
        self.assertIsNotNone(result['epg']['swiss-fr']['url'])
        self.db.execute("UPDATE epg_checks SET checked_at='2000-01-01T00:00:00+00:00'")
        result = export_playlists(self.db, self.config, self.root / 'private', 'domestic')
        self.assertIsNone(result['epg']['swiss-fr']['url'])

    def test_unknown_mapping_keeps_original_id_without_false_coverage(self):
        self.store_guide()
        self.config['epg']['sources'][0]['channel_ids'] = {'RTS1.ch': 'missing', 'RTS2.ch': 'missing'}
        result = export_playlists(self.db, self.config, self.root / 'public')
        body = (self.root / 'public/swiss-fr.m3u').read_text(encoding='utf-8')
        self.assertIn('tvg-id="RTS1.ch"', body)
        self.assertNotIn('url-tvg=', body)
        self.assertIsNone(result['epg']['swiss-fr']['url'])

    def test_current_failure_invalidates_previous_available_check(self):
        self.store_guide()
        with patch('swiss_iptv.epg.download_guide', side_effect=OSError('offline')):
            verify_guides(self.db, self.config, self.root)
        result = export_playlists(self.db, self.config, self.root / 'public')
        self.assertIsNone(result['epg']['swiss-fr']['url'])

    def test_gzip_download_and_decompressed_limit(self):
        class Response(io.BytesIO):
            url = 'https://example.org/guide.xml.gz'
        for cfg, raises in [({}, False), ({'max_decoded_bytes': 30}, True)]:
            response = Response(gzip.compress(guide_document()))
            with patch('swiss_iptv.epg.public_url'), patch('swiss_iptv.epg.urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = response
                if raises:
                    with self.assertRaises(ValueError):
                        download_guide(response.url, {'request_delay': 0, **cfg})
                else:
                    status, channels, details = download_guide(response.url, {'request_delay': 0})
                    self.assertEqual(status, 'available')
                    self.assertEqual(len(channels), 2)
                    self.assertTrue(details['gzip'])
                    self.assertEqual(len(details['sha256']), 64)

    def test_invalid_xmltv_and_orphan_future_programmes(self):
        with self.assertRaises(ValueError):
            parse_xmltv(io.BytesIO(b'<html><body>Service error</body></html>'))
        with self.assertRaises(ValueError):
            parse_xmltv(io.BytesIO(b'<tv><channel id="a"/><channel id="a"/></tv>'))
        document = guide_document().replace(b'channel="rts-one"', b'channel="orphan"').replace(b'channel="rts-two"', b'channel="orphan"')
        channels, status = parse_xmltv(io.BytesIO(document))
        self.assertEqual(status, 'outdated')

    def test_swiss_variant_preferred_with_fallback_and_stable_number(self):
        config = {'lineup': [{'ids': ['TF1Switzerland.ch', 'TF1.fr'], 'number': 3}]}
        selected = {cid: ({'id': cid, 'name': cid}, {}) for cid in ['Z.fr', 'TF1.fr', 'TF1Switzerland.ch']}
        chosen = ordered_selection(selected, config)
        self.assertEqual([c['id'] for c, s in chosen], ['TF1Switzerland.ch', 'Z.fr'])
        del selected['TF1Switzerland.ch']
        self.assertEqual(ordered_selection(selected, config)[0][0]['id'], 'TF1.fr')
        self.assertEqual(operator_for('rtp://233.35.254.148:1234', 'https://example.org/sunrise-tv.m3u'), 'sunrise')

    def test_domestic_cli_defaults_outside_pages_and_rejects_public_folder(self):
        arguments = ['swiss-iptv', '--db', str(self.root / 'catalog.sqlite'), 'export', '--audience', 'domestic']
        with patch('sys.argv', arguments), patch('sys.stdout', io.StringIO()), patch('swiss_iptv.cli.export_playlists', return_value={}) as exporter:
            main()
            self.assertEqual(exporter.call_args.args[2:], ('output/domestic', 'domestic'))
        with patch('sys.argv', arguments + ['--output', 'output/public/private']), patch('sys.stderr', io.StringIO()), patch('swiss_iptv.cli.connect') as connector:
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
            connector.assert_not_called()


if __name__ == '__main__':
    unittest.main()
