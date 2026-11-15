"""Refresh the reviewed household selection on this PC; never publish new links."""
import json
import os
from pathlib import Path
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from swiss_iptv.catalog import connect, inventory, now
from swiss_iptv.discover import discover
from swiss_iptv.epg import verify_guides
from swiss_iptv.publish import export_playlists, load_reviews, report
from swiss_iptv.remote import publish_site
from swiss_iptv.seed import seed_catalog
from swiss_iptv.locking import update_lock
from swiss_iptv.verify import verify


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
            load_reviews(db, reviews)
            discover(db, config, 'data/evidence/update')
            for sid in selected:
                verify(db, config['verification'], source_id=sid, limit=1, country=country, isp=profile.get('isp', 'unknown'))
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
                       'reviewed_sources': len(selected), 'household': household['playlists'],
                       'public': public['playlists'], 'publication': publication,
                       'guides': [{'url': g['url'], 'status': g['status']} for g in guides]}
            Path('output/audit/update.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
            print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Update stopped: {error}', file=sys.stderr)
        sys.exit(1)
