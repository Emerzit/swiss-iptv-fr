"""Compare identities and measured playback with a reference, including malformed rows.

HD labels are declarations, not measurements. Never infer multicast reception
or overall picture quality from the number of channels or a playlist label.
"""
import hashlib
import json
from pathlib import Path
import re

from .catalog import parse_m3u


def reference_entries(text):
    for block in re.split(r'(?m)^#EXTINF:', text)[1:]:
        raw = '#EXTINF:' + block
        lines = raw.splitlines()
        url = next((line.strip() for line in lines[1:] if re.match(r'^(?:https?|rtp|udp)://', line.strip())), None)
        parsed = list(parse_m3u(raw))
        if parsed:
            yield {**parsed[0], 'malformed': False}
        else:
            # Audit only: retain the rejected row without importing or executing it.
            yield {**dict(re.findall(r'([\w-]+)="([^"]*)"', lines[0])),
                   'name': lines[0].rsplit(',', 1)[-1].strip(), 'url': url, 'malformed': True}


def reference_report(db, config, published, include_urls=False):
    cfg = config.get('reference', {})
    path = Path(cfg.get('file', 'data/inputs/tvopenchfr.m3u'))
    if not cfg or not path.exists():
        return None
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    selected = {c['id']: c for c in published}
    rows, represented = [], set()
    for entry in reference_entries(text):
        candidates = [dict(r) for r in db.execute('SELECT * FROM sources WHERE url=?', (entry['url'],))]
        ids = list(dict.fromkeys(config.get('canonical_ids', {}).get(c['channel_id'], c['channel_id']) for c in candidates))
        raw_id = entry.get('tvg-id', '').split('@')[0]
        override = cfg.get('channel_ids', {}).get(raw_id) or config.get('canonical_ids', {}).get(raw_id)
        matches = [cid for cid in ids if cid in selected]
        canonical = [cid for cid in ids if not cid.startswith('local.')]
        cid = override or (matches[0] if len(matches) == 1 else canonical[0] if len(canonical) == 1 else ids[0] if len(ids) == 1 else None)
        current = selected.get(cid)
        if cid:
            represented.add(cid)
        reference_decode = None
        internet_checks = []
        if cid:
            for attempt in db.execute('''SELECT s.id,s.url,k.status,k.checked_at FROM sources s JOIN checks k ON s.id=k.source_id
                WHERE s.channel_id=? AND k.country='CH' AND k.network='internet'
                AND k.id=(SELECT MAX(id) FROM checks WHERE source_id=s.id AND country='CH' AND network='internet')''', (cid,)):
                internet_checks.append({k: attempt[k] for k in ['id', 'status', 'checked_at']})
                if include_urls:
                    internet_checks[-1]['url'] = attempt['url']
        for source in candidates:
            if source['protocol'] in {'rtp', 'udp'} and source['operator'] in {'', 'unknown'}:
                continue
            check = db.execute('''SELECT * FROM checks WHERE source_id=? AND country='CH' AND network=?
                                  ORDER BY id DESC LIMIT 1''', (source['id'], source['operator'] or 'internet')).fetchone()
            if check and check['status'] == 'playable':
                reference_decode = {'checked_at': check['checked_at'], **json.loads(check['details']).get('decode', {})}
                break
        declared = 'FHD' if re.search(r'\bFHD\b', entry['name'], re.I) else 'HD' if re.search(r'\bHD\b', entry['name'], re.I) else None
        floor = 1080 if declared == 'FHD' else 720 if declared == 'HD' else None
        rows.append({'name': entry['name'], 'channel_id': cid,
            'malformed_reference_row': entry['malformed'], 'declared_quality': declared,
            'present': bool(current), 'published_width': current.get('width') if current else None,
            'published_height': current.get('height') if current else None,
            'published_fps': current.get('fps') if current else None,
            'published_checked_at': current.get('checked_at') if current else None,
            'meets_declared_height_floor': current['height'] >= floor if current and current.get('height') and floor else None,
            'reference_decode': reference_decode,
            'internet_checks': internet_checks,
            'quality_comparison': 'reference_not_measured' if not reference_decode else 'measurements_only_not_perceptual_quality',
            'note': cfg.get('notes', {}).get(cid)})
        if include_urls:
            rows[-1]['reference_url'] = entry['url']
    missing = [r for r in rows if not r['present']]
    return {'url': cfg.get('url'), 'sha256': hashlib.sha256(raw).hexdigest(),
            'reference_entries': len(rows), 'covered_entries': len(rows) - len(missing),
            'missing_entries': len(missing), 'additional_channels': sorted(selected.keys() - represented),
            'identity_coverage_complete': not missing, 'quality_parity': 'not_established',
            'reference_streams_measured': sum(bool(r['reference_decode']) for r in rows),
            'warnings': (['malformed_header'] if text.splitlines()[0].count('#EXTM3U') != 1 else []) +
                        (['malformed_rows_retained_for_audit_only'] if any(r['malformed_reference_row'] for r in rows) else []),
            'channels': rows}
