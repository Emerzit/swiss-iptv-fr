"""Create the requested GitHub repository / Pages site using existing Git authentication."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner', required=True)
    parser.add_argument('--name', default='swiss-iptv-fr')
    parser.add_argument('--pages', action='store_true', help='Enable branch publication after gh-pages exists')
    args = parser.parse_args()
    if not all(re.fullmatch('[A-Za-z0-9_.-]+', value) for value in [args.owner, args.name]):
        parser.error('Invalid GitHub owner or repository name')
    credential = subprocess.run(['git', 'credential', 'fill'],
        input=f'protocol=https\nhost=github.com\nusername={args.owner}\n\n',
        capture_output=True, text=True, timeout=30, check=True,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'})
    fields = dict(line.split('=', 1) for line in credential.stdout.splitlines() if '=' in line)
    token = fields.get('password')
    if not token:
        raise ValueError('Sign in to GitHub using Git Credential Manager first')

    def api(path, data=None, method='GET', missing=False):
        request = urllib.request.Request('https://api.github.com' + path,
            data=json.dumps(data).encode() if data is not None else None, method=method,
            headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                     'User-Agent': 'Swiss-IPTV-FR-Setup', 'X-GitHub-Api-Version': '2026-03-10',
                     'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            if missing and error.code == 404:
                return None
            raise RuntimeError(f'GitHub API {method} {path}: HTTP {error.code}') from None

    user = api('/user')
    if user['login'].casefold() != args.owner.casefold():
        raise ValueError('Authenticated account does not match the requested repository owner')
    path = f'/repos/{args.owner}/{args.name}'
    repo = api(path, missing=True)
    if repo is None:
        repo = api('/user/repos', {'name': args.name, 'private': False,
            'description': 'Swiss IPTV FR — chaînes francophones pour la Suisse, provenance et lectures vérifiées.',
            'homepage': f'https://{args.owner.lower()}.github.io/{args.name}/',
            'auto_init': False}, 'POST')
    elif 'Swiss IPTV FR' not in (repo.get('description') or ''):
        raise ValueError('Existing repository is not identified as this project; refusing to modify it')
    pages = None
    if args.pages:
        pages = api(path + '/pages', missing=True)
        body = {'source': {'branch': 'gh-pages', 'path': '/'}, 'build_type': 'legacy'}
        if pages is None:
            pages = api(path + '/pages', body, 'POST')
        elif pages.get('source') != body['source'] or pages.get('build_type') != 'legacy':
            api(path + '/pages', body, 'PUT')
            pages = api(path + '/pages')
    settings = {'enabled': True, 'repository': repo['clone_url']}
    (ROOT / 'data/github.local.yaml').write_text(yaml.safe_dump(settings, sort_keys=False), encoding='utf-8')
    result = {'repository': repo['html_url'], 'public': not repo['private'],
              'pages': pages.get('html_url') if pages else None}
    (ROOT / 'data/setup-github.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
