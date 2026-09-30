"""Brain coordinates of every IBL Brainwide Map unit, fetched without the bulk download.

For each probe in tables/units.parquet, reads three small alf files from the public server
(clusters.channels, channels.mlapdv, channels.brainLocationIds_ccf_2017; tens of KB per
probe) and writes tables/unit_coords.parquet: one row per unit, in the same order as
units.parquet, with ML / AP / DV in µm from bregma (IBL convention: +ML right, +AP anterior,
+DV dorsal). The atlas IDs of the fetched files must equal units.atlas_id, so the rows line
up with the extracted tables.

    python data/ibl/ibl_coords.py --tables data/ibl/tables
"""
import argparse
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from one.api import ONE

URL = 'https://openalyx.internationalbrainlab.org'
NAMES = ['clusters.channels.npy', 'channels.mlapdv.npy', 'channels.brainLocationIds_ccf_2017.npy']
local = threading.local()
one_lock = threading.Lock()  # ONE rewrites ~/.one params on start; don't start two at once


def newest(datasets):
    """The copy ibl_extract.one_file() reads: newest revision among the default datasets.

    Brain locations fall back to non-default revisions (as in ibl_download.py).
    """
    default = [d for d in datasets if d['default_dataset']] or datasets
    return max(default, key=lambda d: d['revision'] or '')


def fetch(url):
    for attempt in range(3):
        try:
            r = requests.get(url.replace('#', '%23'), timeout=60)  # revision folders are #YYYY-MM-DD#
            r.raise_for_status()
            return np.load(io.BytesIO(r.content))
        except requests.RequestException:
            if attempt == 2:
                raise


def session_coords(eid, probes):
    """{probe: (clusters.channels, channels.mlapdv, channels.brainLocationIds)} for one session."""
    if not hasattr(local, 'one'):
        with one_lock:
            local.one = ONE(base_url=URL, password='international', silent=True)
    found = {}
    for d in local.one.alyx.rest('datasets', 'list', session=eid):
        probe = d['collection'].split('/')[1] if d['collection'].count('/') == 2 else None
        if probe in probes and d['collection'].endswith('/pykilosort') and d['name'] in NAMES:
            found.setdefault((probe, d['name']), []).append(d)
    out = {}
    for probe in probes:
        urls = [next(fr['data_url'] for fr in newest(found[(probe, n)])['file_records']
                     if fr['exists'] and 'amazonaws.com' in (fr['data_url'] or ''))  # public S3 copy
                for n in NAMES]
        out[probe] = [fetch(u) for u in urls]
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tables', default='data/ibl/tables')
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()
    tables = Path(args.tables)
    units = pd.read_parquet(tables / 'units.parquet')
    probes = units.groupby('eid', sort=False).probe.unique()
    with ThreadPoolExecutor(args.workers) as ex:
        files = dict(zip(probes.index, ex.map(session_coords, probes.index, probes)))

    parts = []
    for (eid, probe), u in units.groupby(['eid', 'probe'], sort=False):
        ch, mlapdv, ids = files[eid][probe]
        assert len(ch) == len(u), (eid, probe, len(ch), len(u))
        assert (ids[ch] == u.atlas_id.to_numpy()).all(), (eid, probe, 'atlas IDs differ from units.parquet')
        xyz = mlapdv[ch]
        parts.append(pd.DataFrame({'eid': eid, 'probe': probe, 'cluster_id': u.cluster_id.to_numpy(),
                                   'ml_um': xyz[:, 0], 'ap_um': xyz[:, 1], 'dv_um': xyz[:, 2]}, index=u.index))
    coords = pd.concat(parts).loc[units.index]
    coords.to_parquet(tables / 'unit_coords.parquet', index=False)
    print(f'{len(coords)} units from {len(parts)} probes -> {tables / "unit_coords.parquet"}')


if __name__ == '__main__':
    main()
