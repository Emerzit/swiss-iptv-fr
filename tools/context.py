"""Optional country observation for the test connection, without retaining its IP."""
import hashlib
import json
from pathlib import Path
import urllib.request
from datetime import datetime, timezone

if __name__ == '__main__':
    url = 'https://www.cloudflare.com/cdn-cgi/trace'
    with urllib.request.urlopen(url, timeout=15) as response:
        body = response.read(20_000)
    values = dict(line.split('=', 1) for line in body.decode().splitlines() if '=' in line)
    record = dict(observed_at=datetime.now(timezone.utc).isoformat(), provider_url=url,
                  country=values.get('loc', 'unknown'), response_sha256=hashlib.sha256(body).hexdigest(),
                  note='Country reported by Cloudflare for this request; no public IP retained')
    Path('data').mkdir(exist_ok=True)
    Path('data/egress-context.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps(record, indent=2))
