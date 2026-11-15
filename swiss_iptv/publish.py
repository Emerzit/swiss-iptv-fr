import html
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import zipfile

from .catalog import now
from .epg import matching_guide
from .lineup import channel_number, ordered_selection
from .reference import reference_report


def load_reviews(db, records):
    """Validated editorial records; autonomous records must pass the separate link policy."""
    for review in records:
        if not db.execute('SELECT 1 FROM sources WHERE id=?', (review['source_id'],)).fetchone():
            raise ValueError('Unknown source_id')
        if review['decision'] not in {'approved', 'rejected', 'pending'}:
            raise ValueError('Invalid decision')
        if review['scope'] not in {'public_links', 'domestic_links'}:
            raise ValueError('Invalid review scope')
        if not review['evidence_url'].startswith('https://'):
            raise ValueError('Expected HTTPS rights evidence URL')
        if not re.fullmatch('[a-f0-9]{64}', review['evidence_sha256']):
            raise ValueError('Expected evidence SHA-256')
        if not review['reviewer'].strip() or not review['notes'].strip():
            raise ValueError('Reviewer and access/redistribution rationale required')
        date = datetime.fromisoformat(review['reviewed_at'])
        if date.tzinfo is None or date > datetime.now(timezone.utc):
            raise ValueError('Review date must be timezone aware and not in the future')
        if not isinstance(review['access_ch'], bool):
            raise ValueError('access_ch must be a YAML boolean')
    # Validate entire batch before replacing any decisions.
    with db:
        for review in records:
            db.execute('INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?,?,?,?,?)',
                       tuple(review[k] for k in ['source_id', 'decision', 'evidence_url', 'evidence_sha256',
                             'reviewer', 'reviewed_at', 'scope', 'notes', 'access_ch', 'operator']))


def eligible(db, source, cfg, audience='public'):
    review = db.execute('SELECT * FROM reviews WHERE source_id=?', (source['id'],)).fetchone()
    if not review or review['decision'] != 'approved':
        return None, 'rights_pending'
    if not review['access_ch'] or (audience == 'public' and review['scope'] != 'public_links'):
        return None, 'rights_scope'
    current = datetime.now(timezone.utc)
    if current - datetime.fromisoformat(review['reviewed_at']) > timedelta(days=cfg['review_max_days']):
        return None, 'review_expired'
    operator = review['operator']
    provider_mismatch = bool(source['operator'] and source['operator'] != operator)
    if provider_mismatch and (source['protocol'] in {'rtp', 'udp'} or operator):
        return None, 'operator_mismatch'
    network = operator or 'internet'
    check = db.execute('''SELECT * FROM checks WHERE source_id=? AND country='CH'
                          AND network=? ORDER BY id DESC LIMIT 1''', (source['id'], network)).fetchone()
    if not check or check['status'] != 'playable':
        return None, 'no_swiss_playback'
    if current - datetime.fromisoformat(check['checked_at']) > timedelta(hours=cfg['check_max_hours']):
        return None, 'check_expired'
    details = json.loads(check['details'])
    if review['reviewer'] == 'Swiss IPTV FR policy v1':
        languages = db.execute('SELECT languages FROM channels WHERE id=?', (source['channel_id'],)).fetchone()[0].split(',')
        if len(languages) > 1:
            audio_language = details.get('decode', {}).get('audio_language') or next((m['audio_language'] for m in details.get('manifests', []) if m.get('audio_language')), '')
            evidence = json.loads(review['notes']).get('language_evidence') or {}
            if audio_language not in {'fr', 'fra', 'fre'} and not (evidence.get('url') == source['url'] and evidence.get('language') in {'fr', 'fra', 'fre'}):
                return None, 'unconfirmed_french_audio'
    if details.get('is_live') is False:
        return None, 'not_linear_live'
    # A hostname identifies a distributor; a reviewed public HTTP entry can work on another ISP.
    if provider_mismatch and details.get('connection_isp', 'unknown') in {'', 'unknown', source['operator']}:
        return None, 'operator_unconfirmed'
    if details.get('decode', {}).get('frames', 0) < 2:
        return None, 'no_decode_evidence'
    if not db.execute('SELECT 1 FROM origins WHERE source_id=?', (source['id'],)).fetchone():
        return None, 'no_provenance'
    return {**dict(source), 'operator': operator, 'verification': dict(check)}, ''


def clean(value):
    return str(value or '').replace('"', "'").replace('\r', ' ').replace('\n', ' ')


def source_quality(source):
    details = json.loads(source['verification']['details'])
    video = details.get('decode', {})
    return ((video.get('width') or 0) * (video.get('height') or 0), video.get('fps') or 0,
            details.get('quality', {}).get('bandwidth', 0), source.get('official', 0), -source['priority'])


def export_playlists(db, config, destination, audience='public'):
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    accepted, rejected = [], {}
    for row in db.execute('SELECT * FROM sources WHERE active=1 ORDER BY priority,id'):
        source, reason = eligible(db, row, config['publication'], audience)
        if source:
            accepted.append(source)
        else:
            rejected[reason] = rejected.get(reason, 0) + 1
    channels = {r['id']: dict(r) for r in db.execute('SELECT * FROM channels')}
    accepted.sort(key=source_quality, reverse=True)
    filters = {
        'swiss-fr': lambda s, c: True,
        'swiss-fr-internet': lambda s, c: not s['operator'] and s['protocol'] not in {'udp', 'rtp'},
        'swiss-fr-multicast': lambda s, c: s['protocol'] in {'udp', 'rtp'},
        'swiss-fr-regional': lambda s, c: c['country'] == 'CH' and c['regional'],
        'swiss-fr-news': lambda s, c: 'news' in c['category'].lower(),
    }
    counts, epg_summary, qualities = {}, {}, []
    for name, predicate in filters.items():
        selected = {}
        for source in accepted:
            channel = channels[source['channel_id']]
            if predicate(source, channel):
                selected.setdefault(channel['id'], (channel, source))
        ordered = ordered_selection(selected, config)
        if name == 'swiss-fr-internet':
            for channel, source in ordered:
                details = json.loads(source['verification']['details'])
                video = details.get('decode', {})
                qualities.append({'id': channel['id'], 'name': channel['name'], 'source_id': source['id'],
                    'url': source['url'], 'checked_at': source['verification']['checked_at'],
                    'width': video.get('width'), 'height': video.get('height'), 'fps': video.get('fps'),
                    'video_codec': video.get('video_codec'), 'audio_codec': video.get('audio_codec'),
                    'audio_language': video.get('audio_language'), 'frames': video.get('frames'),
                    'language_evidence': config.get('source_language_overrides', {}).get(source['id']),
                    'decoded_seconds': video.get('decoded_seconds'), 'quality': details.get('quality', {})})
        # Kodi uses one XMLTV location per IPTV Simple instance. Providers here are fallbacks.
        guide_url, epg_ids = None, {}
        for guide in config.get('epg', {}).get('sources', []):
            for channel, source in ordered:
                url, epg_id = matching_guide(db, config, channel, source, audience, only_url=guide['url'])
                if url:
                    epg_ids[channel['id']] = epg_id
            if epg_ids:
                guide_url = guide['url']
                break
        header = '#EXTM3U'
        if guide_url:
            header += f' url-tvg="{clean(guide_url)}" x-tvg-url="{clean(guide_url)}"'
        lines = [header, f'# Generated {now()}; audience={audience}; sample playback only']
        for channel, source in ordered:
            attrs = {'tvg-id': epg_ids.get(channel['id'], source['epg_id'] or channel['epg_id']), 'tvg-name': channel['name'],
                     'tvg-logo': channel['logo'], 'group-title': channel['category'],
                     'tvg-language': channel['languages'], 'tvg-country': channel['country']}
            number = channel_number(channel['id'], config)
            if number is not None:
                attrs['tvg-chno'] = number
            lines += ['#EXTINF:-1 ' + ' '.join(f'{k}="{clean(v)}"' for k, v in attrs.items())
                      + ',' + clean(channel['name']), source['url']]
        target = dest / f'{name}.m3u'
        temp = target.with_suffix('.tmp')
        temp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        temp.replace(target)
        counts[name] = len(ordered)
        epg_summary[name] = {'url': guide_url, 'matched_channels': len(epg_ids)}
    previous_path = dest / 'status.json'
    try:
        previous = json.loads(previous_path.read_text(encoding='utf-8')) if previous_path.exists() else {}
    except ValueError:
        previous = {}
    before = {c['id']: c for c in previous.get('channels', [])}
    after = {c['id']: c for c in qualities}
    changes = {'added': sorted(after.keys() - before.keys()) if before else [],
               'removed': sorted(before.keys() - after.keys()),
               'source_changed': [cid for cid in before.keys() & after.keys() if before[cid]['source_id'] != after[cid]['source_id']]}
    summary = {'generated_at': now(), 'audience': audience, 'playlists': counts,
               'exclusions': rejected, 'epg': epg_summary, 'channels': qualities, 'changes': changes}
    comparison = reference_report(db, config, qualities)
    if comparison:
        summary['reference'] = comparison
    status_temp = dest / 'status.json.tmp'
    status_temp.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    status_temp.replace(dest / 'status.json')
    links = ''.join(f'<li><a href="{html.escape(name)}.m3u">{html.escape(name)}</a> : {count} chaînes</li>'
                    for name, count in counts.items())
    guide = epg_summary['swiss-fr-internet']
    guide_link = (f'<p>Guide XMLTV externe : <a href="{html.escape(guide["url"], quote=True)}">'
                  f'{guide["matched_channels"]} chaînes couvertes</a>.</p>') if guide['url'] else '<p>Aucun guide actuellement validé.</p>'
    quality_rows = ''.join('<tr><td>' + html.escape(c['name']) + '</td><td>' +
        html.escape(f"{c['width'] or '?'} × {c['height'] or '?'} · {c['fps'] or '?'} images/s") +
        '</td><td>' + html.escape(c['video_codec'] or '?') + '</td></tr>' for c in qualities)
    reference_html = ''
    if comparison:
        missing = ', '.join(row['name'] for row in comparison['channels'] if not row['present']) or 'aucune'
        reference_rows = ''.join('<tr><td>' + html.escape(row['name']) +
            ('<br><small>' + html.escape(row['note']) + '</small>' if row['note'] else '') +
            '</td><td>' + ('Oui' if row['present'] else 'Absente') + '</td><td>' +
            (html.escape(f"{row['published_width']} × {row['published_height']} · {row['published_fps']} images/s") if row['present'] else '—') +
            '</td><td>' + ('Mesuré' if row['reference_decode'] else 'Non mesuré') + '</td></tr>' for row in comparison['channels'])
        reference_html = (f'<h2>Comparaison avec tvopenchfr.m3u</h2><p>{comparison["covered_entries"]} entrées couvertes '
            f'sur {comparison["reference_entries"]}. Absentes : {html.escape(missing)}.</p>'
            '<p>Les mentions HD/FHD de la référence ne sont pas des mesures. '
            'La qualité de ses flux multicast ne peut être comparée sans lecture sur un réseau compatible.</p>'
            '<details><summary>Comparer chaque chaîne</summary><table><tr><th>Référence</th><th>Présence</th>'
            '<th>Notre lecture vérifiée</th><th>Flux de référence</th></tr>' + reference_rows + '</table></details>')
    (dest / 'index.html').write_text('<!doctype html><html lang="fr"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width"><title>Swiss IPTV FR</title>'
        '<style>body{font:16px system-ui;max-width:950px;margin:2rem auto;padding:0 1rem;line-height:1.5}'
        'table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.5rem;border-bottom:1px solid #ccc}</style>'
        '<h1>Swiss IPTV FR</h1><p>Playlists de sources externes pour une réception personnelle en Suisse.</p>'
        f'<p>Dernière génération : {html.escape(summary["generated_at"])}.</p>'
        '<p>Configurer une fois l’URL de la liste Internet dans Kodi IPTV Simple, puis activer '
        'l’actualisation périodique des chaînes.</p><ul>' + links + '</ul>' + guide_link +
        f'<details><summary>Qualité vérifiée : {len(qualities)} chaînes</summary>'
        '<p>Meilleure variante décodée parmi les sources contrôlées. Les liens adaptatifs restent compatibles '
        'avec le choix de qualité du lecteur. Un essai court ne garantit pas tous les programmes.</p>'
        '<table><tr><th>Chaîne</th><th>Lecture vérifiée</th><th>Codec vidéo</th></tr>' + quality_rows + '</table></details>' +
        reference_html +
        '<p>Les lecteurs contactent directement les infrastructures des diffuseurs ou de leurs distributeurs. '
        'Ce site ne contient aucun lecteur embarqué et n’héberge aucun programme, logo ou guide XMLTV. '
        'Les marques et contenus restent ceux de leurs titulaires. Un test court ne garantit pas la disponibilité continue.</p>'
        '<p><a href="status.json">État de la dernière génération</a></p></html>', encoding='utf-8')
    if audience == 'domestic':
        epg = epg_summary['swiss-fr-internet']
        instructions = (
            'Swiss IPTV FR — usage personnel dans le foyer\n\n'
            f"Chaînes retenues : {counts['swiss-fr-internet']} ; guide vérifié pour {epg['matched_channels']} chaînes.\n\n"
            '1. Copier swiss-fr-internet.m3u sur le Raspberry Pi, par exemple par clé USB.\n'
            '2. Dans Kodi, activer Client IPTV Simple et choisir ce fichier comme liste M3U locale.\n'
            '3. Le lien XMLTV est dans l’en-tête M3U quand disponible. Si Kodi a déjà un ancien guide configuré,\n'
            '   le remplacer dans les réglages EPG par le lien ci-dessous.\n'
            f"   Guide : {epg['url'] or 'aucun guide actuellement validé'}\n"
            '4. Actualiser les chaînes et le guide dans Kodi. Les tests ont été réalisés sur le PC.\n\n'
            'Pour renouveler les fichiers, lancer Mettre_a_jour.cmd à la racine du projet sur le PC.\n'
            'Aucun programme vidéo ni aucune grille de programmes ne sont hébergés dans cette archive.\n'
            'La sélection ne remplace pas un bouquet complet : les chaînes non vérifiées restent absentes.\n')
        (dest / 'LISEZ_MOI.txt').write_text(instructions, encoding='utf-8')
        with zipfile.ZipFile(dest / 'Swiss_IPTV_FR_Kodi.zip', 'w', zipfile.ZIP_DEFLATED) as package:
            for path in sorted(dest.glob('*.m3u')) + [dest / 'LISEZ_MOI.txt']:
                package.write(path, path.name)
    return summary


def report(db, destination):
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    latest = [dict(r) for r in db.execute('''SELECT s.channel_id,s.url,k.* FROM checks k
                  JOIN sources s ON s.id=k.source_id
                  WHERE k.id=(SELECT MAX(id) FROM checks WHERE source_id=k.source_id)''')]
    changes = []
    for check in latest:
        previous = db.execute('SELECT status FROM checks WHERE source_id=? AND run_id<>? ORDER BY id DESC LIMIT 1',
                              (check['source_id'], check['run_id'])).fetchone()
        if previous and previous['status'] != check['status']:
            changes.append({'source_id': check['source_id'], 'before': previous['status'], 'after': check['status']})
    stats = {'generated_at': now(), 'channels': db.execute('SELECT COUNT(*) FROM channels').fetchone()[0],
             'sources': db.execute('SELECT COUNT(*) FROM sources').fetchone()[0],
             'official_sources': db.execute('SELECT COUNT(*) FROM sources WHERE official=1').fetchone()[0],
             'attempts': db.execute('SELECT COUNT(*) FROM checks').fetchone()[0],
             'tested_sources': len(latest), 'statuses': {}, 'changes': changes,
             'new_candidates': [dict(r) for r in db.execute('SELECT id,channel_id,first_seen FROM sources WHERE first_seen >= datetime(\'now\',\'-1 day\')')]}
    for check in latest:
        stats['statuses'][check['status']] = stats['statuses'].get(check['status'], 0) + 1
    (dest / 'summary.json').write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Résultats techniques', '', f"Catalogue : {stats['channels']} chaînes, {stats['sources']} sources.",
             f"Tests : {stats['tested_sources']} sources, {stats['attempts']} tentatives.", '',
             '| Chaîne | Source | Résultat | Pays déclaré | Réseau de test | FAI déclaré | Dernier test |', '|---|---|---|---|---|---|---|']
    for check in latest:
        isp = json.loads(check['details']).get('connection_isp', 'unknown')
        lines.append(f"| {check['channel_id']} | {check['source_id']} | {check['status']} | {check['country']} | {check['network']} | {clean(isp).replace('|', ' ')} | {check['checked_at']} |")
    lines += ['', 'Les pays et réseaux sont déclarés par l’opérateur du test, pas géolocalisés automatiquement.',
              'HTTP 403 ne prouve ni géoblocage ni panne. `unavailable` exige des 404/410 répétés dans ce contexte.',
              'Les flux multicast non testés sur un réseau confirmé restent `network_required`.',
              'Les détails de décodage (images, durée, codecs, dimensions) figurent dans checks.json.']
    (dest / 'verification.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return stats
