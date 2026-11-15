"""Small reproducible phase-1 sample, never an exhaustive or rights-approving scan."""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yaml
from swiss_iptv.catalog import connect
from swiss_iptv.verify import verify

SAMPLES = {
    'France24.fr': 'https://live.france24.com/hls/live/2037179/F24_FR_HI_HLS/master_500.m3u8',
    'LemanBleu.ch': 'https://naxoo.vedge.infomaniak.com/',
    'LaTele.ch': 'https://latele2.vedge.infomaniak.com/',
    'CanalAlphaJura.ch': 'https://canalalphaju.vedge.infomaniak.com/',
    'CanalAlphaNeuchatel.ch': 'https://canalalpha.vedge.infomaniak.com/',
    'Canal9.ch': 'https://livehd.vedge.infomaniak.com/',
    'RTSInfo.ch': 'https://rtsinfo-d.akamaized.net/out/v1/lsvs/',
    'TV5MondeInfo.fr': 'https://',
    'BX1.be': 'https://',
}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--country', default='unknown', help='Actual confirmed test connection country')
    parser.add_argument('--isp', default='unknown', help='Actual declared test ISP')
    args = parser.parse_args()
    config = yaml.safe_load(Path('config.yaml').read_text(encoding='utf-8'))
    with connect('data/catalog.sqlite') as db:
        for channel, prefix in SAMPLES.items():
            source = db.execute('SELECT id,url FROM sources WHERE channel_id=? AND url LIKE ? ORDER BY url LIMIT 1',
                                (channel, prefix + '%')).fetchone()
            if source:
                print(channel, source['id'], flush=True)
                verify(db, config['verification'], source_id=source['id'], limit=1, country=args.country, isp=args.isp)
            else:
                print(channel, 'No matching candidate; not guessed', flush=True)
        multicast = db.execute("SELECT id FROM sources WHERE channel_id='RTS1.ch' AND protocol IN ('udp','rtp') ORDER BY id LIMIT 1").fetchone()
        if multicast:
            # Intentionally confirms the local-network guard without sending multicast traffic.
            verify(db, config['verification'], source_id=multicast['id'], limit=1)
