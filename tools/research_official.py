"""Targeted source research. Archive public documents; never approve a stream."""
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from swiss_iptv.catalog import now
from swiss_iptv.verify import fetch

DEST = Path('data/evidence/expansion')


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    records = []

    def document(url, parent=None):
        record = {'url': url, 'parent': parent, 'observed_at': now()}
        try:
            data, final = fetch(url, timeout=15, delay=1)
            sha = hashlib.sha256(data).hexdigest()
            (DEST / f'{sha}.txt').write_bytes(data)
            body = html.unescape(data.decode('utf-8', errors='replace')).replace('\\/', '/')
            record.update(final_url=final, sha256=sha)
            streams = sorted(set(re.findall(r'https?://[^\s<>"\x27\x60\\]+?\.(?:m3u8|mpd)(?:\?[^\s<>"\x27\x60\\]*)?', body)))
            record['streams'] = streams
            if streams:
                print('STREAMS', url, json.dumps(streams, ensure_ascii=False), flush=True)
            return body, final
        except Exception as exc:
            record['error'] = str(exc)
            print('ERROR', url, type(exc).__name__, str(exc), flush=True)
            return '', url
        finally:
            records.append(record)
            (DEST / 'documents.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')

    for page, pattern in [
        ('https://www.canalalpha.ch/tv', r'/(?:187-|654-|794-|479-|9cb54|app/tv/page-)'),
        ('https://canal9.ch/', r'canal9live\.js'),
        ('https://www.lemanbleu.ch/fr/Direct/Direct.html', r'assets\.lemanbleu\.ch'),
        ('https://www.tvm3.tv/', r'player\.infomaniak\.com'),
        ('https://bx1.be/lives/direct-tv/', r'player|live'),
        ('https://www.tvmonaco.com/', r'(?:index|main|player).*\.js'),
    ]:
        print('PAGE', page, flush=True)
        body, final = document(page)
        resources = re.findall(r'(?:src|href)=["\x27]([^"\x27]+)', body)
        resources = [urljoin(final, resource) for resource in resources if re.search(pattern, resource)]
        for resource in dict.fromkeys(resources[:6]):
            document(resource, final)
        snippets = re.findall(r'.{0,60}(?:dailymotion|xev0m|videoId|data-player-id|channel=|liveUrl).{0,100}', body, re.I)
        if snippets:
            print('HINTS', json.dumps(snippets[:8], ensure_ascii=False), flush=True)
    for urn in ['3608506', '3608517', '1967124']:
        url = f'https://il.srgssr.ch/integrationlayer/2.0/mediaComposition/byUrn/urn:rts:video:{urn}.json'
        body, final = document(url)
        if body:
            obj = json.loads(body)
            print('SRG', urn, json.dumps({key: obj.get(key) for key in ['mediaType', 'title', 'channelId', 'livestream', 'blockReason']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
