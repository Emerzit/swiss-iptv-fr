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
from fractions import Fraction
from pathlib import Path

from .catalog import digest, now


class CheckError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def remaining(cfg, timeout):
    budget = cfg.get('_deadline', float('inf')) - time.monotonic()
    if budget <= 0:
        raise CheckError('timeout', 'Source sampling time budget exhausted')
    return min(timeout, budget)


def attributes(line):
    return {key: quoted or unquoted for key, quoted, unquoted in
            re.findall(r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))', line)}


def frame_rate(value):
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def variant_info(variant):
    attrs = attributes(variant[2])
    dimensions = re.fullmatch(r'(\d+)x(\d+)', attrs.get('RESOLUTION', ''))
    return {'width': int(dimensions[1]) if dimensions else 0,
            'height': int(dimensions[2]) if dimensions else 0,
            'fps': frame_rate(attrs.get('FRAME-RATE', 0)),
            'bandwidth': int(attrs.get('AVERAGE-BANDWIDTH', attrs.get('BANDWIDTH', '0'))),
            'codecs': attrs.get('CODECS', '')}


def variant_rank(variant):
    info = variant_info(variant)
    return (info['width'] * info['height'], info['fps'], 'mp4a' in info['codecs'], info['bandwidth'])


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


def fetch(url, timeout=15, delay=1, max_bytes=2_000_000):
    public_url(url)
    time.sleep(delay)
    request = urllib.request.Request(url, headers={'User-Agent': 'Swiss-IPTV-FR/0.1'})
    with urllib.request.build_opener(SafeRedirect).open(request, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise CheckError('manifest_too_large', f'Document exceeded {max_bytes} bytes')
        return data, response.url


def manifest(url, kind, cfg, depth=0):
    if depth > 3:
        raise CheckError('invalid_manifest', 'Too many nested manifests')
    data, final_url = fetch(url, remaining(cfg, cfg['http_timeout']), cfg['request_delay'])
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
            # Masters can also advertise audio-only variants (RFC 8216 section 8.6).
            video_variants = [v for v in variants if re.search(
                r'(?:[:,])(?:RESOLUTION=\d+x\d+|VIDEO=")|(?:[",])(?:avc[1-4]|hev1|hvc1|dvh1|dvhe|av01|vp09|vp9|vp8)[.\",]', v[2], re.I)]
            choices = sorted(video_variants or variants, key=variant_rank, reverse=cfg.get('quality_mode', 'best') == 'best')
            rank = cfg.get('_variant_rank', 0) if depth == 0 else 0
            if rank >= len(choices):
                raise CheckError('no_more_variants', 'No remaining advertised variants')
            _, child, variant = choices[rank]
            evidence[0]['variants'] = [variant_info(v) for v in choices]
            evidence[0]['selected_variant'] = variant_info(choices[rank])
            evidence[0]['selected_variant_rank'] = rank
            try:
                selected, nested = manifest(urllib.parse.urljoin(final_url, child), 'hls', cfg, depth + 1)
            except (CheckError, urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
                exc.variant_count = len(choices)
                raise
            audio_group = re.search(r'(?:[:,])AUDIO="([^"]+)"', variant)
            audio_evidence = []
            if audio_group:
                tracks = []
                for line in lines:
                    if line.startswith('#EXT-X-MEDIA:'):
                        attrs = attributes(line)
                        if attrs.get('TYPE') == 'AUDIO' and attrs.get('GROUP-ID') == audio_group[1] and attrs.get('URI'):
                            tracks.append(attrs)
                if tracks:
                    track = min(tracks, key=lambda a: (a.get('LANGUAGE', '').lower() not in {'fr', 'fra', 'fre'}, a.get('DEFAULT') != 'YES'))
                    audio_url, audio_evidence = manifest(urllib.parse.urljoin(final_url, track['URI']), 'hls', cfg, depth + 1)
                    evidence[0]['audio_url'] = audio_url
                    evidence[0]['audio_language'] = track.get('LANGUAGE')
                    for proof in audio_evidence:
                        proof['role'] = 'audio'
            evidence[0]['live'] = all(p.get('live', True) for p in nested + audio_evidence)
            return selected, evidence + nested + audio_evidence
        segments = [line for line in lines if not line.startswith('#')]
        if not segments or '#EXTINF:' not in body:
            raise CheckError('invalid_manifest', 'No HLS media segments')
        for uri in segments + re.findall(r'URI="([^"]+)"', body):
            public_url(urllib.parse.urljoin(final_url, uri))
        evidence[0]['live'] = '#EXT-X-ENDLIST' not in body
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
        # FFmpeg exposes DASH representations as video/audio streams in document order.
        videos, audios = [], []
        period = next((e for e in tree.iter() if e.tag.split('}')[-1] == 'Period'), tree)
        for adaptation in period:
            if adaptation.tag.split('}')[-1] != 'AdaptationSet':
                continue
            for representation in adaptation:
                if representation.tag.split('}')[-1] != 'Representation':
                    continue
                props = {**adaptation.attrib, **representation.attrib}
                kind_hint = props.get('contentType', '') + props.get('mimeType', '')
                if 'video' in kind_hint or props.get('height'):
                    videos.append({'width': int(props.get('width', 0)), 'height': int(props.get('height', 0)),
                                   'fps': frame_rate(props.get('frameRate', 0)), 'bandwidth': int(props.get('bandwidth', 0)),
                                   'index': len(videos), 'codecs': props.get('codecs', '')})
                elif 'audio' in kind_hint:
                    audios.append({'index': len(audios), 'language': props.get('lang', '').lower()})
        if videos:
            choices = sorted(videos, key=lambda v: (v['width'] * v['height'], v['fps'], v['bandwidth']),
                             reverse=cfg.get('quality_mode', 'best') == 'best')
            rank = cfg.get('_variant_rank', 0)
            if rank >= len(choices):
                raise CheckError('no_more_variants', 'No remaining DASH video representations')
            evidence[0].update(variants=choices, selected_variant=choices[rank], dash_video_index=choices[rank]['index'])
        if audios:
            audio = min(audios, key=lambda a: a['language'] not in {'fr', 'fra', 'fre'})
            evidence[0].update(dash_audio_index=audio['index'], audio_language=audio['language'])
        evidence[0]['live'] = tree.attrib.get('type', 'static') == 'dynamic'
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


def decode(url, cfg, multicast=False, audio_url=None, video_index=0, audio_index=0):
    executable = ffmpeg_path(cfg['ffmpeg'])
    options = ['-protocol_whitelist', 'rtp,udp' if multicast else 'http,https,tcp,tls',
               '-rw_timeout', str(int(cfg['http_timeout'] * 1_000_000))]
    if not multicast:
        options += ['-user_agent', 'Swiss-IPTV-FR/0.1']
    command = [executable, '-hide_banner', '-nostdin', '-loglevel', 'info'] + options + ['-i', url]
    if audio_url:
        command += options + ['-i', audio_url]
    command += ['-t', str(cfg['sample_seconds']), '-map', f'0:v:{video_index}', '-map', '1:a:0' if audio_url else f'0:a:{audio_index}?',
                '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']
    try:
        result = subprocess.run(command, capture_output=True, timeout=remaining(cfg, cfg['process_timeout']),
                                encoding='utf-8', errors='replace', shell=False,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise CheckError('timeout', 'FFmpeg sample exceeded process timeout')
    stderr = result.stderr
    frames = max([int(n) for n in re.findall(r'^frame=(\d+)', result.stdout, re.M)] or [0])
    elapsed = max([int(n) for n in re.findall(r'^out_time_us=(\d+)', result.stdout, re.M)] or [0])
    input_log = stderr.split('Stream mapping:')[0]
    video_lines = [line for line in input_log.splitlines() if 'Video:' in line]
    audio_lines = [line for line in input_log.splitlines() if 'Audio:' in line]
    video_line = video_lines[video_index] if len(video_lines) > video_index else ''
    audio_line = audio_lines[0 if audio_url else audio_index] if len(audio_lines) > (0 if audio_url else audio_index) else ''
    video = re.search(r'Video: ([\w]+).*?\b(\d{2,5})x(\d{2,5})\b', video_line)
    audio = re.search(r'Audio: ([\w]+)', audio_line)
    fps = re.search(r'([\d.]+) fps', video_line)
    # AAC (LC) is a codec profile, not an ISO language tag. Tags precede "Audio:".
    language = re.search(r'Stream #\d+:\d+(?:\[[^]]+\])?\(([a-z]{2,3})\)', audio_line, re.I)
    details = {'returncode': result.returncode, 'frames': frames, 'decoded_seconds': elapsed / 1_000_000,
               'video_codec': video[1] if video else None,
               'width': int(video[2]) if video else None, 'height': int(video[3]) if video else None,
               'audio_codec': audio[1] if audio else None,
               'fps': float(fps[1]) if fps else 0.0,
               'audio_language': language[1].lower() if language else None,
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
    failures = []
    for rank in range(cfg.get('max_variant_attempts', 6)):
        remaining(cfg, cfg['process_timeout'])
        manifests = None
        try:
            selected, manifests = manifest(url, kind, {**cfg, '_variant_rank': rank})
            audio_url = next((proof['audio_url'] for proof in manifests if proof.get('audio_url')), None)
            decoded = decode(selected, cfg, audio_url=audio_url,
                             video_index=manifests[0].get('dash_video_index', 0),
                             audio_index=manifests[0].get('dash_audio_index', 0))
            declared = manifests[0].get('selected_variant', {})
            return {'decode': decoded, 'manifests': manifests,
                    'quality': {'mode': cfg.get('quality_mode', 'best'), 'variant_rank': rank,
                                'bandwidth': declared.get('bandwidth', 0), 'failed_higher_variants': failures},
                    'is_live': all(p.get('live', True) for p in manifests)}
        except (CheckError, urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
            status = getattr(exc, 'status', type(exc).__name__)
            if status == 'no_more_variants':
                break
            failures.append({'rank': rank, 'status': status})
            if isinstance(exc, CheckError) and status in {'unsafe_url', 'tool_missing', 'unsupported_protocol',
                    'encrypted', 'authentication_required', 'http_forbidden', 'legal_restriction', 'rate_limited'}:
                raise
            if not getattr(exc, 'variant_count', 0) and not (manifests and manifests[0].get('variants')):
                raise
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {401, 403, 429, 451}:
                raise
    raise CheckError('decode_error', 'No advertised variant passed actual decoding: ' + json.dumps(failures))


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
        source_cfg = {**cfg, '_deadline': time.monotonic() + cfg.get('source_timeout', 100)}
        outcomes = []
        for attempt in range(1, cfg['attempts'] + 1):
            details = {}
            try:
                details = check_once(source, source_cfg, network, local_address)
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
            recorded_details = re.sub(r'([?&](?:session|nimblesessionid|token|auth|signature|sig|expires|key|z32)=[^&\s"\\]*)',
                                      lambda m: m[0].split('=')[0] + '=SESSION_REDACTED', recorded_details, flags=re.I)
            db.execute('INSERT INTO checks (source_id,run_id,checked_at,country,network,attempt,status,details) VALUES (?,?,?,?,?,?,?,?)',
                       (source['id'], run_id, now(), country, network, attempt, status, recorded_details))
            db.commit()
            print(source['id'], source['channel_id'], attempt, status, flush=True)
            if status in {'playable', 'network_required', 'tool_missing', 'unsafe_url', 'encrypted',
                          'unsupported_protocol', 'unsupported_manifest', 'rate_limited'}:
                break
            if time.monotonic() >= source_cfg['_deadline']:
                break
            if attempt < cfg['attempts']:
                time.sleep(cfg['retry_delay'] * attempt)
        time.sleep(cfg['request_delay'])
    return run_id
