"""Download audit inputs, recording URLs, timestamps and hashes. No media scan."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'upstream'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Swiss-IPTV-FR-audit/0.1'})
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read(25_000_000)


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    records = []

    def save(url, name):
        try:
            content = fetch(url)
            path = DEST / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            records.append(dict(url=url, file=name, bytes=len(content),
                                sha256=hashlib.sha256(content).hexdigest(),
                                fetched_at=datetime.now(timezone.utc).isoformat()))
            print(name, len(content), flush=True)
            return content
        except Exception as exc:
            records.append(dict(url=url, file=name, error=str(exc)))
            print(name, type(exc).__name__, str(exc), flush=True)
        finally:
            (DEST / 'manifest.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
            time.sleep(0.25)

    for repo in ['iptv-ch/iptv-ch.github.io', 'iptv-org/iptv', 'iptv-org/database', 'iptv-org/epg']:
        owner, name = repo.split('/')
        commit = json.loads(fetch(f'https://api.github.com/repos/{repo}/commits/master'))['sha']
        tree = json.loads(fetch(f'https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1'))
        save(f'https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1', f'{name}/tree.json')
        paths = ['README.md', 'LICENSE', 'CONTRIBUTING.md', 'package.json']
        paths += [entry['path'] for entry in tree['tree']
                  if entry['path'].startswith('.github/workflows/') and entry['path'].endswith(('.yml', '.yaml'))]
        if owner == 'iptv-ch':
            paths += [e['path'] for e in tree['tree'] if '/' not in e['path']
                      and e['path'].endswith(('.m3u', '.m3u8', '.mpd')) and 'radio' not in e['path']]
        if name == 'iptv':
            paths += ['scripts/commands/playlist/test.ts', 'scripts/commands/playlist/validate.ts',
                      'streams/ch.m3u', 'streams/fr.m3u', 'streams/be.m3u']
        available = {e['path'] for e in tree['tree']}
        for path in dict.fromkeys(paths):
            if path in available:
                save(f'https://raw.githubusercontent.com/{repo}/{commit}/{path}', f'{name}/{path}')
    for file in ['channels', 'feeds', 'logos']:
        save(f'https://iptv-org.github.io/api/{file}.json', f'api/{file}.json')
    save('https://iptv-org.github.io/iptv/languages/fra.m3u', 'fra.m3u')


if __name__ == '__main__':
    main()
