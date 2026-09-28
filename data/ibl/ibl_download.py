"""Download the IBL Brainwide Map keep-set (sorted spikes + unit QC + behavior).

Only default-revision files from alf/ are fetched; raw ephys, raw video, waveforms and
old spike-sorting revisions are skipped. Safe to rerun: finished sessions are logged
to <cache>/_download_log.jsonl and skipped, and ONE skips files already on disk.

    TQDM_DISABLE=1 python ibl_download.py --cache /big/disk/ibl --units all
    python ibl_download.py --cache /big/disk/ibl --limit 5      # pilot
"""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
from one.api import ONE

URL = 'https://openalyx.internationalbrainlab.org'
PROBE = r'alf/probe\d+[a-z]?/pykilosort/'

# spikes of units with IBL label == 1 only (~3x smaller than all units)
GOOD_SPIKES = [PROBE + r'passingSpikes\.table\.pqt']
ALL_SPIKES = [PROBE + r'spikes\.(times|clusters)\.npy']
LOCATIONS = r'channels\.(?:brainLocationIds_ccf_2017|mlapdv)\.npy'
META = [
    PROBE + r'clusters\.(metrics\.pqt|channels\.npy|depths\.npy|uuids\.csv)',
    PROBE + r'channels\.(brainLocationIds_ccf_2017|mlapdv|localCoordinates|rawInd)\.npy',
    r'alf/_ibl_trials\.table\.pqt',
    r'alf/_ibl_wheel\.(position|timestamps)\.npy',
    r'alf/licks\.times\.npy',
    r'alf/_ibl_leftCamera\.(times\.npy|lightningPose\.pqt)',
    r'alf/leftCamera\.ROIMotionEnergy\.npy',
]


def connect(cache):
    return ONE(base_url=URL, password='international', silent=True, cache_dir=cache)


def keep_set(one, eid, units):
    everything = one.list_datasets(eid, details=True, query_type='remote')
    d = everything[everything['default_revision'] == True]
    path = d['rel_path'].str.replace(r'#[^#]+#/', '', regex=True)
    pats = META + (ALL_SPIKES if units == 'all' else GOOD_SPIKES)
    keep = d[path.apply(lambda p: any(re.fullmatch(k, p) for k in pats))]
    # some probes have channel locations only in a revision not flagged default: take the newest
    have = set(path[path.str.fullmatch(PROBE + LOCATIONS)].str.extract(r'alf/(probe\w+)/')[0])
    rest = everything[everything['rel_path'].str.contains(PROBE + r'(?:#[^#]+#/)?' + LOCATIONS)]
    rest = rest[~rest['rel_path'].str.extract(r'alf/(probe\w+)/')[0].isin(have)]
    if len(rest):
        name = rest['rel_path'].str.replace(r'#[^#]+#/', '', regex=True)
        rev = rest['rel_path'].str.extract(r'#([^#]+)#')[0].fillna('')
        newest = rest.assign(n=name, r=rev).sort_values('r').groupby('n').tail(1)
        keep = pd.concat([keep, newest.drop(columns=['n', 'r'])])
    if units == 'good':
        # fall back to all-unit spikes for any probe without passingSpikes
        has = set(path.str.extract(r'alf/(probe\w+)/pykilosort/passingSpikes')[0].dropna())
        spk = path.str.extract(r'alf/(probe\w+)/pykilosort/spikes\.(?:times|clusters)\.npy')[0]
        keep = pd.concat([keep, d[spk.notna() & ~spk.isin(has)]])
    return keep


def download(cache, eid, units):
    one = connect(cache)
    t = time.time()
    keep = keep_set(one, eid, units)
    files = one._check_filesystem(keep)
    missing = sum(f is None for f in files)
    return {'eid': eid, 'files': len(keep), 'GB': round(float(keep['file_size'].sum()) / 1e9, 3),
            'missing': missing, 'seconds': round(time.time() - t), 'path': str(one.eid2path(eid))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', required=True)
    ap.add_argument('--units', choices=['good', 'all'], default='all')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--recheck', action='store_true', help='re-list sessions already in the log')
    args = ap.parse_args()

    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    log = cache / '_download_log.jsonl'
    done = set()
    if log.exists() and not args.recheck:
        done = {r['eid'] for r in map(json.loads, log.read_text().splitlines()) if r.get('missing') == 0}

    eids = sorted(str(e) for e in connect(cache).search(tag='Brainwidemap', query_type='remote'))
    todo = [e for e in eids if e not in done][:args.limit]
    print(f'{len(eids)} BWM sessions, {len(done)} done, {len(todo)} to download', flush=True)

    with ThreadPoolExecutor(args.workers) as ex, log.open('a') as f:
        futures = {ex.submit(download, cache, e, args.units): e for e in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                r = fut.result()
            except Exception as err:
                r = {'eid': futures[fut], 'error': repr(err)[:300]}
            f.write(json.dumps(r) + '\n')
            f.flush()
            print(f'[{i}/{len(todo)}]', r, flush=True)


if __name__ == '__main__':
    main()
