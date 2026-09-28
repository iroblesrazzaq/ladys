"""Extract small inventory tables from the Allen Visual Coding Neuropixels session NWBs.

Reads the S3 ecephys-cache copy (session_<id>/session_<id>.nwb + metadata CSVs) and writes,
to --out:
    sessions.parquet   one row per session (type, mouse, units, spikes, length, sizes, streams)
    units.parquet      one row per unit in the NWB, noise units included (QC metrics, region)
    stimuli.parquet    one row per stimulus presentation; natural movies collapsed to one row
                       per movie repeat, spontaneous kept as blocks
    raster.npz         spikes of one example session around the flash block, for a raster plot

Only unit metadata, spike-time index boundaries and stimulus tables are read; waveforms and
spike amplitudes are never loaded. Sessions are processed in parallel.

    python allen_extract.py --data data --out tables --workers 16
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

# AllenSDK EcephysSessionCache.get_units() defaults
QC = {'isi_violations': 0.5, 'amplitude_cutoff': 0.1, 'presence_ratio': 0.9}
UNIT_COLS = ['firing_rate', 'isi_violations', 'amplitude_cutoff', 'presence_ratio', 'snr',
             'amplitude', 'peak_channel_id']
PARAMS = ['orientation', 'temporal_frequency', 'spatial_frequency', 'contrast', 'color',
          'x_position', 'y_position', 'Dir', 'Speed', 'coherence', 'frame']


def text(a):
    return np.array([x.decode() if isinstance(x, bytes) else str(x) for x in a])


def passes_qc(u):
    return ((u.quality == 'good') & (u.isi_violations < QC['isi_violations'])
            & (u.amplitude_cutoff < QC['amplitude_cutoff']) & (u.presence_ratio > QC['presence_ratio']))


def stimulus_table(f, sid):
    rows = []
    for name, g in f['intervals'].items():
        if not name.endswith('_presentations'):
            continue
        t = pd.DataFrame({'start_time': g['start_time'][:], 'stop_time': g['stop_time'][:]})
        t['stimulus'] = name.removesuffix('_presentations')
        t['block'] = g['stimulus_block'][:] if 'stimulus_block' in g else -1
        for p in PARAMS:
            t[p] = pd.to_numeric(pd.Series(text(g[p][:])), errors='coerce') if p in g else np.nan
        if name.startswith('natural_movie'):
            # one row per frame -> one row per movie repeat (a repeat starts at frame 0)
            rep = (t['frame'] == 0).cumsum()
            t = t.groupby(rep).agg(start_time=('start_time', 'min'), stop_time=('stop_time', 'max'),
                                   stimulus=('stimulus', 'first'), block=('block', 'first'),
                                   frames=('frame', 'size')).reset_index(drop=True)
        rows.append(t)
    t = pd.concat(rows, ignore_index=True).sort_values('start_time', ignore_index=True)
    t.insert(0, 'session_id', sid)
    return t


def session_tables(path, meta):
    path = Path(path)
    sid = int(path.stem.split('_')[1])
    with h5py.File(path, 'r') as f:
        U = f['units']
        idx = U['spike_times_index'][:]
        start = np.concatenate([[0], idx[:-1]])
        n = idx - start
        st = U['spike_times']
        nz = n > 0
        first = np.full(len(n), np.nan)
        last = np.full(len(n), np.nan)
        first[nz] = st[start[nz]]
        last[nz] = st[idx[nz] - 1]
        e = f['general/extracellular_ephys/electrodes']
        loc = pd.Series(text(e['location'][:]), index=e['id'][:])
        depth = pd.Series(e['probe_vertical_position'][:], index=e['id'][:])
        probe = pd.Series(text(e['group_name'][:]), index=e['id'][:])
        u = pd.DataFrame({'session_id': sid, 'unit_id': U['id'][:], 'quality': text(U['quality'][:]),
                          **{c: U[c][:] for c in UNIT_COLS}, 'spike_count': n})
        u['region'] = loc.reindex(u.peak_channel_id).to_numpy()
        u['depth_um'] = depth.reindex(u.peak_channel_id).to_numpy()
        u['probe'] = probe.reindex(u.peak_channel_id).to_numpy()
        u['qc'] = passes_qc(u)
        stim = stimulus_table(f, sid)
        streams = {'running': 'processing/running' in f, 'eye_tracking': 'processing/eye_tracking' in f,
                   'optotagging': 'processing/optotagging' in f}
        invalid = len(f['intervals/invalid_times/start_time']) if 'invalid_times' in f['intervals'] else 0

    m = meta.loc[sid]
    session = {
        'session_id': sid, 'session_type': m.session_type, 'specimen_id': int(m.specimen_id),
        'sex': m.sex, 'age_days': m.age_in_days, 'genotype': m.genotype,
        'probes': u.probe.nunique(), 'units': len(u), 'good_units': int((u.quality == 'good').sum()),
        'qc_units': int(u.qc.sum()), 'spikes': int(n.sum()),
        'recording_s': float(np.nanmax(last) - np.nanmin(first)),
        'stimulus_s': float(stim.stop_time.max() - stim.start_time.min()),
        'invalid_intervals': invalid, 'nwb_bytes': path.stat().st_size,
        **{f'has_{k}': v for k, v in streams.items()}}
    return session, u, stim


def raster(path, window_s=30.0):
    """Spikes of every unit from 5 s before the first flash, for window_s seconds."""
    with h5py.File(path, 'r') as f:
        U = f['units']
        g = f['intervals/flashes_presentations']
        t0 = float(g['start_time'][0]) - 5.0
        flash_on = g['start_time'][:] - t0
        flash_color = pd.to_numeric(pd.Series(text(g['color'][:])), errors='coerce').to_numpy()
        idx = U['spike_times_index'][:]
        st = U['spike_times'][:]
        unit = np.repeat(np.arange(len(idx)), np.diff(np.concatenate([[0], idx])))
        keep = (st >= t0) & (st < t0 + window_s)
        keep_on = flash_on < window_s
        return {'session_id': int(Path(path).stem.split('_')[1]), 't0': t0, 'window_s': window_s,
                'times': st[keep] - t0, 'unit_row': unit[keep], 'unit_id': U['id'][:],
                'flash_on': flash_on[keep_on], 'flash_color': flash_color[keep_on]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=16)
    args = ap.parse_args()

    data = Path(args.data)
    meta = pd.read_csv(data / 'sessions.csv').set_index('id')
    paths = sorted(data.glob('session_*/session_*.nwb'))
    print(f'{len(paths)} session NWBs', flush=True)
    with ProcessPoolExecutor(args.workers) as ex:
        results = list(ex.map(session_tables, paths, [meta] * len(paths)))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sessions = pd.DataFrame([r[0] for r in results])
    sessions.to_parquet(out / 'sessions.parquet')
    pd.concat([r[1] for r in results], ignore_index=True).to_parquet(out / 'units.parquet')
    pd.concat([r[2] for r in results], ignore_index=True).to_parquet(out / 'stimuli.parquet')

    # example raster: the session with the median number of units
    ex_sid = sessions.sort_values('units').iloc[len(sessions) // 2].session_id
    np.savez_compressed(out / 'raster.npz', **raster(data / f'session_{ex_sid}' / f'session_{ex_sid}.nwb'))
    print(f'wrote {out}: {len(sessions)} sessions, {int(sessions.units.sum())} units '
          f'({int(sessions.qc_units.sum())} QC), raster {ex_sid}')


if __name__ == '__main__':
    main()
