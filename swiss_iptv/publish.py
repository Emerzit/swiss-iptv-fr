import html
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import zipfile

from .catalog import now
from .epg import matching_guide
from .lineup import channel_number, ordered_selection


def load_reviews(db, records):
    """Explicit editorial action, never invoked by discovery/import/verification."""
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
    filters = {
        'swiss-fr': lambda s, c: True,
        'swiss-fr-internet': lambda s, c: not s['operator'] and s['protocol'] not in {'udp', 'rtp'},
        'swiss-fr-multicast': lambda s, c: s['protocol'] in {'udp', 'rtp'},
        'swiss-fr-regional': lambda s, c: c['country'] == 'CH' and c['regional'],
        'swiss-fr-news': lambda s, c: 'news' in c['category'].lower(),
    }
    counts, epg_summary = {}, {}
    for name, predicate in filters.items():
        selected = {}
        for source in accepted:
            channel = channels[source['channel_id']]
            if predicate(source, channel):
                selected.setdefault(channel['id'], (channel, source))
        ordered = ordered_selection(selected, config)
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
    summary = {'generated_at': now(), 'audience': audience, 'playlists': counts,
               'exclusions': rejected, 'epg': epg_summary}
    (dest / 'status.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    links = ''.join(f'<li><a href="{html.escape(name)}.m3u">{html.escape(name)}</a> : {count} chaînes</li>'
                    for name, count in counts.items())
    guide = epg_summary['swiss-fr-internet']
    guide_link = (f'<p>Guide XMLTV externe : <a href="{html.escape(guide["url"], quote=True)}">'
                  f'{guide["matched_channels"]} chaînes couvertes</a>.</p>') if guide['url'] else '<p>Aucun guide actuellement validé.</p>'
    (dest / 'index.html').write_text('<!doctype html><html lang="fr"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width"><title>Swiss IPTV FR</title>'
        '<h1>Swiss IPTV FR</h1><p>Playlists de sources externes pour une réception personnelle en Suisse.</p>'
        f'<p>Dernière génération : {html.escape(summary["generated_at"])}.</p>'
        '<p>Configurer une fois l’URL de la liste Internet dans Kodi IPTV Simple, puis activer '
        'l’actualisation périodique des chaînes.</p><ul>' + links + '</ul>' + guide_link +
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
