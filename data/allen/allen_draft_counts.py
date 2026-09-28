"""Per-QC-unit spike counts in the flash and drifting-grating blocks of the top-4 sessions (by QC units)
of each Allen session type. Used to identify the draft Table 8 sessions (allen_inventory.ipynb, section 4).

Run next to data/ (the S3 copy) and tables/ (allen_extract.py output):
    python allen_draft_counts.py   ->  tables/draft_window_counts.parquet
"""
import h5py, numpy as np, os, pandas as pd, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); from allen_extract import passes_qc, text
s = pd.read_parquet('tables/sessions.parquet'); u = pd.read_parquet('tables/units.parquet')
c = u[u.qc].groupby('session_id').size()
s['qc'] = s.session_id.map(c)
top = s.sort_values('qc', ascending=False).groupby('session_type').head(4)
rows = []
for sid, typ in zip(top.session_id, top.session_type):
    with h5py.File(f'data/session_{sid}/session_{sid}.nwb', 'r') as f:
        U = f['units']; idx = U['spike_times_index'][:]; st = U['spike_times']
        ids = U['id'][:]; start = np.concatenate([[0], idx[:-1]])
        qcids = set(u[(u.session_id == sid) & u.qc].unit_id)
        fl = f['intervals/flashes_presentations']; fs = fl['start_time'][:]
        blocks = {'flash': (fs, 2.0)}
        for name in ['drifting_gratings', 'drifting_gratings_75_repeats']:
            if f'intervals/{name}_presentations' in f:
                g = f[f'intervals/{name}_presentations']
                blocks['dg'] = (g['start_time'][:], 2.0)
        for i, uid in enumerate(ids):
            if uid not in qcids: continue
            t = st[start[i]:idx[i]]
            r = {'session_id': sid, 'type': typ, 'unit_id': uid}
            for b, (on, w) in blocks.items():
                lo = np.searchsorted(t, on); hi = np.searchsorted(t, on + w)
                r[f'{b}_spikes'] = int((hi - lo).sum()); r[f'{b}_trials_with_spike'] = int((hi > lo).sum())
                r[f'{b}_s'] = len(on) * w
            rows.append(r)
pd.DataFrame(rows).to_parquet('tables/draft_window_counts.parquet'); print(len(rows))
