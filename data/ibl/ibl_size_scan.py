"""Scan server-side file sizes of every Brainwide Map session (no download).

Writes ibl_bwm_sizes.csv: per session, GB by top-level folder (default revision), all
revisions, and the keep-set parts used by ibl_download.py. Copied to data/ibl_tables/server_sizes.csv.
"""
import re, sys, json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from one.api import ONE
URL = 'https://openalyx.internationalbrainlab.org'
one = ONE(base_url=URL, password='international', silent=True)
eids = [str(e) for e in one.search(tag='Brainwidemap', query_type='remote')]
PR = r'alf/probe\d+[a-z]?/pykilosort/'
SPIKES = PR + r'spikes\.(times|clusters)\.npy'
PASSING = PR + r'passingSpikes\.table\.pqt'
META = [PR + r'clusters\.(metrics\.pqt|channels\.npy|depths\.npy|uuids\.csv)',
        PR + r'channels\.(brainLocationIds_ccf_2017|mlapdv|localCoordinates|rawInd)\.npy',
        r'alf/_ibl_trials\.table\.pqt', r'alf/_ibl_wheel\.(position|timestamps)\.npy', r'alf/licks\.times\.npy',
        r'alf/_ibl_leftCamera\.(times\.npy|lightningPose\.pqt)', r'alf/leftCamera\.ROIMotionEnergy\.npy']
def match(p, pats): return any(re.fullmatch(k, p) for k in pats)
def scan(eid):
    for attempt in range(3):
        try:
            o = ONE(base_url=URL, password='international', silent=True)
            d = o.list_datasets(eid, details=True, query_type='remote')
            break
        except Exception as e:
            err = str(e)
    else:
        return {'eid': eid, 'error': err}
    top = d['rel_path'].str.split('/').str[0]
    dd = d[d['default_revision'] == True]
    p = dd['rel_path'].str.replace(r'#[^#]+#/', '', regex=True)
    gb = lambda mask: float(dd.loc[mask, 'file_size'].sum()) / 1e9
    probes = sorted({m.group(0) for m in p.str.extract(r'(probe\d+[a-z]?)')[0].dropna().map(lambda x: re.match(r'.*', x))})
    return {'eid': eid,
            'all_revisions_GB': float(d['file_size'].sum()) / 1e9,
            'default_GB': gb(slice(None)),
            **{f'{t}_GB': gb(p.str.startswith(t + '/')) for t in ['alf', 'raw_ephys_data', 'raw_video_data', 'raw_passive_data', 'raw_behavior_data', 'spike_sorters', 'logs']},
            'spikes_GB': gb(p.apply(lambda x: match(x, [SPIKES]))),
            'passing_GB': gb(p.apply(lambda x: match(x, [PASSING]))),
            'meta_GB': gb(p.apply(lambda x: match(x, META))),
            'n_probes_pyks': int(p.str.extract(r'alf/(probe\d+[a-z]?)/pykilosort/spikes\.times')[0].nunique()),
            'n_probes_passing': int(p.str.extract(r'alf/(probe\d+[a-z]?)/pykilosort/passingSpikes')[0].nunique()),
            'has_trials': bool((p == 'alf/_ibl_trials.table.pqt').any()),
            'has_lp': bool((p == 'alf/_ibl_leftCamera.lightningPose.pqt').any()),
            'path': str(o.eid2path(eid)).split('ibl/')[-1]}
rows = []
with ThreadPoolExecutor(6) as ex:
    for i, r in enumerate(ex.map(scan, eids)):
        rows.append(r)
        if i % 50 == 0: print(i, flush=True)
df = pd.DataFrame(rows); df.to_csv('ibl_bwm_sizes.csv', index=False)
print('errors', df['error'].notna().sum() if 'error' in df else 0)
