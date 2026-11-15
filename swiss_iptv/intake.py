"""Refresh extensible discovery feeds with conditional HTTP and immutable compressed evidence."""
import gzip
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

from .catalog import bootstrap, now
from .verify import public_url, SafeRedirect


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def sync_inputs(db, config, root='data/inputs', force=False):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    blobs = root / 'blobs'
    blobs.mkdir(exist_ok=True)
    state_path = root / 'http-state.json'
    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except (ValueError, OSError):
        state = {}  # Re-fetch evidence rather than relabelling an unverifiable cache.
    cfg = config.get('discovery', {})
    records, outcomes = [], []
    for feed in cfg.get('inputs', []):
        url, name = feed['url'], feed['file']
        target = root / name
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError('Discovery input path escapes its cache')
        cached = state.get(url, {})
        result = {'url': url, 'file': name}
        intact = target.exists() and cached.get('sha256') == hashlib.sha256(target.read_bytes()).hexdigest()
        due = force or not intact or time.time() - cached.get('checked_epoch', 0) >= cfg.get('refresh_hours', 24) * 3600
        try:
            if due or not target.exists():
                public_url(url)
                headers = {'User-Agent': 'Swiss-IPTV-FR/0.2', 'Accept-Encoding': 'identity'}
                if intact:
                    if cached.get('etag'):
                        headers['If-None-Match'] = cached['etag']
                    if cached.get('last_modified'):
                        headers['If-Modified-Since'] = cached['last_modified']
                request = urllib.request.Request(url, headers=headers)
                time.sleep(config['verification']['request_delay'])
                try:
                    with urllib.request.build_opener(SafeRedirect).open(request, timeout=cfg.get('http_timeout', 20)) as response:
                        limit = cfg.get('max_input_bytes', 25_000_000)
                        body = bytearray()
                        deadline = time.monotonic() + cfg.get('download_timeout', 60)
                        while block := response.read(min(65536, limit + 1 - len(body))):
                            body.extend(block)
                            if len(body) > limit or time.monotonic() > deadline:
                                raise ValueError('Discovery input exceeds download limits')
                        body = bytes(body)
                        # Parse JSON before replacing a usable metadata snapshot with an error page.
                        if name.endswith('.json'):
                            json.loads(body)
                        elif not body.lstrip(b'\xef\xbb\xbf\r\n ').startswith(b'#EXTM3U'):
                            raise ValueError('Expected a discovery playlist')
                        sha = hashlib.sha256(body).hexdigest()
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_suffix(target.suffix + '.tmp')
                        temporary.write_bytes(body)
                        temporary.replace(target)
                        archive = blobs / (sha + '.gz')
                        if not archive.exists():
                            archive.write_bytes(gzip.compress(body))
                        cached = {'etag': response.headers.get('ETag'), 'last_modified': response.headers.get('Last-Modified'),
                                  'sha256': sha, 'observed_at': now(), 'checked_epoch': time.time()}
                        result['status'] = 'updated'
                except urllib.error.HTTPError as error:
                    if error.code != 304 or not target.exists():
                        raise
                    cached.update(observed_at=now(), checked_epoch=time.time())
                    result['status'] = 'unchanged'
                state[url] = cached
            else:
                result['status'] = 'cached'
        except Exception as error:
            result.update(status='error', error=f'{type(error).__name__}: {error}')
        if target.exists():
            body = target.read_bytes()
            actual_sha = hashlib.sha256(body).hexdigest()
            if actual_sha == cached.get('sha256'):
                records.append({'url': url, 'file': name, 'sha256': actual_sha,
                                'fetched_at': cached['observed_at']})
            else:
                result.update(status='cache_corrupted', error='Cached bytes do not match downloaded evidence')
        outcomes.append(result)
        save_json(state_path, state)
        print('Input', name, result['status'], flush=True)
    save_json(root / 'manifest.json', records)
    if all('api/' + name + '.json' in {r['file'] for r in records} for name in ['channels', 'feeds', 'logos']):
        bootstrap(db, root, config)
        # Keep official website identities current without deleting local overrides or histories.
        for channel in json.loads((root / 'api/channels.json').read_text(encoding='utf-8')):
            if channel.get('website') and not channel.get('closed'):
                db.execute('UPDATE channels SET website=? WHERE id=?', (channel['website'], channel['id']))
        db.commit()
    (root / 'sync-report.json').write_text(json.dumps(outcomes, indent=2), encoding='utf-8')
    return outcomes
