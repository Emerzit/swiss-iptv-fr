"""Publish only reviewed static exports; authentication stays in Git's credential helper."""
from datetime import datetime, timezone, timedelta
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlparse

from .catalog import parse_m3u


PLAYLISTS = ('swiss-fr', 'swiss-fr-internet', 'swiss-fr-multicast', 'swiss-fr-regional', 'swiss-fr-news')
SITE_FILES = tuple(name + '.m3u' for name in PLAYLISTS) + ('index.html', 'status.json')


def site_payload(directory):
    directory = Path(directory)
    payload = {name: (directory / name).read_bytes() for name in SITE_FILES}
    status = json.loads(payload['status.json'])
    if status.get('audience') != 'public':
        raise ValueError('Only public exports can be published')
    generated = datetime.fromisoformat(status['generated_at'])
    age = datetime.now(timezone.utc) - generated if generated.tzinfo else None
    if age is None or age < timedelta(minutes=-5) or age > timedelta(hours=1):
        raise ValueError('Regenerate public exports before publishing (maximum age: one hour)')
    for name in PLAYLISTS:
        text = payload[name + '.m3u'].decode('utf-8-sig')
        if text.count('#EXTM3U') != 1 or not text.startswith('#EXTM3U'):
            raise ValueError('Invalid generated M3U header')
        entries = list(parse_m3u(text))
        if len(entries) != status['playlists'][name]:
            raise ValueError('Playlist count does not match public status')
        for entry in entries:
            url = urlparse(entry['url'].replace('://@', '://'))
            if url.username or url.password or '/tok_' in url.path or re.search(
                r'(?:^|&)(?:session|token|auth|signature|sig|key|expires|z32)=', url.query, re.I
            ):
                raise ValueError('Credentials or temporary sessions must not be published')
            if url.scheme in {'rtp', 'udp'}:
                if not ipaddress.ip_address(url.hostname).is_multicast:
                    raise ValueError('Expected multicast group')
            elif url.scheme not in {'http', 'https'} or not url.hostname:
                raise ValueError('Expected a public stream URL')
    payload['.nojekyll'] = b''
    return payload


def repository_url(value):
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', value):
        raise ValueError('Expected an HTTPS GitHub repository URL without credentials')
    return value


def publish_site(directory, repository, cache_directory):
    payload = site_payload(directory)  # Validate all files before contacting GitHub.
    repository = repository_url(repository)
    cache = Path(cache_directory).resolve()
    cache.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never',
           'GIT_AUTHOR_NAME': 'Swiss IPTV FR', 'GIT_COMMITTER_NAME': 'Swiss IPTV FR',
           'GIT_AUTHOR_EMAIL': 'swiss-iptv-fr@users.noreply.github.com',
           'GIT_COMMITTER_EMAIL': 'swiss-iptv-fr@users.noreply.github.com'}

    def git(*args, data=None, check=True):
        result = subprocess.run(['git', '--git-dir', str(cache), *args], input=data,
                                capture_output=True, timeout=90, env=env,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if check and result.returncode:
            raise RuntimeError('Git publication failed: ' + result.stderr.decode('utf-8', errors='replace')[-1500:])
        return result

    if not cache.exists():
        subprocess.run(['git', 'init', '--bare', str(cache)], check=True, capture_output=True, timeout=30, env=env,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (cache / 'swiss-iptv-publisher').write_text('1', encoding='ascii')
    elif not (cache / 'swiss-iptv-publisher').is_file():
        raise ValueError('Refusing to use an unrelated repository as publication cache')
    tree_lines = []
    for name, content in sorted(payload.items()):
        sha = git('hash-object', '-w', '--stdin', data=content).stdout.decode().strip()
        tree_lines.append(f'100644 blob {sha}\t{name}\n')
    tree = git('mktree', data=''.join(tree_lines).encode()).stdout.decode().strip()
    # No checkout or force push: a concurrent publisher causes a normal rejection and one retry.
    for attempt in range(2):
        refs = git('ls-remote', '--exit-code', repository, 'refs/heads/gh-pages', check=False)
        if refs.returncode not in {0, 2}:
            raise RuntimeError('Cannot read GitHub publication branch: ' + refs.stderr.decode(errors='replace')[-1000:])
        parent = refs.stdout.decode().split()[0] if refs.returncode == 0 else None
        if parent:
            git('fetch', '--no-tags', repository, 'refs/heads/gh-pages')
            if git('rev-parse', parent + '^{tree}').stdout.decode().strip() == tree:
                return {'changed': False, 'commit': parent, 'branch': 'gh-pages', 'repository': repository}
        args = ['commit-tree', tree, '-m', 'Actualiser les playlists vérifiées depuis la Suisse']
        if parent:
            args += ['-p', parent]
        commit = git(*args).stdout.decode().strip()
        pushed = git('push', '--porcelain', repository, commit + ':refs/heads/gh-pages', check=False)
        if pushed.returncode == 0:
            return {'changed': True, 'commit': commit, 'branch': 'gh-pages', 'repository': repository}
    raise RuntimeError('GitHub rejected publication; the previous online version remains unchanged')
