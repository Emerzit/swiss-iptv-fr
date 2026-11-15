import argparse
import json
from pathlib import Path
import sys

import yaml

from .catalog import bootstrap, connect, import_playlist, inventory
from .discover import discover
from .epg import verify_guides
from .publish import export_playlists, load_reviews, report
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description='Swiss IPTV FR — catalogue, tests et publication contrôlée')
    parser.add_argument('--config', default='config.yaml')
    parser.add_argument('--db', default='data/catalog.sqlite')
    commands = parser.add_subparsers(dest='command', required=True)
    boot = commands.add_parser('bootstrap', help='Importer les instantanés et dédupliquer les candidats')
    boot.add_argument('--upstream', default='data/upstream')
    imp = commands.add_parser('import', help='Importer une collection M3U/M3U8')
    imp.add_argument('path')
    imp.add_argument('--origin', required=True)
    imp.add_argument('--country', default='')
    commands.add_parser('discover', help='Chercher les manifestes publics sur les pages officielles configurées')
    commands.add_parser('epg-check', help='Vérifier les guides XMLTV configurés et les identifiants de chaînes')
    check = commands.add_parser('verify', help='Décoder un échantillon; sans cible, seules les sources officielles')
    group = check.add_mutually_exclusive_group()
    group.add_argument('--channel')
    group.add_argument('--source')
    check.add_argument('--limit', type=int, default=10)
    check.add_argument('--country', default='unknown', help='Pays réel de la connexion de test, CH seulement si confirmé')
    check.add_argument('--network', default='internet', choices=['internet', 'swisscom', 'init7', 'citycable', 'netplus', 'sunrise'])
    check.add_argument('--isp', default='unknown', help='Fournisseur Internet réel du PC de test, distinct du réseau multicast')
    check.add_argument('--local-address', default='', help='Interface multicast locale, ex. 192.168.1.10')
    inv = commands.add_parser('inventory')
    inv.add_argument('--output', default='output/audit')
    review = commands.add_parser('review', help='Appliquer explicitement des décisions éditoriales YAML')
    review.add_argument('file')
    exp = commands.add_parser('export')
    exp.add_argument('--output', help='Par défaut : output/public ou output/domestic selon le périmètre')
    exp.add_argument('--audience', choices=['public', 'domestic'], default='public')
    rep = commands.add_parser('report')
    rep.add_argument('--output', default='output/audit')
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    cfg = config['verification']
    if not 2 <= cfg['attempts'] <= 5 or not 1 <= cfg['sample_seconds'] <= 30:
        parser.error('attempts: 2..5; sample_seconds: 1..30')
    if not all(cfg[key] > 0 for key in ['http_timeout', 'process_timeout', 'request_delay', 'retry_delay']):
        parser.error('Timeouts and delays must be positive')
    if args.command == 'export':
        args.output = args.output or ('output/domestic' if args.audience == 'domestic' else 'output/public')
        if args.audience == 'domestic' and Path(args.output).resolve().is_relative_to(Path('output/public').resolve()):
            parser.error('Un export domestique doit rester hors de output/public (GitHub Pages)')
    db = connect(args.db)
    try:
        if args.command == 'bootstrap':
            result = {'imported_entries': bootstrap(db, args.upstream, config)}
        elif args.command == 'import':
            import_playlist(db, args.path, args.origin, args.country)
            result = {'imported': args.path}
        elif args.command == 'discover':
            result = {'pages': len(discover(db, config, 'data/evidence'))}
        elif args.command == 'epg-check':
            result = {'guides': verify_guides(db, config)}
        elif args.command == 'verify':
            if not 1 <= args.limit <= 100 or (args.country != 'unknown' and not (len(args.country) == 2 and args.country.isupper())):
                parser.error('limit: 1..100; country: ISO 3166-1 alpha-2 or unknown')
            result = {'run_id': verify(db, cfg, args.channel, args.source, args.limit,
                                       args.country, args.network, args.local_address, args.isp)}
        elif args.command == 'inventory':
            result = inventory(db, args.output, config)
        elif args.command == 'review':
            load_reviews(db, yaml.safe_load(Path(args.file).read_text(encoding='utf-8'))['reviews'])
            result = {'reviews_imported': True}
        elif args.command == 'export':
            result = export_playlists(db, config, args.output, args.audience)
        else:
            result = report(db, args.output)
            result = {k: v for k, v in result.items() if k not in {'new_candidates', 'changes'}} | {
                'new_candidates_count': len(result['new_candidates']), 'changes_count': len(result['changes'])}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as exc:
        print(f'Erreur: {exc}', file=sys.stderr)
        sys.exit(1)
