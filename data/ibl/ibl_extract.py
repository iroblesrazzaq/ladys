"""Extract small inventory tables from the downloaded IBL Brainwide Map keep-set.

Reads the ONE cache written by ibl_download.py and writes, to --out:
    sessions.parquet   one row per session (lab, subject, trials, length, sizes, streams)
    probes.parquet     one row per probe insertion (units, spikes, length)
    units.parquet      one row per sorted unit (label, firing rate, region)
    trials.parquet     one row per trial (task variables + BWB trial-QC flag)
    raster.npz         spikes of one example session in a 30 s window, for a raster plot

Spike arrays are memory-mapped and only their first/last samples are read, so memory
stays small. Sessions are processed in parallel.

    python ibl_extract.py --cache data --out tables --workers 16
"""
import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from iblatlas.regions import BrainRegions

BR = BrainRegions()
# BrainWideBench A.4: trials missing any of these events are dropped, then RT > 10 s
BWB_TRIAL_EVENTS = ['stimOn_times', 'probabilityLeft', 'firstMovement_times', 'choice',
                    'feedback_times', 'feedbackType']
TRIAL_COLS = ['contrastLeft', 'contrastRight', 'probabilityLeft', 'choice', 'feedbackType',
              'stimOn_times', 'goCue_times', 'firstMovement_times', 'response_times',
              'feedback_times', 'intervals_0', 'intervals_1']
STREAMS = {'wheel': '_ibl_wheel.position.npy', 'licks': 'licks.times.npy',
           'left_pose': '_ibl_leftCamera.lightningPose.pqt',
           'left_motion_energy': 'leftCamera.ROIMotionEnergy.npy'}


def one_file(folder, name):
    """Path of `name` in folder or its newest revision subfolder (#YYYY-MM-DD#).

    A few datasets have two revisions flagged default on the server (68 of 699 probes carry
    an older copy of clusters.metrics or of the whole probe); the newest one is read.
    """
    hits = sorted(folder.glob(f'#*#/{name}')) or sorted(folder.glob(name))
    return hits[-1] if hits else None


def stale_files(path):
    """Files shadowed by a newer revision of the same dataset in the same collection."""
    seen = {}
    for f in sorted(path.rglob('*')):
        if f.is_file() and f.parent.name.startswith('#'):
            seen.setdefault((f.parent.parent, f.name), []).append(f)
    return [f for fs in seen.values() for f in fs[:-1]]


def bwb_trial_ok(t):
    ok = t[BWB_TRIAL_EVENTS].notna().all(axis=1)
    return ok & ((t['firstMovement_times'] - t['stimOn_times']) <= 10.0)


def session_tables(eid, path):
    path = Path(path)
    alf = path / 'alf'
    lab, _, subject, date, number = path.parts[-5:]
    probes, units, unsorted = [], [], 0
    for pdir in sorted(alf.glob('probe*/pykilosort')):
        probe = pdir.parent.name
        if one_file(pdir, 'spikes.times.npy') is None:
            # CSHL045 2020-02-25/002 probe00: insertion QC CRITICAL, never spike sorted
            unsorted += 1
            continue
        m = pd.read_parquet(one_file(pdir, 'clusters.metrics.pqt'))
        t = np.load(one_file(pdir, 'spikes.times.npy'), mmap_mode='r')
        ch = np.load(one_file(pdir, 'clusters.channels.npy'))
        loc = one_file(pdir, 'channels.brainLocationIds_ccf_2017.npy')
        # locations are fetched for every probe (ibl_download falls back to non-default revisions)
        ids = np.load(loc)[ch] if loc else np.full(len(ch), -1)
        depth = np.load(one_file(pdir, 'clusters.depths.npy'))
        assert len(m) == len(ch) == len(depth)
        u = pd.DataFrame({
            'eid': eid, 'probe': probe, 'cluster_id': m['cluster_id'].to_numpy(),
            'label': m['label'].to_numpy(), 'firing_rate': m['firing_rate'].to_numpy(),
            'spike_count': m['spike_count'].to_numpy(), 'amp_median': m['amp_median'].to_numpy(),
            'depth_um': depth, 'atlas_id': ids,
            **{k: BR.id2acronym(ids, mapping=m) if loc else np.full(len(ch), 'unaligned')
               for k, m in [('region', 'Allen'), ('beryl', 'Beryl'), ('cosmos', 'Cosmos')]}})
        units.append(u)
        probes.append({
            'eid': eid, 'probe': probe, 'aligned': loc is not None, 'units': len(u), 'good_units': int((u.label == 1).sum()),
            'selected_units': int(((u.label == 1) & (u.firing_rate > 1)).sum()),
            'spikes': len(t), 'first_spike_s': float(t[0]), 'last_spike_s': float(t[-1]),
            'spike_bytes': sum(one_file(pdir, f).stat().st_size
                               for f in ['spikes.times.npy', 'spikes.clusters.npy'])})

    tr = pd.read_parquet(one_file(alf, '_ibl_trials.table.pqt'))
    tr = tr.reindex(columns=TRIAL_COLS)
    tr.insert(0, 'eid', eid)
    tr.insert(1, 'trial', np.arange(len(tr)))
    tr['bwb_ok'] = bwb_trial_ok(tr)

    files = [f for f in path.rglob('*') if f.is_file()]
    p = pd.DataFrame(probes)
    u = pd.concat(units, ignore_index=True)
    session = {
        'eid': eid, 'lab': lab, 'subject': subject, 'date': date, 'number': number,
        'probes': len(p), 'unsorted_probes': unsorted, 'units': len(u), 'good_units': int((u.label == 1).sum()),
        'selected_units': int(((u.label == 1) & (u.firing_rate > 1)).sum()),
        'spikes': int(p.spikes.sum()), 'trials': len(tr), 'bwb_trials': int(tr.bwb_ok.sum()),
        'recording_s': float(p.last_spike_s.max() - p.first_spike_s.min()),
        'task_s': float(tr.intervals_1.max() - tr.intervals_0.min()),
        'bytes': sum(f.stat().st_size for f in files), 'spike_bytes': int(p.spike_bytes.sum()),
        'files': len(files), 'stale_files': len(stale := stale_files(path)),
        'stale_bytes': sum(f.stat().st_size for f in stale),
        **{f'has_{k}': one_file(alf, v) is not None for k, v in STREAMS.items()}}
    return session, p, u, tr


def raster(eid, path, window_s=30.0):
    """Spikes of every unit in a window starting at the first stimulus onset."""
    alf = Path(path) / 'alf'
    tr = pd.read_parquet(one_file(alf, '_ibl_trials.table.pqt'))
    t0 = float(np.nanmin(tr['stimOn_times']))
    parts = []
    for pdir in sorted(alf.glob('probe*/pykilosort')):
        t = np.load(one_file(pdir, 'spikes.times.npy'), mmap_mode='r')
        c = np.load(one_file(pdir, 'spikes.clusters.npy'), mmap_mode='r')
        i0, i1 = np.searchsorted(t, [t0, t0 + window_s])
        parts.append((pdir.parent.name, np.asarray(t[i0:i1]) - t0, np.asarray(c[i0:i1])))
    trials = tr[(tr.stimOn_times >= t0) & (tr.stimOn_times < t0 + window_s)]
    return {'eid': eid, 't0': t0, 'window_s': window_s,
            'probe': np.concatenate([np.full(len(t), p) for p, t, _ in parts]),
            'times': np.concatenate([t for _, t, _ in parts]),
            'clusters': np.concatenate([c for _, _, c in parts]),
            'stim_on': trials.stimOn_times.to_numpy() - t0,
            'feedback': trials.feedback_times.to_numpy() - t0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=16)
    args = ap.parse_args()

    log = [json.loads(line) for line in (Path(args.cache) / '_download_log.jsonl').read_text().splitlines()]
    done = {r['eid']: r['path'] for r in log if r.get('missing') == 0}
    eids = sorted(done)
    print(f'{len(eids)} downloaded sessions', flush=True)

    with ProcessPoolExecutor(args.workers) as ex:
        results = list(ex.map(session_tables, eids, [done[e] for e in eids], chunksize=4))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sessions = pd.DataFrame([r[0] for r in results])
    sessions.to_parquet(out / 'sessions.parquet')
    for i, name in [(1, 'probes'), (2, 'units'), (3, 'trials')]:
        pd.concat([r[i] for r in results], ignore_index=True).to_parquet(out / f'{name}.parquet')

    # example raster: the session with the median number of units
    ex_eid = sessions.sort_values('units').iloc[len(sessions) // 2].eid
    np.savez_compressed(out / 'raster.npz', **raster(ex_eid, done[ex_eid]))
    print(f'wrote {out}: {len(sessions)} sessions, {int(sessions.probes.sum())} probes, '
          f'{int(sessions.units.sum())} units, {int(sessions.trials.sum())} trials; raster {ex_eid}')


if __name__ == '__main__':
    main()
