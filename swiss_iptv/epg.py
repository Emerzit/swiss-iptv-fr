"""Check XMLTV links and exact channel IDs, without publishing programme content."""
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from .catalog import now
from .verify import CheckError, SafeRedirect, public_url


def xmltv_time(value):
    match = re.fullmatch(r'(\d{12}|\d{14})(?:\s*([+-]\d{4}|Z))?', value or '')
    if not match:
        return None
    digits, offset = match.groups()
    pattern = '%Y%m%d%H%M%S%z' if len(digits) == 14 else '%Y%m%d%H%M%z'
    try:
        return datetime.strptime(digits + (offset or '+0000'), pattern).astimezone(timezone.utc)
    except ValueError:
        return None


class LimitedReader:
    def __init__(self, stream, limit, deadline):
        self.stream, self.limit, self.deadline = stream, limit, deadline
        self.used = 0

    def read(self, size=-1):
        if time.monotonic() > self.deadline:
            raise ValueError('XMLTV processing time limit exceeded')
        data = self.stream.read(min(size if size >= 0 else 65_536, self.limit - self.used + 1))
        self.used += len(data)
        if self.used > self.limit:
            raise ValueError('XMLTV decompressed size limit exceeded')
        return data


def parse_xmltv(stream, max_bytes=200_000_000, deadline=None):
    reader = LimitedReader(stream, max_bytes, deadline or time.monotonic() + 60)
    iterator = ET.iterparse(reader, events=('start', 'end'))
    event, root = next(iterator)
    if root.tag != 'tv':
        raise ValueError('Expected XMLTV <tv>, not an HTML response or another format')
    channels, programme_counts, ends = {}, {}, {}
    count = 0
    for event, element in iterator:
        if event != 'end':
            continue
        if element.tag == 'channel':
            cid = element.get('id')
            if not cid or cid in channels:
                raise ValueError('Missing or duplicate XMLTV channel ID')
            channels[cid] = [n.text.strip() for n in element.findall('display-name') if n.text]
            element.clear()
            root.clear()
        elif element.tag == 'programme':
            cid = element.get('channel', '')
            start, stop = xmltv_time(element.get('start')), xmltv_time(element.get('stop'))
            if start and stop and stop > start:
                programme_counts[cid] = programme_counts.get(cid, 0) + 1
                ends[cid] = max(ends.get(cid, stop), stop)
            count += 1
            element.clear()
            root.clear()
    if not channels or not count:
        raise ValueError('XMLTV has no channels or programmes')
    current = datetime.now(timezone.utc)
    rows = [{'epg_id': cid, 'display_names': names, 'last_stop': ends[cid].isoformat() if cid in ends else None,
             'programmes': programme_counts.get(cid, 0)} for cid, names in channels.items()]
    return rows, 'available' if any(end > current for cid, end in ends.items() if cid in channels) else 'outdated'


def download_guide(url, cfg):
    public_url(url)
    time.sleep(cfg.get('request_delay', 1))
    deadline = time.monotonic() + cfg.get('total_timeout', 60)
    request = urllib.request.Request(url, headers={'User-Agent': 'Swiss-IPTV-FR/0.1'})
    hasher, size = hashlib.sha256(), 0
    with tempfile.TemporaryFile() as local:
        with urllib.request.build_opener(SafeRedirect).open(request, timeout=cfg.get('http_timeout', 12)) as response:
            final_url = response.url
            while True:
                if time.monotonic() > deadline:
                    raise ValueError('XMLTV download time limit exceeded')
                chunk = response.read(65_536)
                if not chunk:
                    break
                size += len(chunk)
                if size > cfg.get('max_download_bytes', 40_000_000):
                    raise ValueError('XMLTV download size limit exceeded')
                hasher.update(chunk)
                local.write(chunk)
        local.seek(0)
        compressed = local.read(2) == b'\x1f\x8b'
        local.seek(0)
        if compressed:
            with gzip.GzipFile(fileobj=local) as unpacked:
                channels, status = parse_xmltv(unpacked, cfg.get('max_decoded_bytes', 200_000_000), deadline)
        else:
            channels, status = parse_xmltv(local, cfg.get('max_decoded_bytes', 200_000_000), deadline)
    return status, channels, {'final_url': final_url, 'bytes': size, 'gzip': compressed, 'sha256': hasher.hexdigest()}


def verify_guides(db, config, output='output/audit'):
    cfg = config.get('epg', {})
    results = []
    for guide in cfg.get('sources', []):
        if not guide.get('enabled', True):
            continue
        for attempt in range(1, config['verification']['attempts'] + 1):
            channels, details = [], {}
            try:
                status, channels, details = download_guide(guide['url'], cfg)
            except urllib.error.HTTPError as exc:
                status, details = 'http_error', {'http_status': exc.code, 'reason': exc.reason}
            except (gzip.BadGzipFile, ValueError, ET.ParseError, StopIteration, EOFError) as exc:
                status, details = 'invalid_xmltv', {'reason': str(exc)}
            except (urllib.error.URLError, OSError) as exc:
                status, details = 'network_error', {'reason': str(exc)}
            except CheckError as exc:
                status, details = exc.status, {'reason': str(exc)}
            details['attempt'] = attempt
            details['channel_count'] = len(channels)
            with db:
                cursor = db.execute('INSERT INTO epg_checks (url,checked_at,status,sha256,details) VALUES (?,?,?,?,?)',
                                    (guide['url'], now(), status, details.get('sha256'), json.dumps(details)))
                for row in channels:
                    db.execute('INSERT INTO epg_channels VALUES (?,?,?,?,?)', (cursor.lastrowid, row['epg_id'],
                               json.dumps(row['display_names'], ensure_ascii=False), row['last_stop'], row['programmes']))
            print('EPG', guide['url'], attempt, status, flush=True)
            if status in {'available', 'outdated', 'unsafe_url'} or details.get('http_status') in {401, 403, 429}:
                break
            if attempt < config['verification']['attempts']:
                time.sleep(config['verification']['retry_delay'] * attempt)
        results.append({'url': guide['url'], 'status': status, **details})
    path = Path(output)
    path.mkdir(parents=True, exist_ok=True)
    (path / 'epg.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    return results


def matching_guide(db, config, channel, source, audience, only_url=None):
    cfg = config.get('epg', {})
    current = datetime.now(timezone.utc)
    scope = 'public_links' if audience == 'public' else 'domestic_links'
    for guide in cfg.get('sources', []):
        if only_url is not None and guide['url'] != only_url:
            continue
        if not guide.get('enabled', True) or scope not in guide.get('link_scopes', []):
            continue
        check = db.execute('SELECT * FROM epg_checks WHERE url=? ORDER BY id DESC LIMIT 1', (guide['url'],)).fetchone()
        if not check or check['status'] != 'available':
            continue
        if current - datetime.fromisoformat(check['checked_at']) > timedelta(hours=cfg.get('check_max_hours', 24)):
            continue
        candidates = [guide.get('channel_ids', {}).get(channel['id']), source['epg_id'], channel['epg_id']]
        for epg_id in dict.fromkeys(cid for cid in candidates if cid):
            row = db.execute('SELECT * FROM epg_channels WHERE check_id=? AND epg_id=?', (check['id'], epg_id)).fetchone()
            if row and row['last_stop'] and datetime.fromisoformat(row['last_stop']) > current:
                return guide['url'], epg_id
        # Exact typography normalization only; never infer a regional feed from fuzzy similarity.
        if (guide.get('match_unique_names', False) and channel['id'] not in guide.get('channel_ids', {}) and channel['name']):
            def exact_name(value):
                return re.sub(r'[\s.\-]+', '', unicodedata.normalize('NFKC', value).casefold())
            matches = [row for row in db.execute('SELECT * FROM epg_channels WHERE check_id=?', (check['id'],))
                       if row['last_stop'] and datetime.fromisoformat(row['last_stop']) > current and
                       exact_name(channel['name']) in {exact_name(name) for name in json.loads(row['display_names'])}]
            if len(matches) == 1:
                return guide['url'], matches[0]['epg_id']
    return None, source['epg_id'] or channel['epg_id']
