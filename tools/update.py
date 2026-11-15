"""Refresh discovery, validate CH playback, apply link policy, generate and publish."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from swiss_iptv.catalog import connect, inventory, now
from swiss_iptv.epg import verify_guides
from swiss_iptv.publish import export_playlists, load_reviews, report
from swiss_iptv.remote import publish_site
from swiss_iptv.seed import seed_catalog
from swiss_iptv.locking import update_lock
from swiss_iptv.verify import verify
from swiss_iptv.intake import sync_inputs
from swiss_iptv.autonomy import explore, fresh, REVIEWER
from swiss_iptv.publish import eligible, source_quality


def main():
    os.chdir(ROOT)
    config = yaml.safe_load(Path('config.yaml').read_text(encoding='utf-8'))
    profile_path = Path('data/local-profile.yaml')
    profile = yaml.safe_load(profile_path.read_text(encoding='utf-8')) if profile_path.exists() else {}
    decisions = {}
    for filename in config.get('publication', {}).get('review_files', ['data/domestic-reviews.yaml']):
        path = Path(filename)
        if path.exists():
            for review in yaml.safe_load(path.read_text(encoding='utf-8'))['reviews']:
                decisions[review['source_id']] = review
    reviews = list(decisions.values())
    selected = [r['source_id'] for r in reviews if r['decision'] == 'approved']
    if not selected:
        raise ValueError('No reviewed household sources; see data/reviews.example.yaml')
    with update_lock('data/update.lock'):
        context = subprocess.run([sys.executable, str(ROOT / 'tools/context.py')], capture_output=True,
                                 encoding='utf-8', errors='replace', timeout=30, check=True,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        country = json.loads(context.stdout)['country']
        if country != 'CH':
            raise ValueError(f'Test connection reported as {country}; Swiss playback is not assumed')
        with connect('data/catalog.sqlite') as db:
            seed = Path(config.get('publication', {}).get('seed_file', 'data/curated-sources.yaml'))
            if seed.exists():
                seed_catalog(db, seed)
            # Preserve newer re-evaluations of approved public links; explicit holds always win.
            pending_reviews = []
            for review in reviews:
                previous = db.execute('SELECT * FROM reviews WHERE source_id=?', (review['source_id'],)).fetchone()
                if (previous and previous['reviewer'] != REVIEWER and previous['decision'] != 'approved' and
                        review['decision'] == 'approved' and previous['reviewed_at'] > review['reviewed_at']):
                    continue
                if (previous and previous['reviewer'] == REVIEWER and previous['decision'] == review['decision'] == 'approved' and
                        previous['scope'] == review['scope'] == 'public_links' and review['access_ch'] and
                        previous['reviewed_at'] > review['reviewed_at']):
                    continue
                pending_reviews.append(review)
            load_reviews(db, pending_reviews)
            inputs = sync_inputs(db, config)
            # One current primary per channel; discovered alternatives are explored on rotation.
            approved = db.execute("SELECT s.* FROM sources s JOIN reviews r ON r.source_id=s.id WHERE s.active=1 AND r.decision='approved'").fetchall()
            ranked = []
            for source in approved:
                accepted, _ = eligible(db, source, config['publication'])
                if not accepted:
                    historical = db.execute("SELECT details FROM checks WHERE source_id=? AND country='CH' AND network='internet' AND status='playable' ORDER BY id DESC LIMIT 1", (source['id'],)).fetchone()
                    if historical:
                        accepted = {**dict(source), 'verification': {'details': historical[0]}}
                ranked.append((source, source_quality(accepted) if accepted else (0, 0, 0, 0, -source['priority'])))
            ranked.sort(key=lambda item: item[1], reverse=True)
            groups = {}
            for source, quality in ranked:
                groups.setdefault(source['channel_id'], []).append((source, quality))
            def last_primary_check(group):
                check = db.execute('SELECT checked_at FROM checks WHERE source_id=? ORDER BY id DESC LIMIT 1', (group[0][0]['id'],)).fetchone()
                return check[0] if check else ''
            ranked = [item for group in sorted(groups.values(), key=last_primary_check) for item in group]
            working = set()
            refreshed = 0
            refresh_deadline = time.monotonic() + config.get('discovery', {}).get('primary_minutes', 16) * 60
            for source, _ in ranked:
                if time.monotonic() >= refresh_deadline:
                    break
                if source['channel_id'] in working:
                    continue
                latest = db.execute('SELECT * FROM checks WHERE source_id=? ORDER BY id DESC LIMIT 1', (source['id'],)).fetchone()
                details = json.loads(latest['details']) if latest else {}
                if not (latest and latest['status'] == 'playable' and fresh(latest['checked_at'], 20) and
                        latest['country'] == country and latest['network'] == 'internet' and
                        details.get('connection_isp') == profile.get('isp', 'unknown') and
                        details.get('quality', {}).get('mode') == 'best'):
                    verify(db, {**config['verification'], 'source_timeout': min(config['verification'].get('source_timeout', 100),
                           max(1, refresh_deadline - time.monotonic()))}, source_id=source['id'], limit=1, country=country, isp=profile.get('isp', 'unknown'))
                    refreshed += 1
                current = db.execute('SELECT status FROM checks WHERE source_id=? ORDER BY id DESC LIMIT 1', (source['id'],)).fetchone()
                if current and current['status'] == 'playable':
                    working.add(source['channel_id'])
            anchor_ids = [r['source_id'] for r in reviews if r['decision'] == 'approved' and r['scope'] == 'public_links' and r['access_ch']]
            anchors = [dict(r) for r in db.execute('SELECT * FROM sources') if r['id'] in anchor_ids]
            exploration = explore(db, config, anchors, country, profile.get('isp', 'unknown'))
            guides = verify_guides(db, config)
            inventory(db, 'output/audit', config)
            report(db, 'output/audit')
            household = export_playlists(db, config, 'output/domestic', 'domestic')
            public = export_playlists(db, config, 'output/public')
            remote_path = Path('data/github.local.yaml')
            remote = yaml.safe_load(remote_path.read_text(encoding='utf-8')) if remote_path.exists() else {}
            publication = None
            if remote.get('enabled', False):
                publication = publish_site('output/public', remote['repository'], 'data/pages.git')
            summary = {'updated_at': now(), 'country': country, 'isp': profile.get('isp', 'unknown'),
                       'reviewed_sources': db.execute("SELECT COUNT(*) FROM reviews WHERE decision='approved'").fetchone()[0],
                       'editorial_seed_sources': len(selected), 'household': household['playlists'],
                       'public': public['playlists'], 'publication': publication,
                       'guides': [{'url': g['url'], 'status': g['status']} for g in guides]}
            summary.update(inputs=inputs, refreshed_sources=refreshed, exploration=exploration)
            Path('output/audit/update.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
            print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Update stopped: {error}', file=sys.stderr)
        sys.exit(1)
