import functools
import http.server
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

import yaml

from swiss_iptv.catalog import add_source, bootstrap, connect, digest, import_playlist, now, parse_m3u
from swiss_iptv.discover import discover
from swiss_iptv.publish import eligible, export_playlists, load_reviews
from swiss_iptv.verify import CheckError, check_once, decode, ffmpeg_path, manifest, public_url, verify

CONFIG = yaml.safe_load(Path('config.yaml').read_text(encoding='utf-8'))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / 'catalog.sqlite')
        self.db.execute("INSERT INTO channels (id,name,country,languages,category,epg_id,regional) VALUES ('TV.ch','Télé test','CH','fra','news','TV.ch',1)")
        self.sid = add_source(self.db, 'TV.ch', 'https://example.org/live.m3u8', 'https://example.org/live', 'a' * 64)
        self.source = self.db.execute('SELECT * FROM sources WHERE id=?', (self.sid,)).fetchone()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def grant(self, scope='public_links'):
        load_reviews(self.db, [dict(source_id=self.sid, decision='approved', evidence_url='https://example.org/terms',
                     evidence_sha256='b' * 64, reviewer='Test only', reviewed_at=now(), scope=scope,
                     notes='Synthetic test rights evidence, not a broadcaster authorization', access_ch=True, operator='')])

    def playback(self, status='playable', country='CH'):
        self.db.execute('INSERT INTO checks (source_id,run_id,checked_at,country,network,attempt,status,details) VALUES (?,?,?,?,?,?,?,?)',
                        (self.sid, now(), now(), country, 'internet', 1, status, json.dumps({'decode': {'frames': 125}})))
        self.db.commit()

    def test_parser_quotes_bom_and_ignored_player_commands(self):
        rows = list(parse_m3u('\ufeff#EXTM3U\n#EXTINF:-1 tvg-id="a" group-title="Info, Suisse",Télé, région\n#EXTVLCOPT:http-user-agent=ignored\nhttps://example.org/a.m3u8\n#EXTINF:-1,Invalid\nfile:///secret\n'))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['group-title'], 'Info, Suisse')
        self.assertEqual(rows[0]['name'], 'Télé, région')
        self.assertFalse(list(parse_m3u('#EXTINF:-1,tvg-id="bad",Malformed\nhttps://example.org/live')))

    def test_import_idempotent_and_no_rights_promotion(self):
        path = self.root / 'input.m3u8'
        path.write_text('#EXTM3U\n#EXTINF:-1 tvg-id="TV.ch@French",Télé test\nhttps://example.org/live.m3u8\n', encoding='utf-8')
        for _ in range(2):
            import_playlist(self.db, path, 'https://example.org/list')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM sources').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT epg_id FROM sources').fetchone()[0], 'TV.ch@French')
        self.playback()
        self.assertEqual(eligible(self.db, self.source, CONFIG['publication'])[1], 'rights_pending')

    def test_bootstrap_preserves_mixed_feed_languages_instead_of_relabelling_french_only(self):
        folder = self.root / 'upstream'
        (folder / 'api').mkdir(parents=True)
        (folder / 'api/channels.json').write_text(json.dumps([{'id': 'Mixed.ca', 'name': 'Mixed TV', 'country': 'CA', 'website': 'https://example.org/'}]))
        (folder / 'api/feeds.json').write_text(json.dumps([{'channel': 'Mixed.ca', 'id': 'SD', 'languages': ['ell', 'fra', 'eng']}]))
        (folder / 'api/logos.json').write_text('[]')
        text = '#EXTM3U\n#EXTINF:-1 tvg-id="Mixed.ca@SD",Mixed TV\nhttps://example.org/mixed.m3u8\n'
        (folder / 'fra.m3u').write_text(text)
        (folder / 'manifest.json').write_text(json.dumps([{'file': 'fra.m3u', 'url': 'https://example.org/list', 'sha256': digest(text), 'fetched_at': now()}]))
        bootstrap(self.db, folder, {})
        self.assertEqual(set(self.db.execute("SELECT languages FROM channels WHERE id='Mixed.ca'").fetchone()[0].split(',')), {'ell', 'eng', 'fra'})

    def test_approved_rights_require_swiss_playback(self):
        self.grant()
        self.playback(country='unknown')
        self.assertEqual(eligible(self.db, self.source, CONFIG['publication'])[1], 'no_swiss_playback')
        self.playback()
        self.assertIsNotNone(eligible(self.db, self.source, CONFIG['publication'])[0])
        self.playback(status='http_forbidden')
        self.assertEqual(eligible(self.db, self.source, CONFIG['publication'])[1], 'no_swiss_playback')

    def test_domestic_approval_does_not_allow_publication(self):
        self.grant('domestic_links')
        self.playback()
        self.assertEqual(eligible(self.db, self.source, CONFIG['publication'])[1], 'rights_scope')
        self.assertIsNotNone(eligible(self.db, self.source, CONFIG['publication'], 'domestic')[0])

    def test_reviewed_http_provider_needs_confirmed_external_isp_for_internet_export(self):
        self.db.execute('UPDATE sources SET operator=? WHERE id=?', ('netplus', self.sid))
        source = self.db.execute('SELECT * FROM sources WHERE id=?', (self.sid,)).fetchone()
        self.grant('domestic_links')
        self.playback()
        self.assertEqual(eligible(self.db, source, CONFIG['publication'], 'domestic')[1], 'operator_unconfirmed')
        for isp, expected in [('netplus', False), ('sunrise', True)]:
            self.db.execute('UPDATE checks SET details=?', (json.dumps({'decode': {'frames': 125}, 'connection_isp': isp}),))
            accepted, reason = eligible(self.db, source, CONFIG['publication'], 'domestic')
            self.assertEqual(bool(accepted), expected)
            if accepted:
                self.assertEqual(accepted['operator'], '')
        self.assertEqual(eligible(self.db, source, CONFIG['publication'])[1], 'rights_scope')
        self.assertEqual(eligible(self.db, {**dict(source), 'protocol': 'rtp'}, CONFIG['publication'], 'domestic')[1], 'operator_mismatch')

    def test_cdn_session_urls_are_not_persisted_in_check_reports(self):
        proof = {'decode': {'frames': 125}, 'manifests': [{'url': 'https://cdn.example.org/tok_private-session/live/master.m3u8?session=private-query', 'sha256': 'a' * 64}]}
        cfg = {**CONFIG['verification'], 'request_delay': 0}
        with patch('swiss_iptv.verify.check_once', return_value=proof):
            verify(self.db, cfg, source_id=self.sid, country='CH', isp='sunrise')
        saved = self.db.execute('SELECT details FROM checks').fetchone()[0]
        self.assertNotIn('private-session', saved)
        self.assertNotIn('private-query', saved)
        self.assertIn('/SESSION_REDACTED/live/master.m3u8', saved)
        self.assertIn('a' * 64, saved)

    def test_expiry_and_scope_and_metadata(self):
        self.grant()
        self.playback()
        counts = export_playlists(self.db, CONFIG, self.root / 'public')['playlists']
        self.assertEqual(counts['swiss-fr'], 1)
        self.assertEqual(counts['swiss-fr-regional'], 1)
        self.assertEqual(counts['swiss-fr-multicast'], 0)
        self.assertIn('tvg-id="TV.ch"', (self.root / 'public/swiss-fr.m3u').read_text(encoding='utf-8'))
        self.db.execute("UPDATE checks SET checked_at='2000-01-01T00:00:00+00:00'")
        self.assertEqual(eligible(self.db, self.source, CONFIG['publication'])[1], 'check_expired')

    def test_invalid_review_batch_is_atomic(self):
        with self.assertRaises((KeyError, ValueError)):
            load_reviews(self.db, [{'source_id': self.sid, 'decision': 'approved'}])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 0)

    def test_multicast_never_runs_on_unconfirmed_network(self):
        source = {**dict(self.source), 'protocol': 'rtp', 'url': 'rtp://239.1.1.1:10000', 'operator': 'swisscom'}
        with patch('swiss_iptv.verify.decode') as decoder:
            with self.assertRaises(CheckError) as error:
                check_once(source, CONFIG['verification'])
            self.assertEqual(error.exception.status, 'network_required')
            decoder.assert_not_called()

    def test_encryption_is_rejected_without_reading_keys(self):
        encrypted = b'#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="secret.key"\n#EXTINF:4,\nsegment.ts\n'
        with patch('swiss_iptv.verify.fetch', return_value=(encrypted, self.source['url'])) as fetcher:
            with self.assertRaises(CheckError) as error:
                manifest(self.source['url'], 'hls', CONFIG['verification'])
            self.assertEqual(error.exception.status, 'encrypted')
            self.assertEqual(fetcher.call_count, 1)
        mpd = b'<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet><ContentProtection schemeIdUri="urn:uuid:DRM"/></AdaptationSet></Period></MPD>'
        with patch('swiss_iptv.verify.fetch', return_value=(mpd, self.source['url'])):
            with self.assertRaises(CheckError) as error:
                manifest(self.source['url'], 'dash', CONFIG['verification'])
            self.assertEqual(error.exception.status, 'encrypted')

    def test_forbidden_is_not_inferred_as_geoblock(self):
        cfg = {**CONFIG['verification'], 'request_delay': 0, 'retry_delay': 0}
        with patch('swiss_iptv.verify.check_once', side_effect=CheckError('http_forbidden', '403')):
            verify(self.db, cfg, source_id=self.sid)
        outcomes = [r[0] for r in self.db.execute('SELECT status FROM checks')]
        self.assertEqual(outcomes, ['http_forbidden'] * 3)

    def test_retries_before_declaring_missing(self):
        cfg = {**CONFIG['verification'], 'request_delay': 0, 'retry_delay': 0}
        with patch('swiss_iptv.verify.check_once', side_effect=CheckError('not_found', '404')):
            verify(self.db, cfg, source_id=self.sid)
        outcomes = [r[0] for r in self.db.execute('SELECT status FROM checks')]
        self.assertEqual(outcomes, ['not_found', 'not_found', 'unavailable'])

    def test_public_url_guard(self):
        for url in ['file:///secret', 'https://user:password@example.org', 'http://127.0.0.1/a', 'http://169.254.169.254/']:
            with self.assertRaises(CheckError):
                public_url(url)

    def test_hls_prefers_video_over_cheaper_audio_only_variant(self):
        media = b'#EXTM3U\n#EXTINF:6,\nsegment.ts\n'
        for video_attrs in ['RESOLUTION=768x432,CODECS="avc1.4d401e,mp4a.40.2"', 'CODECS="avc1.4d401e,mp4a.40.2"']:
            master = ('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="English",DEFAULT=YES,LANGUAGE="en",URI="english.m3u8"\n'
                      '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="French",LANGUAGE="FRA",URI="french.m3u8"\n'
                      '#EXT-X-STREAM-INF:BANDWIDTH=150000,CODECS="mp4a.40.2",AUDIO="aud"\nenglish.m3u8\n'
                      f'#EXT-X-STREAM-INF:BANDWIDTH=970000,{video_attrs},AUDIO="aud"\nvideo.m3u8\n').encode()
            def download(url, *args, **kwargs):
                return (master if url.endswith('/master.m3u8') else media), url
            with patch('swiss_iptv.verify.fetch', side_effect=download), patch('swiss_iptv.verify.public_url', side_effect=lambda url: url):
                selected, proofs = manifest('https://example.org/master.m3u8', 'hls', CONFIG['verification'])
            self.assertEqual(selected, 'https://example.org/video.m3u8')
            self.assertEqual(proofs[0]['audio_url'], 'https://example.org/french.m3u8')

    def test_bootstrap_filters_feed_language_and_preserves_override(self):
        root = self.root / 'upstream'
        (root / 'api').mkdir(parents=True)
        channels = [{'id': 'News.fr', 'name': 'News', 'country': 'FR', 'categories': ['news']},
                    {'id': 'Regional.ch', 'name': 'Regional', 'country': 'CH', 'categories': ['general']}]
        feeds = [{'channel': 'News.fr', 'id': 'French', 'languages': ['fra']},
                 {'channel': 'News.fr', 'id': 'English', 'languages': ['eng']},
                 {'channel': 'Regional.ch', 'id': 'SD', 'languages': ['deu']}]
        for name, data in [('channels', channels), ('feeds', feeds), ('logos', [])]:
            (root / 'api' / f'{name}.json').write_text(json.dumps(data), encoding='utf-8')
        content = '#EXTM3U\n#EXTINF:-1 tvg-id="News.fr@French",News FR\nhttps://example.org/fr.m3u8\n#EXTINF:-1 tvg-id="News.fr@English",News EN\nhttps://example.org/en.m3u8\n#EXTINF:-1 tvg-id="Regional.ch@SD",Regional\nhttps://example.org/reg.m3u8\n'
        (root / 'fra.m3u').write_text(content, encoding='utf-8')
        (root / 'manifest.json').write_text(json.dumps([{'file': 'fra.m3u', 'url': 'https://example.org/list',
                    'sha256': digest(content), 'fetched_at': now()}]), encoding='utf-8')
        bootstrap(self.db, root, {'feed_language_overrides': {'Regional.ch@SD': ['fra']}})
        urls = [r[0] for r in self.db.execute('SELECT url FROM sources')]
        self.assertIn('https://example.org/fr.m3u8', urls)
        self.assertIn('https://example.org/reg.m3u8', urls)
        self.assertNotIn('https://example.org/en.m3u8', urls)

    def test_bootstrap_provider_variant_mapping_is_scoped_to_distributor(self):
        root = self.root / 'upstream'
        (root / 'api').mkdir(parents=True)
        for name, data in [('channels', [{'id': 'W9.fr', 'name': 'W9', 'country': 'FR'},
                                        {'id': 'W9Switzerland.ch', 'name': 'W9 CH', 'country': 'CH'}]),
                           ('feeds', [{'channel': 'W9.fr', 'id': 'SD', 'languages': ['fra']}]), ('logos', [])]:
            (root / 'api' / f'{name}.json').write_text(json.dumps(data), encoding='utf-8')
        content = '#EXTM3U\n#EXTINF:-1 tvg-id="W9.fr@SD",W9\nhttps://viamotionhsi.netplus.ch/live/w9.m3u8\n#EXTINF:-1 tvg-id="W9.fr@SD",W9\nhttps://example.org/fr.m3u8\n'
        (root / 'fra.m3u').write_text(content, encoding='utf-8')
        (root / 'manifest.json').write_text(json.dumps([{'file': 'fra.m3u', 'url': 'https://example.org/list',
            'sha256': digest(content), 'fetched_at': now()}]), encoding='utf-8')
        bootstrap(self.db, root, {'provider_channel_ids': {'netplus': {'W9.fr': 'W9Switzerland.ch'}}})
        channels = {r['url']: r['channel_id'] for r in self.db.execute('SELECT url,channel_id FROM sources')}
        self.assertEqual(channels['https://viamotionhsi.netplus.ch/live/w9.m3u8'], 'W9Switzerland.ch')
        self.assertEqual(channels['https://example.org/fr.m3u8'], 'W9.fr')

    def test_official_discovery_rejects_vod_and_signed_urls(self):
        document = b'<script>const a=`https://example.org/live.m3u8?DVR`;const b="https://vod.example.org/vod/movie.m3u8";const c="https://example.org/live.m3u8?token=secret";</script>'
        config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': 'https://example.org/live'}]}
        with patch('swiss_iptv.discover.fetch', return_value=(document, 'https://example.org/live')):
            records = discover(self.db, config, self.root / 'evidence')
        self.assertEqual(records[0]['streams'], ['https://example.org/live.m3u8?DVR'])
        official = self.db.execute('SELECT url FROM sources WHERE official=1').fetchall()
        self.assertEqual([r[0] for r in official], ['https://example.org/live.m3u8?DVR'])

    def test_discovery_keeps_jsx_and_query_strings_and_root_on_asset_error(self):
        for suffix in ['jsx', 'js?version=1']:
            asset = f'https://example.org/player.{suffix}'
            page = f'<script src="{asset}"></script>'.encode()
            config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': 'https://example.org/live', 'script_patterns': ['player']}]}
            def download(url, *args, **kwargs):
                if url == 'https://example.org/live':
                    return page, url
                self.assertEqual(url, asset)
                return b'let live="https://example.org/new.m3u8";', url
            with patch('swiss_iptv.discover.fetch', side_effect=download):
                result = discover(self.db, config, self.root / 'evidence')
            self.assertEqual(result[0]['streams'], ['https://example.org/new.m3u8'])
        page = b'<script src="/player.js"></script>https://example.org/root.m3u8'
        with patch('swiss_iptv.discover.fetch', side_effect=[(page, 'https://example.org/live'), OSError('missing asset')]):
            result = discover(self.db, config, self.root / 'evidence')
        self.assertEqual(result[0]['streams'], ['https://example.org/root.m3u8'])
        self.assertTrue(result[0]['resource_errors'])

    def test_public_player_configuration_and_ambiguous_channel_gate(self):
        page = 'https://example.org/direct'
        script = 'https://example.org/live/lecteur.js'
        settings = 'https://example.org/live/config.json'
        docs = {page: f'<script src="{script}"></script>', script:
                '// const unused="https://example.org/old.m3u8";\nconst config="config.json"; const ignored="license-config.json";',
                settings: json.dumps({'streamUrl': 'https://example.org/new.m3u8'})}
        config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': page,
            'script_patterns': ['lecteur'], 'follow_live_links': True, 'require_unique_stream': True}]}
        def download(url, *args, **kwargs):
            return docs[url].encode(), url
        with patch('swiss_iptv.discover.fetch', side_effect=download) as fetcher:
            result = discover(self.db, config, self.root / 'evidence')
        self.assertEqual(result[0]['streams'], ['https://example.org/new.m3u8'])
        self.assertNotIn('license-config.json', ' '.join(call.args[0] for call in fetcher.call_args_list))
        config['official_pages'][0]['script_patterns'] = []
        with patch('swiss_iptv.discover.fetch', return_value=(b'https://example.org/a.m3u8 https://example.org/b.m3u8', page)):
            result = discover(self.db, config, self.root / 'evidence')
        self.assertEqual(result[0]['access_status'], 'ambiguous_channel_identity')
        self.assertEqual(result[0]['streams'], [])

    def test_optional_browser_dom_is_recorded_without_session_extraction(self):
        browser = self.root / 'obscura.exe'
        browser.write_bytes(b'fixture, never executed')
        config = {**CONFIG, 'discovery': {'browser': str(browser)}, 'official_pages': [
            {'channel_id': 'TV.ch', 'url': 'https://example.org/direct', 'render_html': True}]}
        def render(command, **kwargs):
            Path(command[command.index('--output') + 1]).write_text('<video src="https://example.org/rendered.m3u8"></video>', encoding='utf-8')
            self.assertNotIn('--stealth', command)
            self.assertNotIn('--allow-private-network', command)
            self.assertNotIn('cookies', command)
            return subprocess.CompletedProcess(command, 0)
        with patch('swiss_iptv.discover.fetch', return_value=(b'<html>Public TV</html>', 'https://example.org/direct')), \
             patch('swiss_iptv.discover.subprocess.run', side_effect=render):
            result = discover(self.db, config, self.root / 'evidence')
        self.assertTrue(result[0]['browser_rendered'])
        self.assertEqual(result[0]['streams'], ['https://example.org/rendered.m3u8'])

    def test_explicit_public_embedded_player_requires_documented_link_and_host(self):
        page, player = 'https://example.org/live', 'https://public-player.example.net/channel/1/'
        cfg = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': page, 'embed_urls': [player],
                                           'embed_hosts': ['public-player.example.net']}]}
        with patch('swiss_iptv.discover.fetch', side_effect=[(player.encode(), page), (b'https://example.org/official.m3u8', player)]):
            result = discover(self.db, cfg, self.root / 'evidence')
        self.assertEqual(result[0]['streams'], ['https://example.org/official.m3u8'])
        with patch('swiss_iptv.discover.fetch', return_value=(b'No player published here', page)) as fetcher:
            result = discover(self.db, cfg, self.root / 'evidence')
        self.assertIn('not present', result[0]['error'])
        self.assertEqual(fetcher.call_count, 1)

    def test_cpac_public_components_are_followed_without_guessing_unpublished_items(self):
        page = 'https://www.cpac.ca/fr/'
        first, video = '/site/components/cpac-item-lists/livestreams.xml', '/site/components/videos/CPAC_TV.xml'
        cfg = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': page, 'content_store': first}]}
        def download(url, *args, **kwargs):
            if url == page:
                return first.encode(), page
            if url.endswith(first):
                return json.dumps({'descriptorDom': {'component': {'include': video}}}).encode(), url
            self.assertTrue(url.endswith(video))
            return json.dumps({'descriptorDom': {'component': {'url_s': 'https://example.org/cpac.m3u8'}}}).encode(), url
        with patch('swiss_iptv.discover.fetch', side_effect=download) as fetcher:
            result = discover(self.db, cfg, self.root / 'evidence')
        self.assertEqual(fetcher.call_count, 3)
        self.assertEqual(result[0]['streams'], ['https://example.org/cpac.m3u8'])
        with patch('swiss_iptv.discover.fetch', return_value=(b'No component', page)) as fetcher:
            result = discover(self.db, cfg, self.root / 'evidence')
        self.assertIn('not established', result[0]['error'])
        self.assertEqual(fetcher.call_count, 1)

    def test_srg_drm_and_token_resources_never_become_clear_sources(self):
        config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': 'https://example.org/live', 'srg_urn': 'urn:rts:video:1967124'}]}
        metadata = {'chapterList': [{'resourceList': [
            {'url': 'https://example.org/clear.m3u8', 'tokenType': 'NONE'},
            {'url': 'https://example.org/drm.m3u8', 'drmList': [{'type': 'WIDEVINE'}], 'tokenType': 'NONE'},
            {'url': 'https://example.org/token.m3u8', 'tokenType': 'AKAMAI'}]}]}
        with patch('swiss_iptv.discover.fetch', side_effect=[(b'urn:rts:video:1967124', 'https://example.org/live'),
                   (json.dumps(metadata).encode(), 'https://il.srgssr.ch/integrationlayer/2.0/mediaComposition/byUrn/urn:rts:video:1967124.json')]):
            result = discover(self.db, config, self.root / 'evidence')
        self.assertEqual(result[0]['streams'], ['https://example.org/clear.m3u8'])
        self.assertEqual(result[0]['drm_resources'], 1)
        self.assertEqual(result[0]['token_resources'], 1)

    def test_infomaniak_only_constant_public_integrations(self):
        config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': 'https://example.org/live', 'allow_embed': True}]}
        page = b'<iframe src="https://player.infomaniak.com?channel=4310&amp;player=2814"></iframe>'
        metadata = {'result': 'success', 'data': {'integrations': [
            {'url': 'https://example.org/official.m3u8', 'constant_url': True, 'type': 'hls'},
            {'url': 'https://example.org/expiring.m3u8', 'constant_url': False, 'type': 'hls'}]}}
        with patch('swiss_iptv.discover.fetch', side_effect=[(page, 'https://example.org/live'),
                   (b'<html>Player</html>', 'https://player.infomaniak.com?channel=4310&player=2814'),
                   (json.dumps(metadata).encode(), 'https://player.infomaniak.com/playerConfig.php?channel=4310&player=2814')]):
            result = discover(self.db, config, self.root / 'evidence')
        self.assertEqual(result[0]['streams'], ['https://example.org/official.m3u8'])

    def test_discovery_reads_ascii_escaped_stream_urls(self):
        page = br'{"live":"https\u003a\u002f\u002fexample.org\u002flive.m3u8"}'
        config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': 'https://example.org/live'}]}
        with patch('swiss_iptv.discover.fetch', return_value=(page, 'https://example.org/live')):
            result = discover(self.db, config, self.root / 'evidence')
        self.assertEqual(result[0]['streams'], ['https://example.org/live.m3u8'])

    def test_official_geo_error_never_imports_stream_or_labels_foreign_test_swiss(self):
        api = 'https://example.org/config'
        config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': 'https://example.org/live', 'json_url': api}]}
        self.db.execute('UPDATE sources SET official=1 WHERE id=?', (self.sid,))
        for country, active in [('FR', 1), ('CH', 0)]:
            metadata = {'data': {'attributes': {'error': {'code': 'ERROR_GEOLOCATION'},
                        'restriction': {'geoblocking': {'userCountryCode': country}},
                        'streams': [{'url': 'https://example.org/blocked.m3u8'}]}}}
            with patch('swiss_iptv.discover.fetch', side_effect=[(api.encode(), 'https://example.org/live'),
                       (json.dumps(metadata).encode(), api)]):
                result = discover(self.db, config, self.root / 'evidence')
            self.assertEqual(result[0]['access_status'], 'geo_restricted')
            self.assertEqual(result[0]['access_country'], country)
            self.assertFalse(result[0]['streams'])
            self.assertEqual(self.db.execute('SELECT active FROM sources WHERE id=?', (self.sid,)).fetchone()[0], active)

    def test_carac_public_api_requires_page_identity(self):
        page_url = 'https://carac.tv/lives/carac-1'
        config = {**CONFIG, 'official_pages': [{'channel_id': 'TV.ch', 'url': page_url, 'carac_slug': 'carac-1', 'allow_embed': True}]}
        urls = [page_url, 'https://api.m0g.ch/v1/channel/carac-1',
                'https://player.infomaniak.com?channel=123&player=456',
                'https://player.infomaniak.com/playerConfig.php?channel=123&player=456']
        bodies = [b'https://api.m0g.ch/v1', json.dumps({'live_player': urls[2]}).encode(), b'Player',
                  json.dumps({'data': {'integrations': [{'url': 'https://example.org/carac.m3u8', 'constant_url': True, 'type': 'hls'}]}}).encode()]
        with patch('swiss_iptv.discover.fetch', side_effect=list(zip(bodies, urls))) as fetcher:
            result = discover(self.db, config, self.root / 'evidence')
        self.assertEqual([call.args[0] for call in fetcher.call_args_list], urls)
        self.assertEqual(result[0]['streams'], ['https://example.org/carac.m3u8'])
        with patch('swiss_iptv.discover.fetch', return_value=(b'Unrelated page', page_url)) as fetcher:
            result = discover(self.db, config, self.root / 'evidence')
        self.assertIn('identity not established', result[0]['error'])
        self.assertEqual(fetcher.call_count, 1)

    def test_real_hls_and_dash_decode_and_missing_segments(self):
        try:
            executable = ffmpeg_path()
        except CheckError:
            self.skipTest('FFmpeg not installed (CI installs it)')
        # Generate real H.264 media locally; this does not establish broadcaster availability.
        for kind, filename in [('hls', 'index.m3u8'), ('dash', 'index.mpd')]:
            folder = self.root / kind
            folder.mkdir()
            command = [executable, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                       'testsrc=size=160x90:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                       '-t', '4', '-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p',
                       '-g', '25', '-f', kind, filename]
            subprocess.run(command, cwd=folder, check=True, capture_output=True, timeout=30)

        class QuietHandler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

        handler = functools.partial(QuietHandler, directory=str(self.root))
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cfg = {**CONFIG['verification'], 'request_delay': 0, 'sample_seconds': 2}
        try:
            # Only fixture tests permit loopback. Production always checks public destinations.
            with patch('swiss_iptv.verify.public_url', side_effect=lambda url: url):
                for kind, filename in [('hls', 'index.m3u8'), ('dash', 'index.mpd')]:
                    url = f'http://127.0.0.1:{server.server_port}/{kind}/{filename}'
                    details = check_once({'url': url, 'protocol': kind}, cfg)
                    self.assertGreaterEqual(details['decode']['frames'], 40)
                    self.assertEqual(details['decode']['video_codec'], 'h264')
                    self.assertEqual(details['decode']['width'], 160)
                    self.assertEqual(details['decode']['audio_codec'], 'aac')
                    self.assertTrue(details['decode']['audio_decoded'])
                    self.assertIsNone(details['decode']['audio_language'])
                audio_folder = self.root / 'audio'
                audio_folder.mkdir()
                subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                                'sine=frequency=660:sample_rate=48000', '-t', '4', '-c:a', 'aac', '-f', 'hls', 'index.m3u8'],
                               cwd=audio_folder, check=True, capture_output=True, timeout=30)
                (self.root / 'hls/master.m3u8').write_text('#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="French",DEFAULT=YES,LANGUAGE="fr",URI="../audio/index.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=64000,CODECS="mp4a.40.2",AUDIO="aud"\n../audio/index.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=160x90,CODECS="avc1.42e01e,mp4a.40.2",AUDIO="aud"\nindex.m3u8\n', encoding='utf-8')
                paired = check_once({'url': f'http://127.0.0.1:{server.server_port}/hls/master.m3u8', 'protocol': 'hls'}, cfg)
                high = self.root / 'high'
                high.mkdir()
                subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                                'testsrc=size=320x180:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                                '-t', '4', '-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p', '-g', '25', '-f', 'hls', 'index.m3u8'],
                               cwd=high, check=True, capture_output=True, timeout=30)
                master = self.root / 'hls/quality.m3u8'
                master.write_text('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,RESOLUTION=160x90\nindex.m3u8\n'
                                  '#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=320x180\n../high/index.m3u8\n', encoding='utf-8')
                quality_url = f'http://127.0.0.1:{server.server_port}/hls/quality.m3u8'
                best = check_once({'url': quality_url, 'protocol': 'hls'}, cfg)
                self.assertEqual(best['decode']['width'], 320)
                self.assertEqual(best['quality']['bandwidth'], 400000)
                self.assertFalse(best['is_live'])  # Local fixture is VOD, not an actual TV channel.
                (high / 'index.m3u8').unlink()
                fallback = check_once({'url': quality_url, 'protocol': 'hls'}, cfg)
                self.assertEqual(fallback['decode']['width'], 160)
                self.assertEqual(fallback['quality']['variant_rank'], 1)
                multi = self.root / 'multi'
                multi.mkdir()
                subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                    'testsrc=size=320x180:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-t', '4', '-map', '0:v', '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-filter:v:0', 'scale=160:90', '-b:v:0', '100k', '-b:v:1', '400k', '-c:a', 'aac', '-metadata:s:a:0', 'language=fra',
                    '-g', '25', '-adaptation_sets', 'id=0,streams=v id=1,streams=a', '-f', 'dash', 'index.mpd'],
                    cwd=multi, check=True, capture_output=True, timeout=30)
                dash_best = check_once({'url': f'http://127.0.0.1:{server.server_port}/multi/index.mpd', 'protocol': 'dash'}, cfg)
                self.assertEqual(dash_best['decode']['width'], 320)
                self.assertEqual(dash_best['manifests'][0]['dash_video_index'], 1)
                self.assertTrue(dash_best['decode']['audio_decoded'])
                self.assertEqual(dash_best['decode']['audio_language'], 'fra')
                self.assertTrue(paired['decode']['audio_decoded'])
                self.assertTrue(paired['manifests'][0]['audio_url'].endswith('/audio/index.m3u8'))
                for segment in (self.root / 'hls').glob('*.ts'):
                    segment.unlink()
                with self.assertRaises(CheckError):
                    check_once({'url': f'http://127.0.0.1:{server.server_port}/hls/index.m3u8', 'protocol': 'hls'}, cfg)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
