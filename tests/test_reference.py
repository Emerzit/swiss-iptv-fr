from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from swiss_iptv.catalog import add_source, connect
from swiss_iptv.reference import reference_entries, reference_report


class ReferenceComparisonTests(unittest.TestCase):
    def test_malformed_rows_are_counted_without_becoming_valid_imports(self):
        text = '#EXTM3U url-tvg="#EXTM3U url-tvg="https://example.org/guide.xml""\n' + \
            '#EXTINF:-1 tvg-id="TV.ch",TV FHD\nrtp://239.1.1.1:10000\n' + \
            '#EXTINF:-1 ,tvg-id="Other.ch" tvg-name="Other",Other HD\nrtp://239.1.1.2:10000\n'
        entries = list(reference_entries(text))
        self.assertEqual(len(entries), 2)
        self.assertTrue(entries[1]['malformed'])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'reference.m3u'
            path.write_text(text, encoding='utf-8')
            with closing(connect(root / 'db.sqlite')) as db:
                for cid in ['TV.ch', 'Other.ch']:
                    db.execute('INSERT INTO channels (id,name) VALUES (?,?)', (cid, cid))
                add_source(db, 'TV.ch', entries[0]['url'], 'https://example.org/list', 'a' * 64)
                add_source(db, 'Other.ch', entries[1]['url'], 'https://example.org/list', 'a' * 64)
                selected = [{'id': 'TV.ch', 'height': 720, 'width': 1280, 'fps': 50},
                            {'id': 'Extra.fr', 'height': 1080, 'width': 1920, 'fps': 25}]
                result = reference_report(db, {'reference': {'file': str(path), 'url': 'https://example.org/list'}}, selected)
        self.assertEqual(result['reference_entries'], 2)
        self.assertEqual(result['covered_entries'], 1)
        self.assertEqual(result['missing_entries'], 1)
        self.assertEqual(result['additional_channels'], ['Extra.fr'])
        self.assertFalse(result['identity_coverage_complete'])
        self.assertFalse(result['channels'][0]['meets_declared_height_floor'])
        self.assertEqual(result['quality_parity'], 'not_established')
        self.assertEqual(result['reference_streams_measured'], 0)
        self.assertIn('malformed_header', result['warnings'])
        self.assertNotIn('reference_url', result['channels'][0])

    def test_explicit_variant_identity_resolves_ambiguous_upstream_source_assignment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / 'reference.m3u'
            path.write_text('#EXTM3U\n#EXTINF:-1 tvg-id="AlphaNE.ch",Alpha NE HD\nrtp://239.1.1.1:10000\n')
            with closing(connect(root / 'db.sqlite')) as db:
                for cid in ['AlphaJura.ch', 'AlphaNeuchatel.ch']:
                    db.execute('INSERT INTO channels (id,name) VALUES (?,?)', (cid, cid))
                    add_source(db, cid, 'rtp://239.1.1.1:10000', 'https://example.org/list', 'a' * 64)
                cfg = {'reference': {'file': str(path)}, 'canonical_ids': {'AlphaNE.ch': 'AlphaNeuchatel.ch'}}
                result = reference_report(db, cfg, [{'id': 'AlphaNeuchatel.ch', 'height': 1080}])
        self.assertEqual(result['covered_entries'], 1)
        self.assertEqual(result['channels'][0]['channel_id'], 'AlphaNeuchatel.ch')


if __name__ == '__main__':
    unittest.main()
