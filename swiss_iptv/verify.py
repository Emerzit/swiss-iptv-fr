"""Bounded sampling of clear streams. A manifest response alone never passes."""
import ipaddress
import json
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from .catalog import digest, now


class CheckError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def public_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise CheckError('unsafe_url', 'Only public HTTP(S), without embedded credentials')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise CheckError('unsafe_url', 'Private, reserved or local destination')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, timeout=15, delay=1):
    public_url(url)
    time.sleep(delay)
    request = urllib.request.Request(url, headers={'User-Agent': 'Swiss-IPTV-FR/0.1'})
    with urllib.request.build_opener(SafeRedirect).open(request, timeout=timeout) as response:
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise CheckError('manifest_too_large', 'Manifest exceeded 2 MB')
        return data, response.url


def manifest(url, kind, cfg, depth=0):
    if depth > 3:
        raise CheckError('invalid_manifest', 'Too many nested manifests')
    data, final_url = fetch(url, cfg['http_timeout'], cfg['request_delay'])
    body = data.decode('utf-8-sig')
    evidence = [{'url': final_url, 'sha256': digest(body)}]
    if kind == 'hls' or body.lstrip().startswith('#EXTM3U'):
        if not body.lstrip().startswith('#EXTM3U'):
            raise CheckError('invalid_manifest', 'Expected HLS, received another document')
        # Encrypted HLS is deliberately left for a separate access review, including AES-128.
        keys = [line for line in body.splitlines() if line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:'))]
        if any(not re.search(r'(?:^|[:,])METHOD=NONE(?:,|$)', line) for line in keys):
            raise CheckError('encrypted', 'Encrypted HLS: no key requested')
        if '#EXT-X-CONTENT-STEERING' in body:
            raise CheckError('unsupported_manifest', 'Content steering requires separate review')
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        variants = []
        for i, line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF:') and i + 1 < len(lines):
                bandwidth = re.search(r'(?:[:,])BANDWIDTH=(\d+)', line)
                variants.append((int(bandwidth[1]) if bandwidth else 0, lines[i + 1], line))
        if variants:
            # ponytail: select one low-bandwidth video variant; exhaustive variant QA is phase 2.
            # Masters can also advertise audio-only variants (RFC 8216 section 8.6).
            video_variants = [v for v in variants if re.search(
                r'(?:[:,])(?:RESOLUTION=\d+x\d+|VIDEO=")|(?:[",])(?:avc[1-4]|hev1|hvc1|dvh1|dvhe|av01|vp09|vp9|vp8)[.\",]', v[2], re.I)]
            _, child, variant = min(video_variants or variants)
            selected, nested = manifest(urllib.parse.urljoin(final_url, child), 'hls', cfg, depth + 1)
            audio_group = re.search(r'(?:[:,])AUDIO="([^"]+)"', variant)
            audio_evidence = []
            if audio_group:
                tracks = []
                for line in lines:
                    if line.startswith('#EXT-X-MEDIA:'):
                        attrs = {key: quoted or unquoted for key, quoted, unquoted in
                                 re.findall(r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', line)}
                        if attrs.get('TYPE') == 'AUDIO' and attrs.get('GROUP-ID') == audio_group[1] and attrs.get('URI'):
                            tracks.append(attrs)
                if tracks:
                    track = min(tracks, key=lambda a: (a.get('LANGUAGE', '').lower() not in {'fr', 'fra'}, a.get('DEFAULT') != 'YES'))
                    audio_url, audio_evidence = manifest(urllib.parse.urljoin(final_url, track['URI']), 'hls', cfg, depth + 1)
                    evidence[0]['audio_url'] = audio_url
                    evidence[0]['audio_language'] = track.get('LANGUAGE')
                    for proof in audio_evidence:
                        proof['role'] = 'audio'
            return selected, evidence + nested + audio_evidence
        segments = [line for line in lines if not line.startswith('#')]
        if not segments or '#EXTINF:' not in body:
            raise CheckError('invalid_manifest', 'No HLS media segments')
        for uri in segments + re.findall(r'URI="([^"]+)"', body):
            public_url(urllib.parse.urljoin(final_url, uri))
        return final_url, evidence
    if kind == 'dash':
        tree = ET.fromstring(data)
        if tree.tag.split('}')[-1] != 'MPD':
            raise CheckError('invalid_manifest', 'Expected MPD')
        if any(e.tag.split('}')[-1] == 'ContentProtection' for e in tree.iter()):
            raise CheckError('encrypted', 'DASH ContentProtection: no DRM handling')
        for element in tree.iter():
            if any('xlink' in attr for attr in element.attrib):
                raise CheckError('unsupported_manifest', 'External DASH XLink not followed')
            for attr in ('media', 'initialization', 'sourceURL'):
                if attr in element.attrib:
                    public_url(urllib.parse.urljoin(final_url, element.attrib[attr]))
            if element.tag.split('}')[-1] == 'BaseURL' and element.text:
                public_url(urllib.parse.urljoin(final_url, element.text.strip()))
        return final_url, evidence
    raise CheckError('unsupported_protocol', 'Only HLS/DASH manifests in Internet prototype')


def ffmpeg_path(configured='ffmpeg'):
    binary = shutil.which(configured)
    if binary:
        return binary
    # Optional convenience for environments already providing imageio's portable binary.
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise CheckError('tool_missing', 'Install FFmpeg or set verification.ffmpeg')


def decode(url, cfg, multicast=False, audio_url=None):
    executable = ffmpeg_path(cfg['ffmpeg'])
    options = ['-protocol_whitelist', 'rtp,udp' if multicast else 'http,https,tcp,tls',
               '-rw_timeout', str(int(cfg['http_timeout'] * 1_000_000))]
    if not multicast:
        options += ['-user_agent', 'Swiss-IPTV-FR/0.1']
    command = [executable, '-hide_banner', '-nostdin', '-loglevel', 'info'] + options + ['-i', url]
    if audio_url:
        command += options + ['-i', audio_url]
    command += ['-t', str(cfg['sample_seconds']), '-map', '0:v:0', '-map', '1:a:0' if audio_url else '0:a:0?',
                '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']
    try:
        result = subprocess.run(command, capture_output=True, timeout=cfg['process_timeout'],
                                encoding='utf-8', errors='replace', shell=False,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise CheckError('timeout', 'FFmpeg sample exceeded process timeout')
    stderr = result.stderr
    frames = max([int(n) for n in re.findall(r'^frame=(\d+)', result.stdout, re.M)] or [0])
    elapsed = max([int(n) for n in re.findall(r'^out_time_us=(\d+)', result.stdout, re.M)] or [0])
    input_log = stderr.split('Stream mapping:')[0]
    video = re.search(r'Video: ([\w]+).*?\b(\d{2,5})x(\d{2,5})\b', input_log)
    audio = re.search(r'Audio: ([\w]+)', input_log)
    details = {'returncode': result.returncode, 'frames': frames, 'decoded_seconds': elapsed / 1_000_000,
               'video_codec': video[1] if video else None,
               'width': int(video[2]) if video else None, 'height': int(video[3]) if video else None,
               'audio_codec': audio[1] if audio else None,
               'audio_decoded': bool(audio and any(float(n) > 0 for n in re.findall(r'audio:\s*([\d.]+)(?:KiB|kB)', stderr))),
               'ffmpeg_version': Path(executable).name}
    if result.returncode == 0 and frames >= 2 and elapsed >= cfg['sample_seconds'] * 800_000:
        return details
    if re.search(r'(?:HTTP error|Server returned) 403\b', stderr):
        raise CheckError('http_forbidden', 'FFmpeg HTTP 403: cause undetermined')
    if re.search(r'(?:HTTP error|Server returned) 401\b', stderr):
        raise CheckError('authentication_required', 'FFmpeg HTTP 401')
    if re.search(r'(?:HTTP error|Server returned) (?:404|410)\b', stderr):
        raise CheckError('not_found', 'FFmpeg media missing: ' + stderr[-1500:])
    details['ffmpeg_log'] = stderr[-2000:]
    raise CheckError('decode_error', json.dumps(details))


def check_once(source, cfg, network='internet', local_address=''):
    kind, url = source['protocol'], source['url']
    if kind in {'udp', 'rtp'}:
        if network == 'internet' or source['operator'] != network or network == 'unknown':
            raise CheckError('network_required', 'Run on the explicitly confirmed compatible operator network')
        parsed = urllib.parse.urlparse(url.replace('://@', '://'))
        address = ipaddress.ip_address(parsed.hostname or '')
        if not address.is_multicast or not parsed.port:
            raise CheckError('unsafe_url', 'Expected a multicast IP address and port')
        if local_address:
            ipaddress.ip_address(local_address)
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode({'localaddr': local_address})
        return {'decode': decode(url, cfg, multicast=True), 'manifests': []}
    selected, manifests = manifest(url, kind, cfg)
    audio_url = next((proof['audio_url'] for proof in manifests if proof.get('audio_url')), None)
    return {'decode': decode(selected, cfg, audio_url=audio_url), 'manifests': manifests}


def verify(db, cfg, channel=None, source_id=None, limit=10, country='unknown', network='internet', local_address='', isp='unknown'):
    run_id = now()
    query = 'SELECT * FROM sources WHERE active=1'
    params = []
    if source_id:
        query += ' AND id=?'
        params.append(source_id)
    elif channel:
        query += ' AND channel_id=?'
        params.append(channel)
    else:
        query += ' AND official=1'
    query += ' ORDER BY official DESC,priority,id LIMIT ?'
    params.append(limit)
    rows = db.execute(query, params).fetchall()
    for source in rows:
        outcomes = []
        for attempt in range(1, cfg['attempts'] + 1):
            details = {}
            try:
                details = check_once(source, cfg, network, local_address)
                status = 'playable'
            except CheckError as exc:
                status, details = exc.status, {'reason': str(exc)}
            except urllib.error.HTTPError as exc:
                status = {401: 'authentication_required', 403: 'http_forbidden', 404: 'not_found',
                          410: 'not_found', 429: 'rate_limited', 451: 'legal_restriction'}.get(exc.code, 'http_error')
                details = {'http_status': exc.code, 'reason': exc.reason}
            except (urllib.error.URLError, OSError) as exc:
                status, details = 'network_error', {'reason': str(exc)}
            except (ValueError, ET.ParseError, UnicodeError) as exc:
                status, details = 'invalid_manifest', {'reason': str(exc)}
            outcomes.append(status)
            details['connection_isp'] = isp
            if len(outcomes) == cfg['attempts'] and all(s == 'not_found' for s in outcomes):
                status = 'unavailable'
                details['reason'] = 'Repeated HTTP 404/410 from this test context'
            # Transparent CDN redirects can contain short-lived sessions bound to the viewer IP.
            # Keep the stable entry URL and manifest hashes, not reusable session URLs in reports.
            recorded_details = re.sub(r'/tok_[^/\s"\\]+/', '/SESSION_REDACTED/', json.dumps(details))
            db.execute('INSERT INTO checks (source_id,run_id,checked_at,country,network,attempt,status,details) VALUES (?,?,?,?,?,?,?,?)',
                       (source['id'], run_id, now(), country, network, attempt, status, recorded_details))
            db.commit()
            print(source['id'], source['channel_id'], attempt, status, flush=True)
            if status in {'playable', 'network_required', 'tool_missing', 'unsafe_url', 'encrypted',
                          'unsupported_protocol', 'unsupported_manifest', 'rate_limited'}:
                break
            if attempt < cfg['attempts']:
                time.sleep(cfg['retry_delay'] * attempt)
        time.sleep(cfg['request_delay'])
    return run_id
