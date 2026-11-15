import csv
import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .lineup import channel_number, lineup_key, ordered_selection


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
      CREATE TABLE IF NOT EXISTS channels (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT, languages TEXT,
        category TEXT, logo TEXT, epg_id TEXT, website TEXT, regional INTEGER DEFAULT 0);
      CREATE TABLE IF NOT EXISTS sources (
        id TEXT PRIMARY KEY, channel_id TEXT NOT NULL REFERENCES channels(id),
        url TEXT NOT NULL, protocol TEXT NOT NULL, priority INTEGER NOT NULL DEFAULT 100,
        operator TEXT NOT NULL DEFAULT '', geo TEXT NOT NULL DEFAULT 'unknown',
        official INTEGER NOT NULL DEFAULT 0, epg_id TEXT, first_seen TEXT, last_seen TEXT,
        active INTEGER NOT NULL DEFAULT 1, UNIQUE(channel_id,url));
      CREATE TABLE IF NOT EXISTS origins (
        source_id TEXT REFERENCES sources(id), url TEXT NOT NULL, sha256 TEXT NOT NULL,
        observed_at TEXT NOT NULL, UNIQUE(source_id,url,sha256));
      CREATE TABLE IF NOT EXISTS checks (
        id INTEGER PRIMARY KEY, source_id TEXT REFERENCES sources(id), run_id TEXT NOT NULL,
        checked_at TEXT NOT NULL, country TEXT NOT NULL, network TEXT NOT NULL,
        attempt INTEGER NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS checks_source ON checks(source_id,id DESC);
      CREATE TABLE IF NOT EXISTS reviews (
        source_id TEXT PRIMARY KEY REFERENCES sources(id), decision TEXT NOT NULL,
        evidence_url TEXT NOT NULL, evidence_sha256 TEXT NOT NULL, reviewer TEXT NOT NULL,
        reviewed_at TEXT NOT NULL, scope TEXT NOT NULL, notes TEXT NOT NULL,
        access_ch INTEGER NOT NULL, operator TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS epg_checks (
        id INTEGER PRIMARY KEY, url TEXT NOT NULL, checked_at TEXT NOT NULL,
        status TEXT NOT NULL, sha256 TEXT, details TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS epg_channels (
        check_id INTEGER REFERENCES epg_checks(id), epg_id TEXT NOT NULL,
        display_names TEXT NOT NULL, last_stop TEXT, programmes INTEGER NOT NULL,
        PRIMARY KEY(check_id,epg_id));
    ''')
    return db


def parse_m3u(text):
    """M3U collections, including files named .mpd; never execute player options."""
    pending = None
    for line in text.lstrip('\ufeff').splitlines():
        line = line.strip()
        if line.startswith('#EXTINF:'):
            # A comma inside a quoted attribute is not the name separator.
            match = re.match(r'#EXTINF:((?:[^",]|"[^"]*")*),(.*)', line)
            if match:
                attrs, name = match.groups()
                pending = dict(re.findall(r'([\w-]+)="([^"]*)"', attrs))
                pending['name'] = name.strip()
                if re.search(r'\btvg-[\w-]+\s*=', name):
                    pending = None
            else:
                pending = None
        elif line and not line.startswith('#') and pending:
            if urlparse(line).scheme in {'http', 'https', 'rtp', 'udp'}:
                yield {**pending, 'url': line}
            pending = None


def name_key(name):
    name = re.sub(r'\s*\([^)]*\)|\s*\[[^]]*\]', '', name)
    name = re.sub(r'\b(?:UHD|FHD|HD|SD|4K|1080p|720p)\b', '', name, flags=re.I)
    return ''.join(c for c in unicodedata.normalize('NFKD', name).casefold()
                   if c.isalnum() and not unicodedata.combining(c))


def protocol(url):
    parsed = urlparse(url)
    if parsed.scheme in ('rtp', 'udp'):
        return parsed.scheme
    if parsed.path.lower().endswith('.m3u8'):
        return 'hls'
    if parsed.path.lower().endswith('.mpd'):
        return 'dash'
    return 'http'


def operator_for(url, origin=''):
    host = (urlparse(url).hostname or '').lower()
    if 'netplus.ch' in host:
        return 'netplus'
    if protocol(url) in {'udp', 'rtp'}:
        low = origin.lower()
        return next((op for op in ['init7', 'citycable', 'swisscom', 'sunrise'] if op in low), 'unknown')
    if 'init7' in host:
        return 'init7'
    return ''


def add_source(db, channel_id, url, origin, sha, observed=None, official=False, epg_id=''):
    observed = observed or now()
    sid = digest(channel_id + '\n' + url)[:24]
    op = operator_for(url, origin)
    db.execute('''INSERT INTO sources
      (id,channel_id,url,protocol,operator,official,priority,epg_id,first_seen,last_seen)
      VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
      last_seen=MAX(sources.last_seen,excluded.last_seen),active=1,official=MAX(official,excluded.official),
      priority=MIN(priority,excluded.priority),
      operator=CASE WHEN sources.operator IN ('','unknown') AND excluded.operator NOT IN ('','unknown')
                    THEN excluded.operator ELSE sources.operator END,
      epg_id=CASE WHEN COALESCE(sources.epg_id,'')='' THEN excluded.epg_id ELSE sources.epg_id END''',
      (sid, channel_id, url, protocol(url), op, int(official), 10 if official else 100,
       epg_id, observed, observed))
    db.execute('''INSERT INTO origins VALUES (?,?,?,?) ON CONFLICT(source_id,url,sha256)
                  DO UPDATE SET observed_at=MAX(origins.observed_at,excluded.observed_at)''', (sid, origin, sha, observed))
    return sid


def bootstrap(db, root, config):
    root = Path(root)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    records = {r['file']: r for r in manifest if 'sha256' in r}
    metadata = {c['id']: c for c in json.loads((root / 'api/channels.json').read_text(encoding='utf-8'))}
    feeds = json.loads((root / 'api/feeds.json').read_text(encoding='utf-8'))
    french = {f['channel'] for f in feeds if 'fra' in f.get('languages', [])}
    feed_languages = {f"{f['channel']}@{f['id']}": f.get('languages', []) for f in feeds}
    logos = {}
    for logo in json.loads((root / 'api/logos.json').read_text(encoding='utf-8')):
        logos.setdefault(logo['channel'], logo['url'])
    id_lookup = {k.casefold(): k for k in metadata}
    names = {}
    for cid, c in metadata.items():
        if cid in french:
            for name in [c['name'], *c.get('alt_names', [])]:
                names.setdefault(name_key(name), set()).add(cid)
    pages = {p['channel_id']: p for p in config.get('official_pages', [])}
    aliases = config.get('aliases', {})
    imported = 0
    skipped = {}
    for filename, record in records.items():
        if not filename.endswith(('.m3u', '.m3u8', '.mpd')):
            continue
        content = (root / filename).read_text(encoding='utf-8-sig')
        if digest(content) != record['sha256']:
            # Hash original bytes, since Windows newline translation can differ.
            if hashlib.sha256((root / filename).read_bytes()).hexdigest() != record['sha256']:
                raise ValueError(f'Hash mismatch: {filename}')
        for entry in parse_m3u(content):
            raw_id = entry.get('tvg-id', '')
            langs = config.get('feed_language_overrides', {}).get(raw_id, feed_languages.get(raw_id))
            if langs is not None and 'fra' not in langs:
                continue
            cid = id_lookup.get(raw_id.split('@')[0].casefold())
            cid = config.get('canonical_ids', {}).get(cid, cid)
            key = name_key(entry.get('tvg-name') or entry['name'])
            cid = aliases.get(key, cid)
            if not cid and len(names.get(key, set())) == 1:
                cid = next(iter(names[key]))
            lang = entry.get('tvg-language', '').lower()
            is_fr = (cid in french or (langs is not None and 'fra' in langs)
                     or filename == 'fra.m3u' or filename.endswith('tvopenchfr.m3u')
                     or 'french' in lang or 'français' in lang)
            if not is_fr:
                continue
            country = entry.get('tvg-country', '')
            if not cid:
                cid = f'local.{key}.{country or "unknown"}'
            cid = config.get('provider_channel_ids', {}).get(operator_for(entry['url'], record['url']), {}).get(cid, cid)
            reason = ''
            if any(re.search(pattern, cid, re.I) for pattern in config.get('excluded_channel_patterns', [])):
                reason = 'subscription_without_authorization'
            host = urlparse(entry['url']).hostname or ''
            if any(host == suffix or host.endswith('.' + suffix) for suffix in config.get('excluded_host_suffixes', [])):
                reason = 'unreviewed_operator_proxy'
            if urlparse(entry['url']).query and re.search(r'(?:token|auth|signature|z32|expires|key)=', urlparse(entry['url']).query, re.I):
                reason = 'signed_or_credential_url'
            if reason:
                skipped[reason] = skipped.get(reason, 0) + 1
                continue
            meta = metadata.get(cid, {})
            if meta.get('is_nsfw') or meta.get('closed'):
                continue
            page = pages.get(cid, {})
            db.execute('''INSERT OR IGNORE INTO channels
              (id,name,country,languages,category,logo,epg_id,website,regional)
              VALUES (?,?,?,?,?,?,?,?,?)''',
              (cid, meta.get('name', entry['name']), meta.get('country', country), 'fra',
               ','.join(meta.get('categories', [])) or entry.get('group-title', 'unknown'),
               logos.get(cid, entry.get('tvg-logo', '')), cid, meta.get('website', ''),
               int(page.get('regional', False))))
            add_source(db, cid, entry['url'], record['url'], record['sha256'], record['fetched_at'], epg_id=raw_id)
            if cid in config.get('channel_geo', {}):
                db.execute('UPDATE sources SET geo=? WHERE channel_id=?', (config['channel_geo'][cid], cid))
            imported += 1
    # Official candidates can exist without any community playlist entry.
    for cid in french:
        meta = metadata.get(cid, {})
        if (not meta or meta.get('closed') or meta.get('is_nsfw') or not meta.get('website') or
                any(re.search(pattern, cid, re.I) for pattern in config.get('excluded_channel_patterns', []))):
            continue
        db.execute('''INSERT OR IGNORE INTO channels
          (id,name,country,languages,category,logo,epg_id,website,regional)
          VALUES (?,?,?,?,?,?,?,?,0)''',
          (cid, meta['name'], meta.get('country', ''), 'fra', ','.join(meta.get('categories', [])) or 'general',
           logos.get(cid, ''), cid, meta['website']))
    for cid, page in pages.items():
        meta = metadata.get(cid, {})
        db.execute('''INSERT OR IGNORE INTO channels
          (id,name,country,languages,category,logo,epg_id,website,regional)
          VALUES (?,?,?,?,?,?,?,?,?)''',
          (cid, meta.get('name', page.get('name', cid)), meta.get('country', page.get('country', '')),
           'fra', ','.join(meta.get('categories', [])) or 'general', logos.get(cid, ''), cid,
           page['url'], int(page.get('regional', False))))
        db.execute('UPDATE channels SET regional=? WHERE id=?', (int(page.get('regional', False)), cid))
    for cid, name in config.get('channel_names', {}).items():
        db.execute('UPDATE channels SET name=? WHERE id=?', (name, cid))
    db.commit()
    (root.parent / 'import-summary.json').write_text(json.dumps({'entries': imported, 'excluded_entries': skipped}, indent=2), encoding='utf-8')
    return imported


def import_playlist(db, path, origin, country='', language='fra'):
    content = Path(path).read_bytes()
    for entry in parse_m3u(content.decode('utf-8-sig')):
        epg = entry.get('tvg-id', '')
        cid = epg.split('@')[0] if epg else 'local.' + digest(entry['name'] + country)[:16]
        db.execute('INSERT OR IGNORE INTO channels (id,name,country,languages,category,logo,epg_id) VALUES (?,?,?,?,?,?,?)',
                   (cid, entry['name'], country, language, entry.get('group-title', ''),
                    entry.get('tvg-logo', ''), cid))
        add_source(db, cid, entry['url'], origin, hashlib.sha256(content).hexdigest(), epg_id=epg or cid)
    db.commit()


def inventory(db, dest, config=None):
    config = config or {}
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    channels = [dict(r) for r in db.execute('SELECT * FROM channels ORDER BY country,name')]
    channels.sort(key=lambda channel: lineup_key(channel, config))
    sources = [dict(r) for r in db.execute('SELECT * FROM sources ORDER BY channel_id,priority,id')]
    latest = {r['source_id']: dict(r) for r in db.execute('''SELECT k.* FROM checks k
              WHERE k.id=(SELECT MAX(id) FROM checks WHERE source_id=k.source_id)''')}
    reviews = {r['source_id']: dict(r) for r in db.execute('SELECT * FROM reviews')}
    for source in sources:
        check = latest.get(source['id'], {})
        source.update(status=check.get('status', 'not_tested'), last_checked=check.get('checked_at'),
                      test_country=check.get('country'), test_network=check.get('network'),
                      technical=json.loads(check.get('details', '{}')).get('decode', {}),
                      rights_status=reviews.get(source['id'], {}).get('decision', 'pending'),
                      rights_scope=reviews.get(source['id'], {}).get('scope'))
    for channel in channels:
        channel_sources = [s for s in sources if s['channel_id'] == channel['id']]
        dates = [s['last_checked'] for s in channel_sources if s['last_checked']]
        channel.update(source_ids=[s['id'] for s in channel_sources],
                       channel_number=channel_number(channel['id'], config),
                       last_checked=max(dates) if dates else None,
                       status='playable_in_test_context' if any(s['status'] == 'playable' for s in channel_sources)
                       else ('checked_without_confirmed_playback' if dates else 'not_tested'))
    for table, rows in [('channels', channels), ('sources', sources),
                        ('origins', [dict(r) for r in db.execute('SELECT * FROM origins')]),
                        ('checks', [dict(r) for r in db.execute('SELECT * FROM checks')])]:
        (dest / f'{table}.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    with (dest / 'candidates.csv').open('w', encoding='utf-8-sig', newline='') as out:
        fields = ['id', 'name', 'channel_number', 'country', 'languages', 'category', 'website', 'source_count', 'status']
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        for c in channels:
            writer.writerow({**{k: c[k] for k in fields if k in c},
                             'source_count': sum(s['channel_id'] == c['id'] for s in sources),
                             'status': c['status']})
    entries = ordered_selection({c['id']: (c, None) for c in channels}, config)
    with (dest / 'lineup.csv').open('w', encoding='utf-8-sig', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=['position', 'channel_number', 'id', 'name', 'status'])
        writer.writeheader()
        for index, (channel, _) in enumerate(entries, 1):
            writer.writerow({'position': index, **{key: channel[key] for key in ['channel_number', 'id', 'name', 'status']}})
    return {'channels': len(channels), 'sources': len(sources)}
