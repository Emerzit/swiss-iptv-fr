"""Restore curated channel identities and exact sources, without approving new links."""
from pathlib import Path

import yaml

from .catalog import add_source


def seed_catalog(db, path):
    document = yaml.safe_load(Path(path).read_text(encoding='utf-8'))
    with db:
        for item in document['sources']:
            channel = item['channel']
            fields = ('id', 'name', 'country', 'languages', 'category', 'logo', 'epg_id', 'website', 'regional')
            values = tuple(channel.get(key, 0 if key == 'regional' else '') for key in fields)
            db.execute('''INSERT INTO channels (id,name,country,languages,category,logo,epg_id,website,regional)
                VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,regional=excluded.regional''', values)
            if not item['origins']:
                raise ValueError('Curated source requires provenance')
            for origin in item['origins']:
                sid = add_source(db, channel['id'], item['url'], origin['url'], origin['sha256'],
                                 origin['observed_at'], item.get('official', False), item.get('epg_id', channel['id']))
                if sid != item['source_id']:
                    raise ValueError('Curated source identity does not match its URL')
            db.execute('UPDATE sources SET priority=? WHERE id=?', (item.get('priority', 100), sid))
