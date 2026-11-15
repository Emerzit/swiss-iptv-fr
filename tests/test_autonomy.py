import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from swiss_iptv.autonomy import (REVIEWER, approve_playback, candidate_rule, controller_proof, explore, same_site, setup)
from swiss_iptv.catalog import add_source, connect, now
from swiss_iptv.publish import export_playlists, load_reviews


class AutonomousPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / 'db.sqlite')
        setup(self.db)
        self.cfg = {'publication': {'review_max_days': 90, 'check_max_hours': 48},
                    'verification': {}, 'discovery': {'official_pages_per_run': 0}}
        self.db.execute("INSERT INTO channels (id,name,country,languages,website,category) VALUES ('TV.fr','TV','FR','fra','https://tele.example.org/','news')")
        self.sid = add_source(self.db, 'TV.fr', 'https://live.tele.example.org/live.m3u8', 'https://example.org/feed.m3u', 'a' * 64)
        self.source = self.db.execute('SELECT * FROM sources WHERE id=?', (self.sid,)).fetchone()
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def proof(self, live=True, language='fra'):
        details = {'is_live': live, 'connection_isp': 'sunrise', 'decode': {'frames': 125, 'width': 1920, 'height': 1080,
            'audio_decoded': True, 'audio_language': language}, 'quality': {'mode': 'best', 'bandwidth': 5000000}}
        self.db.execute('INSERT INTO checks (source_id,run_id,checked_at,country,network,attempt,status,details) VALUES (?,?,?,?,?,?,?,?)',
            (self.sid, now(), now(), 'CH', 'internet', 1, 'playable', json.dumps(details)))
        self.db.commit()

    def test_provenance_and_real_french_live_playback_are_independent_gates(self):
        rule, _ = candidate_rule(self.db, self.source, self.cfg, [])
        self.assertEqual(rule['rule'], 'first_party_public_live')
        http = {**dict(self.source), 'url': self.source['url'].replace('https:', 'http:')}
        self.assertEqual(candidate_rule(self.db, http, self.cfg, [])[0]['rule'], 'first_party_public_live')
        self.assertFalse(approve_playback(self.db, self.source, rule, self.cfg))
        self.proof()
        self.assertFalse(approve_playback(self.db, self.source, rule, self.cfg))  # Controller not fetched yet.
        rule['sha256'] = 'b' * 64
        rule['rule'] = 'official_page_reference'
        self.proof(live=False)
        self.assertFalse(approve_playback(self.db, self.source, rule, self.cfg))
        self.proof(language='eng')
        self.assertFalse(approve_playback(self.db, self.source, rule, self.cfg))
        self.proof()
        self.assertTrue(approve_playback(self.db, self.source, rule, self.cfg))
        output = export_playlists(self.db, self.cfg, self.root / 'site')
        self.assertEqual(output['playlists']['swiss-fr-internet'], 1)
        self.assertEqual(output['channels'][0]['width'], 1920)

    def test_shared_cdn_untrusted_origin_and_editorial_rejection_cannot_be_promoted(self):
        self.assertFalse(same_site('https://customer.amagi.tv/live.m3u8', 'https://amagi.tv/'))
        self.assertFalse(same_site('https://tele.example.org.evil.org/live.m3u8', 'https://tele.example.org/'))
        other = {**dict(self.source), 'url': 'https://customer.amagi.tv/live.m3u8'}
        self.assertEqual(candidate_rule(self.db, other, self.cfg, [])[1], 'official_relationship_unresolved')
        load_reviews(self.db, [dict(source_id=self.sid, decision='rejected', evidence_url='https://tele.example.org/terms',
            evidence_sha256='b' * 64, reviewer='Human', reviewed_at=now(), scope='public_links',
            notes='Forbidden', access_ch=False, operator='')])
        self.proof()
        self.assertEqual(candidate_rule(self.db, self.source, self.cfg, [])[1], 'explicit_editorial_hold')
        self.assertFalse(approve_playback(self.db, self.source, {'url': 'https://tele.example.org/', 'sha256': 'b' * 64}, self.cfg))

    def test_metadata_website_matching_stream_host_needs_a_public_player_reference(self):
        rule, _ = candidate_rule(self.db, self.source, self.cfg, [])
        cfg = {**self.cfg, 'verification': {'http_timeout': 1, 'request_delay': 0}}
        with patch('swiss_iptv.autonomy.fetch', return_value=(b'Official homepage ' * 20, rule['url'])), \
             patch('swiss_iptv.autonomy.discover', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'exact stream'):
                controller_proof(self.db, rule, cfg, self.root / 'evidence')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM reviews').fetchone()[0], 0)

    def test_audited_language_correction_is_exact_and_keeps_raw_measurement(self):
        self.proof(language='eng')
        proof = {'rule': 'official_page_reference', 'url': 'https://tele.example.org/direct', 'sha256': 'b' * 64}
        correction = {'url': self.source['url'], 'language': 'fra', 'evidence_url': 'https://tele.example.org/direct',
                      'evidence_sha256': 'b' * 64, 'reason': 'French official service verified; incorrect audio tag.'}
        cfg = {**self.cfg, 'source_language_overrides': {self.sid: correction}}
        correction['url'] = 'https://tele.example.org/other.m3u8'
        self.assertFalse(approve_playback(self.db, self.source, proof, cfg))
        correction['url'] = self.source['url']
        self.assertTrue(approve_playback(self.db, self.source, proof, cfg))
        self.assertEqual(json.loads(self.db.execute('SELECT details FROM checks').fetchone()[0])['decode']['audio_language'], 'eng')

    def test_mixed_language_service_needs_confirmed_french_track_even_after_old_approval(self):
        self.db.execute("UPDATE channels SET languages='ell,eng,fra' WHERE id='TV.fr'")
        proof = {'rule': 'official_page_reference', 'url': 'https://tele.example.org/direct', 'sha256': 'b' * 64}
        self.proof(language=None)
        self.assertFalse(approve_playback(self.db, self.source, proof, self.cfg))
        self.proof(language='fra')
        self.assertTrue(approve_playback(self.db, self.source, proof, self.cfg))
        self.proof(language=None)
        result = export_playlists(self.db, self.cfg, self.root / 'site')
        self.assertEqual(result['playlists']['swiss-fr-internet'], 0)
        self.assertEqual(result['exclusions']['unconfirmed_french_audio'], 1)
        cfg = {**self.cfg, 'discovery': {'official_pages_per_run': 1}}
        with patch('swiss_iptv.autonomy.discover', return_value=[{'channel_id': 'TV.fr', 'streams': []}]) as discovery:
            explore(self.db, cfg, [], 'CH', 'sunrise', self.root / 'evidence', budget_seconds=2)
        discovery.assert_called_once()  # Mixed services remain candidates for a confirmed French track.
        self.db.execute("UPDATE channels SET languages='fra' WHERE id='TV.fr'")
        self.proof(language='eng')
        result = export_playlists(self.db, self.cfg, self.root / 'site')
        self.assertEqual(result['playlists']['swiss-fr-internet'], 0)
        self.assertEqual(result['exclusions']['non_french_audio'], 1)

    def test_service_replacement_is_bound_to_channel_and_service(self):
        source = {**dict(self.source), 'url': 'https://viamotionhsi.netplus.ch/live/eds/test/browser-DASH/test.mpd', 'protocol': 'dash'}
        anchor = {**source, 'url': 'https://viamotionhsi.netplus.ch/live/eds/test/browser-HLS/test.m3u8'}
        self.assertEqual(candidate_rule(self.db, source, self.cfg, [anchor])[0]['rule'], 'reviewed_service')
        wrong = {**anchor, 'channel_id': 'Other.fr'}
        self.assertIsNone(candidate_rule(self.db, source, self.cfg, [wrong])[0])
        wrong = {**anchor, 'url': anchor['url'].replace('/test/', '/premium/')}
        self.assertIsNone(candidate_rule(self.db, source, self.cfg, [wrong])[0])

    def test_quality_selects_decoded_source_and_vod_cannot_be_exported(self):
        rule = {'rule': 'official_page_reference', 'url': 'https://tele.example.org/', 'sha256': 'b' * 64}
        self.proof()
        approve_playback(self.db, self.source, rule, self.cfg)
        low = add_source(self.db, 'TV.fr', 'https://live.tele.example.org/low.m3u8', 'https://example.org/feed', 'a' * 64, official=True)
        low_source = self.db.execute('SELECT * FROM sources WHERE id=?', (low,)).fetchone()
        original = self.sid
        self.sid = low
        self.proof()
        self.db.execute("UPDATE checks SET details=json_set(details,'$.decode.width',640,'$.decode.height',360) WHERE source_id=?", (low,))
        self.db.commit()
        approve_playback(self.db, low_source, rule, self.cfg)
        result = export_playlists(self.db, self.cfg, self.root / 'site')
        self.assertEqual(result['channels'][0]['source_id'], original)
        self.sid = original
        self.proof(live=False)
        result = export_playlists(self.db, self.cfg, self.root / 'site')
        self.assertEqual(result['channels'][0]['source_id'], low)

    def test_controller_failure_is_rotated_instead_of_starving_next_candidate(self):
        with patch('swiss_iptv.autonomy.controller_proof', side_effect=ValueError('Unavailable')) as controller:
            first = explore(self.db, self.cfg, [], 'CH', 'sunrise', self.root / 'evidence', budget_seconds=2)
            second = explore(self.db, self.cfg, [], 'CH', 'sunrise', self.root / 'evidence', budget_seconds=2)
        self.assertEqual(first['sources_checked'], 1)
        self.assertEqual(second['sources_checked'], 0)
        self.assertEqual(controller.call_count, 1)

    def test_known_account_requirement_blocks_discovery_and_previous_approval(self):
        self.proof()
        approve_playback(self.db, self.source, {'rule': 'official_page_reference',
            'url': 'https://tele.example.org/direct', 'sha256': 'b' * 64}, self.cfg)
        self.cfg['publication']['access_holds'] = {'TV.fr': {'status': 'account_required'}}
        self.assertEqual(candidate_rule(self.db, self.source, self.cfg, [])[1], 'account_required')
        result = export_playlists(self.db, self.cfg, self.root / 'site')
        self.assertEqual(result['playlists']['swiss-fr-internet'], 0)
        self.assertEqual(result['exclusions']['account_required'], 1)

    def test_reference_gap_due_for_retry_precedes_unvisited_background_channel(self):
        self.db.execute("INSERT INTO channels (id,name,languages,website) VALUES ('A.fr','A','fra','https://a.example.org/')")
        self.db.execute("INSERT INTO exploration VALUES ('page','TV.fr','2000-01-01T00:00:00+00:00','{}')")
        self.db.commit()
        status = self.root / 'status.json'
        status.write_text('{"channels":[]}')
        cfg = {**self.cfg, 'reference': {'file': 'fixture'}, 'discovery': {'official_pages_per_run': 1}}
        def paths(value):
            return status if str(value) == 'output/public/status.json' else Path(value)
        with patch('swiss_iptv.autonomy.Path', side_effect=paths), \
             patch('swiss_iptv.autonomy.reference_report', return_value={'channels': [{'channel_id': 'TV.fr', 'present': False}]}), \
             patch('swiss_iptv.autonomy.discover', return_value=[{'channel_id': 'TV.fr', 'streams': []}]) as discovery, \
             patch('swiss_iptv.autonomy.controller_proof', side_effect=ValueError('fixture')):
            explore(self.db, cfg, [], 'CH', 'sunrise', self.root / 'evidence', budget_seconds=2)
        self.assertEqual(discovery.call_args.args[1]['official_pages'][0]['channel_id'], 'TV.fr')


if __name__ == '__main__':
    unittest.main()
