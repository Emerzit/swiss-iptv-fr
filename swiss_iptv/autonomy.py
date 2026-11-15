"""Bounded, rotating exploration; publication still requires provenance and real CH playback.

An imported playlist is a lead, never an access authorization. Rules admit only
first-party public linear services, exact references on official pages, or a
replacement inside the same previously reviewed channel service.
"""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qsl, urlparse

from .catalog import now
from .discover import discover
from .publish import load_reviews
from .reference import reference_report
from .verify import fetch, verify


REVIEWER = 'Swiss IPTV FR policy v1'
SHARED_SITES = {'facebook.com', 'youtube.com', 'youtu.be', 'dailymotion.com',
                'wixsite.com', 'blogspot.com', 'infomaniak.com', 'akamaized.net',
                'amagi.tv', 'github.io', 'wordpress.com'}


def setup(db):
    db.execute('''CREATE TABLE IF NOT EXISTS exploration (
        kind TEXT NOT NULL, target TEXT NOT NULL, checked_at TEXT NOT NULL,
        details TEXT NOT NULL, PRIMARY KEY(kind,target))''')
    db.commit()


def remember(db, kind, target, details):
    db.execute('INSERT OR REPLACE INTO exploration VALUES (?,?,?,?)',
               (kind, target, now(), json.dumps(details)))
    db.commit()


def fresh(date, hours):
    return bool(date) and timedelta(0) <= datetime.now(timezone.utc) - datetime.fromisoformat(date) < timedelta(hours=hours)


def site_host(url):
    return (urlparse(url).hostname or '').lower().removeprefix('www.')


def same_site(url, website):
    host, owner = site_host(url), site_host(website)
    return bool(owner and '.' in owner and owner not in SHARED_SITES and
                not any(owner.endswith('.' + shared) for shared in SHARED_SITES) and
                (host == owner or host.endswith('.' + owner)))


def service_key(url):
    """Explicit service boundaries, never a blanket approval of a shared CDN."""
    parsed = urlparse(url)
    if parsed.hostname == 'viamotionhsi.netplus.ch':
        match = re.match(r'/live/eds/([^/]+)/', parsed.path)
        return (parsed.hostname, match[1]) if match else None
    if parsed.hostname == 'live.france24.com':
        match = re.match(r'/hls/live/\d+(?:-b)?/(F24_FR_HI_HLS)/', parsed.path)
        return (parsed.hostname, match[1]) if match else None
    # Infomaniak's service is the complete path before /playlist.m3u8 or /manifest.mpd.
    if parsed.hostname and parsed.hostname.endswith('.infomaniak.com'):
        path = re.sub(r'/(?:playlist\.m3u8|manifest\.mpd)$', '', parsed.path)
        if path != parsed.path and path.count('/') >= 2:
            return (parsed.hostname, path)
    return None


def candidate_rule(db, source, config, anchors):
    review = db.execute('SELECT * FROM reviews WHERE source_id=?', (source['id'],)).fetchone()
    if review and review['decision'] != 'approved' and review['reviewer'] != REVIEWER:
        return None, 'explicit_editorial_hold'
    parsed = urlparse(source['url'])
    if source['protocol'] not in {'hls', 'dash'} or parsed.scheme not in {'http', 'https'}:
        return None, 'requires_specific_access_review'
    if parsed.username or parsed.password or re.search(r'/tok_|/SESSION_REDACTED/|(?:^|[/.])vod[/.]|replay', source['url'], re.I):
        return None, 'session_or_replay_url'
    if any(re.search(r'session|token|auth|sign|expire|key|z32', key, re.I) for key, _ in parse_qsl(parsed.query)):
        return None, 'credential_or_signed_url'
    channel = db.execute('SELECT * FROM channels WHERE id=?', (source['channel_id'],)).fetchone()
    if not channel or 'fra' not in (channel['languages'] or '').split(','):
        return None, 'french_identity_unresolved'
    if any(re.search(pattern, source['channel_id'], re.I) for pattern in config.get('excluded_channel_patterns', [])):
        return None, 'subscription_without_authorization'
    host = parsed.hostname or ''
    if any(host == suffix or host.endswith('.' + suffix) for suffix in config.get('excluded_host_suffixes', [])):
        return None, 'unreviewed_proxy'
    origin = db.execute('SELECT * FROM origins WHERE source_id=? ORDER BY observed_at DESC LIMIT 1', (source['id'],)).fetchone()
    if not origin or not fresh(origin['observed_at'], 48):
        return None, 'provenance_not_current'
    # Approved service replacements stay bound to the SAME channel and stream service.
    key = service_key(source['url'])
    for anchor in anchors:
        if (key and anchor['channel_id'] == source['channel_id'] and
                service_key(anchor['url']) == key):
            return {'rule': 'reviewed_service', 'anchor': anchor['id'],
                    'url': origin['url'], 'sha256': origin['sha256']}, ''
    trusted = [p['url'] for p in config.get('official_pages', []) if p['channel_id'] == channel['id']]
    if channel['website']:
        trusted.append(channel['website'])
    if source['official']:
        for evidence in db.execute('SELECT * FROM origins WHERE source_id=? ORDER BY observed_at DESC', (source['id'],)):
            if fresh(evidence['observed_at'], 48) and any(same_site(evidence['url'], page) for page in trusted):
                return {'rule': 'official_page_reference', 'url': evidence['url'], 'sha256': evidence['sha256']}, ''
    if channel['website'] and urlparse(channel['website']).scheme in {'http', 'https'} and same_site(source['url'], channel['website']):
        return {'rule': 'first_party_public_live', 'url': channel['website'], 'sha256': None,
                'source_id': source['id'], 'channel_id': channel['id']}, ''
    return None, 'official_relationship_unresolved'


def controller_proof(db, proof, config, evidence_dir):
    if proof['sha256']:
        return proof
    previous = db.execute("SELECT * FROM exploration WHERE kind='controller' AND target=?", (proof['url'],)).fetchone()
    if previous and fresh(previous['checked_at'], 24):
        saved = json.loads(previous['details'])
        if not saved.get('sha256'):
            raise ValueError('Official website could not be verified in the last 24 hours')
    try:
        if previous and fresh(previous['checked_at'], 24) and json.loads(previous['details']).get('sha256'):
            saved = json.loads(previous['details'])
            final_url = saved['controller_final_url']
            body = (Path(evidence_dir) / (saved['sha256'] + '.html')).read_bytes()
        else:
            body, final_url = fetch(proof['url'], config['verification']['http_timeout'], config['verification']['request_delay'])
        if not same_site(final_url, proof['url']) or len(body) < 80:
            raise ValueError('Official website identity not confirmed')
        sha = hashlib.sha256(body).hexdigest()
        Path(evidence_dir).mkdir(parents=True, exist_ok=True)
        (Path(evidence_dir) / (sha + '.html')).write_bytes(body)
        saved = {'sha256': sha, 'controller_final_url': final_url}
        remember(db, 'controller', proof['url'], saved)
        # A matching streaming hostname is a lead; require a real reference in a public player.
        discover(db, {**config, 'official_pages': [{'channel_id': proof['channel_id'], 'url': proof['url'],
            'script_patterns': ['player|live|video|stream|main|app|index'], 'script_limit': 3,
            'follow_live_links': True, 'require_unique_stream': True, 'allow_embed': True}]}, Path(evidence_dir) / proof['channel_id'])
        for origin in db.execute('SELECT * FROM origins WHERE source_id=? ORDER BY observed_at DESC', (proof['source_id'],)):
            if same_site(origin['url'], proof['url']) and fresh(origin['observed_at'], 1):
                return {**proof, 'rule': 'official_page_reference', 'url': origin['url'], 'sha256': origin['sha256']}
        raise ValueError('A public official player reference to this exact stream is required')
    except Exception as error:
        remember(db, 'controller', proof['url'], {'error': str(error)})
        raise


def approve_playback(db, source, proof, config):
    """Apply an audited link policy only after this exact URL has passed decoding."""
    check = db.execute("SELECT * FROM checks WHERE source_id=? AND country='CH' AND network='internet' ORDER BY id DESC LIMIT 1",
                       (source['id'],)).fetchone()
    if not check or check['status'] != 'playable' or not fresh(check['checked_at'], 1):
        return False
    details = json.loads(check['details'])
    decoded = details.get('decode', {})
    language = decoded.get('audio_language') or next((m['audio_language'] for m in details.get('manifests', []) if m.get('audio_language')), '')
    language_override = config.get('source_language_overrides', {}).get(source['id'])
    if language_override:
        if (language_override.get('url') == source['url'] and language_override.get('language') in {'fr', 'fra', 'fre'} and
                proof.get('rule') == 'official_page_reference' and
                same_site(proof['url'], language_override.get('evidence_url', '')) and
                re.fullmatch('[a-f0-9]{64}', language_override.get('evidence_sha256', '')) and language_override.get('reason')):
            language = language_override['language']
        else:
            language_override = None
    if (details.get('is_live') is not True or decoded.get('frames', 0) < 2 or not decoded.get('audio_decoded') or
            language.lower() not in {'', 'und', 'fr', 'fra', 'fre'} or
            details.get('connection_isp') in {'', None, 'unknown'}):
        return False
    channel_languages = db.execute('SELECT languages FROM channels WHERE id=?', (source['channel_id'],)).fetchone()[0].split(',')
    if len(channel_languages) > 1 and language not in {'fr', 'fra', 'fre'}:
        return False  # A mixed-language feed needs a positively identified French track.
    old = db.execute('SELECT * FROM reviews WHERE source_id=?', (source['id'],)).fetchone()
    if old and old['reviewer'] != REVIEWER:
        if old['decision'] != 'approved' or old['scope'] != 'public_links' or not old['access_ch']:
            return False  # A hold or domestic-only decision is never promoted by policy.
        if fresh(old['reviewed_at'], (config['publication']['review_max_days'] - 7) * 24):
            return True
    if (proof.get('rule') not in {'reviewed_service', 'official_page_reference'} or
            not proof.get('sha256') or not proof['url'].startswith('https://')):
        return False
    load_reviews(db, [dict(source_id=source['id'], decision='approved', evidence_url=proof['url'],
        evidence_sha256=proof['sha256'], reviewer=REVIEWER, reviewed_at=now(), scope='public_links',
        notes=json.dumps({'policy': proof, 'checked_at': check['checked_at'],
            'language_evidence': language_override,
            'prior_editorial_evidence': dict(old) if old and old['reviewer'] != REVIEWER else None,
            'basis': 'Ordinary external link to a public clear linear service; verified controller provenance and CH playback. '
                     'No embedded player, programme redistribution, DRM key, account or access bypass. '
                     'French identity from feed metadata; unknown audio tags do not establish spoken-language certainty.'}, ensure_ascii=False),
        access_ch=True, operator='')])
    return True


def explore(db, config, anchors, country, isp, evidence_dir='data/evidence/autonomy', budget_seconds=None):
    setup(db)
    cfg = config.get('discovery', {})
    deadline = time.monotonic() + (budget_seconds if budget_seconds is not None else cfg.get('exploration_minutes', 18) * 60)
    # Refresh configured pages plus a rotating set of broadcaster websites worldwide.
    attempts = {r['target']: r['checked_at'] for r in db.execute("SELECT * FROM exploration WHERE kind='page'")}
    pages = {p['channel_id']: dict(p) for p in config.get('official_pages', [])}
    configured = set(pages)
    current_channels = {r[0] for r in db.execute("SELECT DISTINCT s.channel_id FROM reviews r JOIN sources s ON s.id=r.source_id WHERE r.decision='approved'")}
    countries = {r['id']: r['country'] for r in db.execute('SELECT id,country FROM channels')}
    for channel in db.execute("SELECT * FROM channels WHERE languages='fra' AND website LIKE 'http%' "):
        if (site_host(channel['website']) not in SHARED_SITES and
                not any(re.search(pattern, channel['id'], re.I) for pattern in config.get('excluded_channel_patterns', []))):
            pages.setdefault(channel['id'], {'channel_id': channel['id'], 'url': channel['website'],
                                            'script_patterns': ['player|live|video|stream|main|app|index'], 'script_limit': 2,
                                            'follow_live_links': True, 'require_unique_stream': True, 'allow_embed': True})
    has_sources = {r[0] for r in db.execute('SELECT DISTINCT channel_id FROM sources WHERE active=1')}
    priority_ids = set(cfg.get('priority_channels', []))
    previous_status = Path('output/public/status.json')
    if config.get('reference') and previous_status.exists():
        try:
            comparison = reference_report(db, config, json.loads(previous_status.read_text(encoding='utf-8')).get('channels', []))
            if comparison:
                priority_ids.update(row['channel_id'] for row in comparison['channels'] if not row['present'] and row['channel_id'])
        except (ValueError, OSError):
            pass
    pending_pages = sorted(pages.values(), key=lambda p: (p['channel_id'] not in priority_ids,
                           bool(attempts.get(p['channel_id'])),
                           attempts.get(p['channel_id'], ''), p['channel_id'] in current_channels,
                           p['channel_id'] not in configured, p['channel_id'] not in has_sources,
                           countries.get(p['channel_id']) not in cfg.get('preferred_countries', ['CH', 'FR', 'BE', 'MC', 'CA']),
                           p['channel_id']))
    page_results = []
    page_deadline = time.monotonic() + max(0, deadline - time.monotonic()) * 0.3
    for page in pending_pages:
        if len(page_results) >= cfg.get('official_pages_per_run', 24) or time.monotonic() >= page_deadline:
            break
        if fresh(attempts.get(page['channel_id']), cfg.get('retry_hours', 72)):
            continue
        page = {**page, 'render_html': len(page_results) < cfg.get('rendered_pages_per_run', 4)}
        results = discover(db, {**config, 'official_pages': [page]}, Path(evidence_dir) / page['channel_id'])
        remember(db, 'page', page['channel_id'], results[0])
        page_results.extend(results)
    eligible_sources, holds = [], {}
    source_attempts = {r['target']: r['checked_at'] for r in db.execute("SELECT * FROM exploration WHERE kind='source'")}
    for row in db.execute('SELECT * FROM sources WHERE active=1'):
        proof, reason = candidate_rule(db, row, config, anchors)
        if proof:
            latest = db.execute('SELECT checked_at,status,details FROM checks WHERE source_id=? ORDER BY id DESC LIMIT 1', (row['id'],)).fetchone()
            review = db.execute('SELECT * FROM reviews WHERE source_id=?', (row['id'],)).fetchone()
            renewal_due = (not review or (review['reviewer'] == REVIEWER and not fresh(review['reviewed_at'], 24)) or
                           not fresh(review['reviewed_at'], (config['publication']['review_max_days'] - 7) * 24))
            reusable = bool(latest and latest['status'] == 'playable' and fresh(latest['checked_at'], 1) and renewal_due)
            sampled_best = bool(latest and json.loads(latest['details']).get('quality', {}).get('mode') == 'best')
            if not reusable and ((latest and (latest['status'] != 'playable' or sampled_best) and fresh(latest['checked_at'], cfg.get('retry_hours', 72))) or
                                 fresh(source_attempts.get(row['id']), cfg.get('retry_hours', 72))):
                continue
            eligible_sources.append((dict(row), {**proof, 'reuse_sample': reusable},
                                     max(latest['checked_at'] if latest else '', source_attempts.get(row['id'], ''))))
        else:
            holds[reason] = holds.get(reason, 0) + 1
    # Oldest attempt first; alternate channels so a broadcaster with many encodings cannot starve others.
    existing = {r[0] for r in db.execute("SELECT DISTINCT s.channel_id FROM reviews r JOIN sources s ON s.id=r.source_id WHERE r.decision='approved'")}
    eligible_sources.sort(key=lambda item: (bool(item[2]), item[2], item[0]['channel_id'] in existing, item[0]['channel_id'], item[0]['id']))
    queued, seen, rest = [], set(), []
    for item in eligible_sources:
        (rest if item[0]['channel_id'] in seen else queued).append(item)
        seen.add(item[0]['channel_id'])
    processed = []
    for source, proof, _ in queued + rest:
        if time.monotonic() >= deadline:
            break
        try:
            proof = controller_proof(db, proof, config, evidence_dir)
            if not proof.pop('reuse_sample', False):
                verify(db, {**config['verification'], 'source_timeout': min(config['verification'].get('source_timeout', 100),
                        max(1, deadline - time.monotonic()))}, source_id=source['id'], limit=1, country=country, isp=isp)
            approved = approve_playback(db, source, proof, config)
            result = {'source_id': source['id'], 'channel_id': source['channel_id'], 'approved': approved, 'rule': proof['rule']}
        except Exception as error:
            result = {'source_id': source['id'], 'channel_id': source['channel_id'], 'error': str(error)}
        remember(db, 'source', source['id'], result)
        processed.append(result)
    summary = {'generated_at': now(), 'pages_checked': len(page_results), 'sources_checked': len(processed),
               'approved': sum(bool(r.get('approved')) for r in processed),
               'remaining_qualified': len(eligible_sources) - len(processed), 'holds': holds, 'results': processed}
    Path(evidence_dir).mkdir(parents=True, exist_ok=True)
    (Path(evidence_dir) / 'exploration.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary
