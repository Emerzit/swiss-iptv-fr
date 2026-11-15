"""Conservative discovery from public official HTML only; no player token extraction."""
import hashlib
import html
import json
from functools import lru_cache
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from .catalog import add_source, now
from .verify import fetch


def document_text(data):
    text = html.unescape(data.decode('utf-8', errors='replace')).replace('\\/', '/')
    return re.sub(r'\\u(00[0-7][0-9a-fA-F])', lambda match: chr(int(match[1], 16)), text)


def discover(db, config, dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    result = []
    cfg = config['verification']
    @lru_cache(maxsize=64)
    def read(url):
        if urlparse(url).path.endswith(('.js', '.mjs')):
            return fetch(url, cfg['http_timeout'], cfg['request_delay'], max_bytes=8_000_000)
        return fetch(url, cfg['http_timeout'], cfg['request_delay'])

    for page in config.get('official_pages', []):
        record = {'channel_id': page['channel_id'], 'url': page['url'], 'observed_at': now()}
        try:
            content, final_url = read(page['url'])
            sha = hashlib.sha256(content).hexdigest()
            (dest / f'{sha}.html').write_bytes(content)
            body = document_text(content)
            documents = [(final_url, body, sha)]
            browser = Path(config.get('discovery', {}).get('browser', ''))
            if page.get('render_html') and browser.is_file():
                # Optional ordinary browser rendering, without a user profile, stealth or private-network access.
                rendered = dest / 'rendered.html'
                try:
                    browser_result = subprocess.run([str(browser.resolve()), 'fetch', final_url, '--dump', 'html',
                        '--timeout', '15', '--wait', '2', '--output', str(rendered.resolve())],
                        capture_output=True, timeout=22, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if browser_result.returncode == 0 and rendered.exists() and rendered.stat().st_size <= 8_000_000:
                        rendered_body = rendered.read_bytes()
                        rendered_sha = hashlib.sha256(rendered_body).hexdigest()
                        (dest / f'{rendered_sha}.html').write_bytes(rendered_body)
                        rendered_text = document_text(rendered_body)
                        documents.append((final_url, rendered_text, rendered_sha))
                        body += '\n' + rendered_text
                        record['browser_rendered'] = True
                except (OSError, subprocess.TimeoutExpired):
                    record['browser_rendered'] = False
            if page.get('follow_live_links'):
                links = [urljoin(final_url, html.unescape(link)) for link in
                         re.findall(r'<a\b[^>]*href=["\x27]([^"\x27]+)', body, re.I)
                         if re.search(r'direct|\blive\b|webtv|watch|player', link, re.I)]
                for link in list(dict.fromkeys(links))[:3]:
                    if urlparse(link).hostname != urlparse(final_url).hostname or link == final_url:
                        continue
                    try:
                        linked_data, linked_url = read(link)
                        linked_sha = hashlib.sha256(linked_data).hexdigest()
                        (dest / f'{linked_sha}.html').write_bytes(linked_data)
                        linked_body = document_text(linked_data)
                        documents.append((linked_url, linked_body, linked_sha))
                        # The actual public player often sits on /direct rather than the homepage.
                        body += '\n' + linked_body
                    except Exception as exc:
                        record.setdefault('resource_errors', []).append({'url': link, 'error': str(exc)})
            allowed_srg = None
            api_blocked = False
            if page.get('json_url'):
                api_url = page['json_url']
                if api_url not in body:
                    raise ValueError('JSON configuration link not present in the official page')
                data, api_url = read(api_url)
                api_sha = hashlib.sha256(data).hexdigest()
                (dest / f'{api_sha}.json').write_bytes(data)
                attributes = json.loads(data).get('data', {}).get('attributes', {})
                error = attributes.get('error') or {}
                if error.get('code'):
                    record['access_status'] = 'geo_restricted' if error['code'] == 'ERROR_GEOLOCATION' else 'official_player_error'
                    record['official_error'] = error['code']
                    record['access_country'] = attributes.get('restriction', {}).get('geoblocking', {}).get('userCountryCode', 'unknown')
                    api_blocked = True
                documents.append((api_url, data.decode('utf-8'), api_sha))
            if page.get('carac_slug'):
                slug = page['carac_slug']
                if not re.fullmatch(r'carac-[1-5]', slug) or 'https://api.m0g.ch/v1' not in body or slug not in final_url:
                    raise ValueError('Carac API identity not established from the official page')
                api_url = f'https://api.m0g.ch/v1/channel/{slug}'
                data, api_url = read(api_url)
                api_sha = hashlib.sha256(data).hexdigest()
                (dest / f'{api_sha}.json').write_bytes(data)
                player_url = json.loads(data).get('live_player', '')
                if urlparse(player_url).hostname != 'player.infomaniak.com':
                    raise ValueError('Unexpected Carac live player')
                documents.append((api_url, f'<iframe src="{html.escape(player_url, quote=True)}"></iframe>', api_sha))
            if page.get('srg_urn'):
                urn = page['srg_urn']
                if urn not in body or not re.fullmatch(r'urn:rts:video:\d+', urn):
                    raise ValueError('SRG media identity not present in the official page')
                api_url = f'https://il.srgssr.ch/integrationlayer/2.0/mediaComposition/byUrn/{urn}.json'
                data, api_url = read(api_url)
                api_sha = hashlib.sha256(data).hexdigest()
                (dest / f'{api_sha}.json').write_bytes(data)
                resources = []
                def collect(value):
                    if isinstance(value, dict):
                        resources.extend(value.get('resourceList', []))
                        for child in value.values():
                            collect(child)
                    elif isinstance(value, list):
                        for child in value:
                            collect(child)
                collect(json.loads(data))
                allowed_srg = {r['url'] for r in resources if r.get('url') and not r.get('drmList')
                               and r.get('tokenType', 'NONE') == 'NONE'}
                record['drm_resources'] = sum(bool(r.get('drmList')) for r in resources)
                record['token_resources'] = sum(r.get('tokenType', 'NONE') != 'NONE' for r in resources)
                if resources and not allowed_srg:
                    record['access_status'] = 'drm_required' if record['drm_resources'] else 'token_required'
                documents.append((api_url, json.dumps(sorted(allowed_srg)), api_sha))
            assets = re.findall(r'(?:src|href)=["\x27]([^"\x27]+\.(?:jsx?|mjs)(?:\?[^"\x27]*)?)["\x27]', body, re.I)
            assets = list(dict.fromkeys(a for a in assets if any(re.search(p, a) for p in page.get('script_patterns', []))))
            if page.get('follow_live_links'):
                assets.sort(key=lambda a: (not bool(re.search('player|lecteur|stream|direct|webtv', a, re.I)),
                                          urlparse(urljoin(final_url, a)).hostname != urlparse(final_url).hostname))
            for asset in assets[:min(12, page.get('script_limit', 2))]:
                asset = urljoin(final_url, html.unescape(asset))
                try:
                    nested, asset_url = read(asset)
                except Exception as exc:
                    record.setdefault('resource_errors', []).append({'url': asset, 'error': str(exc)})
                    continue
                nested_sha = hashlib.sha256(nested).hexdigest()
                (dest / f'{nested_sha}.js').write_bytes(nested)
                documents.append((asset_url, document_text(nested), nested_sha))
                imports = re.findall(r'from["\x27]([^"\x27]+\.js)', documents[-1][1])
                for child in [a for a in imports if any(re.search(p, a) for p in page.get('script_patterns', []))][:1]:
                    child = urljoin(asset_url, child)
                    if urlparse(child).hostname != urlparse(asset_url).hostname:
                        continue
                    child_data, child_url = read(child)
                    child_sha = hashlib.sha256(child_data).hexdigest()
                    (dest / f'{child_sha}.js').write_bytes(child_data)
                    documents.append((child_url, document_text(child_data), child_sha))
            if page.get('follow_live_links'):
                # Only literal, public player configuration files, never license/key/token APIs.
                for document_url, document, _ in list(documents):
                    configs = re.findall(r'["\x27]([^"\x27\s<>]+\.json(?:\?[^"\x27\s<>]*)?)["\x27]', document)
                    for location in list(dict.fromkeys(configs))[:2]:
                        if (not re.search('config|player|live|stream', location, re.I) or
                                re.search('license|drm|key|token|auth|session|secret', location, re.I)):
                            continue
                        config_url = urljoin(document_url, location)
                        if urlparse(config_url).hostname != urlparse(document_url).hostname:
                            continue
                        try:
                            settings, config_url = read(config_url)
                            parsed_settings = json.loads(settings)
                            config_sha = hashlib.sha256(settings).hexdigest()
                            (dest / f'{config_sha}.json').write_bytes(settings)
                            documents.append((config_url, json.dumps(parsed_settings), config_sha))
                        except Exception as exc:
                            record.setdefault('resource_errors', []).append({'url': config_url, 'error': str(exc)})
            embeds = [embed for _, document, _ in documents
                      for embed in re.findall(r'<iframe\b[^>]*\bsrc=["\x27]([^"\x27]+)', document, re.I)]
            embeds = [embed for embed in dict.fromkeys(embeds)
                      if not page.get('embed_pattern') or re.search(page['embed_pattern'], embed)]
            embeds = [embed for embed in embeds if urlparse(urljoin(final_url, html.unescape(embed))).hostname == 'player.infomaniak.com'
                      or (page.get('follow_live_links') and urlparse(urljoin(final_url, html.unescape(embed))).hostname == urlparse(final_url).hostname
                          and re.search('live|direct|player', embed, re.I) and not re.search('vod|replay', embed, re.I))]
            for embed in embeds[:2]:
                embed = html.unescape(embed)
                embed = urljoin(final_url, embed)
                if (urlparse(embed).hostname == urlparse(final_url).hostname and page.get('follow_live_links') and
                        re.search(r'live|direct|player', embed, re.I) and not re.search('vod|replay', embed, re.I)):
                    nested, embed_url = read(embed)
                    nested_sha = hashlib.sha256(nested).hexdigest()
                    (dest / f'{nested_sha}.html').write_bytes(nested)
                    documents.append((embed_url, document_text(nested), nested_sha))
                    continue
                if urlparse(embed).hostname != 'player.infomaniak.com':
                    continue
                nested, embed_url = read(embed)
                nested_sha = hashlib.sha256(nested).hexdigest()
                (dest / f'{nested_sha}.html').write_bytes(nested)
                documents.append((embed_url, document_text(nested), nested_sha))
                if page.get('allow_embed', False):
                    query = dict(parse_qsl(urlparse(embed).query))
                    if query.get('channel'):
                        api_url = 'https://player.infomaniak.com/playerConfig.php?' + urlencode(
                            {key: query[key] for key in ['channel', 'player'] if key in query})
                        data, api_url = read(api_url)
                        api_sha = hashlib.sha256(data).hexdigest()
                        (dest / f'{api_sha}.json').write_bytes(data)
                        settings = json.loads(data)
                        clear_urls = [item['url'] for item in settings.get('data', settings).get('integrations', [])
                                      if item.get('constant_url') and item.get('type') in {'hls', 'ios'}]
                        documents.append((api_url, json.dumps(clear_urls), api_sha))
            candidates = []
            for document_url, document, document_sha in documents:
                # A commented-out old manifest is not a public player's current source.
                if urlparse(document_url).path.endswith(('.js', '.jsx', '.mjs')):
                    document = re.sub(r'(?m)^\s*//[^\n]*|/\*.*?\*/', '', document, flags=re.S)
                found = sorted(set(re.findall(r'https?://[^\s<>"\x27\x60\\]+?\.(?:m3u8|mpd)(?:\?[^\s<>"\x27\x60\\]*)?', document)))
                # A TV page also contains replay manifests: never treat those as linear TV.
                found = [url for url in found if not re.search(r'(?:[./_-])vod(?:[./_\d-])|replay', url, re.I)]
                if api_blocked:
                    found = []
                if allowed_srg is not None:
                    found = [url for url in found if url in allowed_srg]
                if 'player.infomaniak.com' in document_url and not page.get('allow_embed', False):
                    found = []  # shared players or wrong regional/language variant need explicit mapping
                if page.get('stream_pattern'):
                    found = [url for url in found if re.search(page['stream_pattern'], url)]
                for url in found:
                    if not any(re.search(r'session|token|auth|sign|expire|key|z32', key, re.I)
                               for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True)):
                        candidates.append((url, document_url, document_sha))
            urls = sorted({url for url, _, _ in candidates})
            if page.get('require_unique_stream') and len(urls) > 1:
                record['access_status'] = 'ambiguous_channel_identity'
                record['ambiguous_stream_count'] = len(urls)
                urls, candidates = [], []
            for url, document_url, document_sha in candidates:
                add_source(db, page['channel_id'], url, document_url, document_sha, record['observed_at'], official=True)
                if document_url != final_url:
                    add_source(db, page['channel_id'], url, final_url, sha, record['observed_at'], official=True)
            record.update(final_url=final_url, sha256=sha, streams=sorted(set(urls)),
                          resources=[{'url': u, 'sha256': h} for u, text, h in documents])
            if record.get('access_status') in {'drm_required', 'token_required'} or (
                record.get('access_status') == 'geo_restricted' and record.get('access_country') == 'CH'
            ):
                db.execute("UPDATE sources SET active=0 WHERE channel_id=? AND official=1 AND operator=''", (page['channel_id'],))
        except Exception as exc:
            record['error'] = f'{type(exc).__name__}: {exc}'
        result.append(record)
        print(page['channel_id'], len(record.get('streams', [])), record.get('error', ''), flush=True)
    db.commit()
    (dest / 'discovery.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
